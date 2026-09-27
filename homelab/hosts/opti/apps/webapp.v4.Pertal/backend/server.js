// Entrypoint. Binds 0.0.0.0 (nginx reaches the container over the compose bridge) and
// shuts down cleanly on SIGTERM so a deploy never leaves a half-written job or snapshot.
'use strict';
const buildApp = require('./app');

const PORT = Number(process.env.PORT) || 3000;

buildApp()
  .then(async (app) => {
    await app.listen({ port: PORT, host: '0.0.0.0' });
    console.log(`pertal ${app.pertal.version} listening on :${PORT}`);
    const shutdown = async (sig) => {
      console.log(`${sig}: shutting down`);
      await app.close();
      process.exit(0);
    };
    process.once('SIGTERM', () => shutdown('SIGTERM'));
    process.once('SIGINT', () => shutdown('SIGINT'));
  })
  .catch((err) => {
    console.error(err);
    process.exit(1);
  });
