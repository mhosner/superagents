# Phase 5: QA Persona + StubLLMClient Strict Mode — Design Spec

**Date:** 2026-03-19

**Goal:** Complete the SDLC persona chain by adding a QA persona with
compliance checking and validation reporting, positioned after Developer
in the pipeline. Add StubLLMClient strict mode for better test diagnostics.

**Dependencies:** Phases 1-4 must be complete (118 tests passing).

**Spec author:** Claude (brainstormed with human)

---

## Strategic Context

Phase 4 proved the PM → Architect → Developer pipeline with full telemetry
and autonomy policy enforcement. Phase 5 adds the final persona (QA) to
complete the governance story: every SDLC role has a persona, every action
emits spans, and every handoff passes through approval gates.

The QA persona implements a "default to skepticism" philosophy inspired by
agency-agents' testing-reality-checker and testing-evidence-collector patterns.
It validates the entire upstream chain (user stories through code plan) rather
than just checking adjacent-hop output.

Phase 5 does NOT include an execution bridge (code generation) or Harbor eval
integration. Those are Phase 6+ concerns. Phase 5's value is the complete
governance chain with end-to-end validation.

---

## Design Decisions (Final)

### D1: Pipeline Placement — After Developer

```
PM → Architect → Developer → QA (terminal)
```

QA receives from Developer but validates against the entire upstream chain:
user stories (PM), tech spec (Architect), implementation plan (Architect),
and code plan (Developer). The metadata dict propagates all artifact paths.

QA is the terminal node — no outbound handoff. The validation report is the
final output for human review.

**Why not between Architect and Developer:** Would require multi-source handoffs
(Developer receiving from both Architect and QA). Not built, not needed yet.

**Why not parallel with Developer:** Requires parallel dispatch infrastructure.
Deferred to future phases.

### D2: Two Skills — SpecComplianceChecker + ValidationReportGenerator

- **SpecComplianceChecker** — Line-by-line gap analysis. "Default to NEEDS WORK."
  Structured PASS/FAIL per requirement. Minimum 3-5 issues even on solid plans.
- **ValidationReportGenerator** — Readiness certification. FAILED / NEEDS WORK / READY.
  The artifact a human QA lead reviews.

**Why not AcceptanceSpecWriter:** The UserStoryWriter (PM persona, Phase 3) already
produces BDD acceptance criteria (Given/When/Then). Rewriting them is redundant.
Can be added in a future phase if PM output proves insufficient.

### D3: Artifact Types — Explicit Classification

Both QA artifact types require approval at Level 2:
- `"compliance_report"` → added to APPROVAL_REQUIRED_TYPES
- `"validation_report"` → added to APPROVAL_REQUIRED_TYPES

`CODE_ARTIFACT_TYPES` is renamed to `APPROVAL_REQUIRED_TYPES` because the set
now contains code, test, migration, compliance_report, and validation_report —
calling it "code artifact types" is misleading.

### D4: Developer Conditional Handoff — via Transport.can_reach()

The Developer's `run_plan_from_spec` hands off to QA only if QA is reachable.
Pre-check via `self.transport.can_reach("qa")` before calling `request_handoff`.

**Why not try/except KeyError:** `request_handoff` opens handoff_span and
approval_gate_span before the registry lookup fails. Catching KeyError would
leave orphaned governance traces in telemetry for a handoff that was never
delivered.

**Protocol extension:** `can_reach(target: str) -> bool` is added to the
Transport Protocol. This is a legitimate transport concern — "can you deliver
to this target?" Every implementation has a natural answer: registry lookup
for InProcessTransport, endpoint ping for future A2ATransport.

### D5: Developer Path Forwarding

The Developer's `handle_handoff` stores file paths alongside content in
`context.parameters` so they can be forwarded to QA via metadata:

```python
context.parameters["tech_spec"] = file_contents      # for skill execution
context.parameters["tech_spec_path"] = path_string    # for metadata forwarding
```

