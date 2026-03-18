"""Shared fixtures for SDLC tests."""

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from superagents.telemetry import init_telemetry, reset_telemetry


@pytest.fixture
def exporter():
    """Provide a fresh InMemorySpanExporter with full init/reset lifecycle."""
    exp = InMemorySpanExporter()
    init_telemetry(exporter=exp)
    yield exp
    reset_telemetry()
