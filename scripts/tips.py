"""Tips for the Betting tab: daily singles and accumulators, a ladder challenge and Premier League
goalscorers, frozen when published, settled from results.

For fun, not an edge: the backtests (betting_backtest.py, betting_books.py) found that neither our
goals model nor bet365's prices beat the market. So the tips use the best estimate we have:
    probability   Betfair Exchange's price with the margin removed (the sharpest price in the data)
    price         bet365's price, where the tip would be placed
    expected      probability * price - 1: what a tip returns on average (below 0 at bet365)
Both come from football-data.co.uk's fixtures.csv (upcoming matches, about 21 leagues, updated by
football-data a few times a week).

Every tip carries its reasons (market view, expected goals, form) and a calibrated confidence: how
often tips with that probability hit in the historical test.

Results: ESPN's public scoreboard the same day (most leagues), football-data's season files as the
fallback (updated about twice a week), FPL's live data for goalscorers. A team-name match between
ESPN and football-data is only accepted when both teams match well.

A card is published once a day for matches kicking off in the next 24 hours that no earlier card
has tipped. Published legs and prices never change; only their results are filled in later.
Everything shown is stored openly in docs/data/tips.json. The goalscorer chances kept between runs
come from the password-protected Advanced data, so they stay encrypted (scripts/cache/
tips_private.enc.json, ADV_PASSWORD); only the 20 shown on the page are public.

Ladder: start at 100 kr, bet the whole payout on the next single at bet365 odds 1.10-1.20, restart at
100 kr after a loss. One bet a day; on Saturdays and Sundays a chain of bets the same day, each
kicking off after the previous has finished and played only if it won. Only leagues with same-day
results, so the ladder can move on daily.

The same rules are also run over every match day of the seasons in the data (history()), with the
prices collected before each match, which gives a track record from the start.

Premier League goalscorers: the FPL model's expected goals per player (Advanced tab data, same
password), chance to score = 1 - exp(-xG), midfielders and forwards only (defenders were overrated
in the 2025/26 check, scripts/scorer_check.py). The projection moves to the next gameweek at the
deadline, so each run keeps the chances of the upcoming gameweek. No bet365 price for scorers in
the data: the tip shows fair odds. A player who does not play is void, as at bookmakers.

    python scripts/tips.py              # publish today's card and ladder plan if not done, settle, write
    python scripts/tips.py --history    # also recompute the historical test (otherwise weekly)
"""

import argparse
import base64
import csv
import hashlib
import io
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
# football-data short names that don't resemble the full name
ALIAS = {"man city": "manchester city", "man united": "manchester united", "nott'm forest": "nottingham forest",
         "wolves": "wolverhampton wanderers", "sheffield weds": "sheffield wednesday", "sheffield united": "sheffield united",
         "qpr": "queens park rangers", "mk dons": "milton keynes dons", "ath madrid": "atletico madrid",
         "ath bilbao": "athletic club", "sociedad": "real sociedad", "betis": "real betis", "espanol": "espanyol",
         "vallecano": "rayo vallecano", "celta": "celta vigo", "la coruna": "deportivo la coruna", "sp gijon": "sporting gijon",
         "ein frankfurt": "eintracht frankfurt", "m'gladbach": "monchengladbach", "fc koln": "koln", "paris sg": "paris saint germain",
         "inter": "internazionale", "milan": "ac milan", "st etienne": "saint etienne", "sp lisbon": "sporting cp",
         "for sittard": "fortuna sittard", "nijmegen": "nec nijmegen", "spurs": "tottenham hotspur", "dag and red": "dagenham redbridge",
         "hearts": "heart of midlothian", "rennes": "stade rennais", "buyuksehyr": "istanbul basaksehir"}
HISTORY_SEASONS = ["2425", "2526", "2627"]
OVERROUND = (0.98, 1.06)   # exchange prices outside this are thin or stale: skip the market
VOID_AFTER = 10            # days after kick-off without a result: the match counts as void
WINDOW = timedelta(hours=24)
MATCH_LEN = timedelta(hours=2)   # kick-off to final whistle, with half-time and stoppage time

