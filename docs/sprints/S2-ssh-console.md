# Sprint 2 — SSH console

**Owner:** TBD. **Status:** planned.

## Goal

User SSHes to the HAOS host on the configured port, authenticates with
the add-on-configured password (or key), and lands in a GNU `screen`
session that is attached to the running SimH primary console —
indistinguishable from the bare-metal Pi experience.

## Entry criteria

S1 exit gate signed. R3 decision recorded in S0 doc (`screen -x` vs
`-RR`).

## Tasks

1. **`dropbear`** in the image; listener on container `:22`, mapped to
   host `:2211` by default via `ports` in `config.yaml`.
2. **`pdp11-user`** — unprivileged user inside container; login shell
   is a wrapper that `exec`s `screen -x pidp11` (per R3 decision) or
   `screen -RR pidp11` if decision changes.
3. **Password management.**
   - `options.ssh_password` (required; schema `password`).
   - On options change, Supervisor restarts add-on; `run.sh` hashes
     the new password with `yescrypt` and writes
     `/etc/dropbear/authorized_keys` + `/etc/shadow` atomically.
   - Never logged.
4. **Optional key auth.** `options.ssh_authorized_keys` (multiline
   string, optional). If set, dropbear enables key auth and still
   requires password unless `options.ssh_password_disabled: true`.
5. **`screen` persistence.** SimH runs under s6; `screen` is a
   *client* attached/reattached in the wrapper shell, not a server
   process — so SimH survives when no one is attached. `screen`
   session `pidp11` is auto-created by s6 at boot with SimH attached
   as the window content.
6. **Banner.** MOTD shows: "PiDP-11 — SimH running, boot <target>.
   `^A d` to detach, session persists."

## Tests

- [ ] `tests/addon/test_ssh_access.py::test_ssh_accepts_password`
- [ ] `tests/addon/test_ssh_access.py::test_ssh_rejects_bad_password`
- [ ] `tests/addon/test_ssh_access.py::test_ssh_lands_in_screen`
- [ ] `tests/addon/test_ssh_access.py::test_screen_shows_simh_prompt`
- [ ] `tests/addon/test_ssh_access.py::test_detach_preserves_simh`
- [ ] `tests/addon/test_ssh_access.py::test_second_user_shares_screen`
      (per R3 `-x` decision)
- [ ] `tests/addon/test_password_rotation.py::test_restart_applies_new_password`
- [ ] `tests/addon/test_password_rotation.py::test_old_password_rejected_after_rotation`
- [ ] `tests/addon/test_password_rotation.py::test_password_never_in_logs`

## Exit gate

- `ssh pdp11-user@<haos-host> -p 2211` produces the SimH primary
  console.
- Rotating the password via add-on UI works; old password rejected
  within one add-on restart.
- Password never appears in `ha supervisor logs` or
  `ha addons logs pidp11`.
- Tag `v0.2.0`.
