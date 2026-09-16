#!/usr/bin/env python3
"""SRD / Open5e data ingest (Plan 03a, widened by Plan 18 batch 02b). Pulls SRD-licensed 5e
data into ruleset-tagged JSON that the engine (Plan 03) loads. 2024 (SRD 5.2) is primary; 2014
(SRD 5.1) fills gaps.

Sources (see homelab/DND.vbeta/Plans/SOURCES.md; only SRD documents are ingested):
  - 5e-database (github.com/5e-bits/5e-database): SRD 5.1 (src/2014/en/) and SRD 5.2
    (src/2024/en/) as JSON, pinned to a commit sha. Primary source for both rulesets, and the
    only source for the batch 02b kinds (levels, features, subclasses, feats, magic items and
    the small lookup tables) — there is no Open5e fallback for any of those.
  - Open5e v2 API (api.open5e.com), document key `srd-2024`: used ONLY for 2024 spells, the one
    kind 5e-database's 2024 set does not ship (confirmed by a 404 on
    `src/2024/en/5e-SRD-Spells.json`).

Never fetches wikidot, 5e.tools, or any non-SRD document (see SOURCES.md "Never ingest").

Usage
  python tools/ingest_srd.py [--refresh] [--kinds monsters,spells] [--out content/rules] [--twice]

  --refresh   bypass the download cache (tools/.ingest-cache/, gitignored)
  --kinds     comma-separated subset of KINDS (default: all) — see KINDS in this file for the
              full list (the original nine plus the sixteen batch 02b kinds)
  --out       output root (default: content/rules, relative to homelab/DND.vbeta/)
  --twice     run the full ingest twice into --out and report whether every output file is
              byte-identical between the two runs (idempotence check for Plan 03a's done_when)

Writes content/rules/{2024,2014}/<kind>.json, manifest.json, LICENSES.md, coverage.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.1.0"
HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "content" / "rules"
CACHE_DIR = HERE / ".ingest-cache"
USER_AGENT = "dungine-ingest/1.0"

GITHUB_REPO = "5e-bits/5e-database"
OPEN5E_DOC_KEY = "srd-2024"

RULESETS = ("2024", "2014")
KINDS = (
    "monsters", "spells", "conditions", "equipment", "classes", "species", "backgrounds", "skills", "damage-types",
    # Batch 02b (Plan 18): the rest of the SRD data.
    "levels", "features", "subclasses", "feats", "magic-items", "magic-schools", "weapon-properties",
    "weapon-mastery-properties", "proficiencies", "languages", "alignments", "ability-scores",
    "equipment-categories", "traits", "subspecies", "poisons",
)
SINGULAR = {
    "monsters": "monster", "spells": "spell", "conditions": "condition", "equipment": "equipment",
    "classes": "class", "species": "species", "backgrounds": "background", "skills": "skill",
    "damage-types": "damage-type",
    "levels": "level", "features": "feature", "subclasses": "subclass", "feats": "feat",
    "magic-items": "magic-item", "magic-schools": "magic-school", "weapon-properties": "weapon-property",
    "weapon-mastery-properties": "weapon-mastery-property", "proficiencies": "proficiency",
    "languages": "language", "alignments": "alignment", "ability-scores": "ability-score",
    "equipment-categories": "equipment-category", "traits": "trait", "subspecies": "subspecies",
    "poisons": "poison",
}
# 5e-database filename per (ruleset, kind). species/subspecies are handled specially (Species/
# Subspecies.json for 2024, Races/Subraces.json for 2014 — 2014 calls them "races"/"subraces";
# both map to the "species"/"subspecies" kinds here).
FILE_FOR_KIND = {
    "monsters": "Monsters", "spells": "Spells", "conditions": "Conditions", "equipment": "Equipment",
    "classes": "Classes", "backgrounds": "Backgrounds", "skills": "Skills", "damage-types": "Damage-Types",
    "levels": "Levels", "features": "Features", "subclasses": "Subclasses", "feats": "Feats",
    "magic-items": "Magic-Items", "magic-schools": "Magic-Schools", "weapon-properties": "Weapon-Properties",
    "weapon-mastery-properties": "Weapon-Mastery-Properties", "proficiencies": "Proficiencies",
    "languages": "Languages", "alignments": "Alignments", "ability-scores": "Ability-Scores",
    "equipment-categories": "Equipment-Categories", "traits": "Traits", "poisons": "Poisons",
}
# Kinds that exist for only one ruleset by design (Plan 18 C1), not by an incidental data gap.
RULESET_SCOPE = {
    "weapon-mastery-properties": {"2024"},
    "poisons": {"2024"},
}


def kind_allowed(kind: str, ruleset: str) -> bool:
    return ruleset in RULESET_SCOPE.get(kind, RULESETS)


# Still skipped (prose, 2014-only).
SKIPPED_KINDS = ["rules", "rule-sections"]

FEET_RE = re.compile(r"(-?\d+)\s*ft")
REACH_RE = re.compile(r"reach\s+(\d+)\s*ft", re.I)
RANGE_RE = re.compile(r"range\s+(\d+)(?:\s*/\s*(\d+))?\s*ft", re.I)


def log(msg: str) -> None:
    print(msg)


# ---------------------------------------------------------------------- HTTP + cache
def cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")


def _fetch_bytes(url: str) -> bytes:
    """urllib first. If Python's OpenSSL rejects the server's certificate chain but the OS trust
    store accepts it (seen 2026-09-11 with api.open5e.com's rotated Let's Encrypt intermediate:
    every link valid, curl fine, urllib 'certificate has expired'), retry through the system
    curl, which verifies via the OS store. Verification is never disabled."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed SRD hosts only
            return resp.read()
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) or not shutil.which("curl"):
            raise
        res = subprocess.run(["curl", "-sS", "-L", "--fail", "--max-time", "60", "-A", USER_AGENT, url], capture_output=True)
        if res.returncode != 0:
            raise RuntimeError(f"curl fallback failed for {url}: {res.stderr.decode(errors='replace').strip()}") from e
        log(f"note: urllib rejected {url.split('/')[2]}'s TLS chain ({e.reason}); fetched via system curl (OS trust store)")
        return res.stdout


