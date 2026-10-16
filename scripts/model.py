"""Expected points: past (xP for rounds already played) and projected (next rounds).

Team strength: a ridge-penalised Poisson regression on team xG per match,
    log E[xG of A vs B] = mu + home*h + attack[A] - defence[B]
fitted by IRLS. It gives every upcoming match an expected goals for and against.

Player projection: FPL's own scoring rules applied to
    minutes      weighted recent minutes, chance of 60+, availability (injury status)
    goals, assists   xG/90 and xA/90 (shrunk toward the position average) x the match's expected goals
    clean sheet  P(team concedes 0) from the opponent's expected goals
    defcon, saves, bonus, cards   shrunk per-90 rates
A backtest predicts each past round from the rounds before it only, so the page can show how well it hits.
"""

import math

import numpy as np

GOAL = {1: 6, 2: 6, 3: 5, 4: 4}
CS = {1: 4, 2: 4, 3: 1, 4: 0}
DC_THR = {2: 10, 3: 12, 4: 12}
K_MIN = 400          # minutes of prior weight when shrinking per-90 rates
K_APPS = 3           # appearances of prior weight for the DefCon hit rate
RIDGE = 3.0          # pull on team attack/defence ratings: about six matches each so far
RECENT_W = [1, 2, 3, 4]   # weights for the last four rounds, oldest first


