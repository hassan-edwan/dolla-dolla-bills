"""Investment screens (configs/screens.yaml): Israel, weapons, Sharia business, Sharia ratios.

Tables written:
  screen_static            (cik, screen, status, reasons, valid_from, knowable_at)
      israel / weapons / sharia_business: identity-based. Note SIC is the CURRENT code.
  screen_dod_share         (cik, year, dod_obligations, revenue, share, knowable_at)
      DoD contract obligations / revenue per calendar year, knowable after both
      the 10-K and the 90-day DoD release delay.
  screen_sharia_financial  (cik, as_of, market_cap_avg, debt, cash_securities,
                            interest_income, revenue, ratios..., status, knowable_at)
      quarterly, using only facts with knowable_at <= as_of.

AsOf.tradable(t) combines them: a company is tradable at t only if every screen passes.

    python -m ddb.db.build_screens
"""
from __future__ import annotations

import re
import time

import pandas as pd
import yaml

from ..config import CONFIG_DIR, DATA_DIR
from .schema import connect

DB_PATH = DATA_DIR / "ddb.duckdb"
ADDR = DATA_DIR / "db" / "company_addresses.parquet"


def _in_ranges(sic, ranges) -> bool:
    if sic is None or pd.isna(sic):
        return False
    for r in ranges:
        lo, hi = (r if isinstance(r, list) else (r, r))
        if lo <= int(sic) <= hi:
            return True
    return False


def _kw(name: str, kws) -> list[str]:
    n = " " + re.sub(r"[^a-z0-9]+", " ", str(name).lower()) + " "
    return [k.strip() for k in kws if re.search(r"(?<![a-z0-9])" + re.escape(k.strip().lower())
                                                 + (r"(?![a-z0-9])" if k.endswith(" ") else ""), n)]


def static_screens(con, cfg) -> pd.DataFrame:
    comp = con.execute("SELECT cik, name, sic, first_filing FROM companies").df()
    names = con.execute("SELECT cik, list(DISTINCT name) AS names FROM company_names GROUP BY 1").df()
    comp = comp.merge(names, on="cik", how="left")
    addr = pd.read_parquet(ADDR)
    comp = comp.merge(addr, on="cik", how="left")
    tick = con.execute("SELECT upper(ticker) AS t, cik FROM tickers").df()
    t2c = tick.groupby("t")["cik"].agg(set).to_dict()
    crypto = set(con.execute("SELECT DISTINCT cik FROM company_industries WHERE industry='crypto_adj'").df()["cik"])

    def manual(section):
        out = {}
        for t, why in (cfg[section].get("manual_fail") or {}).items():
            for c in t2c.get(t.upper(), []):
                out[c] = why
        return out

    man_w, man_i = manual("weapons"), manual("israel")
    w, sb, isr = cfg["weapons"], cfg["sharia_business"], cfg["israel"]
    rows = []
    for r in comp.itertuples(index=False):
        all_names = list(r.names) if isinstance(r.names, (list, tuple)) or hasattr(r.names, "__len__") else [r.name]
        start = pd.Timestamp(r.first_filing).tz_localize("UTC") if pd.notna(r.first_filing) else None
        # Israel
        code = isr["edgar_code"]
        hits = [f"{k}={v}" for k, v in (("incorporated", r.state_of_inc), ("business address", r.business_country_code),
                                        ("mailing address", r.mailing_country_code)) if v == code]
        if not hits and "ISRAEL" in str(r.business_city or "").upper():
            hits.append(f"business city '{r.business_city}'")
        if r.cik in man_i:
            hits.append(man_i[r.cik])
        rows.append((r.cik, "israel", "fail" if hits else "pass", "; ".join(hits)))
        # Weapons
        reasons, status = [], "pass"
        if r.cik in man_w:
            txt = man_w[r.cik]
            status = "review" if txt.startswith("REVIEW") else "fail"
            reasons.append(txt)
        if _in_ranges(r.sic, w["fail_sic"]):
            status, _ = "fail", reasons.append(f"SIC {r.sic}")
        elif _in_ranges(r.sic, w["review_sic"]) and status == "pass":
            status, _ = "review", reasons.append(f"SIC {r.sic} (mixed civilian/military)")
        for n in all_names:
            f = _kw(n, w["fail_name_keywords"])
            if f:
                status = "fail"
                reasons.append(f"name '{n}': {f}")
            elif status == "pass" and _kw(n, w["review_name_keywords"]):
                status = "review"
                reasons.append(f"name '{n}'")
        rows.append((r.cik, "weapons", status, "; ".join(reasons)))
        # Sharia business activity
        reasons, status = [], "pass"
        if _in_ranges(r.sic, sb["fail_sic"]) and not _in_ranges(r.sic, [[x, x] for x in sb["review_sic"]]):
            status = "fail"
            reasons.append(f"SIC {r.sic}")
        elif _in_ranges(r.sic, [[x, x] for x in sb["review_sic"]]):
            status = "review"
            reasons.append(f"SIC {r.sic}")
        for n in all_names:
            f = _kw(n, sb["fail_name_keywords"])
            if f:
                status = "fail"
                reasons.append(f"name '{n}': {f}")
        if r.cik in crypto and status == "pass":
            status = "review"
            reasons.append("crypto industry (scholarly opinion differs; see screens.yaml decisions)")
        rows.append((r.cik, "sharia_business", status, "; ".join(reasons)))
    df = pd.DataFrame(rows, columns=["cik", "screen", "status", "reasons"])
    df = df.merge(comp[["cik", "first_filing"]], on="cik")
    df["valid_from"] = pd.to_datetime(df.pop("first_filing"))
    df["knowable_at"] = df["valid_from"].dt.tz_localize("UTC")
    return df