def fetch_json(url: str, refresh: bool):
    cp = cache_path(url)
    if not refresh and cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    raw = _fetch_bytes(url)
    log(f"fetched {url}")
    data = json.loads(raw.decode("utf-8"))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data), encoding="utf-8")
    return data


def fetch_json_optional(url: str, refresh: bool):
    """None on a 404 (a kind that genuinely does not exist for this ruleset); raises otherwise."""
    try:
        return fetch_json(url, refresh)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


# ---------------------------------------------------------------------- small helpers
def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower())
    return s.strip("-")


def parse_feet(s) -> int | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = FEET_RE.search(str(s))
    return int(m.group(1)) if m else None


def parse_reach_ft(desc: str) -> int | None:
    m = REACH_RE.search(desc or "")
    return int(m.group(1)) if m else None


def parse_range_ft(desc: str) -> list | None:
    m = RANGE_RE.search(desc or "")
    if not m:
        return None
    normal = int(m.group(1))
    long_ = int(m.group(2)) if m.group(2) else normal
    return [normal, long_]


def proficiency_bonus_for_cr(cr) -> int | None:
    if cr is None:
        return None
    cr = float(cr)
    if cr <= 4: return 2
    if cr <= 8: return 3
    if cr <= 12: return 4
    if cr <= 16: return 5
    if cr <= 20: return 6
    if cr <= 24: return 7
    if cr <= 28: return 8
    return 9


def names_of(lst) -> list:
    out = []
    for x in lst or []:
        out.append(x.get("name") or x.get("index") if isinstance(x, dict) else str(x))
    return out


def equip_category(rec: dict) -> str | None:
    cats = rec.get("equipment_categories")
    if isinstance(cats, list) and cats:
        return cats[0].get("name")
    single = rec.get("equipment_category")
    if isinstance(single, dict):
        return single.get("name")
    return None


