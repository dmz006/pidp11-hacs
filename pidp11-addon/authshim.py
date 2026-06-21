#!/usr/bin/env python3
"""
Auth shim: accepts TCP on LISTEN_PORT (default 2223), requires
    AUTH <secret>\n
then proxies the byte stream to SimH's native remote console on SIMH_PORT (default 2224).

Wire protocol is documented in docs/contracts/remote-console.md.
"""
import asyncio
import os
import sys

LISTEN_PORT = int(os.environ.get("AUTHSHIM_PORT", "2223"))
SIMH_PORT   = int(os.environ.get("SIMH_PORT",     "2224"))
SECRET_FILE = os.environ.get("SECRET_FILE", "/data/remote_console.secret")
AUTH_TIMEOUT = 5.0
VERSION = "1.0.0"


def _load_secret() -> str:
    with open(SECRET_FILE) as fh:
        return fh.read().strip()


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(4096)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            dst.close()
            await dst.wait_closed()
        except Exception:
            pass


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    try:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=AUTH_TIMEOUT)
        except asyncio.TimeoutError:
            writer.write(b"DENY auth-timeout\n")
            await writer.drain()
            return

        parts = raw.decode(errors="replace").rstrip("\r\n").split(" ", 1)
        if len(parts) != 2 or parts[0] != "AUTH" or parts[1] != _load_secret():
            writer.write(b"DENY bad-auth\n")
            await writer.drain()
            return

        writer.write(b"OK\n")
        writer.write(f"# pidp11-authshim {VERSION}\n".encode())
        await writer.drain()

        try:
            simh_r, simh_w = await asyncio.open_connection("127.0.0.1", SIMH_PORT)
        except ConnectionRefusedError:
            writer.write(b"# SimH remote console not available yet -- is SimH running?\n")
            await writer.drain()
            return

        await asyncio.gather(_pipe(reader, simh_w), _pipe(simh_r, writer))

    except Exception as exc:
        print(f"[authshim] error from {peer}: {exc}", file=sys.stderr, flush=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _main() -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", LISTEN_PORT)
    print(
        f"[authshim] listening on :{LISTEN_PORT} → SimH :{SIMH_PORT}",
        flush=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
