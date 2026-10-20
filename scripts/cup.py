"""The league's own competitions from the shared Google Sheet: the cup (pokalturnering),
the best single round (højest single GW) and the prize split.

The sheet is maintained by hand and is the source of truth; it is read on every run (every
three hours). Where a cup score is still empty but both legs have been played, a provisional
aggregate is computed from the FPL round scores and marked as such. The sheet's rule for
double gameweeks (only a player's best single match counts) is not applied to that estimate.
"""

import csv
import difflib
import io
import re
import urllib.request

SHEET = "17ewEDgE99HTOYtOQipQjYy-VOLaiZUP2gUCBo6Og3Po"
TAB_CUP = "0"
TAB_PRIZES = "15420024"


def _sheet(gid):
    url = f"https://docs.google.com/spreadsheets/d/{SHEET}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "super-draft-league-site/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return list(csv.reader(io.StringIO(r.read().decode("utf-8"))))


def _int(v):
    m = re.search(r"-?\d+", str(v or ""))
    return int(m.group()) if m else None


def name_matcher(entries):
    """Sheet names ('Kasper F', 'Jakob', 'Emil (Team Gitte)', 'Draft Rank 3 - Emil') -> league entry id."""
    keys = {}
    for le, e in entries.items():
        first, last = e["first"].strip(), (e.get("last") or "").strip()
        keys[f"{first} {last[:1]}".lower()] = le
        keys[f"{first.split()[0]} {last[:1]}".lower()] = le   # 'Kasper F' for Kasper Erik Friis
        keys[first.lower()] = keys.get(first.lower(), le) if sum(1 for x in entries.values() if x["first"] == first) == 1 else None
        keys[e["team"].lower()] = le

    def find(raw):
        s = re.sub(r"^draft rank \d+\s*-\s*", "", str(raw or "").strip(), flags=re.I)
        s = re.sub(r"\s*\(.*\)$", "", s).strip()
        if not s or re.fullmatch(r"[\d/]+", s):
            return None
        k = s.lower()
        if keys.get(k):
            return keys[k]
        close = difflib.get_close_matches(k, [x for x, v in keys.items() if v], n=1, cutoff=0.75)
        return keys[close[0]] if close else None
    return find


def parse_cup(rows, find):
    cell = lambda r, c: rows[r][c].strip() if r < len(rows) and c < len(rows[r]) else ""
    out = {"rules": "", "qualifier": None, "stages": [], "best_gw": [], "best_gw_rules": ""}

    # rules: the line under each title
    for c in range(len(rows[0]) if rows else 0):
        if cell(0, c).lower().startswith("pokalturnering"):
            out["rules"] = cell(1, c).replace("Regler:", "").strip()
        if cell(0, c).lower().startswith("højest single"):
            out["best_gw_rules"] = cell(1, c).replace("Regler:", "").strip()

    # best single round: first three columns, GW | team | points
    for r in range(len(rows)):
        gw, who, pts = _int(cell(r, 0)), cell(r, 1), _int(cell(r, 2))
        if gw and who and pts is not None and cell(r, 0).strip().isdigit():
            out["best_gw"].append({"gw": gw, "name": who, "le": find(who), "points": pts})

    # qualifier: "Kval Kamp N" headers, the two rows below hold name | aggregate
    qual_gws = None
    for r in range(len(rows)):
        for c in range(len(rows[r])):
            v = cell(r, c)
            if re.match(r"gw\s*\d+\s*&\s*\d+", v, re.I) and qual_gws is None and any("kval" in cell(r, x).lower() for x in range(len(rows[r]))):
                qual_gws = [int(x) for x in re.findall(r"\d+", v)]
    matches = []
    for r in range(len(rows)):
        for c in range(len(rows[r])):
            if re.match(r"kval kamp \d", cell(r, c), re.I):
                a, b = (cell(r + 1, c), _int(cell(r + 1, c + 1))), (cell(r + 2, c), _int(cell(r + 2, c + 1)))
                matches.append({"a": a[0], "a_le": find(a[0]), "sa": a[1], "b": b[0], "b_le": find(b[0]), "sb": b[1]})
    if matches:
        out["qualifier"] = {"gws": qual_gws or [], "matches": matches}

    # knockout stages: a header row with Kvartfinale / Semifinale / Finale, legs ("GW 11 & 16") in the row above,
    # entries (name or seed placeholder) in the stage column and the aggregate in the column to its right
    for r in range(len(rows)):
        names = {c: cell(r, c) for c in range(len(rows[r])) if cell(r, c).lower() in ("kvartfinale", "semifinale", "finale")}
        if not names:
            continue
        for c, title in sorted(names.items()):
            legs = [int(x) for x in re.findall(r"\d+", cell(r - 1, c))]
            entries = []
            for rr in range(r + 1, len(rows)):
                v = cell(rr, c)
                if v:
                    seed = _int(cell(rr, c - 1)) if title.lower() == "kvartfinale" else None
                    entries.append({"name": v, "le": find(v), "score": _int(cell(rr, c + 1)), "seed": seed})
            pairs = [{"a": entries[i], "b": entries[i + 1]} for i in range(0, len(entries) - 1, 2)]
            out["stages"].append({"title": title.capitalize(), "gws": legs, "matches": pairs})
        break
    return out


