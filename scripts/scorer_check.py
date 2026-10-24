"""Can the FPL model price "anytime goalscorer"? A check on the 2025/26 replay, no odds needed.

Every round is predicted from the rounds before it only (replay.Season). A player's chance to score
is 1 - exp(-xG), xG being the model's expected goals for him in the match: his expected minutes,
xG/90, penalties and the match's expected goals. Only players whose team plays once in the round.

Compared with a plain baseline: 1 - exp(-goals per round so far).
Measured: Brier score and log loss (lower is better), calibration (said 30%, scored 30%?) and the
model's top 10 per round, the players a goalscorer tip would pick. Rounds 20-38 are the held-out
half the model's settings were not tuned on.

    python scripts/scorer_check.py
"""

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model  # noqa: E402
import replay  # noqa: E402

BINS = [0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "scorer_check.json")   # shown on the Betting tab


def rows(S, rounds):
    out = []
    for gw in rounds:
        known = [g for g in S.gws if g < gw]
        if len(known) < 3:
            continue
        _, det, _ = S.predict(gw, model.ALL)
        games = {}
        for f in S.fixtures:
            if f["event"] == gw:
                games[f["team_h"]] = games.get(f["team_h"], 0) + 1
                games[f["team_a"]] = games.get(f["team_a"], 0) + 1
        for c, d in det.items():
            if games.get(S.team_of[c]) != 1:
                continue
            st = S.live[gw].get(c, {})
            rate = sum(S.live[g].get(c, {}).get("goals_scored", 0) for g in known) / len(known)
            out.append({"gw": gw, "pid": c, "pos": S.pos_of[c], "p": 1 - math.exp(-d["xg"]),
                        "base": 1 - math.exp(-rate), "y": int(st.get("goals_scored", 0) > 0), "min": st.get("minutes", 0)})
    return out


def scores(r, key):
    p = np.clip(np.array([x[key] for x in r]), 1e-4, 1 - 1e-4)
    y = np.array([x["y"] for x in r])
    return float(np.mean((p - y) ** 2)), float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def report(r, title):
    print(f"\n== {title}: {len(r)} player-matches, {sum(x['y'] for x in r)} with a goal")
    for key, name in (("p", "model"), ("base", "baseline")):
        b, l = scores(r, key)
        print(f"  {name:<9} Brier {b:.4f}  log loss {l:.4f}")
    print("  calibration (model):  said -> scored   n")
    for lo, hi in zip(BINS, BINS[1:]):
        sel = [x for x in r if lo <= x["p"] < hi]
        if sel:
            print(f"    {lo:>4.0%}-{hi:<4.0%}  {np.mean([x['p'] for x in sel]):6.1%} -> {np.mean([x['y'] for x in sel]):6.1%}  {len(sel)}")
    top = []
    for gw in sorted({x["gw"] for x in r}):
        top += sorted((x for x in r if x["gw"] == gw), key=lambda x: -x["p"])[:10]
    print(f"  top 10 per round: said {np.mean([x['p'] for x in top]):.1%}, scored {np.mean([x['y'] for x in top]):.1%}"
          f" ({len(top)} picks; {np.mean([x['min'] == 0 for x in top]):.1%} did not play)")
    for pos, name in ((4, "FWD"), (3, "MID"), (2, "DEF")):
        sel = [x for x in r if x["pos"] == pos and x["p"] >= 0.1]
        if sel:
            print(f"  {name} with p >= 10%: said {np.mean([x['p'] for x in sel]):.1%}, scored {np.mean([x['y'] for x in sel]):.1%} (n {len(sel)})")


def summary(r):
    """The numbers the Betting tab shows: midfielders and forwards only, like the tips."""
    r = [x for x in r if x["pos"] in (3, 4)]
    top = []
    for gw in sorted({x["gw"] for x in r}):
        top += sorted((x for x in r if x["gw"] == gw), key=lambda x: -x["p"])[:3]
    cal = []
    for lo, hi in zip(BINS, BINS[1:]):
        sel = [x for x in r if lo <= x["p"] < hi]
        if len(sel) >= 20:
            cal.append({"lo": lo, "hi": hi, "n": len(sel), "pred": round(float(np.mean([x["p"] for x in sel])), 4),
                        "obs": round(float(np.mean([x["y"] for x in sel])), 4)})
    b, l = scores(r, "p")
    bb, lb = scores(r, "base")
    return {"n": len(r), "top3": {"n": len(top), "expected": round(float(np.mean([x["p"] for x in top])), 4),
                                  "hit": round(float(np.mean([x["y"] for x in top])), 4)},
            "cal": cal, "logloss": round(l, 4), "logloss_base": round(lb, 4), "brier": round(b, 4), "brier_base": round(bb, 4)}


def main():
    S = replay.Season(replay.load())
    r = rows(S, range(4, 39))
    report(r, "rounds 4-38")
    held = [x for x in r if x["gw"] >= 20]
    report(held, "held out, rounds 20-38")
    out = {"season": replay.SEASON, "rounds": [20, 38], **summary(held)}
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
    print("\nsummary:", json.dumps(out))


if __name__ == "__main__":
    main()
