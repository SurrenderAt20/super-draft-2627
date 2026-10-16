"""Public forecasts: H2H win chances for the coming round and a season simulation.

Each team's expected score in a round is the expected points of its best XI (from the
projection model). How far real scores land from that is measured on the rounds already
played: every past round is predicted from the rounds before it with the squads of the time,
which gives a bias and a spread. Scores are then simulated as normal draws around the
expectation, rounded to whole points (so draws can happen), many thousand times.

Rounds far ahead assume today's squads; waivers and trades will change them.
"""

import numpy as np

import model

FORM = {1: (1, 1), 2: (3, 5), 3: (2, 5), 4: (1, 3)}
SIMS = 20000
# Squads change through waivers and trades, which today's projections cannot see. Each simulation
# gives every team a lasting offset (points per round) to reflect that. This is an assumption,
# not a measured value, and it is stated on the page.
DRIFT_SD = 3.0


def best_xi_total(xps):
    """xps: list of (pos, xp). Best XI: 1 GK, at least 3 DEF, 2 MID, 1 FWD, 11 in all."""
    by = {1: [], 2: [], 3: [], 4: []}
    for pos, v in xps:
        by[pos].append(v)
    for l in by.values():
        l.sort(reverse=True)
    total, count, rest = 0.0, {}, []
    for pos, (lo, hi) in FORM.items():
        take = by[pos][:lo]
        total += sum(take)
        count[pos] = len(take)
        rest += [(v, pos) for v in by[pos][lo:]]
    picked = sum(count.values())
    for v, pos in sorted(rest, reverse=True):
        if picked >= 11:
            break
        if count[pos] < FORM[pos][1]:
            total += v
            count[pos] += 1
            picked += 1
    return total


def calibrate(live, fixtures, gws, pos_of, team_of, elements, ctx, snapshots, matches):
    """Predict each past round from the rounds before it, using the squads of that round.
    Returns bias and spread of team scores, and how often the favourite won."""
    resid, fav, n = [], 0, 0
    for i, gw in enumerate(gws):
        if i < 2:
            continue
        pred, _, _ = model.project(live, fixtures, gws[:i], [gw], pos_of, team_of, elements, None, ctx, model.ALL, avail="hist")
        snap = snapshots[gw]
        exp = {}
        for le, t in snap["teams"].items():
            ids = [p["id"] for p in t["xi"] + t["bench"]]
            exp[int(le)] = best_xi_total([(pos_of[pid], pred[pid][0]) for pid in ids if pid in pos_of])
            resid.append(t["score"] - exp[int(le)])
        for m in (m for m in matches if m["event"] == gw):
            if m["pa"] == m["pb"] or exp[m["a"]] == exp[m["b"]]:
                continue
            n += 1
            fav += (exp[m["a"]] > exp[m["b"]]) == (m["pa"] > m["pb"])
    r = np.array(resid)
    return {"bias": float(r.mean()) if len(r) else 0.0, "sd": float(r.std(ddof=1)) if len(r) > 2 else 15.0,
            "fav_won": fav, "fav_n": n, "rounds": gws[2:]}


def run(proj_long, targets, pos_of, squads, schedule, standings, calib, blocks, played_scores):
    """proj_long: pid -> xP per round in `targets`. squads: le -> [pid].
    schedule: future H2H matches [{event, a, b}]. standings: le -> {pts, pf}."""
    rng = np.random.default_rng(7)
    teams = sorted(squads)
    idx = {le: i for i, le in enumerate(teams)}
    mu = {}
    for j, gw in enumerate(targets):
        for le in teams:
            xps = [(pos_of[pid], proj_long.get(pid, [0] * len(targets))[j]) for pid in squads[le]]
            mu[(le, gw)] = best_xi_total(xps) + calib["bias"]
    sd = calib["sd"]

    # simulate every remaining round's scores for every team
    gws = [g for g in targets if any(m["event"] == g for m in schedule)]
    drift = rng.normal(0, DRIFT_SD, size=(SIMS, len(teams)))
    scores = {}
    for k, g in enumerate(gws):
        # the lasting offset grows in over the first rounds: next week's squads are mostly known
        w = min(1.0, k / 4)
        scores[g] = np.rint(rng.normal([mu[(le, g)] for le in teams], sd, size=(SIMS, len(teams))) + w * drift)

    pts = np.tile(np.array([standings[le]["pts"] for le in teams], float), (SIMS, 1))
    pf = np.tile(np.array([standings[le]["pf"] for le in teams], float), (SIMS, 1))
    next_round = []
    for g in gws:
        s = scores[g]
        pf += s
        for m in (m for m in schedule if m["event"] == g):
            a, b = idx[m["a"]], idx[m["b"]]
            win, draw = s[:, a] > s[:, b], s[:, a] == s[:, b]
            pts[:, a] += 3 * win + draw
            pts[:, b] += 3 * (~win & ~draw) + draw
            if g == gws[0]:
                next_round.append({"a": m["a"], "b": m["b"], "ea": round(mu[(m["a"], g)], 1), "eb": round(mu[(m["b"], g)], 1),
                                   "pa": round(float(win.mean()), 3), "pd": round(float(draw.mean()), 3),
                                   "pb": round(float((~win & ~draw).mean()), 3)})

    # final rank per simulation: H2H points, then points scored
    order = np.argsort(-(pts * 10000 + pf), axis=1)
    rank = np.empty_like(order)
    rank[np.arange(SIMS)[:, None], order] = np.arange(len(teams))[None, :]
    season = []
    for le in teams:
        i = idx[le]
        dist = np.bincount(rank[:, i], minlength=len(teams)) / SIMS
        season.append({"le": le, "exp_pts": round(float(pts[:, i].mean()), 1), "exp_rank": round(float(rank[:, i].mean() + 1), 2),
                       "p_first": round(float(dist[0]), 3), "p_top3": round(float(dist[:3].sum()), 3),
                       "p_last": round(float(dist[-1]), 3), "dist": [round(float(x), 3) for x in dist]})
    season.sort(key=lambda r: r["exp_rank"])

    # current bottom-half trophy block: chance of the highest block total among the locked group
    trophy = None
    blk = next((b for b in blocks if b["status"] in ("live", "locked") and b.get("group")), None)
    if blk:
        group = [le for le in blk["group"] if le in idx]
        tot = np.zeros((SIMS, len(group)))
        for k, le in enumerate(group):
            tot[:, k] = played_scores(le, blk["from"], blk["to"])
            for g in range(blk["from"], blk["to"] + 1):
                if g in scores:
                    tot[:, k] += scores[g][:, idx[le]]
        best = tot.max(axis=1, keepdims=True)
        share = (tot == best) / (tot == best).sum(axis=1, keepdims=True)   # ties split the prize
        trophy = {"block": blk["id"], "from": blk["from"], "to": blk["to"],
                  "p_win": {le: round(float(share[:, k].mean()), 3) for k, le in enumerate(group)}}

    return {"sims": SIMS, "next_round": next_round, "next_gw": gws[0] if gws else None, "season": season,
            "trophy": trophy, "calibration": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in calib.items()},
            "drift_sd": DRIFT_SD}