DEBT = ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
        "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "ConvertibleNotesPayable", "ConvertibleNotesPayableCurrent", "NotesPayable", "CommercialPaper"]
CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]
INCOME = ["InvestmentIncomeInterest", "InvestmentIncomeInterestAndDividend", "InterestIncomeOther",
          "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
          "RevenueFromContractWithCustomerIncludingAssessedTax"]
SHARES = ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding",
          "WeightedAverageNumberOfDilutedSharesOutstanding"]
# IFRS filers (20-F / 40-F)
IFRS = ["Borrowings", "CurrentBorrowings", "NoncurrentPortionOfNoncurrentBorrowings", "CashAndCashEquivalents",
        "CurrentInvestments", "Revenue", "InterestRevenueCalculatedUsingEffectiveInterestMethod", "FinanceIncome"]


def sharia_financial(con, cfg) -> pd.DataFrame:
    f = cfg["sharia_financial"]
    concepts = ",".join(f"'{c}'" for c in DEBT + CASH + INCOME + SHARES + IFRS)
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sf_facts AS
        SELECT cik, concept, value, period_start, period_end, knowable_at,
               datediff('day', period_start, period_end) AS dur
        FROM fundamentals
        WHERE concept IN ({concepts}) AND unit IN ('USD', 'shares') AND value IS NOT NULL
    """)
    # Quarter-end evaluation grid per company (2010+ to now)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE sf_grid AS
        SELECT c.cik, CAST(q AS DATE) AS as_of
        FROM (SELECT DISTINCT cik FROM sf_facts) c,
             generate_series(TIMESTAMP '2010-03-31', CAST(current_date AS TIMESTAMP), INTERVAL 3 MONTH) g(q)
    """)
    con.execute("UPDATE sf_grid SET as_of = last_day(as_of)")
    # Latest known value per concept at each as_of (instant items: newest period; income: last ~annual period)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE sf_latest AS
        SELECT g.cik, g.as_of, f.concept, f.value
        FROM sf_grid g JOIN sf_facts f
          ON f.cik = g.cik AND f.knowable_at <= CAST(g.as_of AS TIMESTAMPTZ) + INTERVAL 1 DAY
         AND f.period_end >= g.as_of - INTERVAL 18 MONTH
         AND (f.period_start IS NULL OR f.dur BETWEEN 350 AND 380 OR f.concept NOT IN
              ('InvestmentIncomeInterest','InvestmentIncomeInterestAndDividend','InterestIncomeOther','Revenues',
               'RevenueFromContractWithCustomerExcludingAssessedTax','SalesRevenueNet',
               'RevenueFromContractWithCustomerIncludingAssessedTax','Revenue',
               'InterestRevenueCalculatedUsingEffectiveInterestMethod','FinanceIncome',
               'WeightedAverageNumberOfDilutedSharesOutstanding'))
        QUALIFY row_number() OVER (PARTITION BY g.cik, g.as_of, f.concept
                                   ORDER BY f.period_end DESC, f.knowable_at DESC) = 1
    """)
    wide = con.execute("SELECT * FROM sf_latest").df().pivot_table(
        index=["cik", "as_of"], columns="concept", values="value", aggfunc="first").reset_index()
    g = lambda c: wide[c] if c in wide else pd.Series(float("nan"), index=wide.index)
    lt = g("LongTermDebt").fillna(g("LongTermDebtNoncurrent") + g("LongTermDebtCurrent").fillna(0))
    lt = lt.fillna(g("LongTermDebtAndCapitalLeaseObligations") + g("LongTermDebtAndCapitalLeaseObligationsCurrent").fillna(0))
    lt = lt.fillna(g("ConvertibleNotesPayable").fillna(0) + g("ConvertibleNotesPayableCurrent").fillna(0) + g("NotesPayable").fillna(0))
    ifrs_debt = g("Borrowings").fillna(g("NoncurrentPortionOfNoncurrentBorrowings") + g("CurrentBorrowings").fillna(0))
    lt = lt.fillna(ifrs_debt)
    wide["debt"] = lt.fillna(0) + g("ShortTermBorrowings").fillna(0) + g("CommercialPaper").fillna(0) + g("DebtCurrent").where(g("LongTermDebtCurrent").isna(), 0).fillna(0)
    cash = g("CashAndCashEquivalentsAtCarryingValue").fillna(g("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")).fillna(g("CashAndCashEquivalents"))
    wide["cash_securities"] = cash + g("ShortTermInvestments").fillna(g("MarketableSecuritiesCurrent")).fillna(
        g("AvailableForSaleSecuritiesDebtSecuritiesCurrent")).fillna(g("CurrentInvestments")).fillna(0)
    wide["interest_income"] = (g("InvestmentIncomeInterest").fillna(g("InvestmentIncomeInterestAndDividend"))
                               .fillna(g("InterestIncomeOther")).fillna(g("InterestRevenueCalculatedUsingEffectiveInterestMethod"))
                               .fillna(g("FinanceIncome")).fillna(0))
    wide["revenue"] = g("Revenues").fillna(g("RevenueFromContractWithCustomerExcludingAssessedTax")).fillna(
        g("SalesRevenueNet")).fillna(g("RevenueFromContractWithCustomerIncludingAssessedTax")).fillna(g("Revenue"))
    wide["shares"] = (g("EntityCommonStockSharesOutstanding").fillna(g("CommonStockSharesOutstanding"))
                      .fillna(g("WeightedAverageNumberOfDilutedSharesOutstanding")))

    # Monthly market cap = as-traded close x shares known at that month end
    px = con.execute("""
        WITH m AS (
            SELECT p.cik AS pcik, upper(p.symbol) AS sym, last_day(p.date) AS month,
                   arg_max(p.close_raw, p.date) AS close_raw
            FROM prices p WHERE p.close_raw IS NOT NULL GROUP BY 1, 2, 3
        )
        SELECT COALESCE(m.pcik, t.cik) AS cik, m.month, avg(m.close_raw) AS close_raw
        FROM m LEFT JOIN (SELECT DISTINCT upper(ticker) AS sym, cik FROM tickers
                          WHERE source IN ('sec_current', 'research')) t
          ON m.pcik IS NULL AND t.sym = m.sym
        WHERE COALESCE(m.pcik, t.cik) IS NOT NULL
        GROUP BY 1, 2
    """).df()
    sh = wide[["cik", "as_of", "shares"]].dropna().sort_values("as_of")
    px = px.sort_values("month")
    px["month"] = pd.to_datetime(px["month"])
    sh["as_of"] = pd.to_datetime(sh["as_of"])
    mc = pd.merge_asof(px, sh.rename(columns={"as_of": "month"}), on="month", by="cik", direction="backward")
    mc["mcap"] = mc["close_raw"] * mc["shares"]
    mc = mc.dropna(subset=["mcap"]).sort_values(["cik", "month"])
    win = int(f["market_cap_window_months"])
    mc["mcap_avg"] = mc.groupby("cik")["mcap"].transform(lambda s: s.rolling(win, min_periods=int(f["min_months_of_price_history"])).mean())
    wide["as_of"] = pd.to_datetime(wide["as_of"])
    wide = pd.merge_asof(wide.sort_values("as_of"), mc[["cik", "month", "mcap_avg"]].rename(columns={"month": "as_of"}).sort_values("as_of"),
                         on="as_of", by="cik", direction="backward", tolerance=pd.Timedelta(days=40))
    wide["debt_ratio"] = wide["debt"] / wide["mcap_avg"]
    wide["cash_ratio"] = wide["cash_securities"] / wide["mcap_avg"]
    total_income = wide["revenue"].fillna(0) + wide["interest_income"]
    wide["impermissible_share"] = wide["interest_income"] / total_income.where(total_income > 0)
    ok = ((wide["debt_ratio"] <= f["max_debt_to_market_cap"])
          & (wide["cash_ratio"] <= f["max_cash_and_interest_securities_to_market_cap"])
          & (wide["impermissible_share"].fillna(0) <= f["max_impermissible_income_share"]))
    known = wide["mcap_avg"].notna() & wide["cash_securities"].notna()
    wide["status"] = "unknown"
    wide.loc[known & ok, "status"] = "pass"
    wide.loc[known & ~ok, "status"] = "fail"
    # Pre-revenue companies whose only income is interest on cash: scholars/screeners
    # treat this as doubtful (purification), not an automatic fail, if the other ratios pass.
    pre_rev = (wide["revenue"].fillna(0) <= 0) & (wide["interest_income"] > 0)
    ratios_ok = ((wide["debt_ratio"] <= f["max_debt_to_market_cap"])
                 & (wide["cash_ratio"] <= f["max_cash_and_interest_securities_to_market_cap"]))
    wide.loc[known & pre_rev & ratios_ok, "status"] = "review"
    wide["knowable_at"] = (wide["as_of"] + pd.Timedelta(days=1)).dt.tz_localize("UTC")
    cols = ["cik", "as_of", "mcap_avg", "debt", "cash_securities", "interest_income", "revenue",
            "debt_ratio", "cash_ratio", "impermissible_share", "status", "knowable_at"]
    return wide[cols].rename(columns={"mcap_avg": "market_cap_avg"})


def dod_share(con) -> pd.DataFrame:
    try:
        return con.execute("""
            WITH dod AS (
                SELECT cik, year(action_date) AS year, sum(amount) AS dod_obligations
                FROM gov_contracts WHERE agency ILIKE '%Department of Defense%' GROUP BY 1, 2
            ), rev AS (
                SELECT cik, year(period_end) AS year, arg_max(value, knowable_at) AS revenue,
                       min(knowable_at) AS rev_known
                FROM fundamentals
                WHERE concept IN ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet')
                  AND unit = 'USD' AND datediff('day', period_start, period_end) BETWEEN 350 AND 380
                GROUP BY 1, 2
            )
            SELECT d.cik, d.year, d.dod_obligations, r.revenue, d.dod_obligations / NULLIF(r.revenue, 0) AS share,
                   greatest(r.rev_known, CAST(make_date(d.year, 12, 31) AS TIMESTAMPTZ) + INTERVAL 90 DAY) AS knowable_at
            FROM dod d JOIN rev r USING (cik, year)
        """).df()
    except Exception:  # noqa: BLE001 - contracts not loaded yet
        return pd.DataFrame(columns=["cik", "year", "dod_obligations", "revenue", "share", "knowable_at"])


def build(db_path=DB_PATH) -> dict:
    t0 = time.time()
    cfg = yaml.safe_load((CONFIG_DIR / "screens.yaml").read_text())
    con = connect(db_path)
    st = static_screens(con, cfg)
    dod = dod_share(con)
    thr = cfg["weapons"]["dod_revenue_share_review"]
    heavy = dod[dod["share"] > thr]
    extra = []
    for cik, g in heavy.groupby("cik"):
        first = g.sort_values("year").iloc[0]
        extra.append((cik, "weapons_dod", "review", f"DoD obligations {first['share']:.0%} of revenue in {int(first['year'])}",
                      pd.Timestamp(first["knowable_at"]).tz_convert(None), first["knowable_at"]))
    if extra:
        st = pd.concat([st, pd.DataFrame(extra, columns=st.columns)], ignore_index=True)
    fin = sharia_financial(con, cfg)
    for name, df in (("screen_static", st), ("screen_dod_share", dod), ("screen_sharia_financial", fin)):
        con.register("x", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM x")
        con.unregister("x")
    summary = st.pivot_table(index="screen", columns="status", values="cik", aggfunc="count").fillna(0).astype(int)
    fin_s = fin["status"].value_counts().to_dict()
    con.close()
    return {"static": summary.to_dict(orient="index"), "sharia_financial_quarters": fin_s,
            "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    import json
    print(json.dumps(build(), indent=1, default=str))
