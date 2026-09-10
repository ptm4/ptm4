// Decorates the app with `app.jobs`, the stepped-execution + audit registry.
// Registered after event-bus so jobs can stream their transitions; see lib/jobs.js
// for the model and why it looks like this.
const fp = require('fastify-plugin');
const { createJobs } = require('../lib/jobs');

module.exports = fp(async function jobsPlugin(app) {
  app.decorate('jobs', createJobs(app));
}, { name: 'jobs', dependencies: ['event-bus'] });
