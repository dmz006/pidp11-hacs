# Sprint 0 — Scaffolding & Contracts

**Dated:** 2026-04-18. **Owner:** David. **Status:** planned.

## Goal

Land the skeleton: every file that will hold code exists, every public
interface is named, every public interface has at least one failing
test. Resolve the two blocking unknowns (R1 `/dev/mem` on HAOS,
R3 `screen` mode) before S1 opens.

## Entry criteria

- Repo exists with `AGENT.md`, `README.md`, `docs/`.
- User has agreed to the architecture in `docs/architecture.md`.

## Tasks

1. **Structure.** Create directory layout per `docs/architecture.md`:
   `custom_components/pidp11/`, `pidp11-addon/`, `tests/`, `.github/`.
2. **Manifests.** `custom_components/pidp11/manifest.json`,
   `pidp11-addon/config.yaml`, `hacs.json`, `repository.yaml`. All
   three pass their respective JSON-schema validators (in tests).
3. **Failing tests.** One failing `pytest` test per public surface:
   - manifest schema
   - add-on config schema
   - config-flow user step (name → host → port)
   - coordinator construction
   - each entity class (sensor, switch)
   - each service name (boot, halt, deposit, examine)
   - add-on container boot (xfail until S1)
   - SSH listener (xfail until S2)
4. **CI.** Minimal `ci.yml`: ruff, mypy, pytest (excluding `hardware`,
   `addon` markers). Green.
5. **Spike R1** — boot HAOS on a spare SD card on the Pi 5, install a
   smoke-test add-on that maps `/dev/mem`, measure what access we
   get. Results land in `docs/risks.md` R1 as *closed* or *escalated*.
6. **Decision R3** — pick `screen -x` vs `-RR`. Default recommendation
   `-x`. Record decision in `docs/sprints/S0-scaffolding.md > Decisions`.
7. **Decision R4** — design the remote-console auth shim. Sketch
   protocol in `docs/contracts/remote-console.md`.

## Tests (red list)

- [ ] `tests/integration/schema/test_manifest.py::test_required_keys`
- [ ] `tests/integration/schema/test_manifest.py::test_semver`
- [ ] `tests/integration/schema/test_addon_config.py::test_required_keys`
- [ ] `tests/integration/schema/test_addon_config.py::test_arm64_in_arch`
- [ ] `tests/integration/test_config_flow.py::test_user_step_exists`
- [ ] `tests/integration/test_coordinator.py::test_construct`
- [ ] `tests/integration/test_entities.py::test_sensor_registered`
- [ ] `tests/integration/test_entities.py::test_switch_registered`
- [ ] `tests/integration/test_services.py::test_boot_service_registered`
- [ ] `tests/integration/test_services.py::test_halt_service_registered`
- [ ] `tests/addon/test_container_boot.py::test_image_builds` — xfail S1
- [ ] `tests/addon/test_ssh_access.py::test_ssh_responds` — xfail S2

## Exit gate

- All listed tests exist and fail with `NotImplementedError` or
  equivalent (so we know they're wired, not silent).
- CI green on lint + schema tests.
- R1 resolved: known-good path to reach `/dev/mem` from the add-on.
- R3 decided + written into `docs/sprints/S0-scaffolding.md`.
- Tag `v0.0.1` created — proves the versioning lockstep works.

## Decisions

*(filled in as sprint runs)*

- R3 — recommended `-x`, pending user ack. — *[date] [initials]*
- R4 — remote-console auth shim: small asyncio TCP proxy in Python
  inside the container, does `AUTH` handshake then bridges to SimH's
  `127.0.0.1:2224` local remote-console port. — *[date] [initials]*

## Notes

- Nothing in `custom_components/pidp11/*.py` runs yet; every public
  function raises `NotImplementedError("pending S<N>")`.
- `pidp11-addon/Dockerfile` exists but only contains `FROM scratch`
  + a comment; it does not build a useful image.
