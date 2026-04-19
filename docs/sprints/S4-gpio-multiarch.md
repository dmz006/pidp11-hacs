# Sprint 4 — GPIO + Multi-arch Release

**Owner:** TBD. **Status:** planned.

## Goal

Physical PiDP-11 hat works end-to-end: lamps animate, switches read,
boot-select encoder changes behavior. Release tagged as `v1.0.0` and
installable by any user with HAOS on a Pi 5 + the hat.

## Entry criteria

S3 exit gate signed. R6 (perf) baseline measured. A Pi 5 with the hat
is available for testing.

## Tasks

1. **Add-on config.** `privileged: [SYS_RAWIO]`, `devices: [/dev/mem]`,
   `gpio: true`, `devicetree: true`. Verified against R1 findings.
2. **SimH build flags.** Enable the pidp11 GPIO driver in the image
   (bake flag at `make` time, not runtime).
3. **Cold-start ordering.** s6 must start SimH *after* `/dev/mem` is
   available; if not, wait-loop with bounded retries (10 × 500 ms).
4. **Boot-select encoder.** Wire the encoder read path to update
   `sensor.pidp11_boot_select` and trigger the boot-selector service
   per R10 decision.
5. **Multi-arch CI.** Build `linux/arm64` image, push to
   `ghcr.io/<owner>/pidp11-addon-aarch64:X.Y.Z` on tag.
   `linux/amd64` ships too but is emulator-only (no GPIO) and uses a
   different image name.
6. **Docs for HA Container users.** `docs/install-container.md` with
   a `docker-compose.example.yml` that sets the same devices +
   privileges.
7. **Hardware checklist updated.** Every v1 feature has a checklist
   entry in `tests/hardware/MANUAL-CHECKLIST.md`. Signed run attached
   to the v1.0.0 release.

## Tests

- [ ] `tests/addon/test_gpio_mock.py::test_driver_writes_lamp_register`
      (uses `PIDP11_GPIO_MOCK=1`)
- [ ] `tests/addon/test_gpio_mock.py::test_driver_reads_switch_register`
- [ ] `tests/addon/test_startup_ordering.py::test_waits_for_dev_mem`
- [ ] Hardware checklist entries (see
      `tests/hardware/MANUAL-CHECKLIST.md`):
  - [ ] Lamps animate while 2.11BSD boots
  - [ ] SR register read via `pidp11.examine` matches physical switches
  - [ ] START/HALT switches change `sensor.pidp11_state` within 1 s
  - [ ] Boot-select encoder changes `sensor.pidp11_boot_select`
  - [ ] Cold-boot HAOS → emulator up and hat responsive in < 60 s

## Exit gate

- Hardware checklist complete, signed, committed.
- `ghcr.io/<owner>/pidp11-addon-aarch64:1.0.0` pushed.
- HACS install succeeds from a freshly-flashed HAOS SD.
- `v1.0.0` tag + GitHub Release with checklist attached.
