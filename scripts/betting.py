"""Goals model for the Betting tab: Dixon-Coles team ratings per league, turned into match markets.

Data: football-data.co.uk, one CSV per league and season, with results, shots on target and
Pinnacle / Betfair Exchange odds both when first collected (Friday for weekend games, Tuesday
midweek) and at kick-off. Raw files are kept in scripts/cache/fd (not committed).

Model, per league:
    log E[goals of A vs B] = mu + home*h + attack[A] - defence[B]
fitted by weighted Poisson likelihood with
    time decay      a match d days old counts exp(-XI * d)
    ridge           attack/defence pulled toward a prior: 0, or for a team new to the league
                    -PROMO if it came up, +PROMO if it came down
    shots on target the fitted "goals" are SOT_W * goals + (1 - SOT_W) * k * shots on target,
                    k = goals per shot on target in the training data (less noisy than goals alone)
Then rho, the Dixon-Coles correction for 0-0, 1-0, 0-1 and 1-1, is fitted on the real scorelines.
Scoreline probabilities give 1X2, over/under 2.5 and both teams to score.
"""

import csv
import io
import math
import os
import urllib.request
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize

FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "fd")
FD_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
# divisions per country, top first: tells whether a new team came up or down
CHAINS = {"E": ["E0", "E1", "E2", "E3"], "D": ["D1", "D2"], "SP": ["SP1", "SP2"],
          "I": ["I1", "I2"], "F": ["F1", "F2"], "N": ["N1"]}
NAMES = {"E0": "Premier League", "E1": "Championship", "E2": "League One", "E3": "League Two",
         "D1": "Bundesliga", "D2": "2. Bundesliga", "SP1": "La Liga", "SP2": "La Liga 2",
         "I1": "Serie A", "I2": "Serie B", "F1": "Ligue 1", "F2": "Ligue 2", "N1": "Eredivisie"}
SEASONS = ["2122", "2223", "2324", "2425", "2526", "2627"]
# reference prices: first collected and closing, 1X2 and over/under 2.5.
# Pinnacle stops in January 2026 (its public feed closed); Betfair Exchange runs from 2024/25.
BOOKS = {
    "ps": {"open_1x2": ("PSH", "PSD", "PSA"), "close_1x2": ("PSCH", "PSCD", "PSCA"),
           "open_ou": ("P>2.5", "P<2.5"), "close_ou": ("PC>2.5", "PC<2.5")},
    "bfe": {"open_1x2": ("BFEH", "BFED", "BFEA"), "close_1x2": ("BFECH", "BFECD", "BFECA"),
            "open_ou": ("BFE>2.5", "BFE<2.5"), "close_ou": ("BFEC>2.5", "BFEC<2.5")},
}

XI = 0.003        # time decay per day (tuned on 2023/24, all leagues)
RIDGE = 2.0       # pull toward the prior (tuned on 2023/24)
PROMO = 0.25      # prior attack/defence shift for a promoted (-) or relegated (+) team
SOT_W = 0.45      # weight on real goals in the fitted target (tuned on 2023/24)
WINDOW = 3 * 365  # days of history used
MAXG = 10


def country(div):
    return next(c for c, ds in CHAINS.items() if div in ds)


