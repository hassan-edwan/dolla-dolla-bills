"""Build the model-ready store (ddb.store.Store) from the signal outputs.

Inputs: data/db/signals/panel.parquet + scores.parquet (monthly, ddb.features.panel /
validate), data/db/store/daily/* (written by ddb.features.daily), the database (screens,
events). Output: data/db/store/ with one company list (ids.npy) shared by every block:

  month/X.npy         [month, company, signal] raw values           float32
  month/R.npy         [month, company, signal] sign-adjusted percentile - 0.5, liquid universe
  month/y.npy         [month, company, 2] next 1 / 3-month return (labels)
  month/liquid.npy, tradable.npy, industry.npy, dates.npy
  daily/...           the daily block, re-indexed to the same company list
  events/...          the event index (ddb.store.events)
  meta.json           features, signs, scaling (train-period median / IQR), splits

    python -m ddb.store.build
"""
from __future__ import annotations

import json
import shutil
import time

import numpy as np
import pandas as pd
import yaml

from ..config import CONFIG_DIR, DATA_DIR
from ..db.schema import connect
from ..rl.splits import periods
from . import ROOT
from . import events as E

SIG = DATA_DIR / "db" / "signals"
DB_PATH = DATA_DIR / "ddb.duckdb"


def _scaling(X: np.ndarray, mask: np.ndarray) -> dict:
    v = X[mask]                                   # rows in the universe, [n, F]
    med = np.nanmedian(v, axis=0)
    q75, q25 = np.nanpercentile(v, 75, axis=0), np.nanpercentile(v, 25, axis=0)
    iqr = np.where(np.isfinite(q75 - q25) & ((q75 - q25) > 0), q75 - q25, 1.0)
    return {"median": np.nan_to_num(med).tolist(), "iqr": iqr.tolist()}


