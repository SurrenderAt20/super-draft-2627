"""Does the goals model beat the market? Walk-forward backtest against Pinnacle.

Every round of matches is predicted from the matches before it only (refit Mon and Fri).
Settings are tuned on 2023/24 by log loss against results (--tune), never on the test seasons
2024/25, 2025/26 and 2026/27 so far.

Measured per league and market (1X2, over/under 2.5):
    log loss      model vs Pinnacle's first price and closing price (margin removed proportionally)
    pool weight   best w in p ~ close^(1-w) * model^w: how much the model adds to the closing price
                  (0 = nothing), with a 90% interval from resampling matches
    bets          flat 1 unit on the outcome with the largest edge = p_model * first price - 1,
                  when that edge is at least the threshold, taken at Pinnacle's first price
    CLV           expected profit of the bet if the closing fair probability is the truth, after
                  exchange commission. Much less noisy than profit, and the gate:
PASS: at least 100 bets at a 5% edge and the 90% interval for mean CLV above 0.
    baseline      the same CLV for backing every outcome of every match: what the price data gives
                  with no model at all (it should be below 0; if not, the opening prices are off)

BTTS: football-data has no BTTS odds, so the model is compared with a market proxy, BTTS from
the expected goals that reproduce Pinnacle's closing 1X2 and over/under 2.5. No bets can be tested.

    python scripts/betting_backtest.py --tune     # settings grid on 2023/24
    python scripts/betting_backtest.py            # test seasons with the settings in betting.py
"""

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import betting as bt  # noqa: E402

LEAGUES = ["E0", "E1", "E2", "E3", "D1", "D2", "SP1", "SP2", "I1", "I2", "F1", "F2", "N1"]
TEST = ["2425", "2526", "2627"]
TUNE = ["2324"]
THRESHOLDS = [0.03, 0.05, 0.10]
GATE_THR, GATE_N = 0.05, 100
RNG = np.random.default_rng(7)
BOOT = 2000
OUT = os.path.join(bt.FD, "backtest.json")
COMMISSION = {"bfe": 0.02, "ps": 0.0}   # exchange commission on net winnings (rate depends on the account)


def walk(args):
    """Predict every match of the given seasons in one division. Returns one row per match."""
    div, seasons, by_div, params = args
    allm = by_div[div]
    rows = []
    for season in seasons:
        priors = bt.team_priors(div, season, by_div)
        games = [m for m in allm if m["season"] == season]
        rounds = {}
        for m in games:
            rounds.setdefault(bt.bucket(m["date"]), []).append(m)
        for start, ms in sorted(rounds.items()):
            lo = start - timedelta(days=bt.WINDOW)
            train = [m for m in allm if lo <= m["date"] < start]
            if len(train) < 50:
                continue
            model = bt.fit(train, start, priors, teams=[t for m in ms for t in (m["home"], m["away"])], **params)
            for m in ms:
                lh, la = bt.expected_goals(model, m["home"], m["away"])
                pm = bt.markets(bt.scorelines(lh, la, model["rho"]))
                rows.append({
                    "div": div, "season": season, "date": m["date"].isoformat(), "home": m["home"], "away": m["away"],
                    "res": 0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2,
                    "over": int(m["hg"] + m["ag"] > 2), "btts": int(m["hg"] > 0 and m["ag"] > 0),
                    "lh": lh, "la": la, "m1x2": pm["1x2"], "mou": pm["ou"], "mbtts": pm["btts"],
                    "odds": m["odds"],
                })
    return rows


def run_walk(seasons, params, by_div, leagues=LEAGUES):
    with ProcessPoolExecutor() as ex:
        parts = ex.map(walk, [(d, seasons, by_div, params) for d in leagues])
        return [r for p in parts for r in p]


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-9, 1)
    return -np.log(p[np.arange(len(y)), y])


def market_arrays(rows, key, book):
    """Model, first and closing fair probabilities and outcomes, for matches that have both prices."""
    mk = "m" + key
    ok, ck = "open_" + key, "close_" + key
    use = [r for r in rows if bt.fair(r["odds"][book][ok]) and bt.fair(r["odds"][book][ck])]
    y = np.array([r["res"] if key == "1x2" else 1 - r["over"] for r in use], int)
    return (use, np.array([r[mk] for r in use]), np.array([bt.fair(r["odds"][book][ok]) for r in use]),
            np.array([bt.fair(r["odds"][book][ck]) for r in use]), np.array([r["odds"][book][ok] for r in use], float), y)


