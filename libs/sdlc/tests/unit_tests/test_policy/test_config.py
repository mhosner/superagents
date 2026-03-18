"""Tests for PolicyConfig Pydantic model."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from superagents_sdlc.policy.config import PolicyConfig

if TYPE_CHECKING:
    from pathlib import Path


def test_default_config_level_one():
    config = PolicyConfig()
    assert config.autonomy_level == 1
    assert config.overrides == {}


def test_config_validates_level_range():
    with pytest.raises(ValidationError):
        PolicyConfig(autonomy_level=0)
    with pytest.raises(ValidationError):
        PolicyConfig(autonomy_level=4)


def test_from_yaml_loads_config(tmp_path: Path):
    yaml_file = tmp_path / "policy.yaml"
    yaml_file.write_text("autonomy_level: 3\noverrides:\n  architect: 2\n")
    config = PolicyConfig.from_yaml(yaml_file)
    assert config.autonomy_level == 3
    assert config.overrides == {"architect": 2}


def test_from_yaml_invalid_raises(tmp_path: Path):
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text("autonomy_level: 5\n")
    with pytest.raises(ValidationError):
        PolicyConfig.from_yaml(yaml_file)


def test_from_env_reads_variable(monkeypatch):
    monkeypatch.setenv("SUPERAGENTS_AUTONOMY_LEVEL", "2")
    config = PolicyConfig.from_env()
    assert config.autonomy_level == 2


def test_level_for_with_override():
    config = PolicyConfig(autonomy_level=1, overrides={"architect": 3})
    assert config.level_for("architect") == 3
    assert config.level_for("developer") == 1
