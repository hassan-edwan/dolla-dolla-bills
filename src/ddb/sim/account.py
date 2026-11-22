"""Cash brokerage account: T+N settlement, good-faith rule, FIFO tax lots, wash sales.

Good-faith rule (cash accounts): you may buy with unsettled sale proceeds, but
shares bought that way cannot be sold until those proceeds settle. Each lot
stores ``free_to_sell`` to enforce this.

Wash sales (approximation of IRS rules, 30 days either side):
- Selling at a loss when the same symbol was bought within the prior 30 days
  disallows the loss and adds it to the replacement lot's basis.
- Otherwise the loss stays "pending" for 30 days. A repurchase in that window
  reverses the loss and adds it to the new lot's basis.
Holding-period tacking is not modeled.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Lot:
    symbol: str
    shares: float
    basis: float              # total cost basis (incl. costs and wash adjustments)
    acquired: pd.Timestamp
    free_to_sell: pd.Timestamp
    wash_matched: float = 0.0  # shares already used as a wash-sale replacement


@dataclass
class PendingLoss:
    symbol: str
    loss_per_share: float     # positive number
    shares: float
    sale_date: pd.Timestamp


class CashAccount:
    def __init__(self, cash: float, wash_window_days: int = 30):
        self.settled = float(cash)
        self.unsettled: list[list] = []   # [settle_date, amount]
        self.lots: dict[str, list[Lot]] = {}
        self.pending_losses: list[PendingLoss] = []
        self.realized: list[dict] = []
        self.wash_window = pd.Timedelta(days=wash_window_days)
        self.wash_disallowed_total = 0.0

    # ---- cash -------------------------------------------------------------
    @property
    def cash(self) -> float:
        return self.settled + sum(a for _, a in self.unsettled)

    def settle(self, date: pd.Timestamp) -> None:
        keep = []
        for d, amt in self.unsettled:
            if d <= date:
                self.settled += amt
            else:
                keep.append([d, amt])
        self.unsettled = keep

    def deposit(self, amount: float) -> None:
        self.settled += amount

    def withdraw(self, amount: float, date: pd.Timestamp) -> None:
        """Remove cash (e.g. tax payments)."""
        self._spend(amount, date)

    def _spend(self, amount: float, date: pd.Timestamp) -> pd.Timestamp:
        """Spend cash; return the date the shares become free to sell (good-faith)."""
        if amount > self.cash + 1e-6:
            raise ValueError(f"insufficient cash: need {amount:.2f}, have {self.cash:.2f}")
        use = min(self.settled, amount)
        self.settled -= use
        rest = amount - use
        free = date
        self.unsettled.sort(key=lambda x: x[0])
        for chunk in self.unsettled:
            if rest <= 1e-12:
                break
            take = min(chunk[1], rest)
            chunk[1] -= take
            rest -= take
            free = max(free, chunk[0])
        self.unsettled = [c for c in self.unsettled if c[1] > 1e-9]
        return free

    # ---- positions --------------------------------------------------------
    def shares(self, symbol: str) -> float:
        return sum(l.shares for l in self.lots.get(symbol, []))

    def sellable_shares(self, symbol: str, date: pd.Timestamp) -> float:
        return sum(l.shares for l in self.lots.get(symbol, []) if l.free_to_sell <= date)

    def positions(self) -> dict[str, float]:
        return {s: self.shares(s) for s in self.lots if self.shares(s) > 1e-12}

    def buy(self, symbol: str, shares: float, total_cost: float, date: pd.Timestamp) -> None:
        if shares <= 0:
            return
        free = self._spend(total_cost, date)
        lot = Lot(symbol, shares, total_cost, date, free)
        # Repurchase inside the window of an earlier loss sale -> wash sale.
        remaining = shares
        for pl in self.pending_losses:
            if remaining <= 1e-12:
                break
            if pl.symbol != symbol or pl.shares <= 1e-12 or date - pl.sale_date > self.wash_window:
                continue
            m = min(pl.shares, remaining)
            disallowed = pl.loss_per_share * m
            pl.shares -= m
            remaining -= m
            lot.basis += disallowed
            lot.wash_matched += m
            self.wash_disallowed_total += disallowed
            self.realized.append({"date": date, "symbol": symbol, "gain": disallowed,
                                  "term": "short", "kind": "wash_reversal"})
        self.pending_losses = [p for p in self.pending_losses if p.shares > 1e-12]
        self.lots.setdefault(symbol, []).append(lot)

    def sell(self, symbol: str, shares: float, proceeds: float, date: pd.Timestamp,
             settle_date: pd.Timestamp, enforce_good_faith: bool = True) -> float:
        """FIFO sell. Returns realized gain (after wash adjustments)."""
        held = self.lots.get(symbol, [])
        avail = self.sellable_shares(symbol, date) if enforce_good_faith else self.shares(symbol)
        if shares > avail + 1e-9:
            raise ValueError(f"cannot sell {shares} {symbol}; sellable {avail}")
        px = proceeds / shares
        remaining = shares
        total_gain = 0.0
        sold_lot_ids = set()
        for lot in held:
            if remaining <= 1e-12:
                break
            if enforce_good_faith and lot.free_to_sell > date:
                continue
            take = min(lot.shares, remaining)
            basis_part = lot.basis * take / lot.shares
            gain = px * take - basis_part
            term = "long" if (date - lot.acquired).days > 365 else "short"
            lot.basis -= basis_part
            lot.shares -= take
            remaining -= take
            sold_lot_ids.add(id(lot))
            if gain < 0:
                gain = self._wash_on_loss_sale(symbol, -gain / take, take, date, sold_lot_ids)
            self.realized.append({"date": date, "symbol": symbol, "gain": gain, "term": term, "kind": "sale"})
            total_gain += gain
        self.lots[symbol] = [l for l in held if l.shares > 1e-12]
        if not self.lots[symbol]:
            del self.lots[symbol]
        self.unsettled.append([settle_date, proceeds])
        return total_gain

    def _wash_on_loss_sale(self, symbol, loss_per_share, shares, date, exclude_ids) -> float:
        """Match against replacement buys in the prior window; return the allowed (negative) gain."""
        remaining = shares
        for lot in self.lots.get(symbol, []):
            if remaining <= 1e-12:
                break
            if id(lot) in exclude_ids or lot.shares <= 1e-12:
                continue
            if date - lot.acquired > self.wash_window or lot.acquired > date:
                continue
            capacity = lot.shares - lot.wash_matched
            if capacity <= 1e-12:
                continue
            m = min(capacity, remaining)
            lot.basis += loss_per_share * m
            lot.wash_matched += m
            self.wash_disallowed_total += loss_per_share * m
            remaining -= m
        if remaining > 1e-12:
            self.pending_losses.append(PendingLoss(symbol, loss_per_share, remaining, date))
        return -loss_per_share * remaining

    def remove_position(self, symbol: str) -> float:
        """Drop all lots (e.g. worthless delisting). Returns the total basis written off."""
        basis = sum(l.basis for l in self.lots.pop(symbol, []))
        return basis

    def realized_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.realized, columns=["date", "symbol", "gain", "term", "kind"])
