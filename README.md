# PiDP-11 for Home Assistant

Run the [obsolescence/pidp11](https://github.com/obsolescence/pidp11) PDP-11
emulator on a Raspberry Pi that is also running Home Assistant OS, with full
support for the PiDP-11 front-panel hardware (lamps + switches over GPIO),
and surface the running emulator to Home Assistant as entities, services,
and a Lovelace front-panel dashboard.

---

## What ships from this repo

This repo provides **two artifacts in one repo**, because the Home Assistant
ecosystem distributes Python and containers through different channels:

| Artifact                   | Channel              | What it does                                                                                 |
| -------------------------- | -------------------- | -------------------------------------------------------------------------------------------- |
| **`pidp11-addon/`**        | Supervisor add-on    | Docker container running SimH + PiDP-11 GPIO driver + `dropbear` SSH. Needs `/dev/mem`.      |
| **`custom_components/pidp11/`** | HACS            | Python integration exposing HA entities/services that talk to the add-on.                     |

On **HAOS / HA Supervised**, install both (the add-on handles the container,
the integration handles HA wiring). On **HA Container** or **HA Core**, only
the HACS integration is auto-installable; users must run the container
themselves via `docker run` (see `docs/install-container.md`).

## Quick install (HAOS, Pi 5 with PiDP-11 hat)

1. Settings → Add-ons → Add-on Store → ⋮ → **Repositories** → paste this
   repo's URL. Install **PiDP-11 Emulator**.
2. Open add-on **Configuration** → set an SSH password → **Start**.
3. HACS → ⋮ → **Custom repositories** → add this URL, category
   *Integration*. Install **PiDP-11**.
4. Settings → Devices & Services → **Add Integration** → *PiDP-11* →
   point it at the add-on's hostname (defaults fine on HAOS).
5. SSH to `<HA-host>:2211` using the password from step 2. You land in
   a `screen` session attached to the running PDP-11.

## Status

**Pre-alpha, skeleton only.** See `docs/sprints/` for the plan. Nothing
runs yet.

## Docs

- **Architecture**: `docs/architecture.md`
- **Diagrams**: `docs/diagrams.md`
- **Testing strategy**: `docs/testing-strategy.md`
- **Risks & open questions**: `docs/risks.md`
- **Sprint plan**: `docs/sprints/README.md`
- **Roadmap (post-v1)**: `docs/roadmap.md`
- **Agent rules**: `AGENT.md`

## License

MIT. See `LICENSE`. Upstream `obsolescence/pidp11` has MIT-style per-file
headers; see `docs/risks.md` for the license-hygiene note.
