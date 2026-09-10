FROM python:3.12-alpine
# zoneinfo needs the system tz database (not in the alpine base image)
RUN apk add --no-cache tzdata
WORKDIR /app
COPY discord-jellyfin.py .
CMD ["python3", "discord-jellyfin.py"]
