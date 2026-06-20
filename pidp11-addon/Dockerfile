# syntax=docker/dockerfile:1.7
# Pre-built aarch64 binaries from obsolescence/pidp11 (Dec 2024 build).
# Source build is deferred — see docs/sprints/S1-addon-emulator.md task 1.
ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm
FROM ${BUILD_FROM}

# Runtime deps for pdp11_realcons.
# libsdl2: binary links it; headless via SDL_VIDEODRIVER=offscreen + SDL_AUDIODRIVER=dummy.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libsdl2-2.0-0 \
        libpcap0.8 \
        libreadline8 \
        libtirpc3 \
        screen \
        python3 \
        curl \
        xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Pre-built aarch64 binaries (Dec 2024).
# pidp1170_blinkenlightd and scansw are staged here for S4 (GPIO sprint).
COPY bin/pdp11_realcons         /opt/pidp11/bin/pdp11_realcons
COPY bin/pidp1170_blinkenlightd /opt/pidp11/bin/pidp1170_blinkenlightd
COPY bin/scansw                 /opt/pidp11/bin/scansw
RUN chmod 755 /opt/pidp11/bin/pdp11_realcons \
              /opt/pidp11/bin/pidp1170_blinkenlightd \
              /opt/pidp11/bin/scansw

# Bundled systems.
# idled + blinky: RAM-only, no disk image needed.
# 211bsd: boot.ini only; disk image downloaded to /share/pidp11/disks/ at first start.
COPY systems/ /opt/pidp11/systems/

# Helper scripts
COPY getsel.sh   /opt/pidp11/bin/getsel.sh
COPY authshim.py /opt/pidp11/bin/authshim.py
COPY run.sh      /run.sh
RUN chmod +x /run.sh \
             /opt/pidp11/bin/getsel.sh \
             /opt/pidp11/bin/authshim.py

CMD ["/run.sh"]
