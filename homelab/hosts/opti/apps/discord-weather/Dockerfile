FROM python:3.12-alpine
# zoneinfo needs the system tz database (not in the alpine base image)
RUN apk add --no-cache tzdata
# gateway client for answering pings (the report itself stays stdlib-only)
RUN pip install --no-cache-dir discord.py==2.4.0
WORKDIR /app
COPY discord-weather.py witty_messages.py weather_context.py .
CMD ["python3", "discord-weather.py"]
