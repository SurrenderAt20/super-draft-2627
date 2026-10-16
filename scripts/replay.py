"""Replay the 2025/26 season to test the model on a large, honest sample.

Every round is predicted from the rounds before it only, with 2024/25 as the starting point,
injury status and penalty / set-piece takers as they were before the round, and bookmakers'
pre-match odds. Data: FPL-Core-Insights (2024/25, 2025/26) and football-data.co.uk.

Run:  python scripts/replay.py            builds the replay data (cached) and prints the report
The result is written to scripts/cache/replay_report.json and shown on the site.

Known limits: 2024/25 has no DefCon, saves, cards or starts, so the starting point for those
is the position average; a player's club is his club at the end of 2025/26; the set-piece
effect is left out (it was measured on 2025/26 itself).
"""

import csv
import io
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history  # noqa: E402
import model  # noqa: E402
import odds as odds_src  # noqa: E402

CORE = history.CORE
SEASON, PRIOR = "2025-2026", "2024-2025"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_CACHE = os.path.join(HERE, "cache", "replay_2025-26.json")
REPORT = os.path.join(HERE, "cache", "replay_report.json")
POS = {"Goalkeeper": 1, "Defender": 2, "Midfielder": 3, "Forward": 4}
CUM = {"minutes": "minutes", "starts": "starts", "goals_scored": "goals_scored", "assists": "assists",
       "clean_sheets": "clean_sheets", "goals_conceded": "goals_conceded", "saves": "saves", "bonus": "bonus",
       "yellow_cards": "yellow_cards", "red_cards": "red_cards", "own_goals": "own_goals",
       "penalties_saved": "penalties_saved", "penalties_missed": "penalties_missed",
       "expected_goals": "expected_goals", "expected_assists": "expected_assists",
       "expected_goals_conceded": "expected_goals_conceded", "defensive_contribution": "defensive_contribution"}
f = history._f


def _csv(url):
    return history._csv(url)


