# Phase 1: Telemetry Skeleton Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the OpenTelemetry instrumentation foundation — a hybrid singleton tracer provider and four span context managers — that all subsequent Superagents layers emit spans through.

**Architecture:** A `telemetry/` subpackage inside `libs/superagents/superagents/` with two modules: `provider.py` (TracerProvider lifecycle with idempotent init, explicit no-op fallback bypassing OTel global state) and `spans.py` (four context managers for persona/skill/handoff/approval_gate spans). Tests use the SDK's `InMemorySpanExporter` with auto-selected `SimpleSpanProcessor` for synchronous, race-free assertions.

**Tech Stack:** Python 3.12+, opentelemetry-api, opentelemetry-sdk, opentelemetry-exporter-otlp, pytest

**Spec:** `docs/superpowers/specs/2026-03-17-phase1-telemetry-skeleton-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `superagents/telemetry/__init__.py` | Public API re-exports |
| `superagents/telemetry/provider.py` | `init_telemetry()`, `get_tracer()`, `reset_telemetry()` — TracerProvider lifecycle |
| `superagents/telemetry/spans.py` | `persona_span()`, `skill_span()`, `handoff_span()`, `approval_gate_span()` — context managers |
| `tests/__init__.py` | Package marker |
| `tests/unit_tests/__init__.py` | Package marker |
| `tests/unit_tests/test_telemetry/__init__.py` | Package marker |
| `tests/unit_tests/test_telemetry/conftest.py` | Shared fixture: init/reset telemetry per test |
| `tests/unit_tests/test_telemetry/test_provider.py` | 7 provider lifecycle tests |
| `tests/unit_tests/test_telemetry/test_spans.py` | 8 span context manager tests |

All paths are relative to `libs/superagents/`. All commands run from `libs/superagents/`.

---

### Task 1: Project scaffolding and test infrastructure

Create the directory structure, package markers, and the shared test fixture. No production code yet — just verify pytest discovers the test directory.

**Files:**
- Create: `superagents/telemetry/__init__.py`
- Create: `superagents/telemetry/provider.py`
- Create: `superagents/telemetry/spans.py`
- Create: `tests/__init__.py`
- Create: `tests/unit_tests/__init__.py`
- Create: `tests/unit_tests/test_telemetry/__init__.py`
- Create: `tests/unit_tests/test_telemetry/conftest.py`
- Create: `tests/unit_tests/test_telemetry/test_provider.py`
- Create: `tests/unit_tests/test_telemetry/test_spans.py`

- [ ] **Step 1: Create package markers and empty modules**

```python
# superagents/telemetry/__init__.py
"""Superagents telemetry — OpenTelemetry instrumentation primitives."""

# superagents/telemetry/provider.py
"""TracerProvider lifecycle management."""

# superagents/telemetry/spans.py
"""Span context managers for personas, skills, handoffs, and approval gates."""

# tests/__init__.py
# (empty)

# tests/unit_tests/__init__.py
# (empty)

# tests/unit_tests/test_telemetry/__init__.py
# (empty)
```

- [ ] **Step 2: Create the shared test fixture in conftest.py**

```python
# tests/unit_tests/test_telemetry/conftest.py
"""Shared fixtures for telemetry tests."""

import pytest
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

from superagents.telemetry.provider import init_telemetry, reset_telemetry


@pytest.fixture()
def exporter():
    """Provide a fresh InMemorySpanExporter with full init/reset lifecycle.

    Initialises the telemetry provider with a SimpleSpanProcessor (auto-selected
    because InMemorySpanExporter is detected). Shuts down and clears global state
    after each test.
    """
    exp = InMemorySpanExporter()
    init_telemetry(exporter=exp)
    yield exp
    reset_telemetry()
```

- [ ] **Step 3: Create a smoke test to verify pytest discovery**

```python
# tests/unit_tests/test_telemetry/test_provider.py
def test_placeholder():
    """Smoke test — verifies pytest discovers this file."""
    assert True
```

```python
# tests/unit_tests/test_telemetry/test_spans.py
def test_placeholder():
    """Smoke test — verifies pytest discovers this file."""
    assert True
```

- [ ] **Step 4: Run tests to verify discovery**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/ -v`
Expected: 2 tests collected, both PASS

- [ ] **Step 5: Commit**

```bash
git add superagents/telemetry/ tests/
git commit -m "chore(telemetry): scaffold telemetry package and test infrastructure"
```

