# Phase 4: Architect + Developer Personas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Architect and Developer personas to complete a PM → Architect → Developer pipeline with full telemetry and autonomy policy enforcement.

**Architecture:** Two new BasePersona subclasses with engineering skills (TechSpecWriter, ImplementationPlanner, CodePlanner). Backward-compatible metadata field on PersonaHandoff enables structured inter-persona context passing. Pre-flight validation on workflow methods prevents mid-workflow crashes.

**Tech Stack:** Python 3.12, Pydantic v2, OpenTelemetry, pytest (asyncio_mode="auto"), ruff

**Spec:** `docs/superpowers/specs/2026-03-18-phase4-architect-developer-design.md`

**Working directory:** `libs/sdlc/` (all paths relative to this unless stated otherwise)

**Run tests with:** `.venv/bin/python -m pytest tests/ -v`

**Run lint with:** `.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/`

---

## File Map

### New files to create

| File | Responsibility |
|------|---------------|
| `src/superagents_sdlc/skills/engineering/__init__.py` | Re-exports: TechSpecWriter, ImplementationPlanner, CodePlanner |
| `src/superagents_sdlc/skills/engineering/tech_spec_writer.py` | TechSpecWriter skill |
| `src/superagents_sdlc/skills/engineering/implementation_planner.py` | ImplementationPlanner skill |
| `src/superagents_sdlc/skills/engineering/code_planner.py` | CodePlanner skill |
| `src/superagents_sdlc/personas/architect.py` | ArchitectPersona |
| `src/superagents_sdlc/personas/developer.py` | DeveloperPersona |
| `tests/unit_tests/test_skills/test_engineering/__init__.py` | Test package |
| `tests/unit_tests/test_skills/test_engineering/test_tech_spec_writer.py` | TechSpecWriter tests |
| `tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py` | ImplementationPlanner tests |
| `tests/unit_tests/test_skills/test_engineering/test_code_planner.py` | CodePlanner tests |
| `tests/unit_tests/test_personas/test_architect.py` | ArchitectPersona tests |
| `tests/unit_tests/test_personas/test_developer.py` | DeveloperPersona tests |
| `tests/unit_tests/test_personas/test_pipeline.py` | End-to-end PM→Architect→Developer tests |

### Existing files to modify

| File | Change |
|------|--------|
| `src/superagents_sdlc/handoffs/contract.py` | Add `metadata: dict[str, Any]` field to PersonaHandoff |
| `src/superagents_sdlc/personas/base.py` | Add `metadata` param to `request_handoff()` |
| `tests/unit_tests/test_handoffs/test_contract.py` | Add metadata round-trip test |
| `src/superagents_sdlc/personas/__init__.py` | Add ArchitectPersona, DeveloperPersona re-exports |

---

## Task 1: Contract changes — PersonaHandoff metadata field

**Files:**
- Modify: `src/superagents_sdlc/handoffs/contract.py`
- Modify: `tests/unit_tests/test_handoffs/test_contract.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit_tests/test_handoffs/test_contract.py`:

```python
def test_handoff_metadata_json_round_trip():
    original = PersonaHandoff(
        source_persona="architect",
        target_persona="developer",
        artifact_type="architecture",
        artifact_path="/artifacts/plan.md",
        context_summary="Tech spec and plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
        metadata={
            "tech_spec_path": "/artifacts/spec.md",
            "autonomy_level": 2,
            "is_critical": True,
        },
    )
    json_str = original.model_dump_json()
    restored = PersonaHandoff.model_validate_json(json_str)
    assert restored.metadata["tech_spec_path"] == "/artifacts/spec.md"
    assert restored.metadata["autonomy_level"] == 2
    assert restored.metadata["is_critical"] is True
    assert restored == original
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_handoffs/test_contract.py::test_handoff_metadata_json_round_trip -v`

Expected: FAIL — `metadata` field doesn't exist on PersonaHandoff yet.

- [ ] **Step 3: Add metadata field to PersonaHandoff**

In `src/superagents_sdlc/handoffs/contract.py`, add import and field:

```python
# Add to imports (line 7-9 area):
from typing import Any

from pydantic import BaseModel, Field

# Add as last field in PersonaHandoff class (after parent_span_id):
    metadata: dict[str, Any] = Field(default_factory=dict)
```

The full updated class should have these imports and fields:

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PersonaHandoff(BaseModel):
    # ... existing fields unchanged ...
    source_persona: str
    target_persona: str
    artifact_type: str
    artifact_path: str
    context_summary: str
    autonomy_level: int
    requires_approval: bool
    trace_id: str
    parent_span_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_handoffs/test_contract.py -v`

Expected: All 4 tests pass (3 existing + 1 new). Existing tests pass because `metadata` defaults to `{}`.

- [ ] **Step 5: Add metadata param to BasePersona.request_handoff**

In `src/superagents_sdlc/personas/base.py`, update `request_handoff`:

1. Add `from typing import Any` to the imports at top (or to `TYPE_CHECKING` block — but `Any` is used at runtime in the signature, so it needs to be a runtime import. With `from __future__ import annotations`, it can go in TYPE_CHECKING).

2. Add `metadata` parameter to signature (after `context_summary`):

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

3. Update the docstring Args to include:
```
        metadata: Structured key-value pairs for inter-persona routing.
