# Risks & Open Questions

Living document. Each entry has an owner, a mitigation, and — once
retired — a link to the PR that closed it.

## R1 — `/dev/mem` access from HAOS add-ons (BLOCKER if unresolved)

**Risk.** The Pi 5 pidp11 driver mmaps `/dev/mem` directly (RP1
pinctrl). HAOS may restrict `/dev/mem` exposure to add-ons even with
`privileged: [SYS_RAWIO]` + `devices: [/dev/mem]`. If restricted, we
cannot drive the hat from a container.

**Spike.** S0-spike-1: boot HAOS on a Pi 5, install a minimal test
add-on with `/dev/mem` mapped, run `dd if=/dev/mem bs=4 count=1`. If
that reads 4 bytes without EPERM, we are green. If not, we investigate
`kernel_modules: true`, `full_access: true`, or an alternative path
using upstream's libgpiod fallback (would need an upstream PR).

**Owner.** David. **Status.** Open. **Tracking.** issue TBD.

## R2 — Upstream `obsolescence/pidp11` has no root LICENSE file

**Risk.** Per-file MIT headers exist, but no repo-root `LICENSE`
means redistribution under a single SPDX tag is ambiguous for image
registries and HACS metadata.

**Mitigation.** (a) Open an upstream issue asking for a top-level
LICENSE; (b) in our Dockerfile, bundle a `THIRD_PARTY_LICENSES` file
that reproduces each MIT header with attribution; (c) our own code
ships under MIT unambiguously.

**Owner.** David. **Status.** Open.

## R3 — `screen` session ownership and re-attach behavior

**Risk.** If two SSH users connect simultaneously, both try to attach
to the same `screen` session. `screen -RR` attaches even if another
attached session exists, which can clobber the other user's terminal
state.

**Mitigation.** Decide in S2 between `-x` (multi-attach, same view)
and `-RR` (take over). We recommend `-x` so multiple users share the
console read-only-ish — matching the spirit of a shared physical
front panel. Confirm with user.

**Owner.** TBD. **Status.** Design question for S2.

## R4 — SimH remote-console auth

**Risk.** SimH's "remote console" (`set remote`) does not natively
support authentication. If we expose it on a host port for the HA
integration, anyone on the LAN can drive the emulator.

**Mitigation.** Wrap SimH's remote console behind a tiny Python
auth-shim inside the container (accept TCP, require `AUTH <secret>`,
then forward bytes to the local SimH remote-console socket). Secret
lives in `/data/remote_console.secret`, generated on first start.
Bind to container-internal IP only unless user opts into LAN access.

**Owner.** TBD. **Status.** Design decision for S3.

## R5 — SSH password rotation surface

**Risk.** User asked for "SSH set via add-on options and can be
reset." We must guarantee a rotation does not lock out an already-
attached session, and must never log the new password.

**Mitigation.** On options-change, Supervisor restarts the add-on —
dropbear picks up the new hash, existing sessions survive until they
disconnect. Password hashed with `yescrypt`. Never written to stdout
or Supervisor logs.

**Owner.** TBD. **Status.** Plan for S2.

## R6 — Performance / GPIO timing under a container

**Risk.** SimH + pidp11 GPIO driver spins updating lamps at ~1 kHz.
Containerization adds scheduling noise that could cause visible lamp
flicker or missed switch reads on a Pi 5, especially if HA is under
load.

**Mitigation.** `cpuset` pin the container to an isolated core if
possible; set `cgroup-parent` to give SimH priority; measure with
`perf`. Fall back to `cpu_shares` tuning. Add a hardware-checklist
entry "lamp animation matches bare-metal reference video".

**Owner.** TBD. **Status.** Observe in S4.

## R7 — HA Container install path (non-HAOS)

**Risk.** Users on HA Container cannot install Supervisor add-ons.
The README claims we support them via `docker run`; we need to
actually write that doc and test it.

**Mitigation.** `docs/install-container.md` in S4, plus a
`docker-compose.example.yml`. Explicitly supported targets documented.

**Owner.** TBD. **Status.** Plan for S4.

## R8 — HACS review / acceptance

**Risk.** HACS has review criteria for default-repo inclusion. v1
targets *custom repository* install only (user pastes URL). Default
inclusion is a later goal.

**Mitigation.** Track HACS acceptance as a post-v1 line item; keep
`hacs.json` schema-valid regardless.

**Owner.** TBD. **Status.** Post-v1.

## R9 — Upstream API drift (SimH command output)

**Risk.** Our integration parses SimH command output with regex. If
upstream changes phrasing, we silently break.

**Mitigation.** Contract tests (`tests/integration/protocol/`) run a
recorded transcript against the live SimH in the container test, so
the parser and the producer go red together. See
`docs/testing-strategy.md §4`.

**Owner.** TBD. **Status.** Plan for S3.

## R10 — Boot-selector source-of-truth collision

**Risk.** Three inputs can change the next boot target: `options.json`,
the front-panel encoder, an HA service call. They will disagree.

**Mitigation.** Last-writer-wins, with every change logged as a
`sensor.pidp11_boot_source` state attribute. Document this explicitly
in the add-on DOCS.md. Decide in S3 whether "HA service wins until
user touches encoder" should be the rule instead.

**Owner.** David. **Status.** Design question for S3.
