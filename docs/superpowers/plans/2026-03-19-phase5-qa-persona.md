# Phase 5: QA Persona + StubLLMClient Strict Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the SDLC persona chain with a QA persona (SpecComplianceChecker + ValidationReportGenerator), add conditional Developer→QA handoff via Transport.can_reach(), rename CODE_ARTIFACT_TYPES to APPROVAL_REQUIRED_TYPES, and add StubLLMClient strict mode.

**Architecture:** QA persona positioned after Developer in the pipeline (PM → Architect → Developer → QA). QA validates the entire upstream chain via metadata-propagated artifact paths. Transport Protocol extended with can_reach() for pre-handoff reachability check.

**Tech Stack:** Python 3.12, Pydantic v2, OpenTelemetry, pytest (asyncio_mode="auto"), ruff

**Spec:** `docs/superpowers/specs/2026-03-19-phase5-qa-persona-design.md`

**Working directory:** `libs/sdlc/` (all paths relative to this unless stated otherwise)

**Run tests with:** `.venv/bin/python -m pytest tests/ -v`

**Run lint with:** `.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/`

---

## File Map

### New files to create

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

### Existing files to modify

| File | Change |
|------|--------|
| `src/superagents_sdlc/skills/llm.py` | Add `strict` parameter to StubLLMClient |
| `src/superagents_sdlc/policy/engine.py` | Rename `CODE_ARTIFACT_TYPES` → `APPROVAL_REQUIRED_TYPES`, add 2 types |
| `src/superagents_sdlc/handoffs/transport.py` | Add `can_reach` to Transport Protocol + InProcessTransport |
| `src/superagents_sdlc/personas/architect.py` | Store `user_stories_path` in `handle_handoff` for downstream forwarding |
| `src/superagents_sdlc/personas/developer.py` | Conditional handoff to QA, path forwarding in metadata |
| `src/superagents_sdlc/personas/__init__.py` | Add QAPersona re-export |
| `tests/unit_tests/test_skills/test_llm.py` | Add strict mode tests |
| `tests/unit_tests/test_handoffs/test_transport.py` | Add can_reach tests |
| `tests/unit_tests/test_policy/test_engine.py` | Add approval-required tests for new types |
| `tests/unit_tests/test_personas/test_developer.py` | Add conditional handoff test |
| `tests/unit_tests/test_personas/test_pipeline.py` | Add 4-persona pipeline tests |

---

## Task 1: StubLLMClient strict mode

**Files:**
- Modify: `src/superagents_sdlc/skills/llm.py`
- Modify: `tests/unit_tests/test_skills/test_llm.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_skills/test_llm.py`:

```python
import pytest


async def test_stub_llm_strict_raises_on_no_match():
    stub = StubLLMClient(responses={"prd": "generated PRD"}, strict=True)
    with pytest.raises(ValueError, match="No response matched prompt"):
        await stub.generate("unrelated prompt")


async def test_stub_llm_strict_still_matches_normally():
    stub = StubLLMClient(responses={"prd": "generated PRD"}, strict=True)
    result = await stub.generate("Please write a prd for feature X")
    assert result == "generated PRD"
```

Also add `import pytest` at the top of the file (it's not imported yet).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_llm.py::test_stub_llm_strict_raises_on_no_match -v`

Expected: FAIL — `TypeError: StubLLMClient.__init__() got an unexpected keyword argument 'strict'`

- [ ] **Step 3: Implement strict mode**

In `src/superagents_sdlc/skills/llm.py`, modify the `StubLLMClient` class:

1. Update `__init__` signature to add `strict` parameter (line 38):

```python
    def __init__(self, *, responses: dict[str, str], strict: bool = False) -> None:
```

2. Store it (after line 46):

```python
        self._responses = responses
        self._strict = strict
        self.calls: list[tuple[str, str]] = []
```

3. Update docstring Args to include:
```
            strict: If True, raise ValueError when no key matches the prompt.
                If False (default), return empty string on no match.
```

4. Update `generate` method — replace the `return ""` at line 63 with:

```python
        if self._strict:
            msg = f"No response matched prompt: {prompt[:100]}"
            raise ValueError(msg)
        return ""
```

5. Update `generate` docstring Returns to:
```
            Matched response, empty string (non-strict), or raises ValueError (strict).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_llm.py -v`

Expected: All 6 tests pass (4 existing + 2 new).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/llm.py tests/unit_tests/test_skills/test_llm.py
git add src/superagents_sdlc/skills/llm.py tests/unit_tests/test_skills/test_llm.py
git commit -m "feat(sdlc): add strict mode to StubLLMClient"
```

---

## Task 2: Policy engine rename + new artifact types

**Files:**
- Modify: `src/superagents_sdlc/policy/engine.py`
- Modify: `tests/unit_tests/test_policy/test_engine.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_policy/test_engine.py`:

```python
async def test_compliance_report_requires_approval_at_level_2(exporter):
    config = PolicyConfig(autonomy_level=2)
    gate = MockApprovalGate(should_approve=True)
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(
        _make_handoff(artifact_type="compliance_report")
    )
    assert result.outcome == "approved"  # delegated to gate, not auto_proceeded


async def test_validation_report_requires_approval_at_level_2(exporter):
    config = PolicyConfig(autonomy_level=2)
    gate = MockApprovalGate(should_approve=True)
    engine = PolicyEngine(config=config, gate=gate)

    result = await engine.evaluate_handoff(
        _make_handoff(artifact_type="validation_report")
    )
    assert result.outcome == "approved"  # delegated to gate, not auto_proceeded
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_policy/test_engine.py::test_compliance_report_requires_approval_at_level_2 -v`

Expected: PASS — these artifact types are already non-planning, so approval is
already required at Level 2. The tests validate the desired behavior is preserved
through the rename. This is a refactoring step, not a behavior change.

- [ ] **Step 3: Rename and add types**

In `src/superagents_sdlc/policy/engine.py`:

Replace lines 28-34:
```python
CODE_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        "code",
        "test",
        "migration",
    }
)
```

With:
```python
APPROVAL_REQUIRED_TYPES: frozenset[str] = frozenset(
    {
        "code",
        "test",
        "migration",
        "compliance_report",
        "validation_report",
    }
)
```

Note: `CODE_ARTIFACT_TYPES` is not referenced anywhere in the engine logic — the engine only checks `PLANNING_ARTIFACT_TYPES` (line 97: `artifact_type not in PLANNING_ARTIFACT_TYPES`). The `CODE_ARTIFACT_TYPES` constant was declarative documentation, not used in logic. The rename to `APPROVAL_REQUIRED_TYPES` makes it accurate documentation. No logic changes needed.

- [ ] **Step 4: Run all engine tests**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_policy/test_engine.py -v`

