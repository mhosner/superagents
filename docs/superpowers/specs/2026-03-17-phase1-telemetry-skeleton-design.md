# Phase 1: Telemetry Skeleton — Design Spec

## Overview

Build the OpenTelemetry instrumentation foundation for Superagents. This is the first code written — every subsequent layer (personas, skills, handoffs, approval gates) emits spans through these primitives.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Package location | `libs/superagents/superagents/telemetry/` | Telemetry is core infrastructure; dependencies already installed |
| Provider management | Hybrid singleton | Explicit `init_telemetry()` + `get_tracer()` convenience; no-op fallback if uninitialised |
| Span API | Context managers (primary) | Flexible primitive that handles dynamic attributes; decorators added later as sugar if needed |
| Test exporter | SDK's `InMemorySpanExporter` directly | YAGNI — no wrapper until test assertions get repetitive |
| Span processor | Auto-selected by exporter type | `SimpleSpanProcessor` for `InMemorySpanExporter` (synchronous, no race conditions); `BatchSpanProcessor` for everything else |
| Global OTel state | Bypassed after first init | `get_tracer()` always reads `_provider` directly, never falls through to the global API after init/reset cycles |

## Module structure

```
libs/superagents/superagents/telemetry/
├── __init__.py          # Public API re-exports
├── provider.py          # TracerProvider lifecycle
└── spans.py             # Four context managers
```

```
libs/superagents/tests/unit_tests/test_telemetry/
├── __init__.py
├── test_provider.py     # Provider lifecycle tests
└── test_spans.py        # Context manager tests
```

## `provider.py`

### State

Single module-level variable:

```python
_provider: TracerProvider | None = None
```

`_provider is not None` means initialised. No separate boolean flag — one piece of state, one truth.

### `init_telemetry(*, service_name, exporter) -> TracerProvider`

- **Idempotent**: if `_provider is not None`, return it immediately. No duplicate exporters, no reset of in-flight spans.
- Creates a `TracerProvider` with a `Resource(service.name=service_name)`.
- **Processor selection**: if `exporter` is an instance of `InMemorySpanExporter`, wraps it in `SimpleSpanProcessor` (synchronous export on span end — no race conditions in tests). Otherwise wraps in `BatchSpanProcessor` (async background export for production throughput).
- If `exporter` is `None`, defaults to `OTLPSpanExporter()` with `BatchSpanProcessor`. This must not raise even if no OTLP collector is running — `BatchSpanProcessor` silently drops spans it cannot export.
- Calls `trace.set_tracer_provider(provider)` to register globally.
- Stores in `_provider` and returns it.

### `get_tracer(name) -> Tracer`

- If `_provider is not None`, returns `_provider.get_tracer(name)`.
- If `_provider is None`, returns a `NonRecordingTracer` explicitly — **does not fall through to the global OTel API**. This bypasses OpenTelemetry's sticky global state, which can retain a reference to a shutdown provider after `reset_telemetry()`. The no-op path is always safe regardless of global state.

**Implementation note**: the OTel Python SDK's `trace.get_tracer()` caches the global provider. After `set_tracer_provider()` + `shutdown()`, calling `trace.get_tracer()` may return a tracer from the dead provider rather than a true no-op. By always routing through `_provider` or an explicit no-op, we sidestep this entirely. Worth a spike during implementation to confirm whether `trace.set_tracer_provider()` can be called multiple times cleanly; if not, the explicit routing is the fix.

### `reset_telemetry() -> None`

- Test-only. Not part of the public API.
- Calls `_provider.shutdown()` — closes the provider and its processors, not just `force_flush()`.
- Clears `_provider = None`.
- Next `init_telemetry()` call creates a fresh provider and calls `set_tracer_provider()` again, giving clean test isolation.
- Because `get_tracer()` checks `_provider` directly (not the global), post-reset calls correctly return a no-op tracer.

## `spans.py`

Four context managers, one per span category from the CLAUDE.md telemetry spec. All use `start_as_current_span` so nesting produces correct parent-child relationships automatically.

### `persona_span(name, *, autonomy_level) -> Iterator[Span]`

- Span name: `persona.<name>`
- Sets: `persona.name`, `autonomy.level` (if provided)
- Yields the span for dynamic attribute setting

### `skill_span(name) -> Iterator[Span]`

- Span name: `skill.<name>`
- Sets: `skill.name`
- No `persona` parameter — if called inside a `persona_span`, the parent-child relationship captures the association. Queryable by walking the trace tree.

### `handoff_span(source, target, *, artifact_type) -> Iterator[Span]`

- `source` and `target` are required positional args
- Span name: `handoff.<source>_to_<target>`
- Sets: `handoff.source`, `handoff.target`, `artifact.type` (if provided)

### `approval_gate_span(gate_name, *, autonomy_level) -> Iterator[Span]`

