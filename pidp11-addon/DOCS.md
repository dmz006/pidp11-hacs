# PiDP-11 Emulator add-on

**Status: skeleton. Does not run yet.** See `docs/sprints/` in the repo.

## What this does (once shipped)

Runs the SimH PDP-11 emulator from
[obsolescence/pidp11](https://github.com/obsolescence/pidp11) inside a
Supervisor-managed container, drives the PiDP-11 front panel hat over
GPIO on a Raspberry Pi 5, and gives you:

- **Port 2211** — SSH to the PDP-11 console. You land in a persistent
  `screen` session; `^A d` detaches, the emulator keeps running on the
  hat.
- **Port 2223** — SimH remote console, used by the companion HACS
  integration to surface the emulator in Home Assistant.

## Required options

- `ssh_password` — password for the SSH console user. **The add-on
  refuses to start if this is empty.** Change it whenever you want;
  restart the add-on to apply.

## Optional options

- `ssh_authorized_keys` — pasted multiline `authorized_keys` content.
  When set, SSH accepts keys in addition to the password.
- `ssh_password_disabled` — if `true` *and* `ssh_authorized_keys` is
  set, disables password auth.
- `default_boot` — which OS to boot by default. One of `211bsd`,
  `rt11`, `unixv6`, `unixv7`, `rsx11m`. The front-panel boot-select
  encoder overrides this at runtime.
- `enable_gpio` — set `false` to run emulator-only (useful when
  developing without the hat).
- `remote_console_port` — change the TCP port that the HACS
  integration connects to. Default `2223`.

## Connection limits and tuning

SimH accepts only 4 remote-console connections (`set remote connections=4` in
every `boot.ini`); a fifth gets "All connections busy". Every client of the
auth shim holds one of them, so the shim releases a SimH connection as soon as
its client disappears. The HACS integration uses at most 2 (one long-lived
stream for lamps and switches, one for a poll or command), leaving the rest for
people on a console session. How they are shared, and when they are closed:

- **Limit: 4.** SimH's remote console on the internal port `2224` takes at
  most 4 connections. Nothing but the shim connects to it.
- **One for one.** Each client of the shim (a console session on `2223`, the
  lamp stream on `2226`, the legacy watch stream on `2225`) gets exactly one
  SimH connection for as long as it stays connected.
- **Integration share: 2.** One long-lived lamp stream (`AUTH <secret> +sr`,
  lamps and switch register together) plus at most one short connection for a
  5 s poll or a service command. The poll connection is opened, used and closed
  each time, so it only shows up for a moment.
- **Closing.** The shim closes the SimH connection in a `finally` the moment
  its client goes away, whether by a clean close, a reset, or silence longer
  than `IDLE_TIMEOUT`. Streams watch for the client's end-of-file rather than
  waiting for a failed write. The integration closes its own connections the
  same way and cancels the stream when the entry is unloaded.
- **When full.** A fifth client gets `All connections busy` and is hung up on.
  The integration retries with backoff and keeps the last values; the entities
  do not go unavailable.

These environment variables of the shim can be
tuned (defaults shown; most installs never need to):

- `IDLE_TIMEOUT` (3600) — seconds of silence in both directions before a
  proxied console session is closed.
- `HEARTBEAT_INTERVAL` (15) — seconds of quiet before a stream sends a
  `# keepalive` comment line.
- `LAMP_INTERVAL_MS` (50) / `WATCH_INTERVAL_MS` (250) — lamp and SR polling.

## Disk images

Emulated disk images live in `/share/pidp11/disks/` on the HAOS share
(visible over Samba as `pidp11/disks/`). The add-on seeds sensible
defaults on first start; replace any file to use your own image.

## Equivalent shell

The exact same command-line you'd run on a bare-metal Pi:

```bash
ssh pdp11-user@<haos-host> -p 2211
# lands in: screen -x pidp11  (SimH primary console)
```

## Security

- The add-on needs `SYS_RAWIO` + `/dev/mem` to drive the hat. Without
  these, emulator still runs but no lamps/switches.
- Remote console port requires an `AUTH <secret>` handshake. Secret
  lives in `/data/remote_console.secret` on the add-on volume.
