"""Accuracy report: does the model actually know something?

Every test predicts a round using only the rounds before it, then compares with what happened.
Availability is the injury status FPL showed after the previous round (known before the round), for all predictors.
Three predictors are compared on exactly the same players and rounds:
    form   points in the last four rounds (recent weighted most): the "no model" baseline
    old    the model before the minutes / 2024-25 / set-piece work
    new    the current model
Measured:
    minutes      average error in minutes, Brier score for "60+ minutes", and calibration
                 (when the model says 70%, does it happen about 70% of the time?)
    ranking      pairwise accuracy over the following rounds (A predicted above B: right how often?),
                 with a 90% interval from resampling players, and the paired difference new vs old
    clean sheets Brier score and calibration of the predicted clean-sheet chance
"""

import math

import numpy as np

import model

RNG = np.random.default_rng(11)
BOOT = 300


def _fixed_set(live, gws, i, pos_of):
    """The same players for every predictor: anyone who played in the target round or in a round before it."""
    gw = gws[i]
    return [pid for pid in pos_of if any(live[g].get(pid, {}).get("minutes", 0) > 0 for g in gws[:i + 1])]


def minutes_points_test(live, fixtures, gws, pos_of, team_of, elements, ctx):
    """Minutes and single-round points for old and new model, on exactly the same players."""
    res = {k: {"err": [], "brier": [], "cal": [], "pts_err": [], "pts_bias": []} for k in ("old", "new", "form")}
    for i, gw in enumerate(gws):
        if i < 2:
            continue
        pl = _fixed_set(live, gws, i, pos_of)
        known = gws[:i]
        w = model.RECENT_W[-len(known[-4:]):]
        for name, use in (("old", model.OLD_MODEL), ("new", model.ALL)):
            pr, det, _ = model.project(live, fixtures, known, [gw], pos_of, team_of, elements, None, ctx, use, avail="hist")
            for pid in pl:
                st = live[gw].get(pid, {})
                mi, pts = st.get("minutes", 0), st.get("total_points", 0)
                d = det.get(pid)
                if d is None:      # no fixture for his team that round
                    continue
                r = res[name]
                r["err"].append(abs(d["emin"] - mi))
                y = 1.0 if mi >= 60 else 0.0
                r["brier"].append((d["p60"] - y) ** 2)
                r["cal"].append((d["p60"], y))
                r["pts_err"].append(abs(pr[pid][0] - pts))
                r["pts_bias"].append(pr[pid][0] - pts)
        for pid in pl:
            pts = live[gw].get(pid, {}).get("total_points", 0)
            form = sum(wi * live[g].get(pid, {}).get("total_points", 0) for wi, g in zip(w, known[-4:])) / sum(w)
            res["form"]["pts_err"].append(abs(form - pts))
            res["form"]["pts_bias"].append(form - pts)
    out = {}
    for k, r in res.items():
        o = {"pts_mae": round(float(np.mean(r["pts_err"])), 2), "pts_bias": round(float(np.mean(r["pts_bias"])), 2), "n": len(r["pts_err"])}
        if r["err"]:
            o["min_mae"] = round(float(np.mean(r["err"])), 1)
            o["brier60"] = round(float(np.mean(r["brier"])), 3)
            bins = []
            for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
                sel = [(p, y) for p, y in r["cal"] if lo <= p < hi]
                if sel:
                    bins.append({"lo": lo, "hi": min(hi, 1.0), "pred": round(sum(p for p, _ in sel) / len(sel), 3),
                                 "obs": round(sum(y for _, y in sel) / len(sel), 3), "n": len(sel)})
            o["calibration60"] = bins
        out[k] = o
    return out


def _pair_acc(p, a, idx):
    p, a = p[idx], a[idx]
    dp = p[:, None] - p[None, :]
    da = a[:, None] - a[None, :]
    m = (da != 0) & (dp != 0)
    m = np.triu(m, 1)
    return float(np.mean(np.sign(dp[m]) == np.sign(da[m]))) if m.any() else float("nan")


