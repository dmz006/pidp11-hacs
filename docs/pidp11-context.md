# PiDP-11 HACS — Session Context

Quick-start context for new sessions. Read this before touching any code.

---

## What this is

A Home Assistant integration + Docker add-on for the [PiDP-11](https://obsolescence.wixsite.com/obsolescence/pidp-11-how-to-use) — Oscar Vermeulen's PDP-11/70 front-panel kit running on a Raspberry Pi 5.

**Two deliverables live in this repo:**

| Directory | What | Deployed to |
|---|---|---|
| `pidp11-addon/` | Docker add-on (SimH + GPIO drivers + auth shim) | Pi 5 as HAOS add-on or standalone Docker |
| `custom_components/pidp11/` | HACS custom integration | Home Assistant |

---

## Hardware facts

- **Pi 5** + PiDP-11 HAT. GPIO goes through the **RP1** chip — not the legacy GPIO, not `/dev/gpiomem`, but `/dev/gpiochip4`. This matters for scansw.
- Two **rotary encoders on the RIGHT side** of the panel: ADDR knob and DATA knob. The ADDR LED points to the selected address display mode; DATA LED points to DATA PATHS or DISPLAY REGISTER.
- **ADDR knob dual behavior**: HALT switch UP (ENABLE) + press → boot new OS from SR switches. HALT switch DOWN + press → clean Pi shutdown.
- Container needs `--privileged` (GPIO) and `--network host` (ONC RPC portmapper for NFS/disk images).

---

## Key processes inside the container

| Process | Binary | Purpose |
|---|---|---|
| `pidp1170_blinkenlightd` | `server11` | Blinkenlight server — drives ADDRESS/DATA LEDs, reads SR switches, exposes RTCLASS socket |
| `scansw` | `scansw` | Reads physical rotary encoder positions, listens to HALT/ENABLE switch, triggers boot/shutdown |
| SimH | `client11` | PDP-11/70 emulator, connects to blinkenlightd, exposes remote console on TCP 2223 |
| `authshim` | Python | Sits on TCP 2224 (mapped to 2223 externally), gates SimH remote console with shared secret |

**aarch64 fix**: `scansw` hard-coded `/dev/gpiochip0` for Pi 4. For Pi 5 it needs `/dev/gpiochip4`. A patch was submitted upstream (PR #19). Our Dockerfile applies this at build time.

---

## Network ports (container)

| Port | Service |
|---|---|
| 2211 | SSH to the container (use `SSH_PORT=2211` to avoid conflict with Pi's sshd on 22) |
| 2223 | Auth shim → SimH remote console (main integration port) |
| 2224 | Raw SimH remote console (internal only, auth shim proxies to it) |
| 2225 | Watch stream — streams `EVENT sr value=<octal>` on SR change (250 ms poll) |

---

## SimH remote console protocol

Auth shim speaks a simple text protocol:

```
AUTH <secret>\n   → OK\n  (or FAIL\n)
<simh command>\n  → <simh output> sim> 
```

Commands return text ending with `sim> `. SimH **replays its entire console history** to every new connection — always drain the banner before sending commands (`_drain_banner` in coordinator.py). The tail of the banner (`_STATE_TAIL = 300` bytes) contains "Simulator Running" if the CPU is live.

**Register reads:**

```
EXAMINE PC    → PC: 000400
EXAMINE PSW   → PSW: 000014 (octal; bits 15-14 = cpu mode)
EXAMINE SR    → SR: 000000 (22-bit switch register, octal)
```

`_parse_register()` scans all lines for `REG:\t<octal>` — do not rely on it being the last line, SimH may re-emit the banner.

**CPU mode from PSW bits 15-14:**

| Bits | Mode |
|---|---|
| 00 | kernel |
| 01 | supervisor |
| 11 | user |

---

## SR switch register — OS boot table

SR switches select which OS boots when you press the ADDR knob (HALT switch UP). Values are octal. Only images with files in `/opt/pidp11-share/systems/<name>/` are available.

| SR (oct) | System |
|---|---|
| 0000 | idled (default demo) |
| 0010 | unix7 (Unix V7) |
| 0020 | 211bsd (2.11BSD) |
| 0100 | rsts (RSTS/E) |
| 0200 | rsx11m (RSX-11M) |
| 0400 | rt11 (RT-11) |
| 1000 | unix6 (Unix V6) |
| 2000 | xxdp |
| 4000 | diag |

**rsx11bq** is staged (large .dsk and .tap) but has no SR entry yet — requires manual SimH boot.

---

## File paths (inside container / HAOS share)

| Path | Content |
|---|---|
| `/opt/pidp11-share/` | Disk images, OS configs, boot scripts |
| `/opt/pidp11-share/systems/<name>/boot.ini` | SimH boot script per OS |
| `/opt/pidp11-share/selections` | `<octal> <name>` mapping file for scansw |
| `/share/pidp11/remote_console.secret` | Auth shared secret (mounted by HAOS) |
| `/share/pidp11/current_system` | Current system name written by scansw |

---

## HA integration architecture

```
CoordinatorEntity
  └── PiDP11Coordinator (polls every 5 s)
        ├── _poll() → PiDP11State(cpu_state, pc, psw, sr, cpu_mode, system)
        └── async_send_command() → one-shot command

PiDP11State fields:
  cpu_state : "running" | "halted" | "offline"
  pc        : octal string
  psw       : octal string  
  sr        : 22-bit octal string (switch register)
  cpu_mode  : "kernel" | "supervisor" | "user" | None
  system    : "211bsd" | "idled" | ...
```

**Entities shipped (current):**

- `sensor.pidp11_cpu_state` — running/halted/offline
- `sensor.pidp11_pc` — program counter (octal)
- `sensor.pidp11_psw` — processor status word (octal)
- `sensor.pidp11_system` — loaded OS name
- `sensor.pidp11_sr` — switch register (octal); attributes: binary, decimal, SR0–SR21 (bool per bit)
- `sensor.pidp11_cpu_mode` — kernel/supervisor/user (from PSW bits 15–14)
- `binary_sensor.pidp11_halted` — True when CPU halted
- `binary_sensor.pidp11_sr0` – `binary_sensor.pidp11_sr21` — 22 individual SR switch sensors (updated via watch stream)
- `switch.pidp11_cpu_running` — HALT/CONT
- Services: `pidp11.boot`, `pidp11.halt`, `pidp11.continue_cpu`, `pidp11.deposit`, `pidp11.examine`

**HA events:**
- `pidp11_sr_changed` fires with `{ sr_old, sr_new }` on any SR value change (from watch stream or 5 s poll fallback)
- `pidp11_switch_changed` fires with `{ switch: "SR<N>", state: bool }` per bit edge

---

## HACS / CI

- HACS category: integration + plugin (for the Lovelace card)
- CI: `.github/workflows/ci.yml` — lint, mypy, pytest/coverage, schema-and-unit, addon-smoke, publish
- Publish on `v*` tags to `ghcr.io/dmz006/pidp11-addon:<tag>` and `:latest`
- mypy config: `ignore_missing_imports = true` — HA has no type stubs; this is standard for HACS integrations
- Coverage threshold: `fail_under = 15` (lowered when 22 SR bit sensors added with no new tests; raise as entity tests land)

---

## Docker run (standalone, not HAOS)

```bash
docker run -d --name pidp11 \
  --privileged \
  --network host \
  -e SSH_PORT=2211 \
  -e ENABLE_GPIO=true \
  -v /opt/pidp11-share:/opt/pidp11-share \
  ghcr.io/dmz006/pidp11-addon:latest
```

---

## Shutdown commands by OS

From the manual (p. 15):

| OS | Command |
|---|---|
| RSX-11M / RSX-11M+ | `RUN $SHUTUP` |
| 2.11BSD / Unix V7 | `sync` three times, wait for disk activity to stop |
| RT-11 | No command needed — wait 30 seconds, then power off |
| RSTS/E | `SHUTDOWN` from privileged account |

---

## Key lessons learned

**SimH banner replay**: SimH sends its entire console history on every new TCP connection. You MUST drain it before commands or you'll interpret old "Simulator Running" text as the current CPU state. `_drain_banner()` reads until quiet for `_DRAIN_QUIET = 0.5s`.

**SR register address**: `EXAMINE SR` (by name) works. Physical address is `177570` in PDP-11 I/O space.

**CPU register addresses for EXAMINE via front panel** (use LOAD ADRS then EXAM):
`R0=01777700`, `R1=01777701`, ... `R7 (PC)=01777707`

**aarch64 + Pi 5 GPIO**: Use `/dev/gpiochip4` not `/dev/gpiochip0`. Container must run `--privileged`. The Dockerfile patches scansw at build time.

**SSH conflict**: Pi 5 runs sshd on port 22. Container SSH is mapped to `SSH_PORT=2211` in standalone mode; HAOS add-on maps it via the add-on config `network:`.

**idled program** (Mike Hill): The default demo loaded when all SR switches are down. SR switches 5-0 control LED blink speed. SR7 toggles address display increment mode. DATA knob cycles through DATA PATHS / DISPLAY REGISTER display modes.

**mypy + HA stubs**: Never add `strict = true` to mypy config for this project — HA has no type stubs and strict mode produces hundreds of import-not-found errors. Use `ignore_missing_imports = true` plus the individual strict-mode flags explicitly.

**Coverage threshold**: Tests are minimal (coordinator unit tests only). Entity tests are `@pytest.mark.xfail` stubs. Keep `fail_under` at 20 or below until real entity tests land.

**ConfigFlow metaclass**: `class PiDP11ConfigFlow(ConfigFlow, domain=DOMAIN)` triggers mypy `call-arg` error — fix with `# type: ignore[call-arg]`.

**R6 / Remote Pi**: Shipped. `zeroconf_advertise.py` runs in the container and advertises `_pidp11._tcp.local.` on the LAN IP. `config_flow.py` has `async_step_zeroconf` + `async_step_zeroconf_confirm`. HA auto-discovers the Pi; user enters the shared secret (or falls back to manual IP entry).

---

## Pending work

- **v1.4 (next)**: 60 Hz live Lovelace lamp animation. Spike: read lamp register values
  from blinkenlightd via RTCLASS socket or shared memory, stream as `EVENT lamps ...`
- **v1.5**: `pidp11.load_tape`, `pidp11.save_state` / `pidp11.restore_state` services
- **active_device sensor**: `sensor.pidp11_active_device` (which peripheral is I/O-busy)
- **SR bit tests**: real (non-xfail) unit tests for the 22 SR binary sensors and watch coordinator
- **rsx11bq SR entry**: Add SR switch value for RSX-11BQ in the container's selections file
