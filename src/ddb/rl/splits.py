"""Train / validation / test periods for every model (configs/rl.yaml -> splits).

- Periods never overlap, in time order: train, validation, test.
- The first `embargo_days` of validation and test are dropped, and `purge()`
  removes training samples whose label window reaches into a later period, so
  nothing learned in one period leaks into the next.
- The test period is locked. Opening it requires allow_test=True and is logged with
  a timestamp to data/db/rl/test_access.log, so it's visible how often it was used
  (every look at the test set makes it less honest).
"""
from __future__ import annotations

import pandas as pd

from ..config import DATA_DIR, load

LOG = DATA_DIR / "db" / "rl" / "test_access.log"
ORDER = ("train", "validation", "test")
OVERRIDE: dict | None = None    # tests / experiments: replaces configs/rl.yaml -> splits


def periods(cfg: dict | None = None) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """name -> (first usable day, last day), embargo applied."""
    cfg = cfg or OVERRIDE or load("rl")["splits"]
    emb = pd.Timedelta(days=cfg.get("embargo_days", 0))
    out = {}
    for name in ORDER:
        a, b = cfg[name]
        start = pd.Timestamp(a) + (emb if name != "train" else pd.Timedelta(0))
        end = pd.Timestamp(b) if b else pd.Timestamp.now().normalize()
        out[name] = (start, end)
    for x, y in zip(ORDER, ORDER[1:]):
        if pd.Timestamp(cfg[x][1]) >= pd.Timestamp(cfg[y][0]):
            raise ValueError(f"splits overlap: {x} ends {cfg[x][1]}, {y} starts {cfg[y][0]}")
    return out


def open_split(name: str, allow_test: bool = False, who: str = "") -> tuple[pd.Timestamp, pd.Timestamp]:
    if name not in ORDER:
        raise ValueError(f"unknown split {name!r}")
    if name == "test":
        if not allow_test:
            raise PermissionError("The test period is locked. Pass allow_test=True for a final evaluation only; "
                                  "each access is logged.")
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(f"{pd.Timestamp.now(tz='UTC').isoformat()}\t{who}\n")
    return periods()[name]


def test_accesses() -> int:
    return sum(1 for _ in LOG.open()) if LOG.exists() else 0


def label(dates: pd.DatetimeIndex) -> pd.Series:
    """Split name for each date (None inside an embargo or before train)."""
    p = periods()
    vals = [next((n for n, (a, b) in p.items() if a <= d <= b), None) for d in dates]
    return pd.Series(vals, index=dates, dtype=object)


def purge(dates: pd.DatetimeIndex, horizon_days: int) -> pd.Series:
    """True where a sample's label window [date, date + horizon] stays inside its own period."""
    lab = label(dates)
    p = periods()
    end = pd.Series([p[x][1] if x else pd.NaT for x in lab], index=dates)
    return (lab.notna()) & (dates + pd.Timedelta(days=horizon_days) <= end)