```

4. Pass metadata to the PersonaHandoff constructor (after `parent_span_id`):

```python
            handoff = PersonaHandoff(
                source_persona=self.name,
                target_persona=target,
                artifact_type=artifact.artifact_type,
                artifact_path=artifact.path,
                context_summary=context_summary,
                autonomy_level=level,
                requires_approval=False,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                metadata=metadata or {},
            )
```

- [ ] **Step 6: Run full test suite to verify no regressions**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All 70 tests pass (69 existing + 1 new).

- [ ] **Step 7: Lint check**

Run: `.venv/bin/ruff check src/superagents_sdlc/handoffs/contract.py src/superagents_sdlc/personas/base.py tests/unit_tests/test_handoffs/test_contract.py`

Fix any issues.

- [ ] **Step 8: Commit**

```bash
git add src/superagents_sdlc/handoffs/contract.py src/superagents_sdlc/personas/base.py tests/unit_tests/test_handoffs/test_contract.py
git commit -m "feat(sdlc): add metadata field to PersonaHandoff and request_handoff"
```

---

## Task 2: Create engineering skills directory + TechSpecWriter

**Files:**
- Create: `src/superagents_sdlc/skills/engineering/__init__.py`
- Create: `src/superagents_sdlc/skills/engineering/tech_spec_writer.py`
- Create: `tests/unit_tests/test_skills/test_engineering/__init__.py`
- Create: `tests/unit_tests/test_skills/test_engineering/test_tech_spec_writer.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/superagents_sdlc/skills/engineering tests/unit_tests/test_skills/test_engineering
touch tests/unit_tests/test_skills/test_engineering/__init__.py
```

Create `src/superagents_sdlc/skills/engineering/__init__.py`:

```python
"""Engineering skills — technical specification and planning skills."""
```

(Re-exports added in Task 8 after all skills exist.)

- [ ] **Step 2: Write the failing tests**

Create `tests/unit_tests/test_skills/test_engineering/test_tech_spec_writer.py`:

```python
"""Tests for TechSpecWriter skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.engineering.tech_spec_writer import TechSpecWriter

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={"PRD": "# Tech Spec\n## Architecture\nMicroservices with REST API"}
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "prd": "# PRD: Dark Mode\n## Problem\nEye strain in low light",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "product_context": "B2B SaaS project management platform",
        },
        trace_id="trace-1",
    )


def test_spec_validate_passes(tmp_path):
    skill = TechSpecWriter(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_spec_validate_fails_missing_prd(tmp_path):
    skill = TechSpecWriter(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["prd"]
    with pytest.raises(SkillValidationError, match="prd"):
        skill.validate(context)


async def test_spec_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "tech_spec.md").exists()
    assert artifact.artifact_type == "tech_spec"
    assert artifact.path == str(tmp_path / "tech_spec.md")


async def test_spec_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Dark Mode" in prompt
    assert "eye strain" in prompt
    assert "B2B SaaS" in prompt


async def test_spec_execute_returns_correct_metadata(tmp_path):
    stub = _make_stub()
    skill = TechSpecWriter(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert "prd_idea" in artifact.metadata
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_tech_spec_writer.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'superagents_sdlc.skills.engineering.tech_spec_writer'`

- [ ] **Step 4: Implement TechSpecWriter**

Create `src/superagents_sdlc/skills/engineering/tech_spec_writer.py`:

```python
"""TechSpecWriter — technical specification generation skill.

Transforms PRDs and user stories into technical specifications with architecture
decisions, data models, and API designs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior software architect writing a technical specification. \
Your spec translates product requirements into engineering decisions.

## Required output structure

1. **Architecture overview** — High-level component diagram and interactions
2. **Component boundaries** — What each module owns and what it does not
3. **Data model** — Entities, relationships, key fields
4. **API design** — Endpoints or interfaces, request/response shapes
5. **Infrastructure requirements** — Runtime, storage, networking
6. **Security considerations** — Auth, data protection, input validation
7. **Technical risks** — What could go wrong and mitigation strategies
8. **Open technical questions** — Unknowns that need investigation
"""


class TechSpecWriter(BaseSkill):
    """Transform PRDs and user stories into technical specifications."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the tech spec.
        """
        self._llm = llm
        super().__init__(
            name="tech_spec_writer",
            description=(
                "Transform PRDs and user stories into technical specifications "
                "with architecture decisions, data models, and API designs"
            ),
            required_context=["prd", "user_stories", "product_context"],
        )

    def validate(self, context: SkillContext) -> None:
        """Check that required context parameters are present.

        Args:
            context: Execution context to validate.

        Raises:
            SkillValidationError: If a required parameter is missing.
        """
        for key in self.required_context:
            if key not in context.parameters:
                msg = f"Missing required context parameter: {key}"
                raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        """Generate a tech spec from PRD and user stories.

        Args:
            context: Execution context with PRD and product context.

        Returns:
            Artifact pointing to the tech spec output file.
        """
        params = context.parameters
        prd = params["prd"]
        stories = params["user_stories"]
        product = params["product_context"]

        prompt_parts = [
            f"## PRD\n{prd}",
            f"## User stories\n{stories}",
            f"## Product context\n{product}",
        ]

        if "goals_context" in params:
            prompt_parts.append(f"## Goals\n{params['goals_context']}")
        if "priority_output" in params:
            prompt_parts.append(f"## Priority ranking\n{params['priority_output']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "tech_spec.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="tech_spec",
            metadata={"prd_idea": prd[:100]},
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_tech_spec_writer.py -v`

Expected: All 5 pass.

- [ ] **Step 6: Lint check**

Run: `.venv/bin/ruff check src/superagents_sdlc/skills/engineering/ tests/unit_tests/test_skills/test_engineering/`

Fix any issues.

- [ ] **Step 7: Commit**

```bash
git add src/superagents_sdlc/skills/engineering/ tests/unit_tests/test_skills/test_engineering/
git commit -m "feat(sdlc): add TechSpecWriter engineering skill"
```

---

## Task 3: ImplementationPlanner skill

**Files:**
- Create: `src/superagents_sdlc/skills/engineering/implementation_planner.py`
- Create: `tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py`:

```python
"""Tests for ImplementationPlanner skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.engineering.implementation_planner import ImplementationPlanner

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={"tech_spec": "## Tasks\n1. Create data model\n2. Build API\n3. Add UI"}
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
        },
        trace_id="trace-1",
    )