def _num(v):
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def _date(s):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def download(divs, seasons=SEASONS, refresh=("2627",)):
    """Fetch the CSVs not already on disk (and always the seasons in `refresh`)."""
    os.makedirs(FD, exist_ok=True)
    for s in seasons:
        for d in divs:
            path = os.path.join(FD, f"{d}_{s}.csv")
            if os.path.exists(path) and s not in refresh:
                continue
            req = urllib.request.Request(FD_URL.format(season=s, div=d), headers={"User-Agent": "Mozilla/5.0 (super-draft-league-site)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            with open(path, "wb") as f:
                f.write(raw)


def load(div, seasons=SEASONS):
    """Played matches of one division, oldest first, as dicts."""
    out = []
    for s in seasons:
        path = os.path.join(FD, f"{div}_{s}.csv")
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            text = f.read().decode("utf-8-sig", errors="replace")
        for r in csv.DictReader(io.StringIO(text)):
            d = _date(r.get("Date", ""))
            if not d or not r.get("HomeTeam") or r.get("FTHG", "") == "":
                continue
            try:
                hg, ag = int(r["FTHG"]), int(r["FTAG"])
            except ValueError:
                continue
            try:
                hst, ast = int(r["HST"]), int(r["AST"])
            except (KeyError, ValueError):
                hst = ast = None
            out.append({
                "div": div, "season": s, "date": d, "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
                "hg": hg, "ag": ag, "hst": hst, "ast": ast,
                "odds": {book: {k: [_num(r.get(c)) for c in cols] for k, cols in keys.items()} for book, keys in BOOKS.items()},
            })
    out.sort(key=lambda m: m["date"])
    return out


def team_priors(div, season, matches_by_div):
    """Prior attack/defence for teams with no match in this division last season."""
    prev = SEASONS[SEASONS.index(season) - 1] if season in SEASONS[1:] else None
    chain = CHAINS[country(div)]
    members = {d: {m["home"] for m in matches_by_div.get(d, []) if m["season"] == prev} for d in chain}
    now = {m["home"] for m in matches_by_div[div] if m["season"] == season} | {m["away"] for m in matches_by_div[div] if m["season"] == season}
    pri = {}
    for t in now:
        if t in members[div]:
            continue
        above = any(t in members[d] for d in chain[:chain.index(div)])
        pri[t] = PROMO if above else -PROMO
    return pri


def fit(train, asof, priors, xi=XI, ridge=RIDGE, sot_w=SOT_W, teams=()):
    """Team ratings from matches before `asof`. Returns a dict usable by predict()."""
    teams = sorted({m["home"] for m in train} | {m["away"] for m in train} | set(teams))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = np.array([idx[m["home"]] for m in train])
    ai = np.array([idx[m["away"]] for m in train])
    hg = np.array([m["hg"] for m in train], float)
    ag = np.array([m["ag"] for m in train], float)
    age = np.array([(asof - m["date"]).days for m in train], float)
    w = np.exp(-xi * age)
    has = np.array([m["hst"] is not None for m in train])
    hst = np.array([m["hst"] or 0 for m in train], float)
    ast = np.array([m["ast"] or 0 for m in train], float)
    k = (hg[has].sum() + ag[has].sum()) / max(1.0, hst[has].sum() + ast[has].sum())
    yh = np.where(has, sot_w * hg + (1 - sot_w) * k * hst, hg)
    ya = np.where(has, sot_w * ag + (1 - sot_w) * k * ast, ag)
    p = np.array([priors.get(t, 0.0) for t in teams])

    def f(x):
        mu, home, att, dfn = x[0], x[1], x[2:2 + n], x[2 + n:]
        lh = mu + home + att[hi] - dfn[ai]
        la = mu + att[ai] - dfn[hi]
        eh, ea = np.exp(lh), np.exp(la)
        nll = -np.sum(w * (yh * lh - eh)) - np.sum(w * (ya * la - ea))
        nll += ridge * (np.sum((att - p) ** 2) + np.sum((dfn - p) ** 2))
        rh, ra = w * (yh - eh), w * (ya - ea)
        g = np.empty_like(x)
        g[0] = -(rh.sum() + ra.sum())
        g[1] = -rh.sum()
        g[2:2 + n] = -(np.bincount(hi, rh, n) + np.bincount(ai, ra, n)) + 2 * ridge * (att - p)
        g[2 + n:] = (np.bincount(ai, rh, n) + np.bincount(hi, ra, n)) + 2 * ridge * (dfn - p)
        return nll, g

    x0 = np.concatenate([[math.log(max(0.5, (hg.mean() + ag.mean()) / 2)), 0.2], p, p])
    x = minimize(f, x0, jac=True, method="L-BFGS-B").x
    mu, home, att, dfn = x[0], x[1], x[2:2 + n], x[2 + n:]
    # rho on real scorelines, given the fitted expected goals
    lh = np.exp(mu + home + att[hi] - dfn[ai])
    la = np.exp(mu + att[ai] - dfn[hi])
    low = (hg <= 1) & (ag <= 1)
    best = (0.0, -np.inf)
    for rho in np.arange(-0.2, 0.201, 0.01):
        t = tau(hg[low], ag[low], lh[low], la[low], rho)
        if np.all(t > 0):
            ll = np.sum(w[low] * np.log(t))
            if ll > best[1]:
                best = (rho, ll)
    return {"idx": idx, "mu": mu, "home": home, "att": att, "def": dfn, "rho": best[0], "priors": priors}


def tau(x, y, lh, la, rho):
    return np.where((x == 0) & (y == 0), 1 - lh * la * rho,
           np.where((x == 0) & (y == 1), 1 + lh * rho,
           np.where((x == 1) & (y == 0), 1 + la * rho,
           np.where((x == 1) & (y == 1), 1 - rho, 1.0))))


def rating(model, team):
    i = model["idx"].get(team)
    if i is None:
        p = model["priors"].get(team, 0.0)
        return p, p
    return model["att"][i], model["def"][i]


def expected_goals(model, home, away):
    ah, dh = rating(model, home)
    aa, da = rating(model, away)
    return math.exp(model["mu"] + model["home"] + ah - da), math.exp(model["mu"] + aa - dh)


def scorelines(lh, la, rho=0.0):
    """P[x, y] for x home goals and y away goals, 0..MAXG, with the Dixon-Coles correction."""
    g = np.arange(MAXG + 1)
    ph = np.exp(-lh) * lh ** g / np.array([math.factorial(i) for i in g])
    pa = np.exp(-la) * la ** g / np.array([math.factorial(i) for i in g])
    P = np.outer(ph, pa)
    P[:2, :2] *= tau(g[:2, None], g[None, :2], lh, la, rho)
    return P / P.sum()


def markets(P):
    """Probabilities for 1X2, over 2.5 goals and both teams to score from a scoreline matrix."""
    x, y = np.indices(P.shape)
    return {"1x2": [P[x > y].sum(), P[x == y].sum(), P[x < y].sum()],
            "ou": [P[x + y > 2].sum(), P[x + y <= 2].sum()],
            "btts": [P[(x > 0) & (y > 0)].sum(), P[(x == 0) | (y == 0)].sum()]}


def fair(prices):
    """Bookmaker prices -> probabilities with the margin removed proportionally (None if any is missing)."""
    if not prices or any(p is None for p in prices):
        return None
    inv = [1 / p for p in prices]
    s = sum(inv)
    return [v / s for v in inv]


def bucket(d):
    """Round of matches a date belongs to: Mon-Thu or Fri-Sun. The model is refitted once per round."""
    start = d - timedelta(days=d.weekday()) if d.weekday() <= 3 else d - timedelta(days=d.weekday() - 4)
    return start
