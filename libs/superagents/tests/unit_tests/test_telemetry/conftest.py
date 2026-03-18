"""Shared fixtures for telemetry tests."""

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
