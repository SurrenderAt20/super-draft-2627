"""Build the league site's data files from the public FPL Draft API.

Writes:
  docs/data/gameweeks/gwNN.json  one snapshot per finished gameweek (frozen once final)
  docs/data/blocks.json          bottom-half trophy history (frozen per block once final)
  docs/data/current.json         everything the site shows right now

Frozen files are never rewritten. Edit them by hand if a result has to be corrected.
Standard library only, so it runs anywhere with Python 3.9+.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import advanced
import forecast

API = "https://draft.premierleague.com/api"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")
GW_DIR = os.path.join(DATA, "gameweeks")

NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------- helpers

def fetch(path, tries=4):
    url = f"{API}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "super-draft-league-site/1.0"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == tries - 1:
                raise RuntimeError(f"Could not fetch {url}: {e}") from e
            time.sleep(2 * (attempt + 1))


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    """Write only if content changed, so unchanged runs produce no git diff."""
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def result(a, b):
    return "W" if a > b else "D" if a == b else "L"


def h2h_points(r):
    return {"W": 3, "D": 1, "L": 0}[r]


# ---------------------------------------------------------------- core calculations

def table_from_matches(matches, entries, upto_gw):
    """H2H table after `upto_gw`, ranked by H2H points then points scored."""
    rows = {le: {"le": le, "p": 0, "w": 0, "d": 0, "l": 0, "pf": 0, "pa": 0, "pts": 0} for le in entries}
    for m in matches:
        if m["event"] > upto_gw:
            continue
        for me, opp, pm, po in ((m["a"], m["b"], m["pa"], m["pb"]), (m["b"], m["a"], m["pb"], m["pa"])):
            r = rows[me]
            res = result(pm, po)
            r["p"] += 1
            r["pf"] += pm
            r["pa"] += po
            r["pts"] += h2h_points(res)
            r[{"W": "w", "D": "d", "L": "l"}[res]] += 1
    ranked = sorted(rows.values(), key=lambda r: (-r["pts"], -r["pf"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked


def all_play(scores):
    """Each team's record if it had played every other team that gameweek."""
    out = {}
    for le, s in scores.items():
        others = [v for k, v in scores.items() if k != le]
        w = sum(s > o for o in others)
        d = sum(s == o for o in others)
        l = len(others) - w - d
        out[le] = {"w": w, "d": d, "l": l, "xpts": round((3 * w + d) / len(others), 3)}
    return out


def awards_for(gw_matches, teams):
    scores = {le: t["score"] for le, t in teams.items()}

    def tied(metric, best):
        return [le for le, v in metric.items() if v == best]

    hi, lo = max(scores.values()), min(scores.values())
    a = {
        "top_score": {"le": tied(scores, hi), "value": hi},
        "low_score": {"le": tied(scores, lo), "value": lo},
    }
    decided = [m for m in gw_matches if m["pa"] != m["pb"]]
    if decided:
        margin = max(abs(m["pa"] - m["pb"]) for m in decided)
        big = [m for m in decided if abs(m["pa"] - m["pb"]) == margin]
        a["biggest_win"] = {"matches": big, "value": margin}
        winners = {(m["a"] if m["pa"] > m["pb"] else m["b"]): max(m["pa"], m["pb"]) for m in decided}
        losers = {(m["b"] if m["pa"] > m["pb"] else m["a"]): min(m["pa"], m["pb"]) for m in decided}
        lw = min(winners.values())
        hl = max(losers.values())
        a["luckiest_win"] = {"le": tied(winners, lw), "value": lw}
        a["unluckiest_loss"] = {"le": tied(losers, hl), "value": hl}
    bench = {le: t["bench_pts"] for le, t in teams.items() if t.get("bench_pts") is not None}
    if bench:
        b = max(bench.values())
        a["bench_shame"] = {"le": tied(bench, b), "value": b}
    waiver = {le: t["waiver_pts"] for le, t in teams.items() if t.get("waiver_pts") is not None}
    if waiver:
        w = max(waiver.values())
        a["waiver_hero"] = {"le": tied(waiver, w), "value": w}
    best = None
    for le, t in teams.items():
        for p in t.get("xi", []):
            if best is None or p["pts"] > best["pts"]:
                best = {**p, "le": le}
    if best:
        a["best_player"] = best
    return a


