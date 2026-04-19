"""Schema tests for custom_components/pidp11/manifest.json.

These tests are the one part of S0 that should already pass — the manifest
exists and has required keys. They lock the surface before anything else
is built.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REQUIRED_KEYS = {
    "domain",
    "name",
    "version",
    "documentation",
    "issue_tracker",
    "codeowners",
    "config_flow",
    "iot_class",
    "requirements",
}

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_required_keys(integration_manifest_path: Path) -> None:
    manifest = _load(integration_manifest_path)
    missing = REQUIRED_KEYS - manifest.keys()
    assert not missing, f"manifest.json missing keys: {missing}"


def test_domain_is_pidp11(integration_manifest_path: Path) -> None:
    assert _load(integration_manifest_path)["domain"] == "pidp11"


def test_semver(integration_manifest_path: Path) -> None:
    version = _load(integration_manifest_path)["version"]
    assert SEMVER_RE.match(version), f"version {version!r} is not SemVer"


def test_codeowners_is_list_of_handles(integration_manifest_path: Path) -> None:
    codeowners = _load(integration_manifest_path)["codeowners"]
    assert isinstance(codeowners, list) and codeowners
    assert all(isinstance(x, str) and x.startswith("@") for x in codeowners)


def test_config_flow_enabled(integration_manifest_path: Path) -> None:
    assert _load(integration_manifest_path)["config_flow"] is True
