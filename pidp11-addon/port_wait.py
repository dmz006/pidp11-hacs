"""Wait for a loopback TCP port: bindable (free) or listening.

Used by run.sh around SimH's remote console (`set remote telnet=2224`).

  port_wait.py bindable HOST PORT TIMEOUT
      Exit 0 once a plain bind to HOST:PORT succeeds. No SO_REUSEADDR, so a
      port still held by closed connections in TIME_WAIT counts as busy, the
      same way SimH's own bind sees it.

  port_wait.py listening PORT TIMEOUT
      Exit 0 once some local address has a LISTEN socket on PORT. Read from
      /proc/net/tcp{,6}, so the probe opens no connection and takes no SimH
      console slot.

Exit status: 0 success, 1 timeout, 2 bad usage.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

_POLL_INTERVAL = 0.25
_TCP_LISTEN = "0A"  # /proc/net/tcp state code for LISTEN
_PROC_TCP_FILES = ("/proc/net/tcp", "/proc/net/tcp6")


def can_bind(host: str, port: int) -> bool:
    """One plain bind attempt; the socket is closed again straight away."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def is_listening(port: int) -> bool:
    """True when /proc shows a LISTEN socket on the given local port."""
    for path in _PROC_TCP_FILES:
        try:
            with open(path, encoding="ascii") as fh:
                next(fh, None)  # header line
                for line in fh:
                    fields = line.split()
                    if len(fields) < 4 or fields[3] != _TCP_LISTEN:
                        continue
                    local_port = int(fields[1].rsplit(":", 1)[1], 16)
                    if local_port == port:
                        return True
        except OSError:
            continue
    return False


def _poll_until(check, timeout: float) -> bool:
    """Call check() at least once, then every _POLL_INTERVAL until it passes or time runs out."""
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        if check():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_POLL_INTERVAL, remaining))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="mode", required=True)

    p_bind = sub.add_parser("bindable")
    p_bind.add_argument("host")
    p_bind.add_argument("port", type=int)
    p_bind.add_argument("timeout", type=float)

    p_listen = sub.add_parser("listening")
    p_listen.add_argument("port", type=int)
    p_listen.add_argument("timeout", type=float)

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2

    if args.mode == "bindable":
        ok = _poll_until(lambda: can_bind(args.host, args.port), args.timeout)
    else:
        ok = _poll_until(lambda: is_listening(args.port), args.timeout)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
