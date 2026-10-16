"""Bookmaker odds turned into expected goals per team and match.

Sources
  The Odds API (ODDS_API_KEY): upcoming Premier League matches, 1X2 and over/under 2.5 from
      UK bookmakers. Free tier is 500 credits a month and one call costs 2, so it is called at
      most once every 20 hours.
  football-data.co.uk: fixtures.csv for upcoming matches (fallback) and E0.csv with pre-match
      odds for every match already played, which lets the backtest measure what odds add.

Odds are converted to probabilities (bookmaker margin removed), and the two expected-goals
figures (home, away) are found so that independent Poisson scorelines reproduce P(home win),
P(away win) and, when available, P(over 2.5 goals).

Only these derived numbers are stored (scripts/cache/odds.json), never the raw odds: The Odds API
terms do not allow redistributing their data as a standalone product, and the repo is public.
"""

import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, timedelta, timezone

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "odds.json")
REFRESH = timedelta(hours=20)
ODDS_API = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds?regions=uk&markets=h2h,totals&oddsFormat=decimal&apiKey={key}"
FD_PLAYED = "https://www.football-data.co.uk/mmz4281/2627/E0.csv"
FD_FIXTURES = "https://www.football-data.co.uk/fixtures.csv"

# names used by The Odds API and football-data.co.uk -> FPL team names
ALIAS = {
    "brighton and hove albion": "brighton", "brighton & hove albion": "brighton",
    "manchester city": "man city", "manchester united": "man utd", "man united": "man utd",
    "nottingham forest": "nott'm forest", "tottenham hotspur": "spurs", "tottenham": "spurs",
    "newcastle united": "newcastle", "leeds united": "leeds", "coventry": "coventry city",
    "hull": "hull city", "ipswich": "ipswich town", "wolverhampton wanderers": "wolves",
    "west ham united": "west ham", "afc bournemouth": "bournemouth",
}


def _get(url, as_json=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (super-draft-league-site)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if as_json else raw.decode("utf-8-sig", errors="replace")


def team_lookup(boot):
    names = {t["name"].lower(): t["id"] for t in boot["teams"]}

    def find(name):
        n = str(name).strip().lower()
        return names.get(ALIAS.get(n, n))
    return find


def pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def outcome_probs(lh, la, kmax=10):
    ph = [pois(k, lh) for k in range(kmax + 1)]
    pa = [pois(k, la) for k in range(kmax + 1)]
    home = sum(ph[i] * pa[j] for i in range(kmax + 1) for j in range(i))
    away = sum(ph[i] * pa[j] for j in range(kmax + 1) for i in range(j))
    under = sum(ph[i] * pa[j] for i in range(3) for j in range(3 - i))
    return home, away, 1 - under


def implied_goals(p_home, p_away, p_over=None):
    """Expected goals (home, away) matching the bookmakers' probabilities; coarse grid, then refine."""
    def err(lh, la):
        h, a, o = outcome_probs(lh, la)
        e = (h - p_home) ** 2 + (a - p_away) ** 2
        return e + ((o - p_over) ** 2 if p_over is not None else 0.0)
    best = min(((err(lh / 10, la / 10), lh / 10, la / 10) for lh in range(2, 41) for la in range(2, 41)))
    _, lh, la = best
    step = 0.05
    for _ in range(30):
        cands = [(err(lh + dx, la + dy), lh + dx, la + dy) for dx in (-step, 0, step) for dy in (-step, 0, step) if lh + dx > 0.05 and la + dy > 0.05]
        e, nlh, nla = min(cands)
        if (nlh, nla) == (lh, la):
            step /= 2
            if step < 0.002:
                break
        lh, la = nlh, nla
    return round(lh, 3), round(la, 3)


def no_margin(*prices):
    inv = [1 / p for p in prices]
    s = sum(inv)
    return [x / s for x in inv]


def _fd_rows(text):
    return [r for r in csv.DictReader(io.StringIO(text)) if r.get("HomeTeam")]


def _fd_goals(r):
    try:
        h, d, a = no_margin(float(r["AvgH"]), float(r["AvgD"]), float(r["AvgA"]))
    except (KeyError, ValueError, ZeroDivisionError):
        return None
    try:
        over, _ = no_margin(float(r["Avg>2.5"]), float(r["Avg<2.5"]))
    except (KeyError, ValueError, ZeroDivisionError):
        over = None
    return implied_goals(h, a, over)


def _odds_api(key, find):
    out = {}
    for ev in _get(ODDS_API.format(key=key), as_json=True):
        h_id, a_id = find(ev["home_team"]), find(ev["away_team"])
        if not h_id or not a_id:
            print(f"  odds: unknown team {ev['home_team']} / {ev['away_team']}", flush=True)
            continue
        hs, as_, os_ = [], [], []
        for b in ev.get("bookmakers", []):
            for m in b.get("markets", []):
                pr = {o["name"]: o for o in m["outcomes"]}
                if m["key"] == "h2h" and {ev["home_team"], ev["away_team"], "Draw"} <= set(pr):
                    h, d, a = no_margin(pr[ev["home_team"]]["price"], pr["Draw"]["price"], pr[ev["away_team"]]["price"])
                    hs.append(h); as_.append(a)
                if m["key"] == "totals" and "Over" in pr and "Under" in pr and pr["Over"].get("point") == 2.5:
                    os_.append(no_margin(pr["Over"]["price"], pr["Under"]["price"])[0])
        if not hs:
            continue
        p_over = sum(os_) / len(os_) if os_ else None
        lh, la = implied_goals(sum(hs) / len(hs), sum(as_) / len(as_), p_over)
        out[f"{h_id}-{a_id}"] = {"gh": lh, "ga": la, "src": "the-odds-api", "books": len(hs), "t": ev["commence_time"]}
    return out


def refresh(boot):
    """Upcoming and played matches' implied expected goals, from cache if it is fresh."""
    old = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            old = json.load(f)
    now = datetime.now(timezone.utc)
    fetched = datetime.fromisoformat(old["fetched"]) if old.get("fetched") else None
    if fetched and now - fetched < REFRESH:
        return old

    find = team_lookup(boot)
    upcoming, played = dict(old.get("upcoming", {})), dict(old.get("played", {}))
    try:
        for r in _fd_rows(_get(FD_FIXTURES)):
            if r.get("Div") != "E0":
                continue
            h, a = find(r["HomeTeam"]), find(r["AwayTeam"])
            g = _fd_goals(r)
            if h and a and g:
                upcoming[f"{h}-{a}"] = {"gh": g[0], "ga": g[1], "src": "football-data"}
        for r in _fd_rows(_get(FD_PLAYED)):
            h, a = find(r["HomeTeam"]), find(r["AwayTeam"])
            g = _fd_goals(r)
            if h and a and g:
                played[f"{h}-{a}"] = {"gh": g[0], "ga": g[1]}
    except Exception as e:
        print(f"  odds: football-data unavailable ({e})", flush=True)

    key = os.environ.get("ODDS_API_KEY")
    if key:
        try:
            upcoming.update(_odds_api(key, find))   # preferred: more bookmakers, updated daily
        except Exception as e:
            print(f"  odds: The Odds API unavailable ({e})", flush=True)

    data = {"fetched": now.isoformat(timespec="minutes"), "upcoming": upcoming, "played": played}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"  odds: {len(upcoming)} upcoming and {len(played)} played matches with odds", flush=True)
    return data
