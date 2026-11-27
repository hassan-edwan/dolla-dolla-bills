"""Model-ready data: memory-mapped arrays that load instantly and slice by index.

    from ddb.store import Store
    st = Store()                                   # nothing is read until used
    m = st.month                                   # monthly signals
    m.X[t, :, :]      raw values  [month, company, signal]
    m.R[t, :, :]      cross-sectional percentile, sign-adjusted, in [-0.5, 0.5] (0.5 = most favorable)
    m.y[t, :, h]      forward return (labels: next 1 / 3 months, delisting-adjusted)
    m.liquid[t, :]    price >= $2 and $1M+ daily volume;  m.tradable[t, :] passes every screen
    d = st.day                                     # daily data points, same layout (+ d.cost)
    st.events.batch_before(ciks, t, k=32)          # each company's last 32 events public by t
    idx = st.split_index("month", "train", horizon_days=31)   # rows inside the split, purged
    Xn = st.normalize_pit(idx, m.X[idx])           # scaled with earlier months only (point in time)
    m.R                                            # cross-sectional percentiles: point in time by construction

Point in time: row t holds only information public by that date's close; labels
(y) are future returns and must never be used as inputs. Splits come from
configs/rl.yaml (ddb.rl.splits), with purge so a label window never crosses into
a later period.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ..config import DATA_DIR

ROOT = DATA_DIR / "db" / "store"


def _load_block(d: Path, names: list[str]) -> SimpleNamespace:
    ns = SimpleNamespace()
    for n in names:
        f = d / f"{n}.npy"
        if f.exists():
            setattr(ns, n, np.load(f, mmap_mode="r"))
    meta = d / "meta.json"
    ns.meta = json.loads(meta.read_text()) if meta.exists() else {}
    ns.features = ns.meta.get("features", [])
    if hasattr(ns, "dates"):
        ns.dates = pd.DatetimeIndex(np.asarray(ns.dates))
    return ns


class Store:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.meta = json.loads((self.root / "meta.json").read_text())
        self.ids = np.load(self.root / "ids.npy")
        self._month = self._day = self._events = None

    @property
    def month(self) -> SimpleNamespace:
        if self._month is None:
            self._month = _load_block(self.root / "month", ["X", "R", "y", "liquid", "tradable", "industry", "dates",
                                                            "pit_median", "pit_iqr"])
        return self._month

    @property
    def day(self) -> SimpleNamespace:
        if self._day is None:
            self._day = _load_block(self.root / "daily", ["X", "mask", "y", "cost", "industry", "dates", "ids"])
        return self._day

    @property
    def events(self):
        if self._events is None:
            from .events import EventIndex
            self._events = EventIndex.load(self.root / "events", self.ids)
        return self._events

    def split_index(self, freq: str, split: str, horizon_days: int = 0, allow_test: bool = False) -> np.ndarray:
        """Row indices of `freq` ('month' | 'day') dates inside the split whose label
        window [date, date + horizon_days] stays inside it."""
        from ..rl.splits import open_split
        a, b = open_split(split, allow_test=allow_test, who=f"Store.split_index({freq})")
        dates = (self.month if freq == "month" else self.day).dates
        ok = (dates >= a) & (dates + pd.Timedelta(days=horizon_days) <= b)
        return np.where(ok)[0]

    def normalize_pit(self, t: np.ndarray | int, X: np.ndarray) -> np.ndarray:
        """Point-in-time robust scaling of monthly X at month index t (scalar or one per
        row of X): each month uses the median / IQR of EARLIER months only. Clipped to +-5;
        NaN where fewer than 6 earlier months exist. Prefer this (or R) for anything that
        must match what was knowable at the time."""
        med = np.asarray(self.month.pit_median)[t]
        iqr = np.asarray(self.month.pit_iqr)[t]
        if np.ndim(t):                           # one month index per row of X: broadcast over companies
            med, iqr = med[:, None, :], iqr[:, None, :]
        return np.clip((np.asarray(X, np.float32) - med) / iqr, -5, 5)

    def normalize(self, freq: str, X: np.ndarray) -> np.ndarray:
        """Robust scaling with train-period median / IQR per feature, clipped to +-5.
        Note: a training-period sample scaled this way uses statistics from later in
        the training period; use normalize_pit (or R) where that matters."""
        s = self.meta["scaling"][freq]
        med, iqr = np.asarray(s["median"], np.float32), np.asarray(s["iqr"], np.float32)
        return np.clip((np.asarray(X, np.float32) - med) / iqr, -5, 5)

    def column(self, cik: int) -> int:
        """Company column in the monthly arrays (self.ids)."""
        return int(np.searchsorted(self.ids, cik))