def ranking_test(live, fixtures, gws, pos_of, team_of, elements, ctx, start):
    known = [g for g in gws if g < start]
    tg = [g for g in gws if g >= start]
    if len(known) < 2 or not tg:
        return None
    preds = {}
    for name, use in (("old", model.OLD_MODEL), ("new", model.ALL)):
        pr, _, _ = model.project(live, fixtures, known, tg, pos_of, team_of, elements, None, ctx, use, avail="hist")
        preds[name] = pr
    pl = [pid for pid in pos_of if sum(live[g].get(pid, {}).get("minutes", 0) for g in tg) >= 45 * len(tg)]
    act = np.array([sum(live[g].get(pid, {}).get("total_points", 0) for g in tg) for pid in pl], float)
    w = model.RECENT_W[-len(known[-4:]):]
    form = np.array([sum(wi * live[g].get(pid, {}).get("total_points", 0) for wi, g in zip(w, known[-4:])) for pid in pl], float)
    vec = {"form": form, "old": np.array([sum(preds["old"][pid]) for pid in pl]), "new": np.array([sum(preds["new"][pid]) for pid in pl])}
    full = np.arange(len(pl))
    out = {"from": known[-1], "to": tg[-1], "players": len(pl)}
    boots = {k: [] for k in vec}
    for _ in range(BOOT):
        idx = RNG.choice(full, size=len(full), replace=True)
        for k, v in vec.items():
            boots[k].append(_pair_acc(v, act, idx))
    for k, v in vec.items():
        b = np.array(boots[k])
        out[k] = {"acc": round(_pair_acc(v, act, full), 3), "lo": round(float(np.nanpercentile(b, 5)), 3), "hi": round(float(np.nanpercentile(b, 95)), 3)}
    diff = np.array(boots["new"]) - np.array(boots["old"])
    out["new_vs_old"] = {"diff": round(out["new"]["acc"] - out["old"]["acc"], 3), "lo": round(float(np.nanpercentile(diff, 5)), 3),
                         "hi": round(float(np.nanpercentile(diff, 95)), 3), "p_better": round(float(np.mean(diff > 0)), 2)}
    diff_f = np.array(boots["new"]) - np.array(boots["form"])
    out["new_vs_form"] = {"diff": round(out["new"]["acc"] - out["form"]["acc"], 3), "lo": round(float(np.nanpercentile(diff_f, 5)), 3),
                          "hi": round(float(np.nanpercentile(diff_f, 95)), 3), "p_better": round(float(np.mean(diff_f > 0)), 2)}
    return out


def cleansheet_test(live, fixtures, gws, pos_of, team_of, elements, ctx):
    cal = []
    gk = {}
    for pid, pos in pos_of.items():
        if pos == 1:
            gk.setdefault(team_of[pid], []).append(pid)
    for i, gw in enumerate(gws):
        if i < 2:
            continue
        _, det, _ = model.project(live, fixtures, gws[:i], [gw], pos_of, team_of, elements, None, ctx, model.ALL, avail="hist")
        for f in fixtures:
            if f["event"] != gw or not f.get("finished") or f.get("team_h_score") is None:
                continue
            for team, conceded in ((f["team_h"], f["team_a_score"]), (f["team_a"], f["team_h_score"])):
                p = next((det[pid]["cs"] for pid in gk.get(team, []) if pid in det), None)
                if p is not None:
                    cal.append((p, 1.0 if conceded == 0 else 0.0))
    if not cal:
        return None
    base = sum(y for _, y in cal) / len(cal)
    bins = []
    for lo, hi in ((0, .2), (.2, .3), (.3, .4), (.4, 1.01)):
        sel = [(p, y) for p, y in cal if lo <= p < hi]
        if sel:
            bins.append({"lo": lo, "hi": min(hi, 1.0), "pred": round(sum(p for p, _ in sel) / len(sel), 3),
                         "obs": round(sum(y for _, y in sel) / len(sel), 3), "n": len(sel)})
    return {"n": len(cal), "brier": round(sum((p - y) ** 2 for p, y in cal) / len(cal), 3),
            "brier_flat": round(sum((base - y) ** 2 for _, y in cal) / len(cal), 3), "rate": round(base, 3), "calibration": bins}


def scorecard(live, fixtures, gws, pos_of, team_of, elements, ctx):
    rep = {"rounds": gws[2:]}
    rep["single_round"] = minutes_points_test(live, fixtures, gws, pos_of, team_of, elements, ctx)
    start = 3 if len(gws) < 10 else len(gws) - 5
    rep["ranking"] = ranking_test(live, fixtures, gws, pos_of, team_of, elements, ctx, start)
    rep["clean_sheets"] = cleansheet_test(live, fixtures, gws, pos_of, team_of, elements, ctx)
    s1, r = rep["single_round"], rep["ranking"]
    print(f"  evaluate (same {s1['new']['n']} player-rounds): minutes MAE old {s1['old']['min_mae']} -> new {s1['new']['min_mae']}, "
          f"Brier(60+) {s1['old']['brier60']} -> {s1['new']['brier60']}; points MAE form {s1['form']['pts_mae']} old {s1['old']['pts_mae']} new {s1['new']['pts_mae']}, "
          f"bias old {s1['old']['pts_bias']} new {s1['new']['pts_bias']}", flush=True)
    print(f"  evaluate: calibration 60+ new {s1['new']['calibration60']}", flush=True)
    if r:
        print(f"  evaluate: pairwise form {r['form']['acc']} old {r['old']['acc']} new {r['new']['acc']} [{r['new']['lo']}-{r['new']['hi']}], "
              f"new-old {r['new_vs_old']}, new-form {r['new_vs_form']}", flush=True)
    if rep["clean_sheets"]:
        c = rep["clean_sheets"]
        print(f"  evaluate: clean sheets Brier {c['brier']} vs flat {c['brier_flat']} (n={c['n']}) {c['calibration']}", flush=True)
    return rep
