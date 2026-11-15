# Glossary

- **Auth shim** (`pidp11-addon/authshim.py`) — proxy on port 2223 that checks the shared secret, then forwards to SimH's console on 2224. Also serves the SR watch (2225) and lamp (2226) streams. See [remote-console contract](contracts/remote-console.md).
- **Connection budget** — SimH accepts 4 remote-console connections (`set remote connections=4`). The integration holds at most 2: one stream plus one transient poll/command. See [architecture](architecture.md).
- **"All connections busy"** — what SimH sends when the budget is used up. The integration retries with backoff and keeps the last values; see README [Troubleshooting](../README.md#troubleshooting).
- **Lamp stream** — port 2226, `EVENT lamps ADDRESS=… DATA=…` at up to 20 Hz; with `AUTH <secret> +sr` it also carries `EVENT sr value=…`.
- **SR** — switch register, 22 bits, shown as `sensor.pidp_11_switch_register` and `binary_sensor.pidp_11_sr0`–`sr21`.
- **SR watch stream** — port 2225, SR-only, kept for older clients.
- **Heartbeat** — `# keepalive` comment line a stream sends when quiet (`HEARTBEAT_INTERVAL`); clients ignore non-`EVENT` lines.
- **Idle timeout** — `IDLE_TIMEOUT`; closes a proxied console session with no traffic.
- **Entity prefix** — `pidp_11` for the "PiDP-11" device (older installs: `pidp11`); the card resolves either.
- **Card** — `custom:pidp11-panel-card`, the Lovelace front-panel replica. See README [Dashboard Card](../README.md#dashboard-card).
