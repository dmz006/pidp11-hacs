# Changelog

Top-level project changelog. See `pidp11-addon/CHANGELOG.md` for the
add-on's own log. Both follow SemVer and stay in lockstep per
AGENT.md §7.

## [Unreleased]

### Fixed
- Dashboard card never rendered in Home Assistant: it is now a real custom element
  (`extends HTMLElement`), so Lovelace's `document.createElement` gets `setConfig`/`hass`.
- Card and README used `pidp11_*` entity ids; the device slugs to `pidp_11_*`. The card now
  falls back to the entity with the same suffix under either prefix.
- SimH ran out of its 4 console connections ("All connections busy"): the integration now
  shares one stream for lamps and SR, closes every connection, backs off, and keeps the last
  values while SimH is busy. The auth shim closes a SimH connection when its client goes away,
  times out idle proxied sessions and sends keepalive comments.

### Operator review required
- Entity ids are `pidp_11_*`, not `pidp11_*`. Check every automation, script, template and
  dashboard that references `pidp11_*` ids (Developer Tools → States) and update or rename.
- SR now rides the lamp stream (`AUTH <secret> +sr`, port 2226). Custom clients on port 2225
  keep working; re-check any proxy or firewall rule that only allows 2225.
- Reload the `pidp11-panel-card.js` resource (clear the browser cache) after upgrading.

### Changed
- The SR watch now rides the lamp stream (port 2226, `AUTH <secret> +sr`); port 2225 stays for old clients.
- Entity ids in the README: `sensor.pidp_11_switch_register`, `binary_sensor.pidp_11_cpu_halted`.
- Tests: Node/jsdom card tests under `tests/card` (`npm ci`).

## [1.4.3] - 2026-11-15

### Fixed
- A shared secret pasted with a leading or trailing space or newline was rejected as
  "Shared secret rejected by the add-on" even when correct. The config flow now strips the value.
- The setup form and the README gave a command to read the secret that cannot work
  (`ssh pdp11@<pi> -p 2211 'cat /data/remote_console.secret'`); they now give
  `sudo docker exec pidp11 cat /data/remote_console.secret`.

### Added
- Reconfigure step: change the shared secret of an existing device from
  Settings, Devices & Services, PiDP-11, the three-dot menu, **Reconfigure**.
- README: step-by-step "Adding the device in Home Assistant", a troubleshooting table and a
  check that tests the secret without printing it.

## [1.4.2] - 2026-11-14

### Fixed
- Config flow failed to load ("Invalid handler specified") on current HA:
  `ZeroconfServiceInfo` is now imported from
  `homeassistant.helpers.service_info.zeroconf`, falling back to the old
  location on older HA.

## [1.4.1] - 2026-11-14

### Fixed
- Add-on: authshim watchdog restarts a stalled lamp stream; Docker
  `HEALTHCHECK` added so Supervisor restarts an unhealthy add-on
  (lamp stream stability).
- Custom component: Lovelace card registration uses `async_register_static_paths` (the sync `register_static_path` was removed in HA core).
- CI: authshim loopback-socket tests use the `socket_enabled` fixture
  (the `enable_socket` marker no longer overrides the HA socket guard);
  ruff clean, so the GHCR publish job can run again.

### Added
- Initial scaffolding (S0): AGENT.md, docs, diagrams, sprint plans,
  skeleton Python module in `custom_components/pidp11/`, skeleton
  add-on in `pidp11-addon/`, failing test stubs in `tests/`.
- `LICENSE` (MIT), `hacs.json`, `repository.yaml`.

### Changed
- Scope narrowed: supported targets are **HAOS + HA Supervised only**.
  HA Container / HA Core are explicitly out of scope; no `docker run`
  or `docker-compose` install path ships. R7 retired in `docs/risks.md`.
- AGENT.md no longer references the datawatch template; rules are
  project-owned and self-contained.

### Open

- R1: confirm `/dev/mem` access from HAOS add-ons on Pi 5.
- R3: pick `screen -x` vs `-RR` for multi-user SSH.
- R4: design remote-console auth shim.
