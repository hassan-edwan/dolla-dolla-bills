"""Build company, name, industry, ticker, filing and event tables from the SEC
bulk ``submissions.zip`` (every EDGAR filer, including dead companies).

    python -m ddb.db.build_companies
"""
from __future__ import annotations

import json
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from ..config import DATA_DIR
from ..data.edgar import classify_filing
from .schema import connect
from .taxonomy import Taxonomy

SUBMISSIONS_ZIP = DATA_DIR / "raw" / "sec" / "submissions.zip"
DB_PATH = DATA_DIR / "ddb.duckdb"
FILING_COLS = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form",
               "items", "primaryDocument", "size"]


def _ts(s):
    return pd.Timestamp(s[:10]) if s else None


def _name_periods(sub: dict, first_filing):
    """[(name, from, to)] oldest first; the current name runs from the last rename."""
    former = sorted(sub.get("formerNames") or [], key=lambda x: x.get("from") or "")
    periods = []
    for f in former:
        start = _ts(f.get("from")) or first_filing
        end = _ts(f.get("to"))
        periods.append((f["name"], start, end))
    cur_start = max((p[2] for p in periods if p[2] is not None), default=first_filing)
    periods.append((sub.get("name") or "", cur_start, None))
    if periods and first_filing is not None and periods[0][1] > first_filing:
        n, _, e = periods[0]
        periods[0] = (n, first_filing, e)
    return periods


def _filings(z: zipfile.ZipFile, sub: dict, cik: int) -> pd.DataFrame:
    parts = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []) or []:
        try:
            parts.append(json.loads(z.read(f["name"])))
        except KeyError:
            pass
    frames = [pd.DataFrame({c: p.get(c, [None] * len(p.get("form", []))) for c in FILING_COLS})
              for p in parts if p.get("form")]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["cik"] = cik
    return df


