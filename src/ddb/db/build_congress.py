"""Congressional stock trades (STOCK Act Periodic Transaction Reports), free primary sources.

House: yearly index (disclosures-clerk.house.gov .../financial-pdfs/{YEAR}FD.zip)
       -> PTR PDFs (.../ptr-pdfs/{YEAR}/{DocID}.pdf), parsed with pdftotext.
       Scanned paper filings have no text layer and are logged as needs_ocr.

TIMING: members may disclose up to 45 days after the trade (often later).
knowable_at = the day AFTER the filing date (the PDF is published around the
filing date), never the transaction date.

    python -m ddb.db.build_congress [--years 2012 2026]
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import time
import zipfile

import pandas as pd

from ..config import DATA_DIR
from ..data.http import RateLimitedSession

RAW = DATA_DIR / "raw" / "house"
OUT = DATA_DIR / "db" / "politician_trades"
INDEX = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{y}FD.zip"
PTR = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{y}/{doc}.pdf"

LINE = re.compile(
    r"^\s*(?P<owner>SP|JT|DC)?\s+(?P<asset>.+?)\s*\((?P<ticker>[A-Z][A-Z0-9.\-]{0,6})\)\s*"
    r"(?:\[(?P<atype>[A-Z]{2})\])?\s+(?P<type>P|S \(partial\)|S|E)\s+"
    r"(?P<tdate>\d{2}/\d{2}/\d{4})\s+(?P<ndate>\d{2}/\d{2}/\d{4})\s+(?P<amt>.+?)\s*$")
AMOUNT = re.compile(r"\$([\d,]+)")


def parse_ptr_text(text: str) -> list[dict]:
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = LINE.match(line)
        if not m:
            continue
        amt = m.group("amt")
        if amt.rstrip().endswith("-") and i + 1 < len(lines):   # range wraps to the next line
            nxt = AMOUNT.findall(lines[i + 1])
            if nxt:
                amt = amt + " $" + nxt[-1]
        nums = [int(x.replace(",", "")) for x in AMOUNT.findall(amt)]
        atype = m.group("atype")
        if atype is None and i + 1 < len(lines):
            mm = re.search(r"\[([A-Z]{2})\]", lines[i + 1])
            atype = mm.group(1) if mm else None
        out.append({
            "owner": m.group("owner") or "self",
            "asset_name": m.group("asset").strip(),
            "ticker": m.group("ticker"),
            "asset_type": atype,
            "transaction_type": {"P": "buy", "S": "sell", "S (partial)": "sell_partial", "E": "exchange"}[m.group("type")],
            "trans_date": pd.to_datetime(m.group("tdate"), format="%m/%d/%Y", errors="coerce"),
            "notification_date": pd.to_datetime(m.group("ndate"), format="%m/%d/%Y", errors="coerce"),
            "amount_min": nums[0] if nums else None,
            "amount_max": nums[1] if len(nums) > 1 else None,
        })
    return out


def house_index(year: int, session) -> pd.DataFrame:
    path = RAW / f"{year}FD.zip"
    if not path.exists():
        path.write_bytes(session.get(INDEX.format(y=year)).content)
    z = zipfile.ZipFile(path)
    txt = z.read(f"{year}FD.txt").decode("utf-8", "ignore")
    df = pd.read_csv(io.StringIO(txt), sep="\t", dtype=str)
    return df[df["FilingType"] == "P"]


def build(years=(2012, 2026)) -> dict:
    t0 = time.time()
    session = RateLimitedSession(min_interval_s=0.35, user_agent="Mozilla/5.0", retries=3)
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "ptr").mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    stats = {"filings": 0, "parsed": 0, "needs_ocr": 0, "errors": 0, "trades": 0}
    log = []
    for y in range(years[0], years[1] + 1):
        idx = house_index(y, session)
        rows = []
        for r in idx.itertuples(index=False):
            stats["filings"] += 1
            pdf = RAW / "ptr" / f"{y}_{r.DocID}.pdf"
            try:
                if not pdf.exists():
                    pdf.write_bytes(session.get(PTR.format(y=y, doc=r.DocID)).content)
                text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True,
                                      text=True, timeout=60).stdout
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                log.append({"year": y, "doc_id": r.DocID, "status": "error", "detail": repr(exc)[:200]})
                continue
            trades = parse_ptr_text(text)
            if not text.strip():
                stats["needs_ocr"] += 1
                log.append({"year": y, "doc_id": r.DocID, "status": "needs_ocr", "detail": ""})
                continue
            stats["parsed"] += 1
            filed = pd.to_datetime(r.FilingDate, format="%m/%d/%Y", errors="coerce")
            name = " ".join(x for x in [r.First, r.Last, r.Suffix] if isinstance(x, str) and x)
            for t in trades:
                rows.append({**t, "chamber": "house", "member": name, "state_district": r.StateDst,
                             "doc_id": r.DocID, "filing_date": filed,
                             "knowable_at": (filed + pd.Timedelta(days=1)).tz_localize("UTC") if pd.notna(filed) else None,
                             "disclosure_lag_days": (filed - t["trans_date"]).days if pd.notna(filed) and pd.notna(t["trans_date"]) else None,
                             "source_url": PTR.format(y=y, doc=r.DocID)})
            if not trades:
                log.append({"year": y, "doc_id": r.DocID, "status": "no_trades_parsed", "detail": ""})
        df = pd.DataFrame(rows)
        if not df.empty:
            df.to_parquet(OUT / f"house_{y}.parquet", index=False)
        stats["trades"] += len(df)
        print(f"  {y}: {len(idx)} PTRs, {len(df):,} trades | totals {stats} {time.time() - t0:.0f}s", flush=True)
    pd.DataFrame(log).to_csv(DATA_DIR / "db" / "politician_parse_log.csv", index=False)
    stats["seconds"] = round(time.time() - t0)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs=2, type=int, default=[2012, 2026])
    a = ap.parse_args()
    print(build(tuple(a.years)))
