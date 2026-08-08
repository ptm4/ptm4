# stream-station — headless VLC + streamlink, remuxing live streams to HLS.
# Built on noblenumbat by the deploy workflow (docker compose build stream-station).

FROM python:3.12-slim

# vlc-bin gives cvlc; vlc-plugin-base carries the livehttp access-out, the ts mux,
# gnutls (https inputs) and live555 (rtsp). procps is for `docker exec ... ps` during QA.
RUN apt-get update && apt-get install -y --no-install-recommends \
        vlc-bin vlc-plugin-base ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*

# streamlink comes from pip, not apt, on purpose: Twitch's ad-bypass breaks every few
# months and the fix is always "newer streamlink". Bump STREAMLINK_REV (any value) to
# bust this layer's cache and pull the current release — that is the upgrade button.
ARG STREAMLINK_REV=2026-08-07
RUN pip install --no-cache-dir --upgrade streamlink

# VLC refuses to run as root and exits immediately — everything below is uid 1000,
# which must match the tmpfs uid= in the compose file or segments can't be written.
RUN useradd -m -u 1000 streamer
COPY stream-station.py /app/stream-station.py

USER streamer
ENV HOME=/home/streamer
EXPOSE 8098
CMD ["python", "-u", "/app/stream-station.py"]