Expected: All 8 tests pass (6 existing + 2 new).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/policy/engine.py tests/unit_tests/test_policy/test_engine.py
git add src/superagents_sdlc/policy/engine.py tests/unit_tests/test_policy/test_engine.py
git commit -m "refactor(sdlc): rename CODE_ARTIFACT_TYPES to APPROVAL_REQUIRED_TYPES, add QA types"
```

---

## Task 3: Transport.can_reach() protocol extension

**Files:**
- Modify: `src/superagents_sdlc/handoffs/transport.py`
- Modify: `tests/unit_tests/test_handoffs/test_transport.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit_tests/test_handoffs/test_transport.py`:

```python
def test_transport_can_reach_registered():
    persona = _make_mock_persona("architect")
    registry = PersonaRegistry()
    registry.register(persona)
    transport = InProcessTransport(registry=registry)

    assert transport.can_reach("architect") is True


def test_transport_can_reach_unknown():
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    assert transport.can_reach("nonexistent") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_handoffs/test_transport.py::test_transport_can_reach_registered -v`

Expected: FAIL — `AttributeError: 'InProcessTransport' object has no attribute 'can_reach'`

- [ ] **Step 3: Implement can_reach**

In `src/superagents_sdlc/handoffs/transport.py`:

1. Add to `Transport` Protocol class (after the `send` method, line 30):

```python
    def can_reach(self, target: str) -> bool:
        """Check if the transport can deliver to the given target.

        Args:
            target: Name of the target persona.

        Returns:
            True if the target is reachable.
        """
        ...
```

2. Add to `InProcessTransport` class (after `__init__`, before `send`):

```python
    def can_reach(self, target: str) -> bool:
        """Check if the target persona is registered.

        Args:
            target: Name of the target persona.

        Returns:
            True if the persona is registered.
        """
        try:
            self._registry.get(target)
        except KeyError:
            return False
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_handoffs/test_transport.py -v`

Expected: All 6 tests pass (4 existing + 2 new).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/handoffs/transport.py tests/unit_tests/test_handoffs/test_transport.py
git add src/superagents_sdlc/handoffs/transport.py tests/unit_tests/test_handoffs/test_transport.py
git commit -m "feat(sdlc): add can_reach() to Transport protocol and InProcessTransport"
```

---

## Task 4: SpecComplianceChecker skill

**Files:**
- Create: `src/superagents_sdlc/skills/qa/__init__.py`
- Create: `src/superagents_sdlc/skills/qa/spec_compliance_checker.py`
- Create: `tests/unit_tests/test_skills/test_qa/__init__.py`
- Create: `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/superagents_sdlc/skills/qa tests/unit_tests/test_skills/test_qa
touch tests/unit_tests/test_skills/test_qa/__init__.py
```

Create `src/superagents_sdlc/skills/qa/__init__.py`:

```python
"""QA skills — compliance checking and validation reporting."""
```

(Re-exports added in Task 9 after both skills exist.)

- [ ] **Step 2: Write the failing tests**

Create `tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py`:

```python
"""Tests for SpecComplianceChecker skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.qa.spec_compliance_checker import SpecComplianceChecker

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Requirement | Status |\n"
                "| Dark mode toggle | PASS |\n"
                "| Theme persistence | FAIL |\n"
                "## Summary\nOverall: NEEDS WORK\n"
                "Total: 2 | Pass: 1 | Fail: 1"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "## Task 1: DarkModeToggle\n### RED\ntest_toggle",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_compliance_validate_passes(tmp_path):
    skill = SpecComplianceChecker(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_compliance_validate_fails_missing_code_plan(tmp_path):
    skill = SpecComplianceChecker(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["code_plan"]
    with pytest.raises(SkillValidationError, match="code_plan"):
        skill.validate(context)


def test_compliance_validate_fails_missing_user_stories(tmp_path):
    skill = SpecComplianceChecker(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["user_stories"]
    with pytest.raises(SkillValidationError, match="user_stories"):
        skill.validate(context)


async def test_compliance_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "compliance_report.md").exists()
    assert artifact.artifact_type == "compliance_report"
    assert artifact.path == str(tmp_path / "compliance_report.md")
    assert artifact.metadata["framework"] == "spec_compliance"


async def test_compliance_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = SpecComplianceChecker(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "DarkModeToggle" in prompt
    assert "dark mode" in prompt
    assert "REST API" in prompt
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'superagents_sdlc.skills.qa.spec_compliance_checker'`

