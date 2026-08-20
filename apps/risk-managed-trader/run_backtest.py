#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

import data as data_mod
import stats as stats_mod
from config import RiskConfig
from simulator import run_backtest

DEFAULT_UNIVERSE = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT"]


def main():
    parser = argparse.ArgumentParser(description="Backtest the risk-managed small-account strategy.")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_UNIVERSE)
    parser.add_argument("--period", default="3y", help="Yahoo Finance range, e.g. 1y, 2y, 5y")
    parser.add_argument("--capital", type=float, default=None, help="Override starting_capital")
    parser.add_argument("--out", default="backtest_output", help="Directory to write CSV/JSON results")
    args = parser.parse_args()

    config = RiskConfig() if args.capital is None else RiskConfig(starting_capital=args.capital)

    print(f"Fetching {args.period} of daily data for {args.symbols}...")
    data = data_mod.fetch_universe(args.symbols, period=args.period)

    liquid = data_mod.liquidity_filter(data, config.min_avg_dollar_volume, config.liquidity_lookback)
    dropped = sorted(set(data) - set(liquid))
    if dropped:
        print(f"Dropping illiquid symbols (below ${config.min_avg_dollar_volume:,.0f}/day avg): {dropped}")
    data = {s: data[s] for s in liquid}
    if not data:
        print("No symbols passed the liquidity filter; nothing to backtest.", file=sys.stderr)
        sys.exit(1)

    result = run_backtest(data, config)

    summary = stats_mod.summarize(result.equity, result.trade_log)
    print("\n=== Backtest summary ===")
    for key, value in summary.items():
        print(f"{key:>20}: {value:,.4f}" if isinstance(value, float) else f"{key:>20}: {value}")

    print(f"\nEnded with {len(result.risk_manager.positions)} open position(s): "
          f"{list(result.risk_manager.positions)}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.equity.to_csv(out_dir / "equity_curve.csv", header=["equity"])
    result.trade_log.to_csv(out_dir / "trade_log.csv", index=False)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote equity_curve.csv, trade_log.csv, summary.json to {out_dir}/")


if __name__ == "__main__":
    main()