def test_planner_validate_passes(tmp_path):
    skill = ImplementationPlanner(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_planner_validate_fails_missing_spec(tmp_path):
    skill = ImplementationPlanner(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["tech_spec"]
    with pytest.raises(SkillValidationError, match="tech_spec"):
        skill.validate(context)


async def test_planner_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = ImplementationPlanner(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "implementation_plan.md").exists()
    assert artifact.artifact_type == "implementation_plan"


async def test_planner_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = ImplementationPlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "REST API" in prompt
    assert "PostgreSQL" in prompt
    assert "dark mode" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ImplementationPlanner**

Create `src/superagents_sdlc/skills/engineering/implementation_planner.py`:

```python
"""ImplementationPlanner — ordered task breakdown from technical specs.

Breaks technical specs into ordered implementation tasks with file paths,
dependencies, and verification steps aligned with Superpowers methodology.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior software architect breaking a technical spec into an \
ordered implementation plan following the Superpowers methodology.

## Task structure requirements

Each task should be 2-5 minutes of focused work. For each task provide:
- **Description**: What to build or change
- **File paths**: Exact files to create or modify
- **Dependencies**: Which tasks must complete first
- **Verification**: How to prove this task is done (test command, assertion)

## Output structure

1. **Task list** — Ordered by dependency, grouped by component
2. **Critical path** — Which tasks are on the longest dependency chain
3. **Integration points** — Where separately-built components connect
"""


class ImplementationPlanner(BaseSkill):
    """Break technical specs into ordered implementation tasks."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the implementation plan.
        """
        self._llm = llm
        super().__init__(
            name="implementation_planner",
            description=(
                "Break technical specs into ordered implementation tasks "
                "with file paths, dependencies, and verification steps"
            ),
            required_context=["tech_spec", "user_stories"],
        )

    def validate(self, context: SkillContext) -> None:
        """Check that required context parameters are present.

        Args:
            context: Execution context to validate.

        Raises:
            SkillValidationError: If a required parameter is missing.
        """
        for key in self.required_context:
            if key not in context.parameters:
                msg = f"Missing required context parameter: {key}"
                raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        """Generate an implementation plan from the tech spec.

        Args:
            context: Execution context with tech spec and user stories.

        Returns:
            Artifact pointing to the implementation plan output file.
        """
        params = context.parameters
        spec = params["tech_spec"]
        stories = params["user_stories"]

        prompt_parts = [
            f"## Technical specification\n{spec}",
            f"## User stories to implement\n{stories}",
        ]

        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")
        if "product_context" in params:
            prompt_parts.append(f"## Product context\n{params['product_context']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "implementation_plan.md"
        output_path.write_text(response)

        lines = [line.strip() for line in response.splitlines() if line.strip()]
        task_count = sum(1 for line in lines if line and line[0].isdigit())

        return Artifact(
            path=str(output_path),
            artifact_type="implementation_plan",
            metadata={"task_count": str(task_count)},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py -v`

Expected: All 4 pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/engineering/implementation_planner.py tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py
git add src/superagents_sdlc/skills/engineering/implementation_planner.py tests/unit_tests/test_skills/test_engineering/test_implementation_planner.py
git commit -m "feat(sdlc): add ImplementationPlanner engineering skill"
```

---

## Task 4: CodePlanner skill

**Files:**
- Create: `src/superagents_sdlc/skills/engineering/code_planner.py`
- Create: `tests/unit_tests/test_skills/test_engineering/test_code_planner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_skills/test_engineering/test_code_planner.py`:

```python
"""Tests for CodePlanner skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.engineering.code_planner import CodePlanner

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "implementation_plan": (
                "## Task 1: Create DarkModeToggle\n"
                "### RED\ntest_toggle_switches_theme\n"
                "### GREEN\ndef toggle(): pass"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": "## Tasks\n1. Create data model\n2. Build API",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_code_planner_validate_passes(tmp_path):
    skill = CodePlanner(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_code_planner_validate_fails_missing_plan(tmp_path):
    skill = CodePlanner(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["implementation_plan"]
    with pytest.raises(SkillValidationError, match="implementation_plan"):
        skill.validate(context)


async def test_code_planner_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "code_plan.md").exists()
    assert artifact.artifact_type == "code"


async def test_code_planner_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = CodePlanner(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Create data model" in prompt
    assert "REST API" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_code_planner.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement CodePlanner**

Create `src/superagents_sdlc/skills/engineering/code_planner.py`:

```python
"""CodePlanner — TDD code plan generation skill.

Generates detailed code-level plans with file paths, function signatures,
and test cases following the RED-GREEN-REFACTOR cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior developer planning a TDD implementation. For each task \
from the implementation plan, produce a detailed code-level plan.

## Per-task structure

For each task:
- **File paths**: Exact files to create or modify (with full paths)
- **Function/class signatures**: With type hints
- **RED**: Test cases to write first (test name, assertion, expected behavior)
- **GREEN**: Minimum implementation to make tests pass
- **REFACTOR**: Cleanup opportunities after green

## Output structure

1. **Ordered task breakdown** — In dependency order
2. **Integration test outline** — How to verify components work together
"""


class CodePlanner(BaseSkill):
    """Generate detailed TDD code plans."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the code plan.
        """
        self._llm = llm
        super().__init__(
            name="code_planner",
            description=(
                "Generate detailed TDD code plans with file paths, "
                "function signatures, and test cases"
            ),
            required_context=["implementation_plan", "tech_spec"],
        )

    def validate(self, context: SkillContext) -> None:
        """Check that required context parameters are present.

        Args:
            context: Execution context to validate.

        Raises:
            SkillValidationError: If a required parameter is missing.
        """
        for key in self.required_context:
            if key not in context.parameters:
                msg = f"Missing required context parameter: {key}"
                raise SkillValidationError(msg)

    async def execute(self, context: SkillContext) -> Artifact:
        """Generate a TDD code plan from the implementation plan and tech spec.

        Args:
            context: Execution context with implementation plan and tech spec.

        Returns:
            Artifact pointing to the code plan output file.
        """
        params = context.parameters
        plan = params["implementation_plan"]
        spec = params["tech_spec"]

        prompt_parts = [
            f"## Implementation plan\n{plan}",
            f"## Technical specification\n{spec}",
        ]

        if "user_stories" in params:
            prompt_parts.append(f"## User stories\n{params['user_stories']}")
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "code_plan.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="code",
            metadata={"spec_source": "implementation_plan"},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_engineering/test_code_planner.py -v`

Expected: All 4 pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/engineering/code_planner.py tests/unit_tests/test_skills/test_engineering/test_code_planner.py
git add src/superagents_sdlc/skills/engineering/code_planner.py tests/unit_tests/test_skills/test_engineering/test_code_planner.py
git commit -m "feat(sdlc): add CodePlanner engineering skill"
```

---

## Task 5: ArchitectPersona + workflow tests

**Files:**
- Create: `src/superagents_sdlc/personas/architect.py`
- Create: `tests/unit_tests/test_personas/test_architect.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_personas/test_architect.py`:

```python
"""Tests for ArchitectPersona."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.architect import ArchitectPersona
from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient


# -- Stub developer (handoff target) --


class StubDeveloperPersona(BasePersona):
    """Stub developer that stores received handoffs."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        self.received.append(handoff)


# -- Helpers --


def _make_stub_llm() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## PRD\n": "# Tech Spec\n## Architecture\nMicroservices with REST API",
            "## Technical specification\n": "## Tasks\n1. Create model\n2. Build API\n3. Add UI",
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "prd": "# PRD: Dark Mode\n## Problem\nEye strain",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "product_context": "B2B SaaS project management platform",
        },
        trace_id="trace-1",
    )


def _make_architect(
    tmp_path: Path,
    *,
    stub_llm: StubLLMClient | None = None,
) -> tuple[ArchitectPersona, StubDeveloperPersona, StubLLMClient]:
    llm = stub_llm or _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    architect = ArchitectPersona(llm=llm, policy_engine=engine, transport=transport)
    developer = StubDeveloperPersona(
        name="developer",
        skills={},
        policy_engine=PolicyEngine(config=config, gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=registry),
    )
    registry.register(architect)
    registry.register(developer)

    return architect, developer, llm


# -- Tests --


def test_architect_has_two_skills(tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    assert "tech_spec_writer" in architect.skills
    assert "implementation_planner" in architect.skills
    assert len(architect.skills) == 2


async def test_architect_receive_handoff_stores(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    handoff = PersonaHandoff(
        source_persona="product_manager",
        target_persona="architect",
        artifact_type="user_story",
        artifact_path="/stories.md",
        context_summary="Stories ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await architect.receive_handoff(handoff)
    assert len(architect.received) == 1
    assert architect.received[0].source_persona == "product_manager"


async def test_architect_workflow_runs_two_skills_in_order(exporter, tmp_path):
    architect, _, stub_llm = _make_architect(tmp_path)
    context = _make_context(tmp_path)

    await architect.run_spec_from_prd(context)

    prompts = [call[0] for call in stub_llm.calls]
    assert len(prompts) == 2
    assert "## PRD\n" in prompts[0]  # tech_spec_writer gets PRD
    assert "## Technical specification\n" in prompts[1]  # implementation_planner


async def test_architect_workflow_returns_two_artifacts(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await architect.run_spec_from_prd(context)

    assert len(artifacts) == 2
    assert artifacts[0].artifact_type == "tech_spec"
    assert artifacts[1].artifact_type == "implementation_plan"


async def test_architect_workflow_emits_persona_span(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)

    await architect.run_spec_from_prd(context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.architect"]
    assert len(persona_spans) == 1

    skill_spans = [s for s in spans if s.name.startswith("skill.")]
    for ss in skill_spans:
        assert ss.parent is not None
        assert ss.parent.span_id == persona_spans[0].context.span_id


async def test_architect_preflight_fails_missing_prd(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)
    del context.parameters["prd"]

    with pytest.raises(SkillValidationError, match="prd"):
        await architect.run_spec_from_prd(context)


async def test_architect_preflight_fails_missing_user_stories(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)
    del context.parameters["user_stories"]

    with pytest.raises(SkillValidationError, match="user_stories"):
        await architect.run_spec_from_prd(context)


async def test_architect_preflight_fails_missing_product_context(exporter, tmp_path):
    architect, _, _ = _make_architect(tmp_path)
    context = _make_context(tmp_path)
    del context.parameters["product_context"]

    with pytest.raises(SkillValidationError, match="product_context"):
        await architect.run_spec_from_prd(context)


async def test_architect_handle_handoff_loads_user_stories(exporter, tmp_path):
    architect, dev, _ = _make_architect(tmp_path)

    # Write a user stories file for the handoff to reference
    stories_path = tmp_path / "user_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    handoff = PersonaHandoff(
        source_persona="product_manager",
        target_persona="architect",
        artifact_type="user_story",
        artifact_path=str(stories_path),
        context_summary="Stories ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )

    # Context with prd and product_context pre-loaded (precondition)
    context = SkillContext(
        artifact_dir=tmp_path / "architect_output",
        parameters={
            "prd": "# PRD: Dark Mode",
            "product_context": "B2B SaaS platform",
        },
        trace_id="trace-1",
    )
    (tmp_path / "architect_output").mkdir()

    artifacts = await architect.handle_handoff(handoff, context)

    assert len(artifacts) == 2
    assert context.parameters["user_stories"] == "As a PM, I want dark mode"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_architect.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'superagents_sdlc.personas.architect'`

- [ ] **Step 3: Implement ArchitectPersona**

Create `src/superagents_sdlc/personas/architect.py`:

```python
"""Architect persona — technical specification and implementation planning."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.engineering.implementation_planner import ImplementationPlanner
from superagents_sdlc.skills.engineering.tech_spec_writer import TechSpecWriter

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)

_REQUIRED_CONTEXT = ("prd", "user_stories", "product_context")


class ArchitectPersona(BasePersona):
    """Architect persona producing tech specs and implementation plans."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        policy_engine: PolicyEngine,
        transport: Transport,
    ) -> None:
        """Initialize with LLM client and infrastructure.

        Args:
            llm: LLM client for skill execution.
            policy_engine: Policy engine for handoff evaluation.
            transport: Transport for delivering handoffs.
        """
        skills = {
            "tech_spec_writer": TechSpecWriter(llm=llm),
            "implementation_planner": ImplementationPlanner(llm=llm),
        }
        super().__init__(
            name="architect",
            skills=skills,
            policy_engine=policy_engine,
            transport=transport,
        )
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        """Store and log incoming handoff.

        Args:
            handoff: The incoming handoff to store.
        """
        self.received.append(handoff)
        logger.info(
            "Architect received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_spec_from_prd(self, context: SkillContext) -> list[Artifact]:
        """Run the spec-from-PRD workflow.

        Linear pipeline: tech spec → implementation plan → handoff to developer.

        Args:
            context: Execution context with prd, user_stories, product_context.

        Returns:
            List of two artifacts: [tech_spec, implementation_plan].

        Raises:
            SkillValidationError: If required context keys are missing.
        """
        # Pre-flight: fail fast before opening spans
        for key in _REQUIRED_CONTEXT:
            if key not in context.parameters:
                msg = f"Missing required context for architect workflow: {key}"
                raise SkillValidationError(msg)

        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            # Step 1: Generate tech spec
            tech_spec_artifact = await self.execute_skill("tech_spec_writer", context)
            tech_spec_content = Path(tech_spec_artifact.path).read_text()
            context.parameters["tech_spec"] = tech_spec_content

            # Step 2: Generate implementation plan
            # (uses tech_spec from step 1 + user_stories already in context)
            plan_artifact = await self.execute_skill("implementation_planner", context)

            # Step 3: Handoff to developer with full context chain
            await self.request_handoff(
                target="developer",
                artifact=plan_artifact,
                context_summary="Tech spec and implementation plan ready for code planning",
                metadata={
                    "tech_spec_path": tech_spec_artifact.path,
                    "user_stories_path": context.parameters.get("user_stories_path", ""),
                    "prd_path": context.parameters.get("prd_path", ""),
                },
            )

        return [tech_spec_artifact, plan_artifact]

    async def handle_handoff(
        self, handoff: PersonaHandoff, context: SkillContext
    ) -> list[Artifact]:
        """Build context from a handoff and run the spec workflow.

        Precondition: context.parameters must already contain "prd" and
        "product_context". The handoff artifact provides user_stories.

        Args:
            handoff: Incoming handoff with artifact path.
            context: Execution context with base context pre-loaded.

        Returns:
            List of artifacts from the workflow.
        """
        context.parameters["user_stories"] = Path(handoff.artifact_path).read_text()
        return await self.run_spec_from_prd(context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_architect.py -v`

Expected: All 9 pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/personas/architect.py tests/unit_tests/test_personas/test_architect.py
git add src/superagents_sdlc/personas/architect.py tests/unit_tests/test_personas/test_architect.py
git commit -m "feat(sdlc): add ArchitectPersona with spec-from-prd workflow"
```

---

## Task 6: DeveloperPersona + workflow tests

**Files:**
- Create: `src/superagents_sdlc/personas/developer.py`
- Create: `tests/unit_tests/test_personas/test_developer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_personas/test_developer.py`:

```python
"""Tests for DeveloperPersona."""

from __future__ import annotations

from pathlib import Path

import pytest

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.developer import DeveloperPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient


def _make_stub_llm() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "implementation_plan": (
                "## Task 1\n### RED\ntest_toggle\n### GREEN\ndef toggle(): pass"
            ),
        }
    )


def _make_developer(
    tmp_path: Path,
    *,
    stub_llm: StubLLMClient | None = None,
) -> tuple[DeveloperPersona, StubLLMClient]:
    llm = stub_llm or _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    dev = DeveloperPersona(llm=llm, policy_engine=engine, transport=transport)
    registry.register(dev)
    return dev, llm


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": "## Tasks\n1. Create model\n2. Build API",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


# -- Tests --


def test_developer_has_one_skill(tmp_path):
    dev, _ = _make_developer(tmp_path)
    assert "code_planner" in dev.skills
    assert len(dev.skills) == 1


async def test_developer_receive_handoff_stores(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    handoff = PersonaHandoff(
        source_persona="architect",
        target_persona="developer",
        artifact_type="architecture",
        artifact_path="/plan.md",
        context_summary="Plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await dev.receive_handoff(handoff)
    assert len(dev.received) == 1


async def test_developer_workflow_returns_code_plan(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await dev.run_plan_from_spec(context)

    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "code"
    assert (tmp_path / "code_plan.md").exists()


async def test_developer_workflow_emits_persona_span(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    context = _make_context(tmp_path)

    await dev.run_plan_from_spec(context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.developer"]
    assert len(persona_spans) == 1


async def test_developer_preflight_fails_missing_context(exporter, tmp_path):
    dev, _ = _make_developer(tmp_path)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={"tech_spec": "some spec"},  # missing implementation_plan
        trace_id="trace-1",
    )

    with pytest.raises(SkillValidationError, match="implementation_plan"):
        await dev.run_plan_from_spec(context)


async def test_developer_handle_handoff_loads_tech_spec_from_metadata(exporter, tmp_path):
    dev, stub_llm = _make_developer(tmp_path)

    # Write files that the handoff references
    plan_path = tmp_path / "implementation_plan.md"
    plan_path.write_text("## Tasks\n1. Create model\n2. Build API")

    spec_path = tmp_path / "tech_spec.md"
    spec_path.write_text("# Tech Spec\n## Architecture\nREST API with PostgreSQL")

    handoff = PersonaHandoff(
        source_persona="architect",
        target_persona="developer",
        artifact_type="architecture",
        artifact_path=str(plan_path),
        context_summary="Plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
        metadata={"tech_spec_path": str(spec_path)},
    )

    output_dir = tmp_path / "dev_output"
    output_dir.mkdir()
    context = SkillContext(artifact_dir=output_dir, parameters={}, trace_id="trace-1")

    artifacts = await dev.handle_handoff(handoff, context)

    # Verify context was populated from files
    assert context.parameters["implementation_plan"] == "## Tasks\n1. Create model\n2. Build API"
    assert "REST API" in context.parameters["tech_spec"]
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "code"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_developer.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'superagents_sdlc.personas.developer'`

- [ ] **Step 3: Implement DeveloperPersona**

Create `src/superagents_sdlc/personas/developer.py`:

```python
"""Developer persona — TDD code plan generation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.engineering.code_planner import CodePlanner

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)

