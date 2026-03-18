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
