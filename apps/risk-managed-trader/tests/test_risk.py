import pytest

from config import RiskConfig
from risk import RiskManager, RiskViolation


def make_rm(**overrides):
    return RiskManager(RiskConfig(**overrides))


def test_position_sizing_respects_risk_per_trade_pct():
    rm = make_rm(starting_capital=1000.0, max_risk_per_trade_pct=0.01, max_position_pct=1.0)
    entry, stop = 100.0, 98.0  # $2/share risk
    position, reason = rm.open_position("AAA", "2024-01-01", entry, stop, marks={})
    assert reason is None
    # risk budget = 1% of 1000 = $10; stop distance = $2 -> 5 shares
    assert position.shares == 5


def test_position_notional_capped_by_max_position_pct():
    rm = make_rm(starting_capital=1000.0, max_risk_per_trade_pct=1.0, max_position_pct=0.5)
    # huge risk pct would size far more shares than the notional cap allows
    entry, stop = 10.0, 9.9
    position, reason = rm.open_position("AAA", "2024-01-01", entry, stop, marks={})
    assert reason is None
    assert position.shares * entry <= 1000.0 * 0.5 + 1e-6


def test_no_leverage_caps_shares_to_available_cash():
    rm = make_rm(starting_capital=100.0, max_risk_per_trade_pct=1.0, max_position_pct=1.0, allow_leverage=False)
    entry, stop = 10.0, 9.99
    position, reason = rm.open_position("AAA", "2024-01-01", entry, stop, marks={})
    assert reason is None
    assert position.shares * entry <= 100.0 + 1e-6


def test_every_order_requires_a_stop_loss_below_entry():
    rm = make_rm()
    with pytest.raises(RiskViolation):
        rm.size_order(entry_price=100.0, stop_loss=None, marks={})
    with pytest.raises(RiskViolation):
        rm.size_order(entry_price=100.0, stop_loss=105.0, marks={})  # stop above entry


def test_no_averaging_down_blocks_second_entry_in_same_symbol():
    rm = make_rm(starting_capital=10_000.0)
    rm.open_position("AAA", "2024-01-01", 100.0, 95.0, marks={})
    position, reason = rm.open_position("AAA", "2024-01-01", 90.0, 85.0, marks={"AAA": 90.0})
    assert position is None
    assert "averaging down" in reason


def test_max_trades_per_day_enforced():
    rm = make_rm(starting_capital=100_000.0, max_trades_per_day=2)
    rm.open_position("AAA", "2024-01-01", 10.0, 9.0, marks={})
    rm.open_position("BBB", "2024-01-01", 10.0, 9.0, marks={"AAA": 10.0})
    position, reason = rm.open_position("CCC", "2024-01-01", 10.0, 9.0, marks={"AAA": 10.0, "BBB": 10.0})
    assert position is None
    assert "max trades per day" in reason


def test_trade_count_resets_on_new_day():
    rm = make_rm(starting_capital=100_000.0, max_trades_per_day=1)
    rm.open_position("AAA", "2024-01-01", 10.0, 9.0, marks={})
    position, reason = rm.open_position("BBB", "2024-01-01", 10.0, 9.0, marks={"AAA": 10.0})
    assert position is None

    position, reason = rm.open_position("BBB", "2024-01-02", 10.0, 9.0, marks={"AAA": 10.0})
    assert position is not None


def test_daily_loss_circuit_breaker_halts_new_entries():
    rm = make_rm(starting_capital=1000.0, max_daily_loss_pct=0.02, max_trades_per_day=10)
    position, _ = rm.open_position("AAA", "2024-01-01", 100.0, 99.0, marks={})
    assert position is not None
    # Close it at a loss big enough to breach the 2% daily loss limit.
    rm.close_position("AAA", "2024-01-01", 70.0, marks={"AAA": 70.0}, reason="stop_loss")
    assert rm.halted_today()

    position, reason = rm.open_position("BBB", "2024-01-01", 10.0, 9.0, marks={})
    assert position is None
    assert "daily loss" in reason


def test_daily_loss_halt_clears_on_new_day():
    rm = make_rm(starting_capital=1000.0, max_daily_loss_pct=0.02, max_trades_per_day=10)
    rm.open_position("AAA", "2024-01-01", 100.0, 99.0, marks={})
    rm.close_position("AAA", "2024-01-01", 70.0, marks={"AAA": 70.0}, reason="stop_loss")
    assert rm.halted_today()

    position, reason = rm.open_position("BBB", "2024-01-02", 10.0, 9.0, marks={})
    assert position is not None


def test_fractional_sizing_lets_small_accounts_trade_expensive_symbols():
    # $750 account, 1% risk, SPY-like price with a wide ATR stop: whole-share
    # sizing would round this down to zero shares and never trade at all.
    rm = make_rm(starting_capital=750.0, max_risk_per_trade_pct=0.01, allow_fractional_shares=True)
    entry, stop = 550.0, 530.0  # $20/share risk -> $7.5 budget / $20 = 0.375 shares
    position, reason = rm.open_position("SPY", "2024-01-01", entry, stop, marks={})
    assert reason is None
    assert position is not None
    assert 0.37 < position.shares < 0.38


def test_whole_share_only_rounds_expensive_symbol_down_to_zero():
    rm = make_rm(starting_capital=750.0, max_risk_per_trade_pct=0.01, allow_fractional_shares=False)
    position, reason = rm.open_position("SPY", "2024-01-01", 550.0, 530.0, marks={})
    assert position is None
    assert "zero shares" in reason


def test_state_roundtrip_preserves_cash_and_positions():
    rm = make_rm(starting_capital=1000.0)
    rm.open_position("AAA", "2024-01-01", 100.0, 95.0, marks={})
    state = rm.to_state()

    restored = RiskManager.from_state(RiskConfig(starting_capital=1000.0), state)
    assert restored.cash == rm.cash
    assert restored.positions.keys() == rm.positions.keys()
    assert restored.positions["AAA"].shares == rm.positions["AAA"].shares
