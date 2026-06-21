# PiDP-11 Front Panel Guide

Reference for operating the physical PiDP-11 front panel — booting operating systems,
using the switches and knobs, and shutting down safely.

This applies whether you're running the add-on under Home Assistant or the
[standalone Docker container](./standalone-docker.md).

For more detail, see the [PiDP-11 how-to page](https://obsolescence.wixsite.com/obsolescence/pidp-11-how-to-use)
and the [PiDP-11 Manual](https://obsolescence.dev/pidp11/PiDP-11_Manual.pdf) (pp. 12–15).

---

## Panel layout

The PiDP-11 front panel reproduces the PDP-11/70 layout:

- **SR switches** (22 toggles across the bottom) — set octal numbers for address/data/OS selection
- **Toggle switches** (middle row, left to right): `LOAD ADRS`, `EXAM`, `DEP`, `CONT`, `HALT`,
  `S INST` (single instruction), `START`
- **Two rotary encoders on the right side of the panel** — one above the ADDRESS LED row,
  one above the DATA LED row. Press the rotary encoder (click it in) to activate its hidden
  function. The DATA knob selects the LED display source (DATA PATHS or DISPLAY REGISTER).
- **ADDRESS LEDs** (top row, 22 LEDs) — shows program counter or bus address
- **DATA LEDs** (bottom row, 16 LEDs) — shows data at the current address
- **RUN lamp** — amber when CPU is running, dark when halted

> **ADDR rotary encoder — two behaviors depending on HALT switch position:**
> - **HALT up (ENABLE)**: pressing the ADDR knob signals SimH to exit and restart into
>   the OS selected by the current SR switches (hidden function, not on real PDP-11/70).
> - **HALT down (HALT)**: pressing the ADDR knob cleanly shuts down the Pi.
>   Wait 30 seconds before removing power.

---

## OS selection — SR switch table

Set the SR switches to the octal number for the OS you want, then boot
(see [boot sequence](#boot-sequence) below).
The SR switches are grouped in colored blocks of three — each block is one octal digit.

| SR (octal) | Category | System | Disk required |
|-----------|----------|--------|---------------|
| `0000` | Demo | `idled` — lamp demo (default, all switches down) | — |
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

**Bundled** — image is inside the Docker container, no staging needed.  
**Auto-downloaded** — the container fetches it on first boot (2.11BSD only).  
**Staged images** — see [staging disk images](./standalone-docker.md#7--staging-optional-disk-images).

### Reading the switch setting from the idled display

With all SR switches down (`0000`) the system boots `idled` by default —
a 64-instruction PDP-11 "poem" by Mike Hill that keeps the front panel lights busy.

While `idled` is running the ADDRESS LEDs cycle through every available OS entry
(~2 s each), displaying the SR switch value in binary (MSB left). Read the lit LEDs
to find the octal value for the OS you want, set the switches, then press the
ADDR rotary encoder to boot it.

**`idled` SR switch controls** (set while `idled` is running, before booting):

| SR bits | Effect |
|---------|--------|
| SR 5–0 | Control the LED update speed on the DATA display |
| SR 7 | When ON, also increments the ADDRESS display LEDs |

**DATA knob** (right side of panel, above DATA LEDs): rotate to **DATA PATHS** or
**DISPLAY REGISTER** to switch between two different LED animation modes.

---

## Boot sequence

1. Make sure the **HALT toggle is up (ENABLE position)**.
2. Set the SR switches to the octal value from the table above.
3. **Press the ADDR rotary encoder** (right side of panel, above ADDRESS LEDs) — SimH
   exits and the container restarts into the OS selected by the SR switches.
4. The running OS halts, SimH exits, and the container reads the SR switches and
   boots the selected OS.

---

## Front panel controls

### Halt and continue

1. Flip the **HALT** toggle to the **HALT** position — the CPU stops at the next
   instruction and the RUN lamp goes dark.
2. To resume: flip back to **ENABLE**, then toggle **CONT** — the CPU resumes and
   the RUN lamp lights up.

### Single-step execution

1. Flip **HALT** to **HALT** to stop the CPU.
2. Toggle **CONT** once per instruction — each toggle executes one instruction.
3. Watch the ADDRESS and DATA LEDs change with each step.
4. To return to full speed: flip to **ENABLE** and toggle **CONT**.

### Examine a memory address or register

CPU must be halted.

1. Set the SR switches to the address you want to inspect (in octal).
2. Toggle **LOAD ADRS** — the ADDRESS LEDs mirror your SR switches, confirming
   the address is loaded into the bus address register.
3. Toggle **EXAM** — the value at that address appears on the DATA LEDs.
4. Toggle **EXAM** again to step to the next address automatically.

**CPU registers** are at special addresses at the top of memory:
R0 = `01777700`, R1 = `01777701`, and so on (each register at the next octal address).

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

> **Important:** Always shut down the OS cleanly before halting, just as you would
> on a real PDP-11. Do not just pull the power — the Pi needs 15 seconds to finish
> writing to the SD card.

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

1. **Flip the HALT toggle to HALT** to stop the CPU.
2. **Press the ADDR rotary encoder** (right side of panel) — with HALT down, this tells
   the PiDP-11 software to exit cleanly rather than reboot.
3. **Wait 30 seconds** before cutting power to let the Pi finish writing to the SD card.

---

## SimH console (SSH)

SSH into the container (port 2211 in standalone mode) to reach the SimH command line:

```bash
ssh pdp11@<pi-ip> -p 2211
```

Useful SimH commands:

| Command | Effect |
|---------|--------|
| `HALT` | Stop the CPU |
| `CONT` | Resume the CPU |
| `EXAMINE <addr>` | Read memory at address (octal) |
| `DEPOSIT <addr> <value>` | Write value to address |
| `GO <addr>` | Start execution from address |
| `EXIT` | Exit SimH (container will restart and re-read SR switches) |
| `RESET ALL` | Reset all devices |

These correspond directly to the physical front panel switches.

---

## Without physical hardware

Use `DEFAULT_BOOT` to select an OS at container startup without touching switches:

```bash
docker run -d ... -e DEFAULT_BOOT=211bsd ...
```

Or from the SimH SSH console:

```bash
HALT
EXIT    # container restarts, reads SR switches (or DEFAULT_BOOT)
```

---

## Hardware test checklist (first power-on)

After assembly, verify each switch and LED row works before normal use.
Boot into `idled` (all SR switches down) so the lamps are active.

1. **HALT switch** — flip down; the machine should stop (RUN lamp goes dark).
2. **HALT switch** — flip back up to ENABLE.
3. **CONT switch** — toggle; the lamps should start moving again.
4. **HALT switch** — flip down again.
5. **DEP switch** — with all SR switches down and the ADDR rotary dial in the CONSULT
   position, toggle DEP; the bottom DATA LED row should light up.
6. **LOAD ADRS switch** — toggle it; the SR switch values should appear on the
   ADDRESS LED row (top row). With all switches down = all dark.
7. **Each SR switch individually** — lift SR switch 0 (rightmost), toggle LOAD ADRS;
   LED 0 in the ADDRESS row should light. Lower it, raise SR switch 1, repeat.
   Work through all 22 SR switches to confirm each one drives the right LED.
8. **TEST LAMP (white switch)** — clear all SR switches, then lift the white switch;
   every single lamp on the panel should light up. This confirms the LED board is good.
9. **ADDR rotary encoder press (HALT up = reboot)** — confirm HALT is up (ENABLE),
   press the ADDR knob; the system should restart into whichever OS the SR switches
   select (all down = `idled` = effectively a reset).
10. **ADDR rotary encoder press (HALT down = shutdown)** — flip HALT down, press the
    ADDR knob; the Pi shuts down cleanly. Wait 30 seconds, then power off.

---

## Further reading

- [PiDP-11 how-to page](https://obsolescence.wixsite.com/obsolescence/pidp-11-how-to-use)
- [PiDP-11 Manual](https://obsolescence.dev/pidp11/PiDP-11_Manual.pdf) — "Using the PiDP-11" (pp. 12–15)
- [PDP-11/70 front panel deep dive](https://www.pdp-11.nl/pdp11-70startpage.html)
- [PDP-11/70 Processor Handbook, Chapter 11](https://bitsavers.trailing-edge.com/pdf/dec/pdp11/1170/PDP-11_70_Handbook_1977-78.pdf)
- [Front panel programming step-by-step](http://www.retrocmp.com/attachments/article/146/consoleserialport.blinkenlight_instructions.txt)
- [idled boot.ini source](https://github.com/obsolescence/pidp11) — in `systems/idled/boot.ini`; the comments
  show PDP-11 addressing modes, programming techniques, and alternate LED patterns
