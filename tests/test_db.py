import pandas as pd
import pytest

from ddb.db.build_prices import unadjust
from ddb.db.pit import AsOf, LookaheadError
from ddb.db.schema import connect
from ddb.db.taxonomy import Taxonomy

T = pd.Timestamp


def test_name_history_dates_industry_pivot():
    """Riot: biotech names until Oct 2017, then 'Riot Blockchain' -> crypto from 2017-10."""
    tax = Taxonomy()
    periods = [("AspenBio Pharma, Inc.", T("2002-04-12"), T("2012-12-13")),
               ("Venaxis, Inc.", T("2012-12-20"), T("2016-11-30")),
               ("Bioptix, Inc.", T("2016-12-01"), T("2017-09-29")),
               ("Riot Blockchain, Inc.", T("2017-10-04"), T("2022-12-19")),
               ("Riot Platforms, Inc.", T("2022-12-19"), None)]
    tags = tax.tag_company(periods, sic=6199, first_filing=T("2002-02-07"))
    crypto = [t for t in tags if t["industry"] == "crypto_adj"]
    bio = [t for t in tags if t["industry"] == "gene_biotech"]
    assert crypto and crypto[0]["valid_from"] == T("2017-10-04") and crypto[0]["valid_to"] is None
    assert bio and bio[0]["valid_from"] == T("2002-04-12") and bio[0]["valid_to"] == T("2017-10-04")


def test_sic_tag_starts_after_pivot():
    tax = Taxonomy()
    periods = [("Acme Bitcoin Corp", T("2015-01-01"), T("2019-01-01")),
               ("Acme Semiconductor", T("2019-01-01"), None)]
    tags = tax.tag_company(periods, sic=3674, first_filing=T("2015-01-01"))
    sic = [t for t in tags if t["method"] == "sic"][0]
    assert sic["industry"] == "tech" and sic["valid_from"] == T("2019-01-01")


def test_keywords_match_word_starts_only():
    tax = Taxonomy()
    assert not tax.name_tags("General Electric Co")
    assert {t.industry for t in tax.name_tags("SolarEdge Technologies")} == {"energy"}


def test_asof_hides_future_rows_and_labels(tmp_path):
    con = connect(tmp_path / "t.duckdb")
    con.execute("""INSERT INTO events VALUES
        (1, 'bankruptcy', DATE '2020-03-01', '8-K', 'a1', TIMESTAMPTZ '2020-03-01 21:00:00+00'),
        (1, 'late_annual_report', DATE '2019-04-01', 'NT 10-K', 'a0', TIMESTAMPTZ '2019-04-01 21:00:00+00')""")
    con.execute("INSERT INTO outcomes (cik, outcome) VALUES (1, 'bankrupt')")
    with AsOf(con, "2019-12-31") as db:
        ev = db.query("SELECT event_type FROM events WHERE cik = 1")
        assert list(ev["event_type"]) == ["late_annual_report"]
        with pytest.raises(LookaheadError):
            db.query("SELECT * FROM outcomes")
        with pytest.raises(LookaheadError):
            db.query("SELECT * FROM companies")
    with AsOf(con, "2020-03-02") as db:
        assert len(db.query("SELECT * FROM events")) == 2


def test_unadjust_reverses_later_splits():
    idx = pd.to_datetime(["2021-01-04", "2021-01-05", "2023-06-01"])
    bars = pd.DataFrame({"close": [5.0, 5.0, 5.0], "volume": [100.0, 100.0, 100.0]}, index=idx)
    ev = pd.DataFrame([{"date": T("2022-01-03"), "type": "split", "value": 1 / 50}])  # 1:50 reverse
    out = unadjust(bars, ev)
    assert out["close_raw"].iloc[0] == pytest.approx(0.10)      # actually traded at $0.10
    assert out["volume_raw"].iloc[0] == pytest.approx(5000)
    assert out["close_raw"].iloc[-1] == pytest.approx(5.0)


PTR_SAMPLE = """
           SP         Albemarle Corporation (ALB) [ST]            S                 12/21/2023 01/08/2024             $1,001 - $15,000
           SP         Charles Schwab Corporation (SCHW) P                           12/14/2023 01/08/2024             $50,001 -
                      [ST]                                                                                            $100,000
"""


def test_ptr_parser_handles_wrapped_fields():
    from ddb.db.build_congress import parse_ptr_text
    rows = parse_ptr_text(PTR_SAMPLE)
    assert [r["ticker"] for r in rows] == ["ALB", "SCHW"]
    assert rows[0]["transaction_type"] == "sell" and rows[0]["amount_max"] == 15000
    assert rows[1]["transaction_type"] == "buy" and rows[1]["asset_type"] == "ST"
    assert (rows[1]["amount_min"], rows[1]["amount_max"]) == (50001, 100000)