- [ ] **Step 4: Implement SpecComplianceChecker**

Create `src/superagents_sdlc/skills/qa/spec_compliance_checker.py`:

```python
"""SpecComplianceChecker — gap analysis between specs and implementation artifacts.

Defaults to skepticism: identifies minimum 3-5 issues even on solid plans.
Structured PASS/FAIL per requirement with exact spec text citations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior QA engineer performing a compliance review. Your default \
stance is skepticism — assume NEEDS WORK until proven otherwise.

## Review methodology

For each user story and spec requirement:
1. **Quote** the exact spec text
2. **Quote** the corresponding code plan section (or note "NOT FOUND")
3. **Verdict**: PASS / FAIL / PARTIAL with brief justification

## Mandatory checks

- Every user story must have a corresponding implementation task
- Every implementation task must trace back to a requirement
- Acceptance criteria must have concrete verification steps (not vague)
- Identify minimum 3-5 risks, gaps, or ambiguities even on solid plans

## Automatic FAIL triggers

- Requirement with no corresponding implementation task
- Implementation task with no corresponding requirement
- Vague acceptance criteria without concrete verification

## Output structure

1. Per-requirement compliance table
2. Summary: total checks, pass count, fail count, partial count
3. Overall assessment: PASS / NEEDS WORK / FAIL
"""


class SpecComplianceChecker(BaseSkill):
    """Line-by-line gap analysis between specs and implementation artifacts."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the compliance report.
        """
        self._llm = llm
        super().__init__(
            name="spec_compliance_checker",
            description=(
                "Line-by-line gap analysis between specifications and "
                "implementation artifacts, defaulting to skepticism"
            ),
            required_context=["code_plan", "user_stories", "tech_spec"],
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
        """Run compliance check against the code plan.

        Args:
            context: Execution context with code plan, user stories, and tech spec.

        Returns:
            Artifact pointing to the compliance report.
        """
        params = context.parameters

        prompt_parts = [
            f"## Code plan\n{params['code_plan']}",
            f"## User stories\n{params['user_stories']}",
            f"## Technical specification\n{params['tech_spec']}",
        ]

        if "implementation_plan" in params:
            prompt_parts.append(
                f"## Implementation plan\n{params['implementation_plan']}"
            )
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "compliance_report.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="compliance_report",
            metadata={"framework": "spec_compliance"},
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_qa/test_spec_compliance_checker.py -v`

Expected: All 5 pass.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/qa/ tests/unit_tests/test_skills/test_qa/
git add src/superagents_sdlc/skills/qa/ tests/unit_tests/test_skills/test_qa/
git commit -m "feat(sdlc): add SpecComplianceChecker QA skill"
```

---

## Task 5: ValidationReportGenerator skill

**Files:**
- Create: `src/superagents_sdlc/skills/qa/validation_report_generator.py`
- Create: `tests/unit_tests/test_skills/test_qa/test_validation_report_generator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_skills/test_qa/test_validation_report_generator.py`:

```python
"""Tests for ValidationReportGenerator skill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient
from superagents_sdlc.skills.qa.validation_report_generator import (
    ValidationReportGenerator,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage with gaps.\n"
                "## Certification\nNEEDS WORK\n"
                "## Required Fixes\n- Add persistence tests"
            ),
        }
    )


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "compliance_report": "## Summary\nTotal: 2 | Pass: 1 | Fail: 1",
            "code_plan": "## Task 1: DarkModeToggle\n### RED\ntest_toggle",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
        },
        trace_id="trace-1",
    )


def test_validation_validate_passes(tmp_path):
    skill = ValidationReportGenerator(llm=_make_stub())
    skill.validate(_make_context(tmp_path))


def test_validation_validate_fails_missing_compliance(tmp_path):
    skill = ValidationReportGenerator(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["compliance_report"]
    with pytest.raises(SkillValidationError, match="compliance_report"):
        skill.validate(context)


def test_validation_validate_fails_missing_code_plan(tmp_path):
    skill = ValidationReportGenerator(llm=_make_stub())
    context = _make_context(tmp_path)
    del context.parameters["code_plan"]
    with pytest.raises(SkillValidationError, match="code_plan"):
        skill.validate(context)


async def test_validation_execute_writes_artifact(tmp_path):
    stub = _make_stub()
    skill = ValidationReportGenerator(llm=stub)
    context = _make_context(tmp_path)

    artifact = await skill.execute(context)

    assert (tmp_path / "validation_report.md").exists()
    assert artifact.artifact_type == "validation_report"
    assert artifact.path == str(tmp_path / "validation_report.md")
    assert artifact.metadata["certification"] == "NEEDS WORK"


async def test_validation_execute_includes_context_in_prompt(tmp_path):
    stub = _make_stub()
    skill = ValidationReportGenerator(llm=stub)
    context = _make_context(tmp_path)

    await skill.execute(context)

    prompt = stub.calls[0][0]
    assert "Pass: 1" in prompt  # compliance report content
    assert "DarkModeToggle" in prompt  # code plan content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_qa/test_validation_report_generator.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ValidationReportGenerator**

Create `src/superagents_sdlc/skills/qa/validation_report_generator.py`:

```python
"""ValidationReportGenerator — readiness certification skill.

