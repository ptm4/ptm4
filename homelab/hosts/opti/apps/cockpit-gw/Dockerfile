FROM ubuntu:24.04
ARG COCKPIT_VERSION=362-1~bpo24.04.1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    cockpit-ws=${COCKPIT_VERSION} openssh-client python3 ca-certificates \
 && test "$(dpkg-query -W -f='${Version}' cockpit-ws)" = "$COCKPIT_VERSION" \
 && rm -rf /var/lib/apt/lists/*
COPY supervisor.py health.py /opt/cockpit-gw/
ENTRYPOINT ["python3", "/opt/cockpit-gw/supervisor.py"]
HEALTHCHECK --interval=15s --timeout=6s --start-period=30s --retries=2 CMD ["python3", "/opt/cockpit-gw/health.py"]
