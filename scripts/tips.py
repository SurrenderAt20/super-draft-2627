"""Tips for the Betting tab: singles, accumulators, same-match combinations, a ladder challenge and
Premier League goalscorers, frozen when published, settled from results.

For fun, not an edge: the backtests (betting_backtest.py, betting_books.py) found that neither our
goals model nor bet365's prices beat the market. So the tips use the best estimate we have:
    probability   Betfair Exchange's price with the margin removed (the sharpest price in the data).
                  Markets without exchange prices (team to score, over 1.5 / 3.5, both teams to score,
                  team over 1.5, same-match combinations) come from the expected goals that reproduce
                  the exchange's 1X2 and over/under 2.5 (independent Poisson); checked on 2024-26
                  results, those chances are honest. 1X2 and double chance use the exchange directly.
    price         bet365's price where the data has it (1X2, over/under 2.5). Elsewhere an estimate:
                  the fair price less bet365's margin in that match (double chance from bet365's own
                  1X2). Estimated prices are marked; check bet365 before playing.
    expected      probability * price - 1: what a tip returns on average (below 0 at bet365)
Upcoming matches and prices: football-data.co.uk's fixtures.csv (about 22 leagues).

Every tip carries its reasons (market view, expected goals, form) and a calibrated confidence: how
often tips with that probability hit in the historical test.

Publishing: 11:00 is the day's first card, 15:00 an update with fresh odds for matches that have not
kicked off, leaving out bets already tipped. Published tips never change; only results are added.

Results: ESPN's public scoreboard the same day (most leagues), football-data's season files as the
fallback, FPL's live data for goalscorers.

Ladder: start at 100 kr, bet the whole payout on the next step, restart at 100 kr after a loss. A
step is a single or a double whose total bet365 odds are 1.10-1.20, whichever is expected to return
most. One step a day; on Saturdays and Sundays a chain the same day, each step kicking off after the
previous has finished and played only if it won. Only leagues with same-day results.

The same rules also run over every match day of the seasons in the data (history()). It is shown as
background and gives the calibrated confidence; the logs on the page start on the first live day.

Premier League goalscorers: the FPL model's expected goals per player (Advanced tab data, password),
chance to score = 1 - exp(-xG), midfielders and forwards only (defenders were overrated in the
2025/26 check, scripts/scorer_check.py). The model projects the next gameweek; for matches still to
come in the current gameweek a player's expected goals are his share of his team's expected goals
next gameweek times his team's expected goals in this match (from the exchange). The chances kept
between runs stay encrypted (scripts/cache/tips_private.enc.json); only those shown are public.

    python scripts/tips.py              # publish this run's card and the ladder plan if due, settle, write
    python scripts/tips.py --history    # also recompute the historical test (otherwise weekly)
"""

import argparse
import base64
import csv
import hashlib
import io
import itertools
import json
import math
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import advanced  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "tips.json")
OLD_ENC = os.path.join(ROOT, "docs", "data", "tips.enc.json")   # before the tab was opened up: read once, then removed
PRIVATE = os.path.join(ROOT, "scripts", "cache", "tips_private.enc.json")
ADV = os.path.join(ROOT, "docs", "data", "adv.enc.json")
SCORER_CHECK = os.path.join(ROOT, "scripts", "cache", "scorer_check.json")
FD = os.path.join(ROOT, "scripts", "cache", "fd")
DRAFT = "https://draft.premierleague.com/api/"
FIXTURES = "https://www.football-data.co.uk/fixtures.csv"
RESULTS = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={ymd}"
UK, CPH = ZoneInfo("Europe/London"), ZoneInfo("Europe/Copenhagen")

LEAGUES = {
    "E0": "Premier League", "E1": "Championship", "E2": "League One", "E3": "League Two", "EC": "National League",
    "SC0": "Skotsk Premiership", "SC1": "Skotsk Championship", "SC2": "Skotsk League One", "SC3": "Skotsk League Two",
    "D1": "Bundesliga", "D2": "2. Bundesliga", "SP1": "La Liga", "SP2": "La Liga 2", "I1": "Serie A", "I2": "Serie B",
    "F1": "Ligue 1", "F2": "Ligue 2", "N1": "Eredivisie", "B1": "Jupiler Pro League", "P1": "Primeira Liga",
    "T1": "Süper Lig", "G1": "Super League (GR)",
}
# ESPN scoreboard per league; the ladder only uses leagues checked to have same-day results there
ESPN_SLUG = {"E0": "eng.1", "E1": "eng.2", "E2": "eng.3", "E3": "eng.4", "EC": "eng.5", "SC0": "sco.1", "SC1": "sco.2",
             "SC2": "sco.3", "SC3": "sco.4", "D1": "ger.1", "D2": "ger.2", "SP1": "esp.1", "SP2": "esp.2", "I1": "ita.1",
             "I2": "ita.2", "F1": "fra.1", "F2": "fra.2", "N1": "ned.1", "B1": "bel.1", "P1": "por.1", "T1": "tur.1", "G1": "gre.1"}
FAST = {"E0", "E1", "E2", "E3", "SC0", "SC1", "D1", "D2", "SP1", "SP2", "I1", "I2", "F1", "F2", "N1", "T1", "G1"}
# football-data and FPL short names that don't resemble the full name
ALIAS = {"man city": "manchester city", "man united": "manchester united", "man utd": "manchester united",
         "nott'm forest": "nottingham forest", "wolves": "wolverhampton wanderers", "sheffield weds": "sheffield wednesday",
         "qpr": "queens park rangers", "mk dons": "milton keynes dons", "ath madrid": "atletico madrid",
         "ath bilbao": "athletic club", "sociedad": "real sociedad", "betis": "real betis", "espanol": "espanyol",
         "vallecano": "rayo vallecano", "celta": "celta vigo", "la coruna": "deportivo la coruna", "sp gijon": "sporting gijon",
         "ein frankfurt": "eintracht frankfurt", "m'gladbach": "monchengladbach", "fc koln": "koln", "paris sg": "paris saint germain",
         "inter": "internazionale", "milan": "ac milan", "st etienne": "saint etienne", "sp lisbon": "sporting cp",
         "for sittard": "fortuna sittard", "nijmegen": "nec nijmegen", "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
         "dag and red": "dagenham redbridge", "hearts": "heart of midlothian", "rennes": "stade rennais",
         "buyuksehyr": "istanbul basaksehir"}
HISTORY_SEASONS = ["2425", "2526", "2627"]
OVERROUND = (0.98, 1.06)   # exchange prices outside this are thin or stale: skip the market
VOID_AFTER = 10            # days after kick-off without a result: the match counts as void
WINDOW = timedelta(hours=24)
MATCH_LEN = timedelta(hours=2)   # kick-off to final whistle, with half-time and stoppage time
SLOTS = (11, 15)                 # publishing hours, Copenhagen

# tip rules
BANKER_P, BANKER_N, BANKER_MIN_PRICE = (0.70, 0.92), 4, 1.10
VALUE_P = (0.30, 0.75)
EDGE_N = 3
GOALS_P, GOALS_N = (0.55, 0.85), 3
SGM_P, SGM_N = (0.40, 0.70), 2
SAFE_MIN, SAFE_LEGS = 0.75, 4
MIX_P, MIX_TARGET, MIX_MAX = (0.55, 0.78), 4.0, 5
LONG_P, LONG_TARGET, LONG_MAX = (0.40, 0.65), 8.0, 5
PER_TYPE = 2                     # at most this many legs of one market type in a card section or acca
SCORER_N, SCORER_LIST = 3, 20
CAL_BINS = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

# ladder rules
LADDER_START = 100.0
LADDER_ODDS = (1.10, 1.20)
LADDER_GAP = timedelta(minutes=15)   # next step kicks off this long after the previous has finished
LADDER_MAX = 5
LADDER_POOL = 80                      # most likely legs considered for doubles
CHAIN_DAYS = (5, 6)                   # Saturday and Sunday


# ---------------------------------------------------------------- data

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (super-draft-league-site)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8-sig", errors="replace"), r.headers.get("Last-Modified")


def _get_json(url):
    return json.loads(_get(url)[0])


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


