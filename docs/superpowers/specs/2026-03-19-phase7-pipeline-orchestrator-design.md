# Phase 7: Pipeline Orchestrator — Design Spec

**Date:** 2026-03-19

**Goal:** Replace the test helper `_run_full_pipeline` with a real
`PipelineOrchestrator` class that owns persona sequencing, context
management, and artifact directory layout. Provides named workflow
methods that CLI and Harbor eval can call directly.

**Dependencies:** Phases 1-6 must be complete (156 tests passing).

**Spec author:** Claude (brainstormed with human)

---

## Strategic Context

The SDLC pipeline (PM → Architect → Developer → QA) works end-to-end
in tests, but running it requires ~40 lines of adapter code per test
helper: creating SkillContexts, reading artifacts, populating parameters,
calling `handle_handoff`. The orchestrator extracts this into a reusable
class with a clean API. CLI calls `orchestrator.run_idea_to_code("Add dark mode")`
instead of replicating adapter glue. Harbor eval calls the same interface.

---

## Design Decisions (Final)

### D1: Named Workflow Methods, Not Configurable Pipelines

The orchestrator has explicit methods per workflow:
- `run_idea_to_code(idea, ...)` — full chain: PM → Architect → Developer → QA
- `run_spec_from_prd(prd_path, ...)` — from PRD: Architect → Developer → QA
- `run_plan_from_spec(implementation_plan_path, tech_spec_path, ...)` — from spec: Developer → QA

Each has a different input contract reflected in its signature. No generic
`run(workflow, start_from, inputs)` pattern — that hides varying contracts
behind a dict and pushes validation to runtime.

**Why not configurable pipelines:** The adapter logic between personas is
genuinely different at each transition. PM needs `idea` + context files,
Architect needs `prd` from PM output, Developer and QA use `handle_handoff`.
A step-definition DSL would need to encode these differences, adding
complexity for a use case we don't have yet. YAGNI.

### D2: Orchestrator Owns Sequencing, Personas Own Skills

The orchestrator calls persona workflow methods and `handle_handoff` in
the right order. Personas don't know about the pipeline — they execute
their skills and emit handoffs. The orchestrator reads handoffs from
`persona.received` and passes them to the next persona's `handle_handoff`.

### D3: Constructor Context + Call-Time Overrides

The orchestrator is "this pipeline configured for this project." Context
files (`product_context`, `goals_context`, `personas_context`) are set at
construction time and reused across runs. Each `run_*` call accepts
optional `context_overrides: dict[str, str]` that merge over the base
context via simple dict update.

```python
orchestrator = PipelineOrchestrator(
    llm=llm,
    policy_engine=engine,
    context={"product_context": "...", "goals_context": "...", "personas_context": "..."},
)

# Normal — uses constructor context
await orchestrator.run_idea_to_code("Add dark mode", artifact_dir=tmp_path)

# Override — merges with constructor context
await orchestrator.run_idea_to_code(
    "Add dark mode",
    artifact_dir=tmp_path,
    context_overrides={"personas_context": "different personas"},
)
```

### D4: PipelineResult with Per-Persona Grouping + Certification

```python
@dataclass
class PipelineResult:
    artifacts: list[Artifact]       # all artifacts in pipeline order
    pm: list[Artifact]              # empty if PM was skipped
    architect: list[Artifact]       # empty if Architect was skipped
    developer: list[Artifact]       # empty if Developer was skipped
    qa: list[Artifact]              # empty if QA was skipped
    certification: str              # "READY"/"NEEDS WORK"/"FAILED"/"skipped"
```

`certification` is read from `qa[-1].metadata["certification"]` if QA ran,
else `"skipped"`. Promotes the most important pipeline signal to the result
so CLI and Harbor eval don't parse artifact metadata.

### D5: Transport Is Internal

The orchestrator creates `PersonaRegistry` and `InProcessTransport`
internally. The caller provides `llm` and `policy_engine` — they control
*what* the personas do (LLM behavior) and *how much autonomy* they have
(approval gates). Transport is an implementation detail of in-process
persona communication.

```python
def __init__(self, *, llm: LLMClient, policy_engine: PolicyEngine, context: dict[str, str]) -> None:
    self._context = dict(context)
    self._registry = PersonaRegistry()
    self._transport = InProcessTransport(registry=self._registry)
    # Create and register all four personas...
```

