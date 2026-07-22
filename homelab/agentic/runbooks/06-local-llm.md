# Local LLM on the android server

## What it is
`llama.cpp` `llama-server` running on the **android** phone (Snapdragon 855, unrooted,
Termux), serving a local LLM over HTTP on the LAN. Private, offline, zero API cost.

## Endpoint
- `http://android.lan:8080` (or the phone's current LAN IP), OpenAI-compatible API.
- Health: `GET /health` → `{"status":"ok"}`.
- Chat: `POST /v1/chat/completions` (standard OpenAI schema).

## Models (`~/models/` on the phone)
- `qwen2.5-3b-q4.gguf` — **default**, ~7-8 tok/s, better judgment.
- `qwen2.5-1.5b-q4.gguf` — fast path, ~13.6 tok/s, for routing/simple lookups.
- Only ONE model is resident at a time. To switch, edit the service `run` script's `-m`.

## Service management (runit / termux-services)
- Service dir: `$PREFIX/var/service/llama` (run + log/svlogd).
- Status: `sv status llama`. Restart: `sv restart llama`. Stop/start: `sv down/up llama`.
- Logs: `~/logs/llama/current`.
- Auto-starts on boot via `~/.termux/boot/00-start-server.sh` (Termux:Boot) + wake-lock.

## Build notes
- Built with clang on-device. Termux's sysroot lacks `<spawn.h>`, so a stub header was
  added at `$PREFIX/include/spawn.h` (Bionic has the posix_spawn symbols) to build the
  mtmd/server targets. `llama-completion` is the CLI fallback.

## Ceiling
- CPU-only (Hexagon NPU is root-gated). Keep to 1.5-3B models. Good for runbook Q&A,
  command routing, extraction, summarization — NOT live multi-host diagnosis (that's a
  real-Claude job).
