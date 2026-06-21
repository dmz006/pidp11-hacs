#!/usr/bin/env bash
# PiDP-11 add-on launcher.
# Mirrors the upstream pidp11.sh loop: after SimH exits, if the front-panel
# triggered a reboot (tmpsimhcommand.txt == "exit"), re-read SR switches and
# boot the newly selected system.  This is how switch-based OS switching works.
set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────────────
BIN_DIR="/opt/pidp11/bin"
SYSTEMS_DIR="/opt/pidp11/systems"
DISKS_DIR="/share/pidp11/disks"
DATA_DIR="/data"
SECRET_FILE="${DATA_DIR}/remote_console.secret"
SHM_DIR="/dev/shm/pidp11"
SIMH="${BIN_DIR}/pdp11_realcons"
SERVER11="${BIN_DIR}/pidp1170_blinkenlightd"

log() { echo "[pidp11] $*"; }
die() { echo "[pidp11] FATAL: $*" >&2; exit 1; }

# ── Read add-on options ───────────────────────────────────────────────────────
# Priority: bashio (HA Supervisor → /data/options.json)
#         > docker -e env vars (s6 stores them in S6_ENV but strips them from CMD)
#         > hardcoded defaults
_S6E=/var/run/s6/container_environment

if [ -f /usr/lib/bashio/bashio.sh ]; then
    # shellcheck source=/dev/null
    source /usr/lib/bashio/bashio.sh
    # Returns empty string when Supervisor API is unreachable (direct docker-run)
    _boot=$(bashio::config 'default_boot'          2>/dev/null || true)
    _gpio=$(bashio::config 'enable_gpio'           2>/dev/null || true)
    _sshpw=$(bashio::config 'ssh_password'         2>/dev/null || true)
    _sshpwd=$(bashio::config 'ssh_password_disabled' 2>/dev/null || true)
    _sshkeys=$(bashio::config 'ssh_authorized_keys' 2>/dev/null || true)
    [[ -n "${_boot}"    ]] && DEFAULT_BOOT="${_boot}"
    [[ -n "${_gpio}"    ]] && ENABLE_GPIO="${_gpio}"
    [[ -n "${_sshpw}"   ]] && SSH_PASSWORD="${_sshpw}"
    [[ -n "${_sshpwd}"  ]] && SSH_PASSWORD_DISABLED="${_sshpwd}"
    [[ -n "${_sshkeys}" ]] && SSH_AUTHORIZED_KEYS="${_sshkeys}"
fi
# s6-overlay strips -e env vars from the CMD process; read them from the env dir
DEFAULT_BOOT="${DEFAULT_BOOT:-$(cat "${_S6E}/DEFAULT_BOOT"          2>/dev/null || true)}"
ENABLE_GPIO="${ENABLE_GPIO:-$(cat "${_S6E}/ENABLE_GPIO"             2>/dev/null || true)}"
SSH_PASSWORD="${SSH_PASSWORD:-$(cat "${_S6E}/SSH_PASSWORD"          2>/dev/null || true)}"
SSH_PASSWORD_DISABLED="${SSH_PASSWORD_DISABLED:-$(cat "${_S6E}/SSH_PASSWORD_DISABLED" 2>/dev/null || true)}"
SSH_AUTHORIZED_KEYS="${SSH_AUTHORIZED_KEYS:-$(cat "${_S6E}/SSH_AUTHORIZED_KEYS"       2>/dev/null || true)}"
# Final hardcoded defaults
DEFAULT_BOOT="${DEFAULT_BOOT:-211bsd}"
ENABLE_GPIO="${ENABLE_GPIO:-false}"
SSH_PASSWORD_DISABLED="${SSH_PASSWORD_DISABLED:-false}"

log "Default boot: ${DEFAULT_BOOT} | GPIO: ${ENABLE_GPIO}"

# ── Initial setup ─────────────────────────────────────────────────────────────
mkdir -p "${SHM_DIR}" "${DISKS_DIR}" /data/ssh /share/pidp11

if [[ ! -f "${SECRET_FILE}" ]]; then
    python3 -c "import secrets; print(secrets.token_hex(32))" > "${SECRET_FILE}"
    chmod 600 "${SECRET_FILE}"
    log "Generated remote console secret"
fi
# Share secret with the HA integration via /share (readable by HA core)
cp "${SECRET_FILE}" /share/pidp11/remote_console.secret 2>/dev/null || true

# SDL stubs — binary links against SDL2 but we never open a display
export SDL_VIDEODRIVER=offscreen
export SDL_AUDIODRIVER=dummy

# ── Disk image helpers ────────────────────────────────────────────────────────
_ensure_211bsd() {
    local dsk="${DISKS_DIR}/211bsd/2.11BSD_rq.dsk"
    [[ -f "${dsk}" ]] && return 0
    log "211bsd disk image not found — downloading Chase Covello's 2.11BSD (~250 MB compressed)"
    mkdir -p "${DISKS_DIR}/211bsd"
    curl -fL --progress-bar \
        -o "${dsk}.xz" \
        "https://github.com/chasecovello/211bsd-pidp11/raw/refs/heads/master/2.11BSD_rq.dsk.xz"
    log "Decompressing..."
    unxz "${dsk}.xz"
    log "211bsd ready at ${dsk}"
}

