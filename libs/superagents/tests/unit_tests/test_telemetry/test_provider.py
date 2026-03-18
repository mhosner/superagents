from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from superagents.telemetry.provider import get_tracer, init_telemetry


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
