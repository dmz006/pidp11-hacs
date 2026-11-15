"""Options flow for PiDP-11: poll interval and lamp refresh rate."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    LAMP_FPS_DEFAULT,
    LAMP_FPS_MAX,
    LAMP_FPS_MIN,
    OPT_LAMP_FPS,
    OPT_POLL_INTERVAL,
    POLL_INTERVAL_DEFAULT,
    POLL_INTERVAL_MAX,
    POLL_INTERVAL_MIN,
    clamp_lamp_fps,
    clamp_poll_interval,
)


def _number(low: int, high: int, unit: str | None = None) -> selector.NumberSelector:
    config: dict[str, Any] = {
        "min": low,
        "max": high,
        "step": 1,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


class PiDP11OptionsFlow(OptionsFlow):
    """Change how often the coordinator polls and how fast the lamp feed is drawn."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # The selector already rejects values out of range; clamping here keeps
            # what is stored equal to what the coordinator will use.
            return self.async_create_entry(
                title="",
                data={
                    OPT_POLL_INTERVAL: clamp_poll_interval(user_input[OPT_POLL_INTERVAL]),
                    OPT_LAMP_FPS: clamp_lamp_fps(user_input[OPT_LAMP_FPS]),
                },
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_POLL_INTERVAL,
                    default=clamp_poll_interval(
                        options.get(OPT_POLL_INTERVAL, POLL_INTERVAL_DEFAULT)
                    ),
                ): _number(POLL_INTERVAL_MIN, POLL_INTERVAL_MAX, "s"),
                vol.Required(
                    OPT_LAMP_FPS,
                    default=clamp_lamp_fps(options.get(OPT_LAMP_FPS, LAMP_FPS_DEFAULT)),
                ): _number(LAMP_FPS_MIN, LAMP_FPS_MAX, "fps"),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