def season_of(d):
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def parse(text):
    """Matches from a football-data CSV: teams, kick-off, bet365 and exchange prices, score if played."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        d = _date(r.get("Date", ""))
        div = r.get("Div", "").strip()
        if not d or div not in LEAGUES or not r.get("HomeTeam"):
            continue
        ko = None
        if r.get("Time"):
            try:
                h, m = map(int, r["Time"].split(":"))
                ko = datetime(d.year, d.month, d.day, h, m, tzinfo=UK).astimezone(timezone.utc)
            except ValueError:
                pass
        try:
            score = (int(r["FTHG"]), int(r["FTAG"]))
        except (KeyError, ValueError):
            score = None
        out.append({
            "div": div, "date": d.isoformat(), "ko": ko.isoformat() if ko else None,
            "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(), "score": score,
            "b365": {"1x2": [_num(r.get(c)) for c in ("B365H", "B365D", "B365A")],
                     "ou": [_num(r.get(c)) for c in ("B365>2.5", "B365<2.5")]},
            "bfe": {"1x2": [_num(r.get(c)) for c in ("BFEH", "BFED", "BFEA")],
                    "ou": [_num(r.get(c)) for c in ("BFE>2.5", "BFE<2.5")]},
        })
    return out


def match_id(m):
    return f"{m['div']}|{m['date']}|{m['home']}|{m['away']}"


def leg_key(l):
    return f"{l['id']}|{l['mkt']}|{l['sel']}"


def fair(prices):
    """Exchange prices -> probabilities with the margin removed, or None if missing or implausible."""
    if not prices or any(p is None for p in prices):
        return None
    s = sum(1 / p for p in prices)
    if not OVERROUND[0] <= s <= OVERROUND[1]:
        return None
    return [1 / p / s for p in prices]


class Seasons:
    """football-data season files, fetched at most once per run (cached on disk for past seasons)."""

    def __init__(self, today):
        self.today, self.rows = today, {}

    def get(self, div, season):
        if (div, season) not in self.rows:
            path = os.path.join(FD, f"{div}_{season}.csv")
            text = None
            if os.path.exists(path) and season != season_of(self.today):
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            else:
                try:
                    text, _ = _get(RESULTS.format(season=season, div=div))
                    os.makedirs(FD, exist_ok=True)
                    with open(path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(text)
                except Exception as e:
                    print(f"  tips: results {div} {season} unavailable ({e})", flush=True)
            self.rows[(div, season)] = [m for m in parse(text) if m["score"]] if text else []
        return self.rows[(div, season)]


# ---------------------------------------------------------------- fast results (ESPN)

def norm(name):
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    n = ALIAS.get(n, n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    stop = {"fc", "afc", "cf", "sc", "ac", "as", "ss", "us", "club", "cd", "ud", "sd", "rc", "rcd", "vfl", "vfb", "tsg",
            "fsv", "sv", "calcio", "the", "de", "1", "04", "05"}
    return " ".join(w for w in n.split() if w not in stop)


def similar(a, b):
    a, b = norm(a), norm(b)
    if a == b:
        return 1.0
    if a and b and (a in b or b in a):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


class Espn:
    def __init__(self):
        self.days = {}

    def day(self, div, d):
        key = (div, d)
        if key not in self.days:
            out = []
            try:
                data = _get_json(ESPN.format(slug=ESPN_SLUG[div], ymd=d.strftime("%Y%m%d")))
                for e in data.get("events", []):
                    if not e["status"]["type"].get("completed"):
                        continue
                    c = {x["homeAway"]: x for x in e["competitions"][0]["competitors"]}
                    out.append({"home": c["home"]["team"]["displayName"], "away": c["away"]["team"]["displayName"],
                                "score": (int(c["home"]["score"]), int(c["away"]["score"]))})
            except Exception as e:
                print(f"  tips: ESPN {div} {d} unavailable ({e})", flush=True)
            self.days[key] = out
        return self.days[key]

    def score(self, div, ko, home, away):
        """Final score of a finished match, or None. Both team names must match well."""
        if div not in ESPN_SLUG:
            return None
        d = datetime.fromisoformat(ko).date()
        best = (0.0, None)
        for day in (d, d - timedelta(days=1)):
            for e in self.day(div, day):
                s = min(similar(home, e["home"]), similar(away, e["away"]))
                if s > best[0]:
                    best = (s, e["score"])
        return best[1] if best[0] >= 0.6 else None


# ---------------------------------------------------------------- probabilities and markets

_G = np.arange(0.1, 4.51, 0.05)
_K = np.arange(11)
_FACT = np.array([math.factorial(i) for i in _K], float)
GRID = None


def _grid():
    pk = np.exp(-_G[:, None]) * _G[:, None] ** _K / _FACT
    P = pk[:, None, :, None] * pk[None, :, None, :]
    x, y = np.indices((11, 11))
    return P[..., x > y].sum(-1).ravel(), P[..., x < y].sum(-1).ravel(), P[..., x + y > 2].sum(-1).ravel()


def implied(p1x2, pou):
    """Expected goals (home, away) that reproduce the exchange's 1X2 and over/under 2.5."""
    global GRID
    if GRID is None:
        GRID = _grid()
    H, A, O = GRID
    i = int(((H - p1x2[0]) ** 2 + (A - p1x2[2]) ** 2 + (O - pou[0]) ** 2).argmin())
    return float(_G[i // len(_G)]), float(_G[i % len(_G)])


def scoreline(lh, la):
    return np.outer(np.exp(-lh) * lh ** _K / _FACT, np.exp(-la) * la ** _K / _FACT)


# every market: (type, selection) -> test on a score. Lines are in the selection code.
WINS = {
    ("1x2", "H"): lambda h, a: h > a, ("1x2", "D"): lambda h, a: h == a, ("1x2", "A"): lambda h, a: h < a,
    ("dc", "1X"): lambda h, a: h >= a, ("dc", "X2"): lambda h, a: h <= a, ("dc", "12"): lambda h, a: h != a,
    ("ou", "O1.5"): lambda h, a: h + a > 1, ("ou", "U1.5"): lambda h, a: h + a < 2,
    ("ou", "O2.5"): lambda h, a: h + a > 2, ("ou", "U2.5"): lambda h, a: h + a < 3,
    ("ou", "O3.5"): lambda h, a: h + a > 3, ("ou", "U3.5"): lambda h, a: h + a < 4,
    ("btts", "Y"): lambda h, a: (h > 0) & (a > 0), ("btts", "N"): lambda h, a: (h == 0) | (a == 0),
    ("ts", "H"): lambda h, a: h > 0, ("ts", "A"): lambda h, a: a > 0,
    ("t2", "H"): lambda h, a: h > 1, ("t2", "A"): lambda h, a: a > 1,
}
GOAL_TYPES = ("ou", "btts", "ts", "t2")


# Chances from the score grid are a little off per market (checked on 2024-26 results: e.g. "over 1.5"
# said 80% happened 81.6%). Each market gets a correction fitted on the history's results,
# logit(p) -> a + b * logit(p), refitted with the weekly historical test. 1X2, double chance and
# over/under 2.5 come straight from the exchange and are not corrected.
CALIB = {}
CALIB_MIN = 300   # results needed to fit a market's correction


def calibrate(key, p):
    ab = CALIB.get(key)
    if not ab or not 0 < p < 1:
        return p
    z = ab[0] + ab[1] * math.log(p / (1 - p))
    return 1 / (1 + math.exp(-z))


def _platt(ps, ys):
    x = np.log(ps / (1 - ps))
    a, b = 0.0, 1.0
    for _ in range(30):
        q = 1 / (1 + np.exp(-(a + b * x)))
        w = q * (1 - q)
        g = np.array([np.sum(q - ys), np.sum((q - ys) * x)])
        H = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]])
        step = np.linalg.solve(H + 1e-9 * np.eye(2), g)
        a, b = a - step[0], b - step[1]
        if np.abs(step).max() < 1e-8:
            break
    return [round(float(a), 4), round(float(b), 4)]


def fit_calibration(matches):
    """Corrections per derived market from played matches, fitted on the uncorrected chances."""
    global CALIB
    saved, CALIB = CALIB, {}
    data = {}
    try:
        for m in matches:
            for l in legs(m) + same_match(m):
                if l["mkt"] in ("1x2", "dc") or (l["mkt"], l["sel"]) in (("ou", "O2.5"), ("ou", "U2.5")):
                    continue
                key = f"sgm|{l['sel'].split('+')[1]}" if l["mkt"] == "sgm" else f"{l['mkt']}|{l['sel']}"
                data.setdefault(key, []).append((min(max(l["p"], 0.001), 0.999), float(leg_result(l, m["score"]))))
    finally:
        CALIB = saved
    out = {}
    for key, v in data.items():
        if len(v) >= CALIB_MIN:
            a = np.array(v)
            out[key] = _platt(a[:, 0], a[:, 1])
    return out


def legs(m):
    """Every single bet of a match: probability, bet365 price (real or estimated) and expected return."""
    f1, fo = fair(m["bfe"]["1x2"]), fair(m["bfe"]["ou"])
    if not f1 or not fo:
        return []
    lh, la = implied(f1, fo)
    P = scoreline(lh, la)
    x, y = np.indices(P.shape)
    b1, bo = m["b365"]["1x2"], m["b365"]["ou"]
    # bet365's margin in this match, for markets the data has no price for
    margin = sum(1 / p for p in bo) if all(bo) else sum(1 / p for p in b1) if all(b1) else 1.07
    base = {"id": match_id(m), "div": m["div"], "date": m["date"], "ko": m["ko"], "home": m["home"], "away": m["away"],
            "xg": [round(lh, 2), round(la, 2)]}
    out = []
    for (mkt, sel), win in WINS.items():
        price, est = None, False
        if mkt == "1x2":
            p = f1["HDA".index(sel)]
            price = b1["HDA".index(sel)]
        elif mkt == "dc":
            p = sum(f1["1X2".index(c)] for c in sel)
            if all(b1):
                q = [1 / b1["1X2".index(c)] for c in sel]
                price, est = 1 / sum(q), True
        elif (mkt, sel) in (("ou", "O2.5"), ("ou", "U2.5")):
            i = 0 if sel == "O2.5" else 1
            p, price = fo[i], bo[i]
        else:
            p = calibrate(f"{mkt}|{sel}", float(P[win(x, y)].sum()))
        if price is None and p > 0:
            price, est = 1 / (p * margin), True
        if not price or price < 1.01:
            continue
        price = round(price, 2)
        out.append({**base, "mkt": mkt, "sel": sel, "p": round(float(p), 4), "price": price, "est": est,
                    "ev": round(p * price - 1, 4)})
    return out


