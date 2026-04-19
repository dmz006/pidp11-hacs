# syntax=docker/dockerfile:1.7
# S0 skeleton. The real multi-stage build lands in S1.
ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm
FROM ${BUILD_FROM}

# Placeholder — S1 will:
#   1. install build deps (build-essential libpcap-dev git s6-overlay dropbear screen python3)
#   2. clone obsolescence/pidp11 at the pinned SHA
#   3. make the pdp11 binary + pidp11 GPIO driver
#   4. copy rootfs/ with s6 services
#   5. set ENTRYPOINT to /init (s6-overlay)

COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