All four personas are created eagerly in the constructor. This means all
persona modules are import-time dependencies. Acceptable for Phase 7 —
if persona construction becomes expensive later, add lazy initialization.

### D6: Orchestrator Owns Artifact Directory Layout

The orchestrator creates subdirectories per persona: `artifact_dir / "pm"`,
`artifact_dir / "architect"`, etc. Only creates directories for personas
that actually run in the workflow. The caller provides `artifact_dir` —
the orchestrator manages the internal structure.

### D7: Handoff Source Assertions

The orchestrator asserts handoff source when reading from `persona.received`:

```python
handoff = self._architect.received[-1]
assert handoff.source_persona == "product_manager"
```

This catches the failure mode where `received[-1]` isn't the handoff we
just triggered. In the current synchronous in-process model this can't
happen, but the assertion makes the implicit contract explicit and guards
against future changes (retry logic, error recovery, async dispatch).

### D8: Telemetry Asymmetry on Mid-Pipeline Entry

Handoff spans reflect actual inter-persona transitions. Entry points that
skip upstream personas produce fewer handoff spans:

- `run_idea_to_code`: 3 handoff spans (pm→arch, arch→dev, dev→qa)
- `run_spec_from_prd`: 2 handoff spans (arch→dev, dev→qa) — Architect starts cold
- `run_plan_from_spec`: 1 handoff span (dev→qa) — Developer starts cold

This is intentional. Harbor eval and CLI must not assume every pipeline
run has the same span shape.

### D9: Handoff Rejection Not Supported in Phase 7

If a handoff is rejected by the policy engine (e.g., `MockApprovalGate(should_approve=False)`),
`request_handoff` returns `HandoffResult(status="rejected")` and the target
persona's `receive_handoff` is never called. The orchestrator's `received[-1]`
would then raise `IndexError`. Phase 7 does not handle this — callers must
use `AutoApprovalGate` or `MockApprovalGate(should_approve=True)`. Rejection
handling (partial results, retry, escalation) is deferred to a future phase.

### D10: QA Handle_Handoff — User Stories Optional for Mid-Pipeline

QA's `handle_handoff` currently requires `user_stories_path` in metadata.
This fails when entering mid-pipeline (Developer starts cold, no PM output
to provide user stories). Change: make `user_stories_path` optional with
the same graceful pattern as `implementation_plan_path` and `prd_path`.

QA's `run_validation` pre-flight still requires `user_stories` in context
parameters. The orchestrator is responsible for providing user stories
through one of:
- Normal pipeline: metadata chain from PM through Architect and Developer
- `run_plan_from_spec`: optional `user_stories_path` parameter loaded by
  the orchestrator into Developer context

