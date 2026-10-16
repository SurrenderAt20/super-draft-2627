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

Extras (each can be switched off, so the backtest can show what it adds):
    prior   last season (2025/26) as the starting point for player rates and team strength,
            instead of the position/league average. DefCon only exists from 2025/26.
    pens    xG split into open play (npxG) and penalties; the first-choice taker gets the team's penalties
    rot     minutes after a European match, scaled by the measured effect (close to none for regulars)
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
PEN_XG = 0.76        # xG of a penalty
K_LAST_MIN = 1200    # minutes at which last season counts as much as the position average
K_LAST_APPS = 10     # appearances at which last season's DefCon hit rate counts as much as the average
MOVED = 0.6          # weight kept for last season when a player has changed club
TEAM_REGRESS = 0.7   # last season's team ratings pulled 30% toward average
PROMOTED = -0.2      # starting attack and defence for teams not in last season's league
POS_NAME = {"Goalkeeper": 1, "Defender": 2, "Midfielder": 3, "Forward": 4}
ALL = {"prior": True, "pens": True, "rot": True}


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


def fit_strength(rows, teams, prior=None):
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
    theta0 = np.zeros(2 + 2 * n)
    if prior:
        for t, i in idx.items():
            theta0[2 + i] = prior["att"].get(t, 0.0)
            theta0[2 + n + i] = prior["def"].get(t, 0.0)
    theta = theta0.copy()
    theta[0] = math.log(max(y.mean(), 0.1)) if len(y) else 0.0
    if not len(y):
        return {"mu": theta[0], "home": 0.0, "att": {t: float(theta0[2 + i]) for t, i in idx.items()},
                "def": {t: float(theta0[2 + n + i]) for t, i in idx.items()}}
    for _ in range(50):
        mu = np.exp(X @ theta)
        grad = X.T @ (y - mu) - P @ (theta - theta0)
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

def player_rates(live, gws, pos_of, ctx=None, use_prior=False, use_pens=False):
    """Season-to-date per-90 rates per player, shrunk toward a prior: the position average,
    or (use_prior) a blend of last season's own rates and the position average."""
    ctx = ctx or {}
    pens_now = ctx.get("pens_now", {})
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
    if use_pens:   # open-play xG only; penalties are added back for the taker in project()
        for pid, t in tot.items():
            n = sum(v for gw, v in pens_now.get(ctx["code_of"].get(pid), {}).items() if gw in gws)
            t["xg"] = max(0.0, t["xg"] - PEN_XG * n)

    prior = {}
    for pos in (1, 2, 3, 4):
        regs = [t for pid, t in tot.items() if pos_of.get(pid) == pos and t["mi"] >= 270]
        mins = sum(t["mi"] for t in regs) or 1
        apps = sum(t["dc_apps"] for t in regs) or 1
        prior[pos] = {k: sum(t[k] for t in regs) / mins * 90 for k in ("xg", "xa", "sv", "bo", "yc")}
        prior[pos]["dc"] = sum(t["dc_hits"] for t in regs) / apps

    last = ctx.get("last", {}).get("players", {}) if use_prior else {}
    rates = {}
    for pid, pos in pos_of.items():
        t = tot.get(pid, {"mi": 0, "xg": 0.0, "xa": 0.0, "sv": 0, "bo": 0, "yc": 0, "dc_apps": 0, "dc_hits": 0})
        pr = dict(prior[pos])
        L = last.get(ctx.get("code_of", {}).get(pid)) if last else None
        if L and L["mi"] >= 300:
            moved = MOVED if str(L.get("team")) != str(ctx["team_code_of"].get(pid)) else 1.0
            w = L["mi"] / (L["mi"] + K_LAST_MIN) * moved
            lxg = max(0.0, L["xg"] - (PEN_XG * L.get("pens", 0) if use_pens else 0.0))
            last_r = {"xg": lxg, "xa": L["xa"], "sv": L["sv"], "bo": L["bo"], "yc": L["yc"]}
            for k in ("xg", "xa", "sv", "bo", "yc"):
                pr[k] = w * last_r[k] / L["mi"] * 90 + (1 - w) * pr[k]
            if L.get("dc_apps") and POS_NAME.get(L.get("pos")) == pos:
                wd = L["dc_apps"] / (L["dc_apps"] + K_LAST_APPS) * moved
                pr["dc"] = wd * L["dc_hits"] / L["dc_apps"] + (1 - wd) * pr["dc"]
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


