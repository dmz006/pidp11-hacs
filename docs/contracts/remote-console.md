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

### Lamp stream (port + 3, default 2226)

Same handshake and the same long-lived, one-SimH-connection-per-client behaviour
as the watch stream. The server polls `EXAMINE PC` and `EXAMINE PSW` every 50 ms
(`LAMP_INTERVAL_MS`) and pushes, once on connect and whenever either changes:

```
EVENT lamps ADDRESS=<pc octal> DATA=<psw octal>\n
```

A client that sends `AUTH <secret> +sr\n` also receives
`EVENT sr value=<octal>\n` on this stream (checked every 250 ms, once on connect
and on change), so a single connection carries everything the integration needs.
A client that sends plain `AUTH <secret>\n` gets lamps only.

### Sampled lamps: `LAMPS2` (port + 3, default 2226)

The `EVENT lamps` stream above is built from `EXAMINE PC` and `EXAMINE PSW` and
so is only meaningful while the CPU is halted or stepping. The add-on can also
read the front-panel lamps straight from the Pi's GPIO, which works while the
CPU runs. It uses the same port and does not touch SimH.

Handshake:

```
AUTH <secret> +lamps\n
AUTH <secret> +lamps fps=<N>\n
AUTH <secret> +lamps +sr fps=10\n
```

`fps=N` is the frame rate this client asks for. It is clamped to 5..20; a value
that is not a number is ignored. With no `fps` token the rate is the add-on's
`LAMP_FPS` setting (default 10). Server responds `OK\n` as for any stream.

After `OK`, lines of this form:

```
LAMPS2 {"leds":{"ADDRESS0":100,"DATA15":0,"USER":100,...},"seq":1}\n
```

- `leds` maps a lamp name to its percentage of time lit, an integer from 0 to
  100. Names are the front-panel daemon's own (`ADDRESS0`..`ADDRESS21`,
  `DATA0`..`DATA15`, `RUN`, `PAUSE`, `PARITY_HIGH`, and so on). The lamp set is
  fixed for a given add-on build.
- `USER`, `SUPER` and `KERNEL` are derived from the MMR0 mode bits: `00` is
  KERNEL, `01` is SUPER and `11` is USER. The raw `MMR0_MODE_BIT0`..`BIT2`
  lamps are also present. The choice of bits is an assumption; see Status below.
- A line is sent when the first frame arrives, and afterwards only when a lamp
  has moved by 2 points or more since the last line sent on this connection.
- A line is also sent at least every 2 seconds (the keepalive). It repeats the
  current frame with the next `seq`. Clients ignore any line that does not start
  with `LAMPS2 ` or `EVENT `.
- `seq` starts at 1 on each connection and goes up by one for every `LAMPS2` line
  sent on that connection.
- With `+sr`, the stream also sends `EVENT sr value=<octal>` on change, as
  described for the lamp stream above.

Sharing and budget:

- All `LAMPS2` clients share one sampler. It runs only while at least one client
  is connected, at the highest rate any of them asked for, and it is released
  when the last one leaves.
- A `LAMPS2` client without `+sr` holds no SimH connection. With `+sr` it holds
  one, as the lamp stream always has.

Fallback:

- If the add-on cannot open the GPIO device read-only, the shim still answers
  `OK` and serves the `EVENT lamps` stream as before. `LAMPS2` never appears on
  that connection, so a client must accept both forms.
- A client that does not send `+lamps` gets the `EVENT lamps` stream, unchanged.

Status: the sampler reads `/dev/gpiomem0` (the RP1 GPIO window, opened read-only
and mapped `PROT_READ`). The lamp-to-pin mapping comes from the upstream source.
Checked on a Pi 5 against a photo of the panel: ADDRESS0..21, DATA0..15, RUN,
USER (raw `MMR0_MODE_BIT2`), ADDRESSING_16, PARITY_HIGH, ADDR_SEL_CPHY and
DATA_SEL_FB_LO0. Not yet checked: SUPER and KERNEL (they depend on the low bit of
the mode code, which is an assumption), the other mode bits, and the remaining
ADDR_SEL and DATA_SEL bits. Treat those as provisional.

