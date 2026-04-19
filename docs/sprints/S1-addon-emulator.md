# Sprint 1 — Add-on Emulator MVP (no GPIO)

**Owner:** TBD. **Status:** planned.

## Goal

A container that builds `obsolescence/pidp11` from source, runs SimH
with a bundled 2.11BSD disk image, and exposes the SimH remote console
on TCP. No GPIO, no SSH yet. Boot on amd64 dev box and aarch64 Pi.

## Entry criteria

S0 exit gate signed. R1 resolved (we know we can reach `/dev/mem`).

## Tasks

1. **Dockerfile.** Multi-stage:
   - stage 1: `debian:bookworm-slim`, install build deps
     (`build-essential`, `libpcap-dev`, `libvdeplug-dev` optional),
     clone `obsolescence/pidp11` at pinned SHA, `make` the `pidp11`
     binary.
   - stage 2: slim runtime with only the binaries + BSD disk image
     + bootstrap scripts.
2. **`run.sh`.** `set -euo pipefail`, validate required options,
   seed disk images from baked-in tarball if `/share/pidp11/disks/`
   is empty, `exec` SimH under s6-overlay.
3. **s6 services.** `services.d/pidp11/run` — launches SimH with a
   generated `.ini` that sets the remote console port and attaches
   the chosen boot disk.
4. **Boot selector.** Tiny shell script reads `options.default_boot`,
   writes the correct `boot rl0` / `boot rp0` line into the SimH
   init file before launch.
5. **Remote-console auth shim.** Python 3 asyncio script,
   `authshim.py`, bound to `0.0.0.0:2223`, proxies to
   `127.0.0.1:2224` after `AUTH <secret>\n` handshake.
6. **Image build.** `docker buildx build --platform linux/arm64` (Pi 5
   only; no other arch targets).

## Tests (moved red → green in this sprint)

- [ ] `tests/addon/test_container_boot.py::test_image_builds`
- [ ] `tests/addon/test_container_boot.py::test_healthy_within_30s`
- [ ] `tests/addon/test_remote_console.py::test_requires_auth`
- [ ] `tests/addon/test_remote_console.py::test_show_cpu_responds`
- [ ] `tests/addon/test_boot_selector.py::test_default_from_options`
- [ ] `tests/addon/test_boot_selector.py::test_override_via_env`

## Exit gate

- The add-on installed in a HAOS test environment (or a local
  Supervisor dev box) reaches `healthy` within 30 s and answers
  `show cpu` on the remote console.
- `pytest -m addon` green on CI runner.
- Dockerfile pinned to specific upstream SHA + specific SimH build
  flags.
- Tag `v0.1.0`.