def pool_weight(model, close, y):
    ws = np.linspace(0, 1, 21)
    lc, lm = np.log(np.clip(close, 1e-9, 1)), np.log(np.clip(model, 1e-9, 1))
    losses = []
    for w in ws:
        q = np.exp((1 - w) * lc + w * lm)
        q /= q.sum(1, keepdims=True)
        losses.append(logloss(q, y))
    L = np.array(losses)                      # weights x matches
    best = ws[L.mean(1).argmin()]
    boot = [ws[L[:, i].mean(1).argmin()] for i in (RNG.integers(0, len(y), len(y)) for _ in range(300))]
    return float(best), [float(np.percentile(boot, 5)), float(np.percentile(boot, 95))], float(L[0].mean() - L.mean(1).min())


def ci(x):
    if len(x) == 0:
        return None
    x = np.asarray(x)
    means = x[RNG.integers(0, len(x), (BOOT, len(x)))].mean(1)
    return [round(float(np.percentile(means, 5)), 4), round(float(np.percentile(means, 95)), 4)]


def clv_net(price, p_close, comm):
    return p_close * (price - 1) * (1 - comm) - (1 - p_close)


def bets(model, close, price, y, thr, comm):
    edge = model * price - 1
    pick = edge.argmax(1)
    take = edge[np.arange(len(y)), pick] >= thr
    pr = price[np.arange(len(y)), pick][take]
    won = (pick == y)[take]
    profit = np.where(won, (pr - 1) * (1 - comm), -1.0)
    clv = clv_net(pr, close[np.arange(len(y)), pick][take], comm)
    return {"thr": thr, "n": int(take.sum()),
            "clv": round(float(clv.mean()), 4) if take.any() else None, "clv_ci": ci(clv),
            "roi": round(float(profit.mean()), 4) if take.any() else None, "roi_ci": ci(profit),
            "avg_price": round(float(pr.mean()), 2) if take.any() else None}


def evaluate(rows, key, book):
    use, pm, po, pc, price, y = market_arrays(rows, key, book)
    if len(y) < 30:
        return None
    w, w_ci, gain = pool_weight(pm, pc, y)
    out = {"n": len(y), "ll_model": round(float(logloss(pm, y).mean()), 4),
           "ll_open": round(float(logloss(po, y).mean()), 4), "ll_close": round(float(logloss(pc, y).mean()), 4),
           "pool_w": w, "pool_w_ci": w_ci, "pool_gain": round(gain, 5),
           "baseline_clv": round(float(clv_net(price, pc, COMMISSION[book]).mean()), 4),
           "bets": [bets(pm, pc, price, y, t, COMMISSION[book]) for t in THRESHOLDS]}
    g = next(b for b in out["bets"] if b["thr"] == GATE_THR)
    out["pass"] = bool(g["n"] >= GATE_N and g["clv_ci"] and g["clv_ci"][0] > 0)
    return out


# BTTS proxy: expected goals reproducing the closing 1X2 and over 2.5, by nearest point on a grid
_G = np.arange(0.1, 4.51, 0.025)


def _grid():
    k = np.arange(bt.MAXG + 1)
    fact = np.array([float(np.prod(range(1, i + 1))) for i in k])
    pk = np.exp(-_G[:, None]) * _G[:, None] ** k / fact          # lambdas x goals
    P = pk[:, None, :, None] * pk[None, :, None, :]              # lh x la x hg x ag
    x, yy = np.indices((bt.MAXG + 1, bt.MAXG + 1))
    H = P[..., x > yy].sum(-1); A = P[..., x < yy].sum(-1); O = P[..., x + yy > 2].sum(-1)
    B = (1 - pk[:, 0])[:, None] * (1 - pk[:, 0])[None, :]
    return H.ravel(), A.ravel(), O.ravel(), B.ravel()


def btts_eval(rows, book):
    use = [r for r in rows if bt.fair(r["odds"][book]["close_1x2"]) and bt.fair(r["odds"][book]["close_ou"])]
    if len(use) < 30:
        return None
    H, A, O, B = _grid()
    proxy = []
    for r in use:
        h, _, a = bt.fair(r["odds"][book]["close_1x2"])
        o = bt.fair(r["odds"][book]["close_ou"])[0]
        proxy.append(B[((H - h) ** 2 + (A - a) ** 2 + (O - o) ** 2).argmin()])
    proxy = np.array(proxy)
    pm = np.array([r["mbtts"][0] for r in use])
    y = np.array([1 - r["btts"] for r in use])          # 0 = yes, matching [yes, no]
    pc = np.column_stack([proxy, 1 - proxy])
    pmm = np.column_stack([pm, 1 - pm])
    w, w_ci, gain = pool_weight(pmm, pc, y)
    return {"n": len(y), "ll_model": round(float(logloss(pmm, y).mean()), 4), "ll_proxy": round(float(logloss(pc, y).mean()), 4),
            "base_rate": round(float((y == 0).mean()), 3), "pool_w": w, "pool_w_ci": w_ci, "pool_gain": round(gain, 5)}


