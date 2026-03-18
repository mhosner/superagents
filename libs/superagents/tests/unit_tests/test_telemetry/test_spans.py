from superagents.telemetry.spans import persona_span, skill_span


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
