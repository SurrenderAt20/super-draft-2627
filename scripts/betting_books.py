"""Price comparison: is a bookmaker's price ever better than the exchange's fair price?

No model. For every match and outcome, the bookmaker's first price (collected at the same time
as the exchange's, Friday for weekend games) is compared with Betfair Exchange's fair probability
at that time (margin removed). When price * fair - 1 >= threshold, it is a signal. Each signal is
judged by CLV: expected profit if the exchange's closing fair probability is the truth.

PASS (per bookmaker and market): at least 100 signals, 90% interval for mean CLV above 0, and
mean CLV above 0 in each of 2024/25 and 2025/26 separately (many bookmakers x markets x groups
are tested, so one good interval alone could be chance).

    python scripts/betting_books.py
"""

import csv
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import betting as bt  # noqa: E402

LEAGUES = ["E0", "E1", "E2", "E3", "D1", "D2", "SP1", "SP2", "I1", "I2", "F1", "F2", "N1"]
GROUPS = {"top 5": ["E0", "D1", "SP1", "I1", "F1"], "EFL": ["E1", "E2", "E3"],
          "other": ["D2", "SP2", "I2", "F2", "N1"]}
SEASONS = ["2425", "2526", "2627"]
BOOKS = ["B365", "BW", "WH", "1XB", "BV", "CL", "LB", "BFD", "BMGM", "SKB", "PS", "Max"]
THRESHOLDS = [0.0, 0.02, 0.05]
REF_OPEN = {"1x2": ("BFEH", "BFED", "BFEA"), "ou": ("BFE>2.5", "BFE<2.5")}
REF_CLOSE = {"1x2": ("BFECH", "BFECD", "BFECA"), "ou": ("BFEC>2.5", "BFEC<2.5")}
SUFFIX = {"1x2": ("H", "D", "A"), "ou": (">2.5", "<2.5")}
OUTCOME = {"1x2": ("home", "draw", "away"), "ou": ("over", "under")}
RNG = np.random.default_rng(5)


def _num(v):
    try:
        x = float(v)
        return x if x > 1.0 else None
    except (TypeError, ValueError):
        return None


def signals():
    """One row per (match, outcome, bookmaker) where the bookmaker and both exchange prices exist."""
    rows = []
    for div in LEAGUES:
        for s in SEASONS:
            path = os.path.join(bt.FD, f"{div}_{s}.csv")
            with open(path, "rb") as f:
                text = f.read().decode("utf-8-sig", errors="replace")
            for r in csv.DictReader(io.StringIO(text)):
                for mk in ("1x2", "ou"):
                    fo = bt.fair([_num(r.get(c)) for c in REF_OPEN[mk]])
                    fc = bt.fair([_num(r.get(c)) for c in REF_CLOSE[mk]])
                    if not fo or not fc:
                        continue
                    for book in BOOKS:
                        pref = "P" if book == "PS" and mk == "ou" else book
                        for i, suf in enumerate(SUFFIX[mk]):
                            p = _num(r.get(pref + suf))
                            if p is None:
                                continue
                            rows.append((div, s, mk, book, i, p, p * fo[i] - 1, p * fc[i] - 1))
    return rows


def ci(x):
    m = x[RNG.integers(0, len(x), (2000, len(x)))].mean(1)
    return np.percentile(m, [5, 95])


def summarise(sel):
    """sel: list of rows. Returns n, mean CLV, interval, mean CLV per season."""
    clv = np.array([r[7] for r in sel])
    by = {s: float(np.mean([r[7] for r in sel if r[1] == s])) if any(r[1] == s for r in sel) else None for s in SEASONS}
    lo, hi = ci(clv) if len(clv) else (None, None)
    return {"n": len(clv), "clv": float(clv.mean()) if len(clv) else None, "ci": (lo, hi), "season": by,
            "price": float(np.mean([r[5] for r in sel])) if sel else None}


def passes(s):
    return (s["n"] >= 100 and s["ci"][0] > 0
            and all(s["season"][x] is not None and s["season"][x] > 0 for x in ("2425", "2526")))


def fmt(s):
    if not s["n"]:
        return "n 0"
    se = " ".join(f"{k}:{v:+.3f}" if v is not None else f"{k}:-" for k, v in s["season"].items())
    return (f"n {s['n']:<5} CLV {s['clv']:+.3f} [{s['ci'][0]:+.3f},{s['ci'][1]:+.3f}] price {s['price']:.2f} | {se}"
            f"{'  PASS' if passes(s) else ''}")


def main():
    rows = signals()
    print(f"{len(rows)} bookmaker prices compared\n")
    for mk in ("1x2", "ou"):
        for thr in THRESHOLDS:
            print(f"=== {mk}, price at least {thr:.0%} above exchange fair price")
            for book in BOOKS:
                sel = [r for r in rows if r[2] == mk and r[3] == book and r[6] >= thr]
                if not sel:
                    continue
                print(f"  {book:<5} all    " + fmt(summarise(sel)))
                for g, ds in GROUPS.items():
                    gs = [r for r in sel if r[0] in ds]
                    if gs:
                        print(f"  {'':<5} {g:<6} " + fmt(summarise(gs)))
            print()
    # bet365 in detail: per league and outcome at a 2% threshold
    print("=== B365 detail, price at least 2% above exchange fair price")
    for mk in ("1x2", "ou"):
        for div in LEAGUES:
            sel = [r for r in rows if r[2] == mk and r[3] == "B365" and r[0] == div and r[6] >= 0.02]
            if sel:
                print(f"  {mk:<4} {bt.NAMES[div]:<15} " + fmt(summarise(sel)))
        for i, name in enumerate(OUTCOME[mk]):
            sel = [r for r in rows if r[2] == mk and r[3] == "B365" and r[4] == i and r[6] >= 0.02]
            if sel:
                print(f"  {mk:<4} {name:<15} " + fmt(summarise(sel)))


if __name__ == "__main__":
    main()
