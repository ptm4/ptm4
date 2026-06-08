#!/usr/bin/env python3
"""
demo_positions.py — positional "where you die" analysis from Valve CS2 demos.

The Leetify public API has no death coordinates, so for real positional coaching
we download each match's Valve .dem (from match.replay_url, bz2-compressed), parse
it with demoparser2, extract the player's deaths (X/Y + callout + side + round),
and aggregate per-map death hotspots. Optionally renders a heatmap PNG with awpy.

Heavy (download + parse), opt-in, and degrades gracefully: if demoparser2 isn't
installed, downloads fail, or a match has no replay, the affected match is skipped
and the rest of the Leetify review proceeds unchanged.

The aggregation core (`aggregate`, `bucket_area`) is pure and unit-testable without
any demo or network — feed it a list of normalized death dicts.

Env:
  HL_DEMO_CACHE_DIR   where to cache/decompress demos (default <agent-logs>/.demos)
  LEETIFY_DEMO_MAX    max matches to parse per run (default 6)
"""

import bz2
import os
import sys
import urllib.request
from collections import defaultdict

DEMO_MAX_DEFAULT = 25  # parse all matches in the Leetify window — run time is acceptable
GRID = 600.0  # world-units per bucket when no callout name is available
TEAM_SIDE = {2: "T", 3: "CT"}  # CS2 team_num → side


def _side(team):
    """Map a CS2 team_num (2=T, 3=CT) to a side string, tolerant of str/float inputs."""
    if team is None:
        return None
    try:
        return TEAM_SIDE.get(int(float(team)))
    except (TypeError, ValueError):
        return None


def cache_dir():
    base = os.environ.get("HL_DEMO_CACHE_DIR")
    if base:
        return base
    logs = os.environ.get("HL_AGENT_LOGS_DIR",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "..", "..", "agent-logs"))
    return os.path.join(logs, ".demos")


# ── Pure aggregation core (unit-testable) ────────────────────────────────────

def bucket_area(death):
    """Resolve a human area name for a death. Prefer the demo's callout; else grid cell."""
    place = (death.get("place") or "").strip()
    if place:
        return place
    x, y = death.get("x"), death.get("y")
    if x is None or y is None:
        return "unknown"
    return f"grid({int(x // GRID)},{int(y // GRID)})"


def aggregate(deaths):
    """deaths: [{map, x, y, place, side('CT'|'T'|None), round, weapon}] -> per-map summary.

    Returns { <map>: { deaths, ct_deaths, t_deaths, hotspots:[{area,count,pct,side}] } }.
    """
    by_map = defaultdict(list)
    for d in deaths:
        by_map[d.get("map") or "unknown"].append(d)

    out = {}
    for mp, ds in by_map.items():
        total = len(ds)
        ct = sum(1 for d in ds if d.get("side") == "CT")
        t = sum(1 for d in ds if d.get("side") == "T")
        # Count by (area, side) so a hotspot can be attributed to a side.
        area_counts = defaultdict(int)
        for d in ds:
            area_counts[(bucket_area(d), d.get("side") or "?")] += 1
        hotspots = [
            {"area": area, "side": side, "count": c, "pct": round(100 * c / total)}
            for (area, side), c in area_counts.items()
        ]
        hotspots.sort(key=lambda h: -h["count"])
        out[mp] = {
            "deaths": total,
            "ct_deaths": ct,
            "t_deaths": t,
            "hotspots": hotspots[:8],
        }
    return out


def hotspots_digest(positions):
    """Compact text of the top death hotspots per map, for the LLM coaching prompt."""
    lines = []
    for mp, p in positions.items():
        top = ", ".join(f"{h['area']} {h['pct']}% ({h['side']})" for h in p["hotspots"][:5])
        lines.append(f"{mp}: {p['deaths']} deaths (CT {p['ct_deaths']} / T {p['t_deaths']}) — top: {top}")
    return "\n".join(lines)


def positions_markdown(positions):
    """Markdown 'Positional breakdown' section for the report log."""
    if not positions:
        return ""
    L = ["## Positional breakdown (where you die)", ""]
    for mp, p in positions.items():
        L.append(f"### {mp} — {p['deaths']} deaths (CT {p['ct_deaths']} / T {p['t_deaths']})")
        L.append("")
        L.append("| Area | Side | Deaths | % |")
        L.append("|---|---|---|---|")
        for h in p["hotspots"]:
            L.append(f"| {h['area']} | {h['side']} | {h['count']} | {h['pct']}% |")
        L.append("")
    return "\n".join(L)


# ── Demo download + parse (best-effort, opti-only) ───────────────────────────

def _download_demo(replay_url, match_id):
    """Download + bz2-decompress a demo to the cache. Returns local .dem path or None."""
    os.makedirs(cache_dir(), exist_ok=True)
    dem_path = os.path.join(cache_dir(), f"{match_id}.dem")
    if os.path.exists(dem_path):
        return dem_path  # cached
    if not replay_url:
        return None
    try:
        tmp_bz2 = dem_path + ".bz2.tmp"
        with urllib.request.urlopen(replay_url, timeout=120) as r, open(tmp_bz2, "wb") as f:
            f.write(r.read())
        with bz2.open(tmp_bz2, "rb") as src, open(dem_path, "wb") as dst:
            dst.write(src.read())
        os.remove(tmp_bz2)
        return dem_path
    except Exception as e:
        print(f"demo download failed ({match_id}): {e}", file=sys.stderr)
        return None


def _col(df, *names):
    """First matching column name present in the DataFrame, else None."""
    for n in names:
        if n in df.columns:
            return n
    return None


def _deaths_from_df(df, steam_id, map_name):
    """Build normalized death dicts (positions/hotspots) from a player_death DataFrame."""
    vic_id = _col(df, "user_steamid", "player_steamid", "victim_steamid")
    x_col = _col(df, "user_X", "player_X", "X")
    y_col = _col(df, "user_Y", "player_Y", "Y")
    team_col = _col(df, "user_team_num", "player_team_num", "team_num")
    place_col = _col(df, "user_last_place_name", "player_last_place_name", "last_place_name")
    round_col = _col(df, "total_rounds_played", "round")
    weap_col = _col(df, "weapon")
    if vic_id is None:
        return []

    deaths = []
    sid = str(steam_id)
    for _, row in df.iterrows():
        if str(row.get(vic_id)) != sid:
            continue
        deaths.append({
            "map": map_name,
            "x": float(row[x_col]) if x_col and row.get(x_col) is not None else None,
            "y": float(row[y_col]) if y_col and row.get(y_col) is not None else None,
            "place": row.get(place_col) if place_col else None,
            "side": _side(row.get(team_col)) if team_col else None,
            "round": int(row[round_col]) if round_col and str(row.get(round_col)).isdigit() else None,
            "weapon": row.get(weap_col) if weap_col else None,
        })
    return deaths


def _rounds_from_events(death_df, hurt_df, end_df, plant_df, defuse_df, steam_id):
    """Assemble per-round summaries for the player from the parsed event DataFrames.

    Returns a list of round dicts (1-indexed round numbers):
      {round, side, won, reason, kills:[{victim,weapon,hs}], died, killer, damage,
       planted, defused}
    """
    sid = str(steam_id)

    # round_end gives the authoritative winner side per (1-indexed) round.
    end_round = _col(end_df, "round")
    end_winner = _col(end_df, "winner")
    end_reason = _col(end_df, "reason")
    outcomes = {}  # round -> (winner_side, reason)
    if end_round is not None and end_winner is not None:
        for _, r in end_df.iterrows():
            rn = r.get(end_round)
            if rn is None or not str(int(rn)).isdigit():
                continue
            outcomes[int(rn)] = (r.get(end_winner), r.get(end_reason) if end_reason else None)

    rounds = defaultdict(lambda: {
        "kills": [], "died": False, "killer": None, "damage": 0,
        "planted": False, "defused": False, "side": None,
    })

    def rnum(row, col):
        """player_death/hurt round is total_rounds_played (0-indexed) → 1-indexed."""
        v = row.get(col) if col else None
        return int(v) + 1 if v is not None and str(v).isdigit() else None

    # Kills + deaths from player_death.
    if death_df is not None and len(death_df):
        vic = _col(death_df, "user_steamid", "player_steamid")
        atk = _col(death_df, "attacker_steamid")
        atk_name = _col(death_df, "attacker_name")
        vic_team = _col(death_df, "user_team_num", "player_team_num")
        atk_team = _col(death_df, "attacker_team_num")
        hs = _col(death_df, "headshot")
        weap = _col(death_df, "weapon")
        drc = _col(death_df, "total_rounds_played", "round")
        for _, row in death_df.iterrows():
            rn = rnum(row, drc)
            if rn is None:
                continue
            if str(row.get(atk)) == sid and str(row.get(vic)) != sid:  # player got a kill
                rounds[rn]["kills"].append({
                    "victim": row.get("user_name") if "user_name" in death_df.columns else None,
                    "weapon": row.get(weap) if weap else None,
                    "hs": bool(row.get(hs)) if hs else False,
                })
                if rounds[rn]["side"] is None and atk_team:
                    rounds[rn]["side"] = _side(row.get(atk_team))
            if str(row.get(vic)) == sid:  # player died
                rounds[rn]["died"] = True
                rounds[rn]["killer"] = row.get(atk_name) if atk_name else None
                if vic_team:
                    rounds[rn]["side"] = _side(row.get(vic_team))

    # Damage from player_hurt.
    if hurt_df is not None and len(hurt_df):
        atk = _col(hurt_df, "attacker_steamid")
        dmg = _col(hurt_df, "dmg_health")
        hrc = _col(hurt_df, "total_rounds_played", "round")
        if atk and dmg:
            for _, row in hurt_df.iterrows():
                if str(row.get(atk)) != sid:
                    continue
                rn = rnum(row, hrc)
                if rn is None:
                    continue
                try:
                    rounds[rn]["damage"] += int(row.get(dmg) or 0)
                except (TypeError, ValueError):
                    pass

    # Objective plays — map by tick into the round whose end-tick is the next one up.
    end_tick = _col(end_df, "tick")
    tick_to_round = []
    if end_round is not None and end_tick is not None:
        for _, r in end_df.iterrows():
            rn, tk = r.get(end_round), r.get(end_tick)
            if rn is not None and tk is not None:
                tick_to_round.append((int(tk), int(rn)))
        tick_to_round.sort()

    def round_for_tick(tk):
        for etk, rn in tick_to_round:
            if tk <= etk:
                return rn
        return None

    for df, key in ((plant_df, "planted"), (defuse_df, "defused")):
        if df is None or not len(df):
            continue
        uid = _col(df, "user_steamid")
        tcol = _col(df, "tick")
        if not uid or not tcol:
            continue
        for _, row in df.iterrows():
            if str(row.get(uid)) != sid:
                continue
            rn = round_for_tick(row.get(tcol))
            if rn is not None:
                rounds[rn][key] = True

    # Fill side for eventless rounds: sides are constant within a half and flip at the
    # halftime switch. Carry the last known side forward/back across rounds in the same half.
    all_rounds = sorted(set(rounds) | set(outcomes))
    known = {rn: rounds[rn]["side"] for rn in rounds if rounds[rn]["side"]}
    if known:
        # Detect the halftime boundary: the round at which the player's side flips.
        flip_round = None
        ordered = sorted(known)
        for a, b in zip(ordered, ordered[1:]):
            if known[a] != known[b]:
                flip_round = b
                break
        first_side = known[ordered[0]]
        second_side = "T" if first_side == "CT" else "CT"
        for rn in all_rounds:
            if rounds[rn]["side"]:
                continue
            if flip_round is None:
                rounds[rn]["side"] = first_side
            else:
                rounds[rn]["side"] = first_side if rn < flip_round else second_side

    # Finalize: attach outcome + side, sort by round.
    out = []
    for rn in all_rounds:
        info = rounds[rn]
        winner, reason = outcomes.get(rn, (None, None))
        side = info["side"]
        won = (winner == side) if (winner and side) else None
        out.append({
            "round": rn,
            "side": side,
            "won": won,
            "reason": reason,
            "kills": info["kills"],
            "died": info["died"],
            "killer": info["killer"],
            "damage": info["damage"],
            "planted": info["planted"],
            "defused": info["defused"],
        })
    return out


def _parse_demo(dem_path, steam_id, map_name):
    """Parse ONE demo once, returning (deaths, rounds).

    deaths feeds the per-map positional aggregate; rounds feeds the per-match deep-dive.
    A single DemoParser instance is reused across all events for efficiency.
    """
    from demoparser2 import DemoParser  # imported lazily; opti-only dependency
    parser = DemoParser(dem_path)

    death_df = parser.parse_event(
        "player_death",
        player=["X", "Y", "Z", "team_num", "last_place_name"],
        other=["total_rounds_played"],
    )
    deaths = _deaths_from_df(death_df, steam_id, map_name)

    def safe(event, **kw):
        try:
            return parser.parse_event(event, **kw)
        except Exception as e:
            print(f"parse_event {event} failed ({map_name}): {e}", file=sys.stderr)
            return None

    hurt_df = safe("player_hurt", other=["total_rounds_played"])
    end_df = safe("round_end")
    plant_df = safe("bomb_planted")
    defuse_df = safe("bomb_defused")

    rounds = []
    if end_df is not None:
        try:
            rounds = _rounds_from_events(death_df, hurt_df, end_df, plant_df, defuse_df, steam_id)
        except Exception as e:
            print(f"round assembly failed ({map_name}): {e}", file=sys.stderr)
    return deaths, rounds


def _parse_deaths(dem_path, steam_id, map_name):
    """Back-compat wrapper: deaths only (used by the self-test / older callers)."""
    deaths, _ = _parse_demo(dem_path, steam_id, map_name)
    return deaths


def _render_heatmaps(deaths_by_map, out_dir):
    """Optional awpy heatmaps. Returns { map: png_filename }. Skips silently if unavailable."""
    pngs = {}
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from awpy.plot import plot  # awpy provides radar-backed plotting
    except Exception:
        return pngs
    os.makedirs(out_dir, exist_ok=True)
    for mp, deaths in deaths_by_map.items():
        pts = [(d["x"], d["y"]) for d in deaths if d.get("x") is not None and d.get("y") is not None]
        if not pts:
            continue
        try:
            fig, _ = plot(map_name=mp, points=pts)  # awpy maps world coords onto the radar
            fname = f"leetify-heatmap-{mp}.png"
            fig.savefig(os.path.join(out_dir, fname), bbox_inches="tight", dpi=80)
            plt.close(fig)
            pngs[mp] = fname
        except Exception as e:
            print(f"heatmap failed ({mp}): {e}", file=sys.stderr)
    return pngs


def _match_score(match, steam_id):
    """Return (won, team_score, enemy_score) for the player's team."""
    sid = str(steam_id)
    stats = match.get("stats") or []
    player_stat = next((s for s in stats if str(s.get("steam64_id")) == sid), None)
    if not player_stat:
        return None, None, None
    team_num = player_stat.get("initial_team_number")
    scores = {s["team_number"]: s["score"] for s in (match.get("team_scores") or [])}
    my_score = scores.get(team_num)
    enemy_score = next((v for k, v in scores.items() if k != team_num), None)
    if my_score is None or enemy_score is None:
        return None, None, None
    return my_score > enemy_score, my_score, enemy_score


def demo_summary(match, deaths, steam_id, rounds=None):
    """Build a per-demo summary dict with date, map, result, stats, hotspots, and rounds."""
    sid = str(steam_id)
    mp = match.get("map_name") or "unknown"
    finished_at = match.get("finished_at") or ""
    stats = match.get("stats") or []
    player_stat = next((s for s in stats if str(s.get("steam64_id")) == sid), {})

    won, my_score, enemy_score = _match_score(match, steam_id)
    result = "win" if won else ("loss" if won is False else "unknown")

    total = len(deaths)
    ct_d = sum(1 for d in deaths if d.get("side") == "CT")
    t_d = sum(1 for d in deaths if d.get("side") == "T")
    area_counts = defaultdict(int)
    for d in deaths:
        area_counts[(bucket_area(d), d.get("side") or "?")] += 1
    hotspots = [
        {"area": a, "side": s, "count": c, "pct": round(100 * c / total) if total else 0}
        for (a, s), c in area_counts.items()
    ]
    hotspots.sort(key=lambda h: -h["count"])

    return {
        "match_id": match.get("id") or match.get("data_source_match_id"),
        "map": mp,
        "date": finished_at[:10] if finished_at else "",
        "result": result,
        "score": f"{my_score}-{enemy_score}" if my_score is not None else "",
        "kills": player_stat.get("total_kills"),
        "deaths": player_stat.get("total_deaths"),
        "rating": player_stat.get("leetify_rating"),
        "hs_pct": round(100 * player_stat["total_hs_kills"] / player_stat["total_kills"])
                  if player_stat.get("total_kills") and player_stat.get("total_hs_kills") is not None else None,
        "demo_deaths": total,
        "ct_deaths": ct_d,
        "t_deaths": t_d,
        "hotspots": hotspots[:6],
        "rounds": round_review(rounds or []),
    }


def demos_digest(demo_summaries):
    """Compact text of per-demo results for the LLM coaching prompt."""
    lines = []
    for d in demo_summaries:
        hs = ", ".join(f"{h['area']} {h['pct']}% ({h['side']})" for h in d["hotspots"][:3])
        rating = d.get("rating")
        rating_str = f"{rating:.3f}" if isinstance(rating, (int, float)) else "?"
        lines.append(
            f"{d['date']} {d['map']} — {d['result']} {d['score']} "
            f"K/D {d['kills']}/{d['deaths']} rating {rating_str} | "
            f"deaths: {hs}"
        )
    return "\n".join(lines)


