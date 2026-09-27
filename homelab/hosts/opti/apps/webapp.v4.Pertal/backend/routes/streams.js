// /api/streams — the guide (from snapshots) and the stream-station controls.
//
// watch / stop / keepalive are media-player controls, not homelab changes, so they are
// direct calls (with a hard timeout and a plain error) rather than audited jobs — a
// keepalive every 5s would drown the audit trail. The bearer token stays server-side.
// Video bypasses Pertal entirely: nginx proxies /hls to noblenumbat.
'use strict';
const { buildGuide } = require('../lib/streams-guide');
const { channelFromUrl } = require('../lib/stream-catalog');
const { STREAM_URL } = require('../sources/streams');

const TOKEN = process.env.HL_STREAM_TOKEN || '';
const ACTIVE = ['starting', 'running'];

async function station(method, path, body, timeoutMs = 8000) {
  const res = await fetch(`${STREAM_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

module.exports = async function streamRoutes(app) {
  app.get('/guide', async () => {
    const s = (k) => app.snapshots.get(k);
    return buildGuide({
      status: s('streams:status')?.data,
      presets: s('streams:presets')?.data,
      day: s('hltv:day')?.data,
      dayMeta: s('hltv:day')?.meta,
      vrs: s('hltv:vrs')?.data,
    });
  });

  const needToken = (reply) =>
    reply.code(503).send({ error: 'HL_STREAM_TOKEN is not set for Pertal — it cannot control stream-station (expected in dev)' });

  // { platform?, channel? | url?, slot?, quality?, profile? } → start, or reuse a slot
  // already playing that channel.
  app.post('/watch', async (req, reply) => {
    if (!TOKEN) return needToken(reply);
    let { platform, channel, url, slot, quality, profile } = req.body || {};
    if (url && !channel) {
      const c = channelFromUrl(url);
      if (c?.type === 'channel') { platform = c.platform; channel = c.channel; url = undefined; }
    }
    if (!channel && !url) return reply.code(400).send({ error: 'channel (with platform) or url is required' });
    platform = platform || 'twitch';

    const snap = await app.snapshots.refresh('streams:status');
    if (!snap?.meta.ok) return reply.code(502).send({ error: `stream-station unreachable: ${snap?.meta.error}` });
    const slots = snap.data.slots || [];
    const already = channel && slots.find((x) => ACTIVE.includes(x.state) && x.platform === platform
      && String(x.channel).toLowerCase() === String(channel).toLowerCase());
    if (already) return { ok: true, slot: already.slot, state: already.state, reused: true };
    if (!slot) {
      const free = slots.find((x) => !ACTIVE.includes(x.state));
      if (!free) return reply.code(409).send({ error: 'all 4 slots are busy — stop one first' });
      slot = free.slot;
    }
    const body = channel
      ? { slot, type: 'channel', platform, channel, ...(quality ? { quality } : {}), ...(profile ? { profile } : {}) }
      : { slot, type: 'url', url, ...(profile ? { profile } : {}) };
    try {
      const out = await station('POST', '/start', body, 15_000);
      if (out.status !== 200) return reply.code(out.status).send({ error: out.data?.error || `stream-station answered HTTP ${out.status}` });
      app.snapshots.refresh('streams:status');
      return { ...out.data, ok: true, slot, reused: false };
    } catch (err) {
      return reply.code(502).send({ error: `stream-station unreachable: ${err.message}` });
    }
  });

  app.post('/stop', async (req, reply) => {
    if (!TOKEN) return needToken(reply);
    const slot = Number(req.body?.slot);
    if (!(slot >= 1 && slot <= 4)) return reply.code(400).send({ error: 'slot must be 1-4' });
    try {
      const out = await station('POST', '/stop', { slot });
      app.snapshots.refresh('streams:status');
      return reply.code(out.status).send(out.data);
    } catch (err) {
      return reply.code(502).send({ error: `stream-station unreachable: ${err.message}` });
    }
  });

  // The open page says "these slots are still wanted" every few seconds, or the
  // station's idle reaper stops them.
  app.post('/keepalive', async (req, reply) => {
    if (!TOKEN) return needToken(reply);
    const slots = (req.body?.slots || []).map(Number).filter((n) => n >= 1 && n <= 4);
    try {
      const out = await station('POST', '/keepalive', { slots }, 4000);
      return reply.code(out.status).send(out.data);
    } catch (err) {
      return reply.code(502).send({ error: `stream-station unreachable: ${err.message}` });
    }
  });
};