The `_path` suffix convention distinguishes content from path references.

### D6: StubLLMClient Strict Mode

`StubLLMClient(responses={...}, strict=True)` raises `ValueError` when no
key matches the prompt. Default `strict=False` preserves backward compatibility.
Prevents silent empty responses that cause confusing "empty artifact" test failures.

---

## Module Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/superagents_sdlc/skills/qa/__init__.py` | Re-exports: SpecComplianceChecker, ValidationReportGenerator |
| `src/superagents_sdlc/skills/qa/spec_compliance_checker.py` | Gap analysis skill |
| `src/superagents_sdlc/skills/qa/validation_report_generator.py` | Readiness certification skill |
| `src/superagents_sdlc/personas/qa.py` | QAPersona |
| `tests/unit_tests/test_skills/test_qa/__init__.py` | Test package |
| `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py` | Compliance checker tests |
| `tests/unit_tests/test_skills/test_qa/test_validation_report_generator.py` | Validation report tests |
| `tests/unit_tests/test_personas/test_qa.py` | QA persona tests |

### Modified Files

| File | Change |
|------|--------|
| `src/superagents_sdlc/skills/llm.py` | Add `strict` parameter to StubLLMClient |
| `src/superagents_sdlc/policy/engine.py` | Rename CODE_ARTIFACT_TYPES → APPROVAL_REQUIRED_TYPES, add 2 types |
| `src/superagents_sdlc/handoffs/transport.py` | Add `can_reach` to Transport Protocol + InProcessTransport |
| `src/superagents_sdlc/personas/developer.py` | Conditional handoff to QA, path forwarding in metadata |
| `src/superagents_sdlc/personas/__init__.py` | Add QAPersona re-export |
| `tests/unit_tests/test_skills/test_llm.py` | Add strict mode tests |
| `tests/unit_tests/test_handoffs/test_transport.py` | Add can_reach tests |
| `tests/unit_tests/test_policy/test_engine.py` | Add approval-required tests for new types |
| `tests/unit_tests/test_personas/test_developer.py` | Add conditional handoff test |
| `tests/unit_tests/test_personas/test_pipeline.py` | Add 4-persona pipeline tests |

Note: `src/superagents_sdlc/skills/__init__.py` is NOT modified. QA skills are
imported directly from `superagents_sdlc.skills.qa`, matching the pattern used
by `superagents_sdlc.skills.engineering` (subpackages have their own namespace).

---

## Detailed Behavior

### StubLLMClient Strict Mode (skills/llm.py)

Note: existing code uses `self._responses` (private) and `*` keyword-only
separator on `responses`. The `strict` parameter is added after `responses`.

```python
class StubLLMClient:
    def __init__(
        self, *, responses: dict[str, str], strict: bool = False
    ) -> None:
        self._responses = responses
        self._strict = strict
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, *, system: str = "") -> str:
        self.calls.append((prompt, system))
        for key, response in self._responses.items():
            if key in prompt:
                return response
        if self._strict:
            msg = f"No response matched prompt: {prompt[:100]}"
            raise ValueError(msg)
        return ""
```

### Policy Engine Rename (policy/engine.py)

Before:
```python
CODE_ARTIFACT_TYPES: frozenset[str] = frozenset({
    "code", "test", "migration",
})
```

After:
```python
APPROVAL_REQUIRED_TYPES: frozenset[str] = frozenset({
    "code", "test", "migration",
    "compliance_report", "validation_report",
})
```

All references to `CODE_ARTIFACT_TYPES` within engine.py updated to
`APPROVAL_REQUIRED_TYPES`. No external references exist (verified via grep).

### Transport Protocol Extension (handoffs/transport.py)