If user stories are unavailable (caller didn't provide them), QA's
pre-flight fails fast with a clear error.

---

## Module Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/superagents_sdlc/workflows/__init__.py` | Re-exports: PipelineOrchestrator, PipelineResult |
| `src/superagents_sdlc/workflows/result.py` | PipelineResult dataclass |
| `src/superagents_sdlc/workflows/orchestrator.py` | PipelineOrchestrator class |
| `tests/unit_tests/test_workflows/__init__.py` | Test package |
| `tests/unit_tests/test_workflows/test_result.py` | PipelineResult tests |
| `tests/unit_tests/test_workflows/test_orchestrator.py` | Orchestrator workflow tests |

### Modified Files

| File | Change |
|------|--------|
| `src/superagents_sdlc/personas/qa.py` | Make `user_stories_path` optional in `handle_handoff` |
| `tests/unit_tests/test_personas/test_qa.py` | Add test for optional user stories in handle_handoff |

---

## Detailed Behavior

### PipelineResult (`workflows/result.py`)

```python
from __future__ import annotations

from dataclasses import dataclass, field

from superagents_sdlc.skills.base import Artifact


@dataclass
class PipelineResult:
    """Result of a pipeline workflow execution.

    Groups artifacts by persona and promotes the QA certification to
    a top-level field for easy access by CLI and evaluation harnesses.

    Attributes:
        artifacts: All artifacts in pipeline order.
        pm: PM persona artifacts (empty if skipped).
        architect: Architect persona artifacts (empty if skipped).
        developer: Developer persona artifacts (empty if skipped).
        qa: QA persona artifacts (empty if skipped).
        certification: QA certification or "skipped" if QA didn't run.
    """

    artifacts: list[Artifact] = field(default_factory=list)
    pm: list[Artifact] = field(default_factory=list)
    architect: list[Artifact] = field(default_factory=list)
    developer: list[Artifact] = field(default_factory=list)
    qa: list[Artifact] = field(default_factory=list)
    certification: str = "skipped"
```

### PipelineOrchestrator (`workflows/orchestrator.py`)

**Constructor:**

```python
class PipelineOrchestrator:
    def __init__(
        self,
        *,
        llm: LLMClient,
        policy_engine: PolicyEngine,
        context: dict[str, str],
    ) -> None:
```

Creates `PersonaRegistry`, `InProcessTransport`, all four personas.
Stores `context` as defensive copy.

**`run_idea_to_code`:**

```python
async def run_idea_to_code(
    self,
    idea: str,
    *,
    artifact_dir: Path,
    context_overrides: dict[str, str] | None = None,
) -> PipelineResult:
```

Full chain: PM → Architect → Developer → QA.

1. Merge context: `ctx = {**self._context, **(context_overrides or {})}`
2. Create `artifact_dir / "pm"`, build SkillContext with `ctx`
3. `pm_artifacts = await self._pm.run_idea_to_sprint(idea, pm_context)`
4. Find PRD artifact: `prd_artifact = _find_artifact(pm_artifacts, "prd")`
5. Create `artifact_dir / "architect"`, build context with `prd` content +
   `prd_path` (from artifact path) + `product_context`

`_find_artifact` is a private helper:
```python
def _find_artifact(artifacts: list[Artifact], artifact_type: str) -> Artifact:
    for a in artifacts:
        if a.artifact_type == artifact_type:
            return a
    msg = f"No artifact of type '{artifact_type}' found"
    raise ValueError(msg)
```

This avoids fragile positional indexing — the PM could reorder skills and
the orchestrator still finds the PRD by type.
6. Get Architect handoff: `handoff = self._architect.received[-1]`
7. Assert: `handoff.source_persona == "product_manager"`
8. `arch_artifacts = await self._architect.handle_handoff(handoff, arch_context)`
9. Create `artifact_dir / "developer"`, empty context
10. Get Developer handoff, assert source is `"architect"`
11. `dev_artifacts = await self._developer.handle_handoff(handoff, dev_context)`
12. Create `artifact_dir / "qa"`, empty context
13. Get QA handoff, assert source is `"developer"`
14. `qa_artifacts = await self._qa.handle_handoff(handoff, qa_context)`
15. Extract certification from `qa_artifacts[-1].metadata.get("certification", "unknown")`
16. Return `PipelineResult(...)`

**`run_spec_from_prd`:**

```python
async def run_spec_from_prd(
    self,
    prd_path: str,
    *,
    user_stories_path: str,
    artifact_dir: Path,
    context_overrides: dict[str, str] | None = None,
) -> PipelineResult:
```

From PRD: Architect → Developer → QA. No PM phase.

`user_stories_path` is required — the Architect's pre-flight demands
`user_stories`, and there's no PM to produce them. Making it an explicit
parameter rather than hiding it in `context_overrides` keeps the input
contract clear in the signature. The file doesn't have to be PM-generated —
any file with acceptance criteria works (hand-written stories, BDD specs,
etc.). The name reflects the Architect's context parameter, not the source.

1. Read PRD content from `prd_path`, read user stories from `user_stories_path`
2. Merge context, add `prd`, `prd_path`, `user_stories`, `user_stories_path`
3. Create `artifact_dir / "architect"`, build context
4. `arch_artifacts = await self._architect.run_spec_from_prd(arch_context)`
   — direct call, no handoff (Architect starts cold)
5. Continue with Developer and QA via `handle_handoff` (same as steps 9-14 above)
6. Return `PipelineResult(pm=[], ...)`

Note: No handoff span for the Architect entry — telemetry asymmetry per D8.

**`run_plan_from_spec`:**

```python
async def run_plan_from_spec(
    self,
    *,
    implementation_plan_path: str,
    tech_spec_path: str,
    artifact_dir: Path,
    user_stories_path: str | None = None,
    context_overrides: dict[str, str] | None = None,
) -> PipelineResult:
```

From spec: Developer → QA. No PM or Architect phase.

1. Read implementation plan and tech spec from paths
2. Build Developer context with both loaded + paths stored for metadata forwarding
3. If `user_stories_path` provided, load and store in context + path
4. Create `artifact_dir / "developer"`
5. `dev_artifacts = await self._developer.run_plan_from_spec(dev_context)`
   — direct call, no handoff
6. Continue with QA via `handle_handoff`
7. Return `PipelineResult(pm=[], architect=[], ...)`

### QA `handle_handoff` Change (`personas/qa.py`)

Make `user_stories_path` optional:

Before:
```python
user_stories_path = handoff.metadata["user_stories_path"]
context.parameters["user_stories"] = Path(user_stories_path).read_text()
```

After:
```python
user_stories_path = handoff.metadata.get("user_stories_path", "")
if user_stories_path:
    context.parameters["user_stories"] = Path(user_stories_path).read_text()
```

`tech_spec_path` remains required in QA's `handle_handoff` — every workflow
that reaches QA has a tech spec (it's the Architect's primary output or
provided directly in `run_plan_from_spec`).

If `user_stories` is not in context after `handle_handoff`, QA's
`run_validation` pre-flight fails with "Missing required context: user_stories".
This is correct — the orchestrator is responsible for ensuring user stories
reach QA, either through the metadata chain or via the `user_stories_path`
parameter on `run_plan_from_spec`.

---

## Test Plan — 15 New Tests

### test_result.py (2 tests)

1. `test_pipeline_result_defaults` — empty result has `certification="skipped"`,
   all lists empty
2. `test_pipeline_result_with_artifacts` — populated result has correct
   per-persona grouping and certification

### test_orchestrator.py — run_idea_to_code (5 tests)

3. `test_idea_to_code_returns_eight_artifacts` — full pipeline produces 8
   artifacts with correct types in order
4. `test_idea_to_code_creates_persona_directories` — `artifact_dir / "pm"`,
   `"architect"`, `"developer"`, `"qa"` all exist
5. `test_idea_to_code_returns_certification` — `result.certification` is
   not `"skipped"` (populated from QA)
6. `test_idea_to_code_context_overrides` — override `personas_context`,
   verify the override reaches PM's skill prompt
7. `test_idea_to_code_emits_telemetry` — 4 persona spans, 3 handoff spans

### test_orchestrator.py — run_spec_from_prd (3 tests)

8. `test_spec_from_prd_skips_pm` — `result.pm == []`, `result.architect`
   and `result.developer` populated
9. `test_spec_from_prd_returns_five_artifacts` — 2 Architect (tech_spec,
   implementation_plan) + 1 Developer (code_plan) + 2 QA (compliance_report,
   validation_report) = 5 artifacts
10. `test_spec_from_prd_emits_two_handoff_spans` — arch→dev, dev→qa only

### test_orchestrator.py — run_plan_from_spec (3 tests)

11. `test_plan_from_spec_skips_pm_and_architect` — `result.pm == []`,
    `result.architect == []`
12. `test_plan_from_spec_returns_three_artifacts` — code_plan + compliance + validation
13. `test_plan_from_spec_with_user_stories` — provide `user_stories_path`,
    verify QA can run (user stories reach QA through metadata chain)
14. `test_plan_from_spec_without_user_stories_fails_qa` — omit
    `user_stories_path`, verify QA's pre-flight raises `SkillValidationError`
    for missing `user_stories`

### test_qa.py addition (1 test)

15. `test_qa_handle_handoff_without_user_stories_path` — handoff metadata
    has empty `user_stories_path`, QA's `handle_handoff` doesn't crash
    (but `run_validation` would fail if user_stories not in context)

### test_orchestrator.py — handoff assertions (1 test)

16. `test_orchestrator_asserts_handoff_source` — verify the orchestrator
    catches wrong handoff source (manually append a fake handoff with
    wrong source to persona's received list, assert AssertionError)

**Total: 16 new tests. Running total: 156 + 16 = 172.**

---

## Implementation Order

1. PipelineResult dataclass + tests (2 tests)
2. QA handle_handoff optional user stories + test (1 test)
3. PipelineOrchestrator with `run_idea_to_code` + tests (6 tests)
4. `run_spec_from_prd` + tests (3 tests)
5. `run_plan_from_spec` + tests (3 tests)
6. Workflows `__init__.py` re-exports + final verification (including
   explicit regression run of existing `test_pipeline.py` tests)