# tip rules
BANKER_MIN = 0.65
VALUE_P = (0.30, 0.75)
EDGE_N = 3
SAFE_MIN, SAFE_LEGS = 0.65, 4
LONG_P, LONG_TARGET, LONG_MAX = (0.40, 0.65), 8.0, 5
BTTS_MIN = 0.55
SCORER_N, SCORER_LIST = 3, 20
CAL_BINS = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

# ladder rules
LADDER_START = 100.0
LADDER_ODDS = (1.10, 1.20)
LADDER_GAP = timedelta(hours=2, minutes=15)   # next bet kicks off this long after the previous at the earliest
LADDER_MAX = 5
CHAIN_DAYS = (5, 6)                            # Saturday and Sunday


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


# ---------------------------------------------------------------- probabilities

# Expected goals (independent Poisson) that reproduce the exchange's 1X2 and over/under 2.5: gives
# both teams to score, which has no prices in the data, and the expected score for the reasons.
_G = np.arange(0.1, 4.51, 0.05)
GRID = None


def _grid():
    k = np.arange(11)
    pk = np.exp(-_G[:, None]) * _G[:, None] ** k / np.array([math.factorial(i) for i in k], float)
    P = pk[:, None, :, None] * pk[None, :, None, :]
    x, y = np.indices((11, 11))
    return (P[..., x > y].sum(-1).ravel(), P[..., x < y].sum(-1).ravel(), P[..., x + y > 2].sum(-1).ravel(),
            ((1 - pk[:, 0])[:, None] * (1 - pk[:, 0])[None, :]).ravel())