def build_data():
    """Everything the model needs for 2025/26, in the same shapes as the live pipeline."""
    players = {p["player_id"]: p for p in _csv(f"{CORE}/{SEASON}/players.csv")}
    snaps = defaultdict(dict)
    for r in _csv(f"{CORE}/{SEASON}/playerstats.csv"):
        snaps[r["id"]][int(f(r["gw"]))] = r
    live = defaultdict(dict)       # gw -> code -> stats (per round)
    state = defaultdict(dict)      # gw -> code -> status/orders as shown after that round
    pos_of, team_of = {}, {}
    for pid, by in snaps.items():
        p = players.get(pid)
        if not p or p.get("position") not in POS:
            continue
        code = int(p["player_code"])
        pos_of[code], team_of[code] = POS[p["position"]], int(f(p["team_code"]))
        prev = {k: 0.0 for k in CUM}
        for gw in sorted(by):
            r = by[gw]
            cur = {k: f(r.get(col)) for k, col in CUM.items()}
            d = {k: round(max(0.0, cur[k] - prev[k]), 3) for k in CUM}
            prev = cur
            d["total_points"] = int(f(r.get("event_points")))
            if d["minutes"] > 0 or d["total_points"]:
                live[gw][code] = d
            ch = r.get("chance_of_playing_next_round")
            state[gw][code] = {"status": r.get("status") or "a", "chance": f(ch) if ch not in (None, "") else None,
                               "pen": int(f(r.get("penalties_order"))) or None,
                               "corner": int(f(r.get("corners_and_indirect_freekicks_order"))) or None,
                               "fk": int(f(r.get("direct_freekicks_order"))) or None}

    prem, euro = history.euro_and_prem(SEASON, range(1, 39))
    scores = {}
    for gw in range(1, 39):
        for m in _csv(f"{CORE}/{SEASON}/By%20Gameweek/GW{gw}/matches.csv"):
            scores[m.get("match_id")] = (m.get("home_score"), m.get("away_score"))
    fixtures = []
    for i, m in enumerate(prem):
        hs, as_ = scores.get(m["id"], (None, None))
        fixtures.append({"id": i + 1, "event": m["gw"], "team_h": int(m["home"]), "team_a": int(m["away"]),
                         "finished": m["finished"], "kickoff_time": m["t"].isoformat() if m["t"] else None,
                         "team_h_score": int(f(hs)) if hs not in (None, "") else None,
                         "team_a_score": int(f(as_)) if as_ not in (None, "") else None})

    # penalty attempts per player per round (for open-play xG)
    code_of = {pid: int(p["player_code"]) for pid, p in players.items()}
    pens = defaultdict(dict)
    for gw in range(1, 39):
        for r in _csv(f"{CORE}/{SEASON}/By%20Gameweek/GW{gw}/playermatchstats.csv"):
            if history._kind(r.get("match_id")) != "prem":
                continue
            c = code_of.get(r.get("player_id"))
            n = int(f(r.get("penalties_scored")) + f(r.get("penalties_missed")))
            if c and n:
                pens[str(c)][gw] = pens[str(c)].get(gw, 0) + n

    # bookmakers' pre-match odds -> expected goals per match
    teams = {t["name"].lower(): int(t["code"]) for t in _csv(f"{CORE}/{SEASON}/teams.csv")}
    alias = dict(odds_src.ALIAS, **{"man united": "man utd", "tottenham": "spurs", "wolves": "wolves", "west ham": "west ham"})
    find = lambda n: teams.get(alias.get(n.strip().lower(), n.strip().lower()))
    raw = odds_src._get("https://www.football-data.co.uk/mmz4281/2526/E0.csv")
    odds = {}
    for r in odds_src._fd_rows(raw):
        h, a, g = find(r["HomeTeam"]), find(r["AwayTeam"]), odds_src._fd_goals(r)
        if h and a and g:
            odds[f"{h}-{a}"] = g

    # starting point: 2024/25 (no DefCon, saves, cards or starts in that file)
    older = history.older_season()
    prior_players = {c: {"pos": o["pos"], "team": o["team"], "mi": o["mi"], "xg": o["xg"], "xa": o["xa"],
                         "bo": o["bo"], "pens": o["pens"]} for c, o in older.items()}
    p_prem, _ = history.euro_and_prem(PRIOR, range(1, 39))
    if not p_prem:   # 2024/25 keeps matches in matches/GWn/
        for gw in range(1, 39):
            for m in _csv(f"{CORE}/{PRIOR}/matches/GW{gw}/matches.csv"):
                if history._kind(m.get("match_id")) in ("prem", "") and str(m.get("finished")).lower() in ("true", "1"):
                    p_prem.append({"home": str(int(f(m["home_team"]))), "away": str(int(f(m["away_team"]))),
                                   "xgh": f(m.get("home_expected_goals_xg")), "xga": f(m.get("away_expected_goals_xg")), "finished": True})
    team_matches = [(m["home"], m["away"], 1, m["xgh"]) for m in p_prem] + [(m["away"], m["home"], 0, m["xga"]) for m in p_prem]
    pens_rate = sum(o["pens"] for o in older.values()) / max(1, len(team_matches))

    data = {"live": {gw: {str(c): s for c, s in d.items()} for gw, d in live.items()},
            "state": {gw: {str(c): s for c, s in d.items()} for gw, d in state.items()},
            "pos_of": {str(c): v for c, v in pos_of.items()}, "team_of": {str(c): v for c, v in team_of.items()},
            "fixtures": fixtures, "euro": [{"home": e["home"], "away": e["away"], "t": e["t"].isoformat() if e["t"] else None} for e in euro],
            "pens": pens, "odds": odds,
            "prior": {"players": prior_players, "team_matches": team_matches, "pens_per_team_match": round(pens_rate, 4)}}
    os.makedirs(os.path.dirname(DATA_CACHE), exist_ok=True)
    with open(DATA_CACHE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))
    print(f"replay data: {len(pos_of)} players, {len(fixtures)} matches, {len(odds)} with odds, "
          f"{len(prior_players)} players with 2024/25 data", flush=True)
    return data


def load():
    if os.path.exists(DATA_CACHE):
        with open(DATA_CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    return build_data()


class Season:
    """The replay data in the shapes model.project() expects."""

    def __init__(self, d):
        self.live = {int(gw): {int(c): s for c, s in v.items()} for gw, v in d["live"].items()}
        self.state = {int(gw): {int(c): s for c, s in v.items()} for gw, v in d["state"].items()}
        self.pos_of = {int(c): v for c, v in d["pos_of"].items()}
        self.team_of = {int(c): v for c, v in d["team_of"].items()}
        self.fixtures = d["fixtures"]
        self.gws = sorted(g for g in self.live if any(f_["event"] == g for f_ in self.fixtures))
        for gw in range(1, 39):
            self.live.setdefault(gw, {})
        teams = sorted(set(self.team_of.values()))
        boot = {"elements": [{"id": c, "code": c, "team": t, "element_type": self.pos_of[c]} for c, t in self.team_of.items()],
                "teams": [{"id": t, "code": t} for t in teams]}
        euro = [{"home": e["home"], "away": e["away"], "t": history._t(e["t"])} for e in d["euro"]]
        rounds = defaultdict(dict)
        for gw, st in self.state.items():
            for c, s in st.items():
                rounds[str(c)][gw] = {"status": s["status"], "chance": s["chance"], "corner": s["corner"], "fk": s["fk"], "mi": 0}
        pens = {c: {int(g): n for g, n in v.items()} for c, v in d["pens"].items()}
        now = {"euro": euro, "pens": pens, "rounds": rounds}
        last = {"players": d["prior"]["players"], "team_matches": [tuple(x) for x in d["prior"]["team_matches"]],
                "pens_per_team_match": d["prior"]["pens_per_team_match"], "rotation": {}, "setpiece": {}, "older": {}}
        self.ctx = model.context(boot, self.gws, self.fixtures, last, now)
        self.ctx["odds"] = {}
        for fx in self.fixtures:
            o = d["odds"].get(f"{fx['team_h']}-{fx['team_a']}")
            if o:
                self.ctx["odds"][fx["id"]] = tuple(o)
        self.ctx["odds_w"] = 1.0
        self.teams = teams

    def elements_before(self, gw):
        """Penalty / set-piece takers and status as FPL showed them after the previous round."""
        st = self.state.get(gw - 1, {})
        return {c: {"status": st.get(c, {}).get("status", "a"), "chance_of_playing_next_round": st.get(c, {}).get("chance"),
                    "penalties_order": st.get(c, {}).get("pen"), "corners_and_indirect_freekicks_order": st.get(c, {}).get("corner"),
                    "direct_freekicks_order": st.get(c, {}).get("fk")} for c in self.pos_of}

    def predict(self, gw, use, horizon=1):
        known = [g for g in self.gws if g < gw]
        targets = [g for g in range(gw, min(39, gw + horizon))]
        el = self.elements_before(gw)
        self.ctx["setp_now"] = {c: (e["corners_and_indirect_freekicks_order"], e["direct_freekicks_order"]) for c, e in el.items()}
        pr, det, _ = model.project(self.live, self.fixtures, known, targets, self.pos_of, self.team_of, el, self.teams,
                                   self.ctx, use, avail="hist")
        return pr, det, targets


# ---------------------------------------------------------------- metrics

def pair_acc(p, a):
    dp = p[:, None] - p[None, :]
    da = a[:, None] - a[None, :]
    m = np.triu((da != 0) & (dp != 0), 1)
    return float(np.mean(np.sign(dp[m]) == np.sign(da[m]))) if m.any() else float("nan")


def evaluate(S, variants, rounds, horizon=3):
    """Per round: single-round point error, minutes Brier, and pairwise accuracy over the next `horizon`
    rounds. Every predictor is scored on the same players. Rounds are the unit for intervals and p-values."""
    per = {k: [] for k in list(variants) + ["form"]}
    cs = []
    gaps = []   # (predicted gap per round, correct?) for the "new" model, pooled over rounds
    for gw in rounds:
        known = [g for g in S.gws if g < gw]
        if len(known) < 3:
            continue
        preds = {name: S.predict(gw, use, horizon) for name, use in variants.items()}
        targets = next(iter(preds.values()))[2]
        # players who played in the rounds before or in the target rounds: the same set for everyone
        pl = [c for c in S.pos_of if any(S.live[g].get(c, {}).get("minutes", 0) > 0 for g in known[-6:] + targets)]
        act1 = np.array([S.live[gw].get(c, {}).get("total_points", 0) for c in pl], float)
        acth = np.array([sum(S.live[g].get(c, {}).get("total_points", 0) for g in targets) for c in pl], float)
        minsh = np.array([sum(S.live[g].get(c, {}).get("minutes", 0) for g in targets) for c in pl], float)
        rank_set = minsh >= 45 * len(targets)
        w = model.RECENT_W[-len(known[-4:]):]
        form1 = np.array([sum(wi * S.live[g].get(c, {}).get("total_points", 0) for wi, g in zip(w, known[-4:])) / sum(w) for c in pl])
        per["form"].append({"gw": gw, "mae": float(np.mean(np.abs(form1 - act1))), "rmse": float(np.sqrt(np.mean((form1 - act1) ** 2))), "pair": pair_acc(form1[rank_set] * len(targets), acth[rank_set])})
        for name, (pr, det, _) in preds.items():
            p1 = np.array([pr[c][0] if c in pr else 0.0 for c in pl])
            ph = np.array([sum(pr[c]) if c in pr else 0.0 for c in pl])
            mi = np.array([S.live[gw].get(c, {}).get("minutes", 0) for c in pl], float)
            p60 = np.array([det[c]["p60"] if c in det else 0.0 for c in pl])
            if name == "new":
                pr_h, a_h = ph[rank_set], acth[rank_set]
                dp = pr_h[:, None] - pr_h[None, :]
                da = a_h[:, None] - a_h[None, :]
                m = np.triu((da != 0) & (dp != 0), 1)
                gaps += list(zip((np.abs(dp[m]) / len(targets)).tolist(), (np.sign(dp[m]) == np.sign(da[m])).tolist()))
            per[name].append({"gw": gw, "mae": float(np.mean(np.abs(p1 - act1))), "rmse": float(np.sqrt(np.mean((p1 - act1) ** 2))), "bias": float(np.mean(p1 - act1)),
                              "brier60": float(np.mean((p60 - (mi >= 60)) ** 2)), "pair": pair_acc(ph[rank_set], acth[rank_set])})
            if name == "new":
                gk = {}
                for c, pos in S.pos_of.items():
                    if pos == 1 and c in det:
                        gk.setdefault(S.team_of[c], det[c]["cs"])
                for fx in S.fixtures:
                    if fx["event"] != gw or fx["team_h_score"] is None:
                        continue
                    for team, conceded in ((fx["team_h"], fx["team_a_score"]), (fx["team_a"], fx["team_h_score"])):
                        if team in gk:
                            cs.append((gk[team], 1.0 if conceded == 0 else 0.0))
    evaluate.gaps = gaps
    return per, cs


def summarise(per, cs, base="old", new="new"):
    rng = np.random.default_rng(5)
    out = {}
    for k, rows in per.items():
        if not rows:
            continue
        out[k] = {m: round(float(np.nanmean([r[m] for r in rows])), 4) for m in rows[0] if m != "gw"}
        out[k]["rounds"] = len(rows)
    for other in (base, "form"):
        a = np.array([r["pair"] for r in per[new]])
        b = np.array([r["pair"] for r in per[other]])
        d = a - b
        boots = [np.nanmean(rng.choice(d, size=len(d))) for _ in range(4000)]
        out[f"{new}_vs_{other}"] = {"diff_pair": round(float(np.nanmean(d)), 4),
                                    "lo": round(float(np.percentile(boots, 5)), 4), "hi": round(float(np.percentile(boots, 95)), 4),
                                    "p_value": round(float(np.mean(np.array(boots) <= 0)), 4), "better_rounds": int(np.sum(d > 0)), "rounds": len(d)}
        if other == base:
            dm = np.array([r["mae"] for r in per[other]]) - np.array([r["mae"] for r in per[new]])
            out[f"{new}_vs_{other}"]["mae_gain"] = round(float(np.mean(dm)), 4)
            dr = np.array([r["rmse"] for r in per[other]]) - np.array([r["rmse"] for r in per[new]])
            boots_r = [np.mean(rng.choice(dr, size=len(dr))) for _ in range(4000)]
            out[f"{new}_vs_{other}"]["rmse_gain"] = round(float(np.mean(dr)), 4)
            out[f"{new}_vs_{other}"]["rmse_p_value"] = round(float(np.mean(np.array(boots_r) <= 0)), 4)
    if cs:
        base_rate = sum(y for _, y in cs) / len(cs)
        bins = []
        for lo, hi in ((0, .2), (.2, .3), (.3, .4), (.4, .5), (.5, 1.01)):
            sel = [(p, y) for p, y in cs if lo <= p < hi]
            if sel:
                bins.append({"lo": lo, "hi": min(hi, 1.0), "pred": round(sum(p for p, _ in sel) / len(sel), 3),
                             "obs": round(sum(y for _, y in sel) / len(sel), 3), "n": len(sel)})
        out["clean_sheets"] = {"n": len(cs), "brier": round(sum((p - y) ** 2 for p, y in cs) / len(cs), 4),
                               "brier_flat": round(sum((base_rate - y) ** 2 for _, y in cs) / len(cs), 4), "calibration": bins}
    return out


GAP_EDGES = [0.0, 0.5, 1.0, 2.0, 3.0]   # predicted difference per round, lower edges


def confidence_table(S, rounds):
    """How often the model was right when it put player A above player B, by horizon, predicted gap
    per round, whether both were regular starters (240+ minutes in the last four rounds) and whether
    they play the same position. Counted, not stored per pair."""
    table = {}
    for Hk in (1, 3, 6, 10, "season"):
        cnt = {}
        for gw in rounds:
            known = [g for g in S.gws if g < gw]
            if len(known) < 3:
                continue
            # "season": every round left, from rounds with at least ten to go
            H = 39 - gw if Hk == "season" else Hk
            if Hk == "season" and H < 10:
                continue
            pr, _, tg = S.predict(gw, model.ALL, H)
            if len(tg) < H:
                continue
            pl = [c for c in S.pos_of if sum(S.live[g].get(c, {}).get("minutes", 0) for g in tg) >= 45 * len(tg)]
            p = np.array([sum(pr[c]) for c in pl])
            a = np.array([sum(S.live[g].get(c, {}).get("total_points", 0) for g in tg) for c in pl], float)
            reg = np.array([sum(S.live[g].get(c, {}).get("minutes", 0) for g in known[-4:]) >= 240 for c in pl])
            pos = np.array([S.pos_of[c] for c in pl])
            dp, da = p[:, None] - p[None, :], a[:, None] - a[None, :]
            m = np.triu((da != 0) & (dp != 0), 1)
            gap = np.abs(dp)[m] / H
            ok = (np.sign(dp) == np.sign(da))[m]
            both = (reg[:, None] & reg[None, :])[m]
            same = (pos[:, None] == pos[None, :])[m]
            b = np.searchsorted(GAP_EDGES, gap, side="right") - 1
            for gi in range(len(GAP_EDGES)):
                for rg in (0, 1):
                    for sp in (0, 1):
                        sel = (b == gi) & (both == bool(rg)) & (same == bool(sp))
                        n = int(sel.sum())
                        if n:
                            k = f"{gi}|{rg}|{sp}"
                            c = cnt.setdefault(k, [0, 0])
                            c[0] += int(ok[sel].sum())
                            c[1] += n
        table[str(Hk)] = {k: {"acc": round(v[0] / v[1], 3), "n": v[1]} for k, v in cnt.items()}
    return {"gap_edges": GAP_EDGES, "cells": table, "rounds": [min(rounds), max(rounds)],
            "regular": "240+ minutes in the last four rounds"}


def report():
    """Full-season replay (rounds 4-38) and the held-out half (20-38) the settings were not tuned on."""
    S = Season(load())
    variants = {"old": model.OLD_MODEL, "new": model.ALL}
    per, cs = evaluate(S, variants, range(4, 39))
    full = summarise(per, cs)
    per_t, _ = evaluate(S, variants, range(20, 39))
    gaps = evaluate.gaps
    held = summarise(per_t, [])
    buckets = []
    for lo, hi in ((0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 99)):
        sel = [c for g, c in gaps if lo <= g < hi]
        if sel:
            buckets.append({"lo": lo, "hi": hi if hi < 99 else None, "acc": round(sum(sel) / len(sel), 3), "n": len(sel)})
    conf = confidence_table(S, range(4, 39))
    from datetime import datetime, timezone
    rep = {"season": SEASON, "prior": PRIOR, "made": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "full": full, "held_out": held, "held_out_rounds": [20, 38], "tuned_on_rounds": [4, 19],
           "gap_buckets": buckets, "players": len(S.pos_of), "confidence": conf,
           "settings": {k: getattr(model, k) for k in ("K_MIN", "RIDGE", "K_LAST_MIN", "MIN_K", "CALIB_K", "TEAM_REGRESS")}}
    with open(REPORT, "w", encoding="utf-8", newline=chr(10)) as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps({k: rep[k] for k in ("held_out", "gap_buckets")}, indent=1))
    return rep


if __name__ == "__main__":
    report()
