FROM debian:bookworm
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential debhelper dh-python gettext zlib1g-dev libkrb5-dev libxslt1-dev \
    libglib2.0-dev libgnutls28-dev libsystemd-dev libpolkit-agent-1-dev libjson-glib-dev \
    libpam0g-dev pkgconf systemd xsltproc xmlto docbook-xsl glib-networking python3 \
    python3-pip python3-setuptools python3-wheel openssh-client procps \
    python3-pytest-asyncio python3-pytest-timeout curl ca-certificates xz-utils dpkg-dev
WORKDIR /build
RUN curl -fsSLO https://deb.debian.org/debian/pool/main/c/cockpit/cockpit_337.orig.tar.xz \
 && curl -fsSLO https://deb.debian.org/debian/pool/main/c/cockpit/cockpit_337-1+deb13u2.debian.tar.xz \
 && echo 'df51ef5920fae69e1b435f657376aa93772c0c1720b954a3bac10ebba26bfedf  cockpit_337.orig.tar.xz' | sha256sum -c - \
 && echo 'c5fc9d0f56a16d5af3fb6ecd556d174664fbd7f5abe26d470bb4d7f147f0f55f  cockpit_337-1+deb13u2.debian.tar.xz' | sha256sum -c - \
 && curl -fsSLO https://deb.debian.org/debian/pool/main/c/cockpit/cockpit_337-1+deb13u2.dsc \
 && dpkg-source -x cockpit_337-1+deb13u2.dsc
WORKDIR /build/cockpit-337
RUN sed -i '1s/337-1+deb13u2/337-1~bpo12+pertal1/' debian/changelog
RUN apt-get install -y --no-install-recommends fakeroot sudo \
 && useradd --create-home builder && chown -R builder:builder /build
USER builder
RUN dpkg-buildpackage -us -uc -b -j2