def same_match(m):
    """Two-part bets inside one match (result or double chance with a goals market): the joint chance
    from the score grid, scaled so the result part matches the exchange (the grid has too few draws),
    the price estimated with bet365's margin on both parts."""
    f1, fo = fair(m["bfe"]["1x2"]), fair(m["bfe"]["ou"])
    if not f1 or not fo:
        return []
    lh, la = implied(f1, fo)
    P = scoreline(lh, la)
    x, y = np.indices(P.shape)
    b1, bo = m["b365"]["1x2"], m["b365"]["ou"]
    m1 = sum(1 / p for p in b1) if all(b1) else 1.06
    mo = sum(1 / p for p in bo) if all(bo) else 1.07
    out = []
    for (m_a, s_a), (m_b, s_b) in itertools.product([k for k in WINS if k[0] in ("1x2", "dc") and k[1] != "D"],
                                                     [k for k in WINS if k[0] in GOAL_TYPES]):
        wa, wb = WINS[(m_a, s_a)], WINS[(m_b, s_b)]
        p_grid = float(P[wa(x, y)].sum())
        p_exch = f1["HDA".index(s_a)] if m_a == "1x2" else sum(f1["1X2".index(c)] for c in s_a)
        p = min(float(P[wa(x, y) & wb(x, y)].sum()) * p_exch / p_grid, p_exch, float(P[wb(x, y)].sum()))
        p = calibrate(f"sgm|{m_b}:{s_b}", p)
        if p <= 0.05:
            continue
        price = round(1 / (p * m1 * mo), 2)
        out.append({"id": match_id(m), "div": m["div"], "date": m["date"], "ko": m["ko"], "home": m["home"], "away": m["away"],
                    "xg": [round(lh, 2), round(la, 2)], "mkt": "sgm", "sel": f"{m_a}:{s_a}+{m_b}:{s_b}",
                    "p": round(p, 4), "price": price, "est": True, "ev": round(p * price - 1, 4)})
    return out


# ---------------------------------------------------------------- tip rules

def _pick(cands, n, per_type=PER_TYPE, taken=(), key="id"):
    """Up to n candidates, one per match (or key), at most per_type of one market type."""
    seen, types, out = set(taken), {}, []
    for c in cands:
        t = c["mkt"]
        if c[key] in seen or types.get(t, 0) >= per_type:
            continue
        out.append(c)
        seen.add(c[key])
        types[t] = types.get(t, 0) + 1
        if len(out) == n:
            break
    return out


def _acca(kind, ls):
    price = math.prod(l["price"] for l in ls)
    p = math.prod(l["p"] for l in ls)
    return {"kind": kind, "legs": ls, "price": round(price, 2), "p": round(p, 4), "ev": round(p * price - 1, 4),
            "est": any(l["est"] for l in ls)}


def _build_to(cands, target, max_legs):
    out = []
    types = {}
    for l in cands:
        if any(x["id"] == l["id"] for x in out) or types.get(l["mkt"], 0) >= PER_TYPE:
            continue
        out.append(l)
        types[l["mkt"]] = types.get(l["mkt"], 0) + 1
        if math.prod(x["price"] for x in out) >= target or len(out) == max_legs:
            break
    return out


def build_card(matches, scorers=(), skip=()):
    """Singles, same-match combinations and accas for one batch of matches. `skip`: leg keys already
    tipped today. Deterministic: same matches, same card."""
    every = [l for m in matches for l in legs(m) if leg_key(l) not in skip]
    real = [l for l in every if not l["est"]]
    singles, accas = [], []

    bankers = _pick(sorted((l for l in every if BANKER_P[0] <= l["p"] <= BANKER_P[1] and l["price"] >= BANKER_MIN_PRICE),
                           key=lambda l: (-l["p"], -l["ev"])), BANKER_N)
    singles += [{**l, "kind": "banker"} for l in bankers]
    used = {l["id"] for l in bankers}
    value = _pick(sorted((l for l in real if VALUE_P[0] <= l["p"] <= VALUE_P[1]), key=lambda l: -l["ev"]), 3, taken=used)
    singles += [{**l, "kind": "value"} for l in value]
    # bet365 above the exchange's fair price: the "value" a model sees. betting_books.py found the market
    # usually moves against these, so they are tracked to show whether it holds up here.
    edge = _pick(sorted((l for l in real if l["ev"] > 0), key=lambda l: -l["ev"]), EDGE_N)
    singles += [{**l, "kind": "edge"} for l in edge]
    used |= {l["id"] for l in value}
    goals = _pick(sorted((l for l in every if l["mkt"] in GOAL_TYPES and GOALS_P[0] <= l["p"] <= GOALS_P[1]),
                         key=lambda l: (-l["p"], -l["ev"])), GOALS_N, per_type=1, taken=used)
    singles += [{**l, "kind": "goals"} for l in goals]
    sgm = _pick(sorted((s for m in matches for s in same_match(m) if leg_key(s) not in skip and SGM_P[0] <= s["p"] <= SGM_P[1]),
                       key=lambda s: (-s["ev"], -s["p"])), SGM_N, per_type=SGM_N)
    singles += [{**l, "kind": "sgm"} for l in sgm]
    # one scorer per match, so a single game's news can't sink all three
    singles += [{**l, "kind": "scorer"} for l in _pick(sorted((s for s in scorers if leg_key(s) not in skip), key=lambda l: -l["p"]),
                                                       SCORER_N, per_type=SCORER_N, key="fixture")]

    safe = _pick(sorted((l for l in every if l["p"] >= SAFE_MIN and l["price"] >= 1.12), key=lambda l: (-l["ev"], -l["p"])), SAFE_LEGS)
    if len(safe) >= 3:
        accas.append(_acca("safe", safe))
    mix = _build_to(sorted((l for l in every if MIX_P[0] <= l["p"] <= MIX_P[1]), key=lambda l: (-l["ev"], -l["p"])), MIX_TARGET, MIX_MAX)
    if len(mix) >= 3:
        accas.append(_acca("mix", mix))
    long_ = _build_to(sorted((l for l in every if LONG_P[0] <= l["p"] <= LONG_P[1]), key=lambda l: -l["ev"]), LONG_TARGET, LONG_MAX)
    if len(long_) >= 3 and math.prod(x["price"] for x in long_) >= 5:
        accas.append(_acca("long", long_))
    return singles, accas


def _end(step):
    return max(datetime.fromisoformat(l["ko"]) for l in step["legs"]) + MATCH_LEN


def _start(step):
    return min(datetime.fromisoformat(l["ko"]) for l in step["legs"])


def ladder_steps(matches):
    """Every possible ladder step in these matches: singles or doubles (different matches) with total
    odds 1.10-1.20, in leagues with same-day results."""
    pool = [l for m in matches if m["div"] in FAST and m["ko"] for l in legs(m)]
    steps = [{"legs": [l], "price": l["price"], "p": l["p"]} for l in pool if LADDER_ODDS[0] <= l["price"] <= LADDER_ODDS[1]]
    small = sorted((l for l in pool if l["price"] < LADDER_ODDS[1]), key=lambda l: -l["p"])[:LADDER_POOL]
    for a, b in itertools.combinations(small, 2):
        price = round(a["price"] * b["price"], 2)
        if a["id"] != b["id"] and LADDER_ODDS[0] <= price <= LADDER_ODDS[1]:
            steps.append({"legs": sorted([a, b], key=lambda l: l["ko"]), "price": price, "p": a["p"] * b["p"]})
    for s in steps:
        s["p"] = round(s["p"], 4)
        s["ev"] = round(s["p"] * s["price"] - 1, 4)
        s["est"] = any(l["est"] for l in s["legs"])
    return steps


def ladder_plan(matches, chain):
    """One day's ladder steps. A single step: the one expected to return most. A chain: the longest
    sequence that fits (each step kicking off after the previous has finished), and of those the one
    most likely to survive."""
    steps = sorted(ladder_steps(matches), key=lambda s: _start(s))
    if not steps:
        return []
    if not chain:
        return [max(steps, key=lambda s: (s["ev"], s["p"]))]
    best = []   # best[i] = (length, sum log p, chain) ending with steps[i]
    for i, s in enumerate(steps):
        opt = (1, math.log(s["p"]), [s])
        for j in range(i):
            n, lp, ch = best[j]
            if n < LADDER_MAX and _end(steps[j]) + LADDER_GAP <= _start(s) and (n + 1, lp + math.log(s["p"])) > opt[:2]:
                opt = (n + 1, lp + math.log(s["p"]), ch + [s])
        best.append(opt)
    return max(best, key=lambda b: b[:2])[2]


# ---------------------------------------------------------------- reasons and confidence

# ---------------------------------------------------------------- watchlist: matches with a story

ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/news?limit=50"
NEWS_AGE = timedelta(hours=72)
WATCH_N, WATCH_MIN = 6, 2.0
# headline words -> kind of news, checked in this order; transfer gossip is left out
NEWS_KINDS = [
    ("udelukket", ("suspend", " ban ", "banned", "red card")),
    ("skade", ("injur", "hamstring", "knee", "ankle", "ruled out", "sidelined", "doubt", "fitness", "fit to", "surgery", "setback", "out for")),
    ("comeback", ("return", "back in training", "back from", "available again")),
    ("træner", ("sack", "fired", "interim", "appoint", "new manager", "new coach", "replace", "job ")),
    ("krise", ("crisis", "pressure", "blast", "slump", "turmoil", " row", "unrest")),
]
NEWS_SKIP = ("transfer", "rumor", "rumour", "eye ", "target", "linked")


