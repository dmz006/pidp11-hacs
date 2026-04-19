"""Shared pytest fixtures. Skeleton — expanded per-sprint."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def integration_manifest_path(repo_root: Path) -> Path:
    return repo_root / "custom_components" / "pidp11" / "manifest.json"


@pytest.fixture(scope="session")
def addon_config_path(repo_root: Path) -> Path:
    return repo_root / "pidp11-addon" / "config.yaml"
