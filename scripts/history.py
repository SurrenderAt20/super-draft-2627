"""Last season's data and European fixtures, from FPL-Core-Insights.

Last season (2025/26) does not change, so it is fetched once and cached in
scripts/cache/season_2025-26.json. It gives the model:
  - per player (keyed by FPL player code): minutes and xG, xA, saves, bonus, yellow cards,
    DefCon threshold hits, penalty attempts, team and position
  - team strength (attack/defence) from last season's matches, keyed by team code
  - minutes in Premier League games right after a European match vs. other games
DefCon was introduced in 2025/26, so that is the only season with DefCon data.

European fixtures for this season (past and upcoming) are read on every run,
to flag Premier League games that come shortly after a European match.
"""

import csv
import io
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

CORE = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data"
LAST = "2025-2026"
THIS = "2026-2027"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", f"season_{LAST}.json")
CACHE_VERSION = 2
OLDER = "2024-2025"   # weighted half; has xG, xA, bonus and minutes (via xGC per 90), no DefCon
UNAVAILABLE = {"i", "s", "u", "n"}   # injured, suspended, unavailable, not available (loan etc.)
DC_THR = {"Defender": 10, "Midfielder": 12, "Forward": 12}
EURO_WINDOW_H = 100   # a European match within ~4 days before kick-off counts as "Europe in the week"


def _csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "super-draft-league-site/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
    except Exception as e:
        print(f"  note: could not read {url}: {e}", flush=True)
        return []


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _t(s):
    """Parse a kick-off time; times without a zone are taken as UTC so they compare with FPL's."""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _kind(match_id):
    parts = str(match_id).split("-")
    return parts[2] if len(parts) > 2 else ""


def euro_and_prem(season, gws):
    """All matches in the season's gameweek folders, split into Premier League and European."""
    prem, euro, seen = [], [], set()
    for gw in gws:
        for m in _csv(f"{CORE}/{season}/By%20Gameweek/GW{gw}/matches.csv"):
            mid = m.get("match_id")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            row = {"id": mid, "gw": gw, "home": str(int(_f(m.get("home_team")))), "away": str(int(_f(m.get("away_team")))),
                   "t": _t(m.get("kickoff_time")), "xgh": _f(m.get("home_expected_goals_xg")), "xga": _f(m.get("away_expected_goals_xg")),
                   "finished": str(m.get("finished")).lower() in ("true", "1")}
            (prem if _kind(mid) == "prem" else euro).append(row)
    return prem, euro


def euro_before(prem_kickoff, team_code, euro):
    """Hours since the team's last European match before this kick-off, if within the window."""
    best = None
    for e in euro:
        if team_code in (e["home"], e["away"]) and e["t"] and prem_kickoff and e["t"] < prem_kickoff:
            h = (prem_kickoff - e["t"]).total_seconds() / 3600
            if h <= EURO_WINDOW_H and (best is None or h < best):
                best = h
    return best


def season_rounds(season, players):
    """Per player code: {gw: {mi, st, xg, xa, status, corner, fk}} from the cumulative per-round snapshots."""
    rows = _csv(f"{CORE}/{season}/playerstats.csv")
    by = defaultdict(dict)
    for r in rows:
        by[r["id"]][int(_f(r["gw"]))] = r
    out = {}
    for pid, snaps in by.items():
        p = players.get(pid)
        if not p:
            continue
        prev = {"mi": 0.0, "st": 0.0, "xg": 0.0, "xa": 0.0}
        gws = {}
        for gw in sorted(snaps):
            r = snaps[gw]
            cur = {"mi": _f(r.get("minutes")), "st": _f(r.get("starts")), "xg": _f(r.get("expected_goals")), "xa": _f(r.get("expected_assists"))}
            d = {k: max(0.0, cur[k] - prev[k]) for k in cur}
            prev = cur
            ch = r.get("chance_of_playing_next_round")
            gws[gw] = {**d, "status": r.get("status") or "a", "chance": _f(ch) if ch not in (None, "") else None,
                       "corner": int(_f(r.get("corners_and_indirect_freekicks_order"))) or None,
                       "fk": int(_f(r.get("direct_freekicks_order"))) or None}
        out[p["player_code"]] = gws
    return out


