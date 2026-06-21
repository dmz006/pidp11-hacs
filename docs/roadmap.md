# Roadmap

v1 scope is "PiDP-11 on HAOS works exactly like on Pi OS, plus basic
HA observability." Everything else is here. Items are R-numbered so we
can reference them in commits and issues.

---

## ~~v1 (targets: sprints S0–S4)~~ ✅ shipped as v1.1.0

- ~~**R0** Container add-on boots, SSH lands in `screen`, lamps+switches
  work on Pi 5 hardware.~~
  > Shipped. Docker image at `ghcr.io/dmz006/pidp11-addon:latest`. GPIO via RP1
  > on Pi 5. aarch64 scansw fix submitted upstream (PR #19).

- ~~**R1** HACS integration exposes `sensor.pidp11_state`,
  `sensor.pidp11_pc`, `switch.pidp11_power`, services `pidp11.boot`
  / `pidp11.halt`.~~
  > Shipped. Coordinator, config flow, sensor/switch entities, HALT/CONT/BOOT/DEPOSIT/EXAMINE services.

- ~~**R2** Multi-arch build, auto-updates via HACS + add-on store.~~
  > Shipped. CI builds linux/arm64, pushes to GHCR on every main push (latest) and
  > version tags (semver). HACS manifest and hacs.json in place.

---

## ~~v1.1 — Lovelace front panel dashboard (sprint S5)~~ ✅ shipped as v1.1.0

~~A Lovelace custom card that looks like the PiDP-11 face: address LEDs,
data LEDs, run/halt lamp, boot-select rotary, the full switch row. Live
sync with the emulator — the on-screen panel and the physical panel
mirror each other. Ships as `lovelace/pidp11-panel-card.js` and is
referenced from the integration's HACS Lovelace category. Priority
per user ask. See `docs/sprints/S5-lamps-switches-dashboard.md`.~~

> Shipped (register snapshot, not live lamps). `lovelace/pidp11-panel-card.js` —
> amber ADDRESS/DATA LEDs, RUN lamp, polls coordinator at 5 s. Auto-registers on
> integration install. Live 60 Hz animation deferred to v1.2 (needs blinkenlightd
> push channel).

---

## ~~v1.2 — Switch events in HA~~ ✅ shipped (minus 60 Hz lamps)

~~Every physical switch throw fires an HA event
(`pidp11_switch { name, state, timestamp }`). Each switch also has a
`binary_sensor.pidp11_sw_<name>` so users can build automations like
"when SR register = 0o177777, blink the office lamp." Depends on a
push-notification channel from the pidp11 GPIO driver to the remote
console — needs an upstream PR or a sidecar reader of the driver's
shared memory. Spike in S5.

Also includes live Lovelace lamp animation (60 Hz via blinkenlightd push channel)
deferred from v1.1.~~

> **Shipped (partial):** 22 SR bit binary sensors (`binary_sensor.pidp11_sr0`–`sr21`),
> `pidp11_switch_changed` HA event per bit, `pidp11_sr_changed` HA event. Implemented
> via a 250 ms `EXAMINE SR` push channel on port 2225 (authshim watch stream) rather
> than the blinkenlightd driver — no upstream changes needed.
>
> **Not done:** 60 Hz Lovelace lamp animation. Still requires a blinkenlightd push
> channel (RTCLASS protocol or new socket). Tracked as v1.5.

## ~~v1.3 — Richer register sensors~~ ✅ shipped (partial)

~~- `sensor.pidp11_sr` (switch register, 0-7777 octal), attributes for
  binary representation.~~
~~- `sensor.pidp11_mmu_state` (kernel/super/user mode).~~
- `sensor.pidp11_active_device` (which peripheral is I/O-busy). ⏳ not yet done.

> **Shipped:** `sensor.pidp11_sr` (octal + binary/decimal attributes + SR0–SR21 bool
> attributes), `sensor.pidp11_cpu_mode` (kernel/supervisor/user from PSW bits 15–14),
> `binary_sensor.pidp11_halted`.

## ~~R6 — Remote-Pi topology~~ ✅ shipped

~~Run HA on an Intel NUC (or any host) and the PiDP-11 on a separate Pi 5.
Integration targets the remote Pi over the network; no local add-on required.~~

> **Shipped:** `zeroconf_advertise.py` in the add-on advertises `_pidp11._tcp.local.`
> on the LAN IP. `config_flow.py` adds `async_step_zeroconf` + `async_step_zeroconf_confirm`
> so HA auto-discovers the Pi and asks only for the shared secret. Manual IP/port entry
> still works as a fallback. See README Topology B.

## v1.4 — Tape / paper-tape / disk library service

- `pidp11.load_tape` service: URL or `/share/pidp11/media/…` path,
  downloads if remote, `attach pt0 …` via remote console.
- `pidp11.save_state` / `pidp11.restore_state` using SimH's
  `save`/`restore` commands.
- Automation trigger: "every night at 03:00 save state to dated file."

## v2 — Multi-simulator family

Add sibling add-ons for PDP-8, PDP-10, IMLAC, Altair. Share a common
`pidp-common` Python package under `custom_components/`. One HACS
repo with the shared integration + each add-on's container. Not a v1
concern — tracked only to avoid painting into a corner now.

## v3 — HA-driven "what would happen if" probes

Read-only simulation harness: the integration sends a `save`, forks a
second SimH process in another container, runs a scenario, discards.
Useful for "will my boot script succeed" kind of automations. Needs
resource guardrails.

## v1.4 — 60 Hz live Lovelace lamp animation

Real-time ADDRESS/DATA LED animation in the Lovelace card (deferred from v1.1 → v1.2 → now v1.4).
Requires reading lamp state from `pidp1170_blinkenlightd` at the driver's update rate. Options:

- **RTCLASS reader**: blinkenlightd speaks the RTCLASS wire protocol and exposes lamp
  state. Connect to it directly from authshim and stream `EVENT lamps ...` to the coordinator.
- **Shared memory poll**: blinkenlightd writes lamp state to shared memory; poll it in authshim.
- **Upstream PR**: new push socket in pidp11 driver (was spike item in S5 plan).

**Next steps:** spike which blinkenlightd interface is accessible from authshim without
modifying the binary, then stream lamp register values through the existing EVENT channel
or a new port 2226.

## v1.5 — Tape / paper-tape / disk library service

## Priority order

1. ~~v1.1 Lovelace panel dashboard~~ ✅ done
2. ~~v1.2 Switch events + SR sensors~~ ✅ done (250 ms watch stream; 60 Hz lamps → v1.5)
3. ~~v1.3 SR/cpu_mode sensors~~ ✅ done (active_device pending)
4. ~~R6 Remote-Pi mDNS topology~~ ✅ done
5. v1.4 60 Hz lamp animation. ← **next up**
6. v1.5 Tape/state services.
7. v2+ later.
