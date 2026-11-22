import pandas as pd
import pytest

from ddb.sim.account import CashAccount

D = pd.Timestamp


def test_settlement_and_good_faith():
    a = CashAccount(0)
    a.deposit(1000)
    a.buy("AAA", 10, 1000, D("2024-01-02"))
    a.sell("AAA", 10, 1100, D("2024-01-03"), settle_date=D("2024-01-04"))
    assert a.settled == 0 and a.cash == 1100
    # Buy with unsettled proceeds -> lot can't be sold until 01-04.
    a.buy("BBB", 11, 1100, D("2024-01-03"))
    assert a.sellable_shares("BBB", D("2024-01-03")) == 0
    with pytest.raises(ValueError):
        a.sell("BBB", 11, 1100, D("2024-01-03"), settle_date=D("2024-01-04"))
    a.settle(D("2024-01-04"))
    assert a.sellable_shares("BBB", D("2024-01-04")) == 11


def test_wash_sale_repurchase_after_loss():
    a = CashAccount(10_000)
    a.buy("AAA", 10, 1000, D("2024-01-02"))
    gain = a.sell("AAA", 10, 800, D("2024-02-01"), D("2024-02-02"))
    assert gain == pytest.approx(-200)
    a.settle(D("2024-02-02"))
    a.buy("AAA", 10, 800, D("2024-02-15"))          # within 30 days -> wash
    assert a.wash_disallowed_total == pytest.approx(200)
    assert a.lots["AAA"][0].basis == pytest.approx(1000)
    assert a.realized_frame()["gain"].sum() == pytest.approx(0)


def test_no_wash_after_window():
    a = CashAccount(10_000)
    a.buy("AAA", 10, 1000, D("2024-01-02"))
    a.sell("AAA", 10, 800, D("2024-02-01"), D("2024-02-02"))
    a.settle(D("2024-02-02"))
    a.buy("AAA", 10, 800, D("2024-03-15"))
    assert a.wash_disallowed_total == 0
    assert a.realized_frame()["gain"].sum() == pytest.approx(-200)


def test_wash_sale_prior_replacement_buy():
    a = CashAccount(10_000)
    a.buy("AAA", 10, 1000, D("2024-01-02"))
    a.buy("AAA", 10, 800, D("2024-01-20"))           # replacement bought before loss sale
    gain = a.sell("AAA", 10, 800, D("2024-01-25"), D("2024-01-26"))  # FIFO sells the $1000 lot
    assert gain == pytest.approx(0)
    assert a.lots["AAA"][0].basis == pytest.approx(1000)


def test_fifo_and_terms():
    a = CashAccount(10_000)
    a.buy("AAA", 5, 500, D("2022-01-03"))
    a.buy("AAA", 5, 1000, D("2023-06-01"))
    a.settle(D("2023-06-02"))
    a.sell("AAA", 7, 1400, D("2023-07-03"), D("2023-07-05"))
    r = a.realized_frame()
    assert list(r["term"]) == ["long", "short"]
    assert r["gain"].iloc[0] == pytest.approx(500)     # 5*200 - 500
    assert r["gain"].iloc[1] == pytest.approx(0)       # 2*200 - 400
