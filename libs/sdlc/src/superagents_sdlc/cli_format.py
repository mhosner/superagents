"""Terminal formatting helpers for CLI narrative streaming.

All print functions accept an optional ``file`` parameter for testability.
ANSI codes are only emitted when stdout is a TTY.
"""

from __future__ import annotations

import sys
from typing import IO, Any

GREEN = "32"
YELLOW = "33"
RED = "31"
CYAN = "36"

_DISPLAY_NAMES = {
    "product_manager": "Product Manager",
    "architect": "Architect",
    "developer": "Developer",
}

_CERT_COLORS = {
    "READY": GREEN,
    "NEEDS WORK": YELLOW,
    "FAILED": RED,
}


def _is_tty() -> bool:
    """Check if stdout is a TTY.

    Returns:
        True if stdout is connected to a terminal.
    """
    return sys.stdout.isatty()


def bold(text: str) -> str:
    """Wrap text in bold ANSI escape if stdout is a TTY.

    Args:
        text: Text to format.

    Returns:
        Formatted or plain text.
    """
    if not _is_tty():
        return text
    return f"\033[1m{text}\033[0m"


def color(text: str, code: str) -> str:
    """Wrap text in ANSI color escape if stdout is a TTY.

    Args:
        text: Text to format.
        code: ANSI color code (e.g., "32" for green).

    Returns:
        Formatted or plain text.
    """
    if not _is_tty():
        return text
    return f"\033[{code}m{text}\033[0m"


def print_skill(
    persona: str,
    skill: str,
    summary: str,
    *,
    file: IO[Any] | None = None,
) -> None:
    """Print a skill execution line.

    Args:
        persona: Persona name.
        skill: Skill name.
        summary: Artifact summary.
        file: Output stream (defaults to stdout).
    """
    out = file or sys.stdout
    arrow = bold(f"  {persona} → {skill}:")
    print(f"{arrow} {summary}", file=out, flush=True)  # noqa: T201


def print_qa_findings(
    *,
    certification: str,
    key_findings: list[dict],
    file: IO[Any] | None = None,
) -> None:
    """Print QA certification and key findings.

    Args:
        certification: Certification rating string.
        key_findings: List of finding dicts with id, summary, severity.
        file: Output stream (defaults to stdout).
    """
    out = file or sys.stdout
    cert_color = _CERT_COLORS.get(certification, YELLOW)
    cert_text = bold(color(f"  Certification: {certification}", cert_color))
    print(cert_text, file=out, flush=True)  # noqa: T201
    for finding in key_findings:
        fid = finding.get("id", "?")
        severity = finding.get("severity", "?")
        summary = finding.get("summary", "")
        print(f"    {fid} [{severity}]: {summary}", file=out, flush=True)  # noqa: T201


def print_routing(
    routing: dict,
    cascade: list[str],
    *,
    file: IO[Any] | None = None,
) -> None:
    """Print findings routing summary.

    Args:
        routing: Routing dict mapping persona keys to finding lists.
        cascade: Ordered list of cascade persona keys.
        file: Output stream (defaults to stdout).
    """
    out = file or sys.stdout
    total = sum(len(items) for items in routing.values())
    parts: list[str] = []
    for key in ("product_manager", "architect", "developer"):
        count = len(routing.get(key, []))
        if count > 0:
            label = _DISPLAY_NAMES.get(key, key).lower()
            parts.append(f"{count} {label}")
    breakdown = ", ".join(parts) if parts else "none"
    print(  # noqa: T201
        f"  Routed {total} findings: {breakdown}",
        file=out, flush=True,
    )
    cascade_display = [_DISPLAY_NAMES.get(p, p) for p in cascade]
    print(  # noqa: T201
        f"  Cascade: {' → '.join(cascade_display)}",
        file=out, flush=True,
    )


def print_retry_start(
    certification: str,
    finding_count: int,
    *,
    file: IO[Any] | None = None,
) -> None:
    """Print retry trigger line.

    Args:
        certification: Pre-retry certification.
        finding_count: Number of findings triggering retry.
        file: Output stream (defaults to stdout).
    """
    out = file or sys.stdout
    text = bold(color(
        f"  Retry triggered: {certification}, {finding_count} findings",
        YELLOW,
    ))
    print(text, file=out, flush=True)  # noqa: T201
