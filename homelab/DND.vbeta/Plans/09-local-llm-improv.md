---
plan: 09
title: Local LLM improv (optional layer)
stage: 3
model: fable
mode: decide
depends_on: [07, 08]
inputs: [campaign schema optional_llm hook, host machine GPU facts (Peter: RTX 4070 Ti), Unity platform targets]
outputs: [decision llama.cpp sidecar vs LLamaSharp, model choice + download-on-first-run, guardrail prompt builder from campaign context, NPC freeform chat UI hook, optional Claude-backed DM switch, all off by default]
done_when: [game runs fully with the layer disabled, a friend hosting on a mid-range GPU (or CPU fallback) gets a reply in under a few seconds, no network calls unless the Claude switch is on]
status: stub
---

# 09: Local LLM improv (optional layer)

## Goal
Freeform NPC conversation inside authored guardrails, using a small quantized model on
whoever is hosting (D3, D11). Zero API cost, zero Claude tokens. Strictly optional; the
game must be complete without it.

## Shape
- Host-only: the host process launches the model; clients send text intents over Relay.
- Vulkan backend so any GPU vendor works; CPU fallback with a warning.
- Guardrails: system prompt assembled from the campaign's facts, the NPC's authored
  personality and knowledge, and the current flags; outputs constrained to dialogue plus a
  small set of allowed state changes.
- Model download on first enable, hash-verified, stored outside the build.
- Optional **Claude-backed DM** switch for Peter's own hosting (Max plan) behind the same
  interface.

## Open questions
- LLamaSharp inside Unity (IL2CPP/Mono constraints) vs llama-server sidecar process.
- Which model at ~4-8B fits an 8 GB card with the game running.
- macOS (Metal) and Linux builds of the sidecar.
