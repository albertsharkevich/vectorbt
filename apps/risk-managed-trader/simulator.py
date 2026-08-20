from dataclasses import dataclass

import pandas as pd

import fees as fees_mod
from risk import RiskManager
from strategy import generate_signals


@dataclass
class SimulationResult:
    equity: pd.Series
    trade_log: pd.DataFrame
    risk_manager: RiskManager


def run_backtest(data: dict, config, atr_stop_mult=2.5, **strategy_kwargs) -> SimulationResult:
    """Event-driven, day-by-day simulation across a universe of symbols.

    Execution model: a signal computed from bar T's close is acted on at bar
    T+1's open (no lookahead). Stop-losses are checked against each day's
    intraday low/open while a position is held. Every order flows through
    RiskManager, so position sizing, the daily trade cap, the daily loss
    circuit breaker, and the no-averaging-down rule are enforced identically
    to how paper/live trading would enforce them.
    """
    signals = {
        symbol: generate_signals(df, **strategy_kwargs).assign(
            entry=lambda s: s["entry"].shift(1).fillna(False),
            exit=lambda s: s["exit"].shift(1).fillna(False),
            signal_atr=lambda s: s["atr"].shift(1),
        )
        for symbol, df in data.items()
    }

    calendar = sorted(set().union(*(df.index for df in data.values())))
    rm = RiskManager(config)
    equity_curve = []

    for date in calendar:
        marks = {
            symbol: data[symbol].loc[date, "close"]
            for symbol in data
            if date in data[symbol].index
        }

        # 1. Stop-losses first: protect capital before anything else executes.
        for symbol in list(rm.positions.keys()):
            if date not in data[symbol].index:
                continue
            bar = data[symbol].loc[date]
            position = rm.positions[symbol]
            if bar["low"] <= position.stop_loss:
                raw_fill = position.stop_loss if bar["open"] > position.stop_loss else bar["open"]
                fill = fees_mod.apply_slippage(raw_fill, "sell", config)
                proceeds = position.shares * fill
                reg_fee = fees_mod.sell_regulatory_fees(proceeds, position.shares, config)
                rm.close_position(symbol, date, fill, marks, fees=reg_fee, reason="stop_loss")
                marks[symbol] = fill

        # 2. Signal-driven exits.
        for symbol in list(rm.positions.keys()):
            sig = signals[symbol]
            if date not in sig.index or not bool(sig.loc[date, "exit"]):
                continue
            if date not in data[symbol].index:
                continue
            raw_fill = data[symbol].loc[date, "open"]
            fill = fees_mod.apply_slippage(raw_fill, "sell", config)
            position = rm.positions[symbol]
            proceeds = position.shares * fill
            reg_fee = fees_mod.sell_regulatory_fees(proceeds, position.shares, config)
            rm.close_position(symbol, date, fill, marks, fees=reg_fee, reason="signal_exit")
            marks[symbol] = fill

        # 3. Signal-driven entries (subject to every risk-engine gate).
        for symbol in data:
            sig = signals[symbol]
            if date not in sig.index or not bool(sig.loc[date, "entry"]):
                continue
            if date not in data[symbol].index:
                continue
            atr_value = sig.loc[date, "signal_atr"]
            if pd.isna(atr_value):
                continue
            raw_fill = data[symbol].loc[date, "open"]
            fill = fees_mod.apply_slippage(raw_fill, "buy", config)
            stop_loss = fill - atr_stop_mult * atr_value
            commission = fees_mod.buy_commission(0, config)  # Robinhood: $0, kept for clarity/extensibility
            position, _reason = rm.open_position(symbol, date, fill, stop_loss, marks, fees=commission)
            if position is not None:
                marks[symbol] = fill

        equity_curve.append((date, rm.equity(marks)))

    equity_series = pd.Series(dict(equity_curve)).sort_index()
    equity_series.index.name = "date"
    trade_log = pd.DataFrame(rm.trade_log)
    return SimulationResult(equity=equity_series, trade_log=trade_log, risk_manager=rm)
