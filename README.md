# PiDP-11 for Home Assistant

> *Lights that blink. Switches that matter. A 1975 computer that now lives in your smart home.*

Run the iconic [PiDP-11](https://obsolescence.wixsite.com/obsolescence/pidp-11) — Oscar Vermeulen's
beautiful reproduction of the PDP-11/70 front panel — on a Raspberry Pi 5 alongside
Home Assistant OS, and wire it up to your HA dashboard with live register displays,
CPU state sensors, and front-panel services.

Powered under the hood by [SimH](http://simh.trailing-edge.com/) via the
[obsolescence/pidp11](https://github.com/obsolescence/pidp11) distribution, with the
GPIO lamp driver running inside an HAOS Supervisor add-on container.

---

## Dashboard Card

Add the **PiDP-11 Front Panel** card to any Lovelace dashboard for a faithful
software replica of the physical PDP-11/70 front panel — real-time ADDRESS and DATA
LED rows, status indicators, SR toggle switches, rotary selector indicators, and
control buttons, all in the original dark panel color scheme.

![PiDP-11 Lovelace card showing faithful PDP-11/70 front panel replica](./docs/images/lovelace-card.svg)

The card auto-registers when you install the integration — no manual Lovelace resource
step needed. Just add it:

```yaml
type: custom:pidp11-panel-card
```

Or click **Add Card → PiDP-11 Front Panel** in the Lovelace card picker.

### What the lights mean

| Panel element | Source | What it shows |
|---------------|--------|---------------|
| **STATUS row** (12 LEDs) | CPU state / PSW | PAR ERR, ADRS ERR, RUN (on = running), PAUSE, MASTER; USER/SUPER/KERNEL (lit by CPU mode from PSW bits 15–14); ADDRESSING 16/18/22 (22 lit for PDP-11/70). |
| **ADDRESS** (22 LEDs) | `EXAMINE PC` — 20 Hz live | Program counter as 22 binary LEDs in groups `[1,3,3,3,3,3,3,3]` (bits 21–0, MSB left). Updates at up to 20 Hz via the lamp push stream on port 2226. |
| **DATA** (16 LEDs) | `EXAMINE PSW` — 20 Hz live | Processor status word as 16 binary LEDs in 4 groups of 4. Interrupt level in bits 7–5, condition codes in bits 3–0. Same 20 Hz stream as ADDRESS. |
| **PARITY H/L** | *(no source)* | Always dark — SimH does not expose parity. |
| **SR switches** (22) | `binary_sensor.pidp11_sr0`–`sr21` | Physical SR switch positions, updated via 250 ms push stream (port 2225). Toggle-knob style; knob at top = ON. |
| **ADDR SELECT** | *(hardcoded)* | Shows PROG PHY active — always, because we EXAMINE PC. |
| **DATA SELECT** | *(hardcoded)* | Shows DISPLAY REGISTER active — always, because we EXAMINE PSW. |

ADDRESS and DATA LEDs animate at **up to 20 Hz** via the dedicated lamp stream (port 2226,
`_handle_lamp_stream` in the add-on). On each `pidp11_lamps` HA event the card calls
`requestAnimationFrame` and patches only the LED class list — no full re-render.
The 5 s coordinator tick still updates status indicators, CPU mode, system name, and SR
switch positions.

### Optional entity overrides

The card defaults to the entity IDs the integration creates automatically. Override any
of them if you've renamed your device:

```yaml
type: custom:pidp11-panel-card
state_entity:    sensor.pidp11_cpu_state
pc_entity:       sensor.pidp11_pc
psw_entity:      sensor.pidp11_psw
system_entity:   sensor.pidp11_system
sr_prefix:       binary_sensor.pidp11_sr    # appended with 0..21
cpu_mode_entity: sensor.pidp11_cpu_mode
```

---

## What ships from this repo

Two artifacts in one repo, because HA distributes Python and containers through
different channels:

| Artifact | Channel | What it does |
|----------|---------|--------------|
| **`pidp11-addon/`** | Supervisor add-on or standalone Docker | Container running SimH + GPIO lamp/switch driver (`pidp1170_blinkenlightd`) + auth shim (port 2223) + SR watch stream (port 2225) + mDNS advertisement + SSH console. |
| **`custom_components/pidp11/`** | HACS Integration | Python integration exposing HA entities, services, and the Lovelace card. Connects to the add-on over TCP (local `127.0.0.1:2223` or remote Pi IP via mDNS auto-discovery). |

The add-on includes a boot-select encoder: at startup it reads the front-panel SR
switches via `scansw` and boots the OS whose octal code matches the switch pattern
(e.g., SW0 up → `0001` → RSX-11M+). All-switches-down falls back to the `default_boot`
add-on option.

---

## Running without Home Assistant

Just want the blinking lights without HA? The same Docker image runs as a
standalone PDP-11 on any Raspberry Pi 5 with Docker installed — pull, run,
SSH in, enjoy.

```bash
docker run -d --name pidp11 --restart unless-stopped \
  --privileged --network host \
  -v /run/rpcbind.sock:/run/rpcbind.sock \
  -v /opt/pidp11-share:/share \
  -v pidp11-data:/data \
  -e ENABLE_GPIO=true \
  -e SSH_PASSWORD=pdp11 \
  -e SSH_PORT=2211 \
  ghcr.io/dmz006/pidp11-addon:latest
```

Full instructions, prerequisites, disk image staging, and OS boot table:
**[docs/standalone-docker.md](./docs/standalone-docker.md)**

Front panel controls, OS switch table, and shutdown procedures:
**[docs/front-panel.md](./docs/front-panel.md)**

---

## Supported topologies

### Topology A — Pi runs both the emulator and HAOS (add-on mode)

The Pi 5 runs **HAOS** directly (or HA Supervised). The PiDP-11 add-on installs inside
the Supervisor. The HACS integration talks to it on `127.0.0.1:2223`. This is the
simplest setup — everything on one board.

### Topology B — Pi runs the emulator; HAOS is on a separate machine

The Pi 5 runs **Docker standalone** with the PiDP-11 image. Your Home Assistant instance
is a VM, NUC, or another host on the same LAN. The HACS integration is installed on
that remote HA and connects to the Pi's IP on port 2223. mDNS/zeroconf auto-discovery
advertises the Pi on your LAN so HA finds it automatically.

Both topologies are fully supported. HAOS and HA Supervised both work in topology A.
HA Container and HA Core do not support add-ons and are only usable in topology B.

Hardware: **Raspberry Pi 5** with the PiDP-11 hat. The Pi 5 uses the RP1 I/O chip;
the GPIO driver has been tested and confirmed working (`/dev/gpiomem0`–`/dev/gpiomem4`).

---

## Quick install

### Topology A — Pi + HAOS (add-on mode)

1. Settings → Add-ons → Add-on Store → ⋮ → **Repositories** → paste `https://github.com/dmz006/pidp11-hacs`. Install **PiDP-11 Emulator**.
2. Add-on **Configuration** → set an `ssh_password` → **Start**.
3. Watch the add-on log: within ~30 s you should see `[pidp11] Starting SimH` and the
   physical lamps should begin blinking.
4. HACS → ⋮ → **Custom repositories** → add `https://github.com/dmz006/pidp11-hacs`, category *Integration*. Install **PiDP-11**.
5. Settings → Devices & Services → **Add Integration** → *PiDP-11*.
   - Host: `127.0.0.1` (add-on is reachable at localhost)
   - Port: `2223`
   - Shared secret: auto-detected from `/share/pidp11/remote_console.secret`
6. Open any Lovelace dashboard → **Edit** → **Add Card** → search *PiDP-11 Front Panel*.

### Topology B — Pi running Docker; HAOS on a separate host

1. On the Pi: follow **[docs/standalone-docker.md](./docs/standalone-docker.md)** to start
   the container. The add-on image advertises itself via mDNS and listens on port 2223.
2. On your HAOS VM / NUC:
   - HACS → ⋮ → **Custom repositories** → add `https://github.com/dmz006/pidp11-hacs`, category *Integration*. Install **PiDP-11**.
   - Restart HA.
3. HA should show **"New device found: PiDP-11"** within ~30 s (mDNS auto-discovery).
   Click **Configure**, enter the shared secret and you're done.

   **If the mDNS notification doesn't appear** (different subnets, or multicast blocked):
   Settings → Devices & Services → **Add Integration** → *PiDP-11* → enter the Pi's IP,
   port `2223`, and the shared secret manually.

   **To retrieve the secret from the Pi:**
   ```sh
   ssh pdp11@<pi-ip> -p 2211 'cat /data/remote_console.secret'
   # or read it from the container log on first boot
   ```

### SSH to the PDP-11 console

```sh
ssh pdp11@<ha-host> -p 2211
# password = whatever you set in step 2
```

You land in a `screen` session attached to SimH's interactive console. The PDP-11
is right there. Type `HALT`, then `EXAMINE PC`, then `CONTINUE` — watch the LEDs react.

---

## Entities & Services

### Sensors

| Entity | What it shows |
|--------|---------------|
| `sensor.pidp11_cpu_state` | `running` / `halted` / `offline` |
| `sensor.pidp11_pc` | Program counter (octal) |
| `sensor.pidp11_psw` | Processor status word (octal) |
| `sensor.pidp11_system` | Booted OS: `idled`, `211bsd`, `rsx11mp`, … |
| `sensor.pidp11_cpu_mode` | `kernel` / `supervisor` / `user` (from PSW bits 15–14) |
| `sensor.pidp11_sr` | Switch register (octal) with per-bit attributes `SR0`–`SR21` |

### Binary sensors

| Entity | What it shows |
|--------|---------------|
| `binary_sensor.pidp11_halted` | `on` when CPU is halted |
| `binary_sensor.pidp11_sr0` – `binary_sensor.pidp11_sr21` | Individual front-panel switch positions (22 sensors, updated via 250 ms push stream) |

### Services

| Service | Parameters | What it does |
|---------|------------|--------------|
| `pidp11.halt` | — | Halts the CPU (front-panel HALT) |
| `pidp11.continue_cpu` | — | Resumes from HALT |
| `pidp11.examine` | `address` | Returns the value at a SimH address/register |
| `pidp11.deposit` | `address`, `value` | Deposits a value (octal) at address |
| `pidp11.boot` | `target` | Boots a system by name |

### Events

| Event | Payload | When fired |
|-------|---------|------------|
| `pidp11_sr_changed` | `{ sr_old, sr_new }` | SR register changes (from watch stream or 5 s poll) |
| `pidp11_switch_changed` | `{ switch: "SR<N>", state: bool }` | Individual SR bit edge (from watch stream) |
| `pidp11_lamps` | `{ ADDRESS: "xxxxxx", DATA: "xxxxxx" }` | PC and PSW snapshot (octal), fired up to 20 Hz by the lamp stream; consumed by the Lovelace card for live LED animation |

Example automation — announce when the PDP-11 halts:
```yaml
trigger:
  - platform: state
    entity_id: sensor.pidp11_cpu_state
    to: halted
action:
  - service: notify.mobile_app
    data:
      message: "The PDP-11 just halted at PC {{ states('sensor.pidp11_pc') }} (octal)"
```

---

## Bootable systems

The add-on ships these systems in the image (no disk required):

| SR octal | OS | Notes |
|----------|----|-------|
| `0000` | *(default_boot option)* | All switches down → follow add-on config |
| `0001` | `idled` | Idle loop with lamp animation — the screensaver |
| `1002` | `blinky` | Pure LED demo, no OS |

These systems need disk images staged at `/share/pidp11/disks/<name>/`:

| SR octal | OS | Disk |
|----------|----|------|
| `0001` | `rsx11mp` | `PiDP11_DU0.dsk` |
| `0002` | `rsts7` | (pre-stage) |
| `0101` | `unix1` | `disk0.hp` |
| `0102` | `211bsd` | downloaded automatically on first boot (~250 MB) |

Full switch-to-OS mapping is in `pidp11-addon/systems/selections`.

---

## Card developer notes

> For contributors and future sprints — here is how the card is built and where to go next.

### Architecture

```
custom_components/pidp11/www/pidp11-panel-card.js  ← the card (vanilla JS)
custom_components/pidp11/__init__.py               ← serves the file + calls add_extra_js_url()
```

The card is **zero-dependency vanilla JS** (no npm, no webpack, no Lit import).
It extends `HTMLElement` directly, attaches a shadow root, and rebuilds `innerHTML`
on every `hass` set (every 5 s coordinator tick). At this update rate that is
completely fine — no diffing needed.

The integration's `async_setup_entry` calls `hass.http.register_static_path()` to
serve the file at `/pidp11-hacs/pidp11-panel-card.js`, then calls
`add_extra_js_url()` so HA loads it in every frontend session. The `customElements.define`
call in the JS makes `type: custom:pidp11-panel-card` work in Lovelace.

### What the card draws (v1.4)

The card is a **faithful software replica of the physical PDP-11/70 front panel**:

- **Status row** — 12 indicator LEDs (PAR ERR, ADRS ERR, RUN, PAUSE, MASTER; USER/SUPER/KERNEL by CPU mode; ADDRESSING 16/18/22)
- **ADDRESS row** — 22 orange-red LEDs in groups `[1,3,3,3,3,3,3,3]`, dark brick-red segment bar above
- **DATA row** — 16 orange-red LEDs in 4 groups of 4, PARITY H/L dots (always off), dark purple segment bar above
- **SR switches** — 22 toggle-style switches in alternating light/dark crimson groups, with bit numbers above (21→0)
- **ADDR SELECT / DATA SELECT** — rotary indicator dot rows (8 + 4 positions) hardcoded to PROG PHY and DISPLAY REGISTER
- **Footer** — booted OS name + LOAD ADRS / EXAM / DEP / CONT / ENABLE / S INST / START control buttons

**Live animation** is driven by `pidp11_lamps` HA events (up to 20 Hz from port 2226).
The fast path (`_updateLeds`) only patches `.adr` and `.dat` LED class lists via
`querySelectorAll` + `requestAnimationFrame` — no full DOM rebuild. The 5 s coordinator
tick handles everything else (status LEDs, CPU mode, system name, SR switches).

### Adding the card to HACS as a Lovelace plugin

When the card matures enough to list separately, register the repo in HACS as a
**Plugin** category (in addition to the Integration category registration). Update
`hacs.json` to add `"plugin": true` or create a separate plugin entry. The card file
is already at the root-accessible path the HACS plugin installer expects.

---

## Upstream projects

This project stands on the shoulders of giants:

- **[PiDP-11](https://obsolescence.wixsite.com/obsolescence/pidp-11)** by
  [Oscar Vermeulen](https://github.com/oscarverein) — the hardware kit, PCB, GPIO driver,
  and curated OS disk images that make the whole thing possible. If you don't have one,
  you should get one. It's gorgeous.
- **[obsolescence/pidp11](https://github.com/obsolescence/pidp11)** — the software
  distribution: SimH with realcons patches, `pidp1170_blinkenlightd`, `scansw`, boot
  scripts, and disk images for a dozen vintage OSes.
- **[SimH](http://simh.trailing-edge.com/)** — the multi-system simulator that actually
  emulates the PDP-11/70 CPU, memory, and peripherals. Without SimH there is no PDP-11.
- **[SIMH on GitHub](https://github.com/simh/simh)** — the community-maintained SimH
  fork with active development.
- **[Home Assistant](https://www.home-assistant.io/)** — the open-source home
  automation platform doing the heavy lifting on the HA side.

---

## Status

Working end-to-end on Pi 5 + HAOS + PiDP-11 hat as of June 2026:

- ✅ Lamps blink (IDLED pattern, 2.11BSD boot animation, all confirmed)
- ✅ SR switch reading works (scansw, aarch64, Pi 5 RP1 GPIO)
- ✅ Boot-select encoder works (SW0 up → `0001` → RSX-11M+)
- ✅ HA sensors: cpu_state, PC, PSW, system, cpu_mode, switch register (SR)
- ✅ Binary sensors: CPU halted, SR0–SR21 (22 per-switch sensors)
- ✅ HALT/CONTINUE services work; HALT→RUNNING transition in < 3 s
- ✅ SSH console (port 2211)
- ✅ Lovelace front panel card — faithful PDP-11/70 panel replica with all elements
- ✅ SR watch stream: 250 ms push channel for switch change events (port 2225)
- ✅ Lamp stream: 20 Hz PC/PSW push channel for live LED animation (port 2226)
- ✅ mDNS auto-discovery: remote HAOS finds the Pi on the LAN automatically
- ⏳ v1.0.0 release tag + GHCR image build

See `docs/sprints/` for the full sprint plan.

---

## License

MIT. See `LICENSE`. The upstream `obsolescence/pidp11` distribution uses MIT-style
per-file headers; see `docs/risks.md` for the license-hygiene note.
