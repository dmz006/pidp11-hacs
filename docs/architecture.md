# Architecture

## 1. Intent

Recreate the PiDP-11 experience — a user SSHes to the Pi and reconnects
to a persistent, always-running SimH PDP-11 console — but with the
emulator living in a Supervisor-managed Docker container on a Pi 5
running Home Assistant OS, so the same hardware can host HA and the
PiDP-11 at once. Beyond parity, expose the emulator to HA so it can be
observed and driven from automations and Lovelace.

## 2. Topology

Two supported topologies:

**Topology A (single-Pi):** One Raspberry Pi 5 runs HAOS with the PiDP-11 hat on
the 40-pin header. The add-on container and the HA integration both run on the Pi.
GPIO is shared between the Pi 5's RP1 I/O controller and the SimH GPIO driver
inside the add-on via `/dev/mem` mmap. Integration connects to `127.0.0.1:2223`.

**Topology B (remote):** Pi 5 runs the Docker image as a standalone container
(no HAOS required). Home Assistant runs on a separate host on the same LAN. The
add-on advertises itself via mDNS (`_pidp11._tcp.local.`) and the HACS integration
auto-discovers it. Integration connects to the Pi's LAN IP on port 2223.

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
- **authshim** (`authshim.py`) sits between HA and SimH: listens on `:2223`
  (host-mapped), gates with `AUTH <secret>` handshake, then proxies to SimH's
  native remote console on `:2224` (internal only).
- **Watch stream** listens on `:2225` (host `:2225`). Same auth handshake, then
  polls SimH `EXAMINE SR` every 250 ms and streams `EVENT sr value=<octal>` when
  the SR register changes. Allows the integration to detect switch changes without
  waiting for the 5 s coordinator poll.
- **zeroconf advertisement** (`zeroconf_advertise.py`) runs as a background process,
  advertising `_pidp11._tcp.local.` on the LAN IP so HA can auto-discover the Pi.
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

- `config_flow.py` — user-initiated setup (host, port, shared secret) plus
  `async_step_zeroconf` / `async_step_zeroconf_confirm` for mDNS auto-discovery.
- `coordinator.py` — `DataUpdateCoordinator` polling every 5 s for
  `PiDP11State(cpu_state, pc, psw, sr, cpu_mode, system)`. Also maintains a
  background watch-stream task (`_run_sr_watch`) on port 2225 for 250 ms SR updates.
- `sensor.py` — `cpu_state`, `pc`, `psw`, `system`, `sr` (+ binary/decimal/bit
  attributes), `cpu_mode` (kernel/supervisor/user).
- `binary_sensor.py` — `halted`, plus 22 SR bit sensors `SR0`–`SR21`.
- `switch.py` — `cpu_running` (HALT/CONT).
- Services: `pidp11.boot`, `pidp11.halt`, `pidp11.continue_cpu`, `pidp11.deposit`,
  `pidp11.examine`.
- Events: `pidp11_sr_changed` (sr_old, sr_new), `pidp11_switch_changed` (switch,
  state) per SR bit edge.

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
  integration → TCP :2223 (auth shim) → SimH remote console → response → HA
  entity state update.
- **Watch stream path**: coordinator background task → TCP :2225 (watch stream)
  → auth shim polls `EXAMINE SR` every 250 ms → `EVENT sr value=<octal>` → coordinator
  fires `pidp11_sr_changed` + per-bit `pidp11_switch_changed` events + updates
  `binary_sensor.pidp11_sr0`–`sr21` immediately via `async_set_updated_data`.
- **GPIO path**: SimH process inside container → ONC RPC → blinkenlightd →
  `/dev/mem` mmap → RP1 IO_BANK / PADS_BANK registers → ribbon cable → PiDP-11 lamps &
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
- VT11/Tektronix vector display emulation (upstream issue #14).
- 60 Hz live Lovelace lamp animation — requires a blinkenlightd push channel
  (RTCLASS protocol read or upstream socket). Tracked as v1.4 in roadmap.

## 7. Supported targets

**Topology A (HAOS / HA Supervised):** Both ship the Supervisor and can install the
add-on container. Tested end-to-end on Pi 5 + HAOS.

**Topology B (remote):** The Docker image runs standalone on any Pi 5 with Docker.
HA on a separate LAN host installs the HACS integration and connects via IP:2223 or
via mDNS auto-discovery. HA Container and HA Core are supported in this topology
(they can install HACS integrations, just not Supervisor add-ons).

## 8. Build & release model

See `docs/testing-strategy.md` for CI details. Releases are cut on a
merge to `main` after a green CI run + a completed hardware checklist
signed in the release commit body. Images go to
`ghcr.io/<owner>/pidp11-addon-aarch64` (Pi 5 is aarch64-only).