---

### Task 2: `provider.py` — `get_tracer()` no-op fallback

Implement `get_tracer()` first because it has no dependencies and the no-op behavior is the foundation other tests build on.

**Files:**
- Modify: `superagents/telemetry/provider.py`
- Modify: `tests/unit_tests/test_telemetry/test_provider.py`

- [ ] **Step 1: Write the failing test — `test_get_tracer_without_init_returns_noop`**

```python
# tests/unit_tests/test_telemetry/test_provider.py
from superagents.telemetry.provider import get_tracer


def test_get_tracer_without_init_returns_noop():
    """get_tracer() without init returns a tracer that creates non-recording spans."""
    tracer = get_tracer()
    span = tracer.start_span("test")
    assert not span.is_recording()
    span.end()
```

Remove the placeholder test.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_get_tracer_without_init_returns_noop -v`
Expected: FAIL (ImportError or AttributeError — `get_tracer` not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# superagents/telemetry/provider.py
"""TracerProvider lifecycle management."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import NonRecordingSpan, Span, Tracer

_provider: TracerProvider | None = None


class _NoOpTracer(Tracer):
    """Tracer that always produces non-recording spans."""

    def start_span(self, name: str, **kwargs) -> Span:  # noqa: ANN003, ARG002
        """Return a non-recording span."""
        return NonRecordingSpan(context=None)


_NOOP_TRACER = _NoOpTracer()


def get_tracer(name: str = "superagents") -> Tracer:
    """Get a tracer from the global provider.

    If ``init_telemetry()`` has not been called, returns a no-op tracer
    that creates non-recording spans. Never raises.

    Args:
        name: Tracer instrumentation name.

    Returns:
        A ``Tracer`` instance.
    """
    if _provider is not None:
        return _provider.get_tracer(name)
    return _NOOP_TRACER
```

**Implementation note:** The OTel SDK's `NonRecordingSpan` may require a valid `SpanContext` rather than `None`. During implementation, spike this: if `context=None` raises, construct a minimal invalid `SpanContext` instead. The key invariant is `span.is_recording() == False`. The `_NoOpTracer` class may also need to implement additional abstract methods from `Tracer` (like `start_as_current_span`). Check the `Tracer` ABC and implement whatever is required — the test is the arbiter.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_get_tracer_without_init_returns_noop -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add superagents/telemetry/provider.py tests/unit_tests/test_telemetry/test_provider.py
git commit -m "feat(telemetry): add get_tracer() with no-op fallback"
```

---

### Task 3: `provider.py` — `init_telemetry()`

Implement the idempotent initialisation with auto-selected span processor.

**Files:**
- Modify: `superagents/telemetry/provider.py`
- Modify: `tests/unit_tests/test_telemetry/test_provider.py`

- [ ] **Step 1: Write the failing test — `test_init_telemetry_configures_provider`**

```python
# tests/unit_tests/test_telemetry/test_provider.py
from superagents.telemetry.provider import get_tracer


def test_init_telemetry_configures_provider(exporter):
    """After init, spans appear in the exporter."""
    tracer = get_tracer()
    with tracer.start_as_current_span("test-span"):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-span"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_init_telemetry_configures_provider -v`
Expected: FAIL (`init_telemetry` not defined or not functional)

- [ ] **Step 3: Write minimal implementation**

```python
# Add to superagents/telemetry/provider.py

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter
from opentelemetry import trace


def init_telemetry(
    *,
    service_name: str = "superagents",
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Initialise the global tracer provider. Idempotent.

    First call configures the provider. Subsequent calls return the
    existing provider without modification.

    Args:
        service_name: OpenTelemetry service name resource attribute.
        exporter: Span exporter. Defaults to OTLP if not provided.
            Pass ``InMemorySpanExporter`` for testing.

    Returns:
        The configured ``TracerProvider``.
    """
    global _provider  # noqa: PLW0603

    if _provider is not None:
        return _provider

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if exporter is None:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter()

    if isinstance(exporter, InMemorySpanExporter):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _provider = provider
    return provider
```

**Note:** `OTLPSpanExporter` is imported lazily inside the function to avoid import-time failures when no OTLP dependencies are configured. The `BatchSpanProcessor` import is also deferred since it's not needed in test paths.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_init_telemetry_configures_provider -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — `test_init_telemetry_is_idempotent`**

