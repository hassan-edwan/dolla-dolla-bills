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

# Older PDFs render in small caps, so pdftotext yields mixed case ("apple Inc. (aaPl)"):
# match case-insensitively and upper-case the ticker afterwards.
LINE = re.compile(
    r"^\s*(?P<owner>SP|JT|DC)?\s+(?P<asset>.+?)\s*\((?P<ticker>[A-Za-z][A-Za-z0-9.\-]{0,6})\)\s*"
    r"(?:\[(?P<atype>[A-Za-z]{2})\])?\s+(?P<type>P|S \(partial\)|S|E)\s+"
    r"(?P<tdate>\d{1,2}/\d{1,2}/\d{4})\s+(?P<ndate>\d{1,2}/\d{1,2}/\d{4})\s+(?P<amt>.+?)\s*$", re.I)
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
            mm = re.search(r"\[([A-Za-z]{2})\]", lines[i + 1])
            atype = mm.group(1) if mm else None
        out.append({
            "owner": (m.group("owner") or "self").upper() if m.group("owner") else "self",
            "asset_name": m.group("asset").strip(),
            "ticker": m.group("ticker").upper(),
            "asset_type": atype.upper() if atype else None,
            "transaction_type": {"P": "buy", "S": "sell", "S (PARTIAL)": "sell_partial", "E": "exchange"}[m.group("type").upper()],
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


# ---------------------------------------------------------------- Senate (eFD)
SENATE = "https://efdsearch.senate.gov"
AMT_TYPES = {"Purchase": "buy", "Sale (Full)": "sell", "Sale (Partial)": "sell_partial",
             "Sale": "sell", "Exchange": "exchange"}


def _senate_session():
    """The user approved accepting eFD's access agreement for personal research use."""
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    home = s.get(f"{SENATE}/search/home/", timeout=60).text
    tok = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home).group(1)
    s.post(f"{SENATE}/search/home/", data={"prohibition_agreement": "1", "csrfmiddlewaretoken": tok},
           headers={"Referer": f"{SENATE}/search/home/"}, timeout=60)
    return s


def _senate_reports(s, start="01/01/2012 00:00:00"):
    end = pd.Timestamp.now().strftime("%m/%d/%Y 23:59:59")
    out, offset = [], 0
    while True:
        csrf = s.cookies.get("csrftoken")
        d = s.post(f"{SENATE}/search/report/data/", timeout=60,
                   headers={"Referer": f"{SENATE}/search/", "X-CSRFToken": csrf},
                   data={"start": str(offset), "length": "100", "report_types": "[11]", "filer_types": "[]",
                         "submitted_start_date": start, "submitted_end_date": end, "candidate_state": "",
                         "senator_state": "", "office_id": "", "first_name": "", "last_name": "",
                         "csrfmiddlewaretoken": csrf}).json()
        for first, last, full, link, filed in d["data"]:
            href = re.search(r'href="([^"]+)"', link).group(1)
            out.append({"member": f"{first} {last}".strip(), "filer": full, "href": href,
                        "filing_date": pd.to_datetime(filed, format="%m/%d/%Y", errors="coerce")})
        offset += 100
        if offset >= d["recordsTotal"]:
            return pd.DataFrame(out)
        time.sleep(0.5)


def parse_senate_table(html: str) -> list[dict]:
    tbody = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if not tbody:
        return []
    rows = []
    for tr in re.findall(r"<tr.*?>(.*?)</tr>", tbody.group(1), re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
                 for c in re.findall(r"<td.*?>(.*?)</td>", tr, re.S)]
        if len(cells) < 8:
            continue
        _, tdate, owner, ticker, asset, atype, ttype, amt = cells[:8]
        nums = [int(x.replace(",", "")) for x in AMOUNT.findall(amt)]
        rows.append({"owner": owner.lower() or "self", "asset_name": asset,
                     "ticker": ticker if ticker not in ("--", "") else None, "asset_type": atype,
                     "transaction_type": AMT_TYPES.get(ttype, ttype.lower()),
                     "trans_date": pd.to_datetime(tdate, format="%m/%d/%Y", errors="coerce"),
                     "notification_date": pd.NaT,
                     "amount_min": nums[0] if nums else None, "amount_max": nums[1] if len(nums) > 1 else None})
    return rows


def build_senate() -> dict:
    t0 = time.time()
    s = _senate_session()
    reports = _senate_reports(s)
    raw = DATA_DIR / "raw" / "senate"
    raw.mkdir(parents=True, exist_ok=True)
    rows, stats = [], {"reports": len(reports), "electronic": 0, "paper_needs_ocr": 0, "trades": 0}
    for k, r in enumerate(reports.itertuples(index=False)):
        if "/paper/" in r.href:
            stats["paper_needs_ocr"] += 1
            continue
        cache = raw / (r.href.strip("/").split("/")[-1] + ".html")
        if not cache.exists():
            resp = s.get(SENATE + r.href, timeout=60)
            if "prohibition_agreement" in resp.text:     # session expired: re-accept
                s = _senate_session()
                resp = s.get(SENATE + r.href, timeout=60)
            cache.write_text(resp.text)
            time.sleep(0.5)
        stats["electronic"] += 1
        for t in parse_senate_table(cache.read_text()):
            rows.append({**t, "chamber": "senate", "member": r.member, "state_district": None,
                         "doc_id": r.href.strip("/").split("/")[-1], "filing_date": r.filing_date,
                         "knowable_at": (r.filing_date + pd.Timedelta(days=1)).tz_localize("UTC"),
                         "disclosure_lag_days": (r.filing_date - t["trans_date"]).days if pd.notna(t["trans_date"]) else None,
                         "source_url": SENATE + r.href})
        if k % 200 == 0:
            print(f"  senate {k + 1}/{len(reports)} trades={len(rows):,} {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    if not df.empty:
        df.to_parquet(OUT / "senate_all.parquet", index=False)
    stats["trades"] = len(df)
    stats["seconds"] = round(time.time() - t0)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs=2, type=int, default=[2012, 2026])
    ap.add_argument("--senate", action="store_true", help="Senate only")
    a = ap.parse_args()
    print(build_senate() if a.senate else build(tuple(a.years)))