# ---------------------------------------------------------------- gameweek snapshot

def acquisition_lookup(choices, transactions, entry_to_le):
    drafted = defaultdict(set)
    for c in choices:
        le = entry_to_le.get(c["entry"])
        if le:
            drafted[le].add(c["element"])
    acquired = defaultdict(list)  # (le, element) -> [(event, kind)]
    for t in transactions:
        if t["result"] != "a":
            continue
        le = entry_to_le.get(t["entry"])
        if le:
            acquired[(le, t["element_in"])].append((t["event"], t["kind"]))

    def how(le, element, gw):
        moves = [m for m in acquired.get((le, element), []) if m[0] <= gw]
        if moves:
            return "waiver" if max(moves)[1] == "w" else "free"
        if element in drafted[le]:
            return "draft"
        return "other"

    return how


def build_snapshot(gw, ctx):
    live = fetch(f"event/{gw}/live")
    pts = {int(k): v["stats"]["total_points"] for k, v in live["elements"].items()}
    kickoffs = [parse_time(f["kickoff_time"]) for f in live.get("fixtures", []) if f.get("kickoff_time")]
    last_kickoff = max(kickoffs) if kickoffs else None
    all_done = all(f.get("finished") for f in live.get("fixtures", []))

    gw_matches = [m for m in ctx["matches"] if m["event"] == gw]
    scores = {}
    for m in gw_matches:
        scores[m["a"]] = m["pa"]
        scores[m["b"]] = m["pb"]

    teams = {}
    for le, info in ctx["entries"].items():
        picks = fetch(f"entry/{info['entry_id']}/event/{gw}")
        time.sleep(0.15)
        xi = {p["element"] for p in picks["picks"] if p["position"] <= 11}
        bench = {p["element"] for p in picks["picks"] if p["position"] > 11}
        for s in picks.get("subs", []):
            xi.discard(s["element_out"]); bench.add(s["element_out"])
            bench.discard(s["element_in"]); xi.add(s["element_in"])

        def player(e):
            el = ctx["elements"].get(e, {})
            return {
                "id": e,
                "name": el.get("web_name", str(e)),
                "pos": el.get("pos", ""),
                "club": el.get("club", ""),
                "pts": pts.get(e, 0),
                "acq": ctx["how"](le, e, gw),
            }

        xi_players = sorted((player(e) for e in xi), key=lambda p: -p["pts"])
        bench_players = sorted((player(e) for e in bench), key=lambda p: -p["pts"])
        teams[le] = {
            "score": scores.get(le, 0),
            "calc": sum(p["pts"] for p in xi_players),
            "bench_pts": sum(p["pts"] for p in bench_players),
            "waiver_pts": sum(p["pts"] for p in xi_players if p["acq"] in ("waiver", "free")),
            "xi": xi_players,
            "bench": bench_players,
        }

    final_at = (last_kickoff + timedelta(hours=ctx["config"]["final_after_hours"])) if last_kickoff else None
    final = bool(all_done and final_at and NOW >= final_at)

    return {
        "gw": gw,
        "final": final,
        "final_at": final_at.isoformat() if final_at else None,
        "updated": NOW.isoformat(timespec="minutes"),
        "matches": gw_matches,
        "teams": teams,
        "all_play": all_play(scores),
        "table_after": table_from_matches(ctx["matches"], ctx["entries"], gw),
        "awards": awards_for(gw_matches, teams),
    }


# ---------------------------------------------------------------- trophy blocks

