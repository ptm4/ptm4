# Local LLM Troubleshooting

> ⚙️ **HAND-AUTHORED — not auto-generated.** This is a runbook (like the other `0X-*.md`
> files), not one of opti's `2X-*.md` generated docs. Update it directly when you hit and
> fix a new issue with the local-LLM stack.

Diagnostic history for the phone's local LLM (`llama-server` + `llama-ctl` + the webapp
"Local LLM" page). Each entry: symptom → root cause → fix → how it was diagnosed, so the
same investigation doesn't have to happen twice.

---

## Webapp "Runbooks" list showed 0 files (2026-07-22)

**Symptom:** the Local LLM page's runbook manager showed an empty list, even though
`~/runbooks/` on the phone visibly had files in it (via `ls`).

**Root cause:** `~/runbooks/` had just been restructured from a flat directory into two
subdirs — `authored/` (synced from noblenumbat) and `generated/` (synced from opti) — so
that each source's `rsync --delete` stays scoped to its own files. `askcore.py` (used by
the `ask` CLI) was updated to glob recursively (`RUNBOOKS_DIR/**/*.md`) and picked the
subdirs up fine. But `llamactl/server.py` — the separate control API the *webapp* talks
to — still had the old **flat, non-recursive** glob (`RUNBOOKS_DIR/*.md`), which matched
nothing once the top-level directory was emptied out into the two subdirs.

**Lesson:** two independent code paths read the same directory (`ask` CLI via `askcore.py`,
webapp via `llamactl/server.py`) — a structural change to that directory has to be applied
to *both*, not just the one you're actively testing.

**Fix:** `list_runbooks()` in `server.py` now globs both `authored/*.md` and
`generated/*.md` explicitly and returns each entry's name prefixed with its subdir (e.g.
`authored/01-hosts-and-ssh.md`) plus an `"editable"` flag. Writes/deletes are scoped to
`authored/` only — `generated/` is opti-managed and gets overwritten on every docs
regeneration anyway, so editing it through the UI would be silently pointless. The frontend
(`llmRenderRunbookList`/`llmEditRunbook` in `app.js`) now hides the Edit/Delete buttons for
non-editable (`generated/`) entries and shows a read-only viewer instead.

**How to check this class of bug again:** `curl http://127.0.0.1:8081/runbooks` directly on
the phone — if that's empty but `ls ~/runbooks/**/*.md` shows files, it's a glob-path
mismatch in `server.py`, not a sync problem.

---

## Prompt console: HTTP 504 on broad/long-answer questions (2026-07-22)

This turned out to be **three separate, layered issues**, found one at a time by looking at
what actually happened at each hop (nginx → webapp → llama-ctl → llama-server) rather than
guessing from the error code alone. The 504/502 alone was not enough information — each
layer's own log told a different part of the story.

### Layer 1 — `llama-server` defaults to 4 parallel KV-cache slots

**Symptom:** LLM queries were *inconsistently* slow — some fast (~10s), some took minutes
or timed out, with no obvious pattern.

**Root cause:** `llama-server` was started with no `--parallel` flag, so it defaulted to
**4 separate slots**, each with its own independent KV cache. `llama-warmup` (which primes
the cache with the runbook system-prompt so the first real query doesn't pay the full
prefill cost) only primes *one* request — which lands in exactly one slot. A subsequent
real query gets load-balanced into whichever slot the server picks (LRU / prefix-similarity
based), which is frequently a **different, cold** slot — forcing a full multi-minute
re-prefill of the ~8k-token runbook context, invisibly, on what looked like a random subset
of queries.

**How diagnosed:** `tail ~/logs/llama/current` on the phone during a slow request showed
`selected slot by LCP similarity, sim_best = 0.528` — a ~53% prefix match, i.e. barely
warm, followed by a large `prompt processing` phase reprocessing thousands of tokens from
scratch. The startup log also plainly states `n_slots = 4`.

**Fix:** added `--parallel 1` to the `llama-server` launch flags in
`$PREFIX/var/service/llama/run` on the phone. This pins the server to a single KV-cache
slot, so `llama-warmup` warming "the cache" now unambiguously means *the only* cache —
every subsequent query either hits it or the sync service's auto-rewarm (below) has already
handled a content change.

### Layer 2 — nginx's default 60s timeout was far shorter than realistic LLM response times

**Symptom:** even a query that *would* eventually succeed got cut off with a 504 before the
backend had a chance to finish.

**Root cause:** `nginx-wg.conf`'s `location /` block (which the webapp's API traffic rides
on, including `/api/llama/*`) had no `proxy_read_timeout`/`proxy_send_timeout` override, so
nginx used its default **60 seconds**. A local LLM query on this hardware can legitimately
take well over a minute — nginx was cutting the connection before the Node backend's own
(already-longer) fetch timeout even had a chance to resolve either way.