```python
def test_init_telemetry_is_idempotent(exporter):
    """Second call to init_telemetry returns the same provider, ignores new exporter."""
    from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

    from superagents.telemetry.provider import init_telemetry

    # Note: the `exporter` fixture already called init_telemetry() once.
    # This call is the second init — it should return the same provider.
    first_provider = init_telemetry(exporter=exporter)
    second_exporter = InMemorySpanExporter()
    second_provider = init_telemetry(exporter=second_exporter)

    assert first_provider is second_provider

    # Spans go to the first exporter, not the second
    tracer = get_tracer()
    with tracer.start_as_current_span("idempotent-test"):
        pass

    assert len(exporter.get_finished_spans()) == 1
    assert len(second_exporter.get_finished_spans()) == 0
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_init_telemetry_is_idempotent -v`
Expected: PASS (should already pass with the idempotent guard)

- [ ] **Step 7: Commit**

```bash
git add superagents/telemetry/provider.py tests/unit_tests/test_telemetry/test_provider.py
git commit -m "feat(telemetry): add idempotent init_telemetry() with auto processor selection"
```

---

### Task 4: `provider.py` — `reset_telemetry()` and isolation tests

Implement reset and verify clean isolation between init cycles.

**Files:**
- Modify: `superagents/telemetry/provider.py`
- Modify: `tests/unit_tests/test_telemetry/test_provider.py`

- [ ] **Step 1: Write the failing test — `test_reset_then_reinit_isolates_exporters`**

```python
def test_reset_then_reinit_isolates_exporters():
    """After reset + reinit, old and new exporters are fully isolated."""
    from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

    from superagents.telemetry.provider import init_telemetry, reset_telemetry

    # First lifecycle
    old_exporter = InMemorySpanExporter()
    init_telemetry(exporter=old_exporter)
    tracer = get_tracer()
    with tracer.start_as_current_span("old-span"):
        pass
    assert len(old_exporter.get_finished_spans()) == 1

    # Reset
    reset_telemetry()

    # Second lifecycle
    new_exporter = InMemorySpanExporter()
    init_telemetry(exporter=new_exporter)
    tracer = get_tracer()
    with tracer.start_as_current_span("new-span"):
        pass

    # Old exporter keeps old span, new exporter has only new span
    assert len(old_exporter.get_finished_spans()) == 1
    assert old_exporter.get_finished_spans()[0].name == "old-span"
    assert len(new_exporter.get_finished_spans()) == 1
    assert new_exporter.get_finished_spans()[0].name == "new-span"

    # Clean up
    reset_telemetry()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_reset_then_reinit_isolates_exporters -v`
