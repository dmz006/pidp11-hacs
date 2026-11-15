"""Live lamp feed on the card, checked under jsdom (no browser).

The card subscribes to ``pidp11_lamps2`` (live frames: percent-on per lamp) and to
``pidp11_lamps`` (the old PC/PSW snapshot). These tests run the real card through
``tests/card/check-lamps.mjs`` and check what is drawn:

* brightness: each lamp's ``--lv`` is its percent, a lamp missing from a frame
  keeps its entity value, and a non-numeric or out-of-range value is not drawn as sent;
* the marker: "live" while frames arrive, "approximate" after the old event alone
  or after 5 seconds with no frame, and the fallback returns to the entity values;
* the old format keeps working on its own.

Requires Node.js and the jsdom package from ``tests/card`` (``npm ci``). If either is
missing the tests are skipped with the reason stated.
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
LAMP_CHECKER = CARD_DIR / "check-lamps.mjs"

# A running device: PC 000200 (bit 7 set), PSW 140246 (bit 15 set), CPU running.
BASE_STATES: dict[str, str] = {
    "sensor.pidp_11_cpu_state": "running",
    "sensor.pidp_11_pc": "000200",
    "sensor.pidp_11_psw": "140246",
    "sensor.pidp_11_system": "211bsd",
    "sensor.pidp_11_cpu_mode": "user",
}


@pytest.fixture(scope="module")
def require_card_runtime() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH; card lamp tests need Node.js")
    if not (CARD_DIR / "node_modules" / "jsdom").is_dir():
        pytest.skip("jsdom is not installed; run `npm ci` in tests/card")


def _run(scenario: dict[str, Any]) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None
    proc = subprocess.run(
        [node, str(LAMP_CHECKER), str(CARD_JS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=CARD_DIR,
    )
    assert proc.returncode == 0, f"check-lamps.mjs crashed: {proc.stderr}"
    report: dict[str, Any] = json.loads(proc.stdout)
    assert report["errors"] == [], "; ".join(report["errors"])
    return report


def _snap(report: dict[str, Any], label: str) -> dict[str, Any]:
    return report["snaps"][label]


# ── Subscriptions ────────────────────────────────────────────────────────────


def test_card_subscribes_to_both_feeds(require_card_runtime: None) -> None:
    report = _run({"states": BASE_STATES, "steps": []})
    assert sorted(report["subscribed"]) == ["pidp11_lamps", "pidp11_lamps2"]


# ── Brightness from percent ──────────────────────────────────────────────────


def test_live_frame_draws_each_lamp_at_its_percent(require_card_runtime: None) -> None:
    frame = {
        "ADDRESS21": 100,
        "ADDRESS0": 50,
        "ADDRESS3": 30,
        "DATA3": 25,
        "RUN": 100,
        "PARITY_HIGH": 80,
        "ADDR_SEL_P_PHY": 100,
    }
    report = _run({
        "states": BASE_STATES,
        "steps": [{"op": "live", "seq": 1, "leds": frame}, {"op": "snap", "label": "live"}],
    })
    live = _snap(report, "live")
    assert live["mode"] == "live"
    assert live["dataMode"] == "live"
    # adr[0] is ADDRESS21 (leftmost); adr[21] is ADDRESS0.
    assert live["adr"][0] == "1"
    assert live["adr"][21] == "0.5"
    assert live["adr"][18] == "0.3"  # ADDRESS3
    assert live["dat"][12] == "0.25"  # DATA3 (dat[0] is DATA15)
    assert live["lamps"]["RUN"] == "1"
    assert live["lamps"]["PARITY_HIGH"] == "0.8"
    assert live["lamps"]["PARITY_LOW"] == "0"  # not in the frame: no entity value, so off


def test_lamp_missing_from_frame_keeps_entity_value(require_card_runtime: None) -> None:
    # ADDRESS7 is not in the frame: the PC entity (000200, bit 7) still lights it.
    report = _run({
        "states": BASE_STATES,
        "steps": [
            {"op": "live", "seq": 1, "leds": {"ADDRESS21": 100}},
            {"op": "snap", "label": "live"},
        ],
    })
    live = _snap(report, "live")
    assert live["adr"][14] == "1"  # ADDRESS7
    assert live["adr"][20] == "0"  # ADDRESS1: not in the frame, PC bit 1 is 0
    assert live["dat"][0] == "1"  # DATA15: not in the frame, PSW bit 15 is 1


def test_non_numeric_value_is_not_drawn_and_out_of_range_is_clamped(
    require_card_runtime: None,
) -> None:
    states = dict(BASE_STATES, **{"sensor.pidp_11_cpu_state": "halted"})
    report = _run({
        "states": states,
        "steps": [
            {"op": "live", "seq": 1, "leds": {"RUN": "100", "PAR_ERR": 150, "DATA0": "100"}},
            {"op": "snap", "label": "live"},
        ],
    })
    live = _snap(report, "live")
    assert live["mode"] == "live"
    assert live["lamps"]["RUN"] == "0"  # a string is ignored: the halted entity value stays
    assert live["lamps"]["PAR_ERR"] == "1"  # 150 is clamped to 100
    assert live["dat"][15] == "0"  # DATA0: the string is ignored, PSW bit 0 is 0


def test_selector_lamp_matches_any_spelling_of_the_position(require_card_runtime: None) -> None:
    report = _run({
        "states": BASE_STATES,
        "steps": [
            {"op": "live", "seq": 1, "leds": {"DATA_SEL_D_P": 100, "ADDR_SEL_KI": 40}},
            {"op": "snap", "label": "live"},
        ],
    })
    live = _snap(report, "live")
    assert live["lamps"]["DATA_SEL_DP"] == "1"
    assert live["lamps"]["ADDR_SEL_KI"] == "0.4"


# ── Live marker and fallback ─────────────────────────────────────────────────


def test_marker_reads_approximate_before_any_frame(require_card_runtime: None) -> None:
    report = _run({"states": BASE_STATES, "steps": [{"op": "snap", "label": "start"}]})
    start = _snap(report, "start")
    assert start["mode"] == "approximate"
    assert start["dataMode"] == "approximate"


def test_frame_then_five_quiet_seconds_falls_back_to_entities(require_card_runtime: None) -> None:
    report = _run({
        "states": BASE_STATES,
        "steps": [
            {"op": "live", "seq": 1, "leds": {"ADDRESS21": 100}},
            {"op": "snap", "label": "live"},
            {"op": "advance", "ms": 4000},
            {"op": "snap", "label": "still-live"},
            {"op": "advance", "ms": 2000},
            {"op": "snap", "label": "quiet"},
        ],
    })
    assert _snap(report, "live")["mode"] == "live"
    assert _snap(report, "still-live")["mode"] == "live"
    quiet = _snap(report, "quiet")
    assert quiet["mode"] == "approximate"
    assert quiet["dataMode"] == "approximate"
    assert quiet["adr"][0] == "0"  # ADDRESS21 is back to the PC entity value


def test_old_event_alone_is_approximate_and_draws_the_snapshot(require_card_runtime: None) -> None:
    report = _run({
        "states": BASE_STATES,
        "steps": [
            {"op": "old", "data": {"address": "000400", "data": "140246"}},
            {"op": "snap", "label": "old"},
        ],
    })
    old = _snap(report, "old")
    assert old["mode"] == "approximate"
    assert old["adr"][13] == "1"  # ADDRESS8, from the old snapshot PC 000400
    assert old["rvPc"] == "000400"


def test_old_event_does_not_mark_the_feed_live(require_card_runtime: None) -> None:
    report = _run({
        "states": BASE_STATES,
        "steps": [
            {"op": "old", "data": {"address": "000400", "data": "140246"}},
            {"op": "advance", "ms": 6000},
            {"op": "snap", "label": "later"},
        ],
    })
    assert _snap(report, "later")["mode"] == "approximate"
