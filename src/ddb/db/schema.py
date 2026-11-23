"""Company database schema (DuckDB, single file: data/ddb.duckdb).

POINT-IN-TIME RULE: every table used for FEATURES has a ``knowable_at``
timestamp (UTC), the earliest moment the row could have been known by a
market participant. Feature code must read through ``ddb.db.pit.AsOf``,
which filters on ``knowable_at <= t``.

LABEL tables (``outcomes``) describe what happened later. They may be used
only as training targets, never as inputs, and are deliberately excluded
from the AsOf feature views.

Tables
------
companies            static identity (cik, current name/SIC). The current SIC is NOT
                     point-in-time; use company_industries for dated membership
company_names        dated name history (EDGAR formerNames)          [feature]
company_industries   dated industry tags with method + confidence    [feature]
tickers              dated ticker history                            [feature]
filings              every filing with acceptance time               [feature]
events               failure / dilution / corporate events           [feature]
fundamentals         XBRL facts, each version as filed              [feature]
prices               daily bars (knowable after the close)           [feature]
corporate_actions    splits / dividends                              [feature]
macro                market series                                   [feature]
outcomes             how a company's listing ended                   [LABEL]
research_notes       provenance for every web-researched value
research_queue       open lookups (missing tickers, outcomes, industry checks)
"""

DDL = """
CREATE TABLE IF NOT EXISTS companies (
    cik              BIGINT PRIMARY KEY,
    name             VARCHAR,
    sic              INTEGER,
    sic_description  VARCHAR,
    entity_type      VARCHAR,
    filer_category   VARCHAR,
    state_of_inc     VARCHAR,
    fiscal_year_end  VARCHAR,
    current_tickers  VARCHAR[],
    current_exchanges VARCHAR[],
    first_filing     DATE,
    last_filing      DATE,
    n_filings        INTEGER,
    n_annual_reports INTEGER,
    is_current_listed BOOLEAN,      -- has a ticker in SEC's current map (as of build)
    built_at         TIMESTAMP
);

CREATE TABLE IF NOT EXISTS company_names (
    cik         BIGINT,
    name        VARCHAR,
    valid_from  DATE,
    valid_to    DATE,               -- NULL = current
    knowable_at TIMESTAMPTZ         -- = valid_from (the rename filing date)
);

CREATE TABLE IF NOT EXISTS company_industries (
    cik          BIGINT,
    industry     VARCHAR,
    sub_industry VARCHAR,
    method       VARCHAR,           -- sic | keyword_name | manual | research
    matched      VARCHAR,           -- the SIC code or keyword that matched
    confidence   VARCHAR,           -- high | medium | low
    valid_from   DATE,
    valid_to     DATE,
    knowable_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tickers (
    cik         BIGINT,
    ticker      VARCHAR,
    exchange    VARCHAR,
    valid_from  DATE,
    valid_to    DATE,
    source      VARCHAR,            -- sec_current | xbrl_dei | research
    knowable_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS filings (
    cik          BIGINT,
    accession    VARCHAR,
    form         VARCHAR,
    filing_date  DATE,
    report_date  DATE,
    acceptance   TIMESTAMPTZ,
    items        VARCHAR,
    primary_doc  VARCHAR,
    size_bytes   BIGINT,
    knowable_at  TIMESTAMPTZ        -- acceptance time (fallback: filing_date end of day)
);

CREATE TABLE IF NOT EXISTS events (
    cik         BIGINT,
    event_type  VARCHAR,
    event_date  DATE,
    form        VARCHAR,
    accession   VARCHAR,
    knowable_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS prices (
    symbol      VARCHAR,
    date        DATE,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    adjclose    DOUBLE,
    volume      DOUBLE,
    source      VARCHAR,
    knowable_at TIMESTAMPTZ         -- 21:00 UTC on `date` (after the US close)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    symbol      VARCHAR,
    date        DATE,
    type        VARCHAR,
    value       DOUBLE,
    knowable_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS macro (
    series      VARCHAR,
    date        DATE,
    value       DOUBLE,
    source      VARCHAR,
    knowable_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS outcomes (          -- LABEL TABLE: never a feature
    cik            BIGINT,
    outcome        VARCHAR,       -- active | acquired | bankrupt | delisted_exchange | deregistered | went_private | unknown
    exit_date      DATE,
    terminal_value DOUBLE,        -- per-share value received, if known
    acquirer       VARCHAR,
    consideration  VARCHAR,
    method         VARCHAR,       -- rule | research
    confidence     VARCHAR,
    source_url     VARCHAR,
    notes          VARCHAR,
    event_known_at TIMESTAMPTZ    -- when the exit became public (for label timing)
);

CREATE TABLE IF NOT EXISTS research_notes (
    cik           BIGINT,
    field         VARCHAR,       -- ticker | outcome | terminal_value | industry | ...
    value         VARCHAR,
    as_of_date    DATE,          -- the date the fact refers to / became public
    source_url    VARCHAR,
    method        VARCHAR,       -- web_lookup | filing_read
    confidence    VARCHAR,
    retrieved_at  TIMESTAMPTZ,
    notes         VARCHAR
);

CREATE TABLE IF NOT EXISTS research_queue (
    cik       BIGINT,
    task      VARCHAR,           -- resolve_ticker | resolve_outcome | verify_industry
    priority  DOUBLE,
    status    VARCHAR,           -- open | done | unresolvable
    reason    VARCHAR,
    created_at TIMESTAMPTZ
);
"""