def pois_floor_div(lam, n, kmax=25):
    """E[floor(X / n)] for X ~ Poisson(lam): goals conceded per 2, saves per 3."""
    if lam <= 0:
        return 0.0
    p = math.exp(-lam)
    total = 0.0
    for k in range(kmax + 1):
        if k:
            p *= lam / k
        total += (k // n) * p
    return total


def actual_points(st, pos):
    """FPL points rebuilt from live stats. Used as a check that the rules above are right."""
    m = st.get("minutes", 0)
    if not m:
        return 0
    p = 2 if m >= 60 else 1
    p += GOAL[pos] * st.get("goals_scored", 0) + 3 * st.get("assists", 0)
    p += CS[pos] * st.get("clean_sheets", 0)
    if pos in (1, 2):
        p -= st.get("goals_conceded", 0) // 2
    if pos == 1:
        p += st.get("saves", 0) // 3 + 5 * st.get("penalties_saved", 0)
    thr = DC_THR.get(pos)
    if thr and st.get("defensive_contribution", 0) >= thr:
        p += 2
    p += st.get("bonus", 0) - st.get("yellow_cards", 0) - 3 * st.get("red_cards", 0)
    p -= 2 * st.get("own_goals", 0) + 2 * st.get("penalties_missed", 0)
    return p


def past_xp(st, pos):
    """Expected points for a round already played: goals, assists and clean sheet replaced by
    xG, xA and P(clean sheet) from the player's own xG conceded; everything else as it happened."""
    m = st.get("minutes", 0)
    if not m:
        return 0.0
    xgc = float(st.get("expected_goals_conceded", 0) or 0)
    p = 2 if m >= 60 else 1
    p += GOAL[pos] * float(st.get("expected_goals", 0) or 0) + 3 * float(st.get("expected_assists", 0) or 0)
    if m >= 60:
        p += CS[pos] * math.exp(-xgc)
    if pos in (1, 2):
        p -= pois_floor_div(xgc, 2)
    if pos == 1:
        p += st.get("saves", 0) // 3 + 5 * st.get("penalties_saved", 0)
    thr = DC_THR.get(pos)
    if thr and st.get("defensive_contribution", 0) >= thr:
        p += 2
    p += st.get("bonus", 0) - st.get("yellow_cards", 0) - 3 * st.get("red_cards", 0)
    p -= 2 * st.get("own_goals", 0) + 2 * st.get("penalties_missed", 0)
    return round(p, 2)


# ---------------------------------------------------------------- team strength

def team_matches(live, fixtures, team_of, gws):
    """(attacking team, defending team, home flag, team xG) for every match in `gws`.
    Team xG is the sum of its players' xG; rounds where a team plays twice are skipped
    because the round total cannot be split between the two matches."""
    rows = []
    for gw in gws:
        fx = [f for f in fixtures if f["event"] == gw and f.get("finished")]
        count = {}
        for f in fx:
            count[f["team_h"]] = count.get(f["team_h"], 0) + 1
            count[f["team_a"]] = count.get(f["team_a"], 0) + 1
        xg = {}
        for pid, st in live[gw].items():
            t = team_of.get(pid)
            if t:
                xg[t] = xg.get(t, 0.0) + float(st.get("expected_goals", 0) or 0)
        for f in fx:
            h, a = f["team_h"], f["team_a"]
            if count[h] > 1 or count[a] > 1:
                continue
            rows.append((h, a, 1, xg.get(h, 0.0)))
            rows.append((a, h, 0, xg.get(a, 0.0)))
    return rows


def fit_strength(rows, teams):
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    X = np.zeros((len(rows), 2 + 2 * n))
    y = np.zeros(len(rows))
    for r, (att, dfn, home, v) in enumerate(rows):
        X[r, 0] = 1.0
        X[r, 1] = home
        X[r, 2 + idx[att]] = 1.0
        X[r, 2 + n + idx[dfn]] = -1.0
        y[r] = v
    P = np.diag([0.0, 0.0] + [RIDGE] * (2 * n))
    theta = np.zeros(2 + 2 * n)
    theta[0] = math.log(max(y.mean(), 0.1)) if len(y) else 0.0
    for _ in range(50):
        mu = np.exp(X @ theta)
        grad = X.T @ (y - mu) - P @ theta
        H = X.T @ (X * mu[:, None]) + P
        step = np.linalg.solve(H, grad)
        theta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return {"mu": float(theta[0]), "home": float(theta[1]),
            "att": {t: float(theta[2 + i]) for t, i in idx.items()},
            "def": {t: float(theta[2 + n + i]) for t, i in idx.items()}}


def lam(S, att, dfn, home):
    return math.exp(S["mu"] + S["home"] * home + S["att"].get(att, 0.0) - S["def"].get(dfn, 0.0))


# ---------------------------------------------------------------- player projection

def player_rates(live, gws, pos_of):
    """Season-to-date per-90 rates per player, shrunk toward the position average."""
    tot = {}
    for gw in gws:
        for pid, st in live[gw].items():
            m = st.get("minutes", 0)
            if not m:
                continue
            t = tot.setdefault(pid, {"mi": 0, "xg": 0.0, "xa": 0.0, "sv": 0, "bo": 0, "yc": 0, "dc_apps": 0, "dc_hits": 0})
            t["mi"] += m
            t["xg"] += float(st.get("expected_goals", 0) or 0)
            t["xa"] += float(st.get("expected_assists", 0) or 0)
            t["sv"] += st.get("saves", 0)
            t["bo"] += st.get("bonus", 0)
            t["yc"] += st.get("yellow_cards", 0)
            thr = DC_THR.get(pos_of.get(pid))
            if thr and m >= 60:
                t["dc_apps"] += 1
                t["dc_hits"] += st.get("defensive_contribution", 0) >= thr

    prior = {}
    for pos in (1, 2, 3, 4):
        regs = [t for pid, t in tot.items() if pos_of.get(pid) == pos and t["mi"] >= 270]
        mins = sum(t["mi"] for t in regs) or 1
        apps = sum(t["dc_apps"] for t in regs) or 1
        prior[pos] = {k: sum(t[k] for t in regs) / mins * 90 for k in ("xg", "xa", "sv", "bo", "yc")}
        prior[pos]["dc"] = sum(t["dc_hits"] for t in regs) / apps

    rates = {}
    for pid, pos in pos_of.items():
        t = tot.get(pid, {"mi": 0, "xg": 0.0, "xa": 0.0, "sv": 0, "bo": 0, "yc": 0, "dc_apps": 0, "dc_hits": 0})
        pr = prior[pos]
        r = {k: (t[k] + pr[k] * K_MIN / 90) / ((t["mi"] + K_MIN) / 90) for k in ("xg", "xa", "sv", "bo", "yc")}
        r["dc"] = (t["dc_hits"] + pr["dc"] * K_APPS) / (t["dc_apps"] + K_APPS)
        rates[pid] = r
    return rates


def minutes_profile(live, gws):
    """Expected minutes, P(plays) and P(60+) from the last four rounds, most recent weighted most."""
    last = gws[-len(RECENT_W):]
    w = RECENT_W[-len(last):]
    tw = sum(w) or 1
    prof = {}
    pids = set()
    for gw in last:
        pids.update(live[gw].keys())
    for pid in pids:
        mins = [live[gw].get(pid, {}).get("minutes", 0) for gw in last]
        prof[pid] = {
            "emin": sum(wi * m for wi, m in zip(w, mins)) / tw,
            "p60": sum(wi for wi, m in zip(w, mins) if m >= 60) / tw,
            "pplay": sum(wi for wi, m in zip(w, mins) if m > 0) / tw,
        }
    return prof


def availability(el, k):
    """Chance of being available k rounds ahead (k = 0 is the next round)."""
    status, chance = el.get("status", "a"), el.get("chance_of_playing_next_round")
    if status in ("u", "n"):
        return 0.0
    a0 = chance / 100 if chance is not None else (1.0 if status == "a" else 0.75 if status == "d" else 0.0)
    return min(1.0, a0 + (1 - a0) * min(1.0, k / 4))   # injured players drift back over about four rounds


def project(live, fixtures, gws_known, targets, pos_of, team_of, elements=None, teams=None):
    """Expected points per player for each round in `targets`, using only `gws_known`."""
    teams = teams or sorted({t for t in team_of.values()})
    S = fit_strength(team_matches(live, fixtures, team_of, gws_known), teams)

    # each team's average expected goals for/against in the matches already played,
    # so a player's rates are compared with the schedule they were earned against
    past = {t: {"for": [], "against": []} for t in teams}
    for f in fixtures:
        if f["event"] in gws_known and f.get("finished"):
            h, a = f["team_h"], f["team_a"]
            past[h]["for"].append(lam(S, h, a, 1)); past[h]["against"].append(lam(S, a, h, 0))
            past[a]["for"].append(lam(S, a, h, 0)); past[a]["against"].append(lam(S, h, a, 1))
    avg = {t: {k: (sum(v) / len(v) if v else math.exp(S["mu"])) for k, v in d.items()} for t, d in past.items()}

    rates = player_rates(live, gws_known, pos_of)
    prof = minutes_profile(live, gws_known)
    out = {}
    detail = {}
    for pid, pos in pos_of.items():
        team = team_of.get(pid)
        mp = prof.get(pid, {"emin": 0.0, "p60": 0.0, "pplay": 0.0})
        r = rates[pid]
        row = []
        for k, gw in enumerate(targets):
            a = availability(elements[pid], k) if elements else 1.0
            xp = 0.0
            for f in (f for f in fixtures if f["event"] == gw and team in (f["team_h"], f["team_a"])):
                home = 1 if f["team_h"] == team else 0
                opp = f["team_a"] if home else f["team_h"]
                lf, la_ = lam(S, team, opp, home), lam(S, opp, team, 1 - home)
                m_att, m_def = lf / avg[team]["for"], la_ / avg[team]["against"]
                emin, p60, pplay = mp["emin"] * a, mp["p60"] * a, mp["pplay"] * a
                share = emin / 90
                xg, xa = r["xg"] * share * m_att, r["xa"] * share * m_att
                pts = 2 * p60 + (pplay - p60)
                pts += GOAL[pos] * xg + 3 * xa
                pts += CS[pos] * p60 * math.exp(-la_)
                if pos in (1, 2):
                    pts -= pois_floor_div(la_ * share, 2)
                if pos == 1:
                    pts += pois_floor_div(r["sv"] * share * m_def, 3)
                if pos in DC_THR:
                    pts += 2 * r["dc"] * p60
                pts += r["bo"] * share * (0.5 + 0.5 * m_att) - r["yc"] * share
                xp += pts
                if k == 0 and pid not in detail:
                    detail[pid] = {"emin": round(emin), "p60": round(p60, 2), "xg": round(xg, 2), "xa": round(xa, 2),
                                   "cs": round(math.exp(-la_), 2), "dc": round(r["dc"], 2)}
            row.append(round(xp, 2))
        out[pid] = row
    return out, detail, S


def backtest(live, fixtures, gws, pos_of, team_of, actual):
    """Predict each round from the rounds before it only; compare with a plain form baseline."""
    errs, base_errs, pairs = [], [], []
    tested = []
    for i, gw in enumerate(gws):
        if i < 2:
            continue
        known = gws[:i]
        pred, _, _ = project(live, fixtures, known, [gw], pos_of, team_of)
        last = known[-len(RECENT_W):]
        w = RECENT_W[-len(last):]
        for pid in pos_of:
            act = actual.get(gw, {}).get(pid)
            p = pred[pid][0]
            if act is None and p < 0.5:
                continue      # neither played nor expected to
            act = act or 0
            form = sum(wi * actual.get(g, {}).get(pid, 0) for wi, g in zip(w, last)) / sum(w)
            errs.append(abs(p - act))
            base_errs.append(abs(form - act))
            pairs.append((p, act))
        tested.append(gw)
    if not pairs:
        return None
    a = np.array(pairs)
    corr = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
    return {"gws": tested, "n": len(pairs), "mae": round(float(np.mean(errs)), 2),
            "mae_form": round(float(np.mean(base_errs)), 2), "corr": round(corr, 2)}


def run(boot, live, gws, fixtures, next_gw, horizon=6):
    """Everything the protected pages need: past xP, projections, fixtures and the backtest."""
    pos_of = {e["id"]: e["element_type"] for e in boot["elements"]}
    team_of = {e["id"]: e["team"] for e in boot["elements"]}
    elements = {e["id"]: e for e in boot["elements"]}
    teams = sorted(t["id"] for t in boot["teams"])

    # sanity check: rebuilt points must match FPL's, otherwise the scoring rules are off
    actual, wrong = {}, 0
    for gw in gws:
        actual[gw] = {}
        for pid, st in live[gw].items():
            if st.get("minutes"):
                actual[gw][pid] = st.get("total_points", 0)
                wrong += actual_points(st, pos_of[pid]) != st.get("total_points", 0)
    print(f"  model: rules check, {wrong} appearances where rebuilt points differ from FPL", flush=True)

    xpt = {gw: {pid: past_xp(st, pos_of[pid]) for pid, st in live[gw].items() if st.get("minutes")} for gw in gws}

    targets = [g for g in range(next_gw, min(39, next_gw + horizon))] if next_gw else []
    proj, detail, S = project(live, fixtures, gws, targets, pos_of, team_of, elements, teams)

    fix = {}
    for t in teams:
        fix[t] = []
        for gw in targets:
            for f in (f for f in fixtures if f["event"] == gw and t in (f["team_h"], f["team_a"])):
                home = 1 if f["team_h"] == t else 0
                opp = f["team_a"] if home else f["team_h"]
                fix[t].append({"gw": gw, "opp": opp, "home": home,
                               "gf": round(lam(S, t, opp, home), 2), "ga": round(lam(S, opp, t, 1 - home), 2)})

    bt = backtest(live, fixtures, gws, pos_of, team_of, actual)
    if bt:
        print(f"  model: backtest rounds {bt['gws']}: MAE {bt['mae']} (form baseline {bt['mae_form']}), r={bt['corr']}", flush=True)

    return {"xpt": xpt, "proj": {"gws": targets, "by_player": proj, "detail": detail},
            "fixtures": fix, "backtest": bt, "rules_mismatch": wrong,
            "strength": {"home": round(S["home"], 3), "att": {t: round(v, 3) for t, v in S["att"].items()},
                         "def": {t: round(v, 3) for t, v in S["def"].items()}}}
