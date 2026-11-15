# Changelog

All notable changes to the `pidp11-addon` container. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning:
[SemVer](https://semver.org/spec/v2.0.0.html), kept in lockstep with
the HACS integration version (see AGENT.md §7).

## [Unreleased]

### Fixed
- Auth shim leaked SimH console connections when a client vanished; it now closes them in a
  `finally`, detects client EOF on streams, enforces `IDLE_TIMEOUT` and sends keepalives.
- SimH's remote console (port 2224) stayed down after "bind error 98 / Can't open network port":
  `run.sh` waits up to 90 s (`port_wait.py bindable`) for 127.0.0.1:2224 to be bindable before
  starting SimH, and logs `ERROR: SimH remote console not listening on 2224` if it is not
  listening 20 s after start.
- `AUTH <secret> +system` on port 2223 is answered `SYSTEM <name>` from
  `/share/pidp11/current_system` (or `unknown`), without a SimH connection. Used by the
  integration when its own copy of the file is missing.

### Added
- `AUTH <secret> +sr` on the lamp port (2226) also streams `EVENT sr value=<octal>`.
- Env vars `IDLE_TIMEOUT` (3600) and `HEARTBEAT_INTERVAL` (15).

## [1.4.3] - 2026-11-15

### Changed
- Version bump in lockstep with the integration (no add-on code change). The documentation
  now says how to read and rotate the remote-console secret.

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
- S0 skeleton: `config.yaml`, `Dockerfile`, `run.sh`, `DOCS.md`.
  Nothing functional.
