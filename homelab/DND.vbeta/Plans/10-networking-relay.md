---
plan: 10
title: Networking (Netcode for GameObjects + Relay + Lobby)
stage: 3
model: sonnet
mode: execute
depends_on: [03, 02]
inputs: [engine intent/event log, UGS project linked in 01, Unity multiplayer skill from the Unity plugin]
outputs: [host/join flow with join codes, intent RPCs client to host, event log replication host to clients, per-player fog of war, reconnect, DM role, two-client local test]
done_when: [two clients on one machine and one across the internet join by code, play a full combat with identical engine state (hash of event log matches), a dropped client reconnects and catches up]
status: stub
---

# 10: Networking

## Goal
Friends type a code and play (D16). Host-authoritative: the host runs the engine, clients
send intents and apply the replicated event log. Because the engine is deterministic and
event-sourced, replication is the log, not the world.

## Steps (draft)
1. Netcode for GameObjects + Unity Transport + Relay + Lobby packages, UGS sign-in.
2. Lobby create/join with a 6-char code; roles (DM, player, spectator).
3. Intent RPC (client to host) and event broadcast (host to clients), ordered and reliable.
4. Late join and reconnect: send a snapshot plus log tail.
5. Per-player fog and visibility computed from the replicated state.
6. Voice stays in Discord (D11).

## Open questions
- Free-tier Relay limits for a 6-person table; verify current quotas.
- Whether the DM can hand host to another player mid-session (probably not in v1).
