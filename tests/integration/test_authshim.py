"""Unit tests for authshim.py — auth shim protocol and watch stream.

These tests do NOT require a running add-on container or HA instance.
They run in the standard CI schema-and-unit job (no addon marker).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# pytest-homeassistant-custom-component enables pytest-socket which blocks
# raw TCP by default. These tests start real asyncio TCP servers on loopback
# so we opt in to socket access at the module level.
pytestmark = [pytest.mark.enable_socket]

# Make the add-on directory importable.
_ADDON_DIR = Path(__file__).resolve().parent.parent.parent / "pidp11-addon"
if str(_ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(_ADDON_DIR))


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _start_mock_simh(
    responses: list[str],
    *,
    banner: bytes = b"PDP-11 Remote Console\nsim> ",
) -> tuple[int, asyncio.Server]:
    """Start a minimal mock SimH server.

    On connect, sends *banner* immediately.
    For each b'EXAMINE SR\\n' received, sends the next entry from *responses*
    (formatted as 'SR:\\t<value>\\nsim> ') then moves to the next.
    The last entry is repeated indefinitely.
    """
    idx = [0]

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(banner)
        await writer.drain()
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            if line.strip() == b"EXAMINE SR":
                val = responses[min(idx[0], len(responses) - 1)]
                idx[0] += 1
                writer.write(f"SR:\t{val}\nsim> ".encode())
                await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return port, server


async def _start_mock_simh_multi(
    responses: dict[bytes, list[str]],
    *,
    banner: bytes = b"PDP-11 Remote Console\nsim> ",
) -> tuple[int, asyncio.Server]:
    """Start a mock SimH that handles multiple EXAMINE commands independently.

    responses: mapping of command bytes → list of return values.
    Each command key tracks its own index; the last value in each list repeats.
    The register name is derived from the last word of the command.
    """
    counters: dict[bytes, list[int]] = {cmd: [0] for cmd in responses}

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(banner)
        await writer.drain()
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            cmd = line.strip()
            if cmd in responses:
                vals = responses[cmd]
                idx = counters[cmd][0]
                val = vals[min(idx, len(vals) - 1)]
                counters[cmd][0] = idx + 1
                reg = cmd.split()[-1].decode()  # b"EXAMINE PC" → "PC"
                writer.write(f"{reg}:\t{val}\nsim> ".encode())
                await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return port, server


async def _connect_and_auth(
    port: int, secret: str = "testsecret"
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"AUTH {secret}\n".encode())
    await writer.drain()
    return reader, writer


async def _close_servers(*servers: asyncio.Server) -> None:
    """Close servers and cancel any handler tasks they may have spawned.

    Using server.close() without wait_closed() avoids blocking on handlers
    that loop indefinitely (e.g. _handle_watch when SR value stays constant).
    """
    for s in servers:
        s.close()
    pending = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}
    for t in pending:
        t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bad_auth_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong secret on the main port → DENY bad-auth."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))

    server = await asyncio.start_server(shim._handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        reader, writer = await _connect_and_auth(port, secret="wrongsecret")
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(server)

    assert response.startswith(b"DENY")


@pytest.mark.asyncio
async def test_watch_bad_auth_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong secret on the watch port → DENY bad-auth."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))

    server = await asyncio.start_server(shim._handle_watch, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        reader, writer = await _connect_and_auth(port, secret="wrongsecret")
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(server)

    assert response.startswith(b"DENY")


@pytest.mark.asyncio
async def test_watch_streams_initial_sr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock SimH returning '000042' → verify EVENT sr value=000042 is streamed."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "WATCH_INTERVAL_MS", 10.0)

    simh_port, simh_server = await _start_mock_simh(["000042"])
    monkeypatch.setattr(shim, "SIMH_PORT", simh_port)

    watch_server = await asyncio.start_server(shim._handle_watch, "127.0.0.1", 0)
    watch_port = watch_server.sockets[0].getsockname()[1]

    reader, writer = await _connect_and_auth(watch_port)
    try:
        ok_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert ok_line.strip() == b"OK"

        event_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(watch_server, simh_server)

    assert event_line.strip() == b"EVENT sr value=000042"


@pytest.mark.asyncio
async def test_watch_streams_sr_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock SimH: 000000, 000000, 000001 → verify 2 EVENT lines (initial + change)."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "WATCH_INTERVAL_MS", 10.0)

    simh_port, simh_server = await _start_mock_simh(["000000", "000000", "000001"])
    monkeypatch.setattr(shim, "SIMH_PORT", simh_port)

    watch_server = await asyncio.start_server(shim._handle_watch, "127.0.0.1", 0)
    watch_port = watch_server.sockets[0].getsockname()[1]

    reader, writer = await _connect_and_auth(watch_port)
    try:
        ok_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert ok_line.strip() == b"OK"

        event1 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert event1.strip() == b"EVENT sr value=000000"

        event2 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert event2.strip() == b"EVENT sr value=000001"

        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(watch_server, simh_server)


@pytest.mark.asyncio
async def test_lamp_bad_auth_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wrong secret on the lamp port → DENY bad-auth."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))

    server = await asyncio.start_server(shim._handle_lamp_stream, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        reader, writer = await _connect_and_auth(port, secret="wrongsecret")
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(server)

    assert response.startswith(b"DENY")


@pytest.mark.asyncio
async def test_lamp_streams_initial_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mock SimH returning PC=001400, PSW=004000 → EVENT lamps ADDRESS=001400 DATA=004000."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "LAMP_INTERVAL_MS", 10.0)

    simh_port, simh_server = await _start_mock_simh_multi({
        b"EXAMINE PC":  ["001400"],
        b"EXAMINE PSW": ["004000"],
    })
    monkeypatch.setattr(shim, "SIMH_PORT", simh_port)

    lamp_server = await asyncio.start_server(shim._handle_lamp_stream, "127.0.0.1", 0)
    lamp_port = lamp_server.sockets[0].getsockname()[1]

    reader, writer = await _connect_and_auth(lamp_port)
    try:
        ok_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert ok_line.strip() == b"OK"

        event_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(lamp_server, simh_server)

    assert event_line.strip() == b"EVENT lamps ADDRESS=001400 DATA=004000"


@pytest.mark.asyncio
async def test_lamp_streams_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lamp stream fires on initial connect and again only when PC or PSW changes."""
    import authshim as shim  # type: ignore[import]

    secret_file = tmp_path / "secret"
    secret_file.write_text("testsecret")
    monkeypatch.setattr(shim, "SECRET_FILE", str(secret_file))
    monkeypatch.setattr(shim, "_DRAIN_QUIET", 0.05)
    monkeypatch.setattr(shim, "LAMP_INTERVAL_MS", 10.0)

    # Poll 1: PC=001400, PS=004000  → event (initial)
    # Poll 2: same values            → no event
    # Poll 3: PC=002000, PS=000000  → event (changed)
    simh_port, simh_server = await _start_mock_simh_multi({
        b"EXAMINE PC":  ["001400", "001400", "002000"],
        b"EXAMINE PSW": ["004000", "004000", "000000"],
    })
    monkeypatch.setattr(shim, "SIMH_PORT", simh_port)

    lamp_server = await asyncio.start_server(shim._handle_lamp_stream, "127.0.0.1", 0)
    lamp_port = lamp_server.sockets[0].getsockname()[1]

    reader, writer = await _connect_and_auth(lamp_port)
    try:
        ok_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert ok_line.strip() == b"OK"

        event1 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert event1.strip() == b"EVENT lamps ADDRESS=001400 DATA=004000"

        event2 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert event2.strip() == b"EVENT lamps ADDRESS=002000 DATA=000000"

        writer.close()
        await writer.wait_closed()
    finally:
        await _close_servers(lamp_server, simh_server)
