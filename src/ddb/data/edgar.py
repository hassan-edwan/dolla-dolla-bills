"""SEC EDGAR (free): company metadata, filings, XBRL fundamentals, failure signals.

- ``form_index`` parses the quarterly full index, which lists EVERY filing,
  including those from companies that later disappeared. This is how
  delisted and bankrupt companies get into the training universe.
- ``company_facts_pit`` turns XBRL facts into PIT records with
  knowable_at = filing date + 1 day (conservative, because XBRL facts carry only a date).
- ``filing_events`` extracts failure/corporate-event signals from 8-K items
  and form types.
"""
from __future__ import annotations

import re

import pandas as pd

from .http import RateLimitedSession, sec_user_agent

FULL_INDEX = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"

# Form types that signal a company leaving public markets.
EXIT_FORMS = {
    "25": "delisting_voluntary",
    "25-NSE": "delisting_exchange",
    "15-12B": "deregistration",
    "15-12G": "deregistration",
    "15-15D": "deregistration",
}
# 8-K items worth flagging. Failures and dilution weigh heavily in this universe.
EIGHT_K_ITEMS = {
    "1.03": "bankruptcy",
    "2.01": "acquisition_completed",
    "3.01": "delisting_notice",
    "3.02": "unregistered_equity_sale",   # dilution
    "4.02": "non_reliance_restatement",
    "4.01": "auditor_change",
    "5.01": "change_in_control",
    "5.02": "officer_director_change",
}
DILUTION_FORMS = {"S-3": "shelf_registration", "S-3ASR": "shelf_registration",
                  "424B5": "offering_prospectus", "S-1": "registration"}
# Other forms that carry signal.
OTHER_FORMS = {
    "NT 10-K": "late_annual_report",     # distress / accounting trouble
    "NT 10-Q": "late_quarterly_report",
    "SC 13D": "activist_or_control_stake",
    "SC TO-T": "tender_offer",
    "DEFM14A": "merger_proxy",
    "S-4": "merger_registration",
    "10-12B": "spin_off_registration",
}

_IDX_LINE = re.compile(r"^(\S.*?)\s{2,}(.+?)\s{2,}(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s*$")

# The SEC fair-access policy allows 10 requests/second; stay well under it.
_session: RateLimitedSession | None = None


def _sec() -> RateLimitedSession:
    global _session
    if _session is None:
        _session = RateLimitedSession(min_interval_s=0.15, user_agent=sec_user_agent())
    return _session


def parse_form_index(text: str) -> pd.DataFrame:
    rows = []
    started = False
    for line in text.splitlines():
        if line.startswith("-----"):
            started = True
            continue
        if not started:
            continue
        m = _IDX_LINE.match(line)
        if m:
            form, name, cik, date, fname = m.groups()
            rows.append((form.strip(), name.strip(), int(cik), date, fname))
    df = pd.DataFrame(rows, columns=["form", "company", "cik", "date_filed", "file"])
    df["date_filed"] = pd.to_datetime(df["date_filed"])
    return df


def form_index(year: int, quarter: int) -> pd.DataFrame:
    return parse_form_index(_sec().get(FULL_INDEX.format(year=year, q=quarter)).text)


def exit_filings(years, quarters=(1, 2, 3, 4)) -> pd.DataFrame:
    """All delisting/deregistration filings across the given years."""
    frames = []
    for y in years:
        for q in quarters:
            try:
                idx = form_index(y, q)
            except Exception:  # noqa: BLE001 - future quarters 404
                continue
            hit = idx[idx["form"].isin(EXIT_FORMS)].copy()
            hit["event_type"] = hit["form"].map(EXIT_FORMS)
            frames.append(hit)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def submissions(cik: int) -> dict:
    return _sec().get(SUBMISSIONS.format(cik=cik)).json()


def current_tickers() -> pd.DataFrame:
    """CURRENT ticker->CIK map only (survivorship-biased; use for live names)."""
    data = _sec().get(COMPANY_TICKERS).json()
    return pd.DataFrame(data.values()).rename(columns={"cik_str": "cik", "title": "company"})


def filings_frame(sub: dict) -> pd.DataFrame:
    """Recent filings from a submissions JSON (the ~1000 most recent).

    Older pages are listed under sub['filings']['files'] and can be fetched
    the same way when deeper history is needed.
    """
    recent = sub["filings"]["recent"]
    df = pd.DataFrame(recent)
    if df.empty:
        return df
    df["acceptance"] = pd.to_datetime(df["acceptanceDateTime"], utc=True, errors="coerce")
    df["filingDate"] = pd.to_datetime(df["filingDate"])
    return df


def classify_filing(form: str, items) -> list[str]:
    """Event types implied by one filing (form + 8-K items)."""
    types = []
    for table in (EXIT_FORMS, DILUTION_FORMS, OTHER_FORMS):
        if form in table:
            types.append(table[form])
    if form.startswith("8-K") and isinstance(items, str) and items:
        types += [EIGHT_K_ITEMS[i.strip()] for i in items.split(",") if i.strip() in EIGHT_K_ITEMS]
    return types


def filing_events(sub: dict) -> pd.DataFrame:
    """Failure, exit and dilution signals for one company, as dated events."""
    df = filings_frame(sub)
    cols = ["cik", "company", "event_type", "event_date", "knowable_at", "form", "accession"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = []
    for r in df.itertuples(index=False):
        types = []
        if r.form in EXIT_FORMS:
            types.append(EXIT_FORMS[r.form])
        if r.form in DILUTION_FORMS:
            types.append(DILUTION_FORMS[r.form])
        if r.form in OTHER_FORMS:
            types.append(OTHER_FORMS[r.form])
        if r.form.startswith("8-K") and isinstance(r.items, str):
            types += [EIGHT_K_ITEMS[i.strip()] for i in r.items.split(",") if i.strip() in EIGHT_K_ITEMS]
        for t in types:
            out.append({"cik": int(sub["cik"]), "company": sub.get("name"), "event_type": t,
                        "event_date": r.filingDate, "knowable_at": r.acceptance,
                        "form": r.form, "accession": r.accessionNumber})
    return pd.DataFrame(out, columns=cols)


def company_facts_pit(cik: int, entity: str | None = None,
                      concepts: list[str] | None = None) -> pd.DataFrame:
    """XBRL us-gaap facts as PIT records. Restatements become new versions."""
    facts = _sec().get(COMPANY_FACTS.format(cik=cik)).json()
    entity = entity or f"CIK{cik}"
    rows = []
    for concept, body in facts.get("facts", {}).get("us-gaap", {}).items():
        if concepts and concept not in concepts:
            continue
        for unit, obs in body.get("units", {}).items():
            for o in obs:
                if "filed" not in o or "end" not in o:
                    continue
                rows.append({
                    "entity": entity,
                    "field": f"{concept}[{unit}]{'' if o.get('fp') is None else ':' + str(o.get('fp'))}",
                    "period_end": o["end"],
                    "value": o["val"],
                    "knowable_at": pd.Timestamp(o["filed"], tz="UTC") + pd.Timedelta(days=1),
                    "source": f"edgar:{o.get('form')}:{o.get('accn')}",
                })
    return pd.DataFrame(rows, columns=["entity", "field", "period_end", "value", "knowable_at", "source"])
