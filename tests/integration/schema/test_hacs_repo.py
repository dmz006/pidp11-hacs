"""HACS repo-level manifest + add-on repository manifest sanity checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


def test_hacs_json_exists(repo_root: Path) -> None:
    data = json.loads((repo_root / "hacs.json").read_text())
    assert data["name"]
    assert data["homeassistant"]


def test_repository_yaml_exists(repo_root: Path) -> None:
    data = yaml.safe_load((repo_root / "repository.yaml").read_text())
    assert data["name"]
    assert data["url"].startswith("https://")


def test_addon_dir_exists(repo_root: Path) -> None:
    assert (repo_root / "pidp11-addon" / "config.yaml").exists()
    assert (repo_root / "pidp11-addon" / "Dockerfile").exists()


def test_integration_dir_exists(repo_root: Path) -> None:
    base = repo_root / "custom_components" / "pidp11"
    for required in (
        "manifest.json",
        "__init__.py",
        "config_flow.py",
        "const.py",
        "coordinator.py",
        "sensor.py",
        "switch.py",
        "services.yaml",
        "strings.json",
        "translations/en.json",
    ):
        assert (base / required).exists(), f"missing {required}"
