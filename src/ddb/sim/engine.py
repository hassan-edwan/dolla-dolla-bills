"""Event-driven daily backtester with realistic delay, costs and account rules.

Timeline for trading day t:
  1. Settle cash due on t.
  2. Execute orders decided at the close of t-1, at t's open (plus optional jitter
     toward t's typical price). Sells first, then buys.
  3. Handle exits: a held symbol whose data ended before t is settled at its
     failure-ledger exit value.
  4. Credit dividends with ex-date t.
  5. Mark to market at t's close.
  6. The strategy sees data up to and including t's close and returns target
     weights (or None = do nothing). Orders are queued for t+1.

The strategy can never see bar t+1 when deciding at t: MarketView slices it away.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from ..data.failures import FailureLedger
from ..data.prices import PriceData
from .account import CashAccount
from .costs import CostModel


def year_tax(st: float, lt: float, carry: float, st_rate: float, lt_rate: float):
    """One tax year with short/long netting and loss carryforward.

    Returns (tax, net_short, net_long, new_carry). carry <= 0. The $3k ordinary-income
    offset is ignored (conservative)."""
    st += carry
    if st < 0 and lt > 0:
        lt, st = max(lt + st, 0.0), min(lt + st, 0.0)
    elif lt < 0 and st > 0:
        st, lt = max(st + lt, 0.0), min(st + lt, 0.0)
    new_carry = 0.0
    if st + lt < 0:
        new_carry, st, lt = st + lt, 0.0, 0.0
    return st_rate * max(st, 0.0) + lt_rate * max(lt, 0.0), st, lt, new_carry


class MarketView:
    """Read-only window onto data up to and including the decision date."""

    def __init__(self, data: PriceData, i: int):
        self._data = data
        self._i = i

    @property
    def date(self) -> pd.Timestamp:
        return self._data.calendar[self._i]

    def history(self, field: str = "close", lookback: int | None = None) -> pd.DataFrame:
        frame = getattr(self._data, field)
        lo = 0 if lookback is None else max(0, self._i + 1 - lookback)
        return frame.iloc[lo:self._i + 1]

    def tradable(self) -> list[str]:
        row = self._data.close.iloc[self._i]
        return list(row.index[row.notna()])

    def bars_left_in_session(self) -> int:
        """Bars still to come today after this one (intraday data; 0 on daily data).
        An order decided now fills at the next bar's open, so to be flat at the close
        a strategy must sell while this is >= 1."""
        if not hasattr(self._data, "_pos_from_end"):
            self._data._pos_from_end = _session_helpers(self._data.calendar)[3]
        return int(self._data._pos_from_end[self._i])

    def is_period_end(self, freq: str) -> bool:
        """True on the last trading day of the week ('W'), month ('M') or quarter ('Q').

        Uses the trading calendar only (known in advance), not future prices.
        """
        cal = self._data.calendar
        if self._i + 1 >= len(cal):
            return True
        a, b = cal[self._i], cal[self._i + 1]
        if freq == "D":
            return a.normalize() != b.normalize()
        if freq == "W":
            return a.isocalendar()[:2] != b.isocalendar()[:2]
        if freq == "M":
            return (a.year, a.month) != (b.year, b.month)
        if freq == "Q":
            return (a.year, a.quarter) != (b.year, b.quarter)
        raise ValueError(freq)


def _session_helpers(cal: pd.DatetimeIndex):
    days = cal.normalize()
    first = np.r_[True, days[1:] != days[:-1]]
    last = np.r_[days[1:] != days[:-1], True]
    # bars left in the session after bar i (0 on the last bar)
    pos_from_end = pd.Series(1, index=range(len(cal))).groupby(days.to_numpy()).cumcount(ascending=False).to_numpy()
    return days, first, last, pos_from_end


@dataclass
class Portfolio:
    date: pd.Timestamp
    cash: float
    equity: float
    shares: dict
    weights: dict


class Strategy(Protocol):
    def decide(self, view: MarketView, portfolio: Portfolio) -> dict | None: ...


@dataclass
class SimSettings:
    initial_cash: float = 10_000.0
    fill: str = "open"             # "open" | "typical"
    jitter: float = 0.0
    seed: int = 7
    min_trade_value: float = 25.0
    fractional: bool = True
    settlement_days: int = 1
    wash_window_days: int = 30
    unknown_exit_recovery: float = 0.5
    short_term_tax_rate: float = 0.32
    long_term_tax_rate: float = 0.15
    pay_taxes: bool = True        # pay prior year's tax on the first trading day of each year
    # Intraday bars (minute / hour): the calendar holds bar END times. Settlement and
    # good-faith rules count trading DAYS, liquidity comes from prior sessions only,
    # and only a fill at the session's first bar pays the wider opening spread.
    intraday: bool = False

    @classmethod
    def from_config(cls, cfg: dict) -> "SimSettings":
        ex, acct, dl = cfg.get("execution", {}), cfg.get("account", {}), cfg.get("delisting", {})
        return cls(
            initial_cash=cfg.get("initial_cash", 10_000),
            fill=ex.get("fill", "open"), jitter=ex.get("jitter", 0.0), seed=ex.get("seed", 7),
            min_trade_value=ex.get("min_trade_value", 25),
            settlement_days=acct.get("settlement_days", 1),
            wash_window_days=acct.get("wash_sale_window_days", 30),
            short_term_tax_rate=acct.get("short_term_tax_rate", 0.32),
            long_term_tax_rate=acct.get("long_term_tax_rate", 0.15),
            pay_taxes=acct.get("pay_taxes", True),
            unknown_exit_recovery=dl.get("unknown_exit_recovery", 0.5),
        )


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    exits: pd.DataFrame
    realized: pd.DataFrame
    cancelled: pd.DataFrame
    wash_disallowed_total: float
    settings: SimSettings
    taxes_paid: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    weights: pd.DataFrame = field(default_factory=pd.DataFrame)

    def estimated_taxes(self) -> pd.DataFrame:
        """Rough yearly tax estimate with loss netting and carryforward."""
        r = self.realized
        if r.empty:
            return pd.DataFrame(columns=["year", "short", "long", "tax"])
        r = r.assign(year=pd.to_datetime(r["date"]).dt.year)
        g = r.pivot_table(index="year", columns="term", values="gain", aggfunc="sum").fillna(0.0)
        carry, rows = 0.0, []
        for year, row in g.iterrows():
            tax, st, lt, carry = year_tax(row.get("short", 0.0), row.get("long", 0.0), carry,
                                          self.settings.short_term_tax_rate,
                                          self.settings.long_term_tax_rate)
            rows.append({"year": year, "short": st, "long": lt, "tax": tax})
        return pd.DataFrame(rows)


class Backtester:
    def __init__(self, data: PriceData, strategy: Strategy, costs: CostModel | None = None,
                 settings: SimSettings | None = None, failures: FailureLedger | None = None):
        self.data = data
        self.strategy = strategy
        self.costs = costs or CostModel()
        self.s = settings or SimSettings()
        self.failures = failures or FailureLedger()
        self.rng = np.random.default_rng(self.s.seed)
        dollar_vol = data.close * data.volume
        if self.s.intraday:
            days, self._first_bar, _, _ = _session_helpers(data.calendar)
            daily_dv = dollar_vol.groupby(days.to_numpy()).sum(min_count=1)
            daily_close = data.close.groupby(days.to_numpy()).last()
            # prior sessions only: today's volume isn't known until the close
            self.adv = daily_dv.rolling(20, min_periods=1).mean().shift(1).reindex(days).set_axis(data.calendar)
            self.vol = (daily_close.pct_change(fill_method=None).rolling(20, min_periods=2).std().shift(1)
                        .reindex(days).set_axis(data.calendar))
            self._sessions = days.unique()
        else:
            self.adv = dollar_vol.rolling(20, min_periods=1).mean()
            self.vol = data.close.pct_change(fill_method=None).rolling(20, min_periods=2).std()
        self.mark = data.close.ffill()
        self._last_valid = {s: data.last_valid_date(s) for s in data.symbols}

    def _settle_date(self, i: int) -> pd.Timestamp:
        cal = self.data.calendar
        if self.s.intraday:   # T+n counts trading days; cash is usable from that day's open
            day = cal[i].normalize()
            j = int(self._sessions.searchsorted(day)) + self.s.settlement_days
            if j < len(self._sessions):
                return self._sessions[j]
            return self._sessions[-1] + pd.offsets.BDay(j - len(self._sessions) + 1)
        j = i + self.s.settlement_days
        if j < len(cal):
            return cal[j]
        return cal[-1] + pd.offsets.BDay(j - len(cal) + 1)

    def _fill_ref(self, sym: str, i: int) -> float:
        o = self.data.open.iat[i, self.data.close.columns.get_loc(sym)]
        if not math.isfinite(o):
            return float("nan")
        if self.s.fill == "typical":
            base = self._typical(sym, i)
            return base if math.isfinite(base) else o
        if self.s.jitter > 0:
            t = self._typical(sym, i)
            if math.isfinite(t):
                return o + self.rng.uniform(0, self.s.jitter) * (t - o)
        return o

    def _typical(self, sym: str, i: int) -> float:
        c = self.data.close.columns.get_loc(sym)
        return (self.data.high.iat[i, c] + self.data.low.iat[i, c] + self.data.close.iat[i, c]) / 3

    def run(self, start=None, end=None) -> BacktestResult:
        cal = self.data.calendar
        i0 = 0 if start is None else int(cal.searchsorted(pd.Timestamp(start)))
        i1 = len(cal) - 1 if end is None else int(cal.searchsorted(pd.Timestamp(end), side="right")) - 1
        acct = CashAccount(self.s.initial_cash, self.s.wash_window_days)
        orders: dict[str, float] = {}
        decided_i = None
        equity, trades, exits, cancelled, weights_log = {}, [], [], [], {}
        data_end = cal[-1]
        tax_due, carry, taxes_paid = 0.0, 0.0, {}
        year = cal[i0].year

        for i in range(i0, i1 + 1):
            d = cal[i]
            acct.settle(d)

            if self.s.pay_taxes:
                if d.year != year:
                    tax, carry = self._tax_for(acct, year, carry)
                    tax_due += tax
                    year = d.year
                if tax_due > 1e-6:
                    tax_due = self._pay_tax(acct, tax_due, i, trades, cancelled, taxes_paid)

            if orders:
                self._execute(acct, orders, i, decided_i, trades, cancelled)
                orders = {}

            # Exits: symbol had data, data stopped before d, and not because the dataset ends.
            for sym in list(acct.positions()):
                lv = self._last_valid[sym]
                if lv is not None and lv < d and lv < data_end:
                    last_close = float(self.mark.at[lv, sym])
                    px, kind = self.failures.exit_value(sym, last_close, self.s.unknown_exit_recovery)
                    if kind == "unknown_exit":
                        warnings.warn(f"{sym} stopped trading on {lv.date()} with no ledger entry; "
                                      f"assuming {self.s.unknown_exit_recovery:.0%} recovery")
                    qty = acct.shares(sym)
                    acct.sell(sym, qty, qty * px, d, self._settle_date(i), enforce_good_faith=False)
                    exits.append({"date": d, "symbol": sym, "shares": qty, "exit_price": px,
                                  "last_close": last_close, "kind": kind})

            # Dividends (ex-date d).
            for sym, qty in acct.positions().items():
                dv = self.data.dividends.at[d, sym]
                if dv:
                    acct.deposit(dv * qty)

            pos = acct.positions()
            mv = {s: q * float(self.mark.at[d, s]) for s, q in pos.items()}
            eq = acct.cash + sum(mv.values())
            equity[d] = eq
            weights_log[d] = {s: v / eq for s, v in mv.items()} if eq > 0 else {}

            if i == i1:
                break
            pf = Portfolio(d, acct.cash, eq, pos, weights_log[d])
            target = self.strategy.decide(MarketView(self.data, i), pf)
            if target is not None:
                orders = self._orders_from_target(target, pos, eq, d)
                decided_i = i

        return BacktestResult(
            equity=pd.Series(equity, name="equity"),
            trades=pd.DataFrame(trades),
            exits=pd.DataFrame(exits),
            realized=acct.realized_frame(),
            cancelled=pd.DataFrame(cancelled),
            wash_disallowed_total=acct.wash_disallowed_total,
            settings=self.s,
            taxes_paid=pd.Series(taxes_paid, name="tax", dtype=float),
            weights=pd.DataFrame.from_dict(weights_log, orient="index").fillna(0.0),
        )

    def _tax_for(self, acct: CashAccount, year: int, carry: float) -> tuple[float, float]:
        r = acct.realized_frame()
        r = r[pd.to_datetime(r["date"]).dt.year == year]
        st = r.loc[r["term"] == "short", "gain"].sum()
        lt = r.loc[r["term"] == "long", "gain"].sum()
        tax, _, _, carry = year_tax(st, lt, carry, self.s.short_term_tax_rate, self.s.long_term_tax_rate)
        return tax, carry

    def _pay_tax(self, acct, due, i, trades, cancelled, paid_log) -> float:
        """Pay what cash allows; if short, sell positions pro rata at today's open."""
        if acct.cash < due:
            pos = acct.positions()
            d = self.data.calendar[i]
            mv = sum(q * float(self.mark.at[d, s]) for s, q in pos.items())
            if mv > 0:
                frac = min(1.0, (due - acct.cash) * 1.03 / mv)
                orders = {s: -q * frac for s, q in pos.items()}
                self._execute(acct, orders, i, max(i - 1, 0), trades, cancelled)
        pay = min(due, max(acct.cash, 0.0))
        if pay > 0:
            acct.withdraw(pay, self.data.calendar[i])
            d = self.data.calendar[i]
            paid_log[d] = paid_log.get(d, 0.0) + pay
        return due - pay

    def _orders_from_target(self, target: dict, pos: dict, eq: float, d) -> dict:
        if any(w < -1e-12 for w in target.values()):
            raise ValueError("long-only: negative weights are not allowed")
        total = sum(target.values())
        if total > 1 + 1e-6:
            raise ValueError(f"weights sum to {total:.4f} > 1 (no leverage)")
        orders = {}
        for sym in set(target) | set(pos):
            px = float(self.mark.at[d, sym]) if sym in self.mark.columns else float("nan")
            if not math.isfinite(px) or px <= 0:
                continue
            want = target.get(sym, 0.0) * eq / px
            delta = want - pos.get(sym, 0.0)
            if abs(delta) * px >= self.s.min_trade_value or (want == 0 and pos.get(sym, 0) > 0):
                orders[sym] = delta
        return orders

    def _execute(self, acct: CashAccount, orders: dict, i: int, decided_i: int, trades, cancelled):
        d = self.data.calendar[i]
        settle = self._settle_date(i)
        adv = self.adv.iloc[decided_i]   # liquidity stats known at decision time
        vol = self.vol.iloc[decided_i]

        def prep(sym, qty):
            ref = self._fill_ref(sym, i)
            if not math.isfinite(ref) or ref <= 0:
                cancelled.append({"date": d, "symbol": sym, "qty": qty, "reason": "no_price"})
                return None
            a = float(adv.get(sym, np.nan))
            a = a if math.isfinite(a) else 0.0
            cap_value = self.costs.max_order_value(a)
            if abs(qty) * ref > cap_value:
                cancelled.append({"date": d, "symbol": sym, "qty": qty - math.copysign(cap_value / ref, qty),
                                  "reason": "participation_cap"})
                qty = math.copysign(cap_value / ref, qty)
            if not self.s.fractional:
                qty = math.copysign(math.floor(abs(qty)), qty)
            if abs(qty) < 1e-9:
                return None
            at_open = self.s.fill == "open" and (not self.s.intraday or bool(self._first_bar[i]))
            slip = self.costs.slippage_frac(abs(qty) * ref, a, float(vol.get(sym, np.nan)), at_open=at_open)
            return qty, ref, slip

        for sym, qty in orders.items():
            if qty >= 0:
                continue
            sellable = acct.sellable_shares(sym, d)
            if sellable < -qty - 1e-9:
                cancelled.append({"date": d, "symbol": sym, "qty": -qty - sellable, "reason": "good_faith"})
            p = prep(sym, -min(-qty, sellable))
            if p is None:
                continue
            q, ref, slip = p
            fill = ref * (1 - slip)
            proceeds = -q * fill - self.costs.commission_per_order
            gain = acct.sell(sym, -q, proceeds, d, settle)
            trades.append({"date": d, "symbol": sym, "side": "sell", "shares": -q, "ref": ref,
                           "fill": fill, "slippage_bps": slip * 1e4, "value": proceeds, "gain": gain})

        buys = []
        for sym, qty in orders.items():
            if qty <= 0:
                continue
            p = prep(sym, qty)
            if p is not None:
                buys.append((sym, *p))
        need = sum(q * ref * (1 + slip) + self.costs.commission_per_order for _, q, ref, slip in buys)
        scale = min(1.0, (acct.cash * 0.999) / need) if need > 0 else 1.0
        for sym, q, ref, slip in buys:
            q = q * scale
            if not self.s.fractional:
                q = math.floor(q)
            fill = ref * (1 + slip)
            cost = q * fill + self.costs.commission_per_order
            if q * fill < self.s.min_trade_value or cost > acct.cash:
                continue
            acct.buy(sym, q, cost, d)
            trades.append({"date": d, "symbol": sym, "side": "buy", "shares": q, "ref": ref,
                           "fill": fill, "slippage_bps": slip * 1e4, "value": -cost, "gain": 0.0})
