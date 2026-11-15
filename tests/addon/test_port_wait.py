"""run.sh waits for SimH's remote-console port before starting SimH.

The helper (pidp11-addon/port_wait.py) is run as a real subprocess against
real loopback sockets: a held listener, a socket in TIME_WAIT, and a listener
that goes away part way through the wait. No Docker, no SimH, no network
beyond 127.0.0.1.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.usefixtures("socket_enabled")]

_ADDON_DIR = Path(__file__).resolve().parent.parent.parent / "pidp11-addon"
_HELPER = _ADDON_DIR / "port_wait.py"
_RUN_SH = _ADDON_DIR / "run.sh"
_HOST = "127.0.0.1"


def _run_helper(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _held_listener() -> tuple[socket.socket, int]:
    """A listening socket with no SO_REUSEADDR, so a bind to its port must fail."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((_HOST, 0))
    srv.listen(1)
    return srv, srv.getsockname()[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((_HOST, 0))
        return probe.getsockname()[1]


def _time_wait_ports() -> set[int]:
    """Local ports with a TIME_WAIT socket (state 06), read from /proc."""
    ports: set[int] = set()
    with open("/proc/net/tcp", encoding="ascii") as fh:
        next(fh)
        for line in fh:
            fields = line.split()
            if fields[3] == "06":
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
    return ports


def test_bindable_succeeds_at_once_on_a_free_port() -> None:
    port = _free_port()
    start = time.monotonic()
    result = _run_helper("bindable", _HOST, str(port), "5")
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - start < 3.0


def test_bindable_times_out_while_a_listener_holds_the_port() -> None:
    srv, port = _held_listener()
    try:
        start = time.monotonic()
        result = _run_helper("bindable", _HOST, str(port), "1")
        elapsed = time.monotonic() - start
    finally:
        srv.close()
    assert result.returncode == 1
    assert 0.8 <= elapsed < 10.0


def test_bindable_times_out_on_a_port_held_in_time_wait() -> None:
    """Closed connections from a previous run: SimH's bind fails the same way."""
    srv, port = _held_listener()
    client = socket.create_connection((_HOST, port))
    conn, _ = srv.accept()
    # Server closes first, so the server side of the connection goes to TIME_WAIT.
    conn.close()
    assert client.recv(1) == b""  # peer's FIN
    client.close()
    srv.close()
    assert port in _time_wait_ports(), "expected a TIME_WAIT socket on the port"
    result = _run_helper("bindable", _HOST, str(port), "1")
    assert result.returncode == 1


def test_bindable_waits_until_the_holder_lets_go() -> None:
    srv, port = _held_listener()
    timer = threading.Timer(0.8, srv.close)
    timer.start()
    try:
        start = time.monotonic()
        result = _run_helper("bindable", _HOST, str(port), "10")
        elapsed = time.monotonic() - start
    finally:
        timer.cancel()
        srv.close()
    assert result.returncode == 0, result.stderr
    assert 0.5 <= elapsed < 8.0


def test_listening_succeeds_when_something_listens() -> None:
    srv, port = _held_listener()
    try:
        result = _run_helper("listening", str(port), "2")
    finally:
        srv.close()
    assert result.returncode == 0, result.stderr


def test_listening_times_out_with_nothing_on_the_port() -> None:
    port = _free_port()
    start = time.monotonic()
    result = _run_helper("listening", str(port), "1")
    assert result.returncode == 1
    assert time.monotonic() - start < 8.0


def test_bad_usage_exits_2() -> None:
    result = _run_helper("nonsense")
    assert result.returncode == 2


def test_run_sh_waits_before_simh_and_checks_after() -> None:
    """Static check of the wiring in run.sh (the script itself needs the container)."""
    text = _RUN_SH.read_text(encoding="utf-8")
    wait = text.index('"${PORT_WAIT}" bindable')
    launch = text.index('screen -dmS pidp11 "${SIMH}"')
    check = text.index('"${PORT_WAIT}" listening')
    assert wait < launch < check
    assert "SIMH_PORT_WAIT_SECONDS=90" in text
    assert "SIMH_LISTEN_WAIT_SECONDS=20" in text
    assert "ERROR: SimH remote console not listening on ${SIMH_REMOTE_PORT}" in text
    assert "still not bindable" in text  # timeout path continues with a warning
