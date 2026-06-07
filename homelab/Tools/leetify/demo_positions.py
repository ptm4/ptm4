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

DEMO_MAX_DEFAULT = 6
GRID = 600.0  # world-units per bucket when no callout name is available


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


def _parse_deaths(dem_path, steam_id, map_name):
    """Extract this player's deaths from one demo. Returns a list of normalized death dicts."""
    from demoparser2 import DemoParser  # imported lazily; opti-only dependency
    parser = DemoParser(dem_path)
    df = parser.parse_event(
        "player_death",
        player=["X", "Y", "Z", "team_num", "last_place_name"],
        other=["total_rounds_played"],
    )
    # demoparser2 prefixes requested player fields by perspective; victim is "user"/"player".
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
        team = row.get(team_col) if team_col else None
        # CS2 team_num: 2 = T, 3 = CT
        side = {2: "T", 3: "CT"}.get(int(team)) if team is not None and str(team).isdigit() else None
        deaths.append({
            "map": map_name,
            "x": float(row[x_col]) if x_col and row.get(x_col) is not None else None,
            "y": float(row[y_col]) if y_col and row.get(y_col) is not None else None,
            "place": row.get(place_col) if place_col else None,
            "side": side,
            "round": int(row[round_col]) if round_col and str(row.get(round_col)).isdigit() else None,
            "weapon": row.get(weap_col) if weap_col else None,
        })
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


def analyze_positions(matches, steam_id, heatmap_dir=None):
    """Top-level: download+parse up to N recent matches, aggregate hotspots, optional heatmaps.

    Returns the `positions` dict (with optional `heatmap_png` per map), or {} if nothing
    could be parsed. Safe to call only when LEETIFY_PARSE_DEMOS is enabled (caller gates).
    """
    try:
        import demoparser2  # noqa: F401 — fail fast with a clear message if absent
    except Exception:
        print("LEETIFY_PARSE_DEMOS set but demoparser2 not installed — skipping positional analysis. "
              "Install with: pip install demoparser2", file=sys.stderr)
        return {}

    cap = int(os.environ.get("LEETIFY_DEMO_MAX", DEMO_MAX_DEFAULT))
    all_deaths = []
    deaths_by_map = defaultdict(list)
    parsed = 0
    for m in matches[:cap]:
        mp = m.get("map_name") or "unknown"
        if not mp.startswith("de_"):
            continue
        dem = _download_demo(m.get("replay_url"), m.get("id") or m.get("data_source_match_id"))
        if not dem:
            continue
        try:
            ds = _parse_deaths(dem, steam_id, mp)
        except Exception as e:
            print(f"demo parse failed ({mp}): {e}", file=sys.stderr)
            continue
        all_deaths.extend(ds)
        deaths_by_map[mp].extend(ds)
        parsed += 1

    if not all_deaths:
        return {}

    positions = aggregate(all_deaths)
    if heatmap_dir:
        for mp, png in _render_heatmaps(deaths_by_map, heatmap_dir).items():
            if mp in positions:
                positions[mp]["heatmap_png"] = png
    print(f"positional analysis: parsed {parsed} demo(s), {len(all_deaths)} deaths across "
          f"{len(positions)} map(s)", file=sys.stderr)
    return positions


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