_REQUIRED_CONTEXT = ("implementation_plan", "tech_spec")


class DeveloperPersona(BasePersona):
    """Developer persona producing TDD code plans."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        policy_engine: PolicyEngine,
        transport: Transport,
    ) -> None:
        """Initialize with LLM client and infrastructure.

        Args:
            llm: LLM client for skill execution.
            policy_engine: Policy engine for handoff evaluation.
            transport: Transport for delivering handoffs.
        """
        skills = {
            "code_planner": CodePlanner(llm=llm),
        }
        super().__init__(
            name="developer",
            skills=skills,
            policy_engine=policy_engine,
            transport=transport,
        )
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        """Store and log incoming handoff.

        Args:
            handoff: The incoming handoff to store.
        """
        self.received.append(handoff)
        logger.info(
            "Developer received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_plan_from_spec(self, context: SkillContext) -> list[Artifact]:
        """Run the code planning workflow.

        Args:
            context: Execution context with implementation_plan and tech_spec.

        Returns:
            List of one artifact: [code_plan].

        Raises:
            SkillValidationError: If required context keys are missing.
        """
        for key in _REQUIRED_CONTEXT:
            if key not in context.parameters:
                msg = f"Missing required context for developer workflow: {key}"
                raise SkillValidationError(msg)

        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            code_plan_artifact = await self.execute_skill("code_planner", context)

        return [code_plan_artifact]

    async def handle_handoff(
        self, handoff: PersonaHandoff, context: SkillContext
    ) -> list[Artifact]:
        """Build context from a handoff and run the code planning workflow.

        Reads the implementation plan from the handoff artifact path and the
        tech spec from the metadata. Optionally loads user_stories and prd
        if paths are present in metadata.

        Args:
            handoff: Incoming handoff with artifact path and metadata.
            context: Execution context (parameters will be populated).

        Returns:
            List of artifacts from the workflow.
        """
        # Required: implementation plan from primary artifact
        context.parameters["implementation_plan"] = Path(handoff.artifact_path).read_text()

        # Required: tech spec from metadata
        tech_spec_path = handoff.metadata["tech_spec_path"]
        context.parameters["tech_spec"] = Path(tech_spec_path).read_text()

        # Optional: additional context from metadata
        for meta_key, param_key in [
            ("user_stories_path", "user_stories"),
            ("prd_path", "prd"),
        ]:
            path_str = handoff.metadata.get(meta_key, "")
            if path_str:
                file_path = Path(path_str)
                if file_path.exists():
                    context.parameters[param_key] = file_path.read_text()

        return await self.run_plan_from_spec(context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_developer.py -v`

Expected: All 6 pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/personas/developer.py tests/unit_tests/test_personas/test_developer.py
git add src/superagents_sdlc/personas/developer.py tests/unit_tests/test_personas/test_developer.py
git commit -m "feat(sdlc): add DeveloperPersona with code-plan-from-spec workflow"
```

---

## Task 7: Pipeline integration tests

**Files:**
- Create: `tests/unit_tests/test_personas/test_pipeline.py`

- [ ] **Step 1: Write the pipeline tests**

Create `tests/unit_tests/test_personas/test_pipeline.py`:

```python
"""End-to-end pipeline tests: PM → Architect → Developer.