def build_blocks(config, snapshots, entries, matches, old_blocks):
    old = {b["id"]: b for b in (old_blocks or [])}
    finished = set(snapshots)
    out = []
    for blk in config["blocks"]:
        prev = old.get(blk["id"])
        if prev and prev.get("final"):
            out.append(prev)
            continue
        gws = list(range(blk["from"], blk["to"] + 1))
        b = {"id": blk["id"], "from": blk["from"], "to": blk["to"], "rule": blk["group"],
             "after_gw": blk.get("after_gw"), "group": None, "standings": [], "played": [],
             "status": "upcoming", "winners": [], "final": False}
        if blk["group"] == "all":
            b["group"] = list(entries)
        elif blk.get("after_gw") in finished:
            table = table_from_matches(matches, entries, blk["after_gw"])
            half = len(table) // 2
            b["group"] = [r["le"] for r in table[half:]]
            b["group_ranks"] = {r["le"]: r["rank"] for r in table[half:]}
        if b["group"] is None:
            out.append(b)
            continue
        played = [g for g in gws if g in finished]
        b["played"] = played
        rows = []
        for le in b["group"]:
            per = {g: snapshots[g]["teams"][le]["score"] for g in played}
            rows.append({"le": le, "total": sum(per.values()), "by_gw": per})
        rows.sort(key=lambda r: -r["total"])
        b["standings"] = rows
        if not played:
            b["status"] = "locked"
        elif len(played) < len(gws):
            b["status"] = "live"
        else:
            b["status"] = "finished"
            top = rows[0]["total"]
            b["winners"] = [r["le"] for r in rows if r["total"] == top]
            b["final"] = all(snapshots[g]["final"] for g in gws)
        out.append(b)
    return out


# ---------------------------------------------------------------- season aggregates

