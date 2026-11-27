"""Monthly point-in-time signal panel + forward returns (for validation and models).

For every month-end trading day t (2011 -> latest), for every company that is
active in a tracked industry at t and has a usable price, compute each signal in
configs/signals.yaml using only information public by t, plus forward returns
over the next 21 / 63 trading days (targets, never inputs).

Point-in-time rules
- Prices: closes through t. Fundamentals: the FIRST published version of each
  fact (a later restatement can't leak backwards), latest period known by t.
- Events/insiders/news/etc.: rows with knowable_at <= t.
- Forward returns: if a stock stops trading inside the window, the last price is
  used and, for failure exits (bankrupt / forced delisting / deregistration), a
  -30% delisting return is applied (Shumway 1997) so failures aren't dropped.

    python -m ddb.features.panel
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from ..db.schema import connect

OUT = DATA_DIR / "db" / "signals"
DB_PATH = DATA_DIR / "ddb.duckdb"
FAIL_OUTCOMES = {"bankrupt", "delisted_exchange", "deregistered"}
# XBRL names for revenue and cost of goods, most common first. Older US filers (pre-2018,
# before ASC 606) used SalesRevenue*; IFRS filers use Revenue / CostOfSales.
REVENUE = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
           "SalesRevenueServicesNet", "Revenue"]
COGS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfSales", "CostOfServices",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]
DELIST_RET = -0.30


# ------------------------------------------------------------------ inputs
def load_prices(con) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Daily wide frames (index date, columns cik): split-adj close, as-traded close, volume."""
    px = con.execute("""
        WITH prim AS (SELECT cik, upper(current_tickers[1]) AS sym FROM companies WHERE len(current_tickers) > 0),
        y AS (
            SELECT prim.cik, p.date, p.close, p.close_raw, p.volume_raw
            FROM prices p JOIN prim ON upper(p.symbol) = prim.sym
            WHERE p.source = 'yahoo' AND p.date >= DATE '2009-06-01'
        ),
        a AS (
            SELECT p.cik, p.date, p.close, p.close_raw, p.volume_raw
            FROM prices p WHERE p.source = 'alpaca' AND p.cik IS NOT NULL
              AND p.cik NOT IN (SELECT DISTINCT cik FROM y)
        )
        SELECT * FROM y UNION ALL SELECT * FROM a
    """).df()
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna(subset=["close"])
    piv = lambda col: px.pivot_table(index="date", columns="cik", values=col, aggfunc="last").sort_index()
    return piv("close"), piv("close_raw"), piv("volume_raw")


# Industry-tag methods to leave out (e.g. ("research",)): configs/signals.yaml exclude_tag_methods.
def _exclude_methods() -> tuple:
    try:
        import yaml

        from ..config import CONFIG_DIR
        return tuple(yaml.safe_load((CONFIG_DIR / "signals.yaml").read_text()).get("exclude_tag_methods") or ())
    except Exception:  # noqa: BLE001
        return ()


EXCLUDE_METHODS: tuple | None = None          # None = from config; set a tuple to override


def universe_by_month(con, months: list[pd.Timestamp]) -> pd.DataFrame:
    methods = _exclude_methods() if EXCLUDE_METHODS is None else EXCLUDE_METHODS
    excl = ",".join(f"'{m}'" for m in methods) or "''"
    m = pd.DataFrame({"d": [x.date() for x in months]})
    con.register("mgrid", m)
    df = con.execute(f"""
        WITH fm AS (SELECT DISTINCT cik, CAST(date_trunc('month', filing_date) AS DATE) AS m FROM filings),
        tagged AS (
            SELECT g.d, ci.cik, arg_min(ci.industry, CASE ci.method WHEN 'research' THEN 0 WHEN 'sic' THEN 1 ELSE 2 END) AS industry
            FROM mgrid g JOIN company_industries ci
              ON ci.valid_from <= g.d AND (ci.valid_to IS NULL OR ci.valid_to > g.d) AND ci.confidence <> 'low'
             AND ci.method NOT IN ({excl})
            GROUP BY 1, 2
        )
        SELECT t.* FROM tagged t
        WHERE EXISTS (SELECT 1 FROM fm WHERE fm.cik = t.cik AND fm.m > t.d - INTERVAL 18 MONTH AND fm.m <= t.d)
    """).df()
    con.unregister("mgrid")
    df["d"] = pd.to_datetime(df["d"])
    return df


