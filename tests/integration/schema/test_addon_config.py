"""Schema tests for pidp11-addon/config.yaml. These lock the add-on surface."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REQUIRED_KEYS = {
    "slug",
    "name",
    "version",
    "arch",
    "startup",
    "boot",
    "ports",
    "map",
    "options",
    "schema",
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def test_required_keys(addon_config_path: Path) -> None:
    cfg = _load(addon_config_path)
    missing = REQUIRED_KEYS - cfg.keys()
    assert not missing, f"config.yaml missing keys: {missing}"


def test_arm64_in_arch(addon_config_path: Path) -> None:
    assert "aarch64" in _load(addon_config_path)["arch"]


def test_slug_matches_integration_domain(addon_config_path: Path) -> None:
    assert _load(addon_config_path)["slug"] == "pidp11"


def test_ssh_password_in_options_and_schema(addon_config_path: Path) -> None:
    cfg = _load(addon_config_path)
    assert "ssh_password" in cfg["options"]
    assert cfg["schema"]["ssh_password"] == "password"


def test_default_boot_enum_present(addon_config_path: Path) -> None:
    schema = _load(addon_config_path)["schema"]["default_boot"]
    assert schema.startswith("list(")


def test_dev_mem_mapped(addon_config_path: Path) -> None:
    cfg = _load(addon_config_path)
    assert "/dev/mem" in cfg.get("devices", [])
    assert "SYS_RAWIO" in cfg.get("privileged", [])
