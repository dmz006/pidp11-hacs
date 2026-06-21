# AGENT.md — pidp11-hacs

Operational rulebook for any AI agent (or human) working on this
repository. Tailored for a dual-artifact project: a Home Assistant
Supervisor add-on plus a HACS integration, co-located in one repo.

---

## 1. Pre-Execution Rule

Before any file change, verify compliance with every rule below. If a rule
conflicts with a task, stop and ask the user. Do not silently bypass a rule.

## 2. Session Safety

- Never stop or restart the user's running Home Assistant instance.
- Never touch a production add-on container; spin up a new one under a
  `pidp11-dev` slug for any test that mutates state.
- Do not write to `/share/pidp11/` on a user system without an explicit
  approval in the current session.

## 3. Scope Constraints

- Work only inside `/home/dmz/Private/src/workspace/pidp11-hacs` (the
  session guardrail in `CLAUDE.md`).
- No edits to system files, global pip installs, or Docker daemon config.
- Do not modify the upstream `obsolescence/pidp11` tree; consume it as a
  git submodule or pinned tarball URL only.

## 4. Code Quality Rules

- Every public Python symbol in `custom_components/pidp11/` has a type
  annotation. `mypy --strict` must pass.
- Shell scripts use `set -euo pipefail` and pass `shellcheck`.
- Dockerfiles pass `hadolint` with the project `.hadolint.yaml`.
- No TODOs land on `main` — open a GitHub issue and reference it from a
  comment instead.

## 5. Testing Rules — TDD, 100%

**Red → Green → Refactor is mandatory.** Tests are written *before* the
code that makes them pass. A PR without a failing-then-passing test in its
history cannot merge.

Two layers:

1. **Unit / integration (Python).** `pytest` +
   `pytest-homeassistant-custom-component`. Lives in `tests/integration/`.
   Mocks the telnet/SSH endpoints of the add-on. Runs in CI.
2. **Add-on container.** `pytest` + `testcontainers` (or `bats` if
   container is already built). Lives in `tests/addon/`. Boots the real
   image in Docker-in-Docker; asserts SSH login lands in `screen`, SimH
   responds on the remote-console port, disk images mount.

**Hardware-in-the-loop** tests live in `tests/hardware/MANUAL-CHECKLIST.md`
and are executed by a human on a Pi 5 with the PiDP-11 hat. Never gated in
CI. Every release candidate gets a completed checklist attached to the
GitHub release notes.

**Coverage**: `pytest --cov=custom_components.pidp11 --cov-fail-under=95`.
Add-on side: every `run.sh` branch has a matching test.

## 6. Git Discipline

- Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`,
  `refactor:`, `ci:`.
- Commit early, commit often. One logical change per commit.
- Never force-push `main`. Never squash without the user's ack.
- Never use `--no-verify`. If a hook fails, fix the underlying issue.
- Tag releases as `vX.Y.Z` (SemVer). The tag must exist before the
  GitHub Release and before `version` bumps in `manifest.json` /
  `pidp11-addon/config.yaml` land on `main`.

## 7. Versioning

SemVer across three files that must stay in lockstep:

- `custom_components/pidp11/manifest.json` → `version`
- `pidp11-addon/config.yaml` → `version`
- `CHANGELOG.md` at repo root

Bump rules:
- **patch** — docs, tests, internal refactors, container base-image bumps.
- **minor** — new HA entity, new service, new add-on option, new arch.
- **major** — breaking change to config schema, service signatures, or
  add-on option keys.

## 8. Dependency Rules

- Python deps pinned in `pyproject.toml`, not `requirements.txt`.
- Runtime deps of the integration belong in `manifest.json:requirements`
  *and* `pyproject.toml[dependencies]`; test deps in
  `pyproject.toml[project.optional-dependencies.test]`.
- New Python deps require a note in the commit body explaining why
  stdlib can't do it.
- Container deps pinned by SHA in the Dockerfile (apt packages by
  version, base images by digest).
- License compatibility: MIT-compatible only. Verify at add-time.

## 9. Planning Rules

- Any work > 1 sprint gets a plan in `docs/sprints/Sx-*.md`.
- Plans are dated (ISO `YYYY-MM-DD`), list success criteria, and list
  the tests that will prove completion.
- Plans are updated, not replaced. Mark obsolete sections struck rather
  than deleting, so history stays auditable.

## 10. Documentation Rules

- Every new HA entity, service, or add-on option is documented in
  `pidp11-addon/DOCS.md` (shown in HA UI) **and** in
  `custom_components/pidp11/strings.json`.
- User-facing docs reference no internal ticket numbers.
- Architecture changes update `docs/architecture.md` and relevant
  diagrams in `docs/diagrams.md` in the same PR as the code.

## 11. Project Tracking

- `docs/sprints/README.md` is the index. Every sprint has: status,
  entry criteria, exit criteria, test list, owner.
- Sprints never lose their ID; retire by marking `status: complete` or
  `status: cancelled`.

## 12. Release Discipline

- **Release (minor/major)**: new tag, GitHub Release with CHANGELOG
  excerpt, multi-arch container image pushed to GHCR with both `:X.Y.Z`
  and `:X.Y` tags, hardware checklist attached.
- **Patch**: new tag, no GitHub Release body required if CHANGELOG
  entry is trivial.
- Never re-tag a shipped version.

## 13. Interruption Handling

If an agent is rate-limited or otherwise interrupted mid-task, it must
leave the working tree in a committable state — either fully clean, or
with a WIP commit on a `wip/<topic>` branch naming the next step in the
commit body. Never leave uncommitted partial edits on `main`. On
resume, the next agent reads the latest commit message to pick up.

## 14. Security Rules

- No credentials in code, commits, logs, or test fixtures. Test SSH
  uses a throwaway keypair generated per-session, not committed.
- The add-on must not phone home. No outbound network calls except to
  the configured upstream emulator sources.
- `/dev/mem` access is privileged; every use is reviewed in the PR and
  documented in `docs/risks.md`.
- Default SSH password is **never** a fixed string — add-on must
  require the user to set it on first start and refuse to boot
  otherwise.

## 15. Session Management Rules

- A session that changes configuration ends with a commit.
- A session that only reads/diagnoses ends with a note in
  `docs/sprints/Sx-*.md` under "notes".

## 16. Feature Documentation — All Access Methods

Every user-visible feature is documented across all four paths it can
be reached from:

1. **Add-on UI** — `config.yaml:options` + `schema` + `DOCS.md`.
2. **HA UI** — config-flow strings in `translations/en.json`.
3. **HA service call** — `services.yaml`.
4. **Raw SSH** — `DOCS.md` shows the equivalent shell command.

If any of the four is missing, the feature is incomplete.

## 17. Decision Making

When the agent is uncertain between two valid approaches, it **asks the
user**, records the answer inline in the relevant doc, and — if the
decision is likely to recur — adds a new rule to this file.

## 18. Configuration Rules

- Every add-on option appears in `config.yaml:options`, validated in
  `config.yaml:schema`, documented in `DOCS.md`, and has a default that
  makes a fresh install functional on a Pi 5 with hardware.
- Integration options appear in the config flow UI; no YAML-only
  options.

## 19. Hardware Spike Gate

Any change that touches `/dev/mem`, `/dev/gpiomem`, or kernel modules
is gated by a manual hardware test on a Pi 5 with a PiDP-11 hat before
merge. The hardware-test entry in
`tests/hardware/MANUAL-CHECKLIST.md` is signed by the tester (initials +
date) in the commit body.

## 20. Monitoring & Observability

- Add-on emits structured logs (JSON lines) to stdout; Supervisor
  aggregates. Log levels follow HA conventions (`info`, `warning`,
  `error`).
- The integration exposes `sensor.pidp11_last_error` + an HA event
  `pidp11_halt_trap` for automations.

## 21. Upstream Sync Rule

When `obsolescence/pidp11` publishes a new upstream commit, we:

1. Open a tracking issue with the upstream commit hash.
2. Bump the pinned commit in the Dockerfile.
3. Run the full add-on test suite + hardware checklist.
4. Patch-release on green.

Never fork upstream semantics without documenting the divergence in
`docs/upstream-divergence.md`.

## 22. Scope Diff Rule

If the user requests work that would expand scope beyond the current
sprint, the agent lists the expansion, its cost in sprints, and asks
for approval before starting.

---

*Rule changes require a user ack; amend this file in the same PR that
introduces the change that motivates them.*


# Memory & Knowledge (datawatch)

Use the datawatch memory system proactively during this session.

## Before starting work
- Use `memory_recall` to check if similar work has been done
- Use `kg_query` to understand entity relationships
- Use `research_sessions` for deep cross-session search

## During work
- Use `memory_remember` to save key decisions and patterns
- Use `kg_add` to record relationships

## When asked about project history
Always check memory first with `memory_recall` before answering from training data.

## Available tools
| Tool | Purpose |
|------|---------|
| `memory_recall` | Semantic search across project memories |
| `memory_remember` | Save decisions, patterns, context |
| `kg_query` | Entity relationship queries |
| `kg_add` | Record new relationships |
| `research_sessions` | Cross-session research |
| `copy_response` | Last LLM response from any session |
| `get_prompt` | Last user prompt from any session |

<!-- rtk-instructions -->
# RTK (Rust Token Killer) - Token-Optimized Commands

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it.
If not, it passes through unchanged. This means RTK is always safe to use.

```bash
# Always use rtk prefix, even in chains:
rtk go build && rtk go test ./...
rtk cargo build
rtk git status && rtk git diff
rtk git log
```

**Key savings:** Build 80-90%, Test 90-99%, Git 59-80%, Files 60-75%.
Run `rtk gain` to view token savings statistics.
<!-- /rtk-instructions -->