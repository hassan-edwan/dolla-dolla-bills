"""Coverage report for the company database -> data/results/db_coverage.md"""
from ddb.config import DATA_DIR
from ddb.db.schema import connect

Q = {
    "Table sizes": """
        SELECT 'companies' t, count(*) n FROM companies UNION ALL
        SELECT 'company_names', count(*) FROM company_names UNION ALL
        SELECT 'company_industries', count(*) FROM company_industries UNION ALL
        SELECT 'tickers', count(*) FROM tickers UNION ALL
        SELECT 'filings', count(*) FROM filings UNION ALL
        SELECT 'events', count(*) FROM events UNION ALL
        SELECT 'fundamentals (fact versions)', count(*) FROM fundamentals UNION ALL
        SELECT 'prices (daily bars)', count(*) FROM prices UNION ALL
        SELECT 'macro', count(*) FROM macro UNION ALL
        SELECT 'outcomes', count(*) FROM outcomes UNION ALL
        SELECT 'research_notes', count(*) FROM research_notes UNION ALL
        SELECT 'research_queue (open)', count(*) FROM research_queue WHERE status = 'open'
    """,
    "Companies per industry (any time since 2005)": """
        SELECT ci.industry,
               count(DISTINCT ci.cik) AS companies,
               count(DISTINCT CASE WHEN c.is_current_listed THEN ci.cik END) AS listed_now,
               count(DISTINCT CASE WHEN NOT c.is_current_listed THEN ci.cik END) AS gone,
               count(DISTINCT CASE WHEN ci.confidence = 'high' THEN ci.cik END) AS high_conf,
               count(DISTINCT CASE WHEN ci.method = 'research' THEN ci.cik END) AS researched
        FROM company_industries ci JOIN companies c USING (cik)
        WHERE c.last_filing >= DATE '2005-01-01'
        GROUP BY 1 ORDER BY 2 DESC
    """,
    "How companies left (labels, best source per company)": """
        WITH best AS (
            SELECT * FROM outcomes
            QUALIFY row_number() OVER (PARTITION BY cik ORDER BY method = 'research' DESC) = 1
        )
        SELECT outcome, count(*) AS companies FROM best b JOIN companies c USING (cik)
        WHERE c.last_filing >= DATE '2005-01-01' GROUP BY 1 ORDER BY 2 DESC
    """,
    "Event signals": """
        SELECT event_type, count(*) AS events, count(DISTINCT cik) AS companies
        FROM events WHERE event_date >= DATE '2005-01-01' GROUP BY 1 ORDER BY 2 DESC
    """,
    "Price coverage": """
        SELECT status, count(*) AS tickers FROM price_fetch_log GROUP BY 1
    """,
}


def main():
    con = connect(DATA_DIR / "ddb.duckdb")
    lines = ["# Company database coverage\n"]
    for title, q in Q.items():
        try:
            df = con.execute(q).df()
        except Exception as exc:  # noqa: BLE001
            lines.append(f"## {title}\n\n_unavailable: {exc}_\n")
            continue
        lines.append(f"## {title}\n\n{df.to_markdown(index=False)}\n")
    out = DATA_DIR / "results" / "db_coverage.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
