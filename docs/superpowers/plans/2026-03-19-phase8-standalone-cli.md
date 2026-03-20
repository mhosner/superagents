# Phase 8: Standalone `superagents-sdlc` CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap `PipelineOrchestrator` in a standalone argparse CLI with real Anthropic LLM integration.

**Architecture:** Thin `cli.py` entry point parses args, loads context files, wires `PolicyEngine` + LLM client, calls orchestrator, prints progress and results. `AnthropicLLMClient` is the first real `LLMClient` protocol implementation, using `anthropic.AsyncAnthropic`. The `anthropic` package is an optional extra — `--stub` flag uses `StubLLMClient` with inline canned responses for testing without it.

**Tech Stack:** Python 3.12+, argparse, anthropic SDK (optional), asyncio

**Spec:** `docs/superpowers/specs/2026-03-19-phase8-standalone-cli-design.md`

---

## File Structure

| Action | Path | Responsibility |
| ------ | ---- | -------------- |
| Modify | `libs/sdlc/pyproject.toml` | Add optional `[anthropic]` extra, console script entry point |
| Modify | `libs/sdlc/src/superagents_sdlc/skills/llm.py` | Add `AnthropicLLMClient` class |
| Modify | `libs/sdlc/src/superagents_sdlc/skills/__init__.py` | Re-export `AnthropicLLMClient` |
| Modify | `libs/sdlc/src/superagents_sdlc/workflows/orchestrator.py` | Add `on_phase_complete` callback to `run_*` methods |
| Create | `libs/sdlc/src/superagents_sdlc/cli.py` | CLI entry point: arg parsing, context loading, orchestrator wiring |
| Create | `libs/sdlc/tests/unit_tests/test_cli.py` | CLI tests (11 tests) |

---

### Task 1: Add `on_phase_complete` callback to orchestrator

Add an optional progress callback to the three `run_*` methods so the CLI can print real-time phase transitions.

**Files:**

