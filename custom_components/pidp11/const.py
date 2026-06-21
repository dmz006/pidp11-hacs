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

UPDATE_INTERVAL_SECONDS: Final = 5

SERVICE_BOOT: Final = "boot"
SERVICE_HALT: Final = "halt"
SERVICE_CONTINUE: Final = "continue_cpu"
SERVICE_DEPOSIT: Final = "deposit"
SERVICE_EXAMINE: Final = "examine"

CPU_STATE_RUNNING: Final = "running"
CPU_STATE_HALTED: Final = "halted"
CPU_STATE_OFFLINE: Final = "offline"
