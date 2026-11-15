"""Options flow: poll interval and lamp refresh rate.

Checks the clamp helpers, the form (defaults, and the values stored in the entry),
that a saved change reloads the entry so the coordinator uses the new values without
a Home Assistant restart, and that out-of-range input is refused.

Runs under pytest-homeassistant with a fake coordinator (no TCP link, no Pi).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pidp11.const import (
    CONF_HOST,
    CONF_REMOTE_CONSOLE_PORT,
    CONF_SHARED_SECRET,
    DOMAIN,
    LAMP_FPS_DEFAULT,
    OPT_LAMP_FPS,
    OPT_POLL_INTERVAL,
    POLL_INTERVAL_DEFAULT,
    clamp_lamp_fps,
    clamp_poll_interval,
)
from custom_components.pidp11.coordinator import PiDP11Coordinator, PiDP11State

pytestmark = [pytest.mark.usefixtures("socket_enabled")]

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRY_ID = "pidp11optionsentry"
FRONTEND_FLAG = "pidp11_frontend_registered"


class FakeCoordinator(PiDP11Coordinator):
    """Real constructor (so the options reach it), no TCP link."""

    async def async_config_entry_first_refresh(self) -> None:
        self.data = PiDP11State(
            cpu_state="running", pc="000200", psw="140246", sr="000000",
            cpu_mode="user", system="211bsd",
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
    """Load the integration from the repo, not from an editable install's path."""
    import custom_components

    monkeypatch.setattr(custom_components, "__path__", [str(REPO_ROOT / "custom_components")])


def _entry(options: dict[str, Any] | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        data={
            CONF_HOST: "127.0.0.1",
            CONF_REMOTE_CONSOLE_PORT: 2223,
            CONF_SHARED_SECRET: "b" * 64,
        },
        options=options or {},
    )


@pytest.fixture
async def setup_entry(
    hass: Any, enable_custom_integrations: None, repo_custom_components_path: None
) -> AsyncIterator[Any]:
    """Return a function that sets the entry up with the given options (fake coordinator)."""
    hass.data[FRONTEND_FLAG] = True
    patcher = patch("custom_components.pidp11.PiDP11Coordinator", FakeCoordinator)
    patcher.start()

    async def setup(options: dict[str, Any] | None = None) -> Any:
        entry = _entry(options)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    yield setup
    patcher.stop()


def _defaults(form: dict[str, Any]) -> dict[str, Any]:
    return {str(k): k.default() for k in form["data_schema"].schema}


# ── Clamp helpers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4, 5), (5, 5), (10, 10), (20, 20), (21, 20), (500, 20), ("12", 12), ("x", 10), (None, 10), (True, 10)],
)
def test_lamp_fps_is_clamped_to_five_to_twenty(value: object, expected: int) -> None:
    assert clamp_lamp_fps(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 1), (1, 1), (5, 5), (60, 60), (61, 60), ("7", 7), ("x", 5), (None, 5), (False, 5)],
)
def test_poll_interval_is_clamped_to_one_to_sixty(value: object, expected: int) -> None:
    assert clamp_poll_interval(value) == expected


# ── The form ─────────────────────────────────────────────────────────────────


async def test_form_offers_the_defaults(hass: Any, setup_entry: Any) -> None:
    entry = await setup_entry()
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["type"] == FlowResultType.FORM
    assert form["step_id"] == "init"
    defaults = _defaults(form)
    assert defaults == {OPT_POLL_INTERVAL: POLL_INTERVAL_DEFAULT, OPT_LAMP_FPS: LAMP_FPS_DEFAULT}
    assert LAMP_FPS_DEFAULT == 10
    assert POLL_INTERVAL_DEFAULT == 5


async def test_form_shows_the_stored_values(hass: Any, setup_entry: Any) -> None:
    entry = await setup_entry({OPT_POLL_INTERVAL: 15, OPT_LAMP_FPS: 12})
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert _defaults(form) == {OPT_POLL_INTERVAL: 15, OPT_LAMP_FPS: 12}


# ── Saving ───────────────────────────────────────────────────────────────────


async def test_saved_options_reload_the_coordinator_without_restart(
    hass: Any, setup_entry: Any
) -> None:
    entry = await setup_entry()
    old = entry.runtime_data
    assert old.update_interval == timedelta(seconds=POLL_INTERVAL_DEFAULT)
    assert old.lamp_fps == LAMP_FPS_DEFAULT

    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={OPT_POLL_INTERVAL: 15, OPT_LAMP_FPS: 12}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options == {OPT_POLL_INTERVAL: 15, OPT_LAMP_FPS: 12}
    new = entry.runtime_data
    assert new is not old, "the entry was not reloaded"
    assert new.update_interval == timedelta(seconds=15)
    assert new.lamp_fps == 12
    assert new.poll_interval == 15


async def test_saved_values_are_stored_as_integers(hass: Any, setup_entry: Any) -> None:
    entry = await setup_entry()
    form = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={OPT_POLL_INTERVAL: 7.0, OPT_LAMP_FPS: 9.0}
    )
    await hass.async_block_till_done()
    assert entry.options == {OPT_POLL_INTERVAL: 7, OPT_LAMP_FPS: 9}
    assert all(type(v) is int for v in entry.options.values())


@pytest.mark.parametrize(
    "user_input",
    [
        {OPT_POLL_INTERVAL: 5, OPT_LAMP_FPS: 4},     # below 5 fps
        {OPT_POLL_INTERVAL: 5, OPT_LAMP_FPS: 21},    # above 20 fps
        {OPT_POLL_INTERVAL: 0, OPT_LAMP_FPS: 10},    # below 1 s
        {OPT_POLL_INTERVAL: 61, OPT_LAMP_FPS: 10},   # above 60 s
    ],
)
async def test_out_of_range_input_is_refused(
    hass: Any, setup_entry: Any, user_input: dict[str, int]
) -> None:
    entry = await setup_entry()
    form = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(form["flow_id"], user_input=user_input)
    assert entry.options == {}
