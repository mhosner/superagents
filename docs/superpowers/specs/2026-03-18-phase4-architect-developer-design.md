# Phase 4 Design: Architect + Developer Personas

**Date:** 2026-03-18
**Status:** Draft
**Depends on:** Phase 1 (telemetry), Phase 2 (skills/personas/policy/handoffs), Phase 3 (PM persona)

## Summary

Add two new personas to the SDLC pipeline: Architect (receives PRD + user stories
from PM, produces tech specs and implementation plans) and Developer (receives
implementation plans from Architect, produces TDD code plans). QA is deferred to a
later phase.

This completes a three-persona pipeline (PM → Architect → Developer) that exercises
the full autonomy gradient: planning artifacts auto-proceed at Level 2, code artifacts
require approval.

## Design Decisions

### D1: Architect produces tech spec + implementation plan

The Architect has two skills, not one. The tech spec captures *what and why*
(architecture decisions, data models, API designs). The implementation plan captures
*how and in what order* (ordered tasks with file paths, dependencies, verification
steps). The Developer receives the plan, not the raw spec.

This maps to the CLAUDE.md persona table: Architect's Superpowers phases are
"brainstorming, writing-plans."

### D2: Developer produces a code plan artifact (not actual code)

The Developer takes the implementation plan + tech spec and produces a detailed
code-level plan: file paths, function signatures, test cases (RED phase),
implementation notes (GREEN phase). It does NOT generate or execute code.

The artifact_type is `"code"`, which triggers approval at Level 2. Actual code
generation and TDD execution are deferred to Phase 5+ when subagent dispatch is
available.

### D3: QA deferred

Three new personas in one phase is too much surface area. Architect and Developer
are well-defined. QA's position in the pipeline (upstream vs downstream vs both) is
genuinely uncertain. QA gets its own brainstorm once the three-persona pipeline is
proven.

### D4: Manual trigger with `handle_handoff` convenience method

Each persona has:
- `receive_handoff(handoff)` — stores and logs (satisfies abstract method)
- `handle_handoff(handoff, context)` — reads artifact from handoff, populates
  context, runs workflow. The caller provides base context (product_context, etc.).
- `run_*()` workflow method — the core logic

When Phase 5 adds auto-triggering, `receive_handoff()` calls `handle_handoff()`
internally. One line change, no refactoring.

### D5: Structured metadata on PersonaHandoff

The `PersonaHandoff` model gains a `metadata: dict[str, Any]` field for structured
inter-persona routing data. This replaces string parsing of `context_summary` for
system-critical paths.

The Architect passes `{"tech_spec_path": "/path/to/spec.md"}` in metadata. The
Developer's `handle_handoff` reads both the primary artifact (implementation plan)
and the tech spec from the metadata path.

### D6: Pre-flight validation on workflow methods

Each workflow method validates that all required context keys exist *before* opening
the persona span. Fail fast with `SkillValidationError`, not a mid-workflow crash
inside a skill's `validate()`.

### D7: No Developer outbound handoff

The Developer has no downstream persona in Phase 4 (QA deferred). The handoff
mechanism is already proven by PM → Architect and Architect → Developer. When QA
arrives, the Developer gets a real handoff target.

## Contract Changes (backward-compatible)

### PersonaHandoff — add `metadata` field

```python
metadata: dict[str, Any] = Field(default_factory=dict)
```

New field, default empty. Existing tests and handoffs unaffected.

### BasePersona.request_handoff — add `metadata` parameter

```python
async def request_handoff(
    self,
    *,
    target: str,
    artifact: Artifact,
    context_summary: str,
    metadata: dict[str, Any] | None = None,
) -> HandoffResult:
```

