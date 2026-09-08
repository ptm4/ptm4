// The one thin-proxy fetch used by every upstream route (bots, streams, llama…).
// v1 carried eight hand-rolled copies of this exact function; the behavior is that
// of the originals: JSON in/out, non-JSON error bodies wrapped as { raw }, and the
// caller decides what an unreachable upstream should read like.
async function proxyJson(base, method, urlPath, body, timeoutMs = 8000, extraHeaders = undefined) {
  const headers = { 'Content-Type': 'application/json', ...(extraHeaders || {}) };
  const res = await fetch(`${base}${urlPath}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
  return { status: res.status, ok: res.ok, data };
}

module.exports = { proxyJson };
