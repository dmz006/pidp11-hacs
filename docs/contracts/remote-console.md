# Contract — SimH remote console (integration ↔ add-on)

**Status:** draft; finalized in S3. This file is the single source of
truth for the wire protocol between
`custom_components/pidp11/coordinator.py` and the add-on's
`authshim.py`.

## Transport

TCP, line-oriented, UTF-8. Default port `2223`, configurable via
add-on option `remote_console_port` and integration config entry.

## Handshake

Client opens connection, sends:

```
AUTH <secret>\n
```

Server responds with one of:

- `OK\n` — authenticated, may send SimH commands.
- `DENY <reason>\n` — auth failed; server closes the socket.

Auth must complete within 5 s or the server closes the socket.

## Commands

After `OK`, the session is a transparent byte stream to SimH's native
remote console, with these additions:

- Lines prefixed with `EVENT ` are push events from the add-on side
  (HALT, TRAP, SWITCH …). The integration parses these out of the
  stream and does not forward them to SimH-response parsers.
- Lines prefixed with `# ` are informational comments from the shim
  itself (e.g. reconnect notices).

## Command set used by the integration (v1)

| Purpose             | Sent                            | Expected response pattern    |
| ------------------- | ------------------------------- | ---------------------------- |
| Capability probe    | `show version\n`                | `SimH V<semver> ...`         |
| Poll state          | `show cpu\n`                    | multi-line with `PC:` & `RUN`|
| Boot                | `boot <target>\n`               | `Booting ...` then stream    |
| Halt                | `halt\n`                        | `HALTED` on next line        |
| Examine             | `examine <octal>\n`             | `<addr>: <value>\n`          |
| Deposit             | `deposit <octal> <octal>\n`     | echo of new value            |

## Events emitted by the shim (v1)

| Event              | Format                                            |
| ------------------ | ------------------------------------------------- |
| Emulator halted    | `EVENT halt pc=<octal> reason=<short>\n`          |
| Trap vector taken  | `EVENT trap vec=<octal> pc=<octal>\n`             |
| Physical switch    | `EVENT switch name=<name> state=<0\|1>\n`         |

## Watch stream (port remote_console_port + 2)

The auth shim exposes a second TCP port at `remote_console_port + 2` (default
`2225`) for near-real-time SR (Switch Register) streaming.

### Handshake

Same as the main port:

```
AUTH <secret>\n
```

Server responds `OK\n` (or `DENY <reason>\n` on failure).

### Stream events

After `OK`, the server opens its own dedicated connection to SimH, drains the
banner once, then polls `EXAMINE SR` every 250 ms (configurable via the
`WATCH_INTERVAL_MS` environment variable).

Whenever the SR value changes (and once immediately on connection), the server
pushes:

```
EVENT sr value=<octal>\n
```

where `<octal>` is the 22-bit SR value in octal notation.

The connection is long-lived. The client should reconnect on EOF or error.

### Integration behaviour

`PiDP11Coordinator` starts a background task (`_run_sr_watch`) that maintains
this connection. On each `EVENT sr value=<octal>` line:

- `pidp11_switch_changed` HA events are fired for each SR bit that changed
  (payload: `{"switch": "SR<N>", "state": <bool>}`).
- `pidp11_sr_changed` is fired with `{"sr_old": <octal>, "sr_new": <octal>}`.
- `coordinator.data.sr` is updated immediately via `async_set_updated_data`.

If the watch port is unavailable the coordinator falls back to the 5-second
poll cycle (which also fires `pidp11_sr_changed` when the watch task is not
running).

## Re-connection

If the TCP connection drops, the integration's coordinator reopens
with exponential backoff (1 s, 2 s, 4 s, ..., capped at 60 s). The
auth handshake runs fresh on every reconnect.

## Versioning

The first line the server sends after `OK` is:

```
# pidp11-authshim <semver>\n
```

The integration reads this and refuses to speak with an incompatible
major version.

## Test coverage

- `tests/integration/protocol/test_remote_console_transcripts.py` replays
  fixture files `tests/fixtures/remote_console_transcripts/*.txt`.
- Add-on side: `tests/addon/test_remote_console.py` exercises the live
  shim against a built image.
- Both suites share the same transcript fixtures so drift on either side
  is caught.
