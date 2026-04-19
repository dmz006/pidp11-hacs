# Sprint 3 — HACS Integration

**Owner:** TBD. **Status:** planned.

## Goal

HA loads the integration from HACS. User adds it through the HA UI.
Core entities + services wired to the add-on's remote console.

## Entry criteria

S2 exit gate signed. R4 decision (auth shim) recorded and the shim
working in S1/S2's container. `docs/contracts/remote-console.md`
written.

## Tasks

1. **`const.py`** — `DOMAIN = "pidp11"`, default ports, option keys.
2. **`config_flow.py`** — single-step UI: host (default "pidp11"
   which is the HAOS-local add-on hostname), remote-console port
   (default 2223), shared secret (optional — if blank, fetch from
   Supervisor API via the add-on's `ingress_url`). Reauth flow
   handled.
3. **`__init__.py`** — `async_setup_entry`, `async_unload_entry`,
   forward platform setup for `sensor` and `switch`.
4. **`coordinator.py`** — `PiDP11Coordinator(DataUpdateCoordinator)`
   opens a persistent TCP connection to the remote-console shim,
   polls `show cpu` every 5 s by default, parses output into a
   dataclass `PiDP11State { pc, psw, run_state, last_error }`.
   Handles disconnects with exponential backoff.
5. **`sensor.py`** — `sensor.pidp11_state`, `sensor.pidp11_pc`,
   `sensor.pidp11_psw`, `sensor.pidp11_last_error`.
6. **`switch.py`** — `switch.pidp11_power` (on → SimH `boot <target>`,
   off → `halt`). State reflects coordinator data.
7. **`services.yaml` + service handlers** — `pidp11.boot` (target
   string), `pidp11.halt`, `pidp11.deposit` (addr, value),
   `pidp11.examine` (addr → returns value).
8. **Events** — fire `pidp11_halt`, `pidp11_trap` on matching
   remote-console output lines.
9. **`strings.json` + `translations/en.json`** — every config-flow
   string, every entity friendly name, every service description.
10. **Config-flow discovery** — if the add-on is installed on the
    same Supervisor, auto-discover it via the Supervisor API and
    pre-fill the host/port fields.

## Tests

- [ ] `tests/integration/test_config_flow.py::test_user_step_creates_entry`
- [ ] `tests/integration/test_config_flow.py::test_duplicate_host_aborts`
- [ ] `tests/integration/test_config_flow.py::test_reauth_on_bad_secret`
- [ ] `tests/integration/test_coordinator.py::test_polls_show_cpu`
- [ ] `tests/integration/test_coordinator.py::test_reconnects_on_drop`
- [ ] `tests/integration/test_coordinator.py::test_parses_halted_state`
- [ ] `tests/integration/test_sensors.py::test_state_reflects_coordinator`
- [ ] `tests/integration/test_sensors.py::test_pc_octal_format`
- [ ] `tests/integration/test_switch.py::test_turn_on_sends_boot`
- [ ] `tests/integration/test_switch.py::test_turn_off_sends_halt`
- [ ] `tests/integration/test_services.py::test_boot_service_call`
- [ ] `tests/integration/test_services.py::test_deposit_service_call`
- [ ] `tests/integration/test_services.py::test_examine_returns_value`
- [ ] `tests/integration/test_events.py::test_halt_fires_event`
- [ ] `tests/integration/test_events.py::test_trap_fires_event`
- [ ] `tests/integration/protocol/test_remote_console_transcripts.py::test_every_scenario`

## Exit gate

- Integration installs from a *custom* HACS repo URL.
- All integration tests green; coverage ≥ 95 %.
- The add-on remote-console contract test (S1) still green against
  the latest SimH pin.
- Tag `v0.3.0`.