def join_desc(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return "\n\n".join(str(x) for x in v)
    return str(v)


def generic_data(rec: dict) -> dict:
    """Plan 18 C2's generic rule: copy every top-level scalar (str/int/float/bool) field
    unchanged; desc becomes description (joined with join_desc). Objects/arrays stay out of
    `data` (they remain in `raw`) unless a per-kind normalizer adds them back explicitly."""
    data = {k: v for k, v in rec.items() if k != "desc" and isinstance(v, (str, int, float, bool))}
    if "desc" in rec:
        data["description"] = join_desc(rec["desc"])
    return data


# ---------------------------------------------------------------------- normalizers (5e-database shape, both rulesets)
def norm_monster(rec: dict, warnings: list, mid: str) -> dict:
    ac_list = rec.get("armor_class") or []
    armor_class = ac_list[0].get("value") if ac_list else None
    speed_raw = rec.get("speed") or {}
    speed_ft = {k: parse_feet(speed_raw.get(k)) for k in ("walk", "fly", "swim", "climb", "burrow")}
    abilities = {
        "str": rec.get("strength"), "dex": rec.get("dexterity"), "con": rec.get("constitution"),
        "int": rec.get("intelligence"), "wis": rec.get("wisdom"), "cha": rec.get("charisma"),
    }
    saving_throws, skills = {}, {}
    for p in rec.get("proficiencies") or []:
        prof = p.get("proficiency") or {}
        idx = prof.get("index", "")
        val = p.get("value")
        if idx.startswith("saving-throw-"):
            saving_throws[idx.replace("saving-throw-", "")] = val
        elif idx.startswith("skill-"):
            skills[idx.replace("skill-", "").replace("-", " ")] = val
    cr = rec.get("challenge_rating")
    prof_bonus = rec.get("proficiency_bonus")
    if prof_bonus is None:
        prof_bonus = proficiency_bonus_for_cr(cr)
    attacks, actions_out = [], []
    for a in rec.get("actions") or []:
        desc = a.get("desc", "")
        actions_out.append({"name": a.get("name"), "desc": desc})
        if "attack_bonus" in a:
            dmg = []
            for d in a.get("damage") or []:
                dt = d.get("damage_type") or {}
                dmg.append({"dice": d.get("damage_dice"), "type": dt.get("index") or dt.get("name")})
            reach = parse_reach_ft(desc)
            rng = parse_range_ft(desc)
            if reach is None and rng is None:
                warnings.append(f"{mid}: could not parse reach/range from action '{a.get('name')}'")
            attacks.append({
                "name": a.get("name"), "attack_bonus": a.get("attack_bonus"),
                "reach_ft": reach, "range_ft": rng, "damage": dmg, "description": desc,
            })
    traits = [{"name": t.get("name"), "desc": t.get("desc")} for t in rec.get("special_abilities") or []]
    legendary = [{"name": t.get("name"), "desc": t.get("desc")} for t in rec.get("legendary_actions") or []]
    return {
        "size": rec.get("size"), "type": rec.get("type"), "alignment": rec.get("alignment"),
        "armor_class": armor_class, "hit_points": rec.get("hit_points"),
        "hit_dice": rec.get("hit_points_roll") or rec.get("hit_dice"),
        "speed_ft": speed_ft, "abilities": abilities, "proficiency_bonus": prof_bonus,
        "challenge_rating": cr, "xp": rec.get("xp"),
        "saving_throws": saving_throws, "skills": skills,
        "senses": rec.get("senses"), "languages": rec.get("languages"),
        "damage_immunities": names_of(rec.get("damage_immunities")),
        "damage_resistances": names_of(rec.get("damage_resistances")),
        "damage_vulnerabilities": names_of(rec.get("damage_vulnerabilities")),
        "condition_immunities": names_of(rec.get("condition_immunities")),
        "attacks": attacks, "actions": actions_out, "traits": traits, "legendary_actions": legendary,
    }


def norm_spell_5edb(rec: dict) -> dict:
    desc = join_desc(rec.get("desc"))
    higher = join_desc(rec.get("higher_level"))
    damage = None
    if "damage" in rec:
        d = rec["damage"]
        dt = d.get("damage_type") or {}
        at_slot = d.get("damage_at_slot_level") or d.get("damage_at_character_level")
        damage = {"type": dt.get("index") or dt.get("name"), "at_slot_level": at_slot}
    dc = None
    if "dc" in rec:
        dct = rec["dc"].get("dc_type") or {}
        dc = {"ability": dct.get("index"), "success": rec["dc"].get("dc_success")}
    area = None
    if "area_of_effect" in rec:
        area = {"type": rec["area_of_effect"].get("type"), "size_ft": rec["area_of_effect"].get("size")}
    return {
        "level": rec.get("level"), "school": (rec.get("school") or {}).get("name"),
        "casting_time": rec.get("casting_time"), "range": rec.get("range"),
        "components": rec.get("components") or [], "material": rec.get("material"),
        "duration": rec.get("duration"), "concentration": bool(rec.get("concentration")),
        "ritual": bool(rec.get("ritual")),
        "classes": [c.get("index") for c in rec.get("classes") or []],
        "description": desc, "higher_level": higher, "damage": damage, "dc": dc, "area": area,
    }


def norm_condition(rec: dict) -> dict:
    return {"description": join_desc(rec.get("desc") if "desc" in rec else rec.get("description"))}


def norm_equipment(rec: dict) -> dict:
    weapon = None
    if "damage" in rec or (isinstance(rec.get("range"), dict) and "properties" in rec):
        dmg = rec.get("damage") or {}
        two_h = rec.get("two_handed_damage") or {}
        rng = rec.get("range") or {}
        weapon = {
            "category": equip_category(rec), "range_class": None,
            "damage": {"dice": dmg.get("damage_dice"), "type": (dmg.get("damage_type") or {}).get("index")} if dmg else None,
            "two_handed_damage": {"dice": two_h.get("damage_dice"), "type": (two_h.get("damage_type") or {}).get("index")} if two_h else None,
            # 5e-database gives melee weapons range {"normal": 5} (their reach); only a real ranged
            # weapon has "long". Thrown weapons carry a separate throw_range.
            "range_ft": [rng.get("normal"), rng.get("long")] if rng.get("long") else None,
            "throw_range_ft": [tr.get("normal"), tr.get("long")] if (tr := rec.get("throw_range") or {}).get("normal") else None,
            "properties": names_of(rec.get("properties")),
        }
    armor = None
    if isinstance(rec.get("armor_class"), dict):
        ac = rec["armor_class"]
        armor = {
            "category": equip_category(rec), "base_ac": ac.get("base"),
            "dex_bonus": bool(ac.get("dex_bonus")), "max_dex_bonus": ac.get("max_bonus"),
            "str_minimum": rec.get("str_minimum"), "stealth_disadvantage": rec.get("stealth_disadvantage"),
        }
    return {
        "category": equip_category(rec), "cost": rec.get("cost"), "weight_lb": rec.get("weight"),
        "weapon": weapon, "armor": armor, "description": join_desc(rec.get("desc")),
    }


def norm_class(rec: dict) -> dict:
    return {
        "hit_die": rec.get("hit_die"),
        "proficiency_choices": rec.get("proficiency_choices"),
        "proficiencies": names_of(rec.get("proficiencies")),
        "saving_throws": names_of(rec.get("saving_throws")),
        "starting_equipment": rec.get("starting_equipment") or rec.get("starting_equipment_options"),
        "spellcasting": rec.get("spellcasting"),
        "subclasses": names_of(rec.get("subclasses")),
    }


def norm_species(rec: dict) -> dict:
    speed_ft = parse_feet(rec["speed"]["walk"]) if isinstance(rec.get("speed"), dict) else parse_feet(rec.get("speed"))
    ability_bonuses = None
    if "ability_bonuses" in rec:
        ability_bonuses = [{"ability": (b.get("ability_score") or {}).get("index"), "bonus": b.get("bonus")} for b in rec["ability_bonuses"]]
    languages = None
    if "languages" in rec:
        langs = rec["languages"]
        languages = names_of(langs) if isinstance(langs, list) else langs
    return {
        "speed_ft": speed_ft, "size": rec.get("size"),
        "ability_bonuses": ability_bonuses, "traits": names_of(rec.get("traits")),
        "languages": languages, "description": rec.get("size_description"),
    }


def norm_background(rec: dict) -> dict:
    ability_scores = [(a.get("index") if isinstance(a, dict) else a) for a in rec.get("ability_scores") or []]
    return {
        "ability_scores": ability_scores or None,
        "feat": (rec.get("feat") or {}).get("name"),
        "proficiencies": names_of(rec.get("proficiencies")),
        "description": join_desc(rec.get("desc")),
    }


def norm_skill(rec: dict) -> dict:
    return {"description": rec.get("description"), "ability": (rec.get("ability_score") or {}).get("index")}


def norm_damage_type(rec: dict) -> dict:
    return {"description": rec.get("description")}


# ---------------------------------------------------------------------- normalizers (batch 02b, Plan 18 C2)
def norm_level(rec: dict) -> dict:
    data = generic_data(rec)
    data["class"] = (rec.get("class") or {}).get("index")
    subclass = rec.get("subclass")
    data["subclass"] = subclass.get("index") if isinstance(subclass, dict) else None
    data["features"] = [f.get("index") for f in rec.get("features") or []]
    data["proficiency_bonus"] = rec.get("prof_bonus")
    data.pop("prof_bonus", None)
    if "spellcasting" in rec:
        data["spellcasting"] = rec["spellcasting"]
    if "class_specific" in rec:
        data["class_specific"] = rec["class_specific"]
    return data


def norm_feature(rec: dict) -> dict:
    data = generic_data(rec)
    data["class"] = (rec.get("class") or {}).get("index")
    subclass = rec.get("subclass")
    data["subclass"] = subclass.get("index") if isinstance(subclass, dict) else None
    data["prerequisites"] = rec.get("prerequisites")
    return data


def norm_subclass(rec: dict) -> dict:
    data = generic_data(rec)
    data["class"] = (rec.get("class") or {}).get("index")
    spells = []
    for s in rec.get("spells") or []:
        prereq = s.get("prerequisites") or []
        spells.append({"level": prereq[0].get("level") if prereq else None, "spell": (s.get("spell") or {}).get("index")})
    data["spells"] = spells
    if "subclass_levels" in rec:
        data["subclass_levels"] = rec["subclass_levels"]
    return data


def norm_feat(rec: dict, warnings: list, fid: str, ruleset: str) -> dict:
    data = generic_data(rec)
    prereqs = rec.get("prerequisites")
    # 2014 SRD feats: prerequisites is a list of {ability_score, minimum_score} (Plan 18 C2's
    # shape). 2024 SRD feats use a different schema entirely (an object with minimum_level /
    # feature_named, plus a separate prerequisite_options for ability-score choices) — that
    # shape is not in the plan, so it is left unnormalized here (missing = absent, per C2);
    # the full structure is still available in `raw`. Flagged in coverage.md for Fable/Peter.
    if isinstance(prereqs, list):
        data["prerequisites"] = [
            {"ability": (p.get("ability_score") or {}).get("index"), "minimum_score": p.get("minimum_score")}
            for p in prereqs
        ]
    elif prereqs is not None:
        warnings.append(f"feats/{ruleset}: {fid} has a non-list 'prerequisites' shape (2024 schema); left unnormalized, see raw")
    return data


def norm_magic_item(rec: dict) -> dict:
    data = generic_data(rec)
    data["category"] = (rec.get("equipment_category") or {}).get("index")
    data["rarity"] = (rec.get("rarity") or {}).get("name")
    data["variant"] = bool(rec.get("variant"))
    data["variants"] = [v.get("index") for v in rec.get("variants") or []]
    return data


def norm_magic_school(rec: dict) -> dict:
    return generic_data(rec)


def norm_weapon_property(rec: dict) -> dict:
    return generic_data(rec)


def norm_weapon_mastery_property(rec: dict) -> dict:
    return generic_data(rec)


def norm_proficiency(rec: dict, ruleset: str) -> dict:
    data = generic_data(rec)
    data["classes"] = [c.get("index") for c in rec.get("classes") or []]
    species_key = "species" if ruleset == "2024" else "races"
    data["species"] = [s.get("index") for s in rec.get(species_key) or []]
    data["reference"] = (rec.get("reference") or {}).get("index")
    return data


def norm_language(rec: dict) -> dict:
    data = generic_data(rec)
    if "typical_speakers" in rec:
        data["typical_speakers"] = rec["typical_speakers"]
    return data


def norm_alignment(rec: dict) -> dict:
    return generic_data(rec)


def norm_ability_score(rec: dict) -> dict:
    data = generic_data(rec)
    data["skills"] = [s.get("index") for s in rec.get("skills") or []]
    return data


def norm_equipment_category(rec: dict) -> dict:
    data = generic_data(rec)
    data["equipment"] = [e.get("index") for e in rec.get("equipment") or []]
    return data


def norm_trait(rec: dict, ruleset: str) -> dict:
    data = generic_data(rec)
    species_key = "species" if ruleset == "2024" else "races"
    subspecies_key = "subspecies" if ruleset == "2024" else "subraces"
    data["species"] = [s.get("index") for s in rec.get(species_key) or []]
    data["subspecies"] = [s.get("index") for s in rec.get(subspecies_key) or []]
    data["proficiencies"] = [p.get("index") for p in rec.get("proficiencies") or []]
    return data


def norm_subspecies(rec: dict, ruleset: str) -> dict:
    data = generic_data(rec)
    parent_key = "species" if ruleset == "2024" else "race"
    data["species"] = (rec.get(parent_key) or {}).get("index")
    if "ability_bonuses" in rec:
        data["ability_bonuses"] = [{"ability": (b.get("ability_score") or {}).get("index"), "bonus": b.get("bonus")} for b in rec["ability_bonuses"]]
    trait_list = rec.get("racial_traits") if "racial_traits" in rec else rec.get("traits")
    data["traits"] = [t.get("index") for t in trait_list or []]
    return data


def norm_poison(rec: dict) -> dict:
    return generic_data(rec)


# Normalizers that need to know which ruleset they are running for (source field names differ,
# e.g. "species" (2024) vs "races" (2014)).
NEEDS_RULESET = {"proficiencies", "traits", "subspecies"}

NORMALIZERS = {
    "conditions": norm_condition,
    "equipment": norm_equipment,
    "classes": norm_class,
    "species": norm_species,
    "backgrounds": norm_background,
    "skills": norm_skill,
    "damage-types": norm_damage_type,
    "levels": norm_level,
    "features": norm_feature,
    "subclasses": norm_subclass,
    "magic-items": norm_magic_item,
    "magic-schools": norm_magic_school,
    "weapon-properties": norm_weapon_property,
    "weapon-mastery-properties": norm_weapon_mastery_property,
    "proficiencies": norm_proficiency,
    "languages": norm_language,
    "alignments": norm_alignment,
    "ability-scores": norm_ability_score,
    "equipment-categories": norm_equipment_category,
    "traits": norm_trait,
    "subspecies": norm_subspecies,
    "poisons": norm_poison,
}


# ---------------------------------------------------------------------- normalizer (Open5e v2 spell shape, 2024 only)
def norm_spell_open5e(rec: dict) -> dict:
    damage = None
    if rec.get("damage_roll"):
        dtypes = rec.get("damage_types") or []
        at_slot: dict = {}
        for opt in rec.get("casting_options") or []:
            m = re.search(r"slot_level_(\d+)", opt.get("type", ""))
            if m and opt.get("damage_roll"):
                at_slot[m.group(1)] = opt["damage_roll"]
        # Open5e lists only the upcast options; the spell's own level uses damage_roll.
        if rec.get("level") is not None and str(rec["level"]) not in at_slot:
            at_slot[str(rec["level"])] = rec["damage_roll"]
        damage = {"type": dtypes[0] if dtypes else None, "at_slot_level": at_slot or None}
    # 2014 data (5e-database) abbreviates abilities ("dex"); match it so the loader sees one vocabulary.
    ability_abbrev = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
    sta = rec.get("saving_throw_ability")
    dc = {"ability": ability_abbrev.get(sta, sta), "success": None} if sta else None
    area = {"type": rec.get("shape_type"), "size_ft": rec.get("shape_size")} if rec.get("shape_type") else None
    components = [c for c, present in (("V", rec.get("verbal")), ("S", rec.get("somatic")), ("M", rec.get("material"))) if present]
    return {
        "level": rec.get("level"), "school": (rec.get("school") or {}).get("name"),
        "casting_time": rec.get("casting_time"), "range": rec.get("range_text") or rec.get("range"),
        "components": components, "material": rec.get("material_specified"),
        "duration": rec.get("duration"), "concentration": bool(rec.get("concentration")),
        # class keys arrive as "srd-2024_wizard"; strip the document prefix to match 5e-database's "wizard".
        "ritual": bool(rec.get("ritual")), "classes": [(c.get("key") or "").split("_", 1)[-1] for c in rec.get("classes") or []],
        "description": rec.get("desc"), "higher_level": rec.get("higher_level"),
        "damage": damage, "dc": dc, "area": area,
    }


# ---------------------------------------------------------------------- envelope + attribution
def attribution_for(ruleset: str, source_kind: str) -> tuple[str, str]:
    """(attribution text, source label). source_kind is '5edb' or 'open5e'."""
    version = "SRD 5.2" if ruleset == "2024" else "SRD 5.1"
    via = "5e-database" if source_kind == "5edb" else "Open5e"
    return f"{version} (Wizards of the Coast) via {via}", version


def envelope(id_: str, kind: str, ruleset: str, name: str, source: str, source_url: str, attribution: str, data: dict, raw: dict) -> dict:
    return {
        "id": id_, "kind": SINGULAR[kind], "ruleset": ruleset, "name": name,
        "source": source, "source_url": source_url, "license": "CC-BY-4.0",
        "attribution": attribution, "data": data, "raw": raw,
    }


# ---------------------------------------------------------------------- pipeline
def discover_5edb(refresh: bool) -> tuple[str, dict]:
    """Returns (commit_sha, {(ruleset, kind): raw_file_path_or_None}) after checking which
    src/<ruleset>/en/5e-SRD-<File>.json paths exist (a HEAD-only existence probe would still
    cost a request each, so we just fetch the recursive tree once and check membership)."""
    commit = fetch_json(f"https://api.github.com/repos/{GITHUB_REPO}/commits/main", refresh)
    sha = commit["sha"]
    tree = fetch_json(f"https://api.github.com/repos/{GITHUB_REPO}/git/trees/{sha}?recursive=1", refresh)
    paths = {t["path"] for t in tree["tree"]}
    existing: dict = {}
    for ruleset in RULESETS:
        for kind, fname in FILE_FOR_KIND.items():
            existing[(ruleset, kind)] = kind_allowed(kind, ruleset) and f"src/{ruleset}/en/5e-SRD-{fname}.json" in paths
        # species/subspecies: 2024 uses Species/Subspecies.json, 2014 uses Races/Subraces.json
        species_file = "Species" if ruleset == "2024" else "Races"
        existing[(ruleset, "species")] = kind_allowed("species", ruleset) and f"src/{ruleset}/en/5e-SRD-{species_file}.json" in paths
        subspecies_file = "Subspecies" if ruleset == "2024" else "Subraces"
        existing[(ruleset, "subspecies")] = kind_allowed("subspecies", ruleset) and f"src/{ruleset}/en/5e-SRD-{subspecies_file}.json" in paths
    return sha, existing


def open5e_document_exists(refresh: bool) -> bool:
    docs = fetch_json(f"https://api.open5e.com/v2/documents/?key={OPEN5E_DOC_KEY}", refresh)
    return any(d.get("key") == OPEN5E_DOC_KEY for d in docs.get("results", []))


def id_for_5edb(rec: dict, kind: str, ruleset: str, index: int, warnings: list) -> str | None:
    """Plan 18 C2 id rule: index, else slugify(name), else skip with a parse warning."""
    idx = rec.get("index")
    if idx:
        return idx
    name = rec.get("name")
    if name:
        return slugify(name)
    warnings.append(f"{kind}/{ruleset}: record {index} has no index or name")
    return None


def run(out_dir: Path, kinds: list[str], refresh: bool) -> dict:
    sha, existing_5edb = discover_5edb(refresh)
    log(f"5e-database commit {sha}")

    open5e_fallback_kinds: set[tuple[str, str]] = set()
    for kind in kinds:
        # Open5e v2 is spells-only (Plan 18 C1): a batch-02b kind missing its 2024 5e-database
        # file is skipped for 2024 (see the "no ... 5e-database file" branch below), not routed
        # to a fallback that does not exist for it.
        if kind == "spells" and not existing_5edb.get(("2024", kind), False):
            open5e_fallback_kinds.add(("2024", kind))

    blocked: list[str] = []  # "ruleset/kind: reason" for a fallback source that could not be reached at all
    if open5e_fallback_kinds:
        try:
            reachable = open5e_document_exists(refresh)
        except (urllib.error.URLError, ConnectionError) as e:
            reachable = False
            open5e_error = str(e)
        else:
            open5e_error = None
        if not reachable:
            reason = open5e_error or "document srd-2024 not found"
            for ruleset, kind in sorted(open5e_fallback_kinds):
                blocked.append(f"{ruleset}/{kind}: 5e-database has no file for this kind and Open5e v2 could not be reached ({reason}). Not ingested for this ruleset; see coverage.md.")
            log(f"Open5e v2 unreachable ({reason}); skipping 2024 data for {sorted(k for _, k in open5e_fallback_kinds)} (2014 is unaffected). Ask Peter.")
            open5e_fallback_kinds = set()  # nothing else in this run touches Open5e
        else:
            log(f"5e-database has no 2024 file for {sorted(k for _, k in open5e_fallback_kinds)}; using Open5e v2 (document srd-2024)")

    warnings: list[str] = []
    files_written: list[dict] = []
    sources_used: list[dict] = [{"name": "5e-database", "commit_or_key": sha, "fetched_at": _now(), "url": f"https://github.com/{GITHUB_REPO}/tree/{sha}"}]
    if open5e_fallback_kinds:
        sources_used.append({"name": "Open5e v2", "commit_or_key": OPEN5E_DOC_KEY, "fetched_at": _now(), "url": "https://api.open5e.com/v2/"})

    counts: dict = {}  # (ruleset, kind) -> record count
    all_ids: dict = {}  # (ruleset, kind) -> set of ids

    for ruleset in RULESETS:
        for kind in kinds:
            if (ruleset, kind) in open5e_fallback_kinds:
                if kind != "spells":
                    raise SystemExit(f"no Open5e fallback implemented for kind={kind!r}; only 'spells' is wired to Open5e v2. Ask Peter.")
                records, source_label, source_url = _fetch_open5e_spells(refresh)
                normalize = norm_spell_open5e
                get_id = lambda rec: rec["key"].split("_", 1)[1] if "_" in rec["key"] else rec["key"]  # noqa: E731
                get_name = lambda rec: rec.get("name", "")  # noqa: E731
                attribution, _ = attribution_for(ruleset, "open5e")
            else:
                if not existing_5edb.get((ruleset, kind), False):
                    log(f"no {ruleset} 5e-database file for {kind}; skipping (see coverage.md)")
                    counts[(ruleset, kind)] = 0
                    all_ids[(ruleset, kind)] = set()
                    continue
                if kind == "species":
                    fname = "Species" if ruleset == "2024" else "Races"
                elif kind == "subspecies":
                    fname = "Subspecies" if ruleset == "2024" else "Subraces"
                else:
                    fname = FILE_FOR_KIND[kind]
                path = f"src/{ruleset}/en/5e-SRD-{fname}.json"
                source_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{sha}/{path}"
                records = fetch_json(source_url, refresh)
                source_label = f"5e-database@{sha}"
                normalize = norm_spell_5edb if kind == "spells" else NORMALIZERS.get(kind)
                if kind == "levels":
                    # 2014's Levels.json (unlike 2024's) carries no "name" field at all; 2024's
                    # own records name themselves "<Class> <level>" (e.g. "Barbarian 1") from
                    # exactly these two fields, so the same convention is applied when the
                    # source omits it, instead of leaving the required envelope field empty.
                    def get_name(rec):
                        n = rec.get("name")
                        if n:
                            return n
                        cls = (rec.get("class") or {}).get("index") or ""
                        lvl = rec.get("level")
                        return f"{cls.replace('-', ' ').title()} {lvl}" if cls and lvl is not None else ""
                else:
                    get_name = lambda rec: rec.get("name", "")  # noqa: E731
                attribution, _ = attribution_for(ruleset, "5edb")

            is_open5e = (ruleset, kind) in open5e_fallback_kinds
            out_records = []
            for i, rec in enumerate(records):
                if is_open5e:
                    rid = get_id(rec)
                else:
                    rid = id_for_5edb(rec, kind, ruleset, i, warnings)
                    if rid is None:
                        continue
                if kind == "monsters":
                    data = norm_monster(rec, warnings, rid)
                elif kind == "feats":
                    data = norm_feat(rec, warnings, rid, ruleset)
                elif kind in NEEDS_RULESET:
                    data = normalize(rec, ruleset)
                else:
                    data = normalize(rec)
                out_records.append(envelope(rid, kind, ruleset, get_name(rec), source_label, source_url, attribution, data, rec))
            out_records.sort(key=lambda r: r["id"])

            dest = out_dir / ruleset / f"{kind}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(out_records, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            # write_text() would translate \n -> os.linesep on Windows, breaking the sha256
            # below and cross-platform idempotence; write the exact bytes instead.
            dest.write_bytes(text.encode("utf-8"))
            log(f"wrote {dest} ({len(out_records)} records)")
            files_written.append({"path": str(dest.relative_to(out_dir)).replace("\\", "/"), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "records": len(out_records)})
            counts[(ruleset, kind)] = len(out_records)
            all_ids[(ruleset, kind)] = {r["id"] for r in out_records}

    manifest = {"generated": _now(), "tool": f"ingest_srd.py {VERSION}", "sources": sources_used, "files": files_written}
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    log(f"wrote {manifest_path}")

    _write_licenses(out_dir, open5e_fallback_kinds)
    _write_coverage(out_dir, kinds, counts, all_ids, warnings, blocked)

    return {"counts": counts, "warnings": warnings, "blocked": blocked}


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _fetch_open5e_spells(refresh: bool) -> tuple[list, str, str]:
    url = f"https://api.open5e.com/v2/spells/?document__key={OPEN5E_DOC_KEY}&limit=100"
    first_url = url
    results = []
    while url:
        page = fetch_json(url, refresh)
        results.extend(page.get("results", []))
        url = page.get("next")
    return results, f"open5e-v2@{OPEN5E_DOC_KEY}", first_url


def _write_licenses(out_dir: Path, open5e_used: set) -> None:
    lines = [
        "# Third-party licenses — content/rules/",
        "",
        "This directory contains data derived from the System Reference Documents (SRD), used",
        "under the Creative Commons Attribution 4.0 International License. The attribution",
        "statements below must appear in the game's credits screen (Plan 11) and in the build's",
        "`THIRD-PARTY.md` (Plan 14).",
        "",
        "> This work includes material from the System Reference Document 5.2 (“SRD 5.2”) by "
        "Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.2 is "
        "licensed under the Creative Commons Attribution 4.0 International License, available at "
        "https://creativecommons.org/licenses/by/4.0/legalcode.",
        "",
        "> This work includes material from the System Reference Document 5.1 (“SRD 5.1”) by "
        "Wizards of the Coast LLC, available at https://www.dndbeyond.com/srd. The SRD 5.1 is "
        "licensed under the Creative Commons Attribution 4.0 International License, available at "
        "https://creativecommons.org/licenses/by/4.0/legalcode.",
        "",
        "5e-database (github.com/5e-bits/5e-database) republishes SRD data as JSON under MIT "
        "(code) with the data itself remaining under the SRD terms above; see its LICENSE file.",
    ]
    if open5e_used:
        lines += [
            "",
            "Open5e (api.open5e.com) served the 2024 spell data that 5e-database does not ship; "
            "see https://open5e.com/legal for its terms. The underlying spell text is still SRD 5.2 "
            "content under the CC-BY-4.0 grant above.",
        ]
    (out_dir / "LICENSES.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    log(f"wrote {out_dir / 'LICENSES.md'}")


def _write_coverage(out_dir: Path, kinds: list[str], counts: dict, all_ids: dict, warnings: list, blocked: list) -> None:
    lines = ["# content/rules coverage", "", f"Generated {_now()} by ingest_srd.py {VERSION}.", ""]
    if blocked:
        lines += ["## Blocked (source unreachable, not a data gap)", "", "Ask Peter about these before treating coverage below as final.", ""]
        lines += [f"- {b}" for b in blocked]
        lines += [""]
    lines += ["| Kind | 2024 records | 2014 records | 2014-only (no 2024 counterpart) |", "|---|---|---|---|"]
    for kind in KINDS:
        c24 = counts.get(("2024", kind), 0)
        c14 = counts.get(("2014", kind), 0)
        ids24 = all_ids.get(("2024", kind), set())
        ids14 = all_ids.get(("2014", kind), set())
        only14 = len(ids14 - ids24)
        lines.append(f"| {kind} | {c24} | {c14} | {only14} |")
    lines += ["", "## Monsters CR ≤ 5", "", "| id | 2024 | 2014 |", "|---|---|---|"]
    lines += _presence_table(out_dir, "monsters", counts, all_ids, lambda rec: (rec.get("data") or {}).get("challenge_rating") is not None and (rec["data"]["challenge_rating"] or 0) <= 5)
    lines += ["", "## Spells level ≤ 3", "", "| id | 2024 | 2014 |", "|---|---|---|"]
    lines += _presence_table(out_dir, "spells", counts, all_ids, lambda rec: (rec.get("data") or {}).get("level") is not None and rec["data"]["level"] <= 3)
    lines += ["", "## Class levels 1–5", "", "| id | 2024 | 2014 |", "|---|---|---|"]
    lines += _presence_table(out_dir, "levels", counts, all_ids, lambda rec: (rec.get("data") or {}).get("level") is not None and rec["data"]["level"] <= 5)
    lines += ["", "## Skipped kinds (this batch)", ""]
    lines += [f"- {k}" for k in SKIPPED_KINDS]
    lines += ["", "## Parse warnings", ""]
    lines += ([f"- {w}" for w in warnings] if warnings else ["(none)"])
    (out_dir / "coverage.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    log(f"wrote {out_dir / 'coverage.md'}")


def _presence_table(out_dir: Path, kind: str, counts: dict, all_ids: dict, predicate) -> list[str]:
    rows = []
    ids: set = set()
    filtered_by_ruleset: dict = {}
    for ruleset in RULESETS:
        p = out_dir / ruleset / f"{kind}.json"
        if not p.exists():
            filtered_by_ruleset[ruleset] = set()
            continue
        recs = json.loads(p.read_text(encoding="utf-8"))
        keep = {r["id"] for r in recs if predicate(r)}
        filtered_by_ruleset[ruleset] = keep
        ids |= keep
    for rid in sorted(ids):
        has24 = "yes" if rid in filtered_by_ruleset.get("2024", set()) else "no"
        has14 = "yes" if rid in filtered_by_ruleset.get("2014", set()) else "no"
        rows.append(f"| {rid} | {has24} | {has14} |")
    return rows or ["| (none) | | |"]


# ---------------------------------------------------------------------- CLI
# manifest.json and coverage.md carry a "generated <timestamp>" line by design (S4.5/S4.6);
# they are meta/reporting artifacts, not the data files S4.4's byte-identical requirement is
# about, so the idempotence check below deliberately excludes them.
NON_IDEMPOTENT_FILES = {"manifest.json", "coverage.md"}


def hash_tree(out_dir: Path) -> dict:
    out = {}
    for p in sorted(out_dir.rglob("*")):
        rel = str(p.relative_to(out_dir))
        if p.is_file() and rel not in NON_IDEMPOTENT_FILES:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--kinds", default=",".join(KINDS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--twice", action="store_true", help="run twice and report idempotence")
    a = ap.parse_args(argv)
    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    for k in kinds:
        if k not in KINDS:
            raise SystemExit(f"unknown kind {k!r}; choose from {KINDS}")
    out_dir = Path(a.out)

    run(out_dir, kinds, a.refresh)
    if a.twice:
        before = hash_tree(out_dir)
        run(out_dir, kinds, refresh=False)  # cached downloads: second pass is fast and network-free
        after = hash_tree(out_dir)
        diff = [p for p in before if before.get(p) != after.get(p)] + [p for p in after if p not in before]
        if diff:
            print("NOT IDEMPOTENT: " + ", ".join(sorted(set(diff))))
            return 1
        print("IDEMPOTENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