FEATURE_TABLES = ["company_names", "company_industries", "tickers", "filings", "events",
                  "fundamentals", "prices", "corporate_actions", "macro",
                  "insider_transactions", "politician_trades", "gov_contracts",
                  "committee_seats", "news_events", "regulatory_documents",
                  "filing_text_signals", "wiki_pageviews", "research_velocity"]
LABEL_TABLES = ["outcomes"]


FUNDAMENTALS_EMPTY = """CREATE TABLE IF NOT EXISTS fundamentals (
    cik          BIGINT,
    taxonomy     VARCHAR,           -- us-gaap | ifrs-full | dei
    concept      VARCHAR,
    unit         VARCHAR,
    value        DOUBLE,
    period_start DATE,
    period_end   DATE,
    fy           INTEGER,
    fp           VARCHAR,
    form         VARCHAR,
    accession    VARCHAR,
    filed        DATE,
    frame        VARCHAR,
    knowable_at  TIMESTAMPTZ        -- acceptance time of the reporting filing
);"""


def connect(path, read_only: bool = False):
    """Open the database. `fundamentals` is a view over Parquet files in
    <db dir>/db/fundamentals when they exist (too large for a table)."""
    from pathlib import Path

    import duckdb
    path = Path(path)
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute("SET TimeZone='UTC'")
    if read_only:
        return con
    con.execute(DDL)
    fdir = path.parent / "db" / "fundamentals"
    kind = con.execute("SELECT table_type FROM information_schema.tables "
                       "WHERE table_name = 'fundamentals'").fetchall()
    if fdir.exists() and any(fdir.glob("*.parquet")):
        if kind and kind[0][0] == "BASE TABLE":
            con.execute("DROP TABLE fundamentals")
        con.execute(f"CREATE OR REPLACE VIEW fundamentals AS "
                    f"SELECT * FROM read_parquet('{fdir.as_posix()}/*.parquet')")
    elif not kind:
        con.execute(FUNDAMENTALS_EMPTY)
    # Prices / corporate actions / fetch log are per-ticker Parquet files.
    for name, sub in (("prices", "prices"), ("corporate_actions", "corporate_actions")):
        d = path.parent / "db" / sub
        if d.exists() and any(d.glob("*.parquet")):
            k = con.execute("SELECT table_type FROM information_schema.tables "
                            f"WHERE table_name = '{name}'").fetchall()
            if k and k[0][0] == "BASE TABLE":
                con.execute(f"DROP TABLE {name}")
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM "
                        f"read_parquet('{d.as_posix()}/*.parquet', union_by_name=true)")
    # Other Parquet-backed feature tables (one directory each).
    for name in ("insider_transactions", "politician_trades", "gov_contracts",
                 "news_events", "regulatory_documents", "filing_text_signals",
                 "wiki_pageviews", "research_velocity"):
        d = path.parent / "db" / name
        if d.exists() and any(d.glob("*.parquet")):
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM "
                        f"read_parquet('{d.as_posix()}/*.parquet', union_by_name=true)")
    log = path.parent / "db" / "price_fetch_log.csv"
    if log.exists():
        k = con.execute("SELECT table_type FROM information_schema.tables "
                        "WHERE table_name = 'price_fetch_log'").fetchall()
        if k and k[0][0] == "BASE TABLE":
            con.execute("DROP TABLE price_fetch_log")
        con.execute(f"CREATE OR REPLACE VIEW price_fetch_log AS SELECT * FROM read_csv_auto('{log.as_posix()}')")
    return con