def first_versions(con, concepts: list[str], annual: bool) -> pd.DataFrame:
    """First-published value per (cik, concept, period). annual=True keeps ~1-year durations."""
    dur = "AND datediff('day', period_start, period_end) BETWEEN 350 AND 380" if annual else "AND period_start IS NULL"
    q = ",".join(f"'{c}'" for c in concepts)
    return con.execute(f"""
        SELECT cik, concept, period_end, arg_min(value, (knowable_at, value)) AS value, min(knowable_at) AS known
        FROM fundamentals
        WHERE concept IN ({q}) AND unit IN ('USD', 'shares', 'USD/shares') {dur} AND value IS NOT NULL
        GROUP BY 1, 2, 3
    """).df()


def prefer(frames: list[pd.DataFrame], key: list[str], latest_period: bool = False) -> pd.DataFrame:
    """One fact per key: the earliest known; ties (same filing) go to the latest period
    if latest_period, then to the earlier frame in `frames` (order of preference).
    Deterministic, and a fact published later can never displace one known earlier."""
    df = pd.concat([f.assign(_pref=i) for i, f in enumerate(frames)], ignore_index=True)
    by, asc = ["known"], [True]
    if latest_period and "period_end" in df:
        by, asc = by + ["period_end"], asc + [False]
    df = df.sort_values(by + ["_pref"], ascending=asc + [True], kind="stable")
    return df.drop_duplicates(key).drop(columns="_pref")


def ticker_cik(con) -> pd.DataFrame:
    """(ticker, month, cik): which company traded under each ticker in each month, from the
    cleaned price data itself, so a symbol reused by another company is never attributed
    to the wrong one."""
    return con.execute("""
        WITH prim AS (SELECT cik, upper(current_tickers[1]) AS sym FROM companies WHERE len(current_tickers) > 0)
        SELECT DISTINCT upper(p.symbol) AS ticker, CAST(date_trunc('month', p.date) AS DATE) AS m,
               coalesce(p.cik, prim.cik) AS cik
        FROM prices p LEFT JOIN prim ON upper(p.symbol) = prim.sym
        WHERE coalesce(p.cik, prim.cik) IS NOT NULL AND p.date >= DATE '2009-06-01'""").df()


