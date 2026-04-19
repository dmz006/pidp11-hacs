"""Constants for the PiDP-11 integration. Skeleton — all values subject to S3."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pidp11"

CONF_HOST: Final = "host"
CONF_REMOTE_CONSOLE_PORT: Final = "remote_console_port"
CONF_SHARED_SECRET: Final = "shared_secret"

DEFAULT_HOST: Final = "a0d7b954-pidp11"
DEFAULT_REMOTE_CONSOLE_PORT: Final = 2223

UPDATE_INTERVAL_SECONDS: Final = 5

SERVICE_BOOT: Final = "boot"
SERVICE_HALT: Final = "halt"
SERVICE_DEPOSIT: Final = "deposit"
SERVICE_EXAMINE: Final = "examine"

EVENT_HALT: Final = "pidp11_halt"
EVENT_TRAP: Final = "pidp11_trap"
EVENT_SWITCH: Final = "pidp11_switch"
