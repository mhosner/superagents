"""Tests for CLI terminal formatting helpers."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from superagents_sdlc.cli_format import (
    bold,
    color,
    GREEN,
    RED,
    YELLOW,
    print_qa_findings,
    print_retry_start,
    print_routing,
    print_skill,
)


def test_bold_with_tty():
    with patch("superagents_sdlc.cli_format._is_tty", return_value=True):
        assert bold("hello") == "\033[1mhello\033[0m"


def test_bold_without_tty():
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        assert bold("hello") == "hello"


def test_color_with_tty():
    with patch("superagents_sdlc.cli_format._is_tty", return_value=True):
        assert color("ok", GREEN) == "\033[32mok\033[0m"


def test_color_without_tty():
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        assert color("ok", GREEN) == "ok"


def test_print_skill_output():
    buf = StringIO()
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        print_skill("product_manager", "prd_generator", "Generated PRD.", file=buf)
    output = buf.getvalue()
    assert "product_manager" in output
    assert "prd_generator" in output
    assert "Generated PRD." in output


def test_print_qa_findings_output():
    buf = StringIO()
    findings = [
        {"id": "RF-1", "summary": "Missing task", "severity": "CRITICAL"},
    ]
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        print_qa_findings(
            certification="NEEDS WORK",
            key_findings=findings,
            file=buf,
        )
    output = buf.getvalue()
    assert "NEEDS WORK" in output
    assert "RF-1" in output
    assert "CRITICAL" in output


def test_print_routing_output():
    buf = StringIO()
    routing = {
        "product_manager": [],
        "architect": [{"id": "RF-1"}],
        "developer": [{"id": "RF-2"}, {"id": "RF-3"}],
    }
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        print_routing(routing, ["architect", "developer"], file=buf)
    output = buf.getvalue()
    assert "3 findings" in output
    assert "architect" in output.lower()
    assert "developer" in output.lower()


def test_print_retry_start_output():
    buf = StringIO()
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        print_retry_start("NEEDS WORK", 8, file=buf)
    output = buf.getvalue()
    assert "NEEDS WORK" in output
    assert "8" in output


def test_no_ansi_when_not_tty():
    """Verify no escape codes when stdout is not a TTY."""
    buf = StringIO()
    with patch("superagents_sdlc.cli_format._is_tty", return_value=False):
        print_skill("pm", "prd", "summary", file=buf)
        print_qa_findings(certification="READY", key_findings=[], file=buf)
    output = buf.getvalue()
    assert "\033[" not in output