```python
class Transport(Protocol):
    async def send(self, handoff: PersonaHandoff) -> HandoffResult: ...
    def can_reach(self, target: str) -> bool: ...

class InProcessTransport:
    def __init__(self, *, registry: PersonaRegistry) -> None:
        self._registry = registry

    def can_reach(self, target: str) -> bool:
        try:
            self._registry.get(target)
            return True
        except KeyError:
            return False

    async def send(self, handoff: PersonaHandoff) -> HandoffResult:
        # ... existing implementation unchanged ...
```

### SpecComplianceChecker (skills/qa/spec_compliance_checker.py)

- **name:** `"spec_compliance_checker"`
- **description:** `"Line-by-line gap analysis between specifications and implementation artifacts, defaulting to skepticism"`
- **required_context:** `["code_plan", "user_stories", "tech_spec"]`
- **Optional context:** `"implementation_plan"`, `"prd"`

**validate():** Checks the three required keys. Raises SkillValidationError
with the missing key name.

**execute():**
1. Compose prompt from code_plan, user_stories, tech_spec (plus optional context).
2. System prompt establishes QA reviewer role:
   - For each user story / spec requirement:
     - Quote exact spec text
     - Quote corresponding code plan section (or note if missing)
     - Verdict: PASS / FAIL / PARTIAL
   - Minimum 3-5 issues — identify risks, gaps, ambiguities even on solid plans
   - Automatic FAIL triggers:
     - Requirements with no corresponding implementation task
     - Implementation tasks with no corresponding requirement
     - Vague acceptance criteria without concrete verification
   - Summary: total checks, pass/fail counts, overall PASS/NEEDS WORK/FAIL
3. Write to `context.artifact_dir / "compliance_report.md"`.
4. Return `Artifact(path=..., artifact_type="compliance_report",
   metadata={"framework": "spec_compliance"})`.

### ValidationReportGenerator (skills/qa/validation_report_generator.py)

- **name:** `"validation_report_generator"`
- **description:** `"Generate a structured readiness certification with honest quality ratings and required fixes"`
- **required_context:** `["compliance_report", "code_plan", "user_stories"]`
- **Optional context:** `"tech_spec"`, `"implementation_plan"`, `"prd"`

**validate():** Checks the three required keys.

**execute():**
1. Compose prompt from compliance_report, code_plan, user_stories (plus optional).
2. System prompt establishes senior QA lead role:
   - Executive summary (one paragraph)
   - Compliance results summary
   - Risk assessment
   - Required fixes (must-fix before proceeding)
   - Recommended improvements (nice-to-have)
   - Certification: FAILED / NEEDS WORK / READY
     - Default rating is NEEDS WORK
     - READY requires overwhelming evidence of coverage
     - No A+ fantasies on first attempts
3. Write to `context.artifact_dir / "validation_report.md"`.
4. Return `Artifact(path=..., artifact_type="validation_report",
   metadata={"certification": extract_certification(response)})`.

`_extract_certification()` is a module-level private function. It scans for
FAILED/NEEDS WORK/READY in response. Default to `"unknown"` if parsing fails.
Simple string search — the system prompt ensures the LLM produces one of the
three values.

### QAPersona (personas/qa.py)

**Constructor:** `llm`, `policy_engine`, `transport` — keyword-only.

Skills:
- `"spec_compliance_checker"`: `SpecComplianceChecker(llm=llm)`
- `"validation_report_generator"`: `ValidationReportGenerator(llm=llm)`

Calls `super().__init__(name="qa", skills=..., ...)`.

**receive_handoff(handoff):** Stores in `self.received`, logs.

**run_validation(context) -> list[Artifact]:**
1. Pre-flight: verify `"code_plan"`, `"user_stories"`, `"tech_spec"` in
   `context.parameters`. Raise `SkillValidationError` if missing.
2. `with persona_span("qa", autonomy_level=level):`
3. Execute `spec_compliance_checker` → compliance artifact
4. Read compliance content, set `context.parameters["compliance_report"]`
5. Execute `validation_report_generator` → validation artifact
6. Return `[compliance_artifact, validation_artifact]`

