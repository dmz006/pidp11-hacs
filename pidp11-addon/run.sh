#!/usr/bin/env bash
# PiDP-11 add-on launcher — Sprint S1 (emulator MVP, no GPIO).
# GPIO (server11 / scansw) wired up in S4.
set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────────────
BIN_DIR="/opt/pidp11/bin"
SYSTEMS_DIR="/opt/pidp11/systems"
SHARE_DIR="/share/pidp11"
DISKS_DIR="${SHARE_DIR}/disks"
DATA_DIR="/data"
SECRET_FILE="${DATA_DIR}/remote_console.secret"
SHM_DIR="/dev/shm/pidp11"
SIMH="${BIN_DIR}/pdp11_realcons"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[pidp11] $*"; }
die()  { echo "[pidp11] FATAL: $*" >&2; exit 1; }

# ── Read add-on options ───────────────────────────────────────────────────────
# bashio is available in the HA base image; fall back to env/defaults otherwise.
if [ -f /usr/lib/bashio/bashio.sh ]; then
    # shellcheck source=/dev/null
    source /usr/lib/bashio/bashio.sh
    DEFAULT_BOOT=$(bashio::config 'default_boot')
    ENABLE_GPIO=$(bashio::config 'enable_gpio')
else
    DEFAULT_BOOT="${DEFAULT_BOOT:-211bsd}"
    ENABLE_GPIO="${ENABLE_GPIO:-false}"
fi

log "Default boot: ${DEFAULT_BOOT}"
log "GPIO enabled: ${ENABLE_GPIO}"

# ── Initial setup ─────────────────────────────────────────────────────────────
mkdir -p "${SHM_DIR}" "${DISKS_DIR}"

# Generate remote-console shared secret on first start.
if [[ ! -f "${SECRET_FILE}" ]]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "${SECRET_FILE}"
    chmod 600 "${SECRET_FILE}"
    log "Generated remote console secret (${SECRET_FILE})"
fi

# SDL2 is linked into the binary but we never open a display.
export SDL_VIDEODRIVER=offscreen
export SDL_AUDIODRIVER=dummy

# ── 211bsd disk image ─────────────────────────────────────────────────────────
BSD_DSK="${DISKS_DIR}/211bsd/2.11BSD_rq.dsk"
if [[ "${DEFAULT_BOOT}" == "211bsd" ]] && [[ ! -f "${BSD_DSK}" ]]; then
    log "211bsd disk image not found — downloading Chase Covello's 2.11BSD (~250 MB compressed)..."
    mkdir -p "${DISKS_DIR}/211bsd"
    curl -fL --progress-bar \
        -o "${DISKS_DIR}/211bsd/2.11BSD_rq.dsk.xz" \
        "https://github.com/chasecovello/211bsd-pidp11/raw/refs/heads/master/2.11BSD_rq.dsk.xz"
    log "Decompressing disk image..."
    unxz "${DISKS_DIR}/211bsd/2.11BSD_rq.dsk.xz"
    log "211bsd ready at ${BSD_DSK}"
fi

# ── Boot selection ────────────────────────────────────────────────────────────
if [[ "${ENABLE_GPIO}" == "true" ]] && [[ -x "${BIN_DIR}/scansw" ]]; then
    # S4: read SR switches to pick the boot system.
    log "Reading SR switches..."
    sw=$("${BIN_DIR}/scansw" 2>/dev/null || echo "0")
    lo=$(( sw % 262144 ))
    lo=$(printf "%04o" "${lo}")
    SEL=$("${BIN_DIR}/getsel.sh" "${lo}" | sed 's/default/idled/')
    log "SR switches → octal ${lo} → system: ${SEL}"
else
    SEL="${DEFAULT_BOOT}"
fi

# Validate system directory exists.
if [[ ! -d "${SYSTEMS_DIR}/${SEL}" ]]; then
    log "WARNING: system '${SEL}' not found, falling back to idled"
    SEL="idled"
fi

log "Booting: ${SEL}"

# Write SimH startup command file.
cat > "${SHM_DIR}/tmpsimhcommand.txt" <<EOF
cd ${SYSTEMS_DIR}/${SEL}
do boot.ini
EOF

# ── Auth shim ─────────────────────────────────────────────────────────────────
log "Starting auth shim (:2223 → SimH :2224)"
SECRET_FILE="${SECRET_FILE}" python3 "${BIN_DIR}/authshim.py" &
SHIM_PID=$!

cleanup() {
    log "Shutting down..."
    kill "${SHIM_PID}" 2>/dev/null || true
    screen -S pidp11 -X quit 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── SimH in screen ────────────────────────────────────────────────────────────
# Screen session named 'pidp11' so SSH users can attach with: screen -x pidp11
log "Launching SimH in screen session 'pidp11'"
screen -dmS pidp11 "${SIMH}" "${SHM_DIR}/tmpsimhcommand.txt"

# Keep container alive while the screen session lives.
while screen -list pidp11 2>/dev/null | grep -q '\.pidp11'; do
    sleep 5
done

log "SimH exited — container stopping"