_check_prestaged() {
    local sys="$1" disk="$2"
    if [[ ! -f "${disk}" ]]; then
        log "WARNING: ${sys} requires disk pre-staged at ${disk}"
        log "  Copy the disk image from your Pi's /opt/pidp11/systems/${sys}/ via SSH/SCP"
        log "  then place it at the path above and restart the add-on."
        return 1
    fi
    return 0
}

# ── SSH console setup ─────────────────────────────────────────────────────────
_setup_ssh() {
    # Host keys — generated once and persisted in /data/ssh/
    if [[ ! -f /data/ssh/dropbear_rsa_host_key ]]; then
        log "Generating SSH host keys"
        dropbearkey -t rsa     -f /data/ssh/dropbear_rsa_host_key    >/dev/null 2>&1
        dropbearkey -t ed25519 -f /data/ssh/dropbear_ed25519_host_key >/dev/null 2>&1
    fi

    # Authorized keys for pdp11 user
    mkdir -p /home/pdp11/.ssh
    chown pdp11:pdp11 /home/pdp11/.ssh
    chmod 700 /home/pdp11/.ssh
    if [[ -n "${SSH_AUTHORIZED_KEYS:-}" ]]; then
        printf '%s\n' "${SSH_AUTHORIZED_KEYS}" > /home/pdp11/.ssh/authorized_keys
        chown pdp11:pdp11 /home/pdp11/.ssh/authorized_keys
        chmod 600 /home/pdp11/.ssh/authorized_keys
        log "SSH: authorized_keys configured"
    fi

    # Password auth
    local db_extra=""
    if [[ "${SSH_PASSWORD_DISABLED}" == "true" ]]; then
        db_extra="-s"
        log "SSH: password auth disabled"
    elif [[ -n "${SSH_PASSWORD:-}" ]]; then
        echo "pdp11:${SSH_PASSWORD}" | chpasswd
        log "SSH: password auth enabled"
    else
        db_extra="-s"
        log "SSH: no password set — password auth disabled (configure ssh_password or ssh_authorized_keys)"
    fi

    if [[ -z "${SSH_PASSWORD:-}" ]] && [[ -z "${SSH_AUTHORIZED_KEYS:-}" ]]; then
        log "SSH: WARNING — no credentials configured; SSH console will reject all logins"
    fi

    log "Starting SSH server (port 22 → 2211)"
    # shellcheck disable=SC2086
    dropbear -F -E -p 22 \
        -r /data/ssh/dropbear_rsa_host_key \
        -r /data/ssh/dropbear_ed25519_host_key \
        -w ${db_extra} &
    DROPBEAR_PID=$!
}

SHIM_PID=""
DROPBEAR_PID=""