def fetch_news(divs, now):
    """ESPN headlines of the last three days per league, with the teams each is tagged with."""
    out = []
    for div in divs:
        if div not in ESPN_SLUG:
            continue
        try:
            data = _get_json(ESPN_NEWS.format(slug=ESPN_SLUG[div]))
        except Exception as e:
            print(f"  tips: ESPN news {div} unavailable ({e})", flush=True)
            continue
        for a in data.get("articles", []):
            try:
                t = datetime.fromisoformat(a["published"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            head = a.get("headline") or ""
            low = f" {head.lower()} "
            if now - t > NEWS_AGE or any(w in low for w in NEWS_SKIP):
                continue
            kind = next((k for k, words in NEWS_KINDS if any(w in low for w in words)), None)
            if not kind:
                continue
            out.append({"div": div, "kind": kind, "headline": head, "link": (a.get("links") or {}).get("web", {}).get("href"),
                        "published": t.isoformat(timespec="minutes"),
                        "teams": [c["description"] for c in a.get("categories", []) if c.get("type") == "team" and c.get("description")]})
    return out


def fpl_absences(boot):
    """Premier League players who matter and may miss the next match: injured, suspended or at most 50%
    to play. "Matter": in the top four of his team on points this season, or drafted in the top 80."""
    if not boot:
        return {}
    teams = {t["id"]: t["name"] for t in boot["teams"]}
    by_team = {}
    for e in boot["elements"]:
        by_team.setdefault(e["team"], []).append(e)
    out = {}
    for tid, es in by_team.items():
        top = sorted(es, key=lambda e: -(e.get("total_points") or 0))[:4]
        for e in es:
            chance = e.get("chance_of_playing_next_round")
            out_now = e["status"] in ("i", "s") or (e["status"] == "d" and chance is not None and chance <= 50)
            if out_now and (e in top or (e.get("draft_rank") or 999) <= 80):
                out.setdefault(teams[tid], []).append(f"{e['web_name']} ({e.get('news') or 'ude'})")
    return out


def standings(rows):
    t = {}
    for m in rows:
        hg, ag = m["score"]
        for team, gf, ga in ((m["home"], hg, ag), (m["away"], ag, hg)):
            s = t.setdefault(team, {"pts": 0, "gd": 0, "gp": 0})
            s["pts"] += 3 if gf > ga else 1 if gf == ga else 0
            s["gd"] += gf - ga
            s["gp"] += 1
    for pos, team in enumerate(sorted(t, key=lambda x: (-t[x]["pts"], -t[x]["gd"])), 1):
        t[team]["pos"] = pos
    return t


def _side(team, home, away):
    sh, sa = similar(team, home), similar(team, away)
    if max(sh, sa) < 0.85:
        return None
    return "H" if sh >= sa else "A"


def watch_match(m, rows, news, absences, seen):
    """The stories around one match, a score for how notable it is, and which way they lean:
    news (ESPN), missing players (FPL, Premier League), a top or bottom clash, form against the market's
    view, a goals tendency, and the exchange moving since we first saw the match."""
    ls = legs(m)
    if not ls:
        return None
    by = {(l["mkt"], l["sel"]): l for l in ls}
    name = {"H": m["home"], "A": m["away"]}
    stories, lean, score = [], [], 0.0

    for side in "HA":
        kinds = {}
        for a in news:
            if a["div"] == m["div"] and any(_side(t, m["home"], m["away"]) == side for t in a["teams"]) and a["kind"] not in kinds:
                kinds[a["kind"]] = a
        # news is context: a headline can't tell which way it moves the match, so it doesn't pick the bet
        for kind, a in kinds.items():
            stories.append({"type": kind, "side": side, "text": f"{name[side]}: “{a['headline']}”", "link": a["link"]})
            score += 2 if len(kinds) < 3 else 0.5
    if m["div"] == "E0":
        for team, players in absences.items():
            side = _side(team, m["home"], m["away"])
            if side:
                stories.append({"type": "fravær", "side": side, "text": f"{name[side]} mangler måske: {', '.join(players[:3])}."})
                score += 2
                lean.append(("dc", "A" if side == "H" else "H"))

    played = [r for r in rows if r["date"] < m["date"]]
    if played:
        tab = standings(played)
        th, ta = tab.get(m["home"]), tab.get(m["away"])
        n = len(tab)
        if th and ta and min(th["gp"], ta["gp"]) >= 5:
            if th["pos"] <= 4 and ta["pos"] <= 4:
                stories.append({"type": "tabel", "text": f"Topopgør: nr. {th['pos']} mod nr. {ta['pos']}."})
                score += 1.5
            elif th["pos"] > n - 4 and ta["pos"] > n - 4:
                stories.append({"type": "tabel", "text": f"Bundopgør: nr. {th['pos']} mod nr. {ta['pos']} af {n}."})
                score += 1.5
        p_win = {"H": by.get(("1x2", "H"), {}).get("p"), "A": by.get(("1x2", "A"), {}).get("p")}
        forms = {s: form_of(played, name[s], m["date"]) for s in "HA"}
        for side in "HA":
            f5 = forms[side][-5:]
            if len(f5) < 5 or p_win[side] is None:
                continue
            pts = sum(3 if x["r"] == "V" else 1 if x["r"] == "U" else 0 for x in f5)
            seq = " ".join(x["r"] for x in f5)
            if pts >= 10 and p_win[side] <= 0.35:
                stories.append({"type": "form", "side": side, "text": f"{name[side]} er i stærk form ({seq}), men markedet giver kun {round(p_win[side] * 100)}% for sejr."})
                score += 2
                lean.insert(0, ("dc", side))
            elif pts <= 2 and p_win[side] >= 0.55:
                other = "A" if side == "H" else "H"
                stories.append({"type": "form", "side": side, "text": f"{name[side]} er favorit ({round(p_win[side] * 100)}%) trods dårlig form ({seq})."})
                score += 2
                lean.insert(0, ("dc", other))
        if all(len(forms[s]) >= 5 for s in "HA"):
            avg = {s: sum(x["gf"] + x["ga"] for x in forms[s]) / len(forms[s]) for s in "HA"}
            btts = {s: sum(x["gf"] > 0 and x["ga"] > 0 for x in forms[s]) / len(forms[s]) for s in "HA"}
            if min(avg.values()) >= 3.0:
                stories.append({"type": "mål", "text": f"Målrige hold: {_fmt(avg['H'])} og {_fmt(avg['A'])} mål i snit i deres kampe."})
                score += 1.5
                lean.append(("ou", "O2.5"))
            elif min(btts.values()) >= 0.65:
                stories.append({"type": "mål", "text": f"Begge hold scorede i {round(btts['H'] * 100)}% og {round(btts['A'] * 100)}% af deres kampe."})
                score += 1.5
                lean.append(("btts", "Y"))
            elif max(avg.values()) <= 2.1:
                stories.append({"type": "mål", "text": f"Målfattige hold: {_fmt(avg['H'])} og {_fmt(avg['A'])} mål i snit."})
                score += 1.5
                lean.append(("ou", "U2.5"))
        # no rest days: the data has league matches only, so cup and European games would look like rest

    first = seen.get(match_id(m))
    if first:
        for side in "HA":
            now_p, was = by.get(("1x2", side), {}).get("p"), first["p"][0 if side == "H" else 2]
            if now_p is not None and abs(now_p - was) >= 0.06:
                up = now_p > was
                stories.append({"type": "marked", "side": side, "text": f"Markedet har flyttet sig: {name[side]} fra {round(was * 100)}% til {round(now_p * 100)}% for sejr."})
                score += 2
                lean.insert(0, ("dc", side if up else ("A" if side == "H" else "H")))
    if score < WATCH_MIN:
        return None

    # the bet the stories point to: the first lean that has a price worth playing, else the most likely
    # double chance or goals bet at odds of at least 1.30
    pick_ = None
    for mkt, sel in lean:
        sel = {"H": "1X", "A": "X2"}.get(sel, sel) if mkt == "dc" else sel
        l = by.get((mkt, sel))
        if l and l["price"] >= 1.20 and l["p"] >= 0.45:
            pick_ = l
            break
    if not pick_:
        pool = [l for l in ls if l["mkt"] in ("dc", "ou", "btts") and l["price"] >= 1.30]
        pick_ = max(pool, key=lambda l: l["p"], default=None)
    if not pick_:
        return None
    return {"id": match_id(m), "div": m["div"], "date": m["date"], "ko": m["ko"], "home": m["home"], "away": m["away"],
            "score": round(score, 1), "stories": stories, "leg": {**pick_, "kind": "watch"}}


def form_of(rows, team, before):
    """A team's league matches this season before a date: results, goals."""
    out = []
    for m in rows:
        if team not in (m["home"], m["away"]) or m["date"] >= before:
            continue
        home = m["home"] == team
        gf, ga = m["score"] if home else m["score"][::-1]
        out.append({"home": home, "gf": gf, "ga": ga, "r": "V" if gf > ga else "U" if gf == ga else "T"})
    return out


def _ppg(ms):
    return sum(3 if x["r"] == "V" else 1 if x["r"] == "U" else 0 for x in ms) / len(ms) if ms else None


def _fmt(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def _team_line(team, f, side, goals):
    venue = [x for x in f if x["home"] == side]
    bits = [f"form {' '.join(x['r'] for x in f[-5:])}", f"{_fmt(_ppg(f), 2)} point per kamp"]
    if venue:
        bits.append(f"{'hjemme' if side else 'ude'} {_fmt(_ppg(venue), 2)}")
    if goals:
        bits.append(f"scorer {_fmt(sum(x['gf'] for x in f) / len(f))} og lukker {_fmt(sum(x['ga'] for x in f) / len(f))} ind per kamp")
        bits.append(f"scorede i {round(100 * sum(x['gf'] > 0 for x in f) / len(f))}% af kampene")
    return f"{team}: " + ", ".join(bits) + "."


def market_line(l):
    """First reason of a tip: where the chance comes from, and the price against it."""
    if l["mkt"] in ("1x2", "dc") or (l["mkt"], l["sel"]) in (("ou", "O2.5"), ("ou", "U2.5")):
        src = "Betfair Exchange"
    else:
        src = "Markedets forventede mål (fra Betfair Exchange, justeret efter testen)"
    line = f"{src}: {round(l['p'] * 100)}% (fair odds {_fmt(1 / l['p'], 2)})."
    if l.get("est"):
        line += f" bet365 ca. {_fmt(l['price'], 2)} (skønnet med bet365's margin; tjek prisen)."
    else:
        line += f" bet365 giver {_fmt(l['price'], 2)}, {'over' if l['ev'] > 0 else 'under'} fair med {_fmt(abs(l['ev']) * 100)}%."
    return line


def explain(l, rows, cal):
    """Reasons behind a tip (frozen with it) and how often tips like it hit in the historical test."""
    why = []
    if l["mkt"] == "scorer":
        why.append(f"FPL-modellen: {_fmt(l['xg_player'], 2)} forventede mål i kampen, {l['emin']} forventede minutter"
                   + (f", {round(l['p_start'] * 100)}% chance for at starte" if l.get("p_start") is not None else "") + ".")
        if l.get("basis") == "share":
            why.append("Spillerens andel af holdets forventede mål i næste runde, ganget med markedets forventede mål for holdet i denne kamp.")
        if l.get("pen"):
            why.append("Førstevalg til straffespark.")
        why.append(f"Fair odds {_fmt(1 / l['p'], 2)}: bet365 skal give mere end det, før spillet er pengene værd.")
    else:
        why.append(market_line(l))
        if l.get("xg"):
            lh, la = l["xg"]
            why.append(f"Markedet venter {_fmt(lh)}–{_fmt(la)} i mål ({_fmt(lh + la)} i alt).")
        goals = l["mkt"] in GOAL_TYPES or l["mkt"] == "sgm"
        for team, side in ((l["home"], True), (l["away"], False)):
            f = form_of(rows, team, l["date"])
            if f:
                why.append(_team_line(team, f, side, goals))
    conf = None
    for b in cal or []:
        if b["lo"] <= l["p"] < b["hi"] or (b["hi"] == 1.0 and l["p"] >= 1.0):
            conf = {"lo": b["lo"], "hi": b["hi"], "obs": b["obs"], "n": b["n"]}
    return {**l, "why": why, "conf": conf}


# ---------------------------------------------------------------- settling

def leg_result(leg, score):
    if leg["mkt"] == "sgm":
        return all(WINS[tuple(part.split(":"))](*score) for part in leg["sel"].split("+"))
    return WINS[(leg["mkt"], leg["sel"])](*score)


def settle_leg(leg, scores, today):
    if leg.get("res"):
        return
    r = scores.get(leg["id"]) if leg["mkt"] != "manual" else None   # a free-text bet is settled on the page
    if leg["mkt"] == "scorer":
        if r:      # (goals, minutes) once the match is finished
            leg["res"] = "void" if r[1] == 0 else "won" if r[0] > 0 else "lost"
            leg["score"] = f"{r[0]} mål" if r[1] else "spillede ikke"
    elif r:
        leg["res"] = "won" if leg_result(leg, r) else "lost"
        leg["score"] = f"{r[0]}-{r[1]}"
    if not leg.get("res") and date.fromisoformat(leg["date"]) + timedelta(days=VOID_AFTER) < today:
        leg["res"] = "void"


def settle_acca(a):
    """An acca or a ladder step: lost on any lost leg, won when the rest are settled (void legs drop out)."""
    rs = [l.get("res") for l in a["legs"]]
    a["legs_hit"] = rs.count("won")
    if "lost" in rs:
        a["res"] = "lost"
    elif all(rs):
        won = [l for l in a["legs"] if l["res"] == "won"]
        a["res"] = "won" if won else "void"
        a["paid"] = round(math.prod(l["price"] for l in won), 2) if won else None
    else:
        a.pop("res", None)


def all_legs(cards, ladder=None):
    out = [l for c in cards for l in c["singles"] + [x for a in c["accas"] for x in a["legs"]] + [w["leg"] for w in c.get("watch", [])]]
    if ladder:
        out += [l for r in ladder["runs"] for b in r["bets"] for l in b["legs"]]
    return out


def results(open_legs, now, seasons, espn):
    """Scores for open legs: FPL live for scorers, ESPN the same day, football-data as the fallback."""
    out = scorer_results([l for l in open_legs if l["mkt"] == "scorer"])
    by_id = {}
    for l in open_legs:
        if l["mkt"] != "scorer" and l.get("ko") and datetime.fromisoformat(l["ko"]) + MATCH_LEN < now:
            by_id.setdefault(l["id"], l)
    for i, l in by_id.items():
        s = espn.score(l["div"], l["ko"], l["home"], l["away"])
        if s is None:
            fd = {match_id(m): m["score"] for m in seasons.get(l["div"], season_of(date.fromisoformat(l["date"])))}
            s = fd.get(i)
        if s is not None:
            out[i] = tuple(s)
    return out


def settle(cards, scores, today):
    for c in cards:
        for l in c["singles"] + [w["leg"] for w in c.get("watch", [])]:
            settle_leg(l, scores, today)
        for a in c["accas"]:
            for l in a["legs"]:
                settle_leg(l, scores, today)
            settle_acca(a)


def profit_single(l):
    if not l.get("price") or l.get("res") not in ("won", "lost"):
        return None
    return l["price"] - 1 if l["res"] == "won" else -1.0


def profit_acca(a):
    if a.get("res") == "won":
        return a["paid"] - 1
    return -1.0 if a.get("res") == "lost" else None


# ---------------------------------------------------------------- ladder

def ladder_walk(lad):
    """Stakes and status from the steps' results: each won step's payout is the next stake; a loss ends
    the attempt, and steps planned after it that day are not played."""
    for run in lad["runs"]:
        stake, current, broken, waiting = LADDER_START, None, False, False
        run["steps"], run["peak"] = 0, LADDER_START
        for b in run["bets"]:
            settle_acca(b)
            if broken:
                b["res"] = "skipped"
                b["stake"] = b["payout"] = None
                continue
            if waiting:   # after an open step: the stake it gets if everything before it wins
                b["stake"], b["payout"], b["if_won"] = round(stake, 2), round(stake * b["price"], 2), True
                stake *= b["price"]
                continue
            b.pop("if_won", None)
            b["stake"] = round(stake, 2)
            b["payout"] = round(stake * b["price"], 2)
            if b.get("res") == "won":
                stake = stake * b["paid"]
                b["payout"] = round(stake, 2)
                run["steps"] += 1
                run["peak"] = max(run["peak"], stake)
            elif b.get("res") == "lost":
                broken = True
                run["broke"] = {"day": b["day"], "legs": [{k: l.get(k) for k in ("mkt", "sel", "home", "away", "score", "res", "text", "player")} for l in b["legs"]],
                                "price": b["price"]}
            elif b.get("res") != "void":
                waiting, current = True, stake
                stake *= b["price"]
        run["status"] = "broken" if broken else "alive"
        run["stake"] = None if broken else round(current if waiting else stake, 2)
        run["end"] = run["bets"][-1]["day"] if run["bets"] else run["start"]


def ladder_step(lad, matches, now, today, why):
    """Plan today's ladder steps if not done and the previous step is settled."""
    if any(b["day"] == today.isoformat() for r in lad["runs"] for b in r["bets"]):
        return
    run = lad["runs"][-1] if lad["runs"] else None
    if run and run["status"] == "alive" and any(not b.get("res") for b in run["bets"]):
        print("  tips: ladder waits for a result", flush=True)
        return
    day_end = datetime.combine(today + timedelta(days=1), datetime.min.time(), CPH)
    today_ms = [m for m in matches if m["ko"] and now + timedelta(minutes=15) < datetime.fromisoformat(m["ko"]) < day_end]
    plan = ladder_plan(today_ms, today.weekday() in CHAIN_DAYS)
    if not plan:
        print("  tips: no ladder step today", flush=True)
        return
    if not run or run["status"] == "broken":
        run = {"id": len(lad["runs"]) + 1, "start": today.isoformat(), "bets": []}
        lad["runs"].append(run)
    for i, s in enumerate(plan):
        run["bets"].append({**s, "legs": [why(l) for l in s["legs"]], "day": today.isoformat(), "order": i + 1, "of": len(plan)})
    print(f"  tips: ladder attempt {run['id']}, {len(plan)} step(s) today", flush=True)


def find_step(lad, ref):
    """A ladder step by its reference on the page, "attempt:day:order"."""
    try:
        rid, day, order = ref.split(":")
    except ValueError:
        return None, None
    for r in lad["runs"]:
        if str(r["id"]) == rid:
            for i, b in enumerate(r["bets"]):
                if b["day"] == day and str(b["order"]) == order:
                    return r, i
    return None, None


def _summary(b):
    return {"legs": [{k: l.get(k) for k in ("mkt", "sel", "home", "away", "text", "price")} for l in b["legs"]],
            "price": b["price"], "manual": bool(b.get("manual"))}


def ladder_action(lad, a, matches, now, why):
    """A change asked for on the page (through the workflow's inputs): swap a step for the next best one
    that fits the chain, put in the user's own bet, or settle the user's own free-text bet. A swap keeps
    what it replaced. Only steps not yet settled or kicked off can be swapped."""
    run, i = find_step(lad, a.get("step", ""))
    if run is None:
        print(f"  tips: ladder step {a.get('step')!r} not found", flush=True)
        return
    b = run["bets"][i]
    if a["action"] == "result":
        if b.get("manual") and a.get("res") in ("won", "lost", "void"):
            for l in b["legs"]:
                if l["mkt"] == "manual":
                    l["res"] = a["res"]
            print(f"  tips: ladder step {a['step']} marked {a['res']}", flush=True)
        return
    if b.get("res") or any(l.get("ko") and datetime.fromisoformat(l["ko"]) <= now for l in b["legs"]):
        print(f"  tips: ladder step {a['step']} is settled or has kicked off; not swapped", flush=True)
        return
    keep = {"day": b["day"], "order": b["order"], "of": b["of"], "replaced": b.get("replaced", []) + [_summary(b)]}

    if a["action"] == "replace":
        same_day = lambda j: 0 <= j < len(run["bets"]) and run["bets"][j]["day"] == b["day"]
        prev = run["bets"][i - 1] if same_day(i - 1) and all(l.get("ko") for l in run["bets"][i - 1]["legs"]) else None
        nxt = run["bets"][i + 1] if same_day(i + 1) and all(l.get("ko") for l in run["bets"][i + 1]["legs"]) else None
        lo = max(now + timedelta(minutes=10), _end(prev) + LADDER_GAP if prev else now)
        day_end = datetime.combine(date.fromisoformat(b["day"]) + timedelta(days=1), datetime.min.time(), CPH)
        used = {leg_key(l) for x in run["bets"] for l in x["legs"]} | {f"{l['home']}|{l['mkt']}|{l['sel']}" for r in keep["replaced"] for l in r["legs"]}
        ms = [m for m in matches if m["ko"] and lo <= datetime.fromisoformat(m["ko"]) < day_end]
        cands = [s for s in ladder_steps(ms) if _start(s) >= lo and (_end(s) + LADDER_GAP <= _start(nxt) if nxt else True)
                 and not any(leg_key(l) in used or f"{l['home']}|{l['mkt']}|{l['sel']}" in used for l in s["legs"])]
        if not cands:
            b["note"] = f"Ingen anden bet passer ind ({now.astimezone(CPH):%d/%m %H:%M})."
            print(f"  tips: no other bet fits ladder step {a['step']}", flush=True)
            return
        s = max(cands, key=lambda s: (s["ev"], s["p"]))
        run["bets"][i] = {**s, "legs": [why(l) for l in s["legs"]], **keep}
        print(f"  tips: ladder step {a['step']} swapped", flush=True)
        return

    if a["action"] == "manual":
        try:
            odds = round(float(str(a.get("odds", "")).replace(",", ".")), 2)
        except ValueError:
            odds = 0
        if not 1.01 <= odds <= 1000:
            print(f"  tips: odds {a.get('odds')!r} not accepted", flush=True)
            return
        m = next((m for m in matches if match_id(m) == a.get("match")), None)
        base = {"p": None, "price": odds, "est": False, "ev": None, "manual": True, "why": ["Dit eget valg."], "conf": None}
        if m and (a.get("mkt"), a.get("sel")) in WINS:
            leg = {"id": match_id(m), "div": m["div"], "date": m["date"], "ko": m["ko"], "home": m["home"], "away": m["away"],
                   "mkt": a["mkt"], "sel": a["sel"], **base}
        elif a.get("text", "").strip():
            leg = {"id": f"manual|{now.isoformat(timespec='seconds')}", "div": "", "date": b["day"], "ko": None, "home": "", "away": "",
                   "mkt": "manual", "sel": "", "text": a["text"].strip()[:120], **base}
        else:
            print("  tips: own bet needs a match and market, or a text", flush=True)
            return
        run["bets"][i] = {"legs": [leg], "price": odds, "p": None, "ev": None, "est": False, "manual": True, **keep}
        print(f"  tips: ladder step {a['step']} set to own bet at {odds}", flush=True)


def reprice(cards, lad, cal_bins):
    """Once: bets published before the per-market corrections get the corrected chance and, where the
    odds were estimated from that chance, the odds that follow from it. The originals are kept."""
    def fix(l):
        if not l.get("est") or l["mkt"] in ("1x2", "dc", "scorer", "manual") or (l["mkt"], l["sel"]) in (("ou", "O2.5"), ("ou", "U2.5")):
            return
        key = f"sgm|{l['sel'].split('+')[1]}" if l["mkt"] == "sgm" else f"{l['mkt']}|{l['sel']}"
        p_new = calibrate(key, l["p"])
        l["p_raw"], l["price_orig"] = l["p"], l["price"]
        l["price"] = round(l["price"] * l["p"] / p_new, 2)
        l["p"] = round(p_new, 4)
        l["ev"] = round(l["p"] * l["price"] - 1, 4)
        if l.get("why"):
            l["why"][0] = market_line(l)
        for b in cal_bins or []:
            if b["lo"] <= l["p"] < b["hi"] or (b["hi"] == 1.0 and l["p"] >= 1.0):
                l["conf"] = {"lo": b["lo"], "hi": b["hi"], "obs": b["obs"], "n": b["n"]}

    def total(x):
        x["price"] = round(math.prod(l["price"] for l in x["legs"]), 2)
        x["p"] = round(math.prod(l["p"] for l in x["legs"]), 4)
        x["ev"] = round(x["p"] * x["price"] - 1, 4)

    for c in cards:
        for l in c["singles"] + [w["leg"] for w in c.get("watch", [])]:
            fix(l)
        for a in c["accas"]:
            for l in a["legs"]:
                fix(l)
            total(a)
            settle_acca(a)
    for r in lad["runs"]:
        for b in r["bets"]:
            if b.get("manual"):
                continue
            for l in b["legs"]:
                fix(l)
            total(b)


def ladder_summary(lad):
    runs = lad["runs"]
    done = [r for r in runs if r["status"] == "broken"]
    bets = [b for r in runs for b in r["bets"] if b.get("res") in ("won", "lost")]
    ours = [b for b in bets if b.get("p") is not None]   # the user's own bets have no chance of ours
    best = max(runs, key=lambda r: (r["steps"], r["peak"]), default=None)
    return {"runs": len(runs), "broken": len(done), "bets": len(bets),
            "hit": round(sum(b["res"] == "won" for b in bets) / len(bets), 4) if bets else None,
            "expected": round(sum(b["p"] for b in ours) / len(ours), 4) if ours else None,
            "manual": sum(1 for r in runs for b in r["bets"] if b.get("manual")),
            "doubles": sum(len(b["legs"]) > 1 for r in runs for b in r["bets"]),
            "avg_steps": round(sum(r["steps"] for r in done) / len(done), 2) if done else None,
            "best": {"steps": best["steps"], "peak": best["peak"], "start": best["start"], "end": best["end"]} if best else None,
            "spent": LADDER_START * len(runs),
            # how far each attempt got before it failed
            "log": [{"id": r["id"], "start": r["start"], "end": r["end"], "steps": r["steps"], "peak": r["peak"],
                     "status": r["status"], "broke": r.get("broke")} for r in runs]}


# ---------------------------------------------------------------- track record

def summarise(cards):
    """Hit rates against the probabilities' promise, profit in units, calibration and near misses."""
    def block(items, prof):
        done = [x for x in items if x.get("res") in ("won", "lost")]
        if not done:
            return {"n": 0, "pending": sum(1 for x in items if not x.get("res"))}
        won = sum(1 for x in done if x["res"] == "won")
        pr = [prof(x) for x in done if prof(x) is not None]
        return {"n": len(done), "won": won, "lost": len(done) - won, "hit": round(won / len(done), 4),
                "expected": round(sum(x["p"] for x in done) / len(done), 4),
                "staked": len(pr), "profit": round(sum(pr), 2), "roi": round(sum(pr) / len(pr), 4) if pr else None,
                "exp_roi": round(sum(x["ev"] for x in done if x.get("ev") is not None) / len(done), 4),
                "est": sum(1 for x in done if x.get("est") and prof(x) is not None),   # results at estimated odds
                "pending": sum(1 for x in items if not x.get("res"))}

    singles = [l for c in cards for l in c["singles"]]
    accas = [a for c in cards for a in c["accas"]]
    out = {"singles": block([l for l in singles if l.get("price")], profit_single), "accas": block(accas, profit_acca), "kinds": {}}
    for k in ("banker", "value", "edge", "goals", "sgm", "scorer"):
        out["kinds"][k] = block([l for l in singles if l["kind"] == k], profit_single)
    # the watchlist's bets: do matches with a story do better than the rest?
    out["kinds"]["watch"] = block([w["leg"] for c in cards for w in c.get("watch", [])], profit_single)
    for k in ("safe", "mix", "long"):
        out["kinds"][k] = block([a for a in accas if a["kind"] == k], profit_acca)
    # every distinct settled leg, singles and acca legs alike: are the probabilities honest?
    seen, cal_legs = set(), []
    for l in singles + [l for a in accas for l in a["legs"]]:
        if leg_key(l) not in seen and l.get("res") in ("won", "lost"):
            seen.add(leg_key(l))
            cal_legs.append(l)
    out["legs"] = len(cal_legs)
    out["leg_hit"] = round(sum(l["res"] == "won" for l in cal_legs) / len(cal_legs), 4) if cal_legs else None
    out["leg_expected"] = round(sum(l["p"] for l in cal_legs) / len(cal_legs), 4) if cal_legs else None
    out["cal"] = []
    for lo, hi in zip(CAL_BINS, CAL_BINS[1:]):
        b = [l for l in cal_legs if lo <= l["p"] < hi or (hi == 1.0 and l["p"] >= 1.0)]
        if b:
            out["cal"].append({"lo": lo, "hi": hi, "n": len(b), "pred": round(sum(l["p"] for l in b) / len(b), 4),
                               "obs": round(sum(l["res"] == "won" for l in b) / len(b), 4)})
    out["acca_missed"] = {}
    for a in accas:
        if a.get("res") in ("won", "lost"):
            miss = str(sum(1 for l in a["legs"] if l.get("res") == "lost"))
            out["acca_missed"][miss] = out["acca_missed"].get(miss, 0) + 1
    return out


def history(today, seasons):
    """The tip and ladder rules run over every match day of the seasons in the data, with pre-match prices.
    Fits the per-market corrections first (on the same matches), which the live tips then use too."""
    global CALIB
    matches = [m for s in HISTORY_SEASONS for div in LEAGUES for m in seasons.get(div, s)]
    CALIB = fit_calibration(matches)
    by_day = {}
    for m in matches:
        by_day.setdefault(m["date"], []).append(m)
    scores = {match_id(m): m["score"] for m in matches}
    cards = []
    lad = {"runs": []}
    for d in sorted(by_day):
        singles, accas = build_card(by_day[d])
        cards.append({"id": d, "singles": singles, "accas": accas})
        # ladder: each day's plan is settled before the next day, as it would be live
        ladder_walk(lad)
        run = lad["runs"][-1] if lad["runs"] else None
        plan = ladder_plan(by_day[d], date.fromisoformat(d).weekday() in CHAIN_DAYS)
        if plan:
            if not run or run["status"] == "broken":
                run = {"id": len(lad["runs"]) + 1, "start": d, "bets": []}
                lad["runs"].append(run)
            for i, s in enumerate(plan):
                for l in s["legs"]:
                    settle_leg(l, scores, today)
                run["bets"].append({**s, "day": d, "order": i + 1, "of": len(plan)})
    settle(cards, scores, today)
    ladder_walk(lad)
    s = summarise(cards)
    lsum = ladder_summary(lad)
    lsum.pop("log")
    s["ladder"] = lsum
    s.update({"calib": CALIB, "seasons": HISTORY_SEASONS, "days": len(cards), "matches": len(matches), "computed": today.isoformat(),
              "first": min(by_day), "last": max(by_day)})
    return s


# ---------------------------------------------------------------- goalscorers

def decrypt(enc, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(enc["salt"]), enc["iter"], dklen=32)
    plain = AESGCM(key).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["data"]), None)
    if enc.get("v") == 1:   # older files were gzipped
        import gzip
        plain = gzip.decompress(plain)
    return json.loads(plain.decode("utf-8"))


def scorer_chances(password, boot, upcoming, now):
    """Chance to score for every midfielder and forward: the next gameweek from the FPL model, and the
    current gameweek's matches still to come from each player's share of his team's expected goals.
    Returns {gameweek: [legs]}."""
    if not os.path.exists(ADV):
        return {}
    with open(ADV, encoding="utf-8") as f:
        enc = json.load(f)
    try:
        adv = decrypt(enc, password)
    except Exception as e:
        print(f"  tips: advanced data unreadable ({e}); no scorer tips", flush=True)
        return {}
    teams = {t["id"]: t["name"] for t in boot["teams"]}
    pens = {int(k): v for k, v in (adv["proj"].get("pens") or {}).items()}
    nxt = adv["proj"]["gws"][0]
    team_fix = {int(t): fx for t, fx in (adv.get("fixtures") or {}).items()}

    def leg(p, d, f, gw, xg, basis):
        ko = datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00"))
        return {"id": f"PL|{f['id']}|{p['id']}", "div": "E0", "date": ko.astimezone(UK).date().isoformat(), "ko": ko.isoformat(),
                "home": teams[f["team_h"]], "away": teams[f["team_a"]], "mkt": "scorer", "sel": str(p["id"]),
                "player": p["name"], "club": p.get("club"), "pid": p["id"], "gw": gw, "fixture": f["id"], "basis": basis,
                "xg_player": round(xg, 2), "emin": d.get("emin"), "p_start": d.get("p_start"), "pen": pens.get(p["id"]) == 1,
                "p": round(1 - math.exp(-xg), 4), "price": None, "est": True, "ev": None}

    def once(fixtures):
        games = {}
        for f in fixtures:
            games[f["team_h"]] = games.get(f["team_h"], 0) + 1
            games[f["team_a"]] = games.get(f["team_a"], 0) + 1
        return games

    players = [(p, adv["proj"]["detail"].get(str(p["id"])) or adv["proj"]["detail"].get(p["id"])) for p in adv["players"]]
    players = [(p, d) for p, d in players if d and p["pos"] in ("MID", "FWD") and d.get("xg")]
    out = {}

    fixtures = [f for f in boot["fixtures"].get(str(nxt), []) if f.get("kickoff_time")]
    games = once(fixtures)
    out[nxt] = [leg(p, d, next(f for f in fixtures if p["team"] in (f["team_h"], f["team_a"])), nxt, d["xg"], "model")
                for p, d in players if games.get(p["team"]) == 1]

    cur = boot["events"].get("current")
    if cur and cur != nxt:
        try:
            live = _get_json(f"{DRAFT}event/{cur}/live")
        except Exception as e:
            print(f"  tips: FPL GW{cur} fixtures unavailable ({e})", flush=True)
            live = {}
        left = [f for f in live.get("fixtures", []) if not f.get("started") and f.get("kickoff_time")
                and datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00")) > now]
        pl = [m for m in upcoming if m["div"] == "E0"]
        games_cur = once(live.get("fixtures", []))
        lam = {}
        for f in left:
            h, a = teams[f["team_h"]], teams[f["team_a"]]
            m = max(pl, key=lambda m: min(similar(h, m["home"]), similar(a, m["away"])), default=None)
            f1, fo = (fair(m["bfe"]["1x2"]), fair(m["bfe"]["ou"])) if m else (None, None)
            if m and f1 and fo and min(similar(h, m["home"]), similar(a, m["away"])) >= 0.6:
                lh, la = implied(f1, fo)
                lam[f["team_h"]], lam[f["team_a"]] = (lh, f), (la, f)
        cur_legs = []
        for p, d in players:
            gf = [x["gf"] for x in team_fix.get(p["team"], []) if x["gw"] == nxt]
            if p["team"] in lam and games_cur.get(p["team"]) == 1 and len(gf) == 1 and gf[0] > 0:
                l_team, f = lam[p["team"]]
                cur_legs.append(leg(p, d, f, cur, d["xg"] / gf[0] * l_team, "share"))
        if cur_legs:
            out[cur] = cur_legs
    return out


def scorer_results(legs_):
    """(goals, minutes) per open scorer leg whose match is finished, from FPL's live data."""
    out = {}
    for gw in {l["gw"] for l in legs_}:
        try:
            live = _get_json(f"{DRAFT}event/{gw}/live")
        except Exception as e:
            print(f"  tips: FPL live GW{gw} unavailable ({e})", flush=True)
            continue
        done = {f["id"] for f in live.get("fixtures", []) if f.get("finished") or f.get("finished_provisional")}
        for l in legs_:
            if l["gw"] == gw and l["fixture"] in done:
                st = live["elements"].get(str(l["pid"]), {}).get("stats", {})
                out[l["id"]] = (st.get("goals_scored", 0), st.get("minutes", 0))
    return out


# ---------------------------------------------------------------- storage

def load_state(password):
    state = {"cards": []}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            state = json.load(f)
    elif os.path.exists(OLD_ENC) and password:
        try:
            with open(OLD_ENC, encoding="utf-8") as f:
                state = decrypt(json.load(f), password)
        except Exception:
            print("  tips: old encrypted record unreadable, starting a new record", flush=True)
    if os.path.exists(PRIVATE) and password:
        try:
            with open(PRIVATE, encoding="utf-8") as f:
                state["scorer_cache"] = decrypt(json.load(f), password)
        except Exception:
            print("  tips: private scorer cache unreadable, starting it again", flush=True)
    return state


def save_state(state, password):
    """The public file, and the scorer cache encrypted apart. Written only when changed: an hourly run
    that settles nothing keeps the file, and its time stamp, as they were."""
    changed = False
    cache = state.pop("scorer_cache", {})
    old = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = f.read()
        prev = json.loads(old)
        now_ = json.loads(json.dumps(state))   # tuples as lists, like the file
        if {k: v for k, v in prev.items() if k != "updated"} == {k: v for k, v in now_.items() if k != "updated"}:
            state["updated"] = prev.get("updated", state["updated"])
    text = json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n"
    if text != old:
        with open(OUT, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        changed = True
    if os.path.exists(OLD_ENC):
        os.remove(OLD_ENC)
        changed = True
    if password:
        digest = hashlib.sha256(json.dumps(cache, sort_keys=True).encode("utf-8")).hexdigest()
        old = {}
        if os.path.exists(PRIVATE):
            with open(PRIVATE, encoding="utf-8") as f:
                old = json.load(f)
        if old.get("hash") != digest:
            with open(PRIVATE, "w", encoding="utf-8", newline="\n") as f:
                json.dump({**advanced.encrypt(cache, password), "hash": digest}, f)
                f.write("\n")
            changed = True
    return changed


# ---------------------------------------------------------------- run

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", action="store_true", help="recompute the historical test now")
    a = ap.parse_args()
    password = os.environ.get("ADV_PASSWORD")
    if not password:
        print("tips: ADV_PASSWORD not set, running without goalscorers", flush=True)
    now = datetime.now(timezone.utc)
    local = now.astimezone(CPH)
    today = local.date()
    # the latest publishing hour that has passed today (None before 11:00: settle only). GitHub starts
    # scheduled runs late or not at all, so every run catches up on whatever is due.
    slot = max((h for h in SLOTS if local.hour >= h), default=None)
    state = load_state(password)
    cards = state["cards"]
    lad = state.get("ladder") or {"runs": []}
    seasons, espn = Seasons(today), Espn()

    global CALIB
    hist = state.get("history")
    if a.history or not hist or "calib" not in hist or (today - date.fromisoformat(hist["computed"])).days >= 7:
        hist = history(today, seasons)
        print(f"  tips: historical test over {hist['days']} match days, {len(hist['calib'])} market corrections", flush=True)
    CALIB = hist["calib"]
    if not state.get("calibrated"):
        reprice(cards, lad, hist.get("cal"))
        state["calibrated"] = now.isoformat(timespec="minutes")
        print("  tips: record repriced with the market corrections", flush=True)

    # settle first: the ladder needs yesterday's result before it plans today
    scores = results([l for l in all_legs(cards, lad) if not l.get("res")], now, seasons, espn)
    settle(cards, scores, today)
    for r in lad["runs"]:
        for b in r["bets"]:
            for l in b["legs"]:
                settle_leg(l, scores, today)
    ladder_walk(lad)

    text, modified = _get(FIXTURES)
    upcoming = parse(text)

    # the exchange's first chances per match, so the watchlist can see the market move
    seen = {i: v for i, v in state.get("seen", {}).items() if v["ko"] and datetime.fromisoformat(v["ko"]) > now - timedelta(days=1)}
    for m in upcoming:
        f1 = fair(m["bfe"]["1x2"])
        if f1 and m["ko"] and match_id(m) not in seen:
            seen[match_id(m)] = {"p": [round(x, 4) for x in f1], "t": now.isoformat(timespec="minutes"), "ko": m["ko"]}

    boot = None
    try:
        boot = _get_json(f"{DRAFT}bootstrap-static")
    except Exception as e:
        print(f"  tips: FPL bootstrap unavailable ({e})", flush=True)

    # scorer chances, kept after the deadline moves the projection on
    cache = state.get("scorer_cache", {})
    if password and boot:
        try:
            for gw, chances in scorer_chances(password, boot, upcoming, now).items():
                if chances:
                    cache[str(gw)] = chances
        except Exception as e:
            print(f"  tips: scorer chances unavailable ({e})", flush=True)
    cache = {g: v for g, v in cache.items() if any(datetime.fromisoformat(l["ko"]) > now - timedelta(days=3) for l in v)}

    rows_for = lambda l: seasons.get(l["div"], season_of(date.fromisoformat(l["date"])))
    why = lambda l: explain(l, rows_for(l) if l["mkt"] != "scorer" else [], hist.get("cal"))

    # this run's card: 11:00 the day's first, 15:00 an update. Matches in the next 24 hours, leaving out
    # bets already tipped today and matches about to start.
    # an extra card asked for on the page or by hand ("publish"): the same rules, whatever the time
    extra = os.environ.get("TIPS_ACTION") == "publish"
    card_id = f"{today.isoformat()}-e{local:%H%M}" if extra else f"{today.isoformat()}-{slot}"
    if (extra or slot is not None) and not any(c["id"] == card_id for c in cards):
        skip = {leg_key(l) for c in cards if c["id"].startswith(today.isoformat()) for l in c["singles"] + [x for a in c["accas"] for x in a["legs"]]}
        window = lambda ko: now + timedelta(minutes=15) < datetime.fromisoformat(ko) <= now + WINDOW
        soon = [m for m in upcoming if m["ko"] and window(m["ko"])]
        scorers = [l for v in cache.values() for l in v if window(l["ko"])]
        singles, accas = build_card(soon, scorers, skip)
        # matches with a story: news, absences, table, form against the market, goals, rest, market moves.
        # A match already on today's watchlist is not repeated at 15:00.
        watched = {w["id"] for c in cards if c["day"] == today.isoformat() for w in c.get("watch", [])}
        news = fetch_news(sorted({m["div"] for m in soon}), now)
        absences = fpl_absences(boot)
        watch = [w for m in soon if match_id(m) not in watched
                 for w in [watch_match(m, rows_for(m), news, absences, seen)] if w]
        watch = sorted(watch, key=lambda w: -w["score"])[:WATCH_N]
        for w in watch:
            w["leg"] = why(w["leg"])
        if singles or accas or watch:
            singles = [why(l) for l in singles]
            accas = [{**x, "legs": [why(l) for l in x["legs"]]} for x in accas]
            cards.append({"id": card_id, "day": today.isoformat(), "slot": None if extra else slot, "extra": extra,
                          "published": now.isoformat(timespec="minutes"),
                          "odds_as_of": modified, "matches": len(soon), "singles": singles, "accas": accas, "watch": watch})
            print(f"  tips: card {card_id} with {len(singles)} singles, {len(accas)} accas and {len(watch)} matches to watch "
                  f"from {len(soon)} matches ({len(news)} news items)", flush=True)
        else:
            print(f"  tips: no card ({len(soon)} matches with prices in the next 24 hours)", flush=True)

    if slot is not None:
        ladder_step(lad, upcoming, now, today, lambda l: {**why(l), "odds_as_of": modified})

    # a change asked for on the page arrives as the workflow's inputs
    action = {k: os.environ.get(f"TIPS_{k.upper()}", "") for k in ("action", "step", "match", "mkt", "sel", "odds", "text", "res")}
    if action["action"] in ("replace", "manual", "result"):
        ladder_action(lad, action, upcoming, now, lambda l: {**why(l), "odds_as_of": modified})
    ladder_walk(lad)

    # the most likely scorers of the soonest gameweek with matches to come, with reasons
    gw_list = None
    future = {g: [l for l in v if datetime.fromisoformat(l["ko"]) > now] for g, v in cache.items()}
    future = {g: v for g, v in future.items() if v}
    if future:
        g = min(future, key=int)
        gw_list = {"gw": int(g), "players": [why(l) for l in sorted(future[g], key=lambda l: -l["p"])[:SCORER_LIST]]}

    scorer_test = None
    if os.path.exists(SCORER_CHECK):
        with open(SCORER_CHECK, encoding="utf-8") as f:
            scorer_test = json.load(f)
    state = {"cards": cards, "live": summarise(cards), "history": hist, "ladder": lad, "ladder_live": ladder_summary(lad),
             "scorers": gw_list, "scorer_test": scorer_test, "scorer_cache": cache, "seen": seen, "calibrated": state["calibrated"],
             "updated": now.isoformat(timespec="minutes"),
             "started": min((c["day"] for c in cards), default=today.isoformat()),
             # matches the page offers for an own ladder bet: the next two days
             "fixtures": [{"id": match_id(m), "div": m["div"], "home": m["home"], "away": m["away"], "ko": m["ko"]}
                          for m in sorted(upcoming, key=lambda m: m["ko"] or "")
                          if m["ko"] and now < datetime.fromisoformat(m["ko"]) < now + timedelta(hours=48)],
             "rules": {"ladder_start": LADDER_START, "ladder_odds": LADDER_ODDS, "ladder_max": LADDER_MAX, "slots": SLOTS}}
    print(f"  tips: {'written' if save_state(state, password) else 'unchanged'}", flush=True)


if __name__ == "__main__":
    main()