def season_stats(ctx, snapshots, details, game, transactions):
    entries = ctx["entries"]
    matches = [m for m in ctx["matches"] if m["event"] in snapshots]
    gws = sorted(snapshots)

    # luck: all-play expected points vs actual, cumulative per gameweek
    luck = {le: {"le": le, "w": 0, "d": 0, "l": 0, "xpts": 0.0, "pts": 0, "series": []} for le in entries}
    for g in gws:
        snap = snapshots[g]
        for m in snap["matches"]:
            for me, pm, po in ((m["a"], m["pa"], m["pb"]), (m["b"], m["pb"], m["pa"])):
                luck[me]["pts"] += h2h_points(result(pm, po))
        for le, ap in snap["all_play"].items():
            L = luck[int(le)]
            L["w"] += ap["w"]; L["d"] += ap["d"]; L["l"] += ap["l"]; L["xpts"] += ap["xpts"]
            L["series"].append({"gw": g, "xpts": round(L["xpts"], 2), "pts": L["pts"]})
    for L in luck.values():
        L["xpts"] = round(L["xpts"], 2)
        L["luck"] = round(L["pts"] - L["xpts"], 2)

    # official standings + form
    form = defaultdict(list)
    for m in sorted(matches, key=lambda m: m["event"]):
        form[m["a"]].append(result(m["pa"], m["pb"]))
        form[m["b"]].append(result(m["pb"], m["pa"]))
    standings = []
    for s in details["standings"]:
        le = s["league_entry"]
        standings.append({"le": le, "rank": s["rank"], "last_rank": s.get("last_rank"),
                          "w": s["matches_won"], "d": s["matches_drawn"], "l": s["matches_lost"],
                          "pf": s["points_for"], "pa": s["points_against"], "pts": s["total"],
                          "form": form[le][-5:]})

    # streaks
    streaks = {}
    for le in entries:
        seq = form[le]
        best_w = best_l = cur = 0
        kind = None
        for r in seq:
            cur = cur + 1 if r == kind else 1
            kind = r
            if r == "W": best_w = max(best_w, cur)
            if r == "L": best_l = max(best_l, cur)
        streaks[le] = {"current": {"kind": kind, "n": cur if kind else 0}, "best_win": best_w, "worst_loss": best_l}

    # points table and recent form (last 4 gameweeks)
    recent = gws[-4:]
    points_table = []
    for le in entries:
        per = [snapshots[g]["teams"][le]["score"] for g in gws]
        points_table.append({"le": le, "total": sum(per), "avg": round(sum(per) / len(per), 1) if per else 0,
                             "best": max(per) if per else 0, "worst": min(per) if per else 0,
                             "recent": sum(snapshots[g]["teams"][le]["score"] for g in recent),
                             "by_gw": per})
    points_table.sort(key=lambda r: -r["total"])

    # head-to-head records
    h2h = {le: {o: {"w": 0, "d": 0, "l": 0, "pf": 0, "pa": 0} for o in entries if o != le} for le in entries}
    for m in matches:
        for me, opp, pm, po in ((m["a"], m["b"], m["pa"], m["pb"]), (m["b"], m["a"], m["pb"], m["pa"])):
            r = h2h[me][opp]
            r[{"W": "w", "D": "d", "L": "l"}[result(pm, po)]] += 1
            r["pf"] += pm; r["pa"] += po

    # schedule swap: team A's scores against team B's fixtures
    opp_of = defaultdict(dict)
    for m in matches:
        opp_of[m["a"]][m["event"]] = m["b"]
        opp_of[m["b"]][m["event"]] = m["a"]
    score = {g: {le: t["score"] for le, t in snapshots[g]["teams"].items()} for g in gws}
    swap = {}
    for a in entries:
        swap[a] = {}
        for b in entries:
            total = 0
            for g in gws:
                o = opp_of[b].get(g)
                if o is None:
                    continue
                if o == a:
                    o = b
                total += h2h_points(result(score[g][a], score[g][o]))
            swap[a][b] = total

    # bench and waivers
    bench = []
    waiver = []
    pickups = defaultdict(lambda: {"pts": 0, "starts": 0})
    for le in entries:
        per = [(g, snapshots[g]["teams"][le]["bench_pts"]) for g in gws]
        worst = max(per, key=lambda x: x[1]) if per else (None, 0)
        bench.append({"le": le, "total": sum(p for _, p in per), "worst_gw": worst[0], "worst": worst[1]})
        wpts = sum(snapshots[g]["teams"][le]["waiver_pts"] for g in gws)
        total = sum(snapshots[g]["teams"][le]["score"] for g in gws)
        tx = [t for t in transactions if ctx["entry_to_le"].get(t["entry"]) == le]
        waiver.append({"le": le, "pts": wpts, "share": round(wpts / total, 3) if total else 0,
                       "claims_won": sum(1 for t in tx if t["kind"] == "w" and t["result"] == "a"),
                       "claims_lost": sum(1 for t in tx if t["kind"] == "w" and t["result"] != "a"),
                       "free_agents": sum(1 for t in tx if t["kind"] == "f" and t["result"] == "a")})
        for g in gws:
            for p in snapshots[g]["teams"][le]["xi"]:
                if p["acq"] in ("waiver", "free"):
                    k = (le, p["id"])
                    pickups[k]["pts"] += p["pts"]
                    pickups[k]["starts"] += 1
                    pickups[k].update({"le": le, "name": p["name"], "pos": p["pos"], "club": p["club"], "acq": p["acq"]})
    bench.sort(key=lambda r: -r["total"])
    waiver.sort(key=lambda r: -r["pts"])
    best_pickups = sorted(pickups.values(), key=lambda r: -r["pts"])[:10]

    # season records
    records = {}
    all_scores = [(g, le, s) for g in gws for le, s in ((int(k), v["score"]) for k, v in snapshots[g]["teams"].items())]
    if all_scores:
        hi = max(all_scores, key=lambda x: x[2]); lo = min(all_scores, key=lambda x: x[2])
        records["high_score"] = {"gw": hi[0], "le": hi[1], "value": hi[2]}
        records["low_score"] = {"gw": lo[0], "le": lo[1], "value": lo[2]}
    decided = [m for m in matches if m["pa"] != m["pb"]]
    if decided:
        big = max(decided, key=lambda m: abs(m["pa"] - m["pb"]))
        records["biggest_win"] = {**big, "value": abs(big["pa"] - big["pb"])}
        lw = min(decided, key=lambda m: max(m["pa"], m["pb"]))
        records["luckiest_win"] = {**lw, "value": max(lw["pa"], lw["pb"])}
        hl = max(decided, key=lambda m: min(m["pa"], m["pb"]))
        records["unluckiest_loss"] = {**hl, "value": min(hl["pa"], hl["pb"])}
    b_all = [(g, le, snapshots[g]["teams"][le]["bench_pts"]) for g in gws for le in entries]
    if b_all:
        bb = max(b_all, key=lambda x: x[2])
        records["bench_shame"] = {"gw": bb[0], "le": bb[1], "value": bb[2]}

    # award count per manager across the season
    honours = {le: defaultdict(int) for le in entries}
    for g in gws:
        for key, a in snapshots[g]["awards"].items():
            if key == "best_player":
                honours[a["le"]][key] += 1
            elif key == "biggest_win":
                for m in a["matches"]:
                    honours[m["a"] if m["pa"] > m["pb"] else m["b"]][key] += 1
            else:
                for le in a["le"]:
                    honours[le][key] += 1

    return {"standings": standings, "points_table": points_table, "luck": sorted(luck.values(), key=lambda r: -r["xpts"]),
            "streaks": streaks, "h2h": h2h, "schedule_swap": swap, "bench": bench, "waivers": waiver,
            "best_pickups": best_pickups, "records": records,
            "honours": {le: dict(v) for le, v in honours.items()}}


