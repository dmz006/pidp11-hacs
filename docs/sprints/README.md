# Sprint index

| # | Title                            | Status  | Exit gate                                                             |
| - | -------------------------------- | ------- | --------------------------------------------------------------------- |
| 0 | Scaffolding & contracts          | planned | skeleton + failing tests for every public surface; HAOS `/dev/mem` spike decided |
| 1 | Add-on emulator MVP (no GPIO)    | planned | container boots on amd64 + aarch64; SimH responds on remote console   |
| 2 | SSH console                      | planned | SSH lands in persistent `screen` session with SimH attached           |
| 3 | HACS integration                 | planned | config flow installs; core sensors/switches/services green           |
| 4 | GPIO + multi-arch release        | planned | lamps & switches work on real Pi 5; v1.0 tag, HACS-installable       |
| 5 | Lamps/switches + Lovelace panel  | planned | front-panel dashboard mirrors physical panel live                     |

## Rules

- A sprint cannot start until the previous one's exit gate is signed
  off in the sprint doc.
- Every sprint opens with a test list and closes with every test
  green and a hardware-checklist entry (if applicable) signed.
- Decisions made mid-sprint get recorded in the sprint doc under
  "Decisions", not lost in chat.

## Dependencies

```
S0 ──► S1 ──► S2 ──► S3 ──► S4 ──► S5
  └── R1 spike (/dev/mem) gates S4
  └── R3 decision (screen -x vs -RR) gates S2
  └── R4 decision (remote console auth) gates S3
```
