# Pertal — one baked image. Dependencies are installed at BUILD time, never at container
# start: v3 ran `npm install` on every restart against a bind mount, which is how a
# deploy or an npm hiccup could take the dashboard down.
#
#   docker build -t pertal .        (context = this folder)

FROM node:24-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:24-alpine AS deps
WORKDIR /src/backend
COPY backend/package.json backend/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM node:24-alpine
ENV NODE_ENV=production PORT=3000
WORKDIR /app
COPY --from=deps /src/backend/node_modules backend/node_modules
COPY backend/ backend/
COPY --from=web /src/frontend/dist frontend/dist
# arch_data is a shared named volume (job audit, vitals, fragments); it must be writable.
RUN mkdir -p /arch-data && chown node:node /arch-data
USER node
EXPOSE 3000
# /api/health does no upstream I/O, so this measures Pertal itself.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/api/health >/dev/null || exit 1
CMD ["node", "backend/server.js"]
