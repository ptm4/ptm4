FROM node:lts-alpine

# better-sqlite3 is a native module — needs build tools
RUN apk add --no-cache python3 make g++

WORKDIR /app
COPY package.json .
RUN npm install --omit=dev
COPY index.js .

VOLUME ["/data"]
EXPOSE 3002

CMD ["node", "index.js"]
