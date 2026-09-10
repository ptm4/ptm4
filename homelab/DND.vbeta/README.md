# DND.vbeta

A Unity-built, HD-2D, D&D 5e (2024 rules) CRPG sandbox: a DM picks voxel environments and
pixel sprites, runs authored campaigns for 3-5 remote friends, and the engine can run a
session by itself ("storybook" auto-DM) with full rules adjudication, with **zero LLM tokens
at runtime**.

Start at [Plans/00-MASTER.md](Plans/00-MASTER.md). Every decision is in
[Plans/DECISIONS.md](Plans/DECISIONS.md); every plan is indexed in
[Plans/README.md](Plans/README.md).

## Tree

| Path | What lives here |
|---|---|
| `Plans/` | The plan set. One `.md` per stage, each routed to a model/agent via frontmatter (see `Plans/CONVENTIONS.md`). |
| `engine/` | Pure C# class library (netstandard2.1, **no UnityEngine refs**): 5e rules engine, storybook runtime, monster AI, xUnit tests. Consumed by Unity as a local UPM package. |
| `content/` | Data, not code: ruleset-tagged rules JSON (SRD/Open5e ingest), homebrew, campaign files. `content/private/` is gitignored for adapted copyrighted modules. |
| `assets-src/` | Pre-import art: generated sprite sheets, `.vox` files, palettes, plus a manifest. Bulk `batches/` and `inbox/` folders are gitignored. |
| `tools/` | Scripts: SRD ingest, sprite cleanup/quantize, sheet assembler, voxel export, build/publish. |

The **Unity project is not in this repo.** It lives at `E:\Unity\Projects\Dungine` with its own
git repo, and contains presentation + netcode only. Rules logic never lives in Unity.
