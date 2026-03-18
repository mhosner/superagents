from superagents.telemetry.provider import get_tracer


def test_get_tracer_without_init_returns_noop():
    """get_tracer() without init returns a tracer that creates non-recording spans."""
    tracer = get_tracer()
    span = tracer.start_span("test")
    assert not span.is_recording()
    span.end()