Keyword-only, default `None` (converted to `{}` when building the handoff).
Existing callers (e.g., PM's `request_handoff`) continue to work unchanged.

## Module Structure

### Source

```
libs/sdlc/src/superagents_sdlc/
├── skills/
│   └── engineering/
│       ├── __init__.py
│       ├── tech_spec_writer.py
│       ├── implementation_planner.py
│       └── code_planner.py
├── personas/
│   ├── base.py                  # Add metadata param to request_handoff
│   ├── architect.py
│   └── developer.py
└── handoffs/
    └── contract.py              # Add metadata field
```

### Tests

```
libs/sdlc/tests/unit_tests/
├── test_skills/
│   └── test_engineering/
│       ├── __init__.py
│       ├── test_tech_spec_writer.py
│       ├── test_implementation_planner.py
│       └── test_code_planner.py
├── test_personas/
│   ├── test_architect.py
│   ├── test_developer.py
│   └── test_pipeline.py
└── test_handoffs/
    └── test_contract.py         # Add metadata round-trip test
```

## Skill Specifications

### TechSpecWriter (`skills/engineering/tech_spec_writer.py`)

- **name**: `"tech_spec_writer"`
- **description**: `"Transform PRDs and user stories into technical specifications
  with architecture decisions, data models, and API designs"`
- **required_context**: `["prd", "user_stories", "product_context"]`
- **Optional context**: `"goals_context"`, `"priority_output"`
- **validate()**: checks the three required keys
- **execute()**:
  1. Compose prompt from PRD, user stories, product context
  2. System prompt mandates: architecture overview, component boundaries, data model,
     API design, infrastructure requirements, security considerations, technical risks,
     open questions
  3. Writes to `context.artifact_dir / "tech_spec.md"`
  4. Returns `Artifact(path=..., artifact_type="tech_spec",
     metadata={"prd_idea": prd[:100]})`

### ImplementationPlanner (`skills/engineering/implementation_planner.py`)

- **name**: `"implementation_planner"`
- **description**: `"Break technical specs into ordered implementation tasks with
  file paths, dependencies, and verification steps"`
- **required_context**: `["tech_spec", "user_stories"]`
- **Optional context**: `"prd"`, `"product_context"`
- **validate()**: checks the two required keys
- **execute()**:
  1. Compose prompt from tech spec and user stories
  2. System prompt mandates Superpowers-aligned structure: ordered tasks (2-5 min each),
     file paths, dependencies, verification steps, task grouping, critical path
  3. Writes to `context.artifact_dir / "implementation_plan.md"`
  4. Returns `Artifact(path=..., artifact_type="implementation_plan",
     metadata={"task_count": str(count)})`

  artifact_type is `"implementation_plan"` (planning artifact, auto-proceeds at Level 2).

### CodePlanner (`skills/engineering/code_planner.py`)

- **name**: `"code_planner"`
- **description**: `"Generate detailed TDD code plans with file paths, function
  signatures, and test cases"`
- **required_context**: `["implementation_plan", "tech_spec"]`
- **Optional context**: `"user_stories"`, `"prd"`
- **validate()**: checks the two required keys
- **execute()**:
  1. Compose prompt from implementation plan and tech spec
  2. System prompt mandates TDD structure: per-task file paths, function/class
     signatures, RED (test cases), GREEN (implementation notes), REFACTOR
     (cleanup), dependency order
  3. Writes to `context.artifact_dir / "code_plan.md"`
  4. Returns `Artifact(path=..., artifact_type="code",
     metadata={"spec_source": "implementation_plan"})`

  artifact_type is `"code"` (requires approval at Level 2).

## Persona Specifications

### ArchitectPersona (`personas/architect.py`)

**Constructor**: `llm`, `policy_engine`, `transport` (keyword-only).

Skills registered: `tech_spec_writer`, `implementation_planner`.

**`receive_handoff(handoff)`**: stores in `self.received`, logs.

**`run_spec_from_prd(context) -> list[Artifact]`**:
1. Pre-flight: verify `"prd"`, `"user_stories"`, `"product_context"` in
   `context.parameters`. Raise `SkillValidationError` if missing.
2. `persona_span("architect", autonomy_level=level)`
3. Execute `tech_spec_writer` → tech_spec_artifact
   (uses `prd`, `user_stories`, `product_context` from pre-flight validated context)
4. Read tech spec, set `context.parameters["tech_spec"]`
5. Execute `implementation_planner` → plan_artifact
   (uses `tech_spec` from step 4 + `user_stories` already in context from step 1)
6. `request_handoff(target="developer", artifact=plan_artifact,
   context_summary="Tech spec and implementation plan ready for code planning",
   metadata={"tech_spec_path": tech_spec_artifact.path,
             "user_stories_path": context.parameters.get("user_stories_path", ""),
             "prd_path": context.parameters.get("prd_path", "")})`
   Passes the full context chain forward so the Developer can load optional context
   for higher-quality TDD plans.
7. Return `[tech_spec_artifact, plan_artifact]`

**`handle_handoff(handoff, context) -> list[Artifact]`**:

**Precondition**: `context.parameters` must already contain `"prd"` and
`"product_context"`. These are base context files that the orchestrator or test
harness loads before calling `handle_handoff`. The handoff itself only carries the
user stories artifact — it does not carry the full context chain.

1. Read artifact from `handoff.artifact_path` → `context.parameters["user_stories"]`
2. Call `run_spec_from_prd(context)` (which pre-flight validates all three keys)

### DeveloperPersona (`personas/developer.py`)

**Constructor**: `llm`, `policy_engine`, `transport` (keyword-only).

Skills registered: `code_planner`.

**`receive_handoff(handoff)`**: stores in `self.received`, logs.

**`run_plan_from_spec(context) -> list[Artifact]`**:
1. Pre-flight: verify `"implementation_plan"`, `"tech_spec"` in
   `context.parameters`. Raise `SkillValidationError` if missing.
2. `persona_span("developer", autonomy_level=level)`
3. Execute `code_planner` → code_plan_artifact
4. No outbound handoff (QA deferred)
5. Return `[code_plan_artifact]`

**`handle_handoff(handoff, context) -> list[Artifact]`**:

1. Read implementation plan file contents from `handoff.artifact_path` →
   `context.parameters["implementation_plan"]` (the actual markdown content,
   not the path string — CodePlanner injects this into the LLM prompt)
2. Read tech spec file contents from path in `handoff.metadata["tech_spec_path"]` →
   `context.parameters["tech_spec"]`
3. Optionally load additional context from metadata if paths are present:
   - `handoff.metadata.get("user_stories_path")` → `context.parameters["user_stories"]`
   - `handoff.metadata.get("prd_path")` → `context.parameters["prd"]`
   Only load if the path is non-empty and the file exists. These are optional context
   that improves code plan quality but is not required by CodePlanner's `validate()`.
4. Call `run_plan_from_spec(context)`

## Test Plan (34 tests)

### Contract changes (1 test)

- T01: `test_handoff_metadata_json_round_trip` — metadata with str, int, bool survives
  dump/validate

### TechSpecWriter (5 tests)

- T02: `test_spec_validate_passes`
- T03: `test_spec_validate_fails_missing_prd`
- T04: `test_spec_execute_writes_artifact` — file exists, type == "tech_spec"
- T05: `test_spec_execute_includes_context_in_prompt`
- T06: `test_spec_execute_returns_correct_metadata`

### ImplementationPlanner (4 tests)

- T07: `test_planner_validate_passes`
- T08: `test_planner_validate_fails_missing_spec`
- T09: `test_planner_execute_writes_artifact` — file exists, type == "implementation_plan"
- T10: `test_planner_execute_includes_context_in_prompt`

### CodePlanner (4 tests)

- T11: `test_code_planner_validate_passes`
- T12: `test_code_planner_validate_fails_missing_plan`
- T13: `test_code_planner_execute_writes_artifact` — file exists, type == "code"
- T14: `test_code_planner_execute_includes_context_in_prompt`

### ArchitectPersona (9 tests)

- T15: `test_architect_has_two_skills`
- T16: `test_architect_receive_handoff_stores`
- T17: `test_architect_workflow_runs_two_skills_in_order`
- T18: `test_architect_workflow_returns_two_artifacts` — [tech_spec, architecture]
- T19: `test_architect_workflow_emits_persona_span`
- T20: `test_architect_preflight_fails_missing_prd`
- T21: `test_architect_preflight_fails_missing_user_stories`
- T22: `test_architect_preflight_fails_missing_product_context`
- T23: `test_architect_handle_handoff_loads_user_stories` — reads artifact from
  handoff path, populates context, delegates to workflow

### DeveloperPersona (6 tests)

- T24: `test_developer_has_one_skill`
- T25: `test_developer_receive_handoff_stores`
- T26: `test_developer_workflow_returns_code_plan`
- T27: `test_developer_workflow_emits_persona_span`
- T28: `test_developer_preflight_fails_missing_context`
- T29: `test_developer_handle_handoff_loads_tech_spec_from_metadata` — verifies
  metadata["tech_spec_path"] is read and loaded into context

### Pipeline (5 tests)

- T30: `test_pipeline_pm_to_architect_to_developer` — full chain, 6 artifacts,
  verify tech spec content reaches Developer's code_planner prompt via metadata
- T31: `test_pipeline_emits_three_persona_spans`
- T32: `test_pipeline_handoff_chain` — two handoff spans: pm→architect, architect→developer
- T33: `test_pipeline_level_2_planning_auto_proceeds` — architecture handoff auto-proceeds
- T34: `test_pipeline_level_1_all_handoffs_require_approval`

Pipeline tests use a `_make_pipeline` helper (same pattern as Phase 3's `_make_stack`)
that wires PM + Architect + Developer with shared StubLLMClient, PolicyEngine,
PersonaRegistry, and InProcessTransport. The helper returns all three personas and
the stub LLM for assertion.

The pipeline test harness needs an adapter block between PM and Architect: after
`pm.run_idea_to_sprint()` completes, the test reads the PM's PRD artifact content
and mounts it (along with `product_context`) into a fresh SkillContext before calling
`architect.handle_handoff()`. This mirrors what a real orchestrator would do — the
handoff carries the artifact path, but the orchestrator provides the base context.

**Total: 34 new tests. Combined with existing 84 = 118.**

## Implementation Order

1. Contract changes (PersonaHandoff.metadata + BasePersona.request_handoff metadata param)
2. TechSpecWriter skill (TDD)
3. ImplementationPlanner skill (TDD)
4. CodePlanner skill (TDD)
5. ArchitectPersona + workflow tests (TDD)
6. DeveloperPersona + workflow tests (TDD)
7. Pipeline integration tests
8. Update `__init__.py` re-exports, final lint pass

## Artifact Type Classification Reference

From `policy/engine.py`:

- **Planning (auto-proceed at L2)**: prd, tech_spec, user_story, roadmap, backlog,
  architecture, implementation_plan
- **Code (require approval at L2)**: code, test, migration

Phase 4 exercises both: Architect produces `tech_spec` and `implementation_plan`
(planning), Developer produces `code` (requires approval).

## Future Work

- **QA persona** (Phase 5): acceptance test specs, layered testing model
- **Auto-triggering**: `receive_handoff()` calls `handle_handoff()` internally
- **Dynamic routing**: replace hardcoded handoff targets with policy-driven routing
- **Code generation**: Developer produces actual code via subagent TDD cycle