Expected: FAIL (`reset_telemetry` not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# Add to superagents/telemetry/provider.py

def reset_telemetry() -> None:
    """Reset global telemetry state. Test-only.

    Shuts down the current provider (flushing pending spans and closing
    processors), then clears module state so the next ``init_telemetry()``
    call starts fresh.
    """
    global _provider  # noqa: PLW0603

    if _provider is not None:
        _provider.shutdown()
        _provider = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_reset_then_reinit_isolates_exporters -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — `test_get_tracer_returns_same_instance`**

```python
def test_get_tracer_returns_same_instance(exporter):
    """get_tracer() returns the same tracer object for the same name."""
    tracer1 = get_tracer("superagents")
    tracer2 = get_tracer("superagents")
    assert tracer1 is tracer2
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_get_tracer_returns_same_instance -v`
Expected: PASS (TracerProvider internally caches tracers by name)

- [ ] **Step 7: Write the failing test — `test_noop_spans_not_captured_after_init`**

```python
def test_noop_spans_not_captured_after_init():
    """Spans created before init_telemetry() don't appear in the exporter."""
    from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

    from superagents.telemetry.provider import init_telemetry, reset_telemetry

    # Create a span before init — goes to no-op tracer
    tracer = get_tracer()
    span = tracer.start_span("pre-init-span")
    span.end()

    # Now init with an exporter
    exp = InMemorySpanExporter()
    init_telemetry(exporter=exp)

    # The pre-init span must not appear
    assert len(exp.get_finished_spans()) == 0

    reset_telemetry()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_noop_spans_not_captured_after_init -v`
Expected: PASS (no-op tracer creates non-recording spans that are never exported)

- [ ] **Step 9: Write the failing test — `test_init_with_default_exporter_does_not_raise`**

```python
def test_init_with_default_exporter_does_not_raise():
    """init_telemetry() with no exporter (OTLP default) does not raise."""
    from superagents.telemetry.provider import init_telemetry, reset_telemetry

    # Should not raise even with no OTLP collector running
    provider = init_telemetry()
    assert provider is not None

    reset_telemetry()
```

- [ ] **Step 10: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py::test_init_with_default_exporter_does_not_raise -v`
Expected: PASS

- [ ] **Step 11: Run all provider tests together**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_provider.py -v`
Expected: 7 tests, all PASS

- [ ] **Step 12: Commit**

```bash
git add superagents/telemetry/provider.py tests/unit_tests/test_telemetry/test_provider.py
git commit -m "feat(telemetry): add reset_telemetry() and complete provider lifecycle tests"
```

---

### Task 5: `spans.py` — `persona_span` and `skill_span` context managers

Implement the first two context managers and their attribute tests.

**Files:**
- Modify: `superagents/telemetry/spans.py`
- Modify: `tests/unit_tests/test_telemetry/test_spans.py`

- [ ] **Step 1: Write the failing test — `test_persona_span_sets_attributes`**

```python
# tests/unit_tests/test_telemetry/test_spans.py
from superagents.telemetry.spans import persona_span


def test_persona_span_sets_attributes(exporter):
    """persona_span sets persona.name and autonomy.level on the span."""
    with persona_span("product_manager", autonomy_level=2):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "persona.product_manager"
    assert span.attributes["persona.name"] == "product_manager"
    assert span.attributes["autonomy.level"] == 2
```

Remove the placeholder test.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_persona_span_sets_attributes -v`
Expected: FAIL (ImportError — `persona_span` not defined)

- [ ] **Step 3: Write minimal implementation**

```python
# superagents/telemetry/spans.py
"""Span context managers for personas, skills, handoffs, and approval gates."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import Span

from superagents.telemetry.provider import get_tracer


@contextmanager
def persona_span(
    name: str,
    *,
    autonomy_level: int | None = None,
) -> Iterator[Span]:
    """Trace a persona operation.

    Args:
        name: Persona identifier (e.g., ``"product_manager"``).
        autonomy_level: Current policy level (1, 2, or 3).

    Yields:
        The active span for dynamic attribute setting.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"persona.{name}") as span:
        span.set_attribute("persona.name", name)
        if autonomy_level is not None:
            span.set_attribute("autonomy.level", autonomy_level)
        yield span
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_persona_span_sets_attributes -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — `test_skill_span_sets_attributes`**

```python
from superagents.telemetry.spans import skill_span


def test_skill_span_sets_attributes(exporter):
    """skill_span sets skill.name on the span."""
    with skill_span("prd_generator"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "skill.prd_generator"
    assert span.attributes["skill.name"] == "prd_generator"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_skill_span_sets_attributes -v`
Expected: FAIL (ImportError — `skill_span` not defined)

- [ ] **Step 7: Write minimal implementation**

```python
# Add to superagents/telemetry/spans.py

@contextmanager
def skill_span(name: str) -> Iterator[Span]:
    """Trace a skill execution.

    Args:
        name: Skill identifier (e.g., ``"prd_generator"``).

    Yields:
        The active span for dynamic attribute setting.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"skill.{name}") as span:
        span.set_attribute("skill.name", name)
        yield span
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_skill_span_sets_attributes -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add superagents/telemetry/spans.py tests/unit_tests/test_telemetry/test_spans.py
git commit -m "feat(telemetry): add persona_span and skill_span context managers"
```

---

### Task 6: `spans.py` — `handoff_span` and `approval_gate_span` context managers

Implement the remaining two context managers including sentinel defaults for approval gates.

**Files:**
- Modify: `superagents/telemetry/spans.py`
- Modify: `tests/unit_tests/test_telemetry/test_spans.py`

- [ ] **Step 1: Write the failing test — `test_handoff_span_sets_attributes`**

```python
from superagents.telemetry.spans import handoff_span


def test_handoff_span_sets_attributes(exporter):
    """handoff_span sets source, target, and artifact_type on the span."""
    with handoff_span("product_manager", "architect", artifact_type="prd"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "handoff.product_manager_to_architect"
    assert span.attributes["handoff.source"] == "product_manager"
    assert span.attributes["handoff.target"] == "architect"
    assert span.attributes["artifact.type"] == "prd"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_handoff_span_sets_attributes -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

```python
# Add to superagents/telemetry/spans.py