def tune(by_div):
    grid = list(itertools.product([0.0015, 0.003, 0.006], [3.0, 8.0, 20.0], [1.0, 0.6, 0.3]))
    res = []
    for xi, ridge, sot_w in grid:
        t = time.time()
        rows = run_walk(TUNE, {"xi": xi, "ridge": ridge, "sot_w": sot_w}, by_div)
        ll1 = logloss([r["m1x2"] for r in rows], np.array([r["res"] for r in rows])).mean()
        llo = logloss([r["mou"] for r in rows], np.array([1 - r["over"] for r in rows])).mean()
        res.append((ll1 + llo, ll1, llo, xi, ridge, sot_w))
        print(f"xi {xi:<6} ridge {ridge:<5} sot_w {sot_w:<4} 1x2 {ll1:.4f} ou {llo:.4f}  ({time.time() - t:.0f}s, {len(rows)} matches)", flush=True)
    res.sort()
    print("best:", res[0][3:], flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    a = ap.parse_args()
    divs = sorted({d for ds in bt.CHAINS.values() for d in ds})
    bt.download(divs)
    by_div = {d: bt.load(d) for d in divs}
    print("matches:", {d: len(v) for d, v in by_div.items()}, flush=True)
    if a.tune:
        tune(by_div)
        return

    t = time.time()
    rows = run_walk(TEST, {"xi": bt.XI, "ridge": bt.RIDGE, "sot_w": bt.SOT_W}, by_div)
    print(f"walk-forward: {len(rows)} matches in {time.time() - t:.0f}s", flush=True)
    report = {"settings": {"xi": bt.XI, "ridge": bt.RIDGE, "sot_w": bt.SOT_W, "promo": bt.PROMO},
              "test_seasons": TEST, "gate": {"thr": GATE_THR, "min_bets": GATE_N}, "books": {}}
    for book in ("bfe", "ps"):
        rep = {"all": {k: evaluate(rows, k, book) for k in ("1x2", "ou")}, "leagues": {}}
        rep["all"]["btts"] = btts_eval(rows, book)
        for d in LEAGUES:
            lr = [r for r in rows if r["div"] == d]
            rep["leagues"][d] = {"name": bt.NAMES[d], "1x2": evaluate(lr, "1x2", book), "ou": evaluate(lr, "ou", book), "btts": btts_eval(lr, book)}
        # per season, all leagues: is any result stable over time?
        rep["seasons"] = {s: {k: evaluate([r for r in rows if r["season"] == s], k, book) for k in ("1x2", "ou")} for s in TEST}
        report["books"][book] = rep
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    for book, rep in report["books"].items():
        print(f"\n===== reference: {book} =====")
        print_report(rep)


def _fmt(e, key):
    if not e:
        return f"{key:<5} (too few matches)"
    g = next(b for b in e["bets"] if b["thr"] == GATE_THR)
    clv = f"{g['clv']:+.3f} [{g['clv_ci'][0]:+.3f},{g['clv_ci'][1]:+.3f}]" if g["n"] else "-"
    roi = f"{g['roi']:+.3f} [{g['roi_ci'][0]:+.3f},{g['roi_ci'][1]:+.3f}]" if g["n"] else "-"
    return (f"{key:<5} n {e['n']:<5} LL model {e['ll_model']:.4f} open {e['ll_open']:.4f} close {e['ll_close']:.4f} "
            f"w {e['pool_w']:.2f} [{e['pool_w_ci'][0]:.2f},{e['pool_w_ci'][1]:.2f}] | base {e['baseline_clv']:+.3f} bets {g['n']:<4} CLV {clv} ROI {roi} "
            f"{'PASS' if e['pass'] else 'fail'}")


def _fmt_btts(b):
    if not b:
        return "btts  (too few matches)"
    return f"btts  n {b['n']:<5} LL model {b['ll_model']:.4f} proxy {b['ll_proxy']:.4f} w {b['pool_w']:.2f} [{b['pool_w_ci'][0]:.2f},{b['pool_w_ci'][1]:.2f}]"


def print_report(rep):
    print("ALL LEAGUES")
    for k in ("1x2", "ou"):
        print("  " + _fmt(rep["all"][k], k))
    print("  " + _fmt_btts(rep["all"]["btts"]))
    for d, v in rep["leagues"].items():
        print(f"{v['name']} ({d})")
        for k in ("1x2", "ou"):
            print("  " + _fmt(v[k], k))
        print("  " + _fmt_btts(v["btts"]))
    print("BY SEASON (all leagues)")
    for s, v in rep["seasons"].items():
        for k in ("1x2", "ou"):
            print(f"  {s} " + _fmt(v[k], k))

if __name__ == "__main__":
    main()