def minutes_summary(gws):
    """Availability-aware minutes pattern: rounds the player was injured/suspended do not count as benched."""
    avail = [g for g in gws.values() if not (g["status"] in UNAVAILABLE and g["mi"] == 0)]
    starts = [g for g in avail if g["st"] >= 1]
    subs = [g for g in avail if g["st"] < 1 and g["mi"] > 0]
    return {"avail": len(avail), "starts": len(starts), "subs": len(subs),
            "min_start": round(sum(g["mi"] for g in starts), 1), "n60_start": sum(1 for g in starts if g["mi"] >= 60),
            "min_sub": round(sum(g["mi"] for g in subs), 1)}


def setpiece_uplift(rounds):
    """Within-player effect of being first-choice corner taker (on xA per 90) and direct free-kick
    taker (on xG per 90): the same players compared in rounds with and without the role."""
    res = {}
    for role, stat in (("corner", "xa"), ("fk", "xg")):
        diffs, weights = [], []
        for gws in rounds.values():
            on = [g for g in gws.values() if g["mi"] >= 45 and g[role] == 1]
            off = [g for g in gws.values() if g["mi"] >= 45 and g[role] != 1]
            if len(on) >= 3 and len(off) >= 3:
                r_on = sum(g[stat] for g in on) / sum(g["mi"] for g in on) * 90
                r_off = sum(g[stat] for g in off) / sum(g["mi"] for g in off) * 90
                w = min(len(on), len(off))
                diffs.append((r_on - r_off) * w)
                weights.append(w)
        res[role] = {"uplift90": round(sum(diffs) / sum(weights), 4) if weights else 0.0, "players": len(weights)}
    return res


def older_season():
    """2024/25 season totals per player code: xG, xA, bonus and minutes. Minutes are not in the file,
    so they are recovered from expected goals conceded and its per-90 value (both FPL's own)."""
    players = {p["player_id"]: p for p in _csv(f"{CORE}/{OLDER}/players/players.csv")}
    last = {}
    for r in _csv(f"{CORE}/{OLDER}/playerstats/playerstats.csv"):
        if r["id"] in players and int(_f(r["gw"])) >= int(_f(last.get(r["id"], {}).get("gw", 0))):
            last[r["id"]] = r
    out = {}
    for pid, r in last.items():
        xgc, xgc90 = _f(r.get("expected_goals_conceded")), _f(r.get("expected_goals_conceded_per_90"))
        mi = xgc / xgc90 * 90 if xgc90 > 0 else 0.0
        if mi < 90:
            continue
        p = players[pid]
        out[p["player_code"]] = {"team": p.get("team_code"), "pos": p.get("position"), "mi": round(mi),
                                 "xg": _f(r.get("expected_goals")), "xa": _f(r.get("expected_assists")), "bo": _f(r.get("bonus")),
                                 "pens": 0}
    code_of = {pid: p["player_code"] for pid, p in players.items()}
    for gw in range(1, 39):
        for m in _csv(f"{CORE}/{OLDER}/playermatchstats/GW{gw}/playermatchstats.csv"):
            if _kind(m.get("match_id")) not in ("prem", ""):
                continue
            c = code_of.get(m.get("player_id"))
            if c in out:
                out[c]["pens"] += int(_f(m.get("penalties_scored")) + _f(m.get("penalties_missed")))
    return out