@contextmanager
def handoff_span(
    source: str,
    target: str,
    *,
    artifact_type: str | None = None,
) -> Iterator[Span]:
    """Trace a persona-to-persona handoff.

    Args:
        source: Source persona identifier.
        target: Target persona identifier.
        artifact_type: Type of artifact being handed off.

    Yields:
        The active span for dynamic attribute setting.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"handoff.{source}_to_{target}") as span:
        span.set_attribute("handoff.source", source)
        span.set_attribute("handoff.target", target)
        if artifact_type is not None:
            span.set_attribute("artifact.type", artifact_type)
        yield span
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_handoff_span_sets_attributes -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests — approval gate sentinel and caller override**

```python
from superagents.telemetry.spans import approval_gate_span


def test_approval_gate_span_sentinel_defaults(exporter):
    """Unset approval outcome shows 'pending', not missing attributes."""
    with approval_gate_span("prd_review", autonomy_level=2):
        pass  # Caller "forgets" to set outcome

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "approval_gate.prd_review"
    assert span.attributes["autonomy.level"] == 2
    assert span.attributes["approval.required"] == "pending"
    assert span.attributes["approval.outcome"] == "pending"


def test_approval_gate_span_caller_sets_outcome(exporter):
    """Caller can overwrite sentinel values on the yielded span."""
    with approval_gate_span("prd_review", autonomy_level=1) as span:
        span.set_attribute("approval.required", True)
        span.set_attribute("approval.outcome", "approved")
        span.set_attribute("gate_duration_ms", 1200)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["approval.required"] is True
    assert span.attributes["approval.outcome"] == "approved"
    assert span.attributes["gate_duration_ms"] == 1200
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py -k "approval_gate" -v`
Expected: FAIL

- [ ] **Step 7: Write minimal implementation**

```python
# Add to superagents/telemetry/spans.py

@contextmanager
def approval_gate_span(
    gate_name: str,
    *,
    autonomy_level: int | None = None,
) -> Iterator[Span]:
    """Trace an approval gate decision.

    Sets sentinel defaults for ``approval.required`` and ``approval.outcome``
    so that forgotten attributes show ``"pending"`` in traces rather than
    being invisibly absent.

    Args:
        gate_name: Gate identifier (e.g., ``"prd_review"``).
        autonomy_level: Current policy level (1, 2, or 3).

    Yields:
        The active span. Caller sets ``approval.required``,
        ``approval.outcome``, and ``gate_duration_ms`` after resolution.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"approval_gate.{gate_name}") as span:
        if autonomy_level is not None:
            span.set_attribute("autonomy.level", autonomy_level)
        span.set_attribute("approval.required", "pending")
        span.set_attribute("approval.outcome", "pending")
        yield span
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py -k "approval_gate" -v`
Expected: 2 tests PASS

- [ ] **Step 9: Commit**

```bash
git add superagents/telemetry/spans.py tests/unit_tests/test_telemetry/test_spans.py
git commit -m "feat(telemetry): add handoff_span and approval_gate_span context managers"
```

---

### Task 7: Span nesting, root isolation, and error handling tests

Test the structural properties: parent-child relationships, root span isolation, and exception recording.

**Files:**
- Modify: `tests/unit_tests/test_telemetry/test_spans.py`

- [ ] **Step 1: Write the failing test — `test_span_nesting_creates_parent_child`**

```python
def test_span_nesting_creates_parent_child(exporter):
    """A skill_span inside a persona_span has the correct parent-child relationship."""
    with persona_span("product_manager", autonomy_level=2) as parent:
        with skill_span("prd_generator"):
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2

    # Spans are exported child-first
    child = next(s for s in spans if s.name == "skill.prd_generator")
    parent_span = next(s for s in spans if s.name == "persona.product_manager")

    assert child.context.trace_id == parent_span.context.trace_id
    assert child.parent.span_id == parent_span.context.span_id
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_span_nesting_creates_parent_child -v`
Expected: PASS (start_as_current_span handles parenting automatically)

- [ ] **Step 3: Write the failing test — `test_skill_span_as_root_has_no_persona_parent`**

```python
from opentelemetry import context


