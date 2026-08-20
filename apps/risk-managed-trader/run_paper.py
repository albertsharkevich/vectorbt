#!/usr/bin/env python3
"""Daily paper-trading runner.

Run this once per day, after market close. It uses the exact same
strategy.py signal logic and risk.py RiskManager as the backtest, applied to
real (delayed, free) market data -- no broker connection, no real money.

Execution model matches the backtest: a signal computed from day T's close is
"pending" and gets filled at day T+1's open on the *next* invocation of this
script. State (cash, positions, pending signals, trade log) persists to a
JSON file between runs so paper trading accumulates day over day.

This intentionally does not talk to Robinhood or any broker. See
broker.py:RobinhoodBroker for exactly what would need to be connected before
any of this could place a real order.
"""
import argparse
import json
from pathlib import Path

import pandas as pd

import fees as fees_mod
from config import RiskConfig
from data import fetch_ohlcv
from risk import RiskManager
from strategy import generate_signals

DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT"]
ATR_STOP_MULT = 2.5


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"risk_manager": None, "pending": {}, "last_date": None}


def save_state(path: Path, state: dict):
    path.write_text(json.dumps(state, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Run one day of paper trading.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE)
    parser.add_argument("--state-file", default="paper_state.json")
    args = parser.parse_args()

    state_path = Path(args.state_file)
    state = load_state(state_path)
    config = RiskConfig()
    rm = RiskManager.from_state(config, state["risk_manager"]) if state["risk_manager"] else RiskManager(config)
    pending = state.get("pending", {})  # symbol -> {"action": "buy"/"sell", "stop_loss": float}

    bars = {}
    for symbol in args.symbols:
        df = fetch_ohlcv(symbol, period="1y")
        if df.empty:
            print(f"WARNING: no data for {symbol}, skipping")
            continue
        bars[symbol] = df

    today = max(df.index[-1] for df in bars.values())
    if str(today) == state.get("last_date"):
        print(f"{today.date()} already processed; nothing to do. Run again after the next close.")
        return

    marks = {s: df.loc[today, "close"] for s, df in bars.items() if today in df.index}

    # 1. Fill anything pending from the previous run at today's open.
    for symbol, order in list(pending.items()):
        if symbol not in bars or today not in bars[symbol].index:
            continue
        today_open = bars[symbol].loc[today, "open"]
        if order["action"] == "buy":
            fill = fees_mod.apply_slippage(today_open, "buy", config)
            position, reason = rm.open_position(symbol, today, fill, order["stop_loss"], marks)
            if position is None:
                print(f"  {symbol}: entry skipped -- {reason}")
            else:
                print(f"  {symbol}: bought {position.shares} @ {fill:.2f}, stop {position.stop_loss:.2f}")
        elif order["action"] == "sell" and symbol in rm.positions:
            fill = fees_mod.apply_slippage(today_open, "sell", config)
            position = rm.positions[symbol]
            reg_fee = fees_mod.sell_regulatory_fees(position.shares * fill, position.shares, config)
            pnl = rm.close_position(symbol, today, fill, marks, fees=reg_fee, reason="signal_exit")
            print(f"  {symbol}: sold @ {fill:.2f}, pnl {pnl:.2f}")
        del pending[symbol]

    # 2. Check stop-losses against today's low for anything still open.
    for symbol in list(rm.positions.keys()):
        if symbol not in bars or today not in bars[symbol].index:
            continue
        bar = bars[symbol].loc[today]
        position = rm.positions[symbol]
        if bar["low"] <= position.stop_loss:
            raw_fill = position.stop_loss if bar["open"] > position.stop_loss else bar["open"]
            fill = fees_mod.apply_slippage(raw_fill, "sell", config)
            reg_fee = fees_mod.sell_regulatory_fees(position.shares * fill, position.shares, config)
            pnl = rm.close_position(symbol, today, fill, marks, fees=reg_fee, reason="stop_loss")
            print(f"  {symbol}: STOPPED OUT @ {fill:.2f}, pnl {pnl:.2f}")

    # 3. Compute today's signals; queue them as pending for the next run's open.
    new_pending = {}
    for symbol, df in bars.items():
        sig = generate_signals(df).iloc[-1]
        if symbol in rm.positions and bool(sig["exit"]):
            new_pending[symbol] = {"action": "sell"}
        elif symbol not in rm.positions and bool(sig["entry"]) and not pd.isna(sig["atr"]):
            stop_loss = sig["close"] - ATR_STOP_MULT * sig["atr"]
            new_pending[symbol] = {"action": "buy", "stop_loss": stop_loss}

    if rm.halted_today():
        skipped = [s for s, o in new_pending.items() if o["action"] == "buy"]
        for symbol in skipped:
            del new_pending[symbol]
        if skipped:
            print(f"  Daily loss limit hit -- not queuing new entries for {skipped}")

    equity = rm.equity(marks)
    print(f"\n{today.date()}: equity=${equity:,.2f} cash=${rm.cash:,.2f} "
          f"positions={list(rm.positions)} queued_for_next_open={new_pending}")

    save_state(
        state_path,
        {"risk_manager": rm.to_state(), "pending": new_pending, "last_date": str(today)},
    )


if __name__ == "__main__":
    main()
