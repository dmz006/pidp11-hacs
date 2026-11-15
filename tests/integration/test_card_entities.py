"""Card entity ids must match the entities the integration registers.

Home Assistant names an entity from its device name and its entity name. The
device is "PiDP-11", so the slug is ``pidp_11`` and the entities are
``sensor.pidp_11_cpu_state``, ``sensor.pidp_11_pc`` and so on. The card used to
default to ``sensor.pidp11_*``, which no install ever produces.

Three layers are checked here:

1. The registry contract. The integration is set up under pytest-homeassistant
   with a fake coordinator, and the entity registry is read back. The exact set
   of unique ids and entity ids is asserted.
2. The card defaults. The default ids in the card script are parsed from the
   JS source and compared with the registry.
3. The card lookup. ``tests/card/check-entities.mjs`` renders the real card under
   jsdom with several hass states. Defaults must find the device entities, a
   missing default must be found by suffix under the device prefix, and explicit
   options must still win.

Layer 3 needs Node.js and the jsdom package from ``tests/card`` (``npm ci``). If
either is missing the tests are skipped with the reason stated.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pidp11.const import (
    CONF_HOST,
    CONF_REMOTE_CONSOLE_PORT,
    CONF_SHARED_SECRET,
    DOMAIN,
)
from custom_components.pidp11.coordinator import PiDP11Coordinator, PiDP11State

REPO_ROOT = Path(__file__).resolve().parents[2]
CARD_JS = REPO_ROOT / "custom_components" / "pidp11" / "www" / "pidp11-panel-card.js"
CARD_DIR = REPO_ROOT / "tests" / "card"
ENTITY_CHECKER = CARD_DIR / "check-entities.mjs"

ENTRY_ID = "pidp11entry"
SR_BITS = range(22)  # SR0..SR21: the card draws 22 switches and the integration has 22 sensors.

# Unique id -> entity id the integration derives. Unique ids are
# "<entry_id>_<key>"; the entity ids follow HA's naming from "PiDP-11" plus the
# entity name (or translated name, for translation_key entities).
EXPECTED_ENTITY_IDS: dict[str, str] = {
    f"{ENTRY_ID}_cpu_state": "sensor.pidp_11_cpu_state",
    f"{ENTRY_ID}_pc": "sensor.pidp_11_pc",
    f"{ENTRY_ID}_psw": "sensor.pidp_11_psw",
    f"{ENTRY_ID}_sr": "sensor.pidp_11_switch_register",
    f"{ENTRY_ID}_cpu_mode": "sensor.pidp_11_cpu_mode",
    f"{ENTRY_ID}_system": "sensor.pidp_11_system",
    f"{ENTRY_ID}_halted": "binary_sensor.pidp_11_cpu_halted",
    f"{ENTRY_ID}_cpu_running": "switch.pidp_11_cpu_running",
    **{f"{ENTRY_ID}_sr{b}": f"binary_sensor.pidp_11_sr{b}" for b in SR_BITS},
}

# Card config key -> the unique-id key whose entity it should default to.
CARD_SINGLE_KEYS: dict[str, str] = {
    "state_entity": "cpu_state",
    "pc_entity": "pc",
    "psw_entity": "psw",
    "system_entity": "system",
    "cpu_mode_entity": "cpu_mode",
}

FRONTEND_FLAG = "pidp11_frontend_registered"  # __init__.py skips the static path when set


class FakeCoordinator(PiDP11Coordinator):
    """Coordinator with no TCP link: fixed data, watch tasks are no-ops."""

    async def async_config_entry_first_refresh(self) -> None:
        self.data = PiDP11State(
            cpu_state="running",
            pc="000200",
            psw="140246",
            sr="000005",
            cpu_mode="user",
            system="211bsd",
        )
        self.last_update_success = True

    def start_sr_watch(self, name: str) -> None:
        return None

    def start_lamp_watch(self, name: str) -> None:
        return None

    def stop_sr_watch(self) -> None:
        return None

    def stop_lamp_watch(self) -> None:
        return None


@pytest.fixture
def repo_custom_components_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point custom_components at the repo copy only.

    An editable install adds a bogus entry to ``custom_components.__path__``; HA
    scans every entry there and fails on it. Pinning the path to the repo keeps
    the loader on the code under test.
    """
    import custom_components

    monkeypatch.setattr(custom_components, "__path__", [str(REPO_ROOT / "custom_components")])


