# Architecture

## 1. Intent

Recreate the PiDP-11 experience — a user SSHes to the Pi and reconnects
to a persistent, always-running SimH PDP-11 console — but with the
emulator living in a Supervisor-managed Docker container on a Pi 5
running Home Assistant OS, so the same hardware can host HA and the
PiDP-11 at once. Beyond parity, expose the emulator to HA so it can be
observed and driven from automations and Lovelace.

## 2. Topology (target)

One Raspberry Pi 5, HAOS installed, PiDP-11 hat on the 40-pin header.
No external hosts. GPIO is shared between the Pi 5's RP1 I/O controller
and the SimH GPIO driver running inside the add-on container via
`/dev/mem` mmap.

## 3. Component split

### 3.1 `pidp11-addon/` — the container

Container image built from `debian:bookworm-slim`:

- **SimH PDP-11** compiled from `obsolescence/pidp11` source, pinned
  by commit SHA.
- **pidp11 GPIO driver** (pinctrl RP1 + BCM2712 path) linked into SimH.
- **GNU screen** hosts the SimH console under session name `pidp11`.
- **dropbear** listens on container `:22`, mapped to host `:2211` by
  default; on login the user's shell is a tiny wrapper that runs
  `screen -RR pidp11` so every SSH session attaches to the single
  persistent console. `^A d` detaches, SSH exit leaves the emulator
  running.
- **SimH remote console** listens on container `:2223` (host `:2223`),
  used by the HA integration for out-of-band control that does not
  interfere with the user's primary console.
- **Disk images**: symlinked from `/share/pidp11/disks/` (bind-mount
  from HAOS share), bundled defaults provisioned on first start if
  missing.
- **Boot selector**: a tiny service reads `options.default_boot`, the
  physical front-panel boot-select encoder position, or an HA service
  call — whichever was last to change — and writes a SimH `boot`
  directive.

Runs with `privileged: [SYS_RAWIO]`, `devices: [/dev/mem]`. No
`host_network` (we want explicit port mappings).

### 3.2 `custom_components/pidp11/` — the HACS integration

Pure Python, no C. Talks to the add-on over its remote-console TCP
port (default 2223). Provides:

- `config_flow.py` — UI setup (host, remote-console port, shared
  secret). Stores an entry in HA's config registry.
- `coordinator.py` — a `DataUpdateCoordinator` that polls the remote
  console every N seconds for CPU state, and consumes async events
  (HALT, TRAP) over a persistent connection.
- `sensor.py` — `sensor.pidp11_state` (running/halted/idle),
  `sensor.pidp11_pc` (program counter), `sensor.pidp11_last_error`.
- `switch.py` — `switch.pidp11_power` (start/halt), and for the
  post-v1 roadmap, one switch per front-panel toggle.
- `services.yaml` — `pidp11.boot`, `pidp11.halt`, `pidp11.deposit`,
  `pidp11.examine`, `pidp11.load_tape`.
- Events — fires `pidp11_halt`, `pidp11_trap` on the HA event bus for
  automations.

### 3.3 Control plane contract

The integration ↔ add-on contract is documented in
`docs/contracts/remote-console.md` (written in S3). It is a
line-oriented TCP protocol: the integration sends SimH control
commands (`show cpu`, `deposit PC 1000`, `boot`, `halt`), receives
text responses, and parses them with a small regex table. This is
deliberately simple — no JSON-RPC, no custom daemon — because it
matches SimH's native interface and lets power users reach the same
port with `telnet`.

## 4. Data flow

See `docs/diagrams.md` for rendered diagrams.

- **User console path**: user → TCP :2211 → dropbear → wrapper shell
  → `screen -RR pidp11` → SimH primary console. Detach/reattach-safe.
- **HA control path**: automation → HA service `pidp11.boot` →
  integration → TCP :2223 → SimH remote console → response → HA
  entity state update.
- **GPIO path**: SimH process inside container → `/dev/mem` mmap →
  RP1 IO_BANK / PADS_BANK registers → ribbon cable → PiDP-11 lamps &
  switches.
- **Persistence path**: SimH writes disk images under
  `/share/pidp11/disks/*.dsk` on the HAOS share, visible to the user
  over Samba.

## 5. Security posture

- No default password. The add-on refuses to start if
  `options.ssh_password` is unset. The UI documents how to reset it.
- SSH is `dropbear` with password auth only by default; users can
  paste an `authorized_keys` blob into options to upgrade to key auth.
- The remote-console TCP port requires a shared-secret line ("AUTH
  <secret>\n") before accepting commands; secret is generated at add-on
  install, stored in `/data/remote_console.secret`, and surfaced to the
  integration via the Supervisor API.
- `/dev/mem` is the largest blast radius. Documented in `docs/risks.md`
  with a mitigation plan (seccomp profile, SYS_RAWIO not SYS_ADMIN).

## 6. What is deliberately out of scope for v1

- Multi-emulator (PDP-8, PDP-10) — handled as sibling add-ons, later.
- Remote Pi topology (HA on one box, PiDP-11 on another) — requires a
  network GPIO bridge; noted in `docs/roadmap.md` as R6.
- VT11/Tektronix vector display emulation (upstream issue #14).

## 7. Build & release model

See `docs/testing-strategy.md` for CI details. Releases are cut on a
merge to `main` after a green CI run + a completed hardware checklist
signed in the release commit body. Multi-arch images go to
`ghcr.io/<owner>/pidp11-addon-aarch64` (Pi 5 is aarch64-only; armv7 is
not a target since users explicitly want Pi 5).
