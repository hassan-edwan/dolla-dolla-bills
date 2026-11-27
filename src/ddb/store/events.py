"""Event index: every dated fact about a company in one array, ready for sequence
models (attention over a company's recent events) and for fast point-in-time lookups.

Layout (compressed sparse rows): events sorted by (company, public time); offsets[i]
is where company i's events start. "All events for company c public before t" is
one binary search inside that company's slice, so lookups take microseconds.

Sources (each event is public at its knowable_at; nothing later is visible):
- filing events (offerings, late filings, auditor changes, mergers, ...);
- risk / growth phrases found in filings (going concern, bottlenecks, ...);
- open-market insider buys and sales (value = log of the dollar amount);
- results announcements (8-K item 2.02).

    idx = EventIndex.load()
    types, values, times = idx.before(cik, t, k=32)      # the last 32 events public by t
    batch = idx.batch_before(ciks, t, k=32)              # padded arrays + mask, for a model
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR

ROOT = DATA_DIR / "db" / "store" / "events"


def build(con, ids: np.ndarray, out: Path = ROOT) -> dict:
    q = lambda sql: con.execute(sql).df()   # noqa: E731
    parts = []
    ev = q("SELECT cik, 'filing:' || event_type AS type, 1.0 AS value, knowable_at AS t FROM events")
    parts.append(ev)
    try:
        parts.append(q("SELECT cik, 'phrase:' || signal || ':' || phrase AS type, 1.0 AS value, knowable_at AS t "
                       "FROM filing_text_signals"))
    except Exception:  # noqa: BLE001 - optional source
        pass
    parts.append(q("""SELECT cik, CASE trans_code WHEN 'P' THEN 'insider:buy' ELSE 'insider:sell' END AS type,
                             ln(1 + shares * price) AS value, knowable_at AS t
                      FROM insider_transactions
                      WHERE NOT is_derivative AND trans_code IN ('P', 'S') AND NOT trans_date_suspect
                        AND NOT coalesce(is_10b5_1_plan, FALSE) AND coalesce(shares * price, 0) BETWEEN 1 AND 2e9"""))
    parts.append(q("""SELECT cik, 'report:results' AS type, 1.0 AS value, knowable_at AS t FROM filings
                      WHERE form LIKE '8-K%' AND items LIKE '%2.02%'"""))
    df = pd.concat(parts, ignore_index=True).dropna(subset=["t"])
    pos = {int(c): i for i, c in enumerate(ids)}
    df["row"] = df["cik"].map(lambda c: pos.get(int(c), -1))
    df = df[df["row"] >= 0]
    df["t"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert(None).astype("datetime64[ns]")
    df = df.sort_values(["row", "t"], kind="stable")
    vocab = sorted(df["type"].unique())
    code = {v: i for i, v in enumerate(vocab)}
    counts = np.bincount(df["row"].to_numpy(), minlength=len(ids))
    offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "offsets.npy", offsets)
    np.save(out / "time.npy", df["t"].to_numpy().astype("datetime64[ns]").astype(np.int64))
    np.save(out / "type.npy", df["type"].map(code).to_numpy(np.int16))
    np.save(out / "value.npy", df["value"].to_numpy(np.float32))
    (out / "vocab.json").write_text(json.dumps(vocab))
    return {"events": int(len(df)), "types": len(vocab), "companies_with_events": int((counts > 0).sum())}


class EventIndex:
    def __init__(self, root: Path = ROOT, ids: np.ndarray | None = None):
        self.offsets = np.load(root / "offsets.npy", mmap_mode="r")
        self.time = np.load(root / "time.npy", mmap_mode="r")
        self.type = np.load(root / "type.npy", mmap_mode="r")
        self.value = np.load(root / "value.npy", mmap_mode="r")
        self.vocab = json.loads((root / "vocab.json").read_text())
        self.ids = ids
        self._row = {int(c): i for i, c in enumerate(ids)} if ids is not None else None

    @classmethod
    def load(cls, root: Path = ROOT, ids: np.ndarray | None = None) -> "EventIndex":
        if ids is None:
            ids = np.load(root.parent / "ids.npy")
        return cls(root, ids)

    @staticmethod
    def _ns(t) -> int:
        t = pd.Timestamp(t)
        if t.tzinfo is not None:
            t = t.tz_convert(None)
        return int(t.value)

    def _slice(self, row: int):
        return int(self.offsets[row]), int(self.offsets[row + 1])

    def before(self, cik: int, t, k: int | None = None, since=None):
        """Events of one company public by t (optionally after `since`), oldest first;
        the last k if k is given. Returns (type codes, values, times as datetime64)."""
        row = self._row.get(int(cik))
        if row is None:
            e = np.array([], dtype=np.int16)
            return e, np.array([], np.float32), np.array([], "datetime64[ns]")
        a, b = self._slice(row)
        tt = self.time[a:b]
        hi = a + int(np.searchsorted(tt, self._ns(t), side="right"))
        lo = a if since is None else a + int(np.searchsorted(tt, self._ns(since), side="left"))
        if k is not None:
            lo = max(lo, hi - k)
        return (np.asarray(self.type[lo:hi]), np.asarray(self.value[lo:hi]),
                np.asarray(self.time[lo:hi]).astype("datetime64[ns]"))

    def batch_before(self, ciks, t, k: int = 32) -> dict:
        """Padded arrays for a model: types [n, k] (-1 = padding), values [n, k],
        age_days [n, k] (how long before t each event became public), mask [n, k]."""
        n = len(ciks)
        types = np.full((n, k), -1, np.int16)
        vals = np.zeros((n, k), np.float32)
        age = np.zeros((n, k), np.float32)
        t_ns = self._ns(t)
        for i, c in enumerate(ciks):
            ty, va, ti = self.before(c, t, k)
            m = len(ty)
            if m:
                types[i, -m:] = ty
                vals[i, -m:] = va
                age[i, -m:] = (t_ns - ti.astype(np.int64)) / 86_400e9
        return {"types": types, "values": vals, "age_days": age, "mask": types >= 0}
