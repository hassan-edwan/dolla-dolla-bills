"""Point-in-time (PIT) store.

Every non-price record carries a ``knowable_at`` timestamp: the earliest moment
the value could have been known (for example, a filing's acceptance time, not
its fiscal period end). ``as_of(t)`` returns only what was knowable at t, with
the latest version of each (entity, field, period_end) key, so restatements
appear only from the date they were filed.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PIT_COLUMNS = ["entity", "field", "period_end", "value", "knowable_at", "source"]


class PointInTimeStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, dataset: str) -> Path:
        return self.root / f"{dataset}.parquet"

    def write(self, dataset: str, df: pd.DataFrame) -> int:
        missing = set(PIT_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"missing PIT columns: {sorted(missing)}")
        df = df[PIT_COLUMNS].copy()
        df["knowable_at"] = pd.to_datetime(df["knowable_at"], utc=True)
        df["period_end"] = pd.to_datetime(df["period_end"])
        if df["knowable_at"].isna().any():
            raise ValueError("every PIT record needs knowable_at")
        path = self._path(dataset)
        if path.exists():
            df = pd.concat([pd.read_parquet(path), df], ignore_index=True)
        df = df.drop_duplicates(subset=["entity", "field", "period_end", "knowable_at", "value"])
        df = df.sort_values(["entity", "field", "period_end", "knowable_at"]).reset_index(drop=True)
        df.to_parquet(path, index=False)
        return len(df)

    def read(self, dataset: str) -> pd.DataFrame:
        path = self._path(dataset)
        if not path.exists():
            return pd.DataFrame(columns=PIT_COLUMNS)
        return pd.read_parquet(path)

    def as_of(self, dataset: str, t, entities=None, fields=None) -> pd.DataFrame:
        t = pd.Timestamp(t)
        t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
        df = self.read(dataset)
        df = df[df["knowable_at"] <= t]
        if entities is not None:
            df = df[df["entity"].isin(list(entities))]
        if fields is not None:
            df = df[df["field"].isin(list(fields))]
        # Latest knowable version of each fact.
        df = df.sort_values("knowable_at").groupby(
            ["entity", "field", "period_end"], as_index=False).last()
        return df.reset_index(drop=True)

    def latest_value(self, dataset: str, t, entity: str, field: str):
        """Most recent period's value for (entity, field) as known at t, or None."""
        df = self.as_of(dataset, t, entities=[entity], fields=[field])
        if df.empty:
            return None
        return df.sort_values("period_end").iloc[-1]["value"]
