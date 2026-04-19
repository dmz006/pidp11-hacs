# Changelog

Top-level project changelog. See `pidp11-addon/CHANGELOG.md` for the
add-on's own log. Both follow SemVer and stay in lockstep per
AGENT.md §7.

## [Unreleased]

### Added
- Initial scaffolding (S0): AGENT.md, docs, diagrams, sprint plans,
  skeleton Python module in `custom_components/pidp11/`, skeleton
  add-on in `pidp11-addon/`, failing test stubs in `tests/`.
- `LICENSE` (MIT), `hacs.json`, `repository.yaml`.

### Open

- R1: confirm `/dev/mem` access from HAOS add-ons on Pi 5.
- R3: pick `screen -x` vs `-RR` for multi-user SSH.
- R4: design remote-console auth shim.