def parse_prizes(rows):
    """'Fordelingsnøgle' label/amount pairs, pot and entry fee. Payment status is left out on purpose."""
    cell = lambda r, c: rows[r][c].strip() if r < len(rows) and c < len(rows[r]) else ""
    out = {"pot": None, "fee": None, "split": []}
    for r in range(len(rows)):
        for c in range(len(rows[r])):
            v = cell(r, c).lower()
            if v == "pulje":
                out["pot"] = _int(cell(r, c + 1).replace(".", ""))
            if v == "indskud":
                out["fee"] = _int(cell(r + 1, c).replace(".", ""))
            if v.startswith("fordelingsn"):
                for rr in range(r, len(rows)):
                    label, amount = cell(rr, c).rstrip(":"), _int(cell(rr, c + 1).replace(".", ""))
                    if rr > r and label and amount:
                        out["split"].append({"label": label, "amount": amount})
                    elif rr == r and _int(cell(rr, c + 1)):
                        pass
    return out


def provisional(stage_gws, a_le, b_le, scores):
    """Aggregate from FPL round scores when the sheet has no score yet and both legs are played."""
    if not a_le or not b_le or not stage_gws or not all(g in scores for g in stage_gws):
        return None
    return sum(scores[g].get(a_le, 0) for g in stage_gws), sum(scores[g].get(b_le, 0) for g in stage_gws)


def build(entries, snapshots, old=None):
    find = name_matcher(entries)
    try:
        cup = parse_cup(_sheet(TAB_CUP), find)
        prizes = parse_prizes(_sheet(TAB_PRIZES))
    except Exception as e:
        print(f"  cup: sheet unavailable ({e}); keeping the last version", flush=True)
        return old
    scores = {g: {int(le): t["score"] for le, t in s["teams"].items()} for g, s in snapshots.items()}

    def settle(m, gws):
        a, b = m["a"], m["b"]
        if a.get("score") is None and b.get("score") is None:
            pv = provisional(gws, a.get("le"), b.get("le"), scores)
            if pv:
                a["score"], b["score"], m["provisional"] = pv[0], pv[1], True
        if a.get("score") is not None and b.get("score") is not None and a["score"] != b["score"]:
            m["winner"] = "a" if a["score"] > b["score"] else "b"
        elif a.get("score") is not None and a.get("score") == b.get("score"):
            m["tie"] = True
    if cup["qualifier"]:
        for m in cup["qualifier"]["matches"]:
            mm = {"a": {"name": m["a"], "le": m["a_le"], "score": m["sa"]}, "b": {"name": m["b"], "le": m["b_le"], "score": m["sb"]}}
            settle(mm, cup["qualifier"]["gws"])
            m.clear()
            m.update(mm)
    for st in cup["stages"]:
        for m in st["matches"]:
            settle(m, st["gws"])
    unmatched = sorted({e["name"] for st in cup["stages"] for m in st["matches"] for e in (m["a"], m["b"])
                        if e.get("le") is None and not re.fullmatch(r"[\d/]+", e["name"])})
    if unmatched:
        print(f"  cup: names not matched to a manager: {unmatched}", flush=True)
    print(f"  cup: {len(cup['best_gw'])} best-round winners, {sum(len(s['matches']) for s in cup['stages'])} knockout matches, "
          f"{len(prizes['split'])} prize lines", flush=True)
    return {"cup": cup, "prizes": prizes, "sheet": f"https://docs.google.com/spreadsheets/d/{SHEET}"}
