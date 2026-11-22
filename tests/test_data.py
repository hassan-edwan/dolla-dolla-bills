import numpy as np
import pandas as pd

from ddb.data.edgar import filing_events, parse_form_index
from ddb.data.store import PointInTimeStore
from ddb.metrics import summary


def test_pit_store_hides_future_and_handles_restatement(tmp_path):
    s = PointInTimeStore(tmp_path)
    s.write("fund", pd.DataFrame([
        {"entity": "AAA", "field": "Revenue", "period_end": "2023-12-31", "value": 100.0,
         "knowable_at": "2024-02-10", "source": "10-K"},
        {"entity": "AAA", "field": "Revenue", "period_end": "2023-12-31", "value": 90.0,
         "knowable_at": "2024-06-01", "source": "10-K/A"},   # restated down
    ]))
    assert s.latest_value("fund", "2024-01-31", "AAA", "Revenue") is None
    assert s.latest_value("fund", "2024-03-01", "AAA", "Revenue") == 100.0
    assert s.latest_value("fund", "2024-07-01", "AAA", "Revenue") == 90.0


IDX = """Description:           Master Index of EDGAR Dissemination Feed by Form Type

Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------------------------------------
25-NSE           1Life Healthcare Inc                                          1404123     2023-02-22  edgar/data/1404123/0001354457-23-000108.txt
SC 13D/A         Some Holder LLC                                               1234567     2023-03-01  edgar/data/1234567/0000000000-23-000001.txt
"""


def test_parse_form_index():
    df = parse_form_index(IDX)
    assert list(df["form"]) == ["25-NSE", "SC 13D/A"]
    assert df["cik"].iloc[0] == 1404123


def test_filing_events_detects_failures_and_dilution():
    sub = {"cik": "99", "name": "Doomed Corp", "filings": {"recent": {
        "accessionNumber": ["a1", "a2", "a3"],
        "filingDate": ["2023-01-05", "2023-03-01", "2023-04-01"],
        "acceptanceDateTime": ["2023-01-05T21:00:00.000Z"] * 3,
        "form": ["424B5", "8-K", "25-NSE"],
        "items": ["", "1.03,9.01", ""],
    }}}
    ev = filing_events(sub)
    assert set(ev["event_type"]) == {"offering_prospectus", "bankruptcy", "delisting_exchange"}


def test_summary_18m_metrics():
    idx = pd.bdate_range("2020-01-01", periods=800)
    eq = pd.Series(np.exp(np.linspace(0, 0.5, 800)), index=idx)
    s = summary(eq)
    assert s["max_drawdown"] == 0
    assert s["h18_pct_positive"] == 1.0
