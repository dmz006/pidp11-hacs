# syntax=docker/dockerfile:1.7
# Multi-stage build — compiles SimH + blinkenlightd from source.
#
# Upstream: https://github.com/obsolescence/pidp11
# Pinned SHA: b814664dc8b35203bd1052949eaaa969bfff74e2 (Dec 2024)
#
# Build (requires arm64 platform — use docker buildx on x86_64 with QEMU,
# or build natively on the Pi):
#   docker buildx build --platform linux/arm64 -t pidp11-addon .

ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm

# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM ${BUILD_FROM} AS builder

ARG PIDP11_SHA=b814664dc8b35203bd1052949eaaa969bfff74e2

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        libpcap-dev \
        libreadline-dev \
        libtirpc-dev \
        rpcbind \
        python3 \
        file \
 && rm -rf /var/lib/apt/lists/*

# Intentionally no libsdl2-dev — see patch_quickmake.py for why.

WORKDIR /build
RUN git clone --depth 1 https://github.com/obsolescence/pidp11.git . \
 && git fetch --depth 1 origin "${PIDP11_SHA}" \
 && git checkout "${PIDP11_SHA}"

# Patch quickmake to remove VT11 vector-display renderer (not needed headless).
# See patch_quickmake.py for the full explanation.
COPY patch_quickmake.py /tmp/patch_quickmake.py
RUN cd src/02.3_simh/4.x+realcons/src \
 && python3 /tmp/patch_quickmake.py \
 && make -f quickmake VIDEO_CCDEFS="" VIDEO_LDFLAGS="" DISPLAY_OPT=""

# Build pidp1170_blinkenlightd + scansw (GPIO/lamp server, activated in S4)
# scansw Makefile uses $(CC) which can default to a 32-bit ARM cross-compiler
# on some builder environments; force the native aarch64 compiler explicitly.
# scansw.c already supports Pi 5 via pinctrl/gpiochip_rp1.c — no source changes needed.
RUN cd src/11_pidp_server/scanswitch \
 && make CC=gcc \
 && cd ../pidp11 \
 && MAKE_TARGET_ARCH=RPI make pidp1170_blinkenlightd

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM ${BUILD_FROM}

# Runtime deps — no SDL2 since the builder compiled without it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpcap0.8 \
        libreadline8 \
        libtirpc3 \
        netbase \
        bsdmainutils \
        dropbear \
        rpcbind \
        sudo \
        screen \
        python3 \
        curl \
        xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Binaries from builder
COPY --from=builder \
    /build/src/02.3_simh/4.x+realcons/bin-rpi/pdp11_realcons \
    /opt/pidp11/bin/pdp11_realcons
COPY --from=builder \
    /build/src/11_pidp_server/pidp11/bin-rpi/pidp1170_blinkenlightd \
    /opt/pidp11/bin/pidp1170_blinkenlightd
COPY --from=builder \
    /build/src/11_pidp_server/scanswitch/scansw \
    /opt/pidp11/bin/scansw
RUN chmod 755 /opt/pidp11/bin/pdp11_realcons \
              /opt/pidp11/bin/pidp1170_blinkenlightd \
              /opt/pidp11/bin/scansw

# Bundled systems: idled + blinky (RAM-only); 211bsd boot.ini only (disk downloaded at runtime).
COPY systems/ /opt/pidp11/systems/

# Scripts
COPY getsel.sh       /opt/pidp11/bin/getsel.sh
COPY authshim.py     /opt/pidp11/bin/authshim.py
COPY ssh_console.sh  /opt/pidp11/bin/ssh_console.sh
COPY run.sh          /run.sh
RUN chmod +x /run.sh \
             /opt/pidp11/bin/getsel.sh \
             /opt/pidp11/bin/authshim.py \
             /opt/pidp11/bin/ssh_console.sh \
 && useradd -ms /opt/pidp11/bin/ssh_console.sh pdp11 \
 && echo '/opt/pidp11/bin/ssh_console.sh' >> /etc/shells \
 && echo 'pdp11 ALL=(root) NOPASSWD: /usr/bin/screen -x pidp11' \
        > /etc/sudoers.d/pidp11-ssh \
 && chmod 440 /etc/sudoers.d/pidp11-ssh

CMD ["/run.sh"]