def build_last_season():
    print(f"  history: building {LAST} cache (one-off)", flush=True)
    players = {p["player_id"]: p for p in _csv(f"{CORE}/{LAST}/players.csv")}
    rows = _csv(f"{CORE}/{LAST}/playerstats.csv")
    by_player = defaultdict(dict)
    for r in rows:
        by_player[r["id"]][int(_f(r["gw"]))] = r

    # per-round values are differences between consecutive cumulative snapshots
    keys = {"mi": "minutes", "xg": "expected_goals", "xa": "expected_assists", "sv": "saves",
            "bo": "bonus", "yc": "yellow_cards", "dc": "defensive_contribution"}
    per_gw = {}
    out = {}
    for pid, snaps in by_player.items():
        p = players.get(pid)
        if not p:
            continue
        prev = {k: 0.0 for k in keys}
        tot = {k: 0.0 for k in keys}
        dc_apps = dc_hits = 0
        thr = DC_THR.get(p.get("position"))
        gws = {}
        for gw in sorted(snaps):
            cur = {k: _f(snaps[gw].get(col)) for k, col in keys.items()}
            d = {k: max(0.0, cur[k] - prev[k]) for k in keys}
            prev = cur
            gws[gw] = d["mi"]
            for k in keys:
                tot[k] += d[k]
            if thr and d["mi"] >= 60:
                dc_apps += 1
                dc_hits += d["dc"] >= thr
        per_gw[p["player_code"]] = gws
        out[p["player_code"]] = {"pos": p.get("position"), "team": p.get("team_code"),
                                 **{k: round(v, 2) for k, v in tot.items() if k != "dc"},
                                 "dc_apps": dc_apps, "dc_hits": dc_hits, "pens": 0}

    prem, euro = euro_and_prem(LAST, range(1, 39))

    # penalty attempts per player (Premier League only), from the match stats
    code_of = {pid: p["player_code"] for pid, p in players.items()}
    for gw in range(1, 39):
        for r in _csv(f"{CORE}/{LAST}/By%20Gameweek/GW{gw}/playermatchstats.csv"):
            if _kind(r.get("match_id")) != "prem":
                continue
            c = code_of.get(r.get("player_id"))
            if c in out:
                out[c]["pens"] += int(_f(r.get("penalties_scored")) + _f(r.get("penalties_missed")))

    # minutes right after a European match vs. other games, for regular starters
    team_kick = defaultdict(dict)
    for m in prem:
        team_kick[m["home"]][m["gw"]] = m["t"]
        team_kick[m["away"]][m["gw"]] = m["t"]
    rot = {}
    for code, gws in per_gw.items():
        team = out[code]["team"]
        after, normal = [], []
        for gw, mins in gws.items():
            kick = team_kick.get(team, {}).get(gw)
            if kick is None:
                continue
            (after if euro_before(kick, team, euro) is not None else normal).append(mins)
        if after and normal:
            rot[code] = {"after": sum(after), "n_after": len(after), "normal": sum(normal), "n_normal": len(normal)}

    rounds = season_rounds(LAST, players)
    for code, gws in rounds.items():
        if code in out:
            out[code]["min"] = minutes_summary(gws)
            mins = sum(g["mi"] for g in gws.values()) or 1
            out[code]["corner_share"] = round(sum(g["mi"] for g in gws.values() if g["corner"] == 1) / mins, 3)
            out[code]["fk_share"] = round(sum(g["mi"] for g in gws.values() if g["fk"] == 1) / mins, 3)
    uplift = setpiece_uplift(rounds)
    older = older_season()

    teams_xg = [(m["home"], m["away"], 1, m["xgh"]) for m in prem if m["finished"]] + \
               [(m["away"], m["home"], 0, m["xga"]) for m in prem if m["finished"]]
    pens_total = sum(p["pens"] for p in out.values())
    data = {"version": CACHE_VERSION, "season": LAST, "players": out, "team_matches": teams_xg,
            "setpiece": uplift, "older": older, "older_season": OLDER,
            "rotation": rot, "pens_per_team_match": round(pens_total / max(1, len(teams_xg)), 4)}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  history: cached {len(out)} players, {len(teams_xg) // 2} matches, {len(rot)} rotation records, "
          f"{data['pens_per_team_match']} pens per team-match, set pieces {uplift}, {len(older)} players from {OLDER}", flush=True)
    return data


def last_season():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") == CACHE_VERSION:
            return data
    return build_last_season()


def this_season(upto_gw):
    """European matches this season (past and upcoming) and penalty attempts per player per round."""
    _, euro = euro_and_prem(THIS, range(1, min(38, upto_gw + 6) + 1))
    players = {p["player_id"]: p["player_code"] for p in _csv(f"{CORE}/{THIS}/players.csv")}
    pens = defaultdict(dict)
    for gw in range(1, upto_gw + 1):
        for r in _csv(f"{CORE}/{THIS}/By%20Gameweek/GW{gw}/playermatchstats.csv"):
            if _kind(r.get("match_id")) != "prem":
                continue
            c = players.get(r.get("player_id"))
            n = int(_f(r.get("penalties_scored")) + _f(r.get("penalties_missed")))
            if c and n:
                pens[c][gw] = pens[c].get(gw, 0) + n
    core_players = {p["player_id"]: p for p in _csv(f"{CORE}/{THIS}/players.csv")}
    rounds = season_rounds(THIS, core_players)
    return {"euro": euro, "pens": pens, "rounds": rounds}