### Integration behaviour

`PiDP11Coordinator` starts one background task (`_run_stream`) that maintains a
single stream for both lamps and SR: it connects to the lamp port
(`remote_console_port + 3`) and authenticates with `AUTH <secret> +sr`, which
adds the same `EVENT sr value=<octal>` lines to that stream. (This port, `+2`,
stays available for older clients.) On each `EVENT sr value=<octal>` line:

- `pidp11_switch_changed` HA events are fired for each SR bit that changed
  (payload: `{"switch": "SR<N>", "state": <bool>}`).
- `pidp11_sr_changed` is fired with `{"sr_old": <octal>, "sr_new": <octal>}`.
- `coordinator.data.sr` is updated immediately via `async_set_updated_data`.

If the stream is unavailable (or the add-on is older and refuses `+sr`, in which
case the lamp stream runs without SR) the coordinator falls back to the 5-second
poll cycle, which also fires `pidp11_sr_changed` when the stream is not carrying SR.

### Connection budget

Every client of the shim holds one SimH remote-console connection, and SimH only
accepts a fixed number: every `boot.ini` sets `set remote connections=4`. Past
that SimH replies `All connections busy` and hangs up. The shim therefore:

- closes its SimH connection as soon as the client side is gone (FIN, reset or
  write failure; the streams check for EOF rather than waiting for a write to
  fail, because they only write when a register changes);
- closes proxied sessions that have moved no bytes in either direction for
  `IDLE_TIMEOUT` seconds (default 3600);
- sends a `# keepalive` comment line on a stream that has been quiet for
  `HEARTBEAT_INTERVAL` seconds (default 15). Clients ignore lines that do not
  start with `EVENT`.

The integration holds at most 2 connections: the one stream plus one transient
connection (a poll or a command, never two at once). When SimH is busy a poll
retries 3 times with doubling backoff (1 s, 2 s, 4 s; `_BUSY_BACKOFF_MAX` caps a single wait at 8 s, unreached with `_BUSY_RETRIES = 3`) and then keeps the last values.

## System name (port 2223)

The integration's System sensor shows the system SimH booted. It reads
`/share/pidp11/current_system` when that file is on its own machine. When it is
not (Home Assistant on another host than the add-on), it asks the add-on on the
main port:

```
AUTH <secret> +system\n
```

The shim answers as for any `AUTH` and then sends one line and closes:

```
OK\n
# pidp11-authshim <semver>\n
SYSTEM <name>\n
```

- `<name>` is the content of the add-on's `/share/pidp11/current_system`. It is
  `unknown` when that file is missing or empty, or when the content is not
  1 to 32 characters from `A-Z a-z 0-9 . _ -`.
- The shim answers before it opens a SimH connection, so the query takes no
  console slot and does not touch SimH.
- The query is a flag on `AUTH`, not a bare `SYSTEM` line sent after it. On this
  port the shim forwards the client's bytes to SimH and clients wait for SimH's
  banner first, so a line the shim had to read before opening SimH would stall
  every poll.
- A wrong secret gets `DENY bad-auth` and no `SYSTEM` line.
- An add-on from before this query does not answer it: it proxies the
  connection to SimH and sends no `SYSTEM` line. The integration reads at most
  four lines, then closes the connection. The sensor stays unknown with no
  error, and the integration does not ask again for 5 minutes.
- The integration asks only when its local file is missing or empty. An
  `unknown` answer is asked again on every poll.

## Re-connection

If the TCP connection drops, the integration's coordinator reopens with
exponential backoff (10 s, 20 s, 40 s, ..., capped at 120 s; reset once the
stream delivers a line). The stream has no read timeout: a quiet machine sends
nothing for long stretches, and reconnecting on silence is what used to strand a
SimH connection each time. The auth handshake runs fresh on every reconnect.

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
- The system-name query is covered by `tests/integration/test_system_query.py`
  (fake add-on, real shim handler) and the run.sh port wait by
  `tests/addon/test_port_wait.py`.
