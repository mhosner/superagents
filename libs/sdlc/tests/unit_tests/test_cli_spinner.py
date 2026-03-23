"""Tests for CLI loading spinner."""

from __future__ import annotations

import time
from io import StringIO
from unittest.mock import patch

from superagents_sdlc.cli_spinner import (
    PHRASES,
    Spinner,
    print_banner,
)


def test_spinner_start_creates_thread():
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=True)
    spinner.start("Testing...")
    assert spinner.is_alive()
    spinner.stop()
    assert not spinner.is_alive()


def test_spinner_stop_clears_line():
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=True)
    spinner.start("Testing...")
    time.sleep(0.15)
    spinner.stop()
    output = buf.getvalue()
    # Should contain \r for line overwriting and spaces to clear
    assert "\r" in output


def test_spinner_cycles_braille_frames():
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=True)
    spinner.start("Working...")
    time.sleep(0.35)  # enough for 3+ frames at 100ms
    spinner.stop()
    output = buf.getvalue()
    # Should contain at least 2 different braille characters
    braille = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
    found = {ch for ch in output if ch in braille}
    assert len(found) >= 2


def test_spinner_displays_phrase():
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=True)
    spinner.start("Smashing the mainframe...")
    time.sleep(0.15)
    spinner.stop()
    output = buf.getvalue()
    assert "Smashing the mainframe..." in output


def test_spinner_swap_changes_phrase():
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=True)
    spinner.start("First phrase...")
    time.sleep(0.15)
    spinner.swap("Second phrase...")
    time.sleep(0.15)
    spinner.stop()
    output = buf.getvalue()
    assert "First phrase..." in output
    assert "Second phrase..." in output


def test_spinner_stop_when_not_started():
    """Calling stop on a never-started spinner should not raise."""
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=True)
    spinner.stop()  # should not raise


def test_phrases_has_at_least_20():
    assert len(PHRASES) >= 20


def test_banner_includes_version():
    buf = StringIO()
    with patch("superagents_sdlc.cli_spinner._is_tty", return_value=False):
        print_banner("0.1.0", file=buf)
    output = buf.getvalue()
    assert "0.1.0" in output
    assert "Not all coding heroes wear capes" in output


def test_banner_includes_ascii_art():
    buf = StringIO()
    with patch("superagents_sdlc.cli_spinner._is_tty", return_value=False):
        print_banner("0.1.0", file=buf)
    output = buf.getvalue()
    assert "SuperAgents" in output or "____" in output


def test_spinner_disabled_when_not_tty():
    """Spinner should not start a thread when output is not a TTY."""
    buf = StringIO()
    spinner = Spinner(file=buf, force_tty=False)
    spinner.start("Testing...")
    assert not spinner.is_alive()
    spinner.stop()  # should not raise