def _process_chunk(args):
    names, zip_path = args[0], args[1]
    force = set(args[2]) if len(args) > 2 else set()   # CIKs added by research
    tax = Taxonomy()
    sic_codes = set(tax.sic_map)
    z = zipfile.ZipFile(zip_path)
    out = {k: [] for k in ("companies", "names", "industries", "tickers", "filings", "events")}
    for fname in names:
        sub = json.loads(z.read(fname))
        # SEC marks many older/defunct operating companies as entityType "other";
        # excluding them would drop failures (survivorship). Only skip funds.
        if sub.get("entityType") == "investment":
            continue
        try:
            sic = int(sub.get("sic") or 0)
        except ValueError:
            sic = 0
        if sic in tax.exclude_sic:
            continue
        cik = int(sub["cik"])
        forced = cik in force
        all_names = [sub.get("name") or ""] + [f["name"] for f in sub.get("formerNames") or []]
        if not forced and sic not in sic_codes and not any(tax.name_tags(n) for n in all_names):
            continue
        fil = _filings(z, sub, cik)
        if fil.empty:
            continue
        n_annual = int(fil["form"].isin(tax.annual_forms).sum())
        if n_annual == 0 and not forced:
            continue   # not an operating reporter (no 10-K/20-F/40-F ever)
        fil["filingDate"] = pd.to_datetime(fil["filingDate"], errors="coerce")
        first, last = fil["filingDate"].min(), fil["filingDate"].max()
        periods = _name_periods(sub, first)
        tags = tax.tag_company(periods, sic, first)
        if not tags and not forced:
            continue

        out["companies"].append({
            "cik": cik, "name": sub.get("name"), "sic": sic or None,
            "sic_description": sub.get("sicDescription"), "entity_type": sub.get("entityType"),
            "filer_category": sub.get("category"), "state_of_inc": sub.get("stateOfIncorporation"),
            "fiscal_year_end": sub.get("fiscalYearEnd"),
            "current_tickers": sub.get("tickers") or [], "current_exchanges": sub.get("exchanges") or [],
            "first_filing": first, "last_filing": last, "n_filings": len(fil),
            "n_annual_reports": n_annual, "is_current_listed": bool(sub.get("tickers")),
        })
        for n, a, b in periods:
            out["names"].append({"cik": cik, "name": n, "valid_from": a, "valid_to": b, "knowable_at": a})
        for t in tags:
            out["industries"].append({"cik": cik, **t, "knowable_at": t["valid_from"]})
        cur_start = periods[-1][1]
        exch = sub.get("exchanges") or []
        for i, tk in enumerate(sub.get("tickers") or []):
            out["tickers"].append({"cik": cik, "ticker": tk, "exchange": exch[i] if i < len(exch) else None,
                                   "valid_from": cur_start, "valid_to": None, "source": "sec_current",
                                   "knowable_at": cur_start})

        acc = pd.to_datetime(fil["acceptanceDateTime"], utc=True, errors="coerce")
        fallback = (fil["filingDate"] + pd.Timedelta(hours=22)).dt.tz_localize("UTC")
        fil["knowable_at"] = acc.fillna(fallback)
        fil["acceptance"] = acc
        fil["reportDate"] = pd.to_datetime(fil["reportDate"], errors="coerce")
        fil = fil.rename(columns={"accessionNumber": "accession", "filingDate": "filing_date",
                                  "reportDate": "report_date", "primaryDocument": "primary_doc",
                                  "size": "size_bytes"})
        fil = fil[["cik", "accession", "form", "filing_date", "report_date", "acceptance", "items",
                   "primary_doc", "size_bytes", "knowable_at"]]
        out["filings"].append(fil)
        for r in fil.itertuples(index=False):
            for et in classify_filing(r.form or "", r.items):
                out["events"].append({"cik": cik, "event_type": et, "event_date": r.filing_date,
                                      "form": r.form, "accession": r.accession,
                                      "knowable_at": r.knowable_at})
    res = {}
    for k, v in out.items():
        if k == "filings":
            res[k] = pd.concat(v, ignore_index=True) if v else pd.DataFrame()
        else:
            res[k] = pd.DataFrame(v)
    return res


def _index_chunk(args):
    names, zip_path = args
    z = zipfile.ZipFile(zip_path)
    rows = []
    for fname in names:
        sub = json.loads(z.read(fname))
        former = [f["name"] for f in sub.get("formerNames") or []]
        rows.append({"cik": int(sub["cik"]), "name": sub.get("name"), "former_names": former,
                     "tickers": sub.get("tickers") or [], "sic": sub.get("sic"),
                     "entity_type": sub.get("entityType")})
    return pd.DataFrame(rows)