**handle_handoff(handoff, context) -> list[Artifact]:**
1. Read code plan from `handoff.artifact_path` → `context.parameters["code_plan"]`
2. Read from metadata (required):
   - `"tech_spec_path"` → `context.parameters["tech_spec"]`
   - `"user_stories_path"` → `context.parameters["user_stories"]`
3. Read from metadata (optional, if path non-empty and file exists):
   - `"implementation_plan_path"` → `context.parameters["implementation_plan"]`
   - `"prd_path"` → `context.parameters["prd"]`
4. Call `run_validation(context)`

### Developer Persona Modification (personas/developer.py)

**handle_handoff changes:**

Store paths alongside content when reading from metadata:
```python
context.parameters["implementation_plan_path"] = handoff.artifact_path
# ... after reading tech_spec:
context.parameters["tech_spec_path"] = tech_spec_path
# ... after reading optional paths:
context.parameters["user_stories_path"] = handoff.metadata.get("user_stories_path", "")
context.parameters["prd_path"] = handoff.metadata.get("prd_path", "")
```

**run_plan_from_spec changes:**

After executing code_planner, add conditional handoff:
```python
with persona_span(self.name, autonomy_level=level):
    code_plan_artifact = await self.execute_skill("code_planner", context)

    if self.transport.can_reach("qa"):
        await self.request_handoff(
            target="qa",
            artifact=code_plan_artifact,
            context_summary="Code plan ready for compliance review",
            metadata={
                "tech_spec_path": context.parameters.get("tech_spec_path", ""),
                "user_stories_path": context.parameters.get("user_stories_path", ""),
                "implementation_plan_path": context.parameters.get(
                    "implementation_plan_path", ""
                ),
                "prd_path": context.parameters.get("prd_path", ""),
            },
        )

return [code_plan_artifact]
```

---

## Test Plan — 28 Tests

### test_llm.py additions (2 tests)

1. `test_stub_llm_strict_raises_on_no_match` — strict=True, unmatched prompt
   raises ValueError with prompt excerpt in message
