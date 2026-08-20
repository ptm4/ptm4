# Local LLM on the android server

## What it is
`llama.cpp` `llama-server` running on the **android** phone (Snapdragon 855, unrooted,
Termux), serving a local LLM over HTTP on the LAN. Private, offline, zero API cost.

## Endpoints
- **Chat UI (use this): `http://192.168.1.10:3010`** — Open WebUI on rpi (streaming,
  history; compose at `homelab/hosts/rpi/open-webui/`, deployed to
  `/srv/docker/compose/open-webui/`). Two models: `homelab-grounded` (runbook-injected)
  and `raw`. The compose disables title/tags/follow-up/autocomplete generation — each
  would fire a hidden extra model call per message against the phone's single slot.
  Memory-capped 1600m because rpi (4GB) is the DNS SPOF; ~950MB steady.
- `http://android.lan:8080` — llama-server, OpenAI-compatible (raw inference only).
  Health: `GET /health` → `{"status":"ok"}`.
- `http://android.lan:8081` — `llama-ctl`: status/models/model-switch/`/ask`, plus
  OpenAI-compatible `/v1/models` + `/v1/chat/completions` (SSE streaming) that inject
  the runbook grounding for model `homelab-grounded` — this is what Open WebUI talks to.
  Source tracked at `homelab/hosts/android/llamactl/` (server.py, askcore.py,
  llama-warmup) — deploy = `scp` to `~/llamactl/` (+ `$PREFIX/bin/` for llama-warmup) +
  `sv restart llama-ctl`. The phone copy is the live one.
- Runbook/docs feed: opti `~/bin/dump-runbooks.sh` + `dump-docs.sh` (tracked at
  `homelab/hosts/opti/bin/`). **Both must point at the live pool** (`/srv/red/fs/...`) —
  after the 2026-07-25 ZFS migration they silently served a stale copy and an empty
  docs list for weeks (fixed 2026-08-20). Keep the combined feed under ~34KB or the
  prompt overflows `-c 13312` and every ask 400s (14993 tokens measured when it did).

## Models (`~/models/` on the phone) — 2026-08-19 upgrade
- `LFM2.5-2.6B-QAD-Q4_0.gguf` — **default.** Liquid AI, Aug 2026; instruction-following/
  tool-routing leader at this size, hybrid conv+GQA = fast prefill. 46.5 pp / 10.0 tg.
- `LFM2.5-1.2B-Instruct-QAD-Q4_0.gguf` — fast path. 117 pp / 25 tg.
- `Qwen3-4B-Instruct-2507-Q4_0.gguf` — quality/knowledge fallback (LFM is weak on
  parametric knowledge by design). Slower: 22 pp / 5.5 tg.
- `qwen2.5-3b-q4.gguf`, `qwen2.5-1.5b-q4.gguf` — the pre-upgrade pair, kept until the
  new stack proves out; delete for ~3 GB back.
- One model resident at a time. Switch via llama-ctl `POST /model` (webapp does this) —
  it rewrites the run script's `-m`, restarts, **and auto-runs llama-warmup** (patched
  2026-08-20; without the warmup every ask times out for minutes after a switch).
- Bench method: `bench-models.sh` (`$PREFIX/bin`), llama-bench pp512/tg128, t4 pinned.

## Two LFM2.5 traps (both cost us the webapp ask, 2026-08-20)
1. **Reasoning:** LFM2.5-2.6B is reasoning-capable and thinks by default (the 1.2B
   "-Instruct" does not). Without a flag, llama-server routes the thinking to
   `reasoning_content` and `message.content` comes back EMPTY — askcore/webapp read
   `content`, so ask silently breaks while `/health` stays green. Fix in the run
   script: `--reasoning-budget 0` (thinking off entirely — right call at phone speeds).
2. **Tool-call hallucination:** it's also agent-tuned — seeing askcore's `### FILE:`
   headers, it answered with raw `<|tool_call_start|>[read(file_path=...)]` tokens
   instead of prose. Fix: the explicit "you have NO tools… never emit tool-call syntax"
   clause in `askcore.build_system_prompt()` — that clause is load-bearing; keep it for
   any agent-tuned model.

## Serving config (run script, rationale)
`-t 4 --cpu-range 4-7` — pin to the A76 big cluster (cpu4-7); 6 threads was measurably
worse (A55 littles pace every ggml sync barrier). Requires the GGML_OPENMP=OFF build.
Do NOT add `--cpu-strict 1`: strict per-core pinning halved throughput in production
(other processes land on a pinned core and stall the whole graph barrier; the floating
mask tolerates it). `--no-mmap` is load-bearing for speed: with mmap, the aarch64
dotprod repack silently doesn't happen (llama.cpp #12701) and prefill ran at ~16 t/s
instead of ~35. `--prio 2` resists Android scheduling. `-c 13312` fits the ~9.6k-token
runbook system prompt (see 07). `-fa on -ctk q8_0 -ctv q8_0` halves KV memory.
`--cache-reuse 256` reuses the cached system-prompt prefix — **the warmed cache is what
makes ask usable**; cold prefill is minutes even on LFM. `--parallel 1` single KV slot
(07 has the history). `--reasoning-budget 0` per above.

## Service management (runit / termux-services)
- Service dir: `$PREFIX/var/service/llama` (run + log/svlogd).
- Status: `sv status llama`. Restart: `sv restart llama`. Stop/start: `sv down/up llama`.
- Logs: `~/logs/llama/current`. Note: the 2026-08 llama-server build logs only `srv`
  lines at default verbosity — no load_tensors/system_info; don't read absence as failure.
- Auto-starts on boot via `~/.termux/boot/00-start-server.sh` (Termux:Boot) + wake-lock,
  which also fires llama-warmup 20s after boot.

## Build notes
- `~/llama.cpp/build` = master d59d455 (2026-08-19), built on-device: `cmake -B build
  -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_OPENMP=OFF -DGGML_LLAMAFILE=OFF`.
  OPENMP=OFF is load-bearing: Termux clang ships libomp, and with OpenMP the
  `--cpu-range/--cpu-strict` affinity flags silently do nothing.
- Shared-lib build: binaries need `LD_LIBRARY_PATH=~/llama.cpp/build/bin` (the run
  script exports it). The embedded rpath points at the original build dir name, so
  renaming the dir breaks linking — that's why.
- Rollback: `~/llama.cpp/build-old-20260722` (the July build) + the old run script at
  `~/llama-run.bak-20260819`.
- Termux sysroot lacks `<spawn.h>`; stub at `$PREFIX/include/spawn.h` (Bionic has the
  posix_spawn symbols).
- GPU is a dead end on this device — llama.cpp's OpenCL backend doesn't support phone
  A6xx (frozen OpenCL 2.0 driver, init crash), and Vulkan/Turnip benches slower than
  CPU. Investigated thoroughly 2026-08-19; don't revisit.

## Ceiling
- CPU-only (Hexagon NPU root-gated, GPU ruled out above). ~2.6B hybrid or ~3B dense is
  the sweet spot; a dense 4B decodes at ~5.5 tok/s (usable but sluggish). Good for
  runbook Q&A, command routing, extraction, summarization — NOT live multi-host
  diagnosis (that's a real-Claude job).