def build(db_path=DB_PATH) -> dict:
    from ..db.pit import AsOf
    t0 = time.time()
    sigcfg = yaml.safe_load((CONFIG_DIR / "signals.yaml").read_text())["signals"]
    panel = pd.read_parquet(SIG / "panel.parquet")
    panel["d"] = pd.to_datetime(panel["d"])
    scores = pd.read_parquet(SIG / "scores.parquet")
    scores["d"] = pd.to_datetime(scores["d"])
    dd = ROOT / "daily"
    d_ids = np.load(dd / "ids.npy") if (dd / "ids.npy").exists() else np.array([], np.int64)
    ids = np.unique(np.concatenate([panel["cik"].astype(np.int64).unique(), d_ids]))
    col = {int(c): i for i, c in enumerate(ids)}
    feats = [s for s in sigcfg if s in panel.columns]
    months = pd.DatetimeIndex(sorted(panel["d"].unique()))
    T, N, F = len(months), len(ids), len(feats)
    mi = {d: i for i, d in enumerate(months)}
    r = panel["d"].map(mi).to_numpy()
    c = panel["cik"].map(col).to_numpy()
    X = np.full((T, N, F), np.nan, np.float32)
    X[r, c, :] = panel[feats].to_numpy(np.float32)
    y = np.full((T, N, 2), np.nan, np.float32)
    y[r, c, :] = panel[["fwd_1m", "fwd_3m"]].to_numpy(np.float32)
    liquid = np.zeros((T, N), bool)
    lq = ((panel["price_raw"] >= 2) & (panel["dollar_vol_20d"] >= 1e6)).to_numpy()
    liquid[r[lq], c[lq]] = True
    inds = sorted(panel["industry"].dropna().unique())
    icode = {k: i for i, k in enumerate(inds)}
    industry = np.full((T, N), -1, np.int8)
    industry[r, c] = panel["industry"].map(icode).fillna(-1).to_numpy(np.int8)
    R = np.full((T, N, F), np.nan, np.float32)
    sr = scores["d"].map(mi).to_numpy()
    sc = scores["cik"].map(col).to_numpy()
    for j, f in enumerate(feats):
        if f"{f}__pct" in scores:
            R[sr, sc, j] = scores[f"{f}__pct"].to_numpy(np.float32) / 100 - 0.5

    print("tradable (screens) per month ...", flush=True)
    con = connect(db_path, read_only=True)
    tradable = np.zeros((T, N), bool)
    for i, d in enumerate(months):
        with AsOf(con, d + pd.Timedelta(hours=21, minutes=30)) as db:
            tr = db.tradable()
        cc = [col[int(x)] for x in tr["cik"] if int(x) in col]
        tradable[i, cc] = True

    out = ROOT
    (out / "month").mkdir(parents=True, exist_ok=True)
    for name, arr in (("X", X), ("R", R), ("y", y), ("liquid", liquid), ("tradable", tradable), ("industry", industry)):
        np.save(out / "month" / f"{name}.npy", arr)
    np.save(out / "month" / "dates.npy", months.to_numpy().astype("datetime64[D]"))
    (out / "month" / "meta.json").write_text(json.dumps({"features": feats, "industries": inds,
                                                         "labels": ["fwd_1m", "fwd_3m"]}))
    np.save(out / "ids.npy", ids)

    # point-in-time scaling: each month's cross-sectional median / IQR (liquid universe),
    # averaged over EARLIER months only (expanding, shifted one month)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        Xl = np.where(liquid[:, :, None], X, np.nan)
        med_t = np.nanmedian(Xl, axis=1)
        iqr_t = np.nanpercentile(Xl, 75, axis=1) - np.nanpercentile(Xl, 25, axis=1)
    pit_med = pd.DataFrame(med_t).expanding(min_periods=6).mean().shift(1).to_numpy(np.float32)
    pit_iqr = pd.DataFrame(iqr_t).expanding(min_periods=6).mean().shift(1).to_numpy(np.float32)
    np.save(out / "month" / "pit_median.npy", pit_med)
    np.save(out / "month" / "pit_iqr.npy", np.where(pit_iqr > 0, pit_iqr, np.nan).astype(np.float32))
    tr0, tr1 = periods()["train"]
    train_m = (months >= tr0) & (months <= tr1)
    scaling = {"month": _scaling(X[train_m], liquid[train_m])}

    # daily block: re-index to the shared company list
    if len(d_ids):
        print("daily block ...", flush=True)
        dm = json.loads((dd / "meta.json").read_text())
        pos = np.array([col[int(x)] for x in d_ids])
        ddates = pd.DatetimeIndex(np.load(dd / "dates.npy"))
        for name, fill in (("X", np.nan), ("y", np.nan), ("cost", np.nan), ("mask", False), ("industry", -1)):
            f = dd / f"{name}.npy"
            if not f.exists():
                continue
            a = np.load(f, mmap_mode="r")
            b = np.full((a.shape[0], N) + a.shape[2:], fill, dtype=a.dtype)
            b[:, pos] = a
            tmp = dd / f"{name}.tmp.npy"
            np.save(tmp, b)
            shutil.move(tmp, f)
            del b
        np.save(dd / "ids.npy", ids)
        Xd = np.load(dd / "X.npy", mmap_mode="r")
        md = np.load(dd / "mask.npy", mmap_mode="r")
        train_d = np.where((ddates >= tr0) & (ddates <= tr1))[0][::5]   # every 5th day is plenty for scaling
        scaling["day"] = _scaling(np.asarray(Xd[train_d]), np.asarray(md[train_d]))
        daily_meta = {"features": dm["features"], "horizons": dm["horizons"], "shape": list(Xd.shape)}
    else:
        daily_meta = {}

    print("event index ...", flush=True)
    ev = E.build(con, ids, out / "events")
    con.close()
    meta = {"built": pd.Timestamp.now(tz="UTC").isoformat(), "companies": int(N),
            "month": {"features": feats, "signs": {f: sigcfg[f]["sign"] for f in feats},
                      "questions": {f: sigcfg[f].get("question") for f in feats}, "shape": [T, N, F],
                      "first": str(months[0].date()), "last": str(months[-1].date())},
            "day": daily_meta, "events": ev, "scaling": scaling,
            "splits": {k: [str(a.date()), str(b.date())] for k, (a, b) in periods().items()}}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    size = sum(f.stat().st_size for f in out.rglob("*.npy")) / 1e6
    return {"companies": int(N), "months": T, "monthly_features": F, "events": ev["events"],
            "size_mb": round(size), "seconds": round(time.time() - t0)}


if __name__ == "__main__":
    print(build())