def test_tradable_applies_screens_point_in_time(tmp_path):
    con = connect(tmp_path / "s.duckdb")
    con.execute("""INSERT INTO company_industries VALUES
        (1, 'tech', 'semis', 'sic', '3674', 'high', DATE '2010-01-01', NULL, TIMESTAMPTZ '2010-01-01 00:00:00+00'),
        (2, 'tech', 'semis', 'sic', '3674', 'high', DATE '2010-01-01', NULL, TIMESTAMPTZ '2010-01-01 00:00:00+00'),
        (3, 'tech', 'semis', 'sic', '3674', 'high', DATE '2010-01-01', NULL, TIMESTAMPTZ '2010-01-01 00:00:00+00')""")
    con.execute("""CREATE TABLE screen_static AS SELECT * FROM (VALUES
        (1, 'israel', 'pass', '', TIMESTAMPTZ '2010-01-01 00:00:00+00'),
        (2, 'israel', 'fail', 'incorporated=L3', TIMESTAMPTZ '2010-01-01 00:00:00+00'),
        (3, 'israel', 'pass', '', TIMESTAMPTZ '2010-01-01 00:00:00+00'))
        t(cik, screen, status, reasons, knowable_at)""")
    for cik in (1, 2, 3):   # active filers (universe requires recent filings)
        con.execute(f"""INSERT INTO filings (cik, accession, form, filing_date, knowable_at)
                        VALUES ({cik}, 'a{cik}', '10-Q', DATE '2019-11-01', TIMESTAMPTZ '2019-11-01 21:00:00+00')""")
    # company 3: compliant in 2019, debt pushes it out from Q1 2020 (known 2020-04-01)
    con.execute("""CREATE TABLE screen_sharia_financial AS SELECT * FROM (VALUES
        (1, DATE '2019-12-31', 'pass', TIMESTAMPTZ '2020-01-01 00:00:00+00'),
        (2, DATE '2019-12-31', 'pass', TIMESTAMPTZ '2020-01-01 00:00:00+00'),
        (3, DATE '2019-12-31', 'pass', TIMESTAMPTZ '2020-01-01 00:00:00+00'),
        (3, DATE '2020-03-31', 'fail', TIMESTAMPTZ '2020-04-01 00:00:00+00'))
        t(cik, as_of, status, knowable_at)""")
    with AsOf(con, "2020-02-15") as db:
        assert sorted(db.tradable()["cik"]) == [1, 3]      # Israeli company never tradable
    with AsOf(con, "2020-04-15") as db:
        assert sorted(db.tradable()["cik"]) == [1]         # ratio failure applies only once known


def test_universe_drops_companies_that_stopped_filing(tmp_path):
    con = connect(tmp_path / "u.duckdb")
    con.execute("""INSERT INTO company_industries VALUES
        (1, 'tech', 'semis', 'sic', '3674', 'high', DATE '2010-01-01', NULL, TIMESTAMPTZ '2010-01-01 00:00:00+00')""")
    con.execute("""INSERT INTO filings (cik, accession, form, filing_date, knowable_at)
                   VALUES (1, 'a1', '10-K', DATE '2015-03-01', TIMESTAMPTZ '2015-03-01 21:00:00+00')""")
    with AsOf(con, "2015-12-31") as db:
        assert list(db.universe()["cik"]) == [1]
    with AsOf(con, "2018-12-31") as db:
        assert db.universe().empty          # no filings for 18+ months -> gone


def test_gdelt_filter_keeps_company_and_signal_articles(tmp_path, monkeypatch):
    import io, zipfile
    from ddb.news import gdelt
    cols = [""] * 27
    def line(date, url, themes, orgs, tone="1.5,2,1"):
        f = list(cols); f[0], f[1], f[3], f[4] = "id", date, "example.com", url
        f[7], f[13], f[15] = themes, orgs, tone
        return "\t".join(f)
    text = "\n".join([
        line("20240102030000", "u1", "ENV_SOLAR;", "first solar;reuters"),          # names a company
        line("20240102030000", "u2", "ENV_NUCLEARPOWER;SHORTAGE;", "doe"),          # industry + bottleneck
        line("20240102030000", "u3", "ENV_NUCLEARPOWER;", "doe"),                   # industry only -> dropped
        line("20240102030000", "u4", "SPORTS;", "constellation"),                   # common word, not aliased
    ]) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.gkg.csv", text)
    class R:
        status_code, content = 200, buf.getvalue()
    class S:
        def get(self, *a, **k): return R()
    theme_ind, theme_sig = gdelt._load_cfg()
    rows = gdelt.process_file("20240102031500", S(), {"first solar": 1274494}, theme_ind, theme_sig)
    assert [r["url"] for r in rows] == ["u1", "u2"]
    assert rows[0]["ciks"] == [1274494] and rows[1]["signals"] == ["bottleneck"]
    assert str(rows[0]["knowable_at"]) == "2024-01-02 03:30:00+00:00"   # file time + 15 min


def test_decision_log_rejects_evidence_from_the_future(tmp_path):
    import duckdb
    from ddb.decisions import DecisionLog, Factor, HindsightError
    con = duckdb.connect(str(tmp_path / "d.duckdb"))
    log = DecisionLog(con)
    run = log.new_run("test-model")
    ok = Factor("momentum", 1.2, value=0.4, knowable_at=pd.Timestamp("2024-01-31 21:00", tz="UTC"))
    log.record(run, "2024-01-31 21:30", 1, "AAA", "buy", target_weight=0.1, factors=[ok])
    late = Factor("next quarter revenue", 0.5, knowable_at=pd.Timestamp("2024-02-15", tz="UTC"))
    with pytest.raises(HindsightError):
        log.record(run, "2024-01-31 21:30", 1, "AAA", "buy", target_weight=0.1, factors=[late])
    log.flush()
    assert con.execute("SELECT count(*) FROM decisions").fetchone()[0] == 1
