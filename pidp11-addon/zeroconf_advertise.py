#!/usr/bin/env python3
"""Advertise the PiDP-11 auth shim on the LAN via mDNS (_pidp11._tcp.local.)."""

from __future__ import annotations

import os
import signal
import socket
import sys
import time

try:
    from zeroconf import ServiceInfo, Zeroconf
except ImportError:
    # python3-zeroconf not installed — skip silently so the add-on still starts.
    sys.exit(0)


def _primary_ip() -> str:
    """Return the outbound LAN IP without sending any packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    port = int(os.environ.get("LISTEN_PORT", "2223"))
    ip = _primary_ip()
    hostname = socket.gethostname()

    info = ServiceInfo(
        type_="_pidp11._tcp.local.",
        name=f"pidp11-{hostname}._pidp11._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=port,
        properties={"version": "1"},
        server=f"{hostname}.local.",
    )

    zc = Zeroconf(interfaces=[ip])
    zc.register_service(info)

    print(f"[zeroconf] advertising _pidp11._tcp.local. at {ip}:{port}", flush=True)

    def _shutdown(sig: int, frame: object) -> None:
        zc.unregister_service(info)
        zc.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
