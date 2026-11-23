"""Write explained decision records for the 12-1 momentum baseline (demo for the dashboard).

Monthly, 2024-01 -> latest month end: among companies tradable as of that date
(all investment screens pass, AsOf.tradable), with average daily dollar volume
>= $10M, hold the top 10 by 12-1 momentum. Each decision records:
  - thesis factor: momentum z-score (the only thing that drives this rule)
  - screen evidence: Sharia ratios as last known, liquidity
  - context (contribution 0 for this rule, shown for transparency): insider
    open-market net buying (90d), news mentions/tone (30d), bottleneck language (1y)
Every factor carries knowable_at <= decision time (DecisionLog enforces it).

    python scripts/demo_decisions.py [--start 2024-01] [--top 10]
"""
import argparse

import numpy as np
import pandas as pd

from ddb.config import DATA_DIR
from ddb.db.pit import AsOf
from ddb.db.schema import connect
from ddb.decisions import DecisionLog, Factor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    con = connect(DATA_DIR / "ddb.duckdb")
    con.execute("DELETE FROM decision_factors WHERE decision_id IN (SELECT decision_id FROM decisions "
                "WHERE run_id IN (SELECT run_id FROM decision_runs WHERE model = 'momentum-12-1-demo'))") \
        if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='decisions'").fetchone()[0] else None
    log = DecisionLog(con)
    con.execute("DELETE FROM decisions WHERE run_id IN (SELECT run_id FROM decision_runs WHERE model='momentum-12-1-demo')")
    con.execute("DELETE FROM decision_runs WHERE model='momentum-12-1-demo'")

    print("loading prices ...", flush=True)
    px = con.execute("""
        SELECT t.cik, upper(p.symbol) AS ticker, p.date, p.close, p.close_raw, p.volume_raw, p.knowable_at
        FROM prices p JOIN (SELECT cik, upper(current_tickers[1]) AS sym FROM companies
                            WHERE len(current_tickers) > 0) t          -- primary (common) ticker only
          ON t.sym = upper(p.symbol)
        WHERE p.date >= DATE '2022-06-01' AND p.source = 'yahoo'
    """).df()
    px["date"] = pd.to_datetime(px["date"])
    px["dollar_vol"] = px["close_raw"] * px["volume_raw"]
    close = px.pivot_table(index="date", columns="cik", values="close", aggfunc="last").sort_index()
    dvol = px.pivot_table(index="date", columns="cik", values="dollar_vol", aggfunc="last").sort_index()
    tick = px.groupby("cik")["ticker"].agg(lambda s: s.value_counts().index[0]).to_dict()
    names = con.execute("SELECT cik, name FROM companies").df().set_index("cik")["name"].to_dict()

    ins = con.execute("""
        SELECT cik, knowable_at, trans_code, shares * price AS value FROM insider_transactions
        WHERE NOT is_derivative AND trans_code IN ('P', 'S') AND trans_date >= DATE '2023-01-01'
          AND NOT trans_date_suspect
    """).df()
    ins["signed"] = np.where(ins["trans_code"] == "P", ins["value"], -ins["value"])
    try:
        news = con.execute("""SELECT unnest(ciks) AS cik, knowable_at, tone FROM news_events WHERE len(ciks) > 0""").df()
    except Exception:  # noqa: BLE001
        news = pd.DataFrame(columns=["cik", "knowable_at", "tone"])
    try:
        bott = con.execute("SELECT cik, knowable_at FROM filing_text_signals WHERE signal = 'bottleneck'").df()
    except Exception:  # noqa: BLE001
        bott = pd.DataFrame(columns=["cik", "knowable_at"])
    fin = con.execute("SELECT * FROM screen_sharia_financial").df()

    months = pd.period_range(a.start, (pd.Timestamp.now() - pd.offsets.MonthEnd(1)).to_period("M"), freq="M")
    run = log.new_run("momentum-12-1-demo", params={"top": a.top, "min_adv": 10e6, "lookback": 252, "skip": 21},
                      description="Demo: hold top-N by 12-1 momentum among screened, liquid companies. "
                                  "Context factors are shown for transparency and do not affect this rule.")
    held: dict[int, float] = {}
    n_dec = 0
    for m in months:
        trade_dates = close.index[close.index <= m.end_time]
        if len(trade_dates) < 260:
            continue
        d = trade_dates[-1]
        as_of = (pd.Timestamp(d) + pd.Timedelta(hours=21, minutes=30)).tz_localize("UTC")
        with AsOf(con, as_of) as db:
            uni = db.tradable()
        cands = [c for c in uni["cik"].unique() if c in close.columns]
        hist = close.loc[:d, cands]
        if len(hist) < 253:
            continue
        mom = hist.iloc[-22] / hist.iloc[-253] - 1
        adv = dvol.loc[:d, cands].tail(20).mean()
        ok = mom.replace([np.inf, -np.inf], np.nan).dropna()
        ok = ok[adv.reindex(ok.index) >= 10e6]
        if len(ok) < a.top:
            continue
        z = (ok - ok.mean()) / ok.std()
        top = set(z.sort_values(ascending=False).head(a.top).index)
        w = 1.0 / a.top
        px_known = (pd.Timestamp(hist.index[-22]) + pd.Timedelta(hours=21)).tz_localize("UTC")
        inds = uni.groupby("cik")["industry"].agg(lambda s: ", ".join(sorted(set(s)))).to_dict()
        for cik in sorted(top | set(held)):
            action = "hold" if (cik in top and cik in held) else ("buy" if cik in top else "sell")
            target = w if cik in top else 0.0
            f = [Factor("12-1 momentum", float(z.get(cik, np.nan)) if cik in z else 0.0,
                        value=float(ok.get(cik, np.nan)) if cik in ok else None,
                        value_text=f"{ok.get(cik, np.nan):+.0%} (rank {int((z > z.get(cik, -99)).sum()) + 1} of {len(z)})"
                        if cik in z else "fell out of the screened/liquid universe",
                        group="thesis", description="Return from 12 months ago to 1 month ago (z-score across universe)",
                        source_table="prices", knowable_at=px_known)]
            f.append(Factor("liquidity (20d avg $ volume)", 0.0, value=float(adv.get(cik, np.nan)),
                            value_text=f"${adv.get(cik, np.nan) / 1e6:,.0f}M/day", group="screen",
                            description="Must be at least $10M/day", source_table="prices",
                            knowable_at=(pd.Timestamp(d) + pd.Timedelta(hours=21)).tz_localize("UTC")))
            fr = fin[(fin["cik"] == cik) & (fin["knowable_at"] <= as_of)].sort_values("as_of").tail(1)
            if len(fr):
                r = fr.iloc[0]
                f.append(Factor("Sharia ratio screen", 0.0, value_text=f"{r['status']}: debt {r['debt_ratio']:.0%}, cash {r['cash_ratio']:.0%}, "
                                f"interest income {0 if pd.isna(r['impermissible_share']) else r['impermissible_share']:.1%}",
                                group="screen", description="AAOIFI-style: debt ≤30%, cash+interest securities ≤30%, interest ≤5%",
                                source_table="screen_sharia_financial", source_ref=str(pd.Timestamp(r["as_of"]).date()),
                                knowable_at=r["knowable_at"]))
            iw = ins[(ins["cik"] == cik) & (ins["knowable_at"] <= as_of) & (ins["knowable_at"] > as_of - pd.Timedelta(days=90))]
            f.append(Factor("insider open-market net buying (90d)", 0.0, value=float(iw["signed"].sum()),
                            value_text=f"${iw['signed'].sum() / 1e6:+,.1f}M ({(iw['trans_code'] == 'P').sum()} buys, {(iw['trans_code'] == 'S').sum()} sales)",
                            group="context", description="Form 4 P minus S, by filing date", source_table="insider_transactions",
                            knowable_at=iw["knowable_at"].max() if len(iw) else None))
            nw = news[(news["cik"] == cik) & (news["knowable_at"] <= as_of) & (news["knowable_at"] > as_of - pd.Timedelta(days=30))]
            f.append(Factor("news mentions (30d)", 0.0, value=float(len(nw)),
                            value_text=f"{len(nw):,} articles, avg tone {nw['tone'].mean():+.1f}" if len(nw) else "no coverage loaded",
                            group="context", description="GDELT articles naming the company", source_table="news_events",
                            knowable_at=nw["knowable_at"].max() if len(nw) else None))
            bw = bott[(bott["cik"] == cik) & (bott["knowable_at"] <= as_of) & (bott["knowable_at"] > as_of - pd.Timedelta(days=365))]
            f.append(Factor("bottleneck language in filings (1y)", 0.0, value=float(len(bw)),
                            value_text=f"{len(bw)} filing mentions", group="context",
                            description="Supply-constraint phrases in 10-K/10-Q/8-K", source_table="filing_text_signals",
                            knowable_at=bw["knowable_at"].max() if len(bw) else None))
            rationale = (f"{'Top' if cik in top else 'Not in top'} {a.top} by 12-1 momentum among {len(z)} screened, "
                         f"liquid companies ({inds.get(cik, 'n/a')}).")
            log.record(run, as_of, cik, tick.get(cik, ""), action, target_weight=target, prev_weight=held.get(cik, 0.0),
                       confidence=None, score=float(z.get(cik, np.nan)) if cik in z else None, rationale=rationale, factors=f)
            n_dec += 1
        held = {c: w for c in top}
        print(f"  {d.date()}: universe {len(z)}, top: {', '.join(tick.get(c, str(c)) for c in sorted(top, key=lambda c: -z[c]))}", flush=True)
    log.flush()
    con.close()
    print(f"run {run}: {n_dec} decisions")


if __name__ == "__main__":
    main()