# ---------------------------------------------------------------- most moved players

def player_moves(choices, transactions, entry_to_le, boot, owners, limit=20):
    """Every pickup and drop per player, oldest first, plus who drafted them and who owns them now."""
    clubs = {t["id"]: t["short_name"] for t in boot["teams"]}
    pos = {t["id"]: t["singular_name_short"] for t in boot["element_types"]}
    info = {e["id"]: e for e in boot["elements"]}
    hist = defaultdict(list)
    for c in choices:
        le = entry_to_le.get(c["entry"])
        if le:
            hist[c["element"]].append({"t": c["choice_time"], "gw": 0, "type": "draft", "le": le})
    for t in sorted((t for t in transactions if t["result"] == "a"), key=lambda t: t["added"]):
        le = entry_to_le.get(t["entry"])
        if not le:
            continue
        kind = "waiver" if t["kind"] == "w" else "free"
        hist[t["element_in"]].append({"t": t["added"], "gw": t["event"], "type": "in", "kind": kind, "le": le})
        hist[t["element_out"]].append({"t": t["added"], "gw": t["event"], "type": "out", "le": le})

    rows = []
    for el, h in hist.items():
        h.sort(key=lambda x: x["t"])
        ins = sum(1 for x in h if x["type"] == "in")
        outs = sum(1 for x in h if x["type"] == "out")
        if ins + outs < 2:
            continue
        e = info.get(el, {})
        owner = owners.get(el)
        rows.append({
            "id": el, "name": e.get("web_name", str(el)), "club": clubs.get(e.get("team"), ""),
            "pos": pos.get(e.get("element_type"), ""), "pts": e.get("total_points", 0),
            "ins": ins, "outs": outs, "moves": ins + outs,
            "managers": len({x["le"] for x in h if x["type"] in ("in", "draft")}),
            "owner": entry_to_le.get(owner) if owner else None,
            "history": [{"gw": x["gw"], "type": x["type"], "le": x["le"], **({"kind": x["kind"]} if "kind" in x else {})} for x in h],
        })
    rows.sort(key=lambda r: (-r["moves"], -r["managers"], -r["pts"]))
    return rows[:limit]


# ---------------------------------------------------------------- main

def first_kickoff(boot, gw):
    fixtures = boot.get("fixtures") or {}
    games = fixtures.get(str(gw)) or fixtures.get(gw) or [] if isinstance(fixtures, dict) else [f for f in fixtures if f.get("event") == gw]
    times = sorted(f["kickoff_time"] for f in games if f.get("kickoff_time"))
    return times[0] if times else None


