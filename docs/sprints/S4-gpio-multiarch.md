# Sprint 4 — GPIO + Multi-arch Release

**Owner:** TBD. **Status:** in-progress (software complete; hardware test pending).

## Goal

Physical PiDP-11 hat works end-to-end: lamps animate, switches read,
boot-select encoder changes behavior. Release tagged as `v1.0.0` and
installable by any user with HAOS on a Pi 5 + the hat.

## Entry criteria

S3 exit gate signed. R6 (perf) baseline measured. A Pi 5 with the hat
is available for testing.

## Tasks

1. ✅ **Add-on config.** `privileged: [SYS_RAWIO]`, `devices: [/dev/mem]`,
   `gpio: true`, `devicetree: true`. Already in `config.yaml`.
2. ✅ **SimH build flags.** `pdp11_realcons` + `pidp1170_blinkenlightd` + `scansw`
   compiled from source in Dockerfile. GPIO driver baked into binary at build time.
3. ✅ **Cold-start ordering.** `run.sh` waits up to 5 s for `/dev/mem`
   (10 × 500 ms); falls back to `ENABLE_GPIO=false` + logs warning if unavailable.
   `rpcbind` and `pidp1170_blinkenlightd` are started before SimH in the boot loop.
4. ✅ **Realcons enabled at runtime.** `run.sh` generates a sed-patched copy of
   each `boot.ini` (in `/dev/shm/pidp11/`) with `set realcons` lines uncommented
   when `ENABLE_GPIO=true`. `blinky` handled as a special case (patches
   `PDP-11xx.ini` separately, redirects `boot.ini` → patched copy). Boot.ini
   source files remain unchanged so container-only operation still works.
4b. ⏳ **Boot-select encoder.** SR switch reading is wired (`scansw` → `getsel.sh`)
   but `scansw` binary is 32-bit ARM (armhf), which fails on the aarch64 container and
   Pi 5 host; also uses BCM2835 GPIO which doesn't exist on Pi 5. Needs rewrite or
   Pi 5-compatible replacement. `sensor.pidp11_boot_select` HA entity deferred.
5. ⏳ **CI image build.** Build `linux/arm64` image, push to
   `ghcr.io/<owner>/pidp11-addon-aarch64:X.Y.Z` on tag. Deferred to v1.0.0 release.
6. ⏳ **Hardware checklist.** Every v1 feature has a checklist entry in
   `tests/hardware/MANUAL-CHECKLIST.md`. Signed run attached to v1.0.0 release.

## Tests

- ✅ `tests/addon/test_gpio_mock.py::test_driver_writes_lamp_register` — xfail stub (pending PIDP11_GPIO_MOCK=1 container)
- ✅ `tests/addon/test_gpio_mock.py::test_driver_reads_switch_register` — xfail stub
- ✅ `tests/addon/test_startup_ordering.py::test_waits_for_dev_mem` — xfail stub
- ✅ `tests/addon/test_startup_ordering.py::test_blinkenlightd_starts_before_simh` — xfail stub
- [ ] Hardware checklist entries (see `tests/hardware/MANUAL-CHECKLIST.md`):
  - [x] Lamps animate (idled pattern confirmed on physical hat — Jun 21 2026)
  - [x] Lamps animate while 2.11BSD boots (lamp activity confirmed Jun 21 2026)
  - [x] SR register read via `EXAMINE SR` matches physical switches (all-down=000000, SW0-up=000001 confirmed Jun 21 2026; NOTE: use `EXAMINE SR` not `EXAMINE 177570` — latter reads through 2.11BSD MMU and gives wrong value)
  - [x] START/HALT switches change `sensor.pidp11_state` within 3 s (HALTED→RUNNING transition confirmed Jun 21 2026; polling at 3s interval)
  - [ ] Boot-select encoder changes `sensor.pidp11_boot_select`
  - [ ] Cold-boot HAOS → emulator up and hat responsive in < 60 s

## Exit gate

- Hardware checklist complete, signed, committed.
- `ghcr.io/<owner>/pidp11-addon-aarch64:1.0.0` pushed.
- HACS install succeeds from a freshly-flashed HAOS SD.
- `v1.0.0` tag + GitHub Release with checklist attached.