def implied(p1x2, pou):
    """(P both teams score, expected home goals, expected away goals)."""
    global GRID
    if GRID is None:
        GRID = _grid()
    H, A, O, B = GRID
    i = int(((H - p1x2[0]) ** 2 + (A - p1x2[2]) ** 2 + (O - pou[0]) ** 2).argmin())
    return float(B[i]), float(_G[i // len(_G)]), float(_G[i % len(_G)])


def legs(m):
    """Every possible single bet of a match with its probability and bet365 price (None if missing)."""
    out = []
    base = {"id": match_id(m), "div": m["div"], "date": m["date"], "ko": m["ko"], "home": m["home"], "away": m["away"]}
    f1, fo = fair(m["bfe"]["1x2"]), fair(m["bfe"]["ou"])
    if f1 and fo:
        b, lh, la = implied(f1, fo)
        base["xg"] = [round(lh, 2), round(la, 2)]
    for mkt, f, sels in (("1x2", f1, "HDA"), ("ou", fo, "OU")):
        if not f:
            continue
        for i, sel in enumerate(sels):
            price = m["b365"][mkt][i]
            out.append({**base, "mkt": mkt, "sel": sel, "p": round(f[i], 4), "price": price,
                        "ev": round(f[i] * price - 1, 4) if price else None})
    if f1 and fo:
        for sel, p in (("Y", b), ("N", 1 - b)):
            out.append({**base, "mkt": "btts", "sel": sel, "p": round(p, 4), "price": None, "ev": None})
    return out


# ---------------------------------------------------------------- tip rules

def _distinct(cands, n, taken=(), key="id"):
    seen, out = set(taken), []
    for c in cands:
        if c[key] in seen:
            continue
        out.append(c)
        seen.add(c[key])
        if len(out) == n:
            break
    return out


def _acca(kind, ls):
    price = math.prod(l["price"] for l in ls)
    p = math.prod(l["p"] for l in ls)
    return {"kind": kind, "legs": ls, "price": round(price, 2), "p": round(p, 4), "ev": round(p * price - 1, 4)}


def build_card(matches, scorers=()):
    """Singles and accas for one batch of matches. Deterministic: same matches, same card."""
    all_legs = [l for m in matches for l in legs(m)]
    priced = [l for l in all_legs if l["price"] and l["mkt"] in ("1x2", "ou")]
    singles, accas = [], []

    bankers = _distinct(sorted((l for l in priced if l["p"] >= BANKER_MIN), key=lambda l: -l["p"]), 3)
    singles += [{**l, "kind": "banker"} for l in bankers]
    value = _distinct(sorted((l for l in priced if VALUE_P[0] <= l["p"] <= VALUE_P[1]), key=lambda l: -l["ev"]), 3,
                      {l["id"] for l in bankers})
    singles += [{**l, "kind": "value"} for l in value]
    # bet365 above the exchange's fair price: the "value" a model sees. betting_books.py found the market
    # usually moves against these, so they are tracked to show whether it holds up here.
    edge = _distinct(sorted((l for l in priced if l["ev"] > 0), key=lambda l: -l["ev"]), EDGE_N)
    singles += [{**l, "kind": "edge"} for l in edge]
    used = {l["id"] for l in singles}
    goals = _distinct(sorted((l for l in priced if l["mkt"] == "ou"), key=lambda l: -l["p"]), 1, used)
    goals += _distinct(sorted((l for l in all_legs if l["mkt"] == "btts" and l["sel"] == "Y" and l["p"] >= BTTS_MIN),
                              key=lambda l: -l["p"]), 1, used | {l["id"] for l in goals})
    singles += [{**l, "kind": "goals"} for l in goals]
    # one scorer per match, so a single game's news can't sink all three
    singles += [{**l, "kind": "scorer"} for l in _distinct(sorted(scorers, key=lambda l: -l["p"]), SCORER_N, key="fixture")]

    safe = _distinct(sorted((l for l in priced if l["p"] >= SAFE_MIN), key=lambda l: (-l["ev"], -l["p"])), SAFE_LEGS)
    if len(safe) >= 3:
        accas.append(_acca("safe", safe))
    long_legs = []
    for l in sorted((l for l in priced if LONG_P[0] <= l["p"] <= LONG_P[1]), key=lambda l: -l["ev"]):
        if any(x["id"] == l["id"] for x in long_legs):
            continue
        long_legs.append(l)
        if math.prod(x["price"] for x in long_legs) >= LONG_TARGET or len(long_legs) == LONG_MAX:
            break
    if len(long_legs) >= 3 and math.prod(x["price"] for x in long_legs) >= 5:
        accas.append(_acca("long", long_legs))
    return singles, accas


def ladder_plan(matches, chain):
    """Ladder bets for one day: bet365 1.10-1.20 in leagues with same-day results. A single bet is the
    most likely one; a chain is the longest sequence that fits (each kicking off after the previous has
    finished), and of those the most likely to survive."""
    cands = sorted((l for m in matches if m["div"] in FAST and m["ko"] for l in legs(m)
                    if l["price"] and LADDER_ODDS[0] <= l["price"] <= LADDER_ODDS[1] and l["mkt"] in ("1x2", "ou")),
                   key=lambda l: l["ko"])
    if not cands:
        return []
    if not chain:
        return [max(cands, key=lambda l: (l["p"], l["ev"]))]
    best = []   # best[i] = (length, sum log p, chain) ending with cands[i]
    for i, c in enumerate(cands):
        opt = (1, math.log(c["p"]), [c])
        for j in range(i):
            n, lp, ch = best[j]
            if n < LADDER_MAX and datetime.fromisoformat(cands[j]["ko"]) + LADDER_GAP <= datetime.fromisoformat(c["ko"]) \
                    and (n + 1, lp + math.log(c["p"])) > opt[:2]:
                opt = (n + 1, lp + math.log(c["p"]), ch + [c])
        best.append(opt)
    return max(best, key=lambda b: b[:2])[2]


# ---------------------------------------------------------------- reasons and confidence

def form_of(rows, team, before):
    """A team's league matches this season before a date: results, goals, points per game."""
    ms = [m for m in rows if team in (m["home"], m["away"]) and m["date"] < before]
    out = []
    for m in ms:
        home = m["home"] == team
        gf, ga = m["score"] if home else m["score"][::-1]
        out.append({"home": home, "gf": gf, "ga": ga, "r": "V" if gf > ga else "U" if gf == ga else "T"})
    return out


def _ppg(ms):
    return sum(3 if x["r"] == "V" else 1 if x["r"] == "U" else 0 for x in ms) / len(ms) if ms else None


def _fmt(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def explain(l, rows, cal):
    """Reasons behind a tip (frozen with it) and how often tips like it hit in the historical test."""
    why = []
    if l["mkt"] == "scorer":
        why.append(f"FPL-modellen: {_fmt(l['xg_player'], 2)} forventede mål i kampen, {l['emin']} forventede minutter"
                   + (f", {round(l['p_start'] * 100)}% chance for at starte" if l.get("p_start") is not None else "") + ".")
        if l.get("pen"):
            why.append("Førstevalg til straffespark.")
        why.append(f"Fair odds {_fmt(1 / l['p'], 2)}: bet365 skal give mere end det, før spillet er pengene værd.")
    else:
        fair_odds = _fmt(1 / l["p"], 2)
        line = f"Betfair Exchange: {round(l['p'] * 100)}% (fair odds {fair_odds})."
        if l.get("price"):
            line += f" bet365 giver {_fmt(l['price'], 2)}, {'over' if l['ev'] > 0 else 'under'} fair med {_fmt(abs(l['ev']) * 100)}%."
        why.append(line)
        if l.get("xg"):
            lh, la = l["xg"]
            why.append(f"Markedet venter {_fmt(lh)}–{_fmt(la)} i mål ({_fmt(lh + la)} i alt).")
        fh, fa = form_of(rows, l["home"], l["date"]), form_of(rows, l["away"], l["date"])
        for team, f, side in ((l["home"], fh, True), (l["away"], fa, False)):
            if not f:
                continue
            venue = [x for x in f if x["home"] == side]
            bits = [f"form {' '.join(x['r'] for x in f[-5:])}", f"{_fmt(_ppg(f), 2)} point per kamp"]
            if venue:
                bits.append(f"{'hjemme' if side else 'ude'} {_fmt(_ppg(venue), 2)}")
            if l["mkt"] in ("ou", "btts"):
                bits.append(f"{_fmt(sum(x['gf'] + x['ga'] for x in f) / len(f))} mål per kamp")
                if l["mkt"] == "ou":
                    bits.append(f"over 2,5 i {round(100 * sum(x['gf'] + x['ga'] > 2 for x in f) / len(f))}%")
                else:
                    bits.append(f"begge scorede i {round(100 * sum(x['gf'] > 0 and x['ga'] > 0 for x in f) / len(f))}%")
            why.append(f"{team}: " + ", ".join(bits) + ".")
    conf = None
    for b in cal or []:
        if b["lo"] <= l["p"] < b["hi"] or (b["hi"] == 1.0 and l["p"] >= 1.0):
            conf = {"lo": b["lo"], "hi": b["hi"], "obs": b["obs"], "n": b["n"]}
    return {**l, "why": why, "conf": conf}


# ---------------------------------------------------------------- settling

def leg_result(leg, score):
    hg, ag = score
    return {"H": hg > ag, "D": hg == ag, "A": hg < ag, "O": hg + ag > 2, "U": hg + ag <= 2,
            "Y": hg > 0 and ag > 0, "N": hg == 0 or ag == 0}[leg["sel"]]


def settle_leg(leg, scores, today):
    if leg.get("res"):
        return
    r = scores.get(leg["id"])
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
    rs = [l.get("res") for l in a["legs"]]
    a["legs_hit"] = rs.count("won")
    if "lost" in rs:
        a["res"] = "lost"
    elif all(rs):
        won = [l for l in a["legs"] if l["res"] == "won"]
        a["res"] = "won" if won else "void"
        a["paid"] = round(math.prod(l["price"] for l in won), 2) if won else None   # void legs drop out
    else:
        a.pop("res", None)


def all_legs(cards, ladder=None):
    out = [l for c in cards for l in c["singles"] + [x for a in c["accas"] for x in a["legs"]]]
    if ladder:
        out += [b for r in ladder["runs"] for b in r["bets"]]
    return out


def results(open_legs, now, seasons, espn):
    """Scores for open legs: FPL live for scorers, ESPN the same day, football-data as the fallback."""
    out = scorer_results([l for l in open_legs if l["mkt"] == "scorer"])
    rest = [l for l in open_legs if l["mkt"] != "scorer" and l.get("ko") and datetime.fromisoformat(l["ko"]) + MATCH_LEN < now]
    by_id = {}
    for l in rest:
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
        for l in c["singles"]:
            settle_leg(l, scores, today)
        for a in c["accas"]:
            for l in a["legs"]:
                settle_leg(l, scores, today)
            settle_acca(a)


def profit_single(l):
    if not l["price"] or l.get("res") not in ("won", "lost"):
        return None
    return l["price"] - 1 if l["res"] == "won" else -1.0


def profit_acca(a):
    if a.get("res") == "won":
        return a["paid"] - 1
    return -1.0 if a.get("res") == "lost" else None


# ---------------------------------------------------------------- ladder

def ladder_walk(lad):
    """Stakes and status from the bets' results: each won bet's payout is the next stake; a loss ends the
    run, and bets planned after it that day are not played."""
    for run in lad["runs"]:
        stake, broken, waiting = LADDER_START, False, False
        run["steps"], run["peak"] = 0, LADDER_START
        for b in run["bets"]:
            if broken:
                if b.get("res") in (None, "skipped"):
                    b["res"] = "skipped"
                b["stake"] = b["payout"] = None
                continue
            if waiting:   # after an open bet: the stake it gets if everything before it wins
                b["stake"], b["payout"], b["if_won"] = round(stake, 2), round(stake * b["price"], 2), True
                stake *= b["price"]
                continue
            if b.get("res") == "skipped":
                b.pop("res")
            b.pop("if_won", None)
            b["stake"] = round(stake, 2)
            b["payout"] = round(stake * b["price"], 2)
            if b.get("res") == "won":
                stake = b["payout"]
                run["steps"] += 1
                run["peak"] = max(run["peak"], stake)
            elif b.get("res") == "lost":
                broken = True
                run["broke"] = {"day": b["day"], "id": b["id"], "mkt": b["mkt"], "sel": b["sel"], "home": b["home"],
                                "away": b["away"], "price": b["price"], "score": b.get("score")}
            elif b.get("res") != "void":
                waiting, current = True, stake
                stake *= b["price"]
        run["status"] = "broken" if broken else "alive"
        run["stake"] = None if broken else round(current if waiting else stake, 2)
        run["end"] = run["bets"][-1]["day"] if run["bets"] else run["start"]


def ladder_step(lad, matches, now, today):
    """Plan today's ladder bets if not done and the previous bet is settled."""
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
        print("  tips: no ladder bet today", flush=True)
        return
    if not run or run["status"] == "broken":
        run = {"id": len(lad["runs"]) + 1, "start": today.isoformat(), "bets": []}
        lad["runs"].append(run)
    for i, l in enumerate(plan):
        run["bets"].append({**l, "day": today.isoformat(), "order": i + 1, "of": len(plan)})
    print(f"  tips: ladder run {run['id']}, {len(plan)} bet(s) today", flush=True)


def ladder_summary(lad):
    runs = lad["runs"]
    done = [r for r in runs if r["status"] == "broken"]
    bets = [b for r in runs for b in r["bets"] if b.get("res") in ("won", "lost")]
    best = max(runs, key=lambda r: (r["steps"], r["peak"]), default=None)
    return {"runs": len(runs), "broken": len(done), "bets": len(bets),
            "hit": round(sum(b["res"] == "won" for b in bets) / len(bets), 4) if bets else None,
            "expected": round(sum(b["p"] for b in bets) / len(bets), 4) if bets else None,
            "avg_steps": round(sum(r["steps"] for r in done) / len(done), 2) if done else None,
            "best": {"steps": best["steps"], "peak": best["peak"], "start": best["start"], "end": best["end"]} if best else None,
            "steps_dist": {str(k): sum(1 for r in done if r["steps"] == k) for k in sorted({r["steps"] for r in done})},
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
        evs = [x["ev"] for x in done if x.get("ev") is not None]
        return {"n": len(done), "won": won, "lost": len(done) - won, "hit": round(won / len(done), 4),
                "expected": round(sum(x["p"] for x in done) / len(done), 4),
                "staked": len(pr), "profit": round(sum(pr), 2), "roi": round(sum(pr) / len(pr), 4) if pr else None,
                "exp_roi": round(sum(evs) / len(evs), 4) if evs else None,
                "pending": sum(1 for x in items if not x.get("res"))}

    singles = [l for c in cards for l in c["singles"]]
    accas = [a for c in cards for a in c["accas"]]
    out = {"singles": block(singles, profit_single), "accas": block(accas, profit_acca), "kinds": {}}
    for k in ("banker", "value", "edge", "goals", "scorer"):
        out["kinds"][k] = block([l for l in singles if l["kind"] == k], profit_single)
    for k in ("safe", "long"):
        out["kinds"][k] = block([a for a in accas if a["kind"] == k], profit_acca)
    # every distinct settled leg, singles and acca legs alike: are the probabilities honest?
    seen, cal_legs = set(), []
    for l in singles + [l for a in accas for l in a["legs"]]:
        key = (l["id"], l["mkt"], l["sel"])
        if key not in seen and l.get("res") in ("won", "lost"):
            seen.add(key)
            cal_legs.append(l)
    out["legs"] = len(cal_legs)
    out["leg_hit"] = round(sum(l["res"] == "won" for l in cal_legs) / len(cal_legs), 4) if cal_legs else None
    out["leg_expected"] = round(sum(l["p"] for l in cal_legs) / len(cal_legs), 4) if cal_legs else None
    out["brier"] = round(sum((l["p"] - (l["res"] == "won")) ** 2 for l in cal_legs) / len(cal_legs), 4) if cal_legs else None
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
    """The tip and ladder rules run over every match day of the seasons in the data, with pre-match prices."""
    matches = [m for s in HISTORY_SEASONS for div in LEAGUES for m in seasons.get(div, s)]
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
            for i, l in enumerate(plan):
                b = {**l, "day": d, "order": i + 1, "of": len(plan)}
                settle_leg(b, scores, today)
                run["bets"].append(b)
    settle(cards, scores, today)
    ladder_walk(lad)
    s = summarise(cards)
    s["ladder"] = ladder_summary(lad)
    s.update({"seasons": HISTORY_SEASONS, "days": len(cards), "matches": len(matches), "computed": today.isoformat(),
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


def scorer_chances(password, boot):
    """Chance to score for every midfielder and forward in the upcoming gameweek's matches."""
    if not os.path.exists(ADV):
        return None, []
    with open(ADV, encoding="utf-8") as f:
        enc = json.load(f)
    try:
        adv = decrypt(enc, password)
    except Exception as e:
        print(f"  tips: advanced data unreadable ({e}); no scorer tips", flush=True)
        return None, []
    gw = adv["proj"]["gws"][0]
    teams = {t["id"]: t["name"] for t in boot["teams"]}
    fixtures = [f for f in boot["fixtures"].get(str(gw), []) if f.get("kickoff_time")]
    games = {}
    for f in fixtures:
        games[f["team_h"]] = games.get(f["team_h"], 0) + 1
        games[f["team_a"]] = games.get(f["team_a"], 0) + 1
    pens = {int(k): v for k, v in (adv["proj"].get("pens") or {}).items()}
    out = []
    for p in adv["players"]:
        d = adv["proj"]["detail"].get(str(p["id"])) or adv["proj"]["detail"].get(p["id"])
        if not d or p["pos"] not in ("MID", "FWD") or games.get(p["team"]) != 1 or not d.get("xg"):
            continue
        f = next(f for f in fixtures if p["team"] in (f["team_h"], f["team_a"]))
        ko = datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00"))
        out.append({"id": f"PL|{f['id']}|{p['id']}", "div": "E0", "date": ko.astimezone(UK).date().isoformat(), "ko": ko.isoformat(),
                    "home": teams[f["team_h"]], "away": teams[f["team_a"]], "mkt": "scorer", "sel": "S",
                    "player": p["name"], "club": p.get("club"), "pid": p["id"], "gw": gw, "fixture": f["id"],
                    "xg_player": d["xg"], "emin": d.get("emin"), "p_start": d.get("p_start"), "pen": pens.get(p["id"]) == 1,
                    "p": round(1 - math.exp(-d["xg"]), 4), "price": None, "ev": None})
    return gw, out


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
    """The public file, and the scorer cache encrypted apart. Written only when changed."""
    changed = False
    cache = state.pop("scorer_cache", {})
    text = json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n"
    old = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = f.read()
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
    today = now.astimezone(CPH).date()
    state = load_state(password)
    cards = state["cards"]
    lad = state.get("ladder") or {"runs": []}
    seasons, espn = Seasons(today), Espn()

    hist = state.get("history")
    if a.history or not hist or "ladder" not in hist or (today - date.fromisoformat(hist["computed"])).days >= 7:
        hist = history(today, seasons)
        print(f"  tips: historical test over {hist['days']} match days", flush=True)

    # settle first: the ladder needs yesterday's result before it plans today
    scores = results([l for l in all_legs(cards, lad) if not l.get("res")], now, seasons, espn)
    settle(cards, scores, today)
    for r in lad["runs"]:
        for b in r["bets"]:
            settle_leg(b, scores, today)
    ladder_walk(lad)

    # scorer chances of the upcoming gameweek, kept after the deadline moves the projection on
    cache = state.get("scorer_cache", {})
    try:
        boot = _get_json(f"{DRAFT}bootstrap-static")
        gw, chances = scorer_chances(password, boot) if password else (None, [])
        if gw and chances:
            cache[str(gw)] = chances
    except Exception as e:
        print(f"  tips: scorer chances unavailable ({e})", flush=True)
    cache = {g: v for g, v in cache.items() if any(datetime.fromisoformat(l["ko"]) > now - timedelta(days=3) for l in v)}

    text, modified = _get(FIXTURES)
    upcoming = parse(text)
    rows_for = lambda l: seasons.get(l["div"], season_of(date.fromisoformat(l["date"])))
    why = lambda l: explain(l, rows_for(l) if l["mkt"] != "scorer" else [], hist.get("cal"))

    # today's card: once a day, matches in the next 24 hours that no card has tipped yet
    tipped = {l["id"] for l in all_legs(cards)}
    soon_window = lambda ko: now + timedelta(minutes=15) < datetime.fromisoformat(ko) <= now + WINDOW
    if not any(c["id"] == today.isoformat() for c in cards):
        soon = [m for m in upcoming if m["ko"] and soon_window(m["ko"]) and match_id(m) not in tipped]
        scorers = [l for v in cache.values() for l in v if soon_window(l["ko"]) and l["id"] not in tipped]
        singles, accas = build_card(soon, scorers)
        if singles or accas:
            singles = [why(l) for l in singles]
            accas = [{**x, "legs": [why(l) for l in x["legs"]]} for x in accas]
            cards.append({"id": today.isoformat(), "published": now.isoformat(timespec="minutes"),
                          "odds_as_of": modified, "matches": len(soon), "singles": singles, "accas": accas})
            print(f"  tips: card {today} with {len(singles)} singles and {len(accas)} accas from {len(soon)} matches", flush=True)
        else:
            print(f"  tips: no card today ({len(soon)} matches with prices in the next 24 hours)", flush=True)

    n_before = sum(len(r["bets"]) for r in lad["runs"])
    ladder_step(lad, upcoming, now, today)
    for r in lad["runs"]:
        for i, b in enumerate(r["bets"]):
            if "why" not in b:
                r["bets"][i] = {**why(b), "odds_as_of": modified}
    if sum(len(r["bets"]) for r in lad["runs"]) != n_before:
        ladder_walk(lad)

    # the next gameweek's most likely scorers, with reasons
    gw_list = None
    if cache:
        g = min(cache, key=lambda g: int(g))
        future = [l for l in cache[g] if datetime.fromisoformat(l["ko"]) > now]
        if future:
            gw_list = {"gw": int(g), "players": [why(l) for l in sorted(future, key=lambda l: -l["p"])[:SCORER_LIST]]}

    scorer_test = None
    if os.path.exists(SCORER_CHECK):
        with open(SCORER_CHECK, encoding="utf-8") as f:
            scorer_test = json.load(f)
    state = {"cards": cards, "live": summarise(cards), "history": hist, "ladder": lad, "ladder_live": ladder_summary(lad),
             "scorers": gw_list, "scorer_test": scorer_test, "scorer_cache": cache, "updated": now.isoformat(timespec="minutes"),
             "rules": {"banker_min": BANKER_MIN, "value_p": VALUE_P, "safe_min": SAFE_MIN, "safe_legs": SAFE_LEGS,
                       "long_p": LONG_P, "long_target": LONG_TARGET, "btts_min": BTTS_MIN,
                       "ladder_start": LADDER_START, "ladder_odds": LADDER_ODDS, "ladder_max": LADDER_MAX}}
    print(f"  tips: {'written' if save_state(state, password) else 'unchanged'}", flush=True)


if __name__ == "__main__":
    main()
