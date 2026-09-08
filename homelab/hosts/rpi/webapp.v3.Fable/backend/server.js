// Entrypoint — compose runs `node server.js` (working_dir /app/backend).
// 0.0.0.0 is required: Fastify's default bind is loopback, and nginx dials this
// container over the compose bridge.
const buildApp = require('./app');

const PORT = 3000;

buildApp()
  .then((app) => app.listen({ port: PORT, host: '0.0.0.0' }))
  .then(() => console.log(`webapp listening on :${PORT}`))
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
