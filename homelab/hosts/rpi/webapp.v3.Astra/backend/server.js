// Entrypoint — compose runs `node server.js` (working_dir /app/backend).
// 0.0.0.0 is required: Fastify's default bind is loopback, and nginx dials this
// container over the compose bridge.
const buildApp = require('./preview-app');

const PORT = Number(process.env.ASTRA_PORT || 3003);

buildApp()
  .then((app) => app.listen({ port: PORT, host: '127.0.0.1' }))
  .then(() => console.log(`Astra preview listening on http://127.0.0.1:${PORT}`))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
