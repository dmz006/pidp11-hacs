# How to debug the integration in Home Assistant

The checks below are in the order to run them while the PiDP-11 integration runs
in a live Home Assistant. Each step says what to look at, what a good result is,
and where to go next if it is not. Placeholders: `<pi-host>` is the machine that
runs the add-on or the Docker container, `<ha-host>` is Home Assistant.

> **Ground rule.** Debugging is read-only. Do not restart Home Assistant, reload,
> delete or reconfigure the live PiDP-11 config entry, or restart the add-on
> container without the operator's approval. Every step below only reads.

## 1. Read the Home Assistant best-practices guide first

If you work through the ha-mcp server (an AI agent or the MCP tools), load its
bundled guide before touching anything: read
`skill://home-assistant-best-practices/SKILL.md` (or call `ha_get_skill_guide`
with no arguments), then only the reference file that matches the step at hand,
for example the safe-refactoring reference before renaming any entity. Use the
`ha_*` tools or the HA UI for every read and change; never edit `.storage/`
files or hand-write `configuration.yaml`.

## 2. The integration entry is loaded

Settings → Devices & services → **PiDP-11**. The entry must show as loaded, with
one device "PiDP-11". With ha-mcp: `ha_get_integration` for domain `pidp11`, and
check `state: loaded`.

| Entry state | Meaning | Next |
|---|---|---|
| `loaded` | Set up and polling. | Step 3. |
| `setup_retry` | The first poll failed (host, port or secret). | Step 4 for the reason, step 6 for the Pi side. |
| `setup_error` / `not_loaded` | Setup raised, or the entry is disabled. | Step 4. |
| missing | The integration was never added. | README → *Adding the device in Home Assistant*. |

## 3. Entity ids and their states

The device is named "PiDP-11", which Home Assistant slugs to `pidp_11`, so every
entity id starts with `pidp_11_`. Developer Tools → States, filter `pidp_11`
(or `ha_search` / `ha_get_state`):

| Entity | Healthy state |
|---|---|
| `sensor.pidp_11_cpu_state` | `running` or `halted` (`offline` = no answer from SimH) |
| `sensor.pidp_11_pc` | octal program counter, changes while running |
| `sensor.pidp_11_psw` | octal PSW |
| `sensor.pidp_11_system` | booted OS, e.g. `211bsd`, `idled`. Read off the event loop; from `/share/pidp11/current_system` on the same machine, otherwise asked of the add-on (`AUTH <secret> +system` → `SYSTEM <name>`). Stuck on a stale value with a remote add-on: check the add-on is current (step 4) |
| `sensor.pidp_11_cpu_mode` | `kernel` / `supervisor` / `user` |
| `sensor.pidp_11_switch_register` | octal, attributes `SR0`–`SR21` |
| `binary_sensor.pidp_11_cpu_halted` | `on` only when halted |
| `binary_sensor.pidp_11_sr0` … `binary_sensor.pidp_11_sr21` | follow the front-panel switches within about 250 ms |

- All `unavailable`: the coordinator has never had a good poll. Go to step 4.
- Values present but frozen: polls fail and the last values are kept (this is
  what happens while SimH is busy). Go to step 4, then step 6.
- Ids end in `_2`, or start with `pidp11_`: an old or duplicate device. The card
  falls back to those, but automations need the real ids. Fix the names through
  the entity registry (UI or `ha_set_entity`), after reading the safe-refactoring
  reference from step 1.

## 4. The log: `PiDP-11 error: 0 bytes read`

Settings → System → Logs, filter `pidp11` (or `ha_get_logs`). The lines to know:

| Log line | Meaning |
|---|---|
| `PiDP-11 error: 0 bytes read on a total of N expected bytes` | The TCP connection opened, then the other end closed it before sending a line. The shim hung up straight away: it could not get a SimH connection (all 4 busy, or SimH not listening yet during boot), or the add-on is restarting. Not a secret problem — a wrong secret gives `DENY bad-auth`. |
| `All connections busy; keeping the last values until a connection is free` | SimH's 4 connections are used up. One warning per outage; the poll retries with backoff. Step 6. |
| `PiDP-11 connection timed out` | Nothing answered within 5 s: wrong host, port, firewall, or the container is down. Step 6. |
| `invalid_auth` / `DENY bad-auth` | Wrong shared secret. README → *Changing the shared secret later*. |

Turn on debug logging for a short time from the integration's page
(⋮ → Enable debug logging) to see `Stream connected on port 2226` and each
reconnect; turn it off again afterwards, which offers the log file for download.

