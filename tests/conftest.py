import numpy as np
import pandas as pd
import pytest

from ddb.data.prices import PriceData


def make_prices(closes: dict[str, list[float]], start="2024-01-02", volume=1e7, opens=None) -> PriceData:
    """Build a PriceData panel. open defaults to the previous close (no gap)."""
    n = max(len(v) for v in closes.values())
    idx = pd.bdate_range(start, periods=n)
    close = pd.DataFrame({s: pd.Series(v + [np.nan] * (n - len(v)), index=idx) for s, v in closes.items()})
    if opens is None:
        open_ = close.shift(1).fillna(close)
        open_[close.isna()] = np.nan
    else:
        open_ = pd.DataFrame(opens, index=idx)
    vol = pd.DataFrame(volume, index=idx, columns=close.columns).where(close.notna())
    return PriceData(open=open_, high=close * 1.01, low=close * 0.99, close=close, volume=vol)


@pytest.fixture
def flat_prices():
    return make_prices({"AAA": [100.0] * 30, "BBB": [50.0] * 30})