def test_skill_span_as_root_has_no_persona_parent(exporter):
    """A standalone skill_span with clean context is a root span."""
    # Attach root context to prevent leakage from other tests
    token = context.attach(context.get_current())

    try:
        with skill_span("standalone_skill"):
            pass
    finally:
        context.detach(token)

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].parent is None
```

**Implementation note:** The exact mechanism to ensure a clean root context may need adjustment during implementation. If `context.get_current()` already returns root context in a clean test, this works as-is. If not, use `context.attach(context.Context())` or the appropriate OTel API to create a fresh root context. The test assertion (`parent is None`) is the invariant — adjust the setup to make it true.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_skill_span_as_root_has_no_persona_parent -v`
Expected: PASS

- [ ] **Step 5: Write the failing test — `test_context_manager_sets_error_on_exception`**

```python
import pytest
from opentelemetry.trace import StatusCode


def test_context_manager_sets_error_on_exception(exporter):
    """An exception inside a span sets status to ERROR and records the exception."""
    with pytest.raises(ValueError, match="test error"):
        with skill_span("failing_skill"):
            raise ValueError("test error")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR

    # The exception should be recorded as an event
    events = span.events
    assert len(events) == 1
    assert events[0].name == "exception"
    assert events[0].attributes["exception.message"] == "test error"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py::test_context_manager_sets_error_on_exception -v`
Expected: PASS (start_as_current_span handles this automatically)

**Implementation note:** The exact attribute names for exception events may differ between OTel SDK versions. Common names are `exception.message` and `exception.type`. If the test fails on attribute names, check `span.events[0].attributes.keys()` and adjust assertions to match the SDK's actual output.

- [ ] **Step 7: Run all span tests together**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/test_spans.py -v`
Expected: 8 tests, all PASS

- [ ] **Step 8: Commit**

```bash
git add tests/unit_tests/test_telemetry/test_spans.py
git commit -m "test(telemetry): add span nesting, root isolation, and error handling tests"
```

---

### Task 8: Public API re-exports and full test suite

Wire up `__init__.py` re-exports, run the full suite, and verify lint.

**Files:**
- Modify: `superagents/telemetry/__init__.py`

- [ ] **Step 1: Write the `__init__.py` re-exports**

```python
# superagents/telemetry/__init__.py
"""Superagents telemetry — OpenTelemetry instrumentation primitives."""

from superagents.telemetry.provider import get_tracer, init_telemetry, reset_telemetry
from superagents.telemetry.spans import (
    approval_gate_span,
    handoff_span,
    persona_span,
    skill_span,
)

__all__ = [
    "approval_gate_span",
    "get_tracer",
    "handoff_span",
    "init_telemetry",
    "persona_span",
    "reset_telemetry",
    "skill_span",
]
```

- [ ] **Step 2: Verify imports work from the package**

Run: `cd libs/superagents && uv run python -c "from superagents.telemetry import init_telemetry, get_tracer, persona_span, skill_span, handoff_span, approval_gate_span; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run the full test suite**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/ -v`
Expected: 15 tests, all PASS

- [ ] **Step 4: Run linter**

Run: `cd libs/superagents && uv run --group test ruff check superagents/telemetry/ tests/unit_tests/test_telemetry/`
Expected: no errors (fix any that appear)

- [ ] **Step 5: Run formatter**

Run: `cd libs/superagents && uv run --group test ruff format superagents/telemetry/ tests/unit_tests/test_telemetry/`
Expected: files already formatted (or reformatted)

- [ ] **Step 6: Commit**

```bash
git add superagents/telemetry/__init__.py
git commit -m "feat(telemetry): add public API re-exports with __all__"
```

- [ ] **Step 7: Run full test suite one final time to confirm green**

Run: `cd libs/superagents && uv run --group test pytest tests/unit_tests/test_telemetry/ -v --tb=short`
Expected: 15 tests, all PASS

---

## Summary

| Task | What it builds | Tests added |
|------|---------------|-------------|
| 1 | Scaffolding + conftest fixture | 0 (smoke only) |
| 2 | `get_tracer()` no-op fallback | 1 |
| 3 | `init_telemetry()` + idempotency | 2 |
| 4 | `reset_telemetry()` + isolation + remaining provider tests | 4 |
| 5 | `persona_span` + `skill_span` | 2 |
| 6 | `handoff_span` + `approval_gate_span` | 3 |
| 7 | Nesting, root isolation, error handling | 3 |
| 8 | `__init__.py` re-exports + full suite verification | 0 |
| **Total** | **3 source files, 15 tests** | **15** |