def main():
    config = read_json(os.path.join(DATA, "config.json"))
    league = config["league_id"]
    details = fetch(f"league/{league}/details")
    game = fetch("game")
    boot = fetch("bootstrap-static")
    draft_id = details["league"]["drafts"][0]["id"] if details["league"].get("drafts") else None
    choices = fetch(f"draft/{league}/choices")["choices"]
    transactions = fetch(f"draft/league/{league}/transactions")["transactions"]
    owners = {x["element"]: x["owner"] for x in fetch(f"league/{league}/element-status")["element_status"]}

    entries = {e["id"]: {"le": e["id"], "entry_id": e["entry_id"], "team": e["entry_name"],
                         "manager": e["player_first_name"], "short": e.get("short_name")}
               for e in details["league_entries"]}
    entry_to_le = {v["entry_id"]: k for k, v in entries.items()}
    clubs = {t["id"]: t["short_name"] for t in boot["teams"]}
    pos = {t["id"]: t["singular_name_short"] for t in boot["element_types"]}
    elements = {e["id"]: {"web_name": e["web_name"], "club": clubs.get(e["team"], ""), "pos": pos.get(e["element_type"], "")}
                for e in boot["elements"]}
    events = boot["events"]["data"] if isinstance(boot["events"], dict) else boot["events"]
    ev = {e["id"]: e for e in events}

    matches = [{"event": m["event"], "a": m["league_entry_1"], "b": m["league_entry_2"],
                "pa": m["league_entry_1_points"], "pb": m["league_entry_2_points"],
                "finished": m["finished"], "started": m["started"]} for m in details["matches"]]
    finished_matches = [m for m in matches if m["finished"]]
    ctx = {"config": config, "entries": entries, "entry_to_le": entry_to_le, "elements": elements,
           "matches": finished_matches, "how": acquisition_lookup(choices, transactions, entry_to_le)}

    finished_gws = sorted({m["event"] for m in finished_matches
                           if ev.get(m["event"], {}).get("finished")
                           and all(x["finished"] for x in matches if x["event"] == m["event"])})

    os.makedirs(GW_DIR, exist_ok=True)
    snapshots = {}
    changed = []
    for gw in finished_gws:
        path = os.path.join(GW_DIR, f"gw{gw:02d}.json")
        snap = read_json(path)
        if snap and snap.get("final"):
            snapshots[gw] = snap
            continue
        print(f"Building GW{gw} snapshot", flush=True)
        snap = build_snapshot(gw, ctx)
        if snap["teams"] and any(t["calc"] != t["score"] for t in snap["teams"].values()):
            bad = {entries[le]["manager"]: (t["calc"], t["score"]) for le, t in snap["teams"].items() if t["calc"] != t["score"]}
            print(f"  note: GW{gw} lineup sum differs from match score for {bad}", flush=True)
        # keep `updated` stable when nothing else changed, so unchanged runs don't commit
        old = read_json(path)
        if old and {k: v for k, v in old.items() if k != "updated"} == {k: v for k, v in snap.items() if k != "updated"}:
            snap["updated"] = old["updated"]
        if write_json(path, snap):
            changed.append(path)
        snapshots[gw] = snap

    # JSON object keys are strings after a round trip; normalise to int
    for snap in snapshots.values():
        snap["teams"] = {int(k): v for k, v in snap["teams"].items()}
        snap["all_play"] = {int(k): v for k, v in snap["all_play"].items()}

    blocks_path = os.path.join(DATA, "blocks.json")
    blocks = build_blocks(config, snapshots, entries, finished_matches, read_json(blocks_path, []))
    if write_json(blocks_path, blocks):
        changed.append(blocks_path)

    season = season_stats(ctx, snapshots, details, game, transactions)

    # the projection model runs every time: its public part (H2H chances, season simulation)
    # goes into current.json; the player-level part is encrypted below when ADV_PASSWORD is set
    adv = advanced.build(boot, sorted(snapshots), fetch, owners, entry_to_le, game.get("next_event"))
    I = adv.pop("_internal")
    squads = defaultdict(list)
    for pid, owner in owners.items():
        if owner in entry_to_le:
            squads[entry_to_le[owner]].append(pid)
    schedule = [{"event": m["event"], "a": m["a"], "b": m["b"]} for m in matches if not m["finished"] and m["event"] in I["targets"]]
    standings_now = {s["league_entry"]: {"pts": s["total"], "pf": s["points_for"]} for s in details["standings"]}
    calib = forecast.calibrate(I["live"], I["fixtures"], I["gws"], I["pos_of"], I["team_of"], I["elements"], I["ctx"],
                               snapshots, finished_matches)
    played = lambda le, a, b: sum(snapshots[g]["teams"][le]["score"] for g in range(a, b + 1) if g in snapshots)
    fc = forecast.run(I["proj_long"], I["targets"], I["pos_of"], dict(squads), schedule, standings_now, calib, blocks, played)
    short = {t["id"]: t["short_name"] for t in boot["teams"]}
    fc["special_rounds"] = [{"gw": r["gw"], "double": [short[x] for x in r["double"]], "blank": [short[x] for x in r["blank"]]}
                            for r in adv.pop("special_rounds")]
    fc["unscheduled"] = adv.pop("unscheduled")
    print(f"  forecast: favourite won {calib['fav_won']} of {calib['fav_n']} past matches, team score bias {calib['bias']:.1f}, spread {calib['sd']:.1f}", flush=True)


    cur = game["current_event"]
    nxt = game.get("next_event")
    live_gw = cur if cur and not game.get("current_event_finished") else None
    live_matches = [m for m in matches if live_gw and m["event"] == live_gw]
    next_matches = [m for m in matches if nxt and m["event"] == nxt]

    current = {
        "league": {"id": league, "name": details["league"]["name"], "season": config["season"],
                   "prize_kr": config["prize_kr"], "draft_id": draft_id},
        "managers": {le: {"team": e["team"], "manager": e["manager"], "short": e["short"]} for le, e in entries.items()},
        "game": {"current": cur, "current_finished": game.get("current_event_finished"), "next": nxt,
                 "waivers_processed": game.get("waivers_processed"),
                 "next_trades": ev.get(nxt, {}).get("trades_time") if nxt else None,
                 "next_waivers": ev.get(nxt, {}).get("waivers_time") if nxt else None,
                 "next_deadline": ev.get(nxt, {}).get("deadline_time") if nxt else None,
                 "next_kickoff": first_kickoff(boot, nxt)},
        "gameweeks": [{"gw": g, "final": snapshots[g]["final"]} for g in sorted(snapshots)],
        "latest_gw": max(snapshots) if snapshots else None,
        "live": {"gw": live_gw, "matches": live_matches} if live_gw else None,
        "next_round": {"gw": nxt, "matches": next_matches} if nxt else None,
        "blocks": blocks,
        "forecast": fc,
        "most_moved": player_moves(choices, transactions, entry_to_le, boot, owners),
        **season,
    }
    # password-protected advanced player data (encrypted; skipped without ADV_PASSWORD)
    adv_path = os.path.join(DATA, "adv.enc.json")
    if os.environ.get("ADV_PASSWORD"):
        adv["managers"] = {le: e["manager"] for le, e in entries.items()}
        adv["teams_of"] = {le: e["team"] for le, e in entries.items()}
        adv["entry_ids"] = {le: e["entry_id"] for le, e in entries.items()}
        adv["game"] = {"next": game.get("next_event"), "waivers_processed": game.get("waivers_processed"),
                       "next_waivers": ev.get(game.get("next_event"), {}).get("waivers_time"),
                       "next_deadline": ev.get(game.get("next_event"), {}).get("deadline_time")}
        if advanced.write(adv_path, adv, read_json, write_json):
            changed.append(adv_path)

    cur_path = os.path.join(DATA, "current.json")
    old = read_json(cur_path)
    content_changed = changed or not old or {k: v for k, v in old.items() if k != "updated"} != json.loads(json.dumps(current))
    current["updated"] = NOW.isoformat(timespec="minutes") if content_changed or not old else old.get("updated")
    if write_json(cur_path, current):
        changed.append(cur_path)

    print(f"Done. {len(snapshots)} gameweeks, {len(changed)} files changed.")


if __name__ == "__main__":
    sys.exit(main())
