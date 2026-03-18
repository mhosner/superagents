from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from superagents.telemetry.provider import get_tracer, init_telemetry, reset_telemetry


def test_get_tracer_without_init_returns_noop():
    """get_tracer() without init returns a tracer that creates non-recording spans."""
    tracer = get_tracer()
    span = tracer.start_span("test")
    assert not span.is_recording()
    span.end()


def test_init_telemetry_configures_provider(exporter):
    """After init, spans appear in the exporter."""
    tracer = get_tracer()
    with tracer.start_as_current_span("test-span"):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-span"


def test_init_telemetry_is_idempotent(exporter):
    """Second call to init_telemetry returns the same provider, ignores new exporter."""
    first_provider = init_telemetry(exporter=exporter)
    second_exporter = InMemorySpanExporter()
    second_provider = init_telemetry(exporter=second_exporter)

    assert first_provider is second_provider

    tracer = get_tracer()
    with tracer.start_as_current_span("idempotent-test"):
        pass

    assert len(exporter.get_finished_spans()) == 1
    assert len(second_exporter.get_finished_spans()) == 0


def test_reset_then_reinit_isolates_exporters():
    """After reset + reinit, old and new exporters are fully isolated."""
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


def test_get_tracer_returns_functional_tracer(exporter):
    """get_tracer() after init returns a tracer that records spans."""
    tracer = get_tracer("superagents")
    with tracer.start_as_current_span("functional-test"):
        pass
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "functional-test"


def test_noop_spans_not_captured_after_init():
    """Spans created before init_telemetry() don't appear in the exporter."""
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


def test_init_with_default_exporter_does_not_raise():
    """init_telemetry() with no exporter (OTLP default) does not raise."""
    provider = init_telemetry()
    assert provider is not None

    reset_telemetry()
