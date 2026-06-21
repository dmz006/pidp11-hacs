# Running the PiDP-11 Container Without Home Assistant

The same Docker image that powers the HAOS add-on works perfectly as a
standalone PDP-11 emulator on any Raspberry Pi 5 running Raspberry Pi OS.
No Home Assistant required — you get SimH, the GPIO lamp driver, and an SSH
console, all in one pull.

This is also the fastest way to get the blinking lights going if you just
want to see the panel light up before worrying about HA.

---

## Prerequisites

- **Raspberry Pi 5** (the GPIO driver uses the RP1 chip — Pi 4 and earlier
  are not supported for lamps, but the emulator itself will run headless on
  any 64-bit arm Linux)
- **Raspberry Pi OS 64-bit (Bookworm)** — or any Debian arm64 system with Docker
- **The PiDP-11 hat** — for physical lamps and switches (optional; the
  emulator boots fine without hardware)
- Docker and rpcbind installed (one-liners below)

---

## 1 — Install Docker

If you don't have Docker yet:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker        # activate group membership now, or log out and back in
```

Docker enables itself on boot automatically — no extra systemd step needed.

## 2 — Enable rpcbind (required for GPIO lamps)

The GPIO driver communicates with SimH via ONC RPC. `rpcbind` must be
running and its socket must exist at `/run/rpcbind.sock` before the
container starts:

```bash
sudo apt-get install -y rpcbind
sudo systemctl enable --now rpcbind
```

Verify the socket exists:
```bash
ls -la /run/rpcbind.sock    # should show srwxr-xr-x
```

If you skip this step the emulator still runs but the physical lamps on the
PiDP-11 hat will not light up.

---

## 3 — Create the share directory

The container reads disk images from a directory on the host, mounted into the
container at `/share`. Use a fixed absolute path — **not `$HOME`** — so it
doesn't change depending on whether you run Docker as your user or with `sudo`:

```bash
sudo mkdir -p /opt/pidp11-share/pidp11/disks
sudo chown pi:pi /opt/pidp11-share     # or: sudo chown $(whoami) /opt/pidp11-share
```

This path (`/opt/pidp11-share`) is what the run command and image downloader
below both use. Change it consistently if you prefer somewhere else.

---

## 4 — Download disk images

Most systems ship bundled in the Docker image. A few large disk images need to
be staged in the share directory first (rsx11mp, unix7, sysiii, sysv). Run the
downloader from the repo — it fetches Oscar's systems archive and lets you
opt into 2.11BSD and the Bilquist RSX-11M+:

```bash
# From a clone of this repo on the Pi:
git clone https://github.com/dmz006/pidp11-hacs.git /tmp/pidp11-hacs
bash /tmp/pidp11-hacs/scripts/get-images.sh /opt/pidp11-share
```

Or if you already have a native pidp11 install (`/opt/pidp11/systems/`), copy
from there instead:

```bash
for sys in rsx11mp unix7 sysiii sysv; do
  sudo mkdir -p /opt/pidp11-share/pidp11/disks/${sys}
  sudo cp /opt/pidp11/systems/${sys}/*.dsk \
          /opt/pidp11/systems/${sys}/*.hp \
          /opt/pidp11-share/pidp11/disks/${sys}/ 2>/dev/null || true
done
sudo chown -R pi:pi /opt/pidp11-share
```

**What's bundled (no staging needed):** idled, blinky, dos11, rsts7, rt11,
unix1, unix5, unix6. 2.11BSD is auto-downloaded on first container boot (~250 MB).

---

## 5 — Pull and run

```bash
docker run -d \
  --name pidp11 \
  --restart unless-stopped \
  --privileged \
  --network host \
  -v /run/rpcbind.sock:/run/rpcbind.sock \
  -v /opt/pidp11-share:/share \
  -v pidp11-data:/data \
  -e ENABLE_GPIO=true \
  -e SSH_PASSWORD=pdp11 \
  -e SSH_PORT=2211 \
  ghcr.io/dmz006/pidp11-addon:latest
```

Replace `pdp11` with a real password.

What each flag does:

| Flag | Why |
|------|-----|
| `--privileged` | Required for `/dev/gpiomem*` access (RP1 GPIO) |
| `--network host` | Lets ONC RPC bind to the standard portmapper port |
| `/run/rpcbind.sock` | Shares the host rpcbind socket so the GPIO driver can register |
| `/opt/pidp11-share:/share` | Disk images and persistent share (survives container updates) |
| `pidp11-data` | Named volume for state, SSH host keys, and the auth-shim secret |
| `ENABLE_GPIO=true` | Starts `pidp1170_blinkenlightd` and `scansw` for physical lamps |
| `SSH_PASSWORD` | Sets the `pdp11` user's SSH password for console access |
| `SSH_PORT=2211` | Dropbear listens on 2211 — avoids colliding with the Pi's own openssh on port 22 |
| `--restart unless-stopped` | Survives reboot; stays down after manual `docker stop` |

The image is built for **linux/arm64** only. It will not run on x86.

**Without the hat** (emulator only, no GPIO lamps):

```bash
docker run -d \
  --name pidp11 \
  --restart unless-stopped \
  -p 2211:22 \
  -v /opt/pidp11-share:/share \
  -v pidp11-data:/data \
  -e SSH_PASSWORD=pdp11 \
  ghcr.io/dmz006/pidp11-addon:latest
```

No `--network host` needed without GPIO. Use `-p 2211:22` for port mapping instead — dropbear stays on its default port 22 inside the container, the host exposes it on 2211.

---

## 4 — Watch it start

```bash
docker logs -f pidp11
```

Within ~30 seconds you should see:

```
[pidp11] Default boot: idled | GPIO: true
[pidp11] Starting auth shim (:2223 → SimH :2224)
[pidp11] Using host rpcbind (socket already present)
[pidp11] Starting Blinkenlight server (server11)
[pidp11] Blinkenlight server registered with portmapper
[pidp11] Launching SimH in screen session 'pidp11'
[pidp11] Booting: idled
```

The physical lamps should begin their idle animation. If they don't, check
the troubleshooting section at the bottom.

---

## 5 — SSH to the PDP-11 console

```bash
ssh pdp11@localhost -p 2211
# or from another machine:
ssh pdp11@<your-pi-ip> -p 2211
```

You land in a `screen` session attached to SimH's interactive console. The
PDP-11 is right there. Some things to try:

```
EXAMINE PC          ; where is the program counter?
HALT                ; stop the CPU (watch the RUN lamp go dark)
CONTINUE            ; resume (watch it light up again)
BOOT DU0            ; boot from disk unit 0 (if you have a disk image staged)
```

Detach from the screen session without stopping SimH: press `Ctrl-A` then `d`.
You can re-attach with another SSH login at any time — multiple users can connect.

### No SSH key? Use `ssh-keygen` first:

Alternatively, pass an authorized key at container startup to avoid passwords:

```bash
docker run -d ... -e SSH_AUTHORIZED_KEYS="$(cat ~/.ssh/id_ed25519.pub)" ...
```

---

## 6 — Day-to-day management

```bash
# See what's running
docker ps

# Follow live logs (Ctrl-C to exit)
docker logs -f pidp11

# Stop the emulator cleanly
docker stop pidp11

# Start it again
docker start pidp11

# Restart (same as stop + start)
docker restart pidp11

# See all container settings (image, env vars, mounts)
docker inspect pidp11

# How much memory/CPU is it using?
docker stats pidp11
```

The container is set to `--restart unless-stopped` — it comes back
automatically after a Pi reboot. A manual `docker stop pidp11` will NOT
auto-restart until you manually `docker start pidp11` again.

---

## 7 — Disk images

### What's bundled in the image

These systems ship with disk images inside the container — no staging needed:

| System | OS | Notes |
|--------|----|-------|
| `idled` | Lamp animation | Default. No disk — pure light show. |
| `blinky` | LED demo | No disk. |
| `dos11` | DOS-11 | Disk bundled. |
| `rsts7` | RSTS/E v7.0 | Disk bundled. |
| `rt11` | RT-11 | Disks bundled (RT-11 + DEC graphics). |
| `unix1` | Unix V1 | Disks bundled (reconstructed). |
| `unix5` | Unix V5 | Disk bundled. |
| `unix6` | Unix V6 | Disks bundled. |
| `211bsd` | 2.11BSD | **Downloaded automatically** (~250 MB, Chase Covello's image). |

### Disk images that need to be staged

These systems need disk images placed in `/opt/pidp11-share/pidp11/disks/<system>/`
on the host (which maps to `/share/pidp11/disks/<system>/` inside the container):

| System | OS | Filename needed | Where to get it |
|--------|----|-----------------|-----------------|
| `rsx11mp` | RSX-11M+ | `rsx11mp/PiDP11_DU0.dsk` | Oscar's distribution or `scripts/get-images.sh` |
| `rsx11bq` | RSX-11M+ (Bilquist) | `rsx11bq/pidp.dsk` | Same |
| `unix7` | Unix V7 | `unix7/disk0.hp` | Upstream distribution |
| `sysiii` | Unix System III | `sysiii/disk.hp` | Upstream distribution |
| `sysv` | Unix System V | `sysv/disk.hp` | Upstream distribution |

If a disk image is missing, the container logs a warning and falls back to `idled`.
No crash, no data loss.

### Getting disk images from the upstream native install

If you previously ran the native pidp11 installer on your Pi, the disk images
are at `/opt/pidp11/systems/<system>/`. Hard-link them into the share directory
(no extra disk space used, since they're on the same filesystem):

```bash
sudo mkdir -p /opt/pidp11-share/pidp11/disks
for sys in rsx11mp rsx11bq unix7 sysiii sysv 211bsd; do
  [ -d /opt/pidp11/systems/$sys ] || continue
  sudo mkdir -p /opt/pidp11-share/pidp11/disks/$sys
  find /opt/pidp11/systems/$sys -maxdepth 1 -type f \
    \( -name '*.dsk' -o -name '*.hp' -o -name '*.tap' -o -name '*.rk' \) -print0 \
    | xargs -0 -I{} sudo ln '{}' /opt/pidp11-share/pidp11/disks/$sys/
done
```

If you're on a fresh Pi with no native install, use `scripts/get-images.sh` (section 4 above) — it downloads Oscar's systems archive and the individual large images directly.

### Staging a new disk image

Drop the image file into the right subdirectory on the host:

```bash
# copy from local machine
scp yourimage.dsk user@<pi-ip>:/opt/pidp11-share/pidp11/disks/rsx11mp/PiDP11_DU0.dsk
# or copy from elsewhere on the Pi
sudo cp /path/to/image.dsk /opt/pidp11-share/pidp11/disks/rsx11mp/PiDP11_DU0.dsk
docker restart pidp11
```

---

## 8 — Boot a different OS with the front-panel switches

For the complete OS switch table, front panel control sequences (halt, single-step,
memory examine/deposit, start), and safe shutdown procedures, see the dedicated guide:

**[docs/front-panel.md](./front-panel.md)**

Quick reference:

| SR (octal) | System | Disk required |
|-----------|--------|---------------|
| `0000` | `idled` — lamp demo (default, all switches down) | — |
| `0001` | `rsx11mplus` — RSX-11M+ | `rsx11mp/PiDP11_DU0.dsk` |
| `0002` | `rsts7` — RSTS/E v7.0 | Bundled |
| `0003` | `rt11` — RT-11 | Bundled |
| `0004` | `dos11` — DOS-11 | Bundled |
| `0005` | `ias` — IAS | Bundled |
| `0102` | `211bsd` — 2.11BSD | Auto-downloaded |
| `0105` | `unix5` — Unix V5 | Bundled |
| `0106` | `unix6` — Unix V6 | Bundled |
| `0107` | `unix7` — Unix V7 | `unix7/disk0.hp` |
| `0113` | `sysiii` — Unix System III | `sysiii/disk.hp` |
| `0115` | `sysv` — Unix System V | `sysv/disk.hp` |
| `1000` | `nankervis` — Nankervis multi-OS system | Special |
| `1001` | `idled` — lamp demo (alternate) | — |
| `1002` | `blinky` — pure LED demo | — |

**To boot:** set SR switches → press the **ADDR rotary encoder button**.

**To shut down:** run the OS shutdown command first (RSX: `RUN $SHUTUP`;
2.11BSD/Unix V7: `sync` three times; RT-11: no shutdown needed), then push
HALT and press the ADDR knob. Wait 15 seconds before cutting power.

### How to read the switch setting from the idled display

When `idled` is running, the address LEDs cycle through every available OS (~2 s each),
showing the SR switch value in binary. Count the lit LEDs to find the octal setting
for the OS you want, then set the switches and press the ADDR knob to boot it.

### Booting without physical switches

### Booting without physical switches

To boot a specific OS without touching hardware, set `DEFAULT_BOOT` in the
docker run command:

```bash
docker run -d ... -e DEFAULT_BOOT=211bsd ...
```

Or from the SSH console, halt SimH and let the container loop re-read switches:

```bash
ssh pdp11@<pi-ip> -p 2211
# Inside SimH:
HALT
# Exit SimH (container reads switches and reboots):
EXIT
```

---

## 9 — Update to a newer image

```bash
docker pull ghcr.io/dmz006/pidp11-addon:latest
docker stop pidp11 && docker rm pidp11
# re-run the docker run command from step 3
```

Your disk images live in `/opt/pidp11-share` (bind mount) and your emulator
state in the `pidp11-data` named volume — both survive this process.

---

## 10 — Adding Home Assistant later

If you later want HA sensors and the Lovelace front-panel card, install the
HACS integration from this repo and point it at `127.0.0.1:2223`. The
container exposes the auth-shim on that port whether or not HA is involved.
See the main [README](../README.md) for full HA setup steps.

---

## Troubleshooting

**Lamps don't light up**  
Check `systemctl status rpcbind`. The socket at `/run/rpcbind.sock` must
exist before `docker run`. Also make sure you passed `ENABLE_GPIO=true`.
Restart rpcbind, then restart the container.

**"Exec format error" in docker logs**  
You're trying to run the image on a non-arm64 host (e.g., x86). The image
is arm64-only. Use a Pi 5.

**Permission denied on /dev/gpiomem***  
The `--privileged` flag is required. Without it, the GPIO driver cannot
open the RP1 memory-mapped registers.

**Container exits immediately**  
`docker logs pidp11` will tell you why. Usually a missing socket mount or
a conflicting process already holding the RPC portmapper port.

**SSH connection refused**  
The container binds to port 22 inside the container (mapped to 2211 on the
host via `--network host`). Wait 30 s for dropbear to start, then try again.
Check `docker logs pidp11` for any SSH startup errors.

**211bsd download is slow / fails**  
The 2.11BSD image (~250 MB compressed) downloads from GitHub on first boot.
Check your Pi's internet connection. The download is retried automatically
next time the container boots.

**I had native pidp11 software auto-starting before**  
Disable the XDG autostart that the upstream install script creates, so it
doesn't fight the container for GPIO:

```bash
echo "Hidden=true" >> ~/.config/autostart/pdp11startup.desktop
# and comment out any autostart lines in ~/.profile:
sed -i 's/^pdp11 #/# pdp11 # disabled: using Docker/' ~/.profile
```

**How do I know which OS is currently running?**  
```bash
docker exec pidp11 cat /share/pidp11/current_system
```
