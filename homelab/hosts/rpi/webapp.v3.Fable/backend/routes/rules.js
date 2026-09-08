// /api/rules — the alert-rule editor's API. Rules live in ui/rules.json (seeded with
// sensible defaults on first read); evaluation happens in the feed poller every 60s
// (lib/rules.js) and on demand via POST /evaluate.
const { KINDS, readRules, writeRules, readHits, validateRule, run, newId } = require('../lib/rules');

module.exports = async function ruleRoutes(app) {
  app.get('/', async () => {
    const { rules, seeded } = readRules();
    const hits = readHits();
    return { rules, seeded, kinds: KINDS, hits: hits.hits, evaluated_at: hits.evaluated_at };
  });

  app.get('/hits', async () => readHits());

  app.post('/', async (req, reply) => {
    const err = validateRule(req.body);
    if (err) return reply.code(400).send({ error: err });
    const { rules } = readRules();
    const rule = { ...req.body, id: newId(), enabled: req.body.enabled !== false };
    rules.push(rule);
    writeRules(rules);
    return rule;
  });

  app.put('/:id', async (req, reply) => {
    const { rules } = readRules();
    const i = rules.findIndex((r) => r.id === req.params.id);
    if (i < 0) return reply.code(404).send({ error: `no rule '${req.params.id}'` });
    const merged = { ...rules[i], ...(req.body || {}), id: rules[i].id };
    const err = validateRule(merged);
    if (err) return reply.code(400).send({ error: err });
    rules[i] = merged;
    writeRules(rules);
    return merged;
  });

  app.delete('/:id', async (req, reply) => {
    const { rules } = readRules();
    const next = rules.filter((r) => r.id !== req.params.id);
    if (next.length === rules.length) return reply.code(404).send({ error: `no rule '${req.params.id}'` });
    writeRules(next);
    return { ok: true, id: req.params.id };
  });

  app.post('/reset', async () => {
    const { DEFAULT_RULES } = require('../lib/rules');
    writeRules(DEFAULT_RULES.map((r) => ({ ...r })));
    return { ok: true, rules: DEFAULT_RULES.length };
  });

  app.post('/evaluate', async () => {
    const out = await run(app);
    if (out.changed && app.events) app.events.emit('incidents', { source: 'rules', hits: out.hits.length });
    return out;
  });
};