Produces a structured certification report with honest quality ratings.
Default rating is NEEDS WORK — READY requires overwhelming evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from superagents_sdlc.skills.base import Artifact, BaseSkill, SkillValidationError

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import SkillContext
    from superagents_sdlc.skills.llm import LLMClient

_SYSTEM_PROMPT = """\
You are a senior QA lead producing a readiness certification. Your default \
rating is NEEDS WORK. READY requires overwhelming evidence of coverage. \
No A+ fantasies on first attempts.

## Required output structure

1. **Executive summary** — One-paragraph honest assessment
2. **Compliance results** — Summary of the compliance checker's findings
3. **Risk assessment** — What could go wrong if we proceed
4. **Required fixes** — Must-fix items before proceeding (if any)
5. **Recommended improvements** — Nice-to-have items
6. **Certification** — One of exactly three ratings:
   - **FAILED**: Critical gaps, missing requirements, fundamental design issues
   - **NEEDS WORK**: Partial coverage, addressable issues, proceed with fixes
   - **READY**: All requirements covered, risks mitigated, clear to proceed
"""

# Ordered by ascending severity; last match wins in _extract_certification.
_CERTIFICATIONS = ("READY", "NEEDS WORK", "FAILED")


def _extract_certification(response: str) -> str:
    """Extract certification rating from the tail of the report response.

    Scans only the last 10 lines (where the Certification section lives per
    the system prompt's output structure) to avoid matching stray occurrences
    in the compliance results body. Checks READY, NEEDS WORK, FAILED in
    priority order — FAILED wins if multiple are present.

    Args:
        response: Raw LLM response text.

    Returns:
        Certification string or "unknown" if not found.
    """
    tail = "\n".join(response.splitlines()[-10:])
    found = "unknown"
    # Iterates ascending severity; last match wins (FAILED > NEEDS WORK > READY)
    for cert in _CERTIFICATIONS:
        if cert in tail:
            found = cert
    return found


