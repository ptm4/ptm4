---
plan: 14
title: Build and distribution
stage: 4
model: sonnet
mode: execute
depends_on: [10]
inputs: [Unity project, Peter's hosting decision (D17 open)]
outputs: [tools/build.ps1 for Win x64 + macOS + Linux, versioning scheme, in-game version/update check, download page (opti web or itch.io private), install notes for friends, SRD attribution screen]
done_when: [a friend on a fresh Windows machine downloads, unzips, launches, and joins by code with no other software; macOS and Linux builds launch; builds are reproducible from a tag]
status: stub
---

# 14: Build and distribution

## Goal
Friends install the game and nothing else (no VPN, no Tailscale). Builds for Windows,
macOS, Linux (D17). **No hosting infrastructure (D24):** Peter hands the zip/exe to friends
himself. No download page, no in-game update check in v1.

## Steps (draft)
1. Batch-mode build script per platform (`unity build` / `tools/build.ps1`); IL2CPP where
   required.
2. Version stamping from git tag; in-game version display so bug reports name a build.
3. macOS: unsigned builds need a right-click Open; write it into the install notes.
4. Install notes (one page, friend-proof) and the CC-BY-4.0 attribution screen in-game.
5. Optional LLM layer: model download on first enable, not bundled.

## Open questions
- Code signing: none for a private game; document the SmartScreen warning.
