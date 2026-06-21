#!/usr/bin/env bash
# Download PiDP-11 disk images for use with the standalone Docker container.
#
# Usage:
#   ./scripts/get-images.sh [SHARE_DIR]
#
# SHARE_DIR defaults to /opt/pidp11-share (recommended for standalone installs).
# The container should be run with: -v /opt/pidp11-share:/share
#
# What this downloads:
#   - Oscar's systems.tar.gz (rsx11mp, unix7, sysiii, sysv and more)
#   - 211bsd is auto-downloaded by the container on first boot — skip here
#   - rsx11bq (Johnny Bilquist's RSX-11M+) is optional; see prompts below
#
# What is ALREADY bundled in the Docker image (no staging needed):
#   idled, blinky, dos11, rsts7, rt11, unix1, unix5, unix6, 211bsd (auto-dl)

set -euo pipefail

SHARE_DIR="${1:-/opt/pidp11-share}"
DISKS_DIR="${SHARE_DIR}/pidp11/disks"
SYSTEMS_URL="http://obsolescence.dev/pidp11/systems.tar.gz"
BSD_URL="https://github.com/chasecovello/211bsd-pidp11/raw/refs/heads/master/2.11BSD_rq.dsk.xz"
RSX_FTP="ftp://ftp.dfupdate.se/pub/pdp11/rsx/pidp"

echo
echo "PiDP-11 disk image downloader"
echo "=============================="
echo "Share directory: ${SHARE_DIR}"
echo "Disk images go to: ${DISKS_DIR}"
echo

# Create share dir — use sudo only if we need to
if [[ ! -d "${SHARE_DIR}" ]]; then
    if [[ -w "$(dirname "${SHARE_DIR}")" ]]; then
        mkdir -p "${DISKS_DIR}"
    else
        echo "Creating ${SHARE_DIR} (needs sudo)..."
        sudo mkdir -p "${DISKS_DIR}"
        sudo chown -R "$(whoami):$(id -gn)" "${SHARE_DIR}"
    fi
else
    mkdir -p "${DISKS_DIR}"
fi

# ── Oscar's systems tarball (rsx11mp, unix7, sysiii, sysv, ...) ─────────────

echo "Downloading Oscar's systems archive (~200-400 MB)..."
echo "Source: ${SYSTEMS_URL}"
echo

TMP_TAR="$(mktemp -t pidp11-systems-XXXXXX.tar.gz)"
trap "rm -f '${TMP_TAR}' '${TMP_TAR%.gz}'" EXIT

wget --progress=bar:force:noscroll -O "${TMP_TAR}" "${SYSTEMS_URL}" 2>&1 || \
    curl -L --progress-bar -o "${TMP_TAR}" "${SYSTEMS_URL}"

echo "Decompressing..."
gzip -d "${TMP_TAR}"
TMP_UNTAR="${TMP_TAR%.gz}"

# Extract into a temp staging dir, then copy only the disk files we need.
# The tarball unpacks to systems/<name>/ — we want specific disk images.
TMP_STAGE="$(mktemp -d -t pidp11-systems-XXXXXX)"
trap "rm -rf '${TMP_STAGE}'" EXIT

echo "Extracting..."
tar -xf "${TMP_UNTAR}" -C "${TMP_STAGE}"

# Find the systems root in the extracted tree
SYSTEMS_SRC="$(find "${TMP_STAGE}" -maxdepth 2 -type d -name "systems" | head -1)"
if [[ -z "${SYSTEMS_SRC}" ]]; then
    # tarball may extract directly as system subdirs
    SYSTEMS_SRC="${TMP_STAGE}"
fi

_stage_system() {
    local sys="$1"; shift
    local files=("$@")
    local src="${SYSTEMS_SRC}/${sys}"
    local dst="${DISKS_DIR}/${sys}"
    if [[ ! -d "${src}" ]]; then
        echo "  WARNING: ${sys} not found in archive — skipping"
        return
    fi
    mkdir -p "${dst}"
    for f in "${files[@]}"; do
        if [[ -f "${src}/${f}" ]]; then
            echo "  ${sys}/${f}"
            cp "${src}/${f}" "${dst}/${f}"
        else
            echo "  WARNING: ${sys}/${f} not in archive"
        fi
    done
}

echo
echo "Staging disk images:"
_stage_system "rsx11mp"   "PiDP11_DU0.dsk"
_stage_system "unix7"     "disk0.hp"
_stage_system "sysiii"    "disk.hp"
_stage_system "sysv"      "disk.hp"

echo
echo "Oscar's systems staged."

# ── 2.11BSD ─────────────────────────────────────────────────────────────────
# The container auto-downloads this on first boot if missing. You can
# pre-stage it here to avoid the wait.

echo
read -rp "Pre-stage 2.11BSD disk image now? (~250 MB, saves time on first boot) [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
    mkdir -p "${DISKS_DIR}/211bsd"
    echo "Downloading 2.11BSD from Chase Covello's GitHub..."
    wget --progress=bar:force:noscroll \
        -O "${DISKS_DIR}/211bsd/2.11BSD_rq.dsk.xz" "${BSD_URL}" 2>&1 || \
        curl -L --progress-bar \
        -o "${DISKS_DIR}/211bsd/2.11BSD_rq.dsk.xz" "${BSD_URL}"
    echo "Decompressing..."
    unxz "${DISKS_DIR}/211bsd/2.11BSD_rq.dsk.xz"
    echo "2.11BSD staged at ${DISKS_DIR}/211bsd/2.11BSD_rq.dsk"
else
    echo "Skipping 2.11BSD — container will auto-download on first boot."
fi

# ── RSX-11M+ (Johnny Bilquist's updated version) ─────────────────────────────
# Optional: requires anonymous FTP access to dfupdate.se

echo
read -rp "Download Johnny Bilquist's RSX-11M+ (rsx11bq) from dfupdate.se FTP? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
    mkdir -p "${DISKS_DIR}/rsx11bq"
    echo "Leave your email as FTP password (courtesy to the host):"
    read -rp "Email: " ftp_email
    ftp_email="${ftp_email:-anonymous@pidp11}"
    for f in pidp.dsk.gz pidp.tap.gz; do
        echo "Downloading ${f}..."
        wget --user=anonymous --password="${ftp_email}" \
            -O "${DISKS_DIR}/rsx11bq/${f}" "${RSX_FTP}/${f}"
        echo "Decompressing..."
        gunzip -f "${DISKS_DIR}/rsx11bq/${f}"
    done
    echo "RSX-11BQ staged."
else
    echo "Skipping rsx11bq."
fi

# ── Summary ──────────────────────────────────────────────────────────────────

echo
echo "Done. Disk image summary:"
find "${DISKS_DIR}" -name "*.dsk" -o -name "*.hp" -o -name "*.tap" 2>/dev/null | sort | \
    while read -r f; do
        size=$(du -sh "${f}" 2>/dev/null | cut -f1)
        echo "  ${size}  ${f#${SHARE_DIR}/}"
    done

echo
echo "Run the container with:"
echo
echo "  docker run -d --name pidp11 --restart unless-stopped \\"
echo "    --privileged --network host \\"
echo "    -v /run/rpcbind.sock:/run/rpcbind.sock \\"
echo "    -v ${SHARE_DIR}:/share \\"
echo "    -v pidp11-data:/data \\"
echo "    -e ENABLE_GPIO=true \\"
echo "    -e SSH_PASSWORD=pdp11 \\"
echo "    ghcr.io/dmz006/pidp11-addon:latest"
echo
