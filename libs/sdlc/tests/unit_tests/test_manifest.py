"""Tests for session manifest module."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from superagents_sdlc.manifest import (
    _state_display,
    _time_ago,
    create_manifest,
    discover_sessions,
    read_manifest,
    update_manifest,
)


def test_create_manifest_writes_json(tmp_path):
    create_manifest(tmp_path, idea="Add dark mode", model="claude-sonnet-4-6", fast_model=None)

    manifest = read_manifest(tmp_path)
    assert manifest is not None
    assert manifest["version"] == 1
    assert manifest["idea"] == "Add dark mode"
    assert manifest["state"] == "brainstorming"
    assert manifest["model"] == "claude-sonnet-4-6"
    assert manifest["fast_model"] is None
    assert "created_at" in manifest
    assert "updated_at" in manifest
    assert manifest["artifacts"] == {
        "brief": None,
        "idea_memory": None,
        "narrative": None,
        "pipeline_dir": None,
    }
    assert manifest["pipeline"] == {
        "certification": None,
        "retry_attempted": False,
        "pass_count": 0,
    }
    # Verify it's actually a file on disk
    assert (tmp_path / ".superagents.json").exists()


def test_update_manifest_merges_fields(tmp_path):
    create_manifest(tmp_path, idea="Test", model="claude-sonnet-4-6", fast_model=None)
    original = read_manifest(tmp_path)

    # Small delay to ensure updated_at changes
    time.sleep(0.01)
    update_manifest(tmp_path, state="brief_ready")

    updated = read_manifest(tmp_path)
    assert updated["state"] == "brief_ready"
    assert updated["idea"] == "Test"  # preserved
    assert updated["updated_at"] >= original["updated_at"]


def test_update_manifest_nested_pipeline(tmp_path):
    create_manifest(tmp_path, idea="Test", model="claude-sonnet-4-6", fast_model=None)
    update_manifest(
        tmp_path,
        pipeline={"certification": "READY", "retry_attempted": True, "pass_count": 2},
    )

    updated = read_manifest(tmp_path)
    assert updated["pipeline"]["certification"] == "READY"
    assert updated["pipeline"]["retry_attempted"] is True
    assert updated["pipeline"]["pass_count"] == 2


def test_update_manifest_artifacts(tmp_path):
    create_manifest(tmp_path, idea="Test", model="claude-sonnet-4-6", fast_model=None)
    update_manifest(
        tmp_path,
        artifacts={"brief": "design_brief.md", "idea_memory": "idea_memory.md"},
    )

    updated = read_manifest(tmp_path)
    assert updated["artifacts"]["brief"] == "design_brief.md"
    assert updated["artifacts"]["idea_memory"] == "idea_memory.md"
    assert updated["artifacts"]["narrative"] is None  # preserved


def test_read_manifest_returns_none_for_missing(tmp_path):
    assert read_manifest(tmp_path) is None


def test_read_manifest_returns_none_for_malformed(tmp_path):
    (tmp_path / ".superagents.json").write_text("not valid json {{{{")
    assert read_manifest(tmp_path) is None


def test_discover_sessions_finds_recent(tmp_path):
    # Create 3 sessions with different update times
    for i, name in enumerate(["alpha", "beta", "gamma"]):
        d = tmp_path / name
        d.mkdir()
        create_manifest(d, idea=f"Idea {name}", model="claude-sonnet-4-6", fast_model=None)
        # Ensure different updated_at by sleeping briefly
        time.sleep(0.01)
        if i > 0:
            update_manifest(d, state="brief_ready")

    sessions = discover_sessions(tmp_path)
    assert len(sessions) == 3
    # Most recently updated first
    assert sessions[0]["idea"] == "Idea gamma"
    # Each has output_dir key
    assert all("output_dir" in s for s in sessions)


def test_discover_sessions_skips_dirs_without_manifest(tmp_path):
    (tmp_path / "has_manifest").mkdir()
    create_manifest(tmp_path / "has_manifest", idea="Yes", model="m", fast_model=None)
    (tmp_path / "no_manifest").mkdir()

    sessions = discover_sessions(tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["idea"] == "Yes"


def test_discover_sessions_limits_to_10(tmp_path):
    for i in range(15):
        d = tmp_path / f"session-{i:02d}"
        d.mkdir()
        create_manifest(d, idea=f"Idea {i}", model="m", fast_model=None)

    sessions = discover_sessions(tmp_path)
    assert len(sessions) == 10


def test_discover_sessions_empty_root(tmp_path):
    assert discover_sessions(tmp_path) == []


def test_discover_sessions_missing_root(tmp_path):
    assert discover_sessions(tmp_path / "nonexistent") == []


def test_time_ago_just_now():
    now = datetime.now(tz=UTC).isoformat()
    assert _time_ago(now) == "just now"


def test_time_ago_minutes():
    ts = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
    assert _time_ago(ts) == "5 minutes ago"


def test_time_ago_hours():
    ts = (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat()
    assert _time_ago(ts) == "2 hours ago"


def test_time_ago_yesterday():
    ts = (datetime.now(tz=UTC) - timedelta(days=1)).isoformat()
    assert _time_ago(ts) == "yesterday"


def test_time_ago_days():
    ts = (datetime.now(tz=UTC) - timedelta(days=3)).isoformat()
    assert _time_ago(ts) == "3 days ago"


def test_time_ago_older():
    ts = (datetime.now(tz=UTC) - timedelta(days=10)).isoformat()
    result = _time_ago(ts)
    # Should be a month+day string like "Mar 28"
    assert any(month in result for month in [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ])


def test_state_display_all_states():
    assert _state_display("brainstorming") == "brainstorm in progress"
    assert _state_display("brief_ready") == "design brief ready"
    assert _state_display("pipeline_running") == "pipeline running"
    assert _state_display("pipeline_complete") == "pipeline complete"
    assert _state_display("pipeline_needs_work") == "pipeline needs work"
    assert _state_display("unknown_state") == "unknown_state"
