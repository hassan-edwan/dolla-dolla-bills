"""Failure ledger: companies that went bust, delisted or were acquired.

With free data only, delisted tickers are mostly missing from price sources,
so backtests over-represent survivors. The ledger records each exit and
what a shareholder actually received (``terminal_value`` per share), so:

1. The simulator settles held positions at a realistic exit value instead
   of silently dropping them.
2. Training data can be balanced with failure examples (Phase 2).
3. The LLM research phase (Phase 5) can fill in unknown terminal values from
   8-K merger terms and bankruptcy outcomes.

Ledger CSV columns: symbol, cik, event_type, event_date, terminal_value, source, notes
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["symbol", "cik", "event_type", "event_date", "terminal_value", "source", "notes"]

# Default recovery when the event type is known but the terminal value is not.
DEFAULT_RECOVERY = {
    "bankruptcy": 0.0,
    "delisting_exchange": 0.2,     # forced delisting: usually falls to OTC near-worthless
    "delisting_notice": 0.3,
    "deregistration": 0.3,
    "delisting_voluntary": None,   # ambiguous (often an acquisition): use the unknown policy
    "acquisition_completed": 1.0,  # ~ last close; deal price is better when known
}


class FailureLedger:
    def __init__(self, df: pd.DataFrame | None = None):
        df = pd.DataFrame(columns=COLUMNS) if df is None else df.copy()
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = np.nan
        df["event_date"] = pd.to_datetime(df["event_date"])
        self.df = df[COLUMNS]

    @classmethod
    def load(cls, path: str | Path) -> "FailureLedger":
        path = Path(path)
        return cls(pd.read_csv(path) if path.exists() else None)

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(path, index=False)

    def add(self, **row) -> None:
        self.df = pd.concat([self.df, pd.DataFrame([row])], ignore_index=True)
        self.df["event_date"] = pd.to_datetime(self.df["event_date"])

    def exit_value(self, symbol: str, last_close: float, unknown_recovery: float) -> tuple[float, str]:
        """Per-share value a holder receives when `symbol` stops trading."""
        rows = self.df[self.df["symbol"] == symbol].sort_values("event_date")
        if rows.empty:
            return last_close * unknown_recovery, "unknown_exit"
        r = rows.iloc[-1]
        if pd.notna(r["terminal_value"]):
            return float(r["terminal_value"]), str(r["event_type"])
        rec = DEFAULT_RECOVERY.get(r["event_type"])
        if rec is None:
            rec = unknown_recovery
        return last_close * rec, str(r["event_type"])

    def merge_edgar_exits(self, exits: pd.DataFrame, still_listed_ciks=()) -> int:
        """Add rows from edgar.exit_filings() that aren't already in the ledger.

        Form 25/15 filings also cover a company's notes, warrants, preferreds and
        exchange transfers. A company that still has a current ticker did not
        fail, so it is excluded. The symbol is left blank: delisted companies have no
        current ticker, and historical tickers are resolved later (Phase 2/5).
        """
        exits = exits[~exits["cik"].isin(set(still_listed_ciks))]
        n0 = len(self.df)
        new = pd.DataFrame({
            "symbol": np.nan,
            "cik": exits["cik"],
            "event_type": exits["event_type"],
            "event_date": exits["date_filed"],
            "terminal_value": np.nan,
            "source": "edgar:" + exits["form"],
            "notes": exits["company"],
        })
        self.df = pd.concat([self.df, new], ignore_index=True).drop_duplicates(
            subset=["cik", "event_type", "event_date"])
        return len(self.df) - n0