## 5. Dashboard card: config, script URL, browser cache

1. **Card config.** Edit the card in YAML. It must be
   `type: custom:pidp11-panel-card`; entity overrides, if any, must be
   `pidp_11_*` ids from step 3. With ha-mcp: `ha_config_get_dashboard`.
2. **Served script.** The integration serves the card itself (no Lovelace
   resource needed) at

   ```
   http://<ha-host>:8123/pidp11-hacs/pidp11-panel-card.js
   ```

   Open that URL in the same browser. It must return JavaScript, and its content
   should match `custom_components/pidp11/www/pidp11-panel-card.js` of the
   installed release. A 404 means the integration entry is not loaded (step 2).
   Do not also add it as a dashboard resource; a second copy from HACS's
   `/hacsfiles/` path can load an older version first.
3. **Browser cache.** The path is served without cache headers, but the HA
   frontend and the companion app still cache aggressively. Hard refresh the tab
   (Ctrl+Shift+R, or Cmd+Shift+R on a Mac); in the companion app use Settings →
   Companion app → Debugging → Reset frontend cache. Then check the browser
   console for `pidp11-panel-card` errors.

## 6. On the Pi: container logs and connection counts

Container logs (Docker install; for the add-on use Settings → Add-ons → PiDP-11 → Log):

```sh
sudo docker logs --tail 200 pidp11
```

Look for `Starting auth shim (:2223 → SimH :2224)`, SimH boot output, and shim
lines about `All connections busy` or closed clients.

Connection counts, from the host (or inside the container with
`sudo docker exec pidp11 ss -tn`):

```sh
# Clients of the shim (Home Assistant, console users), port 2223 and the lamp stream 2226
sudo ss -tn state established '( sport = :2223 or sport = :2226 )'
# The shim's own connections into SimH, port 2224 (internal to the container)
sudo docker exec pidp11 ss -tn state established '( dport = :2224 )'
```

Expected numbers with Home Assistant connected and nobody on a console:

| Port | Expected | Notes |
|---|---|---|
| 2226 | 1 | The integration's long-lived stream (lamps + switches). |
| 2223 | 0, sometimes 1 | The 5 s poll or a service command, open for a moment. |
| 2224 | 1, sometimes 2 | One per shim client above. |

Each console user adds one on 2223 and one on 2224. The limit on 2224 is 4.
**`All connections busy`** is SimH's answer to a fifth connection: it accepts the
TCP connection, writes that text and hangs up, which the integration sees as
step 4's busy warning or `0 bytes read`. If 2224 shows 4 while 2223/2226 show
fewer clients, connections are leaking; if 2226 shows more than 1 from the
Home Assistant address, an old stream was not closed (for example a second
config entry pointing at the same Pi). Report the counts rather than killing
connections or restarting the container.

## 7. Card error: `setConfig is not a function`

The card shows a red box "i.setConfig is not a function" (or "Custom element
doesn't exist"). Lovelace creates the card with `document.createElement` and then
calls `setConfig`. That only works when the script defines a real custom element:
a class that `extends HTMLElement` and calls `super()`. An older card script that
registered a plain constructor function produced an element with no `setConfig`.
The current script uses a proper class, so the error means the browser is still
running an old copy: confirm the served script from step 5 is the current one,
remove any duplicate dashboard resource for the card, then hard refresh.

## 8. Telling an unrelated shell core dump apart

A core dump on the Pi is not automatically the emulator. List them:

```sh
coredumpctl list
coredumpctl info <PID>
```

Look at the `Executable` and `Command Line` fields. `pdp11`, `blinkenlightd` or
`python3 … authshim.py` inside the container's cgroup are ours. A `bash`, `sh`,
`zsh` or `screen` dump from a login shell, with a time that does not match a gap
in the container log or a jump in `sensor.pidp_11_cpu_state` to `offline`, is
unrelated to the integration and can be set aside.

## 9. After a fix: what to update

1. Ship the fix as a new HACS release (tag, then GitHub Release; see AGENT.md).
2. Update through HACS on the Home Assistant side. A Python change needs a Home
   Assistant restart to load — **ask the operator** before restarting; never
   restart it, reload or reconfigure the live entry on your own.
3. Clear the browser cache (hard refresh, or reset the frontend cache in the
   companion app) so the new card script is used.
4. Re-run steps 2, 3, 5 and 6 to confirm.
