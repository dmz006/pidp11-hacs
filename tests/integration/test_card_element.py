"""Lovelace card element contract, checked under jsdom (no browser).

Home Assistant builds the card with ``document.createElement`` and then calls
``setConfig`` and sets ``hass``. The card script must therefore produce a real
custom element. An old-style constructor function that never runs the
HTMLElement constructor does not, so these tests run the real script through
``tests/card/check-card.mjs`` and assert on what Lovelace relies on.

Requires Node.js and the jsdom package from ``tests/card`` (``npm ci``). If
either is missing the module is skipped with the reason stated.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CARD_JS = REPO_ROOT / "custom_components" / "pidp11" / "www" / "pidp11-panel-card.js"
CARD_DIR = REPO_ROOT / "tests" / "card"
CHECKER = CARD_DIR / "check-card.mjs"


@pytest.fixture(scope="module")
def card_report() -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; card element tests need Node.js")
    if not (CARD_DIR / "node_modules" / "jsdom").is_dir():
        pytest.skip("jsdom is not installed; run `npm ci` in tests/card")
    proc = subprocess.run(
        [node, str(CHECKER), str(CARD_JS)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=CARD_DIR,
    )
    assert proc.returncode == 0, f"check-card.mjs crashed: {proc.stderr}"
    report: dict[str, Any] = json.loads(proc.stdout)
    return report


def _errors(report: dict[str, Any]) -> str:
    return "; ".join(report["errors"]) or "no errors recorded"


def test_card_script_loads(card_report: dict[str, Any]) -> None:
    assert card_report["loaded"], _errors(card_report)


def test_card_script_is_idempotent_on_reload(card_report: dict[str, Any]) -> None:
    assert card_report["redefineOk"], _errors(card_report)


def test_card_registered_in_picker(card_report: dict[str, Any]) -> None:
    assert card_report["pickerRegistered"], "window.customCards has no pidp11-panel-card entry"


def test_createElement_returns_element(card_report: dict[str, Any]) -> None:
    assert card_report["created"], _errors(card_report)
    assert card_report["isHTMLElement"], "created element is not an HTMLElement"


def test_element_has_setConfig(card_report: dict[str, Any]) -> None:
    assert card_report["hasSetConfig"] is True, _errors(card_report)


def test_element_has_getCardSize(card_report: dict[str, Any]) -> None:
    assert card_report["hasGetCardSize"] is True, _errors(card_report)
    assert isinstance(card_report["cardSize"], int), card_report["cardSize"]


def test_setConfig_then_hass_renders_shadow_root(card_report: dict[str, Any]) -> None:
    assert card_report["rendered"] is True, _errors(card_report)
    # ADDRESS readout comes from pidp11_pc state "000200" (octal).
    assert card_report["rvPc"] == "000200", card_report["rvPc"]


def test_hass_subscribes_to_lamp_feed(card_report: dict[str, Any]) -> None:
    assert card_report["subscribed"] == 1, _errors(card_report)


def test_disconnect_releases_lamp_feed(card_report: dict[str, Any]) -> None:
    assert card_report["unsubscribed"] == 1, _errors(card_report)
