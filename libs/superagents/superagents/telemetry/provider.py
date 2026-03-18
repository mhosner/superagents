"""TracerProvider lifecycle management."""

from __future__ import annotations

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import NoOpTracer, Tracer

_provider: TracerProvider | None = None
_NOOP_TRACER = NoOpTracer()


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

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
