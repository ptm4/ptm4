FROM python:3.12-alpine
# zoneinfo needs the system tz database (not in the alpine base image)
RUN apk add --no-cache tzdata
WORKDIR /app
# shared bot scaffolding: the "botkit" build context is ../_botkit
# (docker-compose.apps.yml additional_contexts).
COPY --from=botkit . ./_botkit/
COPY discord-sports.py .
CMD ["python3", "discord-sports.py"]