2. `test_stub_llm_strict_still_matches_normally` — strict=True, matched prompt
   returns response (strict doesn't break normal matching)

### test_transport.py additions (2 tests)

3. `test_transport_can_reach_registered` — returns True for registered persona
4. `test_transport_can_reach_unknown` — returns False for unregistered name

### test_engine.py additions (2 tests)

5. `test_compliance_report_requires_approval_at_level_2` — handoff with
   artifact_type="compliance_report" at Level 2 triggers approval gate
6. `test_validation_report_requires_approval_at_level_2` — handoff with
   artifact_type="validation_report" at Level 2 triggers approval gate

Note: QA artifacts don't go through evaluate_handoff in the current architecture
(QA has no outbound handoff). These tests verify the classification is correct
as forward-looking infrastructure, so the gate behavior is ready when a downstream
consumer of QA artifacts is added.

### test_spec_compliance_checker.py (5 tests)

7. `test_compliance_validate_passes` — code_plan, user_stories, tech_spec present
8. `test_compliance_validate_fails_missing_code_plan` — raises SkillValidationError
9. `test_compliance_validate_fails_missing_user_stories` — raises SkillValidationError
10. `test_compliance_execute_writes_artifact` — file exists, artifact_type == "compliance_report"
11. `test_compliance_execute_includes_context_in_prompt` — code plan, user stories,
    tech spec all appear in the prompt

### test_validation_report_generator.py (5 tests)

12. `test_validation_validate_passes` — compliance_report, code_plan, user_stories present
13. `test_validation_validate_fails_missing_compliance` — raises SkillValidationError
14. `test_validation_validate_fails_missing_code_plan` — raises SkillValidationError
15. `test_validation_execute_writes_artifact` — file exists, artifact_type == "validation_report"
16. `test_validation_execute_includes_context_in_prompt` — compliance report and
    code plan appear in prompt

### test_qa.py (6 tests)

17. `test_qa_has_two_skills` — spec_compliance_checker, validation_report_generator
18. `test_qa_receive_handoff_stores` — handoff stored in self.received
19. `test_qa_workflow_runs_two_skills_in_order` — via StubLLMClient.calls order
20. `test_qa_workflow_returns_two_artifacts` — [compliance_report, validation_report]
21. `test_qa_workflow_emits_persona_span` — persona.qa span parents skill spans
22. `test_qa_preflight_fails_missing_context` — SkillValidationError for missing
    code_plan (tests pre-flight, not skill validate)

### test_developer.py addition (1 test)

23. `test_developer_conditional_handoff_to_qa` — Register stub QA in registry,
    run run_plan_from_spec, verify QA received handoff with metadata containing
    tech_spec_path, user_stories_path, implementation_plan_path, prd_path

### test_pipeline.py additions (5 tests)

Full stack: PM → Architect → Developer → QA. Real PolicyEngine, real transport,
StubLLMClient throughout.

The pipeline helper `_run_full_pipeline` is extended to include QA:

```python
async def _run_full_pipeline(tmp_path, pm, architect, developer, qa):
    # PM phase (same as Phase 4)
    pm_artifacts = await pm.run_idea_to_sprint("Add dark mode", pm_context)

    # Adapter: mount PM outputs into Architect context
    prd_content = Path(pm_artifacts[1].path).read_text()
    arch_context = SkillContext(
        artifact_dir=tmp_path / "architect",
        parameters={"prd": prd_content, "product_context": "B2B SaaS"},
        trace_id="trace-pipeline",
    )
    arch_handoff = architect.received[-1]
    arch_artifacts = await architect.handle_handoff(arch_handoff, arch_context)

    # Developer: handle handoff from architect
    dev_context = SkillContext(
        artifact_dir=tmp_path / "developer", parameters={}, trace_id="trace-pipeline",
    )
    dev_handoff = developer.received[-1]
    dev_artifacts = await developer.handle_handoff(dev_handoff, dev_context)

    # QA: handle handoff from developer (new in Phase 5)
    qa_context = SkillContext(
        artifact_dir=tmp_path / "qa", parameters={}, trace_id="trace-pipeline",
    )
    qa_handoff = qa.received[-1]
    qa_artifacts = await qa.handle_handoff(qa_handoff, qa_context)

    return pm_artifacts, arch_artifacts, dev_artifacts, qa_artifacts
```

24. `test_pipeline_pm_to_qa` — Run all four workflows in sequence, verify 8
    artifacts total (3 PM + 2 Architect + 1 Developer + 2 QA), types =
    [backlog, prd, user_story, tech_spec, implementation_plan, code,
    compliance_report, validation_report]
25. `test_pipeline_emits_four_persona_spans` — product_manager, architect,
    developer, qa
26. `test_pipeline_handoff_chain` — three handoff spans: pm→architect,
    architect→developer, developer→qa
27. `test_pipeline_level_2_code_handoff_requires_approval` — The Developer→QA
    handoff carries artifact_type="code", which requires approval at Level 2.
    The PM→Architect and Architect→Developer handoffs carry planning artifacts
    and auto-proceed. Verify via approval_gate_span attributes.
28. `test_pipeline_metadata_reaches_qa` — After QA's handle_handoff, verify
    context.parameters contains tech_spec, user_stories loaded from metadata
    paths (proves the full metadata chain from Architect through Developer to QA)

### Running total: 118 + 28 = 146 tests

---

## Implementation Order

1. StubLLMClient strict mode (2 tests)
2. Policy engine rename + new types + engine tests (2 tests)
3. Transport can_reach (2 tests)
4. SpecComplianceChecker skill (5 tests)
5. ValidationReportGenerator skill (5 tests)
6. QAPersona (6 tests)
7. Developer modification: conditional handoff + path forwarding (1 test)
8. Pipeline integration tests (5 tests)
9. Re-exports + final verification