**Fix:** added a dedicated `location /api/llama/` block in `nginx-wg.conf` with
`proxy_read_timeout 240s; proxy_send_timeout 240s;` — scoped to just the LLM endpoints
rather than raising the timeout for the whole webapp. Verified: `nginx -t` (config test) +
`nginx -s reload` (zero-downtime reload) both succeeded.

**Timeout chain, must stay ordered innermost→outermost so the real error message survives
to the browser instead of an opaque nginx error page:**
`llama-ctl → llama-server` (170s, `askcore.chat`'s `timeout=` in the `/ask` handler)
< `webapp → llama-ctl` (180s, `AbortSignal.timeout` in `routes/llama.js`)
< `nginx → webapp` (240s, `nginx-wg.conf`).

### Layer 3 — generation speed itself craters at this context length, even fully warm

**Symptom:** *even after* fixing layers 1 and 2 (single slot, generous timeouts), a broad
"tell me about network, hardware, software & security" query still failed — this time with
the *inner* 170s timeout, not nginx's.

**Root cause:** CPU-based token *generation* cost scales with attention over the full
cached context — at the original short benchmark (~500 tokens of context) this phone hit
**13.6 tok/s**; once the runbook context grew to ~8,000 tokens (after adding the
auto-generated docs), generation speed on a **warm, correctly-cached** request dropped to
**~1.6-1.7 tok/s** — an ~8x slowdown that is *architectural*, not a bug to fix in code.
`max_tokens` was still defaulted to 400, so worst case a response needed
`400 / 1.6 ≈ 250s` — longer than even the fixed inner timeout.

**How diagnosed:** the failing request's log showed `tg = 1.67 t/s` climbing steadily
token-by-token (i.e. actively generating, not stuck/hung) with **no** large prompt-eval
phase beforehand — proof the cache *was* warm and the slowness was pure decode-time cost,
not a repeat of Layer 1's cold-cache problem.

**Fix (the actual bound, not just a bigger number):** lowered `max_tokens` default from
400 → **200** in both `askcore.chat()` (used by `ask` CLI + `llama-ctl`'s `/ask`) and the
webapp's `/api/llama/chat` raw-mode fallback. At the measured worst-case ~1.6 tok/s floor,
200 tokens caps generation at ~125s — comfortably inside all three timeouts. Also tightened
the system prompt to explicitly ask for short, focused answers (2-4 sentences) and to
summarize-and-point-to-the-doc rather than recite everything for broad questions — this
improves typical-case latency on top of the hard cap, and matches what a phone-CPU model
should realistically be asked to do.

**Corollary — remember to re-warm after *any* system-prompt change, not just content
changes:** the `runbook-sync` service's auto-rewarm only fires when the *runbook file
content* changes (it hashes `~/runbooks/**/*.md`). Editing `askcore.py`'s system-prompt
*template* changes the token sequence sent to the model just as much as a content edit
does — it silently invalidates the warm cache the same way, but the sync service has no
way to know a `.py` file changed. Forgot this once mid-fix and re-triggered a full ~10min
cold prefill unnecessarily by retesting immediately after a prompt-wording edit without
manually running `llama-warmup` first. **After any askcore.py/system-prompt edit: run
`llama-warmup` by hand before assuming the next query will be fast.**

**If context keeps growing and this recurs:** the real long-term fix is not more timeout
tuning — it's not stuffing all 12 runbook files into every query regardless of relevance
(a lightweight per-question retrieval/filter step, or trimming the generated docs'
verbosity, e.g. shorter container tables). Flagged as a known follow-up, not yet built.

### Known limitation, not a bug: a timed-out request keeps running server-side

A client that gives up waiting (browser, `curl`, `llama-ctl`'s own inner timeout) does
**not** cancel the underlying `llama-server` task — it just stops listening. `llama-server`
has no idea the client disconnected and keeps decoding until it finishes (or until it tries
to write the response back to the now-dead connection and discovers it can't). Because the
server is pinned to a **single slot**, that orphaned request monopolizes the only KV cache
for its *entire* remaining runtime — observed once taking 373s total — so anything else
sent to the LLM in that window queues up behind it rather than running in parallel. If you
fire a query, give up, and immediately retry, the retry can appear to hang for a while
that's actually the *first* request still finishing in the background. **If a query seems
stuck, check `tail ~/logs/llama/current` for slot activity before assuming something is
broken** — it may just be the previous orphaned request still draining.

**Practical guidance:** broad, multi-topic "tell me everything about X, Y, and Z" questions
remain the worst case for this hardware even with all the fixes above — prefer specific,
single-topic questions (e.g. "is the network report showing any warnings?" — confirmed
**~18s** end-to-end through the full production path) over broad summaries.

---

## Webapp integration wiped by an unrelated deploy (2026-07-22)

**Symptom:** after the fixes above were deployed and verified working, `/api/llama/*`
suddenly started returning Express's default `Cannot GET/POST /api/llama/...` — not a
timeout, not an app error, just "this route doesn't exist," instantly (<1s).

**Root cause:** the entire Local LLM webapp integration (`routes/llama.js`'s mount in
`index.js`, the frontend page in `app.js`, the nav link in `index.html`, the `LLAMA_URL`/
`LLAMA_CTL_URL` env vars in `docker-compose.yml`, and the `/api/llama/` timeout block in
`nginx-wg.conf`) had **only ever been written to the live deployed copy on rpi**
(`/srv/docker/compose/webapp/`) — never ported into the actual **repo source**
(`homelab/RPI-srv/webapp/`). This was known and flagged at the time as a risk, but not
acted on. An unrelated, legitimate commit (`fea5035 "webapp"`, adding an architecture-diagram
page — nothing to do with the LLM work) touched `homelab/RPI-srv/webapp/**`, which triggered
the `rpi-deploy.yml` GitHub Actions workflow. That workflow does exactly what it's supposed
to: copies the repo's webapp source over the deployed one
(`cp -r $GITHUB_WORKSPACE/homelab/RPI-srv/webapp/. /srv/docker/compose/webapp/` +
a direct overwrite of `docker-compose.yml` and `nginx-wg.conf`). Since the repo copy never
had the LLM integration, the deploy correctly-but-unfortunately reverted the live site back
to a version without it. Nobody did anything wrong — the deploy workflow worked exactly as
designed; the gap was that the LLM integration existed in exactly one place.

**How diagnosed:** `docker ps` showed `webapp` and `nginx-webapp` both freshly restarted
(`Up 8 minutes` / `Up 7 minutes`) right around when the failures started. Comparing the live
`index.js` against what should have been there showed it was back to the stock
"ADD YOUR ROUTES HERE" template with no `llamaRouter` require/mount at all.
`cp -r` doesn't delete extra files it doesn't know about, so `routes/llama.js` itself was
still physically present on disk — just never `require()`'d, which is why the failure mode
was "route not found" rather than a missing-file crash. `git log` confirmed the recent
webapp-touching commit; `git show --stat` confirmed it was unrelated (an architecture page).

**Fix:** re-deployed all 5 affected files to the live rpi copy, recreated the `webapp`
container (`docker compose up -d webapp` — required to pick up the env var, a plain
`restart` doesn't reread compose env), reloaded nginx. Then — this time — actually **ported
all 6 files into the repo source** (`homelab/RPI-srv/webapp/backend/index.js`,
`.../routes/llama.js` (new file), `.../frontend/{app.js,index.html,style.css}`,
`homelab/RPI-srv/docker-compose.yml`, `homelab/RPI-srv/nginx-wg.conf`), staged as
uncommitted changes (`git status` shows them cleanly) for Peter to review and commit.

**Lesson — for anything built directly on rpi's live deployed copy going forward:** if a
change isn't also in `homelab/RPI-srv/**` in the repo, it does not durably exist. It will
survive right up until the next *completely unrelated* push touches any file under that
path, then vanish silently with no error in the deploy workflow itself (the workflow did
exactly what it was told). Port live-deployed changes into the repo source in the *same*
session they're built, not as a "later" follow-up.

---

## Quick diagnostic checklist for "the LLM page/query is slow or failing"

1. `curl http://127.0.0.1:8081/status` on the phone — is `llama_healthy: true`? What's
   `current_model`, and does `sv_status` show it running (not crash-looping)?
2. `tail -30 ~/logs/llama/current` on the phone — look for `n_slots` at startup (should be
   `1`), and for the current request: is it in a `prompt processing` phase (cold/reprocessing)
   or a `tg =` phase (warm, generating)? A `tg` in the 1-3 tok/s range at this context size
   is *expected*, not a bug — only investigate further if it's stuck with no log movement.
3. `free -h` on the phone — RAM pressure (little `free`, heavy swap) makes everything above
   worse. Not usually the *root* cause but always makes it slower.
4. If a request was just cancelled/timed out, the **next** one will still be slow (or fail
   again) unless something re-warms the cache — either wait for `runbook-sync`'s automatic
   rewarm-on-content-change, or run `llama-warmup` by hand. It may also just be queued behind
   the previous orphaned request (see above) — check the log before assuming it's broken.
5. Check the actual failing layer from the *symptom*, don't guess:
   - Express's plain `Cannot GET/POST /path` (instant, <1s) → the route isn't mounted at
     all — check for deploy-drift (below) before anything else.
   - nginx's own HTML `504`/`502` error page (not JSON) → nginx itself gave up or the
     upstream connection broke — check nginx's timeout / whether a container just restarted.
   - A JSON `{"error": "llama-server unreachable: timed out"}` → `llama-ctl`'s own inner
     170s timeout fired — that's the generation-speed/token-cap layer, not nginx.
6. `curl -s https://192.168.1.10:8443/api/llama/status` (production path) returning the
   Express-default 404 text instead of JSON → the webapp's deployed copy has drifted from
   what was actually built (see the deploy-wipe incident above) — diff the live
   `/srv/docker/compose/webapp/` against `homelab/RPI-srv/webapp/` in the repo.
