from superagents.telemetry.spans import (
    approval_gate_span,
    handoff_span,
    persona_span,
    skill_span,
)


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


def test_skill_span_sets_attributes(exporter):
    """skill_span sets skill.name on the span."""
    with skill_span("prd_generator"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "skill.prd_generator"
    assert span.attributes["skill.name"] == "prd_generator"


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


def test_span_nesting_creates_parent_child(exporter):
    """A skill_span inside a persona_span has the correct parent-child relationship."""
    with persona_span("product_manager", autonomy_level=2):
        with skill_span("prd_generator"):
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2

    child = next(s for s in spans if s.name == "skill.prd_generator")
    parent_span = next(s for s in spans if s.name == "persona.product_manager")

    assert child.context.trace_id == parent_span.context.trace_id
    assert child.parent.span_id == parent_span.context.span_id


def test_skill_span_as_root_has_no_persona_parent(exporter):
    """A standalone skill_span is a root span with no parent."""
    with skill_span("standalone_skill"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].parent is None


def test_context_manager_sets_error_on_exception(exporter):
    """An exception inside a span sets status to ERROR and records the exception."""
    import pytest
    from opentelemetry.trace import StatusCode

    with pytest.raises(ValueError, match="test error"):
        with skill_span("failing_skill"):
            raise ValueError("test error")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code == StatusCode.ERROR

    events = span.events
    assert len(events) == 1
    assert events[0].name == "exception"
    assert events[0].attributes["exception.message"] == "test error"