def project(live, fixtures, gws_known, targets, pos_of, team_of, elements=None, teams=None, ctx=None, use=None, avail=True):
    """Expected points per player for each round in `targets`, using only `gws_known`."""
    use = use or {}
    ctx = ctx or {}
    teams = teams or sorted({t for t in team_of.values()})
    S = fit_strength(team_matches(live, fixtures, team_of, gws_known), teams, ctx.get("team_prior") if use.get("prior") else None)

    # each team's average expected goals for/against in the matches already played,
    # so a player's rates are compared with the schedule they were earned against
    past = {t: {"for": [], "against": []} for t in teams}
    for f in fixtures:
        if f["event"] in gws_known and f.get("finished"):
            h, a = f["team_h"], f["team_a"]
            past[h]["for"].append(lam(S, h, a, 1)); past[h]["against"].append(lam(S, a, h, 0))
            past[a]["for"].append(lam(S, a, h, 0)); past[a]["against"].append(lam(S, h, a, 1))
    avg = {t: {k: (sum(v) / len(v) if v else math.exp(S["mu"])) for k, v in d.items()} for t, d in past.items()}

    rates = player_rates(live, gws_known, pos_of, ctx, use.get("prior"), use.get("pens"))
    pen_rate = ctx.get("last", {}).get("pens_per_team_match", 0.12)
    pen_share = {1: 1.0, 2: 0.15}
    prof = minutes_profile(live, gws_known)
    out = {}
    detail = {}
    for pid, pos in pos_of.items():
        team = team_of.get(pid)
        mp = prof.get(pid, {"emin": 0.0, "p60": 0.0, "pplay": 0.0})
        r = rates[pid]
        row = []
        for k, gw in enumerate(targets):
            # the backtest must not see today's injury news for past rounds
            a = availability(elements[pid], k) if elements and avail else 1.0
            xp = 0.0
            for f in (f for f in fixtures if f["event"] == gw and team in (f["team_h"], f["team_a"])):
                home = 1 if f["team_h"] == team else 0
                opp = f["team_a"] if home else f["team_h"]
                lf, la_ = lam(S, team, opp, home), lam(S, opp, team, 1 - home)
                m_att, m_def = lf / avg[team]["for"], la_ / avg[team]["against"]
                emin, p60, pplay = mp["emin"] * a, mp["p60"] * a, mp["pplay"] * a
                if use.get("rot") and ctx.get("euro_flag", {}).get((team, f["id"])):
                    rf = ctx.get("rot_factor", {}).get(pid, ctx.get("rot_league", 1.0))
                    emin, p60 = emin * rf, min(pplay, p60 * rf)
                share = emin / 90
                xg, xa = r["xg"] * share * m_att, r["xa"] * share * m_att
                if use.get("pens") and elements and elements[pid].get("penalties_order") in pen_share:
                    xg += pen_rate * m_att * share * PEN_XG * pen_share[elements[pid]["penalties_order"]]
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


def backtest(live, fixtures, gws, pos_of, team_of, actual, elements=None, ctx=None, use=None):
    """Predict each round from the rounds before it only; compare with a plain form baseline."""
    errs, base_errs, pairs = [], [], []
    tested = []
    for i, gw in enumerate(gws):
        if i < 2:
            continue
        known = gws[:i]
        pred, _, _ = project(live, fixtures, known, [gw], pos_of, team_of, elements, None, ctx, use, avail=False)
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


def rank_test(live, fixtures, gws, pos_of, team_of, elements, ctx, use, start):
    """Predict the sum of rounds start..last from the rounds before, for players who played at least
    half the minutes; return the correlation and how many of the predicted top 30 were in the actual top 30.
    This is closer to a transfer decision than the error of a single round."""
    known = [g for g in gws if g < start]
    tg = [g for g in gws if g >= start]
    pred, _, _ = project(live, fixtures, known, tg, pos_of, team_of, elements, None, ctx, use, avail=False)
    pl = [pid for pid in pos_of if sum(live[g].get(pid, {}).get("minutes", 0) for g in tg) >= 45 * len(tg)]
    if len(pl) < 40:
        return None
    p = np.array([sum(pred[pid]) for pid in pl])
    a = np.array([sum(live[g].get(pid, {}).get("total_points", 0) for g in tg) for pid in pl])
    top = set(sorted(pl, key=lambda x: -sum(pred[x]))[:30])
    best = set(sorted(pl, key=lambda x: -sum(live[g].get(x, {}).get("total_points", 0) for g in tg))[:30])
    return {"from": known[-1], "to": tg[-1], "corr": round(float(np.corrcoef(p, a)[0, 1]), 2), "top30": len(top & best)}