def round_tag(r):
    """One-line 'what happened' summary for a round, framed by round-win impact."""
    k = len(r.get("kills") or [])
    parts = []
    if k:
        parts.append(f"{k}K")
    if r.get("planted"):
        parts.append("planted")
    if r.get("defused"):
        parts.append("defused")
    if r.get("damage"):
        parts.append(f"{r['damage']}dmg")
    if r.get("died"):
        killer = r.get("killer")
        parts.append(f"died{f' to {killer}' if killer else ''}")
    elif not k:
        parts.append("survived, no impact")
    outcome = "won" if r.get("won") else ("lost" if r.get("won") is False else "?")
    return f"{', '.join(parts) or 'no events'} — round {outcome}"


def round_review(rounds):
    """Attach a 'tag' to each round dict (in place) and return it for JSON + UI."""
    for r in rounds:
        r["tag"] = round_tag(r)
    return rounds


def rounds_digest(demo_summaries):
    """Round-by-round text across ALL parsed demos, for the LLM to spot cross-match patterns."""
    blocks = []
    for d in demo_summaries:
        rounds = d.get("rounds") or []
        if not rounds:
            continue
        won = sum(1 for r in rounds if r.get("won"))
        lost = sum(1 for r in rounds if r.get("won") is False)
        head = f"{d['date']} {d['map']} — {d['result']} {d['score']} ({won}W/{lost}L rounds)"
        lines = [head]
        for r in rounds:
            lines.append(f"  R{r['round']} {r.get('side') or '?'}: {r.get('tag', '')}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def analyze_positions(matches, steam_id, heatmap_dir=None):
    """Top-level: download+parse up to N recent matches, aggregate hotspots, optional heatmaps.

    Returns (positions, demo_summaries). positions is the per-map aggregate dict.
    demo_summaries is a list of per-match breakdown dicts. Both are {} / [] if nothing parsed.
    Safe to call only when LEETIFY_PARSE_DEMOS is enabled (caller gates).
    """
    try:
        import demoparser2  # noqa: F401 — fail fast with a clear message if absent
    except Exception:
        print("LEETIFY_PARSE_DEMOS set but demoparser2 not installed — skipping positional analysis. "
              "Install with: pip install demoparser2", file=sys.stderr)
        return {}, []

    cap = int(os.environ.get("LEETIFY_DEMO_MAX", DEMO_MAX_DEFAULT))
    all_deaths = []
    deaths_by_map = defaultdict(list)
    demo_summaries = []
    parsed = 0
    for m in matches[:cap]:
        mp = m.get("map_name") or "unknown"
        if not mp.startswith("de_"):
            continue
        dem = _download_demo(m.get("replay_url"), m.get("id") or m.get("data_source_match_id"))
        if not dem:
            continue
        try:
            ds, rounds = _parse_demo(dem, steam_id, mp)
        except Exception as e:
            print(f"demo parse failed ({mp}): {e}", file=sys.stderr)
            continue
        all_deaths.extend(ds)
        deaths_by_map[mp].extend(ds)
        demo_summaries.append(demo_summary(m, ds, steam_id, rounds=rounds))
        parsed += 1

    if not all_deaths:
        return {}, []

    positions = aggregate(all_deaths)
    if heatmap_dir:
        for mp, png in _render_heatmaps(deaths_by_map, heatmap_dir).items():
            if mp in positions:
                positions[mp]["heatmap_png"] = png
    print(f"positional analysis: parsed {parsed} demo(s), {len(all_deaths)} deaths across "
          f"{len(positions)} map(s)", file=sys.stderr)
    return positions, demo_summaries


if __name__ == "__main__":
    # Tiny self-test of the pure aggregation core (no demos/network needed).
    sample = [
        {"map": "de_dust2", "x": 100, "y": 200, "place": "Long Doors", "side": "T", "round": 1},
        {"map": "de_dust2", "x": 110, "y": 210, "place": "Long Doors", "side": "T", "round": 3},
        {"map": "de_dust2", "x": 900, "y": 50, "place": "Mid Doors", "side": "T", "round": 5},
        {"map": "de_dust2", "x": -50, "y": -50, "place": "B Site", "side": "CT", "round": 7},
    ]
    import json
    print(json.dumps(aggregate(sample), indent=2))
    print(positions_markdown(aggregate(sample)))