cleanup() {
    log "Shutting down..."
    [[ -n "${SHIM_PID}"     ]] && kill "${SHIM_PID}"     2>/dev/null || true
    [[ -n "${DROPBEAR_PID}" ]] && kill "${DROPBEAR_PID}" 2>/dev/null || true
    pkill -x pidp1170_blinkenlightd 2>/dev/null || true
    pkill rpcbind 2>/dev/null || true
    screen -S pidp11 -X quit 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Auth shim — start once, persists across reboots ──────────────────────────
log "Starting auth shim (:2223 → SimH :2224)"
SECRET_FILE="${SECRET_FILE}" python3 "${BIN_DIR}/authshim.py" &
SHIM_PID=$!

_setup_ssh

# ── GPIO: wait for /dev/mem before touching GPIO hardware ────────────────────
# HAOS may not expose /dev/mem immediately on container start; bounded retry.
if [[ "${ENABLE_GPIO}" == "true" ]]; then
    _devmem_retries=10
    until [[ -e /dev/mem ]] || (( --_devmem_retries == 0 )); do
        log "Waiting for /dev/mem... (${_devmem_retries} retries left)"
        sleep 0.5
    done
    if [[ ! -e /dev/mem ]]; then
        log "WARNING: /dev/mem not available after 5 s — disabling GPIO"
        ENABLE_GPIO="false"
    fi
fi

# ── Main boot loop ────────────────────────────────────────────────────────────
# Mirrors upstream pidp11.sh:
#   1. Read SR switches (or use default_boot when GPIO disabled)
#   2. Write SimH command file and launch SimH
#   3. Wait for SimH to exit
#   4. If tmpsimhcommand.txt == "exit" the front panel requested a reboot
#      (user turned SR switches + depressed address rotary) → loop and re-read
#   5. Otherwise SimH exited cleanly → stop container
while true; do

    # ── Select boot system ────────────────────────────────────────────────────
    if [[ "${ENABLE_GPIO}" == "true" ]] && [[ -x "${BIN_DIR}/scansw" ]]; then
        log "Reading SR switches..."
        sw=$("${BIN_DIR}/scansw" 2>/dev/null || echo "0")
        lo=$(( sw % 262144 ))
        lo=$(printf "%04o" "${lo}")
        SEL=$("${BIN_DIR}/getsel.sh" "${lo}" | sed 's/default/idled/')
        log "SR switches → octal ${lo} → system: ${SEL}"
    else
        SEL="${DEFAULT_BOOT}"
    fi

    if [[ ! -d "${SYSTEMS_DIR}/${SEL}" ]]; then
        log "WARNING: system '${SEL}' not found — falling back to idled"
        SEL="idled"
    fi

    # ── Per-system disk checks ────────────────────────────────────────────────
    case "${SEL}" in
        211bsd)
            _ensure_211bsd || { SEL="idled"; log "Falling back to idled"; }
            ;;
        unix7)
            _check_prestaged unix7 "${DISKS_DIR}/unix7/disk0.hp" || SEL="idled"
            ;;
        sysiii)
            _check_prestaged sysiii "${DISKS_DIR}/sysiii/disk.hp" || SEL="idled"
            ;;
        sysv)
            _check_prestaged sysv "${DISKS_DIR}/sysv/disk.hp" || SEL="idled"
            ;;
        rsx11mp)
            _check_prestaged rsx11mp "${DISKS_DIR}/rsx11mp/PiDP11_DU0.dsk" || SEL="idled"
            ;;
        rsx11bq)
            _check_prestaged rsx11bq "${DISKS_DIR}/rsx11bq/pidp.dsk" || SEL="idled"
            ;;
    esac

    log "Booting: ${SEL}"
    echo "${SEL}" > /share/pidp11/current_system

    # ── Generate SimH command file ────────────────────────────────────────────
    # When GPIO is enabled, uncomment 'set realcons' lines at runtime so the
    # same boot.ini files work in both GPIO and container-only modes.
    if [[ "${ENABLE_GPIO}" == "true" ]]; then
        _ini="${SHM_DIR}/gpio_boot.ini"
        if [[ "${SEL}" == "blinky" ]]; then
            # blinky delegates to PDP-11xx.ini — patch that file too
            _pdp11="${SHM_DIR}/gpio_PDP-11xx.ini"
            sed 's/^;set  realcons/set  realcons/;s/^;set realcons test/set realcons test/' \
                "${SYSTEMS_DIR}/blinky/PDP-11xx.ini" > "${_pdp11}"
            # Redirect blinky's boot.ini to use our patched PDP-11xx.ini
            sed "s|do PDP-11xx.ini|do ${_pdp11}|" \
                "${SYSTEMS_DIR}/blinky/boot.ini" > "${_ini}"
        else
            sed 's/^;set realcons/set realcons/' "${SYSTEMS_DIR}/${SEL}/boot.ini" > "${_ini}"
        fi
        printf 'cd %s\ndo %s\n' "${SYSTEMS_DIR}/${SEL}" "${_ini}" > "${SHM_DIR}/tmpsimhcommand.txt"
    else
        printf 'cd %s\ndo boot.ini\n' "${SYSTEMS_DIR}/${SEL}" > "${SHM_DIR}/tmpsimhcommand.txt"
    fi

    # ── GPIO S4: start rpcbind + Blinkenlight server ──────────────────────────
    if [[ "${ENABLE_GPIO}" == "true" ]]; then
        log "Starting rpcbind"
        rpcbind -w &
        sleep 1
        log "Starting Blinkenlight server (server11)"
        "${SERVER11}" &
        sleep 2
    fi

    # ── Launch SimH in detached screen session ────────────────────────────────
    # SSH users attach via:  ssh pdp11@<host> -p 2211
    # ssh_console.sh runs:   sudo screen -x pidp11
    log "Launching SimH in screen session 'pidp11'"
    screen -dmS pidp11 "${SIMH}" "${SHM_DIR}/tmpsimhcommand.txt"

    # Wait for screen/SimH to exit
    while screen -list 2>/dev/null | grep -q '\.pidp11'; do
        sleep 5
    done

    # ── GPIO S4: stop Blinkenlight server before re-reading switches ──────────
    if [[ "${ENABLE_GPIO}" == "true" ]]; then
        pkill -x pidp1170_blinkenlightd 2>/dev/null || true
        sleep 1
    fi

    # ── Check for front-panel reboot request ──────────────────────────────────
    # client11 (SimH + realcons) writes "exit" to tmpsimhcommand.txt when the
    # operator depresses the address rotary switch to trigger a system reboot.
    if [[ "$(cat "${SHM_DIR}/tmpsimhcommand.txt" 2>/dev/null || true)" == "exit" ]]; then
        log "Front-panel reboot request — re-reading SR switches and rebooting"
        continue
    fi

    log "SimH exited — container stopping"
    break

done
