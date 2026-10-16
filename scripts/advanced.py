"""Advanced player data for the password-protected tab.

Per player and gameweek: official FPL numbers (event/{gw}/live) joined with
FPL-Core-Insights match stats (shots, box touches, chances created ...).

The result is encrypted with AES-256-GCM. The key is derived from
the password in the ADV_PASSWORD environment variable (PBKDF2-SHA256), so the
public repo only ever contains ciphertext. Without the variable nothing is written.
"""

import base64
import csv
import hashlib
import io
import json
import os
import urllib.request

import history
import model

CORE = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data/2026-2027"
ITERATIONS = 250_000

# official FPL stats per gameweek: (short key, live-stat name)
FPL_STATS = [
    ("mi", "minutes"), ("st", "starts"), ("pt", "total_points"), ("g", "goals_scored"), ("a", "assists"),
    ("cs", "clean_sheets"), ("gc", "goals_conceded"), ("sv", "saves"), ("bo", "bonus"),
    ("xg", "expected_goals"), ("xa", "expected_assists"), ("xgi", "expected_goal_involvements"),
    ("xgc", "expected_goals_conceded"), ("dc", "defensive_contribution"),
]
# FPL-Core-Insights match stats, summed per gameweek (Premier League matches only).
# big_chances_missed and successful_dribbles are left out: empty in the source this season.
CORE_STATS = [
    ("sh", "total_shots"), ("sot", "shots_on_target"), ("box", "touches_opposition_box"),
    ("cc", "chances_created"), ("crs", "accurate_crosses"), ("aer", "aerial_duels_won"), ("tkw", "tackles_won"),
    ("int", "interceptions"), ("clr", "clearances"), ("gp", "goals_prevented"),
]
# xpt: expected points for the round (see model.past_xp), computed here rather than read
COLS = [k for k, _ in FPL_STATS] + [k for k, _ in CORE_STATS] + ["xpt"]
FIXTURES_URL = "https://fantasy.premierleague.com/api/fixtures/"