def attach_cik(rows: pd.DataFrame, tm: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """rows (ticker, date_col, ...) -> with cik, matched on the ticker's company in that
    month or the month before."""
    r = rows.copy()
    m0 = pd.to_datetime(r[date_col]).dt.tz_localize(None).dt.to_period("M")
    tm = tm.assign(m=pd.to_datetime(tm["m"]).dt.to_period("M"))
    out = []
    for lag in (0, 1):
        x = r.assign(m=m0 - lag).merge(tm, on=["ticker", "m"], how="inner")
        out.append(x)
    x = pd.concat(out).drop(columns="m")
    return x.drop_duplicates([c for c in x.columns if c != "cik"] + ["cik"])


def asof(grid: pd.DataFrame, facts: pd.DataFrame, value_col: str, name: str, max_age_days: int | None = None) -> pd.Series:
    """Latest fact known by each grid time (grid has cik, t)."""
    f = facts.dropna(subset=[value_col])
    f = f.sort_values(["known", "period_end"] if "period_end" in f else ["known"], kind="stable")
    g = grid[["cik", "t"]].reset_index().sort_values("t")
    m = pd.merge_asof(g, f[["cik", "known", value_col] + (["period_end"] if "period_end" in f else [])],
                      left_on="t", right_on="known", by="cik", direction="backward")
    if max_age_days is not None:
        m.loc[(m["t"] - m["known"]).dt.days > max_age_days, value_col] = np.nan
    return m.set_index("index")[value_col].rename(name).reindex(grid.index)


def window_sum(grid: pd.DataFrame, events: pd.DataFrame, value_col: str | None, days: int, name: str) -> pd.Series:
    """Sum (or count) of events with knowable_at in (t - days, t] per company."""
    if events.empty:
        return pd.Series(0.0, index=grid.index, name=name)
    ev = events.dropna(subset=["k"]).copy()
    ev["k"] = pd.to_datetime(ev["k"], utc=True).dt.tz_convert(None)
    ev = ev.sort_values("k")
    out = np.zeros(len(grid))
    by = {c: (g["k"].to_numpy(), g[value_col].to_numpy() if value_col else None) for c, g in ev.groupby("cik")}
    tt = pd.to_datetime(grid["t"], utc=True).dt.tz_convert(None).to_numpy()
    for i, (cik, t) in enumerate(zip(grid["cik"].to_numpy(), tt)):
        g = by.get(cik)
        if g is None:
            continue
        k, vals = g
        lo, hi = np.searchsorted(k, t - np.timedelta64(days, "D"), side="right"), np.searchsorted(k, t, side="right")
        if hi > lo:
            out[i] = vals[lo:hi].sum() if value_col else hi - lo
    return pd.Series(out, index=grid.index, name=name)


def inst_features(con, grid: pd.DataFrame) -> pd.DataFrame:
    """13F ownership at each month-end t (ddb.db.build_13f), point in time.

    Q = the latest quarter-end whose 45-day filing deadline had passed by t, and only
    filings public by t count.
    - inst_breadth_chg: change in the number of 13F filers holding the stock from
      the quarter before Q to Q, divided by the number of 13F filers in Q
      (Chen, Hong and Stein 2002: rising breadth predicts higher returns);
    - inst_own: shares held by 13F filers in Q / shares outstanding.
    """
    out = pd.DataFrame(index=grid.index, columns=["inst_breadth_chg", "inst_own", "inst_holders"], dtype=float)
    try:
        con.execute("SELECT 1 FROM inst_holdings LIMIT 1")
    except Exception:  # noqa: BLE001 - 13F not loaded
        return out
    for d, g in grid.groupby("d"):
        cut = pd.Timestamp(d) - pd.Timedelta(days=46)
        q = (cut.to_period("Q") - (0 if cut == cut.to_period("Q").end_time.normalize() else 1)).end_time.normalize()
        q0 = (q.to_period("Q") - 1).end_time.normalize()
        t = (pd.Timestamp(d) + pd.Timedelta(hours=21, minutes=30)).tz_localize("UTC").isoformat()
        h = con.execute(f"""
            SELECT cik, CAST(period AS DATE) AS p, count(DISTINCT filer_cik) AS holders, sum(shares) AS shares
            FROM inst_holdings
            WHERE CAST(period AS DATE) IN (DATE '{q.date()}', DATE '{q0.date()}') AND shares > 0
              AND knowable_at <= TIMESTAMPTZ '{t}'
            GROUP BY 1, 2""").df()
        if h.empty:
            continue
        nf, nf0 = con.execute(f"""SELECT count(DISTINCT filer_cik) FILTER (WHERE CAST(period AS DATE) = DATE '{q.date()}'),
                                         count(DISTINCT filer_cik) FILTER (WHERE CAST(period AS DATE) = DATE '{q0.date()}')
                                  FROM inst_filers WHERE knowable_at <= TIMESTAMPTZ '{t}'""").fetchone()
        h["p"] = pd.to_datetime(h["p"])
        now = h[h["p"] == q].set_index("cik")
        before = h[h["p"] == q0].set_index("cik")
        ciks = g["cik"]
        hn = now["holders"].reindex(ciks).fillna(0).to_numpy()
        hb = before["holders"].reindex(ciks).fillna(0).to_numpy()
        has = (now["holders"].reindex(ciks).notna() | before["holders"].reindex(ciks).notna()).to_numpy()
        out.loc[g.index, "inst_breadth_chg"] = np.where(has & ((nf or 0) > 0) & ((nf0 or 0) > 0), (hn - hb) / max(nf or 1, 1), np.nan)
        out.loc[g.index, "inst_holders"] = np.where(has, hn, np.nan)
        out.loc[g.index, "inst_own"] = now["shares"].reindex(ciks).to_numpy() / g["shares"].to_numpy()
    out["inst_own"] = out["inst_own"].clip(upper=2.0)
    return out


def optional(con, sql: str, cols: list[str]) -> pd.DataFrame:
    """Rows from an optional source; an empty frame if its table isn't loaded."""
    try:
        return con.execute(sql).df()
    except Exception as exc:  # noqa: BLE001 - CatalogException / missing Parquet files
        print(f"  optional source missing ({str(exc).splitlines()[0][:90]}); its signals stay empty", flush=True)
        return pd.DataFrame(columns=cols)


# ------------------------------------------------------------------ build
def build(start: str = "2011-01", db_path=DB_PATH) -> dict:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect(db_path, read_only=True)
    print("prices ...", flush=True)
    close, close_raw, vol_raw = load_prices(con)
    cal = close.index
    ret = close.pct_change(fill_method=None)
    dollar_vol = close_raw * vol_raw

    months = []
    for m in pd.period_range(start, (cal[-1] - pd.offsets.MonthEnd(0)).to_period("M"), freq="M"):
        d = cal[cal <= m.end_time]
        if len(d) and (len(months) == 0 or d[-1] != months[-1]):
            months.append(d[-1])
    print(f"universe over {len(months)} months ...", flush=True)
    uni = universe_by_month(con, months)
    first_px = close.apply(lambda s: s.first_valid_index())
    uni = uni[uni["cik"].isin(close.columns)]
    uni = uni[uni["cik"].map(first_px) <= uni["d"]]          # only companies already trading at d
    uni["t"] = (uni["d"] + pd.Timedelta(hours=21, minutes=30)).dt.tz_localize("UTC")
    grid = uni.reset_index(drop=True)

    # ---- price signals (vectorized on daily frames, sampled at month ends)
    print("price signals ...", flush=True)
    mkt = ret.median(axis=1)                    # robust "market": cross-sectional median return (mean is dragged by microcap outliers)
    resid = ret.sub(mkt, axis=0)
    feats = {
        "mom_12_1": close.shift(21) / close.shift(252) - 1,
        "rev_1m": close / close.shift(21) - 1,
        "high_52w": close / close.rolling(252, min_periods=200).max(),
        "vol_60d": ret.rolling(60, min_periods=40).std(),
        "max_ret_21d": ret.rolling(21, min_periods=15).max(),
        "amihud": (ret.abs() / dollar_vol.replace(0, np.nan)).rolling(60, min_periods=40).mean() * 1e6,
        "dollar_vol_20d": dollar_vol.rolling(20, min_periods=10).mean(),
        "price_raw": close_raw.ffill(limit=5),
        # residual momentum: sum of market-adjusted returns t-252..t-21, scaled by their volatility
        "resid_mom": (resid.shift(21).rolling(231, min_periods=180).sum()
                      / resid.shift(21).rolling(231, min_periods=180).std()),
        "fwd_1m": close.shift(-21) / close - 1,
        "fwd_3m": close.shift(-63) / close - 1,
    }
    # same-calendar-month seasonality: at month t, the average return of calendar month t+1
    # in each of the prior 5 years (months t+1-12k), needing at least 2 years.
    mret = close.resample("ME").last().pct_change(fill_method=None)
    lagged = [mret.shift(12 * k - 1) for k in range(1, 6)]
    cnt = sum(x.notna().astype(int) for x in lagged)
    seas = sum(x.fillna(0) for x in lagged) / cnt.where(cnt >= 2)
    sel = pd.Index(months)
    cols = {}
    for name, frame in feats.items():
        sub = frame.reindex(sel)
        s = sub.stack(future_stack=True).rename(name)
        cols[name] = s
    long = pd.concat(cols.values(), axis=1)
    long.index.names = ["d", "cik"]
    grid = grid.merge(long.reset_index(), on=["d", "cik"], how="left")
    seas_l = seas.copy()
    seas_l.index = seas_l.index.to_period("M")
    grid["seasonality"] = [seas_l.at[p, c] if (p in seas_l.index and c in seas_l.columns) else np.nan
                           for p, c in zip(grid["d"].dt.to_period("M"), grid["cik"])]

    # forward returns: delisting adjustment for failure exits
    last_valid = close.apply(lambda s: s.last_valid_index())
    outcomes = con.execute("""SELECT cik, arg_min(outcome, CASE method WHEN 'research' THEN 0 ELSE 1 END) AS outcome
                              FROM outcomes GROUP BY 1""").df().set_index("cik")["outcome"]
    pos = {d: i for i, d in enumerate(cal)}
    for h, col in ((21, "fwd_1m"), (63, "fwd_3m")):
        miss = grid[col].isna()
        for i in grid.index[miss]:
            cik, d = grid.at[i, "cik"], grid.at[i, "d"]
            lv = last_valid.get(cik)
            if lv is None or pd.isna(lv) or lv <= d:
                continue
            j = pos.get(d)
            if j is None or j + h < len(cal) and cal[j + h] < lv:
                continue
            if j + h >= len(cal):           # window not finished yet
                continue
            r = close.at[lv, cik] / close.at[d, cik] - 1
            if outcomes.get(cik) in FAIL_OUTCOMES:
                r = (1 + r) * (1 + DELIST_RET) - 1
            grid.at[i, col] = r
    grid["fwd_1m_excess"] = grid["fwd_1m"] - grid.groupby("d")["fwd_1m"].transform("mean")

    # ---- fundamentals
    print("fundamentals ...", flush=True)
    inst = first_versions(con, ["Assets", "StockholdersEquity", "CashAndCashEquivalentsAtCarryingValue",
                                "EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"], annual=False)
    ann = first_versions(con, ["GrossProfit", *REVENUE, *COGS, "NetIncomeLoss",
                               "NetCashProvidedByUsedInOperatingActivities"], annual=True)
    pick = lambda df, c: df[df["concept"] == c]
    grid["assets"] = asof(grid, pick(inst, "Assets"), "value", "assets", 550)
    grid["equity"] = asof(grid, pick(inst, "StockholdersEquity"), "value", "equity", 550)
    grid["cash"] = asof(grid, pick(inst, "CashAndCashEquivalentsAtCarryingValue"), "value", "cash", 550)
    sh = prefer([pick(inst, "EntityCommonStockSharesOutstanding"), pick(inst, "CommonStockSharesOutstanding")],
                ["cik", "known"], latest_period=True)
    grid["shares"] = asof(grid, sh, "value", "shares", 400)
    grid12 = grid[["cik", "t"]].copy()
    grid12["t"] = grid12["t"] - pd.Timedelta(days=365)
    grid["shares_12m_ago"] = asof(grid12, sh, "value", "s12", 400)
    grid["assets_12m_ago"] = asof(grid12, pick(inst, "Assets"), "value", "a12", 550)
    rev = prefer([pick(ann, c) for c in REVENUE], ["cik", "period_end"])   # earliest known; ties by preference
    grid["revenue"] = asof(grid, rev, "value", "revenue", 550)
    gp = pick(ann, "GrossProfit")
    cogs = prefer([pick(ann, c) for c in COGS], ["cik", "period_end"])
    gp2 = rev.merge(cogs[["cik", "period_end", "value", "known"]], on=["cik", "period_end"], suffixes=("_r", "_c"))
    gp2 = pd.DataFrame({"cik": gp2["cik"], "period_end": gp2["period_end"], "value": gp2["value_r"] - gp2["value_c"],
                        "known": gp2[["known_r", "known_c"]].max(axis=1)})
    gp_all = prefer([gp, gp2], ["cik", "period_end"])
    grid["gross_profit"] = asof(grid, gp_all, "value", "gp", 550)
    grid["net_income"] = asof(grid, pick(ann, "NetIncomeLoss"), "value", "ni", 550)
    grid["op_cf"] = asof(grid, pick(ann, "NetCashProvidedByUsedInOperatingActivities"), "value", "ocf", 550)

    grid["mcap"] = grid["price_raw"] * grid["shares"]
    grid.loc[grid["mcap"] <= 0, "mcap"] = np.nan
    grid["size"] = np.log(grid["mcap"])
    grid["book_to_market"] = grid["equity"] / grid["mcap"]
    grid["sales_to_price"] = grid["revenue"] / grid["mcap"]
    grid["gross_prof"] = grid["gross_profit"] / grid["assets"]
    grid["op_cf_assets"] = grid["op_cf"] / grid["assets"]
    grid["asset_growth"] = grid["assets"] / grid["assets_12m_ago"] - 1
    grid["accruals"] = (grid["net_income"] - grid["op_cf"]) / grid["assets"]
    grid["net_issuance"] = grid["shares"] / grid["shares_12m_ago"] - 1
    burn = (-grid["op_cf"]).where(grid["op_cf"] < 0)
    grid["cash_runway"] = np.where(grid["op_cf"] >= 0, 10.0, (grid["cash"] / burn).clip(upper=10.0))
    grid.loc[grid["op_cf"].isna() | grid["cash"].isna(), "cash_runway"] = np.nan

    # ---- earnings surprise (seasonal random walk on quarterly diluted/basic EPS)
    print("earnings signals ...", flush=True)
    q = con.execute("""
        SELECT cik, period_end, datediff('day', period_start, period_end) AS dur,
               arg_min(value, (knowable_at, concept <> 'EarningsPerShareDiluted', value)) AS eps, min(knowable_at) AS known
        FROM fundamentals
        WHERE concept IN ('EarningsPerShareDiluted', 'EarningsPerShareBasic') AND unit = 'USD/shares'
          AND datediff('day', period_start, period_end) BETWEEN 75 AND 380
        GROUP BY 1, 2, 3
    """).df()
    q["period_end"] = pd.to_datetime(q["period_end"])
    qtr = q[q["dur"].between(75, 105)].sort_values(["known", "dur", "eps"], kind="stable").drop_duplicates(["cik", "period_end"])
    fy = q[q["dur"].between(350, 380)]
    ytd9 = q[q["dur"].between(260, 285)]
    q4 = fy.merge(ytd9, on="cik", suffixes=("", "_9"))
    q4 = q4[(q4["period_end"] - q4["period_end_9"]).dt.days.between(80, 100)]
    q4 = pd.DataFrame({"cik": q4["cik"], "period_end": q4["period_end"], "eps": q4["eps"] - q4["eps_9"],
                       "known": q4[["known", "known_9"]].max(axis=1)})
    allq = prefer([qtr[["cik", "period_end", "eps", "known"]], q4], ["cik", "period_end"])
    rows = []
    for cik, g in allq.groupby("cik"):
        g = g.sort_values(["known", "period_end"], kind="stable").reset_index(drop=True)
        for i in range(len(g)):
            # everything this company had published by the time quarter i came out
            h = g[g["known"] <= g.at[i, "known"]].sort_values("period_end").reset_index(drop=True)
            if h["period_end"].iloc[-1] != g.at[i, "period_end"]:
                continue                                    # a late, older quarter: not a new surprise
            pe = h["period_end"].to_numpy()
            ch = []
            for k in range(len(h)):
                prev = np.where(np.abs((pe[k] - pe[:k]).astype("timedelta64[D]").astype(int) - 365) <= 20)[0]
                if len(prev):
                    ch.append(h.at[k, "eps"] - h.at[prev[-1], "eps"])
            if ch and len(pe) > 1 and np.any(np.abs((pe[-1] - pe[:-1]).astype("timedelta64[D]").astype(int) - 365) <= 20):
                hist = ch[-9:-1]
                if len(hist) >= 4 and np.std(hist) > 0:
                    rows.append((cik, g.at[i, "known"], ch[-1] / np.std(hist)))
    sue = pd.DataFrame(rows, columns=["cik", "known", "sue"])
    grid["sue"] = asof(grid, sue, "sue", "sue", 120)

    # earnings-day return around the latest results 8-K (item 2.02)
    ea = con.execute("""SELECT cik, acceptance FROM filings WHERE form LIKE '8-K%' AND items LIKE '%2.02%'
                        AND acceptance IS NOT NULL AND filing_date >= DATE '2010-01-01'""").df()
    ea["acceptance"] = pd.to_datetime(ea["acceptance"], utc=True)
    et = ea["acceptance"].dt.tz_convert("America/New_York")
    d0 = et.dt.tz_localize(None).dt.normalize() + pd.to_timedelta((et.dt.hour >= 16).astype(int), unit="D")
    ea["i0"] = cal.searchsorted(d0)
    ex = ret.sub(mkt, axis=0)
    ex_np, col_pos = ex.to_numpy(), {c: j for j, c in enumerate(ex.columns)}
    vals = []
    for cik, i0 in zip(ea["cik"], ea["i0"]):
        j = col_pos.get(cik)
        if j is None or i0 < 1 or i0 + 1 >= len(cal):
            vals.append((np.nan, pd.NaT))
            continue
        w = ex_np[i0 - 1:i0 + 2, j]
        vals.append((np.nansum(w) if np.isfinite(w).sum() >= 2 else np.nan,
                     pd.Timestamp(cal[i0 + 1]).tz_localize("UTC") + pd.Timedelta(hours=21)))
    ea["ear"], ea["known"] = zip(*vals) if vals else ([], [])
    grid["ear"] = asof(grid, ea.dropna(subset=["ear", "known"]), "ear", "ear", 100)

    # ---- events
    print("events ...", flush=True)
    ev = con.execute("SELECT cik, event_type, knowable_at AS k FROM events WHERE event_date >= DATE '2009-01-01'").df()
    grid["offerings_12m"] = window_sum(grid, ev[ev["event_type"].isin(["shelf_registration", "offering_prospectus"])], None, 365, "o")
    grid["late_filings_12m"] = window_sum(grid, ev[ev["event_type"].isin(["late_annual_report", "late_quarterly_report"])], None, 365, "l")
    fts = optional(con, "SELECT cik, phrase, signal, knowable_at AS k FROM filing_text_signals", ["cik", "phrase", "signal", "k"])
    grid["going_concern"] = window_sum(grid, fts[fts["phrase"].str.contains("going concern")], None, 365, "gc")
    grid["bottleneck_1y"] = window_sum(grid, fts[fts["signal"] == "bottleneck"], None, 365, "b")

    # ---- insiders (Cohen-Malloy-Pomorski: routine = traded in the same calendar month in each of the 3 prior years)
    print("insiders ...", flush=True)
    it = con.execute("""
        SELECT cik, owner_cik, trans_date, knowable_at AS k, trans_code, shares * price AS value,
               coalesce(is_10b5_1_plan, FALSE) AS plan, relationship
        FROM insider_transactions
        WHERE NOT is_derivative AND trans_code IN ('P', 'S') AND NOT trans_date_suspect
          AND coalesce(shares * price, 0) BETWEEN 1 AND 2e9
    """).df()
    it["trans_date"] = pd.to_datetime(it["trans_date"])
    it["ym"] = it["trans_date"].dt.year * 100 + it["trans_date"].dt.month
    months_traded = it.groupby(["cik", "owner_cik"])["ym"].agg(set)
    def routine(r):
        s = months_traded.get((r.cik, r.owner_cik), set())
        y, mth = divmod(r.ym, 100)
        return all(((y - k) * 100 + mth) in s for k in (1, 2, 3))
    it["routine"] = [routine(r) for r in it.itertuples(index=False)]
    opp = it[~it["routine"] & ~it["plan"]].copy()
    opp["signed"] = np.where(opp["trans_code"] == "P", opp["value"], -opp["value"])
    grid["insider_opp_net"] = window_sum(grid, opp, "signed", 90, "io") / grid["mcap"]
    buys = opp[opp["trans_code"] == "P"].drop_duplicates(["cik", "owner_cik", "k"])
    grid["insider_buyers"] = window_sum(grid, buys, None, 90, "ib")

    # ---- alternative data
    print("alternative data ...", flush=True)
    tmap = ticker_cik(con)
    pol = optional(con, "SELECT upper(ticker) AS ticker, transaction_type, knowable_at AS k FROM politician_trades",
                   ["ticker", "transaction_type", "k"])
    pol = attach_cik(pol, tmap, "k") if len(pol) else pol.assign(cik=pd.Series(dtype=float))
    pol["signed"] = np.where(pol["transaction_type"] == "buy", 1.0, -1.0)
    grid["congress_net"] = window_sum(grid, pol, "signed", 180, "cn")
    gc = optional(con, "SELECT cik, amount, knowable_at AS k FROM gov_contracts", ["cik", "amount", "k"])
    grid["contracts_rev"] = window_sum(grid, gc, "amount", 365, "gc") / grid["revenue"].where(grid["revenue"] > 0)
    nw = optional(con, "SELECT unnest(ciks) AS cik, tone, knowable_at AS k FROM news_events WHERE len(ciks) > 0",
                  ["cik", "tone", "k"])
    if len(nw):
        nw["one"] = 1.0
        n30 = window_sum(grid, nw, "one", 30, "n")
        grid["news_volume"] = np.log1p(n30)
        grid["news_tone"] = window_sum(grid, nw.dropna(subset=["tone"]), "tone", 30, "t") / n30.replace(0, np.nan)
        cover_start = nw["k"].min()
        grid.loc[grid["t"] < cover_start + pd.Timedelta(days=30), ["news_volume", "news_tone"]] = np.nan
    else:
        grid["news_volume"] = grid["news_tone"] = np.nan
    import glob
    wsrc = "data/db/wiki_pageviews/*.parquet" if glob.glob("data/db/wiki_pageviews/*.parquet") else "data/db/wiki_pageviews/parts/*.parquet"
    try:   # the loader may still be running: fall back to its checkpoint files
        wk = con.execute(f"SELECT cik, views, CAST(date AS TIMESTAMPTZ) + INTERVAL 1 DAY AS k FROM read_parquet('{wsrc}', union_by_name=true) "
                         "WHERE entity_type = 'company' AND views IS NOT NULL").df()
        wk = wk.dropna(subset=["cik"])
    except Exception:  # noqa: BLE001
        wk = pd.DataFrame()
    if len(wk):
        v30 = window_sum(grid, wk, "views", 30, "w30")
        v180 = window_sum(grid, wk, "views", 210, "w210") - v30
        grid["wiki_attention"] = np.log1p(v30 / 30) - np.log1p(v180 / 180)
        has = grid["cik"].isin(set(wk["cik"].dropna().astype(int)))
        grid.loc[~has, "wiki_attention"] = np.nan
    else:
        grid["wiki_attention"] = np.nan

    # ---- short interest (days to cover), if loaded
    try:
        si = con.execute("""SELECT upper(symbol) AS ticker, settlement_date, days_to_cover, short_interest, knowable_at AS known
                            FROM read_parquet('data/db/short_interest/*.parquet')""").df()
        si = attach_cik(si, tmap, "settlement_date")
        # one row per company and date: the share class with the most shares short
        si = si.sort_values(["known", "short_interest", "ticker"], kind="stable").drop_duplicates(["cik", "known"], keep="last")
        grid["days_to_cover"] = asof(grid, si, "days_to_cover", "dtc", 45)
        grid["short_pct"] = asof(grid, si, "short_interest", "si", 45) / grid["shares"]
    except Exception as exc:  # noqa: BLE001
        print("short interest not loaded:", exc)
        grid["days_to_cover"] = grid["short_pct"] = np.nan

    # ---- institutional ownership (13F), if loaded
    print("institutional ownership ...", flush=True)
    grid[["inst_breadth_chg", "inst_own", "inst_holders"]] = inst_features(con, grid)

    # industry momentum: equal-weight mean of mom_12_1 within industry at t
    grid["ind_mom"] = grid.groupby(["d", "industry"])["mom_12_1"].transform("mean")
    con.close()
    grid.to_parquet(OUT / "panel.parquet", index=False)
    return {"rows": len(grid), "months": grid["d"].nunique(), "companies": grid["cik"].nunique(),
            "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
