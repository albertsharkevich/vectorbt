import numpy as np
import pandas as pd


def summarize(equity: pd.Series, trade_log: pd.DataFrame, trading_days_per_year=252) -> dict:
    equity = equity.dropna()
    returns = equity.pct_change().dropna()

    total_return = equity.iloc[-1] / equity.iloc[0] - 1 if len(equity) > 1 else 0.0
    n_years = max(len(equity) / trading_days_per_year, 1e-9)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / n_years) - 1 if equity.iloc[0] > 0 else 0.0

    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    max_drawdown = drawdown.min() if len(drawdown) else 0.0

    sharpe = (
        np.sqrt(trading_days_per_year) * returns.mean() / returns.std()
        if returns.std() > 0
        else 0.0
    )

    closed = trade_log[trade_log["side"] == "sell"] if not trade_log.empty else trade_log
    n_trades = len(closed)
    wins = closed[closed["pnl"] > 0] if n_trades else closed
    losses = closed[closed["pnl"] <= 0] if n_trades else closed
    win_rate = len(wins) / n_trades if n_trades else 0.0
    gross_profit = wins["pnl"].sum() if len(wins) else 0.0
    gross_loss = -losses["pnl"].sum() if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    stop_outs = (closed["reason"] == "stop_loss").sum() if n_trades else 0

    return {
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "sharpe_ratio": sharpe,
        "num_trades": n_trades,
        "win_rate_pct": win_rate * 100,
        "profit_factor": profit_factor,
        "stop_loss_exits": int(stop_outs),
        "ending_equity": equity.iloc[-1] if len(equity) else float("nan"),
    }