- Span name: `approval_gate.<gate_name>`
- Sets: `autonomy.level` (if provided)
- **Sentinel defaults**: sets `approval.required = "pending"` and `approval.outcome = "pending"` on creation. If the caller forgets to set them, traces show `"pending"` instead of a missing attribute. Missing attributes are invisible in trace UIs; wrong values are visible and obvious.
- Caller sets `approval.required`, `approval.outcome`, `gate_duration_ms` on the yielded span after resolution.

### Error handling

All context managers use `start_as_current_span`, which automatically sets span status to ERROR and records the exception if one propagates out of the `with` block. No additional error handling needed in the context managers themselves.

## `__init__.py`

Re-exports the public API:

```python
from superagents.telemetry.provider import get_tracer, init_telemetry, reset_telemetry
from superagents.telemetry.spans import (
    approval_gate_span,
    handoff_span,
    persona_span,
    skill_span,
)
```

## Test plan

All tests use a pytest fixture that calls `init_telemetry(exporter=InMemorySpanExporter())` before each test and `reset_telemetry()` after.

### `test_provider.py` (7 tests)

| # | Test | Verifies |
|---|------|----------|
| 1 | `test_get_tracer_without_init_returns_noop` | `get_tracer()` without init returns a tracer that creates non-recording spans; no crash |
| 2 | `test_noop_spans_not_captured_after_init` | Spans created before `init_telemetry()` don't appear in the exporter after init — they vanish, not queue up |
| 3 | `test_init_telemetry_configures_provider` | Init with `InMemorySpanExporter`, create a span, verify it appears in `exporter.get_finished_spans()` |
| 4 | `test_init_telemetry_is_idempotent` | Init twice with different exporters; first exporter wins, second call returns the same provider object |
| 5 | `test_get_tracer_returns_same_instance` | Two calls to `get_tracer("superagents")` after init return the same tracer object |
| 6 | `test_reset_then_reinit_isolates_exporters` | Init → span → reset → init with new exporter → span → old exporter has old span, new exporter has only new span |
| 7 | `test_init_with_default_exporter_does_not_raise` | `init_telemetry()` with no exporter (OTLP default) initialises without error even with no collector running |

### `test_spans.py` (8 tests)

| # | Test | Verifies |
|---|------|----------|
| 8 | `test_persona_span_sets_attributes` | `persona.name` and `autonomy.level` on exported span |
| 9 | `test_skill_span_sets_attributes` | `skill.name` on exported span |
| 10 | `test_handoff_span_sets_attributes` | `handoff.source`, `handoff.target`, `artifact.type` on exported span |
| 11 | `test_approval_gate_span_sentinel_defaults` | Unset outcome shows `approval.required = "pending"` and `approval.outcome = "pending"`, not missing attributes |
| 12 | `test_approval_gate_span_caller_sets_outcome` | Caller sets `approval.outcome = "approved"`, overwrites sentinel |
| 13 | `test_span_nesting_creates_parent_child` | `persona_span` wrapping `skill_span` — child's `parent_span_id` matches parent's `span_id` |
| 14 | `test_skill_span_as_root_has_no_persona_parent` | Standalone `skill_span` with `context.attach(ROOT_CONTEXT)` — verify it's a root span with no persona parent |
| 15 | `test_context_manager_sets_error_on_exception` | Exception inside span sets status to ERROR and records the exception event |

### Test infrastructure notes

- **Processor race conditions**: tests use `SimpleSpanProcessor` (auto-selected because they pass `InMemorySpanExporter`), so `get_finished_spans()` is always consistent — no need for `force_flush()` calls in tests.
- **OTel global state**: `get_tracer()` bypasses the global provider, so test isolation works even if `set_tracer_provider()` has sticky behavior. Each test gets its own `_provider` via the fixture.
- **Context propagation**: `test_skill_span_as_root_has_no_persona_parent` uses `context.attach(context.ROOT_CONTEXT)` to ensure a clean context, preventing leakage from other tests or framework spans.

## Span hierarchy (reference)

From the CLAUDE.md spec, showing how these primitives compose:

```
trace: sdlc_workflow
  └── persona.product_manager              (persona_span)
       ├── skill.prd_generator             (skill_span, child of persona)
       ├── approval_gate.prd_review        (approval_gate_span)
       │    ├── approval.required = true
       │    ├── approval.outcome = approved
       │    └── gate_duration_ms = 1200
       └── handoff.product_manager_to_architect  (handoff_span)
            ├── artifact.type = prd
            └── handoff.target = architect
```

## What this does NOT include

- Metrics (Phase 1 is spans only — metrics come when we have real data to measure)
- Decorator sugar on top of context managers (add when repetition justifies it)
- OTLP exporter configuration for production (straightforward via `init_telemetry(exporter=OTLPSpanExporter(...))`)
- Custom `InMemorySpanExporter` wrapper with assertion helpers (YAGNI until test boilerplate warrants it)
