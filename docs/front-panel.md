# PiDP-11 Front Panel Guide

Reference for operating the physical PiDP-11 front panel — booting operating systems,
using the switches and knobs, and shutting down safely.

This applies whether you're running the add-on under Home Assistant or the
[standalone Docker container](./standalone-docker.md).

---

## OS selection — SR switch table

Set the SR switches to the octal number for the OS you want, then boot
(see [boot sequence](#boot-sequence) below).
The SR switches are grouped in colored blocks of three — each block is one octal digit.

| SR (octal) | Category | System | Disk required |
|-----------|----------|--------|---------------|
| `0001` | DEC | `rsx11mplus` — RSX-11M+ | `rsx11mp/PiDP11_DU0.dsk` |
| `0002` | DEC | `rsts7` — RSTS/E v7.0 | Bundled |
| `0003` | DEC | `rt11` — RT-11 | Bundled |
| `0004` | DEC | `dos11` — DOS-11 | Bundled |
| `0005` | DEC | `ias` — IAS | Bundled |
| `0102` | Unix | `211bsd` — 2.11BSD | Auto-downloaded on first boot |
| `0105` | Unix | `unix5` — Unix V5 | Bundled |
| `0106` | Unix | `unix6` — Unix V6 | Bundled |
| `0107` | Unix | `unix7` — Unix V7 | `unix7/disk0.hp` |
| `0113` | Unix | `sysiii` — Unix System III | `sysiii/disk.hp` |
| `0115` | Unix | `sysv` — Unix System V | `sysv/disk.hp` |
| `1000` | Nankervis | `nankervis` — multi-OS Nankervis system | Special |
| `1001` | Demo | `idled` — lamp demo (alternate) | — |
| `1002` | Demo | `blinky` — pure LED demo | — |
| `0000` | Demo | `idled` — lamp demo (default) | — |

**Bundled** — image is inside the Docker container, no staging needed.  
**Auto-downloaded** — the container fetches it on first boot (2.11BSD only).  
**Staged images** — see [staging disk images](./standalone-docker.md#7--staging-optional-disk-images).

When all SR switches are down (`0000`), the system boots into `idled` by default.
The `idled` program cycles through every available OS entry on the address LEDs (~2 s each),
showing the SR switch value in binary — useful for finding the right switch setting.

---

## Boot sequence

**To boot into a specific OS:**

1. Set the SR switches to the octal value from the table above.
2. **Press the ADDR rotary encoder center button** (the knob on the left side of the
   address LEDs — this is the `LOAD ADDRESS` switch on the real PDP-11/70).
3. The running OS halts, SimH exits, and the container reads the SR switches and
   boots the selected OS.

---

## Front panel controls

### Halt and continue

1. Flip the **ENABLE/HALT** toggle to **HALT** — the CPU stops at the next instruction,
   the RUN lamp goes dark.
2. To resume: flip back to **ENABLE**, then toggle **CONT** — the CPU resumes and the
   RUN lamp lights up.

### Single-step execution

1. Flip **ENABLE/HALT** to **HALT**.
2. Toggle **CONT** once per instruction — each toggle executes one instruction.
3. Watch the ADDRESS and DATA lamps change with each step.
4. To return to full speed: flip to **ENABLE** and toggle **CONT**.

### Examine a memory address or register

CPU must be halted.

1. Set the SR switches to the address you want to inspect (in octal).
2. Toggle **LOAD ADRS** — the ADDRESS LEDs mirror your SR switches.
3. Toggle **EXAM** — the value at that address appears on the DATA LEDs.
4. Toggle **EXAM** again to step to the next address automatically.

**CPU registers** are at special addresses at the top of memory:
R0 = `01777700`, R1 = `01777701`, and so on.

### Deposit (write) to a memory address

CPU must be halted.

1. Set the SR switches to the **address** to write.
2. Toggle **LOAD ADRS** — ADDRESS LEDs confirm the address.
3. Set the SR switches to the **data value** to write.
4. Toggle **DEP** — the value is written; the address auto-increments for the next word.

### Start a program from a known address

1. Set the SR switches to the **starting address** of the program.
2. Toggle **LOAD ADRS** — ADDRESS LEDs confirm the address.
3. Toggle **START** — the CPU executes from that address.

---

## Shutting down

> **Important:** Always shut down the OS running inside the PDP-11 before cutting power,
> just as you would on a real PDP-11.

### Step 1 — shut down the OS

| OS | Shutdown command |
|----|-----------------|
| **RSX-11M+** | `RUN $SHUTUP` at the MCR prompt |
| **2.11BSD** | Type `sync` three times, then wait |
| **Unix V7** | Type `sync` three times, then wait |
| **Unix V5 / V6** | Type `sync` three times (or `haltsys`) |
| **Unix System III / System V** | `shutdown -h` or `sync` three times |
| **RSTS/E** | `SHUTUP` at the KMON prompt |
| **RT-11** | No shutdown needed — safe to halt at any time |
| **DOS-11 / IAS** | Halt at any time — no graceful shutdown required |

### Step 2 — halt and power off

Once the OS is down:

1. **Push the HALT switch down** to halt the CPU.
2. **Depress the ADDRESS rotary knob** — this tells the PiDP-11 software to exit cleanly.
3. **Wait 15 seconds** before cutting power to allow the Pi to finish writing.

---

## Without physical hardware

If you're running headless (no PiDP-11 hat), use the `DEFAULT_BOOT` environment variable
to select an OS at startup:

```bash
docker run -d ... -e DEFAULT_BOOT=211bsd ...
```

Or SSH into the container and change OS from the SimH console:

```bash
ssh pdp11@<pi-ip> -p 2211
# In SimH, halt and exit to let the container reboot with current SR switches:
HALT
EXIT
```

---

## Further reading

- [PiDP-11 Manual](https://obsolescence.dev/pidp11/PiDP-11_Manual.pdf) — Chapter "Using the PiDP-11" (pp. 12–15)
- [PDP-11/70 front panel deep dive](https://www.pdp-11.nl/pdp11-70startpage.html)
- [PDP-11/70 Processor Handbook, Chapter 11](https://bitsavers.trailing-edge.com/pdf/dec/pdp11/1170/PDP-11_70_Handbook_1977-78.pdf)
- [Front panel programming step-by-step](http://www.retrocmp.com/attachments/article/146/consoleserialport.blinkenlight_instructions.txt)