class ValidationReportGenerator(BaseSkill):
    """Generate a readiness certification with honest quality ratings."""

    def __init__(self, *, llm: LLMClient) -> None:
        """Initialize with an LLM client.

        Args:
            llm: LLM client for generating the validation report.
        """
        self._llm = llm
        super().__init__(
            name="validation_report_generator",
            description=(
                "Generate a structured readiness certification with "
                "honest quality ratings and required fixes"
            ),
            required_context=["compliance_report", "code_plan", "user_stories"],
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
        """Generate a validation report from compliance results.

        Args:
            context: Execution context with compliance report and code plan.

        Returns:
            Artifact pointing to the validation report.
        """
        params = context.parameters

        prompt_parts = [
            f"## Compliance report\n{params['compliance_report']}",
            f"## Code plan\n{params['code_plan']}",
            f"## User stories\n{params['user_stories']}",
        ]

        if "tech_spec" in params:
            prompt_parts.append(f"## Technical specification\n{params['tech_spec']}")
        if "implementation_plan" in params:
            prompt_parts.append(
                f"## Implementation plan\n{params['implementation_plan']}"
            )
        if "prd" in params:
            prompt_parts.append(f"## PRD\n{params['prd']}")

        prompt = "\n\n".join(prompt_parts)
        response = await self._llm.generate(prompt, system=_SYSTEM_PROMPT)

        output_path = context.artifact_dir / "validation_report.md"
        output_path.write_text(response)

        return Artifact(
            path=str(output_path),
            artifact_type="validation_report",
            metadata={"certification": _extract_certification(response)},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_skills/test_qa/ -v`

Expected: All 10 pass (5 compliance + 5 validation).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/skills/qa/ tests/unit_tests/test_skills/test_qa/
git add src/superagents_sdlc/skills/qa/validation_report_generator.py tests/unit_tests/test_skills/test_qa/test_validation_report_generator.py
git commit -m "feat(sdlc): add ValidationReportGenerator QA skill"
```

---

## Task 6: QAPersona + workflow tests

**Files:**
- Create: `src/superagents_sdlc/personas/qa.py`
- Create: `tests/unit_tests/test_personas/test_qa.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit_tests/test_personas/test_qa.py`:

```python
"""Tests for QAPersona."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from superagents_sdlc.handoffs.contract import PersonaHandoff
from superagents_sdlc.handoffs.registry import PersonaRegistry
from superagents_sdlc.handoffs.transport import InProcessTransport
from superagents_sdlc.personas.qa import QAPersona
from superagents_sdlc.policy.config import PolicyConfig
from superagents_sdlc.policy.engine import PolicyEngine
from superagents_sdlc.policy.gates import AutoApprovalGate
from superagents_sdlc.skills.base import SkillContext, SkillValidationError
from superagents_sdlc.skills.llm import StubLLMClient

if TYPE_CHECKING:
    from pathlib import Path


def _make_stub_llm() -> StubLLMClient:
    return StubLLMClient(
        responses={
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Dark mode toggle | PASS |\n"
                "| Theme persistence | FAIL |\n"
                "## Summary\nTotal: 2 | Pass: 1 | Fail: 1\n"
                "Overall: NEEDS WORK"
            ),
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage.\n"
                "## Certification\nNEEDS WORK"
            ),
        }
    )


def _make_qa(
    tmp_path: Path,
    *,
    stub_llm: StubLLMClient | None = None,
) -> tuple[QAPersona, StubLLMClient]:
    llm = stub_llm or _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    qa = QAPersona(llm=llm, policy_engine=engine, transport=transport)
    registry.register(qa)
    return qa, llm


def _make_context(tmp_path: Path) -> SkillContext:
    return SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "code_plan": "## Task 1: DarkModeToggle\n### RED\ntest_toggle",
            "user_stories": "As a PM, I want dark mode so I reduce eye strain",
            "tech_spec": "# Tech Spec\n## Architecture\nREST API with PostgreSQL",
        },
        trace_id="trace-1",
    )


def test_qa_has_two_skills(tmp_path):
    qa, _ = _make_qa(tmp_path)
    assert "spec_compliance_checker" in qa.skills
    assert "validation_report_generator" in qa.skills
    assert len(qa.skills) == 2


async def test_qa_receive_handoff_stores(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    handoff = PersonaHandoff(
        source_persona="developer",
        target_persona="qa",
        artifact_type="code",
        artifact_path="/code_plan.md",
        context_summary="Code plan ready",
        autonomy_level=2,
        requires_approval=False,
        trace_id="trace-1",
        parent_span_id="span-1",
    )
    await qa.receive_handoff(handoff)
    assert len(qa.received) == 1
    assert qa.received[0].source_persona == "developer"


async def test_qa_workflow_runs_two_skills_in_order(exporter, tmp_path):
    qa, stub_llm = _make_qa(tmp_path)
    context = _make_context(tmp_path)

    await qa.run_validation(context)

    prompts = [call[0] for call in stub_llm.calls]
    assert len(prompts) == 2
    # First call: compliance checker gets code plan
    assert "## Code plan\n" in prompts[0]
    # Second call: validation report gets compliance report
    assert "## Compliance report\n" in prompts[1]


async def test_qa_workflow_returns_two_artifacts(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await qa.run_validation(context)

    assert len(artifacts) == 2
    assert artifacts[0].artifact_type == "compliance_report"
    assert artifacts[1].artifact_type == "validation_report"


async def test_qa_workflow_emits_persona_span(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    context = _make_context(tmp_path)

    await qa.run_validation(context)

    spans = exporter.get_finished_spans()
    persona_spans = [s for s in spans if s.name == "persona.qa"]
    assert len(persona_spans) == 1

    skill_spans = [s for s in spans if s.name.startswith("skill.")]
    for ss in skill_spans:
        assert ss.parent is not None
        assert ss.parent.span_id == persona_spans[0].context.span_id


async def test_qa_preflight_fails_missing_context(exporter, tmp_path):
    qa, _ = _make_qa(tmp_path)
    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "user_stories": "stories",
            "tech_spec": "spec",
        },
        trace_id="trace-1",
    )

    with pytest.raises(SkillValidationError, match="code_plan"):
        await qa.run_validation(context)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_qa.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'superagents_sdlc.personas.qa'`

- [ ] **Step 3: Implement QAPersona**

Create `src/superagents_sdlc/personas/qa.py`:

```python
"""QA persona — compliance checking and validation reporting."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from superagents.telemetry import persona_span

from superagents_sdlc.personas.base import BasePersona
from superagents_sdlc.skills.base import SkillValidationError
from superagents_sdlc.skills.qa.spec_compliance_checker import SpecComplianceChecker
from superagents_sdlc.skills.qa.validation_report_generator import (
    ValidationReportGenerator,
)

if TYPE_CHECKING:
    from superagents_sdlc.handoffs.contract import PersonaHandoff
    from superagents_sdlc.handoffs.transport import Transport
    from superagents_sdlc.policy.engine import PolicyEngine
    from superagents_sdlc.skills.base import Artifact, SkillContext
    from superagents_sdlc.skills.llm import LLMClient

logger = logging.getLogger(__name__)

_REQUIRED_CONTEXT = ("code_plan", "user_stories", "tech_spec")


class QAPersona(BasePersona):
    """QA persona performing compliance checking and readiness certification."""

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
            "spec_compliance_checker": SpecComplianceChecker(llm=llm),
            "validation_report_generator": ValidationReportGenerator(llm=llm),
        }
        super().__init__(
            name="qa",
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
            "QA received handoff from %s: %s",
            handoff.source_persona,
            handoff.artifact_type,
        )

    async def run_validation(self, context: SkillContext) -> list[Artifact]:
        """Run the validation workflow.

        Linear pipeline: compliance check → validation report.

        Args:
            context: Execution context with code_plan, user_stories, tech_spec.

        Returns:
            List of two artifacts: [compliance_report, validation_report].

        Raises:
            SkillValidationError: If required context keys are missing.
        """
        # Pre-flight: fail fast before persona_span opens to avoid orphaned traces.
        # Skills also validate in execute_skill(), but that's inside the span.
        for key in _REQUIRED_CONTEXT:
            if key not in context.parameters:
                msg = f"Missing required context for QA workflow: {key}"
                raise SkillValidationError(msg)

        level = self.policy_engine.config.level_for(self.name)

        with persona_span(self.name, autonomy_level=level):
            # Step 1: Run compliance check
            compliance_artifact = await self.execute_skill(
                "spec_compliance_checker", context
            )
            compliance_content = Path(compliance_artifact.path).read_text()
            context.parameters["compliance_report"] = compliance_content

            # Step 2: Generate validation report
            validation_artifact = await self.execute_skill(
                "validation_report_generator", context
            )

        return [compliance_artifact, validation_artifact]

    async def handle_handoff(
        self, handoff: PersonaHandoff, context: SkillContext
    ) -> list[Artifact]:
        """Build context from a handoff and run the validation workflow.

        Reads the code plan from the primary artifact and loads tech spec,
        user stories, and optional context from metadata paths.

        Args:
            handoff: Incoming handoff with artifact path and metadata.
            context: Execution context (parameters will be populated).

        Returns:
            List of artifacts from the workflow.
        """
        # Required: code plan from primary artifact
        context.parameters["code_plan"] = Path(handoff.artifact_path).read_text()

        # Required: tech spec and user stories from metadata
        tech_spec_path = handoff.metadata["tech_spec_path"]
        context.parameters["tech_spec"] = Path(tech_spec_path).read_text()

        user_stories_path = handoff.metadata["user_stories_path"]
        context.parameters["user_stories"] = Path(user_stories_path).read_text()

        # Optional: implementation plan and PRD
        for meta_key, param_key in [
            ("implementation_plan_path", "implementation_plan"),
            ("prd_path", "prd"),
        ]:
            path_str = handoff.metadata.get(meta_key, "")
            if path_str:
                file_path = Path(path_str)
                if file_path.exists():
                    context.parameters[param_key] = file_path.read_text()

        return await self.run_validation(context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_qa.py -v`

Expected: All 6 pass.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/personas/qa.py tests/unit_tests/test_personas/test_qa.py
git add src/superagents_sdlc/personas/qa.py tests/unit_tests/test_personas/test_qa.py
git commit -m "feat(sdlc): add QAPersona with compliance-and-validation workflow"
```

---

## Task 7: Metadata chain fix + Developer conditional handoff

**Files:**
- Modify: `src/superagents_sdlc/personas/architect.py` (store `user_stories_path` for downstream forwarding)
- Modify: `src/superagents_sdlc/personas/developer.py` (conditional handoff + path forwarding)
- Modify: `tests/unit_tests/test_personas/test_developer.py`

- [ ] **Step 0: Fix Architect metadata chain**

In `src/superagents_sdlc/personas/architect.py`, update `handle_handoff` to store
the user stories path for downstream forwarding. The handoff artifact IS the user
stories file, so:

Add this line in `handle_handoff` after reading user stories content:

```python
        context.parameters["user_stories"] = Path(handoff.artifact_path).read_text()
        context.parameters["user_stories_path"] = handoff.artifact_path  # NEW: forward path
```

This closes the metadata chain: PM → (user_stories artifact) → Architect stores path →
forwards in metadata to Developer → Developer forwards to QA.

Verify existing Architect tests still pass:

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_architect.py -v`

Expected: All 9 pass (storing an extra key doesn't break anything).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit_tests/test_personas/test_developer.py`:

```python
from typing import Any

from superagents_sdlc.personas.base import BasePersona


class StubQAPersona(BasePersona):
    """Stub QA that stores received handoffs."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.received: list[PersonaHandoff] = []

    async def receive_handoff(self, handoff: PersonaHandoff) -> None:
        self.received.append(handoff)


async def test_developer_conditional_handoff_to_qa(exporter, tmp_path):
    """When QA is registered, Developer hands off with full metadata."""
    llm = _make_stub_llm()
    config = PolicyConfig(autonomy_level=2)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())
    registry = PersonaRegistry()
    transport = InProcessTransport(registry=registry)

    dev = DeveloperPersona(llm=llm, policy_engine=engine, transport=transport)
    qa = StubQAPersona(
        name="qa",
        skills={},
        policy_engine=PolicyEngine(config=config, gate=AutoApprovalGate()),
        transport=InProcessTransport(registry=registry),
    )
    registry.register(dev)
    registry.register(qa)

    context = SkillContext(
        artifact_dir=tmp_path,
        parameters={
            "implementation_plan": "## Tasks\n1. Create model",
            "tech_spec": "# Tech Spec\nREST API",
            "tech_spec_path": "/artifacts/spec.md",
            "user_stories_path": "/artifacts/stories.md",
            "implementation_plan_path": "/artifacts/plan.md",
            "prd_path": "/artifacts/prd.md",
        },
        trace_id="trace-1",
    )

    await dev.run_plan_from_spec(context)

    assert len(qa.received) == 1
    handoff = qa.received[0]
    assert handoff.source_persona == "developer"
    assert handoff.target_persona == "qa"
    assert handoff.artifact_type == "code"
    assert handoff.metadata["tech_spec_path"] == "/artifacts/spec.md"
    assert handoff.metadata["user_stories_path"] == "/artifacts/stories.md"
    assert handoff.metadata["implementation_plan_path"] == "/artifacts/plan.md"
    assert handoff.metadata["prd_path"] == "/artifacts/prd.md"
```

Also add a negative test to verify the inverse — no handoff when QA is NOT registered:

```python
async def test_developer_no_handoff_without_qa(exporter, tmp_path):
    """When QA is not registered, Developer skips handoff silently."""
    dev, _ = _make_developer(tmp_path)
    context = _make_context(tmp_path)

    artifacts = await dev.run_plan_from_spec(context)

    assert len(artifacts) == 1
    # No handoff span should exist for developer→qa
    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    dev_to_qa = [s for s in handoff_spans if "qa" in s.attributes.get("handoff.target", "")]
    assert len(dev_to_qa) == 0
```

Also add `from typing import Any` and `from superagents_sdlc.personas.base import BasePersona` to the imports at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_developer.py::test_developer_conditional_handoff_to_qa -v`

Expected: FAIL — QA persona not receiving handoff (Developer doesn't send one yet).

- [ ] **Step 3: Modify Developer persona**

In `src/superagents_sdlc/personas/developer.py`:

1. Update `run_plan_from_spec` — replace lines 87-90:

```python
        with persona_span(self.name, autonomy_level=level):
            code_plan_artifact = await self.execute_skill("code_planner", context)

        return [code_plan_artifact]
```

With:

```python
        with persona_span(self.name, autonomy_level=level):
            code_plan_artifact = await self.execute_skill("code_planner", context)

            # Conditional: hand off to QA if registered
            if self.transport.can_reach("qa"):
                await self.request_handoff(
                    target="qa",
                    artifact=code_plan_artifact,
                    context_summary="Code plan ready for compliance review",
                    metadata={
                        "tech_spec_path": context.parameters.get(
                            "tech_spec_path", ""
                        ),
                        "user_stories_path": context.parameters.get(
                            "user_stories_path", ""
                        ),
                        "implementation_plan_path": context.parameters.get(
                            "implementation_plan_path", ""
                        ),
                        "prd_path": context.parameters.get("prd_path", ""),
                    },
                )

        return [code_plan_artifact]
```

2. Update `handle_handoff` — add path storage alongside content reads. Replace lines 108-121:

```python
        context.parameters["implementation_plan"] = Path(handoff.artifact_path).read_text()
        context.parameters["implementation_plan_path"] = handoff.artifact_path

        tech_spec_path = handoff.metadata["tech_spec_path"]
        context.parameters["tech_spec"] = Path(tech_spec_path).read_text()
        context.parameters["tech_spec_path"] = tech_spec_path

        # Forward optional path metadata for downstream handoffs
        context.parameters["user_stories_path"] = handoff.metadata.get(
            "user_stories_path", ""
        )
        context.parameters["prd_path"] = handoff.metadata.get("prd_path", "")

        for meta_key, param_key in [
            ("user_stories_path", "user_stories"),
            ("prd_path", "prd"),
        ]:
            path_str = handoff.metadata.get(meta_key, "")
            if path_str:
                file_path = Path(path_str)
                if file_path.exists():
                    context.parameters[param_key] = file_path.read_text()
```

- [ ] **Step 4: Run ALL Developer tests to verify no regressions**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_developer.py -v`

Expected: All 8 tests pass (6 existing + 2 new). Existing tests don't register QA, so `can_reach("qa")` returns False and the handoff is skipped.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check src/superagents_sdlc/personas/developer.py tests/unit_tests/test_personas/test_developer.py
git add src/superagents_sdlc/personas/developer.py tests/unit_tests/test_personas/test_developer.py
git commit -m "feat(sdlc): add conditional Developer→QA handoff with path forwarding"
```

---

## Task 8: Pipeline integration tests

**Files:**
- Modify: `tests/unit_tests/test_personas/test_pipeline.py`

- [ ] **Step 1: Write the pipeline tests**

Add to `tests/unit_tests/test_personas/test_pipeline.py`:

1. Add import:
```python
from superagents_sdlc.personas.qa import QAPersona
```

2. Update `_make_pipeline_llm` to add QA skill responses — add these entries to the responses dict:
```python
            # QA skills
            "## Code plan\n": (
                "## Compliance Check\n"
                "| Dark mode toggle | PASS |\n"
                "| Theme persistence | FAIL |\n"
                "## Summary\nTotal: 2 | Pass: 1 | Fail: 1\n"
                "Overall: NEEDS WORK"
            ),
            "## Compliance report\n": (
                "# Validation Report\n"
                "## Executive Summary\nPartial coverage.\n"
                "## Certification\nNEEDS WORK"
            ),
```

3. Add `_make_pipeline_with_qa` helper:
```python
def _make_pipeline_with_qa(
    tmp_path: Path,
    *,
    autonomy_level: int = 2,
    gate=None,
) -> tuple[
    ProductManagerPersona, ArchitectPersona, DeveloperPersona, QAPersona, StubLLMClient
]:
    """Wire up the full PM → Architect → Developer → QA pipeline."""
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
    qa = QAPersona(llm=stub_llm, policy_engine=engine, transport=transport)

    registry.register(pm)
    registry.register(architect)
    registry.register(developer)
    registry.register(qa)

    return pm, architect, developer, qa, stub_llm
```

4. Add `_run_full_pipeline_with_qa` helper:
```python
async def _run_full_pipeline_with_qa(
    tmp_path: Path,
    pm: ProductManagerPersona,
    architect: ArchitectPersona,
    developer: DeveloperPersona,
    qa: QAPersona,
) -> tuple[list, list, list, list]:
    """Run PM → Architect → Developer → QA and return all artifact lists."""
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
    prd_content = Path(pm_artifacts[1].path).read_text()
    arch_context = SkillContext(
        artifact_dir=tmp_path / "architect",
        parameters={
            "prd": prd_content,
            "product_context": "B2B SaaS platform",
        },
        trace_id="trace-pipeline",
    )
    (tmp_path / "architect").mkdir()
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

    # QA: handle handoff from developer
    qa_context = SkillContext(
        artifact_dir=tmp_path / "qa",
        parameters={},
        trace_id="trace-pipeline",
    )
    (tmp_path / "qa").mkdir()
    qa_handoff = qa.received[-1]
    qa_artifacts = await qa.handle_handoff(qa_handoff, qa_context)

    return pm_artifacts, arch_artifacts, dev_artifacts, qa_artifacts
```

5. Add the 5 pipeline tests:
```python
async def test_pipeline_pm_to_qa(exporter, tmp_path):
    pm, architect, developer, qa, stub_llm = _make_pipeline_with_qa(tmp_path)

    pm_art, arch_art, dev_art, qa_art = await _run_full_pipeline_with_qa(
        tmp_path, pm, architect, developer, qa
    )

    all_artifacts = pm_art + arch_art + dev_art + qa_art
    assert len(all_artifacts) == 8
    types = [a.artifact_type for a in all_artifacts]
    assert types == [
        "backlog",
        "prd",
        "user_story",
        "tech_spec",
        "implementation_plan",
        "code",
        "compliance_report",
        "validation_report",
    ]

    # Verify tech spec content reached QA's compliance checker prompt via metadata
    qa_prompt = [c[0] for c in stub_llm.calls if "## Code plan\n" in c[0]]
    assert len(qa_prompt) >= 1


async def test_pipeline_emits_four_persona_spans(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(tmp_path)

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    spans = exporter.get_finished_spans()
    persona_names = {s.name for s in spans if s.name.startswith("persona.")}
    assert "persona.product_manager" in persona_names
    assert "persona.architect" in persona_names
    assert "persona.developer" in persona_names
    assert "persona.qa" in persona_names


async def test_pipeline_four_persona_handoff_chain(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(tmp_path)

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    spans = exporter.get_finished_spans()
    handoff_spans = [s for s in spans if s.name.startswith("handoff.")]
    sources_targets = [
        (s.attributes["handoff.source"], s.attributes["handoff.target"])
        for s in handoff_spans
    ]
    assert ("product_manager", "architect") in sources_targets
    assert ("architect", "developer") in sources_targets
    assert ("developer", "qa") in sources_targets


async def test_pipeline_level_2_code_handoff_requires_approval(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(
        tmp_path, autonomy_level=2, gate=MockApprovalGate(should_approve=True)
    )

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    spans = exporter.get_finished_spans()
    gate_spans = [s for s in spans if s.name.startswith("approval_gate.")]
    # Developer→QA handoff carries code artifact → requires approval at L2
    dev_to_qa = [
        gs for gs in gate_spans if "developer_to_qa" in gs.name
    ]
    assert len(dev_to_qa) == 1
    assert dev_to_qa[0].attributes["approval.required"] is True
    assert dev_to_qa[0].attributes["approval.outcome"] == "approved"

    # PM→Architect and Architect→Developer carry planning artifacts → auto-proceed
    planning_gates = [
        gs for gs in gate_spans if "developer_to_qa" not in gs.name
    ]
    for pg in planning_gates:
        assert pg.attributes["approval.outcome"] == "auto_proceeded"


async def test_pipeline_metadata_reaches_qa(exporter, tmp_path):
    pm, architect, developer, qa, _ = _make_pipeline_with_qa(tmp_path)

    await _run_full_pipeline_with_qa(tmp_path, pm, architect, developer, qa)

    # Verify QA received a handoff with metadata containing upstream paths
    assert len(qa.received) == 1
    meta = qa.received[0].metadata
    assert "tech_spec_path" in meta
    assert meta["tech_spec_path"] != ""
    # Verify the QA context was populated from those paths
    # (the fact that qa_artifacts were produced proves handle_handoff worked)
```

- [ ] **Step 2: Run pipeline tests**

Run: `.venv/bin/python -m pytest tests/unit_tests/test_personas/test_pipeline.py -v`

Expected: All 10 tests pass (5 existing + 5 new).

- [ ] **Step 3: Lint and commit**

```bash
.venv/bin/ruff check tests/unit_tests/test_personas/test_pipeline.py
git add tests/unit_tests/test_personas/test_pipeline.py
git commit -m "test(sdlc): add end-to-end PM→Architect→Developer→QA pipeline tests"
```

---

## Task 9: Re-exports + final verification

**Files:**
- Modify: `src/superagents_sdlc/skills/qa/__init__.py`
- Modify: `src/superagents_sdlc/personas/__init__.py`

- [ ] **Step 1: Update QA skills `__init__.py`**

```python
"""QA skills — compliance checking and validation reporting."""

from superagents_sdlc.skills.qa.spec_compliance_checker import SpecComplianceChecker
from superagents_sdlc.skills.qa.validation_report_generator import (
    ValidationReportGenerator,
)

__all__ = ["SpecComplianceChecker", "ValidationReportGenerator"]
```

- [ ] **Step 2: Update personas `__init__.py`**

Add QAPersona import and update `__all__`. Read the file first to see current state, then add:

```python
from superagents_sdlc.personas.qa import QAPersona
```

And add `"QAPersona"` to `__all__`.

- [ ] **Step 3: Run full SDLC test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: All 147 tests pass (118 existing + 29 new).

- [ ] **Step 4: Run Phase 1 telemetry tests (regression check)**

Run: `cd ../superagents && .venv/bin/python -m pytest tests/unit_tests/test_telemetry/ -v`

Expected: All 15 pass.

- [ ] **Step 5: Full lint + format check**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/`

Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add src/superagents_sdlc/skills/qa/__init__.py src/superagents_sdlc/personas/__init__.py
git commit -m "feat(sdlc): add Phase 5 re-exports for QA skills and persona"
```
