"""Data update coordinator for PiDP-11. Skeleton — lands in S3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@dataclass(slots=True, frozen=True)
class PiDP11State:
    """Snapshot of the running emulator."""

    run_state: str
    pc: int
    psw: int
    last_error: str | None


class PiDP11Coordinator:
    """Polls the SimH remote console via the auth shim."""

    def __init__(self, hass: "HomeAssistant", host: str, port: int, secret: str) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self._secret = secret

    async def async_refresh(self) -> PiDP11State:
        raise NotImplementedError("pending S3")