def build_index(zip_path: Path = SUBMISSIONS_ZIP, out: Path = DATA_DIR / "db" / "sec_index.parquet",
                workers: int = 4) -> pd.DataFrame:
    """Name/ticker index of every EDGAR filer, for matching research seeds."""
    z = zipfile.ZipFile(zip_path)
    mains = [n for n in z.namelist() if n.endswith(".json") and "-submissions-" not in n]
    chunks = [(mains[i:i + 5000], str(zip_path)) for i in range(0, len(mains), 5000)]
    with ProcessPoolExecutor(workers) as ex:
        df = pd.concat(ex.map(_index_chunk, chunks), ignore_index=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def add_companies(ciks, zip_path: Path = SUBMISSIONS_ZIP, db_path: Path = DB_PATH) -> dict:
    """Force-add specific CIKs (e.g. from research) regardless of SIC/keyword rules."""
    con = connect(db_path)
    have = set(con.execute("SELECT cik FROM companies").df()["cik"].astype(int))
    ciks = sorted(set(int(c) for c in ciks) - have)
    if not ciks:
        con.close()
        return {"added": 0}
    names = [f"CIK{c:010d}.json" for c in ciks]
    z = zipfile.ZipFile(zip_path)
    present = set(z.namelist())
    names = [n for n in names if n in present]
    res = _process_chunk((names, str(zip_path), ciks))
    counts = {}
    for key, df in res.items():
        if df.empty:
            continue
        table = KEY_TO_TABLE[key]
        df = df[TABLE_COLS[table]].copy()
        _to_utc(df, ["knowable_at", "acceptance"])
        if table == "companies":
            df["built_at"] = pd.Timestamp.now(tz="UTC").tz_localize(None)
            con.register("df_in", df)
            con.execute("INSERT INTO companies SELECT * FROM df_in")
        else:
            cols = ", ".join(TABLE_COLS[table])
            con.register("df_in", df)
            con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM df_in")
        con.unregister("df_in")
        counts[table] = len(df)
    con.close()
    return {"added": counts.get("companies", 0), **counts}


TABLE_COLS = {
    "companies": ["cik", "name", "sic", "sic_description", "entity_type", "filer_category",
                  "state_of_inc", "fiscal_year_end", "current_tickers", "current_exchanges",
                  "first_filing", "last_filing", "n_filings", "n_annual_reports", "is_current_listed"],
    "company_names": ["cik", "name", "valid_from", "valid_to", "knowable_at"],
    "company_industries": ["cik", "industry", "sub_industry", "method", "matched", "confidence",
                           "valid_from", "valid_to", "knowable_at"],
    "tickers": ["cik", "ticker", "exchange", "valid_from", "valid_to", "source", "knowable_at"],
    "filings": ["cik", "accession", "form", "filing_date", "report_date", "acceptance", "items",
                "primary_doc", "size_bytes", "knowable_at"],
    "events": ["cik", "event_type", "event_date", "form", "accession", "knowable_at"],
}
KEY_TO_TABLE = {"companies": "companies", "names": "company_names", "industries": "company_industries",
                "tickers": "tickers", "filings": "filings", "events": "events"}


def _to_utc(df, cols):
    for c in cols:
        if c in df.columns:
            s = pd.to_datetime(df[c], utc=True, errors="coerce")
            df[c] = s
    return df


def build(zip_path: Path = SUBMISSIONS_ZIP, db_path: Path = DB_PATH, workers: int = 4,
          chunk: int = 4000, limit: int | None = None) -> dict:
    t0 = time.time()
    z = zipfile.ZipFile(zip_path)
    mains = [n for n in z.namelist() if n.endswith(".json") and "-submissions-" not in n]
    if limit:
        mains = mains[:limit]
    chunks = [(mains[i:i + chunk], str(zip_path)) for i in range(0, len(mains), chunk)]
    con = connect(db_path)
    for t in KEY_TO_TABLE.values():
        con.execute(f"DELETE FROM {t}")
    counts = {t: 0 for t in KEY_TO_TABLE.values()}
    with ProcessPoolExecutor(workers) as ex:
        for k, res in enumerate(ex.map(_process_chunk, chunks)):
            for key, df in res.items():
                if df.empty:
                    continue
                table = KEY_TO_TABLE[key]
                df = df[TABLE_COLS[table]].copy()
                _to_utc(df, ["knowable_at", "acceptance"])
                if table == "companies":
                    df["built_at"] = pd.Timestamp.now(tz="UTC").tz_localize(None)
                    con.register("df_in", df)
                    con.execute("INSERT INTO companies SELECT * FROM df_in")
                else:
                    con.register("df_in", df)
                    cols = ", ".join(TABLE_COLS[table])
                    con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM df_in")
                con.unregister("df_in")
                counts[table] += len(df)
            if k % 25 == 0:
                print(f"  chunk {k + 1}/{len(chunks)}  companies={counts['companies']:,}  "
                      f"filings={counts['filings']:,}  {time.time() - t0:.0f}s", flush=True)
    con.close()
    counts["seconds"] = round(time.time() - t0)
    return counts


if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(build(limit=lim))