@pytest.fixture
async def registry_by_unique_id(
    hass: Any, enable_custom_integrations: None, repo_custom_components_path: None
) -> AsyncIterator[dict[str, str]]:
    """Set the integration up with the fake coordinator; return unique_id -> entity_id."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_REMOTE_CONSOLE_PORT: 2223,
            CONF_SHARED_SECRET: "a" * 64,
        },
    )
    entry.add_to_hass(hass)
    hass.data[FRONTEND_FLAG] = True
    with patch("custom_components.pidp11.PiDP11Coordinator", FakeCoordinator):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    mapping = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    yield mapping


# ── 1. Registry contract ─────────────────────────────────────────────────────


async def test_registry_has_exactly_the_expected_entities(
    registry_by_unique_id: dict[str, str],
) -> None:
    assert registry_by_unique_id == EXPECTED_ENTITY_IDS


async def test_registry_has_no_pidp11_prefixed_entity_ids(
    registry_by_unique_id: dict[str, str],
) -> None:
    # HA never produces "pidp11" for this device name: the slug keeps the underscore.
    assert not [eid for eid in registry_by_unique_id.values() if ".pidp11_" in eid]


# ── 2. Card defaults vs registry ─────────────────────────────────────────────


def _card_defaults() -> dict[str, str]:
    """Default entity ids as written in setConfig: `key: config.key || "id"`."""
    source = CARD_JS.read_text(encoding="utf-8")
    pairs = re.findall(r'(\w+):\s+config\.\w+\s+\|\|\s+"([^"]+)"', source)
    return dict(pairs)


def test_card_defaults_cover_every_configurable_key() -> None:
    defaults = _card_defaults()
    assert set(defaults) == {*CARD_SINGLE_KEYS, "sr_prefix"}, defaults


@pytest.mark.parametrize("key", sorted(CARD_SINGLE_KEYS))
def test_card_default_matches_registered_entity(
    key: str, registry_by_unique_id: dict[str, str]
) -> None:
    default = _card_defaults()[key]
    registered = registry_by_unique_id[f"{ENTRY_ID}_{CARD_SINGLE_KEYS[key]}"]
    assert default == registered


def test_card_sr_prefix_builds_every_registered_switch(
    registry_by_unique_id: dict[str, str],
) -> None:
    prefix = _card_defaults()["sr_prefix"]
    built = {f"{prefix}{b}" for b in SR_BITS}
    registered = {registry_by_unique_id[f"{ENTRY_ID}_sr{b}"] for b in SR_BITS}
    assert built == registered


# ── 3. Card lookup under jsdom ───────────────────────────────────────────────


@pytest.fixture(scope="module")
def require_card_runtime() -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH; card lookup tests need Node.js")
    if not (CARD_DIR / "node_modules" / "jsdom").is_dir():
        pytest.skip("jsdom is not installed; run `npm ci` in tests/card")


def _device_states(
    device: str = "pidp_11",
    *,
    sr_on: tuple[int, ...] = (),
    pc: str = "000200",
) -> dict[str, str]:
    """A full set of device states, as the integration reports them."""
    states = {
        f"sensor.{device}_cpu_state": "running",
        f"sensor.{device}_pc": pc,
        f"sensor.{device}_psw": "140246",
        f"sensor.{device}_system": "211bsd",
        f"sensor.{device}_cpu_mode": "user",
    }
    for b in SR_BITS:
        states[f"binary_sensor.{device}_sr{b}"] = "on" if b in sr_on else "off"
    return states


def _render(
    require_card_runtime: None,
    config: dict[str, Any],
    states: dict[str, str],
) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None
    scenario = {
        "config": config,
        "states": {eid: {"state": value} for eid, value in states.items()},
    }
    proc = subprocess.run(
        [node, str(ENTITY_CHECKER), str(CARD_JS), json.dumps(scenario)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=CARD_DIR,
    )
    assert proc.returncode == 0, f"check-entities.mjs crashed: {proc.stderr}"
    report: dict[str, Any] = json.loads(proc.stdout)
    return report


def _errors(report: dict[str, Any]) -> str:
    return "; ".join(report["errors"]) or "no errors recorded"


def test_defaults_find_device_entities(require_card_runtime: None) -> None:
    report = _render(require_card_runtime, {}, _device_states(sr_on=(0, 5, 21)))
    assert report["rendered"], _errors(report)
    assert report["cpuText"] == "RUNNING", report
    assert report["sysText"] == "211bsd", report
    assert report["rvPc"] == "000200", report
    assert report["srOn"] == 3, report


def test_missing_default_is_found_by_suffix_under_device_prefix(
    require_card_runtime: None,
) -> None:
    # HA appends _2 when an id is taken. The default sensor.pidp_11_pc is absent;
    # the same suffix under the device prefix is the entity to use.
    states = _device_states()
    del states["sensor.pidp_11_pc"]
    states["sensor.pidp_11_pc_2"] = "000450"
    report = _render(require_card_runtime, {}, states)
    assert report["rendered"], _errors(report)
    assert report["rvPc"] == "000450", report


def test_suffix_lookup_does_not_match_a_longer_suffix(require_card_runtime: None) -> None:
    # sr1 must not pick up sr11: the scan is for an exact suffix.
    states = _device_states(sr_on=(11,))
    del states["binary_sensor.pidp_11_sr1"]
    report = _render(require_card_runtime, {}, states)
    assert report["rendered"], _errors(report)
    assert report["srOn"] == 1, report


def test_explicit_option_wins_over_device_entity(require_card_runtime: None) -> None:
    states = _device_states(pc="000200")
    states["sensor.my_pc"] = "000777"
    report = _render(require_card_runtime, {"pc_entity": "sensor.my_pc"}, states)
    assert report["rendered"], _errors(report)
    assert report["rvPc"] == "000777", report


def test_explicit_option_missing_falls_back_to_device_entity(
    require_card_runtime: None,
) -> None:
    report = _render(require_card_runtime, {"pc_entity": "sensor.not_there"}, _device_states())
    assert report["rendered"], _errors(report)
    assert report["rvPc"] == "000200", report


def test_explicit_sr_prefix_is_honoured(require_card_runtime: None) -> None:
    states = {"binary_sensor.front_sr0": "on", "binary_sensor.front_sr1": "on"}
    report = _render(require_card_runtime, {"sr_prefix": "binary_sensor.front_sr"}, states)
    assert report["rendered"], _errors(report)
    assert report["srOn"] == 2, report


def test_no_entities_renders_offline_without_error(require_card_runtime: None) -> None:
    report = _render(require_card_runtime, {}, {})
    assert report["rendered"], _errors(report)
    assert report["cpuText"] == "OFFLINE", report
    assert report["errors"] == [], report


def test_old_style_pidp11_ids_still_resolve(require_card_runtime: None) -> None:
    # Installs or devices named "PiDP11" produce pidp11_* ids; they keep working.
    report = _render(require_card_runtime, {}, _device_states(device="pidp11"))
    assert report["rendered"], _errors(report)
    assert report["rvPc"] == "000200", report
