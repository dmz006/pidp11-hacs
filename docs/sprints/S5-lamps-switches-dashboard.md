# Sprint 5 — Lamps, Switches, and Lovelace Front-Panel Dashboard

**Owner:** TBD. **Status:** partial — Lovelace card + SR sensors + switch events shipped Jun 21 2026. Phase 2 (60 Hz lamps) deferred to v1.4 / S6.

## Goal

Two things the user called out:

1. A **Lovelace custom card** that visually mimics the PiDP-11 face —
   address LEDs, data LEDs, run/halt lamp, boot-select rotary, the
   full toggle-switch row — and stays live-synchronized with the
   running emulator so the on-screen panel mirrors the physical one.
2. **Switch events in HA**: every physical switch throw fires an HA
   event and updates a `binary_sensor.pidp11_sw_<name>`.

## Entry criteria

v1.0.0 shipped. Upstream pidp11 either (a) already exposes
lamp/switch state over a channel we can read without hacking the core
SimH build, or (b) we've opened and landed an upstream PR adding a
push-notification socket from the driver.

## Tasks

### Lovelace card (R1 from roadmap)

1. ✅ **Custom card.** `custom_components/pidp11/www/pidp11-panel-card.js` (vanilla
   HTMLElement; zero npm/build dependencies). Serves via `hass.http.register_static_path`
   and `add_extra_js_url` in `__init__.py` — auto-registered on integration install.
   Type: `custom:pidp11-panel-card`. Entities configurable; defaults auto-detect.
2. ✅ **Panel graphic.** Amber-on-dark retro panel. Two 16-LED rows (ADDRESS/PC,
   DATA/PSW), RUN lamp, system name, status indicators (PROC/BUS/PAR/ERR).
   Polls existing coordinator sensors at 5 s interval. Screenshot in `docs/images/`.
3. ⏳ **HACS Lovelace category** — card can also be distributed as a HACS Plugin
   by re-registering the repo under the Plugin category. Deferred until the card
   is stable enough to maintain separately.

### Lamp & switch pipeline

1. ✅ **SR watch stream (250 ms).** `authshim.py` opens a dedicated SimH connection
   on port 2225, polls `EXAMINE SR` every 250 ms, and streams `EVENT sr value=<octal>`
   when the value changes. No blinkenlightd changes required.
2. ✅ **SR binary sensors.** 22 entities `binary_sensor.pidp11_sr0`–`sr21`, updated
   immediately via `async_set_updated_data` on each watch stream event.
3. ✅ **SR sensor.** `sensor.pidp11_sr` with binary, decimal, and per-bit attributes.
4. ✅ **Switch events.** `pidp11_switch_changed` (per SR bit edge) and `pidp11_sr_changed`
   (overall SR value change).
5. ⏳ **60 Hz lamp animation.** Requires reading lamp register values from blinkenlightd
   at ~60 Hz. Deferred to v1.4 / S6. Options: RTCLASS socket, shared memory read, or
   upstream PR adding a push socket to the driver.

## Tests

- [ ] `tests/integration/test_registers_sensor.py::test_state_is_json`
- [ ] `tests/integration/test_registers_sensor.py::test_attributes_broken_out`
- [ ] `tests/integration/test_binary_sensors.py::test_every_switch_has_sensor`
- [ ] `tests/integration/test_binary_sensors.py::test_edges_fire_events`
- [ ] `tests/lovelace/test_card_manifest.py::test_registered_in_hacs`
- [ ] `tests/lovelace/test_card_render.py::test_led_mapping`
      (jsdom + lit snapshot)
- [ ] Hardware checklist:
  - [ ] Flip every physical switch, verify matching `binary_sensor`
        within 200 ms.
  - [ ] Compare Lovelace card to physical panel while running
        2.11BSD `ls`. Side-by-side photo attached to release.

## Exit gate

- Dashboard card installable via HACS Lovelace category.
- Side-by-side video of physical panel + Lovelace card during BSD
  boot attached to the v1.1.0 release.
- Tag `v1.1.0`.

## Notes

- If upstream won't accept the driver push channel, we fork — but
  minimally, and document the divergence in
  `docs/upstream-divergence.md` per AGENT.md §21.