def classic_fixtures():
    """The whole season's fixtures. The Draft API only lists the next three rounds; classic FPL
    lists all 380 with the same team ids. Falls back to the Draft list if classic is unreachable."""
    req = urllib.request.Request(FIXTURES_URL, headers={"User-Agent": "Mozilla/5.0 (super-draft-league-site)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f"  note: classic fixtures unavailable ({e}); using the Draft list", flush=True)
        return None


def _csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "super-draft-league-site/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
    except Exception as e:  # the repo can lag or miss a file; the FPL numbers still stand
        print(f"  note: could not read {url}: {e}", flush=True)
        return []


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def core_by_gameweek(gw, code_to_id):
    """Core-Insights stats for one gameweek keyed by Draft player id. Joined on player code,
    because Core-Insights' own player ids differ from Draft ids for some players."""
    rows = _csv(f"{CORE}/By%20Gameweek/GW{gw}/playermatchstats.csv")
    out = {}
    for r in rows:
        # match ids look like 26-27-prem-..., 26-27-champions-..., 26-27-europa-...
        if r.get("match_id", "").split("-")[2:3] != ["prem"]:
            continue
        pid = code_to_id.get(r.get("player_id"))
        if pid is None:
            continue
        acc = out.setdefault(pid, [0.0] * len(CORE_STATS))
        for i, (_, col) in enumerate(CORE_STATS):
            acc[i] += _num(r.get(col))
    return out


def penalty_order(boot):
    """Penalty takers from classic FPL. The Draft API has the field, but it is empty for every player."""
    req = urllib.request.Request("https://fantasy.premierleague.com/api/bootstrap-static/",
                                 headers={"User-Agent": "Mozilla/5.0 (super-draft-league-site)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            classic = json.load(r)
    except Exception as e:
        print(f"  note: classic bootstrap unavailable ({e}); no penalty takers this run", flush=True)
        return 0
    order = {x["code"]: x.get("penalties_order") for x in classic["elements"]}
    n = 0
    for e in boot["elements"]:
        e["penalties_order"] = order.get(e["code"])
        n += e["penalties_order"] == 1
    return n


def build(boot, gws, fetch, owners, entry_to_le, next_gw=None):
    """Plain (unencrypted) advanced data: player info plus one row of stats per player per gameweek."""
    clubs = {t["id"]: t["short_name"] for t in boot["teams"]}
    pos = {t["id"]: t["singular_name_short"] for t in boot["element_types"]}
    by_code = {e["code"]: e["id"] for e in boot["elements"]}

    # Core-Insights player id -> Draft id, through the shared player code
    code_to_id = {}
    for p in _csv(f"{CORE}/players.csv"):
        did = by_code.get(int(_num(p.get("player_code"))))
        if did is not None:
            code_to_id[p.get("player_id")] = did

    players = []
    for e in boot["elements"]:
        owner = owners.get(e["id"])
        players.append({
            "id": e["id"], "name": e["web_name"], "full": f'{e.get("first_name", "")} {e.get("second_name", "")}'.strip(),
            "club": clubs.get(e["team"], ""), "pos": pos.get(e["element_type"], ""),
            "owner": entry_to_le.get(owner) if owner else None,
            "status": e.get("status"), "news": e.get("news") or "",
            "chance": e.get("chance_of_playing_next_round"),
        })

    live_raw = {gw: {int(k): v["stats"] for k, v in fetch(f"event/{gw}/live")["elements"].items()} for gw in gws}
    fixtures = classic_fixtures()
    if fixtures is None:
        fixtures = [f for fx in (boot.get("fixtures") or {}).values() for f in fx]
        for gw in gws:   # past rounds from the live endpoint, which lists its own fixtures
            fixtures += fetch(f"event/{gw}/live").get("fixtures", [])
    print(f"  advanced: {penalty_order(boot)} first-choice penalty takers", flush=True)
    last = history.last_season()
    now = history.this_season(max(gws) if gws else 1)
    m = model.run(boot, live_raw, list(gws), fixtures, next_gw, last=last, now=now)

    by_gw = {}
    for gw in gws:
        live = {str(k): {"stats": v} for k, v in live_raw[gw].items()}
        core = core_by_gameweek(gw, code_to_id)
        rows = {}
        for sid, v in live.items():
            st = v["stats"]
            pid = int(sid)
            if not st.get("minutes"):
                continue
            vals = [_num(st.get(name)) for _, name in FPL_STATS] + core.get(pid, [0.0] * len(CORE_STATS)) + [m["xpt"][gw].get(pid, 0.0)]
            rows[pid] = [round(x, 2) if x % 1 else int(x) for x in vals]
        by_gw[str(gw)] = rows
        print(f"  advanced: GW{gw} {len(rows)} players, {len(core)} with match stats", flush=True)

    teams = {t["id"]: {"short": t["short_name"], "name": t["name"]} for t in boot["teams"]}
    for p in players:
        p["team"] = next((e["team"] for e in boot["elements"] if e["id"] == p["id"]), None)
    return {"cols": COLS, "gws": list(gws), "players": players, "by_gw": by_gw, "teams": teams,
            "proj": m["proj"], "fixtures": m["fixtures"], "backtest": m["backtest"], "strength": m["strength"],
            "_internal": m["_internal"], "special_rounds": m["special_rounds"], "unscheduled": m["unscheduled"]}


def encrypt(plain, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    # plain JSON (not gzipped): every browser can read it without DecompressionStream
    data = json.dumps(plain, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt, iv = os.urandom(16), os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=32)
    ct = AESGCM(key).encrypt(iv, data, None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"v": 2, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "data": b64(ct)}


def decrypts(enc, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(enc["salt"]), enc["iter"], dklen=32)
        AESGCM(key).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["data"]), None)
        return True
    except Exception:
        return False


def write(path, plain, read_json, write_json):
    """Encrypt and write, but only when the data (or the password) changed: a fresh salt and IV
    would otherwise make every run look like a change. The stored hash covers the data only,
    never the password, so it gives no shortcut around the slow key derivation."""
    password = os.environ.get("ADV_PASSWORD")
    if not password:
        print("  advanced: ADV_PASSWORD not set, keeping the existing file", flush=True)
        return False
    digest = hashlib.sha256(json.dumps(plain, sort_keys=True).encode("utf-8")).hexdigest()
    old = read_json(path)
    if old and old.get("hash") == digest and decrypts(old, password):
        return False
    return write_json(path, {**encrypt(plain, password), "hash": digest})
