FROM python:3.12-slim

# Debian's chromium is a FULL browser build. That matters: Playwright's
# chromium-headless-shell is stripped enough that Cloudflare never lets it
# through, and Playwright ships no Chromium at all for arm64. Installing the
# distro browser solves both. --no-install-recommends keeps it ~400MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium fonts-liberation tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    CHROME_PATH=/usr/bin/chromium \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hltv_api.py .

EXPOSE 8080
CMD ["python3", "hltv_api.py"]
