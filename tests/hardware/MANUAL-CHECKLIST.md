# Hardware Manual Test Checklist

Run on a Raspberry Pi 5 with HAOS and a PiDP-11 hat on the 40-pin
header. Tester initials + ISO date go next to every line; the
completed copy is attached to the matching GitHub Release.

Template: copy this file to `tests/hardware/runs/v<X.Y.Z>.md`, sign,
commit with message `test: hardware checklist vX.Y.Z — <initials>`.

---

## Release under test

- Version: `vX.Y.Z`
- Tester: `<initials>`
- Date: `<YYYY-MM-DD>`
- Pi model: `Raspberry Pi 5 <RAM>`
- HAOS version: `<x.y>`
- PiDP-11 hat serial / notes: `<text>`

## S1 — container MVP

- [ ] Add-on installs from the repo URL.
- [ ] Add-on reaches "Started" state within 60 s.
- [ ] Container logs show no errors.

## S2 — SSH console

- [ ] `ssh pdp11-user@<haos-host> -p 2211` prompts for password.
- [ ] Correct password → `screen` banner, then SimH `.` prompt.
- [ ] Wrong password → rejected.
- [ ] `^A d` detaches; emulator keeps running (lamp animation
      continues).
- [ ] Reconnect → same SimH session (no restart).
- [ ] Second concurrent SSH user shares the console view.
- [ ] Change password in add-on UI → restart → old password
      rejected within one restart cycle.
- [ ] Password never appears in `ha addons logs pidp11`.

## S3 — HACS integration

- [ ] Integration installs from HACS custom-repository URL.
- [ ] Add Integration UI finds it and completes setup.
- [ ] `sensor.pidp11_state` appears and reflects halt/run.
- [ ] `switch.pidp11_power` toggles SimH boot/halt.
- [ ] `pidp11.boot target=211bsd` service call boots 2.11BSD.
- [ ] `pidp11.examine address=0o177570` returns SR register
      value matching the physical switches.

## S4 — GPIO + release

- [ ] Lamps animate during 2.11BSD boot (side-by-side with a
      reference video).
- [ ] SR register read matches physical switches at rest and
      after every flip.
- [ ] Physical START/HALT toggles update `sensor.pidp11_state`
      within 1 s.
- [ ] Boot-select encoder updates `sensor.pidp11_boot_select`.
- [ ] Cold HAOS boot → emulator + hat responsive within 60 s of
      HA-login-page ready.

## S5 — Lovelace panel & switch events

- [ ] Lovelace panel card renders PiDP-11 face.
- [ ] Every LED on the card tracks the physical lamp.
- [ ] Flipping each physical switch fires a `pidp11_switch`
      event with the correct name.
- [ ] Clicking a switch on the card drives the physical lamp
      state (if write-path is in scope).

## Regressions to catch

- [ ] HA restart does not lose `pidp11` session state for attached
      SSH users (they can reconnect and find the same SimH).
- [ ] Container restart reseeds disk images only when
      `/share/pidp11/disks/` is empty — never overwrites user data.
- [ ] No extra CPU load on HA when emulator idle.

## Notes from this run

```
<free-form>
```

## Sign-off

`<initials>` `<date>`
