"""Dashboard server: JSON API over the DuckDB database + the static frontend.

    python -m ddb.app.api            # http://127.0.0.1:8050
    python -m ddb.app.api --port 9000 --host 0.0.0.0

Read-only. Loaders that write Parquet files can keep running; the DuckDB file
itself is opened read-only per request.
"""
from __future__ import annotations

import argparse
import functools
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import DATA_DIR
from ..db.schema import connect
from . import queries as Q

STATIC = Path(__file__).parent / "static"
DB_PATH = DATA_DIR / "ddb.duckdb"
app = FastAPI(title="dolla-dolla-bills dashboard")


_LOCK = threading.Lock()


class _Locked:
    """A connection used by one request at a time. connect() rewrites the Parquet-backed
    views, so two requests opening the file at once conflict; requests queue instead.
    The file is still not held open between requests, so loaders can write to it."""

    def __init__(self, con):
        self._con = con

    def __getattr__(self, name):
        return getattr(self._con, name)

    def close(self):
        try:
            self._con.close()
        finally:
            _LOCK.release()


def _con():
    # connect() (read-write) refreshes the Parquet-backed views; fall back to read-only if locked.
    _LOCK.acquire()
    try:
        try:
            return _Locked(connect(DB_PATH))
        except Exception:  # noqa: BLE001
            return _Locked(connect(DB_PATH, read_only=True))
    except BaseException:
        _LOCK.release()
        raise


def _json(data):
    return JSONResponse(content=data)


@functools.lru_cache(maxsize=1)
def _universe_cached():
    con = _con()
    try:
        return Q.universe_series(con)
    finally:
        con.close()


@app.get("/api/overview")
def overview():
    con = _con()
    try:
        return _json(Q.overview(con))
    finally:
        con.close()


@app.get("/api/universe")
def universe():
    return _json(_universe_cached())


@app.get("/api/screens")
def screens():
    con = _con()
    try:
        return _json(Q.screens(con))
    finally:
        con.close()


@app.get("/api/search")
def search(q: str = ""):
    con = _con()
    try:
        return _json(Q.search(con, q))
    finally:
        con.close()


@app.get("/api/company/{cik}")
def company(cik: int):
    con = _con()
    try:
        data = Q.company(con, cik)
        if not data:
            raise HTTPException(404, "unknown company")
        return _json(data)
    finally:
        con.close()


@app.get("/api/industry/{name}")
def industry(name: str):
    con = _con()
    try:
        return _json(Q.industry(con, name, _universe_cached()))
    finally:
        con.close()


@app.get("/api/signals")
def signals():
    con = _con()
    try:
        return _json(Q.signals_overview(con))
    finally:
        con.close()


@app.get("/api/signal_month/{month}")
def signal_month(month: str):
    con = _con()
    try:
        return _json(Q.signal_month(con, month))
    finally:
        con.close()


@app.get("/api/short_term")
def short_term():
    con = _con()
    try:
        return _json(Q.short_term_overview(con))
    finally:
        con.close()


@app.get("/api/short_term_day/{day}")
def short_term_day(day: str):
    con = _con()
    try:
        return _json(Q.short_term_day(con, day))
    finally:
        con.close()


@app.get("/api/runs")
def runs():
    con = _con()
    try:
        return _json(Q.runs(con))
    finally:
        con.close()


@app.get("/api/decisions/{run_id}")
def decisions(run_id: str):
    con = _con()
    try:
        return _json(Q.decisions(con, run_id))
    finally:
        con.close()


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8050)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port)
