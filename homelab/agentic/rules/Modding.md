# Modding.md — standards for modding anything

Game-agnostic practices. Started 2026-09-01 after the DLSS 5 neural-rendering
installs (Black Flag Resynced, Starfield); nothing here is specific to those.

## 1. Build the exit before the entrance

Before the first modded file lands, the rollback must already exist:

- A `_backup\` folder inside the game/app install holding a **pre-change snapshot**
  (file listing with sizes + dates is enough; hashes for anything you'll replace).
- An **uninstall script** that removes exactly what you added — written and saved
  *before* installing, not promised for later.
- Uninstallers must be **hash-guarded**: only delete a file if its hash matches
  what you installed. A same-named file placed later by a patch or another mod is
  never yours to delete.

## 2. Never overwrite blind

- Check whether every target filename already exists before copying. If it does,
  back the original up under a clear name (`<name>.original`, `<name>.official`)
  in place — renames beat deletions.
- After copying, **verify the installed file's hash against the source**. Silent
  truncation/corruption over a network share is real.

## 3. Manifest everything

Every install gets a manifest next to the backup: file, size, SHA256, where it
came from, and the date. Six months later, "which of these 40 DLLs are mine?" is
answerable only if you wrote it down at install time.

## 4. Archive what you can't re-download

Mod binaries distributed through Discord pins, expiring hosts, or delisted pages
disappear. Keep a hashed local archive of every artifact a working setup depends
on (and its *known-good version*, not just "latest"). Keep large binaries out of
git history — gitignore the archive, don't commit it.

## 5. Versions are load-bearing

- Mod ecosystems have compatibility matrices; a "newer" component regularly
  breaks a stack that pinned an older one. Record the exact versions of a working
  combination before updating anything.
- Update one component at a time, and know what error the wrong version produces
  so you can recognize it later.

## 6. Verify by evidence, not vibes

- Before installing, learn what **success looks like in the logs**, not just on
  screen. After installing, read the logs — "I think it's working" is a
  hypothesis; a log line is a fact.
- Change **one variable per test cycle**. Two changes per launch means a failure
  teaches you nothing.
- When something breaks, capture the log *before* fiddling further.

## 7. Check the gates before debugging the config

Hardware and platform gates (GPU generation/features, graphics API, OS, driver
version) fail with generic errors that look like config mistakes. Rule them out
first — no amount of INI editing fixes a feature the silicon refuses.

## 8. Don't stack frameworks that do the same job

Two injection layers fighting over the same hook (two overlays, two upscaler
shims, a feeder plus a native path) produce crashes that look like bugs in
either. Pick one route per feature; fully remove the loser, don't just disable it.

## 9. Treat documentation as claims, not gospel

READMEs go stale and sometimes contradict the files they ship with. When docs and
observed behavior disagree, believe the behavior — then verify with the source's
issue tracker or community before concluding.

## 10. Hard lines

- **Never mod a game with anti-cheat** (VAC/EAC/BattlEye/etc.) or anything played
  online-competitive. Injection is indistinguishable from cheating and bans are
  permanent. Single-player only.
- Prefer copying files over running installers; when an installer is unavoidable,
  know what it writes and where.
- Unsigned community binaries are a trust decision every time — hash them, note
  provenance, and keep them away from machines that matter.

## 11. Leave the install recoverable, always

At any moment, the modded install should be restorable to stock from what's on
disk: backups + manifest + uninstall script, all living with the install itself
(a backup that lives only in your head, or on a machine that's away, is not a
backup). The test: could someone else, with no context, un-mod this folder
correctly using only what's in `_backup\`?
