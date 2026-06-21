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
  are not supported for lamps, but the emulator itself will run headless)
- **Raspberry Pi OS 64-bit (Bookworm)** — or any Debian arm64 system with
  Docker
- **The PiDP-11 hat** — for physical lamps and switches (optional; the
  emulator boots fine without hardware)
- Docker and rpcbind installed (one-liners below)

---

## 1 — Install Docker

If you don't have Docker yet:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# log out and back in so group membership takes effect
```

## 2 — Enable rpcbind (required for GPIO lamps)

The GPIO driver communicates with SimH via ONC RPC. `rpcbind` must be
running and its socket must exist at `/run/rpcbind.sock` before the
container starts:

```bash
sudo apt-get install -y rpcbind
sudo systemctl enable --now rpcbind
```

If you skip this step the emulator still runs but the physical lamps on the
PiDP-11 hat will not light up.

---

## 3 — Pull and run

```bash
docker run -d \
  --name pidp11 \
  --restart unless-stopped \
  --privileged \
  --network host \
  -v /run/rpcbind.sock:/run/rpcbind.sock \
  -v "$HOME/.pidp11/share:/share" \
  -v pidp11-data:/data \
  -e SSH_PASSWORD=pdp11 \
  ghcr.io/dmz006/pidp11-addon:latest
```

Replace `pdp11` with a real password — this is what you type to SSH into
the console.

What each flag does:

| Flag | Why |
|------|-----|
| `--privileged` | Required for `/dev/gpiomem*` access (RP1 GPIO) |
| `--network host` | Lets ONC RPC bind to the standard portmapper port |
| `/run/rpcbind.sock` | Shares the host rpcbind socket so the GPIO driver can register |
| `/share` | Persistent storage for disk images (survives container updates) |
| `pidp11-data` | Named volume for emulator state, logs, config |
| `SSH_PASSWORD` | Sets the `pdp11` user's SSH password for console access |
| `--restart unless-stopped` | Container comes back after a reboot; stays down if you `docker stop` it |

The image is built for **linux/arm64** only. It will not run on x86.

---

## 4 — Watch it start

```bash
docker logs -f pidp11
```

Within ~30 seconds you should see:

```
[pidp11] Starting rpcbind shim
[pidp11] Starting pidp1170_blinkenlightd
[pidp11] Starting SimH PDP-11/70
```

The physical lamps should begin their idle animation. If they don't, check
that rpcbind is running (`systemctl status rpcbind`) and that
`/run/rpcbind.sock` exists.

---

## 5 — SSH to the PDP-11 console

```bash
ssh pdp11@localhost -p 2211
# or from another machine:
ssh pdp11@<your-pi-ip> -p 2211
```

You land in SimH's interactive console. Some things to try:

```
EXAMINE PC          ; where is the program counter?
HALT                ; stop the CPU (watch the RUN lamp go dark)
CONTINUE            ; resume (watch it light up again)
BOOT DU0            ; boot from disk unit 0 (if you have a disk image)
```

Type `Ctrl-A d` to detach from the screen session without stopping SimH.

---

## 6 — Boot a different OS

Drop disk images in `~/.pidp11/share/disks/<os-name>/` and flip the SR
switches before the next boot. The boot-select encoder maps switch patterns
(octal) to system names — the same mapping used by the HAOS add-on:

| SR octal | System |
|----------|--------|
| `0000` | default (idled animation) |
| `0001` | RSX-11M+ |
| `0101` | UNIX v1 |
| `0102` | 2.11BSD (downloads ~250 MB on first boot) |

See `pidp11-addon/systems/selections` in the repo for the full mapping.

---

## 7 — Stop and update

```bash
docker stop pidp11
docker rm pidp11
docker pull ghcr.io/dmz006/pidp11-addon:latest
# re-run step 3
```

Your disk images and state live in `~/.pidp11/share` (bind-mount) and the
`pidp11-data` named volume — they survive this process.

---

## Adding Home Assistant later

If you later want HA sensors and the Lovelace front-panel card, install the
HACS integration from this repo and point it at `127.0.0.1:2223`. The
container exposes the auth-shim on that port whether or not HA is involved.
See the main [README](../README.md) for full HA setup steps.

---

## Troubleshooting

**Lamps don't light up**  
Check `systemctl status rpcbind`. The socket at `/run/rpcbind.sock` must
exist before `docker run`. Restart rpcbind, then restart the container.

**Permission denied on /dev/gpiomem***  
The `--privileged` flag is required. Without it, the GPIO driver cannot
open the RP1 memory-mapped registers.

**Container exits immediately**  
`docker logs pidp11` will tell you why. Usually a missing socket mount or
a conflicting process already using the RPC portmapper.

**SSH connection refused**  
The container binds to port 2211 on all interfaces (`--network host`).
Wait 30 s for dropbear to start, then try again.

**I had native pidp11 software auto-starting before**  
Disable the XDG autostart that upstream uses so it doesn't fight the
container for GPIO:

```bash
echo "Hidden=true" >> ~/.config/autostart/pdp11startup.desktop
```

And comment out any `pdp11` line from `~/.profile`.
