"""Constants for the PiDP-11 integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pidp11"

CONF_HOST: Final = "host"
CONF_REMOTE_CONSOLE_PORT: Final = "remote_console_port"
CONF_SHARED_SECRET: Final = "shared_secret"

# On HAOS the add-on hostname resolves inside the Supervisor network;
# users on the same LAN can use the Pi's IP address instead.
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_REMOTE_CONSOLE_PORT: Final = 2223

# Path written by the add-on so the integration can auto-discover the secret.
SHARED_SECRET_PATH: Final = "/share/pidp11/remote_console.secret"
CURRENT_SYSTEM_PATH: Final = "/share/pidp11/current_system"

# Options (set in the options flow; defaults apply until the user changes them).
OPT_POLL_INTERVAL: Final = "poll_interval_seconds"
OPT_LAMP_FPS: Final = "lamp_fps"

POLL_INTERVAL_DEFAULT: Final = 5
POLL_INTERVAL_MIN: Final = 1
POLL_INTERVAL_MAX: Final = 60

LAMP_FPS_DEFAULT: Final = 10
LAMP_FPS_MIN: Final = 5
LAMP_FPS_MAX: Final = 20

SERVICE_BOOT: Final = "boot"
SERVICE_HALT: Final = "halt"
SERVICE_CONTINUE: Final = "continue_cpu"
SERVICE_DEPOSIT: Final = "deposit"
SERVICE_EXAMINE: Final = "examine"

CPU_STATE_RUNNING: Final = "running"
CPU_STATE_HALTED: Final = "halted"
CPU_STATE_OFFLINE: Final = "offline"

CPU_MODE_KERNEL: Final = "kernel"
CPU_MODE_SUPERVISOR: Final = "supervisor"
CPU_MODE_USER: Final = "user"

EVENT_SR_CHANGED: Final = "pidp11_sr_changed"
EVENT_SWITCH_CHANGED: Final = "pidp11_switch_changed"
EVENT_LAMPS: Final = "pidp11_lamps"
# Live lamp feed: one event per LAMPS2 line from the add-on, with percent-on per lamp.
EVENT_LAMPS2: Final = "pidp11_lamps2"

WATCH_PORT_OFFSET: Final = 2
LAMP_PORT_OFFSET: Final = 3


def _clamp_int(value: object, low: int, high: int, default: int) -> int:
    """An integer option clamped to [low, high]; anything that is not a number gives the default."""
    if isinstance(value, bool):
        return default
    try:
        number = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default
    return min(max(number, low), high)


def clamp_poll_interval(value: object) -> int:
    """Poll interval in seconds, 1 to 60."""
    return _clamp_int(value, POLL_INTERVAL_MIN, POLL_INTERVAL_MAX, POLL_INTERVAL_DEFAULT)


def clamp_lamp_fps(value: object) -> int:
    """Lamp refresh rate in frames per second, 5 to 20."""
    return _clamp_int(value, LAMP_FPS_MIN, LAMP_FPS_MAX, LAMP_FPS_DEFAULT)
