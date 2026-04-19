# Testing Strategy — TDD, 100%

Every line of shipped code was preceded by a failing test. No exceptions.

## 1. Layers

| Layer              | Tool                                           | Where                         | Runs in CI | Runs on hardware |
| ------------------ | ---------------------------------------------- | ----------------------------- | ---------- | ---------------- |
| Schema / manifest  | `pytest` + json-schema                         | `tests/integration/schema/`   | ✓          | —                |
| Integration (HA)   | `pytest-homeassistant-custom-component`        | `tests/integration/`          | ✓          | —                |
| Protocol contract  | `pytest` with mock TCP server                  | `tests/integration/protocol/` | ✓          | —                |
| Add-on container   | `pytest` + `testcontainers`                    | `tests/addon/`                | ✓          | —                |
| Hardware-in-loop   | Human checklist, signed                        | `tests/hardware/`             | ✗          | ✓                |

## 2. TDD workflow

1. Write one failing test that names a single behavior.
2. Commit the failing test on a feature branch with message `test: red — <behavior>`.
3. Write the smallest change that makes it pass.
4. Commit with message `feat: green — <behavior>`.
5. Refactor without changing behavior; run the test again.
6. Commit with message `refactor: <what>` if structure changed.

The red-commit history is the proof. A PR reviewer checks that the
red commit exists for every new behavior.

## 3. Coverage gate

- `pytest --cov=custom_components.pidp11 --cov-fail-under=95`
- Add-on side: every branch in `run.sh` has a matching `tests/addon/`
  case. Tracked by counting `if/case` arms, not with `kcov`.

## 4. Protocol contract tests

The remote-console TCP protocol (integration ↔ SimH) has both sides
tested against the *same* fixture file
`tests/fixtures/remote_console_transcripts.txt`. Format: one block per
scenario, `>` lines are sent by client, `<` lines received. The
integration test replays the `>` lines against a real mock server; the
add-on test replays the `<` lines against a real SimH. If SimH's output
format changes, both tests go red together — that's the signal to update
the parser.

## 5. Add-on container tests

Spin up the built image with `testcontainers.DockerContainer`, bind a
tmpfs as `/share/pidp11/disks/`, expose ports, and assert:

- Container reaches `healthy` within 30 s.
- `dropbear` accepts a known password (set via env for the test).
- SSH into it lands in `screen` session `pidp11`.
- Remote console accepts `AUTH` + `show version` and responds.
- Stopping the container leaves no orphaned processes on host (checked
  via `docker stats` + subsequent `docker ps -a` inspection).

GPIO is not exercised in the container tests — we can't fake `/dev/mem`.
Instead, the container is started with env `PIDP11_GPIO_MOCK=1`, which
causes the SimH build to load a mock driver that logs every register
write. The test asserts on the log. See `docs/risks.md` — this requires
a small patch to upstream and is a spike in S4.

## 6. Hardware checklist

`tests/hardware/MANUAL-CHECKLIST.md` is the canonical list. Sample
entries for v1:

- [ ] Boot 2.11BSD from switch register — lamps animate correctly.
- [ ] Halt/continue toggles interrupt emulation within 1 s.
- [ ] SR-0..21 switches read back via `pidp11.examine` service.
- [ ] Front-panel boot-select encoder changes `options.default_boot`
  after a HA reload.
- [ ] Cold boot of HAOS brings the emulator up without manual
  intervention.

Every release candidate fills in the tester's initials + date + short
notes, and that completed copy gets attached to the GitHub Release.

## 7. CI

GitHub Actions workflow `ci.yml`:

1. `ruff check`, `mypy --strict`, `shellcheck`, `hadolint`.
2. `pytest -m "not hardware and not addon" --cov`.
3. Build the add-on image for `aarch64` with `docker buildx` + QEMU.
4. Boot the image on the CI runner, run `tests/addon/`.

No self-hosted runner needed for v1 — all four stages work on the
standard ubuntu-latest runner. The hardware layer is never in CI.

## 8. Fixtures & determinism

- Generated SSH keypairs: `tests/conftest.py` generates fresh ed25519
  keys per test session. Never committed.
- Time-dependent assertions use `freezegun`.
- Random seed pinned via `pytest-randomly` with a per-session seed logged
  in test output so failures reproduce.
