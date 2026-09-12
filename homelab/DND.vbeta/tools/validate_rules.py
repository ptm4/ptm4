#!/usr/bin/env python3
"""Validate content/rules/ against the envelope contract (Plan 03a S4.7).

Checks: envelope fields present and non-empty; ruleset in {2024, 2014}; license is
CC-BY-4.0; id unique within a file; monster abilities are six ints in 1..30; monster
armor_class is an int; spell level is in 0..9; manifest.json sha256 values match the files
on disk.

Usage
  python tools/validate_rules.py [--root content/rules]

Exit 0 and prints "OK <n files> <m records>" if everything passes. Otherwise exits 1 and
lists every problem found (does not stop at the first one).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent / "content" / "rules"
REQUIRED_ENVELOPE_FIELDS = ("id", "kind", "ruleset", "name", "source", "source_url", "license", "attribution", "data", "raw")
VALID_RULESETS = {"2024", "2014"}


def check_envelope(rec: dict, path: Path, index: int, problems: list) -> None:
    where = f"{path.name}[{index}]"
    for field in REQUIRED_ENVELOPE_FIELDS:
        if field not in rec:
            problems.append(f"{where}: missing field '{field}'")
            continue
        val = rec[field]
        # "non-empty": None, "", {} and [] are all empty; data/raw must be non-empty dicts.
        if val in (None, "", {}, []):
            problems.append(f"{where}: field '{field}' is empty")
    if rec.get("ruleset") not in VALID_RULESETS:
        problems.append(f"{where}: ruleset {rec.get('ruleset')!r} not in {sorted(VALID_RULESETS)}")
    if rec.get("license") != "CC-BY-4.0":
        problems.append(f"{where}: license {rec.get('license')!r} != 'CC-BY-4.0'")


def check_monster(rec: dict, path: Path, index: int, problems: list) -> None:
    where = f"{path.name}[{index}] id={rec.get('id')}"
    data = rec.get("data") or {}
    abilities = data.get("abilities") or {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        v = abilities.get(ab)
        if not isinstance(v, int) or not (1 <= v <= 30):
            problems.append(f"{where}: abilities.{ab} = {v!r}, expected an int in 1..30")
    ac = data.get("armor_class")
    if not isinstance(ac, int):
        problems.append(f"{where}: armor_class = {ac!r}, expected an int")


def check_spell(rec: dict, path: Path, index: int, problems: list) -> None:
    where = f"{path.name}[{index}] id={rec.get('id')}"
    level = (rec.get("data") or {}).get("level")
    if not isinstance(level, int) or not (0 <= level <= 9):
        problems.append(f"{where}: level = {level!r}, expected an int in 0..9")


def validate_file(path: Path, problems: list) -> int:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        problems.append(f"{path.name}: cannot read/parse JSON: {e}")
        return 0
    if not isinstance(records, list):
        problems.append(f"{path.name}: top-level JSON is not a list")
        return 0
    seen_ids: set = set()
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            problems.append(f"{path.name}[{i}]: record is not an object")
            continue
        check_envelope(rec, path, i, problems)
        rid = rec.get("id")
        if rid in seen_ids:
            problems.append(f"{path.name}: duplicate id {rid!r}")
        seen_ids.add(rid)
        if rec.get("kind") == "monster":
            check_monster(rec, path, i, problems)
        elif rec.get("kind") == "spell":
            check_spell(rec, path, i, problems)
    return len(records)


def check_manifest(root: Path, problems: list) -> None:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        problems.append("manifest.json: missing")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        problems.append(f"manifest.json: cannot read/parse: {e}")
        return
    for entry in manifest.get("files", []):
        rel = entry.get("path", "")  # relative to --root, e.g. "2024/monsters.json"
        expected = entry.get("sha256")
        p = root / rel
        if not p.exists():
            problems.append(f"manifest.json: file {rel} (resolved {p}) does not exist")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"manifest.json: sha256 mismatch for {rel}: manifest says {expected}, file is {actual}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    a = ap.parse_args(argv)
    root = Path(a.root)
    if not root.exists():
        print(f"FAIL: {root} does not exist")
        return 1

    problems: list = []
    n_files = 0
    n_records = 0
    for path in sorted(root.rglob("*.json")):
        if path.name == "manifest.json":
            continue
        n_files += 1
        n_records += validate_file(path, problems)
    check_manifest(root, problems)

    if problems:
        for p in problems:
            print(f"PROBLEM: {p}")
        print(f"\n{len(problems)} problem(s) found")
        return 1
    print(f"OK {n_files} files {n_records} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
