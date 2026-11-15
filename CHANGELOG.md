# Changelog

Top-level project changelog. See `pidp11-addon/CHANGELOG.md` for the
add-on's own log. Both follow SemVer and stay in lockstep per
AGENT.md §7.

## [Unreleased]

## [1.4.2] - 2026-11-14

### Fixed
- Config flow failed to load ("Invalid handler specified") on current HA:
  `ZeroconfServiceInfo` is now imported from
  `homeassistant.helpers.service_info.zeroconf`.
- Minimum Home Assistant version raised to 2025.1.0 (`hacs.json`).

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