def context(boot, gws, fixtures, last, now):
    """Codes, last-season priors, penalties so far and European-week flags for the model."""
    code_of = {e["id"]: str(e["code"]) for e in boot["elements"]}
    tcode = {t["id"]: str(t["code"]) for t in boot["teams"]}
    team_code_of = {e["id"]: tcode.get(e["team"]) for e in boot["elements"]}
    by_code = {c: t for t, c in tcode.items()}

    # last season's team strength, pulled toward average; promoted teams start below average
    team_prior = None
    if last:
        codes = sorted({r[0] for r in last["team_matches"]})
        L = fit_strength([tuple(r) for r in last["team_matches"]], codes)
        team_prior = {"att": {}, "def": {}}
        for t, c in tcode.items():
            team_prior["att"][t] = L["att"][c] * TEAM_REGRESS if c in L["att"] else PROMOTED
            team_prior["def"][t] = L["def"][c] * TEAM_REGRESS if c in L["def"] else PROMOTED

    # minutes factor after a European match, measured on last season's regular starters
    rot_league, rot_factor = 1.0, {}
    if last and last.get("rotation"):
        regs = [r for r in last["rotation"].values() if r["normal"] / r["n_normal"] >= 60 and r["n_after"] >= 3]
        if regs:
            rot_league = (sum(r["after"] for r in regs) / sum(r["n_after"] for r in regs)) / \
                         (sum(r["normal"] for r in regs) / sum(r["n_normal"] for r in regs))
            rot_league = min(1.0, rot_league)   # no evidence that Europe adds minutes
        for pid, c in code_of.items():
            r = last["rotation"].get(c)
            if r and r["n_normal"] and r["normal"] / r["n_normal"] >= 30:
                own = (r["after"] / r["n_after"]) / (r["normal"] / r["n_normal"])
                k = r["n_after"] / (r["n_after"] + 5)      # few European weeks: lean on the league figure
                rot_factor[pid] = min(1.0, k * own + (1 - k) * rot_league)

    # Premier League fixtures that come within ~4 days after a European match
    euro_flag = {}
    if now:
        from history import euro_before, _t
        for f in fixtures:
            kick = _t(f.get("kickoff_time"))
            for t in (f["team_h"], f["team_a"]):
                h = euro_before(kick, tcode.get(t), now["euro"])
                if h is not None:
                    euro_flag[(t, f["id"])] = round(h)
    return {"code_of": code_of, "team_code_of": team_code_of, "last": last or {}, "team_prior": team_prior,
            "pens_now": (now or {}).get("pens", {}), "rot_league": rot_league, "rot_factor": rot_factor,
            "euro_flag": euro_flag}


def run(boot, live, gws, fixtures, next_gw, horizon=6, last=None, now=None):
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
    ctx = context(boot, gws, fixtures, last, now)
    proj, detail, S = project(live, fixtures, gws, targets, pos_of, team_of, elements, teams, ctx, ALL)

    fix = {}
    for t in teams:
        fix[t] = []
        for gw in targets:
            for f in (f for f in fixtures if f["event"] == gw and t in (f["team_h"], f["team_a"])):
                home = 1 if f["team_h"] == t else 0
                opp = f["team_a"] if home else f["team_h"]
                fx = {"gw": gw, "opp": opp, "home": home,
                      "gf": round(lam(S, t, opp, home), 2), "ga": round(lam(S, opp, t, 1 - home), 2)}
                if (t, f["id"]) in ctx["euro_flag"]:
                    fx["euro_h"] = ctx["euro_flag"][(t, f["id"])]
                fix[t].append(fx)

    bt = backtest(live, fixtures, gws, pos_of, team_of, actual, elements, ctx, ALL)
    base = backtest(live, fixtures, gws, pos_of, team_of, actual, elements, ctx, {})
    if bt and base:
        bt["mae_base"], bt["corr_base"] = base["mae"], base["corr"]
        for name in ("prior", "pens", "rot"):
            one = backtest(live, fixtures, gws, pos_of, team_of, actual, elements, ctx, {name: True})
            bt[f"mae_{name}"] = one["mae"]
        print(f"  model: backtest rounds {bt['gws']}: MAE {bt['mae']} r={bt['corr']} | without extras {base['mae']} r={base['corr']} | "
              f"prior only {bt['mae_prior']}, pens only {bt['mae_pens']}, rotation only {bt['mae_rot']} | form {bt['mae_form']}", flush=True)
    if bt and len(gws) >= 4:
        start = 3 if len(gws) < 10 else len(gws) - 5
        bt["rank"] = rank_test(live, fixtures, gws, pos_of, team_of, elements, ctx, ALL, start)
        bt["rank_base"] = rank_test(live, fixtures, gws, pos_of, team_of, elements, ctx, {}, start)
        print(f"  model: rank test {bt['rank']} vs without extras {bt['rank_base']}", flush=True)
    print(f"  model: rotation factor after Europe (league) {ctx['rot_league']:.3f}, {len(ctx['euro_flag'])} flagged team-fixtures", flush=True)

    pens_taker = {e["id"]: e.get("penalties_order") for e in boot["elements"] if e.get("penalties_order") in (1, 2)}
    return {"xpt": xpt, "proj": {"gws": targets, "by_player": proj, "detail": detail, "pens": pens_taker},
            "fixtures": fix, "backtest": bt, "rules_mismatch": wrong,
            "strength": {"home": round(S["home"], 3), "att": {t: round(v, 3) for t, v in S["att"].items()},
                         "def": {t: round(v, 3) for t, v in S["def"].items()}}}
