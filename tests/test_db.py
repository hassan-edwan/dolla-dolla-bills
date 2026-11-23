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