Full stack with StubLLMClient as the only fake. Real PolicyEngine,
InProcessTransport, PersonaRegistry, and telemetry.
"""

from __future__ import annotations

from pathlib import Path

from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.architect import ArchitectPersona
from superagents_sdlc.personas.developer import DeveloperPersona
from superagents_sdlc.personas.product_manager import ProductManagerPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate, MockApprovalGate
from superagents_sdlc.skills.base import SkillContext
from superagents_sdlc.skills.llm import StubLLMClient


def _make_pipeline_llm() -> StubLLMClient:
    """StubLLMClient with canned responses for all skills across all personas.

    Keys use exact prompt section headers to avoid substring collisions.
    Order matters: more specific keys must appear before less specific ones.
    """
    return StubLLMClient(
        responses={
            # PM skills (keyed to prompt section headers from each skill's execute())
            "## Items to prioritize\n": "## Rankings\n1. Dark mode - RICE: 42",
            "## Idea / feature to spec\n": "# PRD: Dark Mode\n## Problem\nEye strain",
            "## Feature description\n": (
                "## Story 1\nAs a PM, I want dark mode\n"
                "### Acceptance Criteria\nGiven dashboard\nWhen toggle\nThen dark"
            ),
            # Architect skills
            "## PRD\n": "# Tech Spec\n## Architecture\nMicroservices with REST API",
            "## Technical specification\n": (
                "## Tasks\n1. Create model\n2. Build API\n3. Add UI"
            ),
            # Developer skills
            "## Implementation plan\n": (
                "## Task 1: DarkModeToggle\n"
                "### RED\ntest_toggle_switches_theme\n"
                "### GREEN\ndef toggle(): pass"
            ),
        }
    )


def _make_pipeline(
    tmp_path: Path,
    *,
    autonomy_level: int = 2,
    gate=None,
) -> tuple[ProductManagerPersona, ArchitectPersona, DeveloperPersona, StubLLMClient]:
    """Wire up the full PM → Architect → Developer pipeline."""
    stub_llm = _make_pipeline_llm()
    if gate is None:
        gate = AutoApprovalGate()
    config = PolicyConfig(autonomy_level=autonomy_level)
    engine = PolicyEngine(config=config, gate=gate)
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    pm = ProductManagerPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    architect = ArchitectPersona(llm=stub_llm, policy_engine=engine, transport=transport)
    developer = DeveloperPersona(llm=stub_llm, policy_engine=engine, transport=transport)

    registry.register(pm)
    registry.register(architect)
    registry.register(developer)

    return pm, architect, developer, stub_llm


async def _run_full_pipeline(
    tmp_path: Path,
    pm: ProductManagerPersona,
    architect: ArchitectPersona,
    developer: DeveloperPersona,
) -> tuple[list, list, list]:
    """Run PM → Architect → Developer and return all artifact lists."""
    # PM phase
    pm_context = SkillContext(
        artifact_dir=tmp_path / "pm",
        parameters={
            "product_context": "B2B SaaS platform",
            "goals_context": "Q1: reduce churn by 10%",
            "personas_context": "# PM Patricia\nManages projects, hates eye strain",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "pm").mkdir()
    pm_artifacts = await pm.run_idea_to_sprint("Add dark mode", pm_context)

    # Adapter: mount PM outputs into Architect context
    prd_content = Path(pm_artifacts[1].path).read_text()  # PRD artifact
    arch_context = SkillContext(
        artifact_dir=tmp_path / "architect",
        parameters={
            "prd": prd_content,
            "product_context": "B2B SaaS platform",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "architect").mkdir()

    # The handoff that the architect received
    arch_handoff = architect.received[-1]
    arch_artifacts = await architect.handle_handoff(arch_handoff, arch_context)

    # Developer: handle handoff from architect
    dev_context = SkillContext(
        artifact_dir=tmp_path / "developer",
        parameters={},
        trace_id="trace-pipeline",
    )
    (tmp_path / "developer").mkdir()

    dev_handoff = developer.received[-1]
    dev_artifacts = await developer.handle_handoff(dev_handoff, dev_context)

    return pm_artifacts, arch_artifacts, dev_artifacts


async def test_pipeline_pm_to_architect_to_developer(exporter, tmp_path):
    pm, architect, developer, stub_llm = _make_pipeline(tmp_path)

    pm_artifacts, arch_artifacts, dev_artifacts = await _run_full_pipeline(
        tmp_path, pm, architect, developer
    )

    # 6 total artifacts across the pipeline
    all_artifacts = pm_artifacts + arch_artifacts + dev_artifacts
    assert len(all_artifacts) == 6
    types = [a.artifact_type for a in all_artifacts]
    assert types == ["backlog", "prd", "user_story", "tech_spec", "implementation_plan", "code"]

    # Verify tech spec content reached Developer's code_planner prompt via metadata
    dev_prompt = stub_llm.calls[-1][0]
    assert "Microservices" in dev_prompt or "REST API" in dev_prompt


async def test_pipeline_emits_three_persona_spans(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(tmp_path)

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    persona_names = {s.name for s in spans if s.name.startswith("persona.")}
    assert "persona.product_manager" in persona_names
    assert "persona.architect" in persona_names
    assert "persona.developer" in persona_names


async def test_pipeline_handoff_chain(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(tmp_path)

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    sources_targets = [(s.attributes["handoff.source"], s.attributes["handoff.target"]) for s in handoff_spans]
    assert ("product_manager", "architect") in sources_targets
    assert ("architect", "developer") in sources_targets


async def test_pipeline_level_2_planning_auto_proceeds(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(tmp_path, autonomy_level=2)

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    # All handoffs carry planning artifacts at Level 2 → all auto-proceed
    for gs in gate_spans:
        assert gs.attributes["approval.outcome"] == "auto_proceeded"


async def test_pipeline_level_1_all_handoffs_require_approval(exporter, tmp_path):
    pm, architect, developer, _ = _make_pipeline(
        tmp_path, autonomy_level=1, gate=MockApprovalGate(should_approve=True)
    )

    await _run_full_pipeline(tmp_path, pm, architect, developer)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    for gs in gate_spans:
        assert gs.attributes["approval.required"] is True
        assert gs.attributes["approval.outcome"] == "approved"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_pipeline.py -v`

Expected: All 5 pass. Pipeline integration tests verify cross-component behavior.
The RED-GREEN-REFACTOR cycle was followed for each component in Tasks 1-6; these
tests verify the composition.

- [ ] **Step 3: Lint check**

Run: `.venv/bin/ruff check tests/unit_tests/test_personas/test_pipeline.py`

Fix any issues.

- [ ] **Step 4: Commit**

```bash
git add tests/unit_tests/test_personas/test_pipeline.py
git commit -m "test(sdlc): add end-to-end PM→Architect→Developer pipeline tests"
```

---

## Task 8: Update `__init__.py` re-exports + final verification

**Files:**
- Modify: `src/superagents_sdlc/skills/engineering/__init__.py`
- Modify: `src/superagents_sdlc/personas/__init__.py`

- [ ] **Step 1: Update engineering skills `__init__.py`**

```python
"""Engineering skills — technical specification and planning skills."""

from superagents_sdlc.skills.engineering.code_planner import CodePlanner
from superagents_sdlc.skills.engineering.implementation_planner import ImplementationPlanner
from superagents_sdlc.skills.engineering.tech_spec_writer import TechSpecWriter

__all__ = ["CodePlanner", "ImplementationPlanner", "TechSpecWriter"]
```

- [ ] **Step 2: Update personas `__init__.py`**

```python
"""Personas subpackage — SDLC persona facades."""

from superagents_sdlc.personas.architect import ArchitectPersona
from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.personas.developer import DeveloperPersona
from superagents_sdlc.personas.product_manager import ProductManagerPersona

__all__ = ["ArchitectPersona", "BasePersona", "DeveloperPersona", "ProductManagerPersona"]
```

- [ ] **Step 3: Run full SDLC test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All 118 tests pass (84 existing + 34 new).

- [ ] **Step 4: Run Phase 1 telemetry tests (regression check)**

Run: `cd ../superagents && .venv/bin/python -m pytest tests/unit_tests/test_telemetry/ -v`

Expected: All 15 pass.

- [ ] **Step 5: Full lint + format check**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/`

Fix any issues. Run `ruff format src/ tests/` if needed, then re-verify tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/superagents_sdlc/skills/engineering/__init__.py src/superagents_sdlc/personas/__init__.py
git commit -m "feat(sdlc): add Phase 4 re-exports for engineering skills and personas"
```
