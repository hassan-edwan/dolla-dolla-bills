"""Point-in-time helpers: deterministic tie-breaking and ticker-at-the-time matching."""
import pandas as pd

from ddb.features.panel import attach_cik, prefer


def test_prefer_earliest_known_then_preference():
    k1, k2 = pd.Timestamp("2018-03-30", tz="UTC"), pd.Timestamp("2019-04-05", tz="UTC")
    pe = pd.Timestamp("2017-12-31")
    a = pd.DataFrame({"cik": [1], "period_end": [pe], "value": [1332.0], "known": [k2]})   # preferred, published later
    b = pd.DataFrame({"cik": [1], "period_end": [pe], "value": [319.0], "known": [k1]})
    c = pd.DataFrame({"cik": [1], "period_end": [pe], "value": [1330.0], "known": [k1]})
    out = prefer([a, b, c], ["cik", "period_end"])
    assert out["value"].tolist() == [319.0]          # earliest known wins; later data can't displace it
    out = prefer([c, b], ["cik", "period_end"])
    assert out["value"].tolist() == [1330.0]         # same filing: order of preference
    assert prefer([b, c], ["cik", "period_end"])["value"].tolist() == [319.0]


def test_prefer_latest_period_on_ties():
    k = pd.Timestamp("2018-03-30", tz="UTC")
    a = pd.DataFrame({"cik": [1, 1], "period_end": pd.to_datetime(["2017-12-31", "2018-02-28"]),
                      "value": [10.0, 11.0], "known": [k, k]})
    out = prefer([a], ["cik", "known"], latest_period=True)
    assert out["value"].tolist() == [11.0]


def test_attach_cik_uses_ticker_of_the_time():
    tm = pd.DataFrame({"ticker": ["ABC", "ABC"], "m": pd.to_datetime(["2015-03-01", "2020-06-01"]), "cik": [111, 222]})
    rows = pd.DataFrame({"ticker": ["ABC", "ABC", "ABC"],
                         "d": pd.to_datetime(["2015-03-13", "2020-06-15", "2018-01-15"]), "x": [1, 2, 3]})
    out = attach_cik(rows, tm, "d").sort_values("x")
    assert out["cik"].tolist() == [111, 222]          # 2018: nobody traded under ABC -> dropped
