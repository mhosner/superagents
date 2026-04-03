"""Session manifest — tracks brainstorm/pipeline state across sessions.

Each output directory contains a ``.superagents.json`` manifest that records
the session idea, current state, model config, artifact paths, and pipeline
results. The guided startup flow uses manifests to discover and resume sessions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_MANIFEST_FILENAME = ".superagents.json"

_STATE_DISPLAY: dict[str, str] = {
    "brainstorming": "brainstorm in progress",
    "brief_ready": "design brief ready",
    "pipeline_running": "pipeline running",
    "pipeline_complete": "pipeline complete",
    "pipeline_needs_work": "pipeline needs work",
}


def create_manifest(
    output_dir: Path,
    idea: str,
    model: str,
    fast_model: str | None,
) -> None:
    """Write initial manifest to output directory.

    Args:
        output_dir: Directory to write manifest to.
        idea: The user's feature idea.
        model: Primary LLM model identifier.
        fast_model: Optional fast/cheap model identifier.
    """
    now = datetime.now(tz=UTC).isoformat()
    manifest = {
        "version": 1,
        "idea": idea,
        "state": "brainstorming",
        "created_at": now,
        "updated_at": now,
        "model": model,
        "fast_model": fast_model,
        "artifacts": {
            "brief": None,
            "idea_memory": None,
            "narrative": None,
            "pipeline_dir": None,
        },
        "pipeline": {
            "certification": None,
            "retry_attempted": False,
            "pass_count": 0,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / _MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2))


def update_manifest(output_dir: Path, **fields: object) -> None:
    """Update manifest fields, preserving existing values.

    Nested dicts (artifacts, pipeline) are merged shallowly — keys in the
    update replace keys in the existing dict, but keys not mentioned are
    preserved.

    Args:
        output_dir: Directory containing the manifest.
        **fields: Fields to update. Nested dicts are merged, not replaced.
    """
    manifest = read_manifest(output_dir)
    if manifest is None:
        return

    for key, value in fields.items():
        if isinstance(value, dict) and isinstance(manifest.get(key), dict):
            manifest[key].update(value)
        else:
            manifest[key] = value

    manifest["updated_at"] = datetime.now(tz=UTC).isoformat()
    (output_dir / _MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2))


def read_manifest(output_dir: Path) -> dict | None:
    """Read manifest from output directory.

    Args:
        output_dir: Directory to read manifest from.

    Returns:
        Manifest dict, or None if file is missing or malformed.
    """
    path = output_dir / _MANIFEST_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def discover_sessions(root: Path = Path("superagents-output")) -> list[dict]:
    """Scan root directory for sessions with manifests.

    Args:
        root: Root directory to scan. Defaults to ``superagents-output``.

    Returns:
        List of manifest dicts (with ``output_dir`` added), sorted by
        ``updated_at`` descending. Limited to 10 most recent.
    """
    if not root.exists() or not root.is_dir():
        return []

    sessions: list[dict] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        manifest = read_manifest(child)
        if manifest is not None:
            manifest["output_dir"] = str(child)
            sessions.append(manifest)

    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions[:10]


def _format_delta(seconds: int, dt: datetime) -> str:
    """Convert elapsed seconds to a human-friendly label.

    Args:
        seconds: Total elapsed seconds since the timestamp.
        dt: Original datetime (used for older-than-a-week formatting).

    Returns:
        Human-friendly relative time string.
    """
    if seconds < 60:  # noqa: PLR2004
        return "just now"
    minutes = seconds // 60
    if minutes < 60:  # noqa: PLR2004
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:  # noqa: PLR2004
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 7:  # noqa: PLR2004
        return f"{days} days ago"
    return dt.strftime("%b %d")


def _time_ago(iso_timestamp: str) -> str:
    """Format an ISO 8601 timestamp as a human-friendly relative time.

    Args:
        iso_timestamp: ISO 8601 timestamp string.

    Returns:
        Human-friendly string like "just now", "5 minutes ago", "yesterday".
    """
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except ValueError:
        return iso_timestamp

    now = datetime.now(tz=UTC)
    delta = now - dt
    return _format_delta(int(delta.total_seconds()), dt)


def _state_display(state: str) -> str:
    """Map manifest state to user-friendly display text.

    Args:
        state: Manifest state string.

    Returns:
        Human-friendly state description.
    """
    return _STATE_DISPLAY.get(state, state)
