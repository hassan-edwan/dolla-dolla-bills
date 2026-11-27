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


@pytest.fixture(scope="session")
def synth(tmp_path_factory):
    """Synthetic database with every pipeline built once: monthly panel + validation,
    daily short-term, regime, model portfolio and tracking. Yields (root, db path)."""
    import os
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from synth import make_db
    from ddb.app import queries as Q
    from ddb.features import daily, panel, regime, validate
    from ddb.live import tracking
    from ddb.portfolio import model
    from ddb.rl import dataset as rl_dataset, readiness, splits, fast
    import ddb.store as store_pkg
    import ddb.store.build as store_build
    root = tmp_path_factory.mktemp("synth")
    db = make_db(root, n=40, start="2016-01-04", end="2019-12-31")
    sig = root / "db" / "signals"
    saved = {(panel, "OUT"): sig, (validate, "SIG_DIR"): sig, (daily, "OUT"): sig / "daily", (Q, "SIG"): sig.as_posix(),
             (regime, "OUT"): root / "db" / "regime", (regime, "SIG"): sig, (model, "OUT"): root / "db" / "portfolio",
             (model, "SIG"): sig, (model, "REGIME"): root / "db" / "regime" / "regime.parquet",
             (tracking, "OUT"): root / "db" / "live", (tracking, "SIG"): sig,
             (rl_dataset, "OUT"): root / "db" / "rl", (rl_dataset, "SIG"): sig,
             (rl_dataset, "REGIME"): root / "db" / "regime" / "regime.parquet",
             (readiness, "DB"): root / "db", (readiness, "OUT"): root / "db" / "rl", (readiness, "DATA_DIR"): root,
             (splits, "LOG"): root / "db" / "rl" / "test_access.log",
             (daily, "STORE"): root / "db" / "store" / "daily", (store_pkg, "ROOT"): root / "db" / "store",
             (store_build, "ROOT"): root / "db" / "store", (store_build, "SIG"): sig,
             (fast, "FAST"): root / "db" / "rl" / "fast",
             (splits, "OVERRIDE"): {"train": ["2017-01-01", "2018-06-30"], "validation": ["2018-07-01", "2019-03-31"],
                                    "test": ["2019-04-01", "2019-12-31"], "embargo_days": 35}}
    old = {k: getattr(*k) for k in saved}
    for (mod, name), v in saved.items():
        setattr(mod, name, v)
    cwd = os.getcwd()
    os.chdir(root)
    try:
        panel.build("2016-01", db_path=db)
        validate.build()
        daily.build(db_path=db)
        regime.build(db_path=db)
        model.build(db_path=db)
        tracking.build(db_path=db)
        rl_dataset.build(db_path=db)
        store_build.build(db_path=db)
        fast.build(root=root / "db" / "rl", out=root / "db" / "rl" / "fast")
        yield root, db
    finally:
        os.chdir(cwd)
        for (mod, name), v in old.items():
            setattr(mod, name, v)
