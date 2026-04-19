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