- Modify: `libs/sdlc/src/superagents_sdlc/workflows/orchestrator.py`
- Test: `libs/sdlc/tests/unit_tests/test_workflows/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Add to `libs/sdlc/tests/unit_tests/test_workflows/test_orchestrator.py`:

```python
async def test_idea_to_code_calls_phase_callback(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()
    phases: list[tuple[str, int]] = []

    def on_phase(name, artifacts):
        phases.append((name, len(artifacts)))

    await orchestrator.run_idea_to_code(
        "Add dark mode", artifact_dir=tmp_path, on_phase_complete=on_phase
    )

    assert phases == [("pm", 3), ("architect", 2), ("developer", 1), ("qa", 2)]


async def test_spec_from_prd_calls_phase_callback(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()
    phases: list[tuple[str, int]] = []

    prd_path = tmp_path / "input_prd.md"
    prd_path.write_text("# PRD: Dark Mode\n## Problem\nEye strain")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    def on_phase(name, artifacts):
        phases.append((name, len(artifacts)))

    await orchestrator.run_spec_from_prd(
        str(prd_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
        on_phase_complete=on_phase,
    )

    assert phases == [("architect", 2), ("developer", 1), ("qa", 2)]


async def test_plan_from_spec_calls_phase_callback(exporter, tmp_path):
    orchestrator, _ = _make_orchestrator()
    phases: list[tuple[str, int]] = []

    plan_path = tmp_path / "input_plan.md"
    plan_path.write_text("## Tasks\n1. Create model")

    spec_path = tmp_path / "input_spec.md"
    spec_path.write_text("# Tech Spec\nREST API")

    stories_path = tmp_path / "input_stories.md"
    stories_path.write_text("As a PM, I want dark mode")

    def on_phase(name, artifacts):
        phases.append((name, len(artifacts)))

    await orchestrator.run_plan_from_spec(
        implementation_plan_path=str(plan_path),
        tech_spec_path=str(spec_path),
        user_stories_path=str(stories_path),
        artifact_dir=tmp_path / "output",
        on_phase_complete=on_phase,
    )

    assert phases == [("developer", 1), ("qa", 2)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_workflows/test_orchestrator.py -k "phase_callback" -v`
Expected: FAIL with `TypeError: run_idea_to_code() got an unexpected keyword argument 'on_phase_complete'`

- [ ] **Step 3: Implement callback on all three run_* methods**

In `libs/sdlc/src/superagents_sdlc/workflows/orchestrator.py`:

Add to the `TYPE_CHECKING` block (line 17):

```python
from collections.abc import Callable
```

Update `run_idea_to_code` signature — add after `context_overrides`:

```python
        on_phase_complete: Callable[[str, list[Artifact]], None] | None = None,
```

Add callback calls after each phase. After `pm_artifacts = await self._pm.run_idea_to_sprint(...)`:

```python
        if on_phase_complete:
            on_phase_complete("pm", pm_artifacts)
```

After `arch_artifacts = await self._architect.handle_handoff(...)`:

```python
        if on_phase_complete:
            on_phase_complete("architect", arch_artifacts)
```

After `dev_artifacts = await self._developer.handle_handoff(...)`:

```python
        if on_phase_complete:
            on_phase_complete("developer", dev_artifacts)
```

After `qa_artifacts = await self._qa.handle_handoff(...)`:

```python
        if on_phase_complete:
            on_phase_complete("qa", qa_artifacts)
```

Update docstring Args to include:

```text
            on_phase_complete: Optional callback invoked after each persona phase
                with (phase_name, artifacts). Phase names: "pm", "architect",
                "developer", "qa".
```

Apply the same pattern to `run_spec_from_prd` — add `on_phase_complete` parameter, call after architect, developer, qa phases.

Apply the same pattern to `run_plan_from_spec` — add `on_phase_complete` parameter, call after developer, qa phases.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_workflows/test_orchestrator.py -k "phase_callback" -v`
Expected: All 3 PASS

- [ ] **Step 5: Run full orchestrator tests**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_workflows/test_orchestrator.py -v`
Expected: All 15 tests PASS (12 existing + 3 new)

- [ ] **Step 6: Lint**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/superagents_sdlc/workflows/orchestrator.py`
Expected: Clean

- [ ] **Step 7: Commit**

```bash
cd /home/matt/coding/superagents/libs/sdlc
git add src/superagents_sdlc/workflows/orchestrator.py tests/unit_tests/test_workflows/test_orchestrator.py
git commit -m "feat(sdlc): add on_phase_complete callback to orchestrator run methods"
```

---

### Task 2: Add `AnthropicLLMClient`

Implement the first real `LLMClient` using `anthropic.AsyncAnthropic` with guarded import.

**Files:**

- Modify: `libs/sdlc/src/superagents_sdlc/skills/llm.py`
- Modify: `libs/sdlc/src/superagents_sdlc/skills/__init__.py`
- Modify: `libs/sdlc/pyproject.toml`
- Test: `libs/sdlc/tests/unit_tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `libs/sdlc/tests/unit_tests/test_cli.py`:

```python
"""Tests for the standalone CLI and AnthropicLLMClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from superagents_sdlc.skills.llm import LLMClient


def test_anthropic_client_satisfies_protocol():
    mock_anthropic = MagicMock()
    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        from superagents_sdlc.skills.llm import AnthropicLLMClient

        client = AnthropicLLMClient(model="claude-sonnet-4-6")
        assert isinstance(client, LLMClient)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py::test_anthropic_client_satisfies_protocol -v`
Expected: FAIL with `ImportError: cannot import name 'AnthropicLLMClient'`

- [ ] **Step 3: Implement AnthropicLLMClient**

Add to the end of `libs/sdlc/src/superagents_sdlc/skills/llm.py`:

```python
class AnthropicLLMClient:
    """LLMClient implementation using Anthropic's API.

    Requires the ``anthropic`` package (``pip install superagents-sdlc[anthropic]``).
    Uses ``AsyncAnthropic`` for async-native HTTP calls.

    Attributes:
        model: Anthropic model identifier.
    """

    def __init__(self, *, model: str = "claude-sonnet-4-6", api_key: str | None = None) -> None:
        """Initialize with model and optional API key.

        Args:
            model: Anthropic model to use.
            api_key: API key. Falls back to ``ANTHROPIC_API_KEY`` env var if omitted.

        Raises:
            ImportError: If the ``anthropic`` package is not installed.
        """
        try:
            import anthropic  # noqa: PLC0415
        except ImportError:
            msg = (
                "anthropic package not installed. "
                "Run: pip install superagents-sdlc[anthropic]"
            )
            raise ImportError(msg) from None

        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, prompt: str, *, system: str = "") -> str:
        """Generate a response via the Anthropic API.

        Args:
            prompt: User prompt.
            system: Optional system prompt.

        Returns:
            Raw response text.
        """
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        return response.content[0].text
```

- [ ] **Step 4: Add re-export to skills/__init__.py**

In `libs/sdlc/src/superagents_sdlc/skills/__init__.py`:

Change the import line to:

```python
from superagents_sdlc.skills.llm import AnthropicLLMClient, LLMClient, StubLLMClient
```

Change `__all__` to:

```python
__all__ = [
    "AnthropicLLMClient",
    "Artifact",
    "BaseSkill",
    "LLMClient",
    "SkillContext",
    "SkillValidationError",
    "StubLLMClient",
]
```

- [ ] **Step 5: Add optional dependency to pyproject.toml**

Add after the `[dependency-groups]` section in `libs/sdlc/pyproject.toml`:

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.40.0"]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py::test_anthropic_client_satisfies_protocol -v`
Expected: PASS

- [ ] **Step 7: Lint**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/superagents_sdlc/skills/llm.py src/superagents_sdlc/skills/__init__.py`
Expected: Clean

- [ ] **Step 8: Commit**

```bash
cd /home/matt/coding/superagents/libs/sdlc
git add src/superagents_sdlc/skills/llm.py src/superagents_sdlc/skills/__init__.py pyproject.toml
git commit -m "feat(sdlc): add AnthropicLLMClient with guarded import and optional extra"
```

---

### Task 3: Context directory loader

Implement `_load_context()` with tests.

**Files:**

- Create: `libs/sdlc/src/superagents_sdlc/cli.py`
- Test: `libs/sdlc/tests/unit_tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `libs/sdlc/tests/unit_tests/test_cli.py`:

```python
import pytest

from superagents_sdlc.cli import _load_context


def test_load_context_reads_all_files(tmp_path):
    (tmp_path / "product_context.md").write_text("Product info")
    (tmp_path / "goals_context.md").write_text("Goals info")
    (tmp_path / "personas_context.md").write_text("Personas info")

    result = _load_context(str(tmp_path))

    assert result == {
        "product_context": "Product info",
        "goals_context": "Goals info",
        "personas_context": "Personas info",
    }


def test_load_context_skips_missing_files(tmp_path):
    (tmp_path / "product_context.md").write_text("Product only")

    result = _load_context(str(tmp_path))

    assert result == {"product_context": "Product only"}


def test_load_context_none_returns_empty():
    result = _load_context(None)

    assert result == {}


def test_load_context_invalid_dir_raises():
    with pytest.raises(FileNotFoundError):
        _load_context("/nonexistent/path/that/does/not/exist")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py -k "load_context" -v`
Expected: FAIL with `ImportError: cannot import name '_load_context'`

- [ ] **Step 3: Implement _load_context**

Create `libs/sdlc/src/superagents_sdlc/cli.py`:

```python
"""Standalone CLI for superagents-sdlc pipelines."""

from __future__ import annotations

from pathlib import Path

# Named context files recognized by the loader.
_CONTEXT_FILES: dict[str, str] = {
    "product_context.md": "product_context",
    "goals_context.md": "goals_context",
    "personas_context.md": "personas_context",
}


def _load_context(context_dir: str | None) -> dict[str, str]:
    """Load context from named markdown files in a directory.

    Args:
        context_dir: Path to the context directory, or None for empty context.

    Returns:
        Dict mapping context keys to file contents.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if context_dir is None:
        return {}

    directory = Path(context_dir)
    if not directory.is_dir():
        msg = f"Context directory not found: {context_dir}"
        raise FileNotFoundError(msg)

    context: dict[str, str] = {}
    for filename, key in _CONTEXT_FILES.items():
        filepath = directory / filename
        if filepath.exists():
            context[key] = filepath.read_text()
    return context
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py -k "load_context" -v`
Expected: All 4 PASS

- [ ] **Step 5: Lint**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/superagents_sdlc/cli.py tests/unit_tests/test_cli.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/matt/coding/superagents/libs/sdlc
git add src/superagents_sdlc/cli.py tests/unit_tests/test_cli.py
git commit -m "feat(sdlc): add context directory loader for CLI"
```

---

### Task 4: CLI argument parsing

Implement the argparse parser with three subcommands and global flags.

**Files:**

- Modify: `libs/sdlc/src/superagents_sdlc/cli.py`
- Test: `libs/sdlc/tests/unit_tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `libs/sdlc/tests/unit_tests/test_cli.py`:

```python
from superagents_sdlc.cli import _build_parser


def test_parse_idea_to_code():
    parser = _build_parser()
    args = parser.parse_args([
        "idea-to-code", "Add dark mode",
        "--output-dir", "/tmp/out",
    ])

    assert args.command == "idea-to-code"
    assert args.idea == "Add dark mode"
    assert args.output_dir == "/tmp/out"
    assert args.autonomy_level == 3
    assert args.model == "claude-sonnet-4-6"
    assert args.stub is False
    assert args.json is False
    assert args.context_dir is None


def test_parse_spec_from_prd():
    parser = _build_parser()
    args = parser.parse_args([
        "spec-from-prd", "/path/prd.md",
        "--user-stories", "/path/stories.md",
        "--output-dir", "/tmp/out",
        "--autonomy-level", "2",
    ])

    assert args.command == "spec-from-prd"
    assert args.prd_path == "/path/prd.md"
    assert args.user_stories == "/path/stories.md"
    assert args.autonomy_level == 2


def test_parse_plan_from_spec():
    parser = _build_parser()
    args = parser.parse_args([
        "plan-from-spec",
        "--plan", "/path/plan.md",
        "--spec", "/path/spec.md",
        "--output-dir", "/tmp/out",
        "--stub",
    ])

    assert args.command == "plan-from-spec"
    assert args.plan == "/path/plan.md"
    assert args.spec == "/path/spec.md"
    assert args.user_stories is None
    assert args.stub is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py -k "test_parse" -v`
Expected: FAIL with `ImportError: cannot import name '_build_parser'`

- [ ] **Step 3: Implement _build_parser**

Add to `libs/sdlc/src/superagents_sdlc/cli.py`:

```python
import argparse


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured ArgumentParser with subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="superagents-sdlc",
        description="Run SDLC persona pipelines from the command line.",
    )

    # Global flags (on parent parser — work before or after subcommand)
    parser.add_argument(
        "--context-dir",
        default=None,
        help="Directory with named context .md files (optional).",
    )
    parser.add_argument(
        "--autonomy-level",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Policy engine autonomy level (default: 3).",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model to use (default: claude-sonnet-4-6).",
    )

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--quiet", action="store_true", help="Suppress all output except errors."
    )

    parser.add_argument(
        "--json", action="store_true", dest="json", help="Dump PipelineResult as JSON to stdout."
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use StubLLMClient instead of Anthropic (development testing only).",
    )

    # Subcommands — each has its own --output-dir to avoid argparse ordering issues
    subparsers = parser.add_subparsers(dest="command", required=True)

    # idea-to-code
    idea_parser = subparsers.add_parser(
        "idea-to-code", help="Run full pipeline: PM -> Arch -> Dev -> QA."
    )
    idea_parser.add_argument("idea", help="Feature idea or description.")
    idea_parser.add_argument(
        "--output-dir", required=True, help="Root directory for artifact output."
    )

    # spec-from-prd
    spec_parser = subparsers.add_parser(
        "spec-from-prd", help="Run from PRD: Arch -> Dev -> QA."
    )
    spec_parser.add_argument("prd_path", help="Path to PRD file.")
    spec_parser.add_argument("--user-stories", required=True, help="Path to user stories file.")
    spec_parser.add_argument(
        "--output-dir", required=True, help="Root directory for artifact output."
    )

    # plan-from-spec
    plan_parser = subparsers.add_parser(
        "plan-from-spec", help="Run from spec: Dev -> QA."
    )
    plan_parser.add_argument("--plan", required=True, help="Path to implementation plan file.")
    plan_parser.add_argument("--spec", required=True, help="Path to tech spec file.")
    plan_parser.add_argument(
        "--user-stories", default=None, help="Path to user stories file (optional)."
    )
    plan_parser.add_argument(
        "--output-dir", required=True, help="Root directory for artifact output."
    )

    return parser
```

Note: `--output-dir` is on each subparser (not the parent) to avoid argparse ordering
issues with required parent arguments and subcommands. `--verbose` has been removed
since it's a no-op in v1 — the spec's `--quiet` handles the only implemented output mode.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py -k "test_parse" -v`
Expected: All 3 PASS

- [ ] **Step 5: Lint**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/superagents_sdlc/cli.py`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/matt/coding/superagents/libs/sdlc
git add src/superagents_sdlc/cli.py tests/unit_tests/test_cli.py
git commit -m "feat(sdlc): add CLI argument parser with three subcommands"
```

---

### Task 5: CLI main() and output wiring

Implement the `main()` entry point that bridges argparse to the async orchestrator, prints
progress, handles errors, and supports `--json`. The `--stub` flag uses inline canned
responses (not imported from test code).

**Files:**

- Modify: `libs/sdlc/src/superagents_sdlc/cli.py`
- Modify: `libs/sdlc/pyproject.toml`
- Test: `libs/sdlc/tests/unit_tests/test_cli.py`

- [ ] **Step 1: Write the failing end-to-end test**

Add to `libs/sdlc/tests/unit_tests/test_cli.py`:

```python
import subprocess
import sys
from pathlib import Path


def test_stub_end_to_end(tmp_path):
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "idea-to-code", "Add dark mode",
            "--output-dir", str(output_dir),
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Certification:" in result.stdout
    assert (output_dir / "pm").is_dir()
    assert (output_dir / "qa").is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py::test_stub_end_to_end -v`
Expected: FAIL (main() not implemented yet)

- [ ] **Step 3: Implement _stub_responses(), _serialize_result(), _run(), and main()**

Add the following to `libs/sdlc/src/superagents_sdlc/cli.py`. First, add these imports
at the top (alongside existing imports):

```python
import asyncio
import json
import sys
from typing import TYPE_CHECKING

from superagents_sdlc.skills.llm import LLMClient, StubLLMClient
from superagents_sdlc.workflows.result import PipelineResult

if TYPE_CHECKING:
    from superagents_sdlc.skills.base import Artifact
```

Then add these functions after `_build_parser`:

```python
def _stub_responses() -> dict[str, str]:
    """Canned LLM responses for ``--stub`` mode.

    Produces valid artifacts for all eight skills across four personas.
    For development testing only — content is generic fixtures.

    Returns:
        Map of prompt substrings to stub responses.
    """
    # WARNING: Key ordering matters — StubLLMClient returns the first match.
    # QA keys must come before Architect/Developer keys because QA prompts
    # contain substrings that would collide with Architect/Developer keys.
    return {
        # PM skills
        "## Items to prioritize\n": "## Rankings\n1. Feature - RICE: 42",
        "## Idea / feature to spec\n": "# PRD: Feature\n## Problem\nNone",
        "## Feature description\n": (
            "## Story 1\nAs a user, I want feature\n"
            "### Acceptance Criteria\nGiven X\nWhen Y\nThen Z"
        ),
        # QA skills — must come before Architect/Developer keys
        "## Compliance report\n": (
            "# Validation Report\n## Executive Summary\nDone.\n"
            "## Certification\nNEEDS WORK"
        ),
        "## Plan structure analysis\n": (
            "## Compliance Check\n| Feature | PASS |\n"
            "## Summary\nTotal: 1 | Pass: 1\nOverall: NEEDS WORK"
        ),
        # Architect skills
        "## PRD\n": "# Tech Spec\n## Architecture\nSimple",
        "## Technical specification\n": "## Tasks\n1. Build it",
        # Developer skills
        "## Implementation plan\n": (
            "### Task 1: Feature\n\n"
            "- [ ] **Step 1: Write test**\nRun: `pytest -v`\n\n"
            "- [ ] **Step 2: Implement**\n"
        ),
    }


def _serialize_result(result: PipelineResult) -> str:
    """Serialize PipelineResult to JSON string.

    Args:
        result: Pipeline result to serialize.

    Returns:
        JSON string with indentation.
    """
    def _dump_artifacts(artifacts: list[Artifact]) -> list[dict[str, object]]:
        return [a.model_dump() for a in artifacts]

    data = {
        "certification": result.certification,
        "artifacts": _dump_artifacts(result.artifacts),
        "pm": _dump_artifacts(result.pm),
        "architect": _dump_artifacts(result.architect),
        "developer": _dump_artifacts(result.developer),
        "qa": _dump_artifacts(result.qa),
    }
    return json.dumps(data, indent=2)


async def _run(args: argparse.Namespace) -> int:
    """Run the pipeline based on parsed arguments.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 success, 1 error).
    """
    from superagents_sdlc.policy.config import PolicyConfig  # noqa: PLC0415
    from superagents_sdlc.policy.engine import PolicyEngine  # noqa: PLC0415
    from superagents_sdlc.policy.gates import AutoApprovalGate  # noqa: PLC0415
    from superagents_sdlc.workflows.orchestrator import PipelineOrchestrator  # noqa: PLC0415

    # Load context
    context = _load_context(args.context_dir)

    # Build LLM client
    if args.stub:
        llm: LLMClient = StubLLMClient(responses=_stub_responses())
    else:
        from superagents_sdlc.skills.llm import AnthropicLLMClient  # noqa: PLC0415

        llm = AnthropicLLMClient(model=args.model)

    # Build policy engine
    config = PolicyConfig(autonomy_level=args.autonomy_level)
    engine = PolicyEngine(config=config, gate=AutoApprovalGate())

    # Build orchestrator
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = PipelineOrchestrator(llm=llm, policy_engine=engine, context=context)

    # Phase progress callback
    def on_phase(name: str, artifacts: list[Artifact]) -> None:
        if not args.quiet:
            count = len(artifacts)
            label = "artifact" if count == 1 else "artifacts"
            print(f"{name.upper()} phase... done ({count} {label})")  # noqa: T201

    # Run the appropriate pipeline
    if args.command == "idea-to-code":
        result = await orchestrator.run_idea_to_code(
            args.idea,
            artifact_dir=output_dir,
            on_phase_complete=on_phase,
        )
    elif args.command == "spec-from-prd":
        result = await orchestrator.run_spec_from_prd(
            args.prd_path,
            user_stories_path=args.user_stories,
            artifact_dir=output_dir,
            on_phase_complete=on_phase,
        )
    else:  # plan-from-spec
        result = await orchestrator.run_plan_from_spec(
            implementation_plan_path=args.plan,
            tech_spec_path=args.spec,
            artifact_dir=output_dir,
            user_stories_path=args.user_stories,
            on_phase_complete=on_phase,
        )

    # Output
    if not args.quiet:
        print(f"\nCertification: {result.certification}")  # noqa: T201
        print(f"Artifacts written to {args.output_dir}")  # noqa: T201

    if args.json:
        print(_serialize_result(result))  # noqa: T201

    return 0


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    try:
        code = asyncio.run(_run(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    else:
        sys.exit(code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add console script to pyproject.toml**

Add to `libs/sdlc/pyproject.toml` after the `[project.optional-dependencies]` section:

```toml
[project.scripts]
superagents-sdlc = "superagents_sdlc.cli:main"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py::test_stub_end_to_end -v`
Expected: PASS

- [ ] **Step 6: Lint**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/superagents_sdlc/cli.py`
Expected: Clean (the `# noqa: T201` suppresses print warnings, `# noqa: PLC0415` suppresses deferred import warnings)

- [ ] **Step 7: Commit**

```bash
cd /home/matt/coding/superagents/libs/sdlc
git add src/superagents_sdlc/cli.py pyproject.toml
git commit -m "feat(sdlc): implement CLI main() with stub mode and progress output"
```

---

### Task 6: JSON output and error exit code tests

Add the remaining CLI tests: `--json` output and error exit code.

**Files:**

- Test: `libs/sdlc/tests/unit_tests/test_cli.py`

- [ ] **Step 1: Write the JSON output test**

Add to `libs/sdlc/tests/unit_tests/test_cli.py`:

```python
import json


def test_json_output(tmp_path):
    output_dir = tmp_path / "output"

    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "idea-to-code", "Add dark mode",
            "--output-dir", str(output_dir),
            "--stub", "--json", "--quiet",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "certification" in data
    assert "artifacts" in data
    assert "pm" in data
    assert "architect" in data
    assert "developer" in data
    assert "qa" in data
    assert len(data["artifacts"]) == 8
```

- [ ] **Step 2: Write the error exit code test**

Add to `libs/sdlc/tests/unit_tests/test_cli.py`:

```python
def test_error_exit_code(tmp_path):
    result = subprocess.run(
        [
            sys.executable, "-m", "superagents_sdlc.cli",
            "idea-to-code", "Test error",
            "--output-dir", str(tmp_path / "output"),
            "--context-dir", "/nonexistent/path/that/does/not/exist",
            "--stub",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=30,
    )

    assert result.returncode == 1
    assert "Error" in result.stderr
```

- [ ] **Step 3: Run new tests**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/unit_tests/test_cli.py::test_json_output tests/unit_tests/test_cli.py::test_error_exit_code -v`
Expected: Both PASS

- [ ] **Step 4: Run full test suite**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/ -v`
Expected: All tests PASS (existing 173 + 14 new = 187)

- [ ] **Step 5: Lint all modified files**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/ tests/`
Expected: Clean

- [ ] **Step 6: Commit**

```bash
cd /home/matt/coding/superagents/libs/sdlc
git add tests/unit_tests/test_cli.py
git commit -m "test(sdlc): add JSON output and error exit code tests for CLI"
```

---

### Task 7: Final integration verification

Run the full test suite, lint, and verify everything works together.

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test pytest tests/ -v --tb=short`
Expected: 187 tests PASS (173 existing + 3 orchestrator callback + 11 CLI)

- [ ] **Step 2: Run full lint**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run --group test ruff check src/ tests/`
Expected: Clean

- [ ] **Step 3: Verify CLI help output**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run python -m superagents_sdlc.cli --help`
Expected: Shows usage with three subcommands

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run python -m superagents_sdlc.cli idea-to-code --help`
Expected: Shows idea-to-code usage with idea positional and flags

- [ ] **Step 4: Verify stub pipeline run**

Run: `cd /home/matt/coding/superagents/libs/sdlc && uv run python -m superagents_sdlc.cli idea-to-code "Test feature" --output-dir /tmp/sdlc-test --stub`
Expected output:

```text
PM phase... done (3 artifacts)
ARCHITECT phase... done (2 artifacts)
DEVELOPER phase... done (1 artifact)
QA phase... done (2 artifacts)

Certification: NEEDS WORK
Artifacts written to /tmp/sdlc-test
```

- [ ] **Step 5: Commit if any fixes were needed**

Only if Steps 1-4 required fixes. Otherwise skip.
