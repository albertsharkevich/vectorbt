# Risk-Managed Small-Account Trader

A staged system for validating a mechanical trading strategy before risking
real money on it: **backtest -> paper trade -> small live capital**, with the
same risk engine enforced at every stage. This directory currently implements
the first two stages. It does not and cannot place real orders (see
[Live trading requirements](#live-trading-requirements) below).

## Hard risk controls

Every one of these lives in `config.py` as a `RiskConfig` field and is
enforced by `risk.py:RiskManager` -- not by convention, by code that rejects
orders that violate them:

| Rule | Enforcement |
|---|---|
| Start with $500-$1,000 | `starting_capital` |
| Risk no more than 7% of equity per trade | `max_risk_per_trade_pct`; position size = `(equity * 7%) / (entry - stop_loss)` |
| Max 2-3 trades per day | `max_trades_per_day`, counted per calendar day, resets at the next day |
| Max daily loss of 7% (matched to risk/trade), then stop for the day | `max_daily_loss_pct`; a circuit breaker that blocks new entries once tripped, existing stops still fire. Set equal to `max_risk_per_trade_pct` so one full-risk loss is exactly enough to end the day -- it still stops a second or third loss from compounding on top, but a single stopped-out trade can land right at the cap rather than safely under it, since the breaker only stops *new* entries after a loss lands and can't cap the loss on the trade that triggers it. |
| Every position has a predetermined stop-loss | `RiskManager.size_order` raises `RiskViolation` if asked to size an order with no stop, or a stop above entry |
| No leverage/margin | `allow_leverage=False`; order size is capped to available cash |
| Only liquid U.S. stocks/ETFs | `data.liquidity_filter`, trailing 20-day average dollar volume >= `min_avg_dollar_volume` |
| No averaging down | `RiskManager.can_open` refuses a second entry while a symbol is already held |
| Objective entry/exit signals only | `strategy.py:generate_signals` -- a fixed SMA-crossover/trend rule, no discretionary input |
| A single trade can't be the whole account | `max_position_pct` caps notional exposure per position (50% by default, per your stated limit) |

One real constraint this surfaces: at $500-1,000 and a *lower* risk cap (1%
was the original starting point here), whole-share sizing on normal-priced
ETFs (SPY, QQQ, ...) rounds most trades down to **zero shares** -- the
risk-adjusted position is smaller than one share. At 7% this binds less
often, but fractional sizing (`allow_fractional_shares=True`) is still the
default so smaller risk settings, or lower-priced positions within a trade,
stay viable. Set it to `False` to see the
whole-share-only behavior (verified in `tests/test_risk.py`); live trading
would need to confirm each symbol is fractionable before sizing it that way.

## The strategy

`strategy.py` is a fully mechanical trend-following rule: enter when the
20-day SMA crosses above the 50-day SMA while price is above the 200-day SMA
(only trade with the primary trend); exit when the 20/50 crossover reverses.
Every position also gets a stop-loss at `entry - 2.5 * ATR(14)`, computed once
at fill time. Nothing here reads news, sentiment, or "vibes" -- it's a pure
function of OHLCV history.

This is a reasonable starting point, not a claim that it's a good strategy.
Swap it for whatever you actually want to run; `risk.py` and `simulator.py`
don't need to change as long as the replacement produces the same `entry`/
`exit`/`atr` shape.

## Realistic backtest

`simulator.py` runs an event-driven, bar-by-bar simulation, not a vectorized
shortcut:

- **No lookahead**: a signal computed from day T's close is filled at day
  T+1's open.
- **Stop-losses checked against intraday low**, filled at the stop price or
  at the day's open if it gapped through the stop, whichever is worse.
- **Costs**: Robinhood's $0 commission, plus the SEC Section 31 fee and FINRA
  Trading Activity Fee on sells (`fees.py`, both are small but real), plus
  slippage (`slippage_bps`, default 5bps) applied against the trader on every
  fill.
- **Every order goes through the same `RiskManager`** that paper/live trading
  will use -- position sizing, the daily trade cap, and the daily loss
  circuit breaker are not backtest-only approximations.

Run it:

```bash
pip install -r requirements.txt
python run_backtest.py --symbols SPY QQQ IWM DIA AAPL MSFT --period 5y
```

Prints a summary (total return, CAGR, max drawdown, Sharpe, win rate, profit
factor, stop-loss exit count) and writes `equity_curve.csv`, `trade_log.csv`,
and `summary.json` to `--out` (default `backtest_output/`).

Data comes from Yahoo Finance's public chart endpoint via plain `requests`
(see `data.py` -- the `yfinance` package's own HTTP client did not work
through this environment's outbound proxy, so this avoids that dependency
entirely).

## Paper trading

`run_paper.py` runs the identical strategy + risk engine against real (free,
delayed) daily data, with no broker connection and no money at risk. State
(cash, open positions, pending orders, trade log) persists to
`paper_state.json` between runs, using the same next-bar-open execution model
as the backtest: a signal from today's close is queued and filled at the next
run's open.

```bash
python run_paper.py --symbols SPY QQQ IWM DIA AAPL MSFT
```

Run it once per day after market close. Before moving to live capital, you
want to see this behave consistently with the backtest over a meaningful
stretch of paper-traded time -- and specifically confirm the risk controls
above actually fire in practice (a forced daily-loss halt, a blocked
averaging-down attempt, a rejected 4th trade of the day), not just that the
strategy is profitable.

## Live trading requirements

**This session has no working connection to Robinhood or any broker.** A
local `claude mcp add robinhood-trading --transport http
https://agent.robinhood.com/mcp/trading` was run earlier in this environment,
and `/mcp` shows it as "connected" in the CLI's own config -- but no tool
under an `mcp__robinhood-trading__*` prefix (or equivalent) is actually
exposed to this agent session. Nothing in this codebase can place, check, or
cancel a real order right now.

`broker.py:RobinhoodBroker` is a stub that documents exactly what needs to
exist before that changes:

1. **Authenticated account access** -- credentials scoped to the specific
   account this is meant to trade, with an explicit way to confirm that
   before any order tool is exposed to an agent.
2. **Read tools** -- account (cash/equity/buying power/day-trade count),
   positions, and quotes.
3. **Order tools** -- place (market/limit, side, qty, time-in-force),
   get status, cancel -- each returning a real broker order id.
4. **Safety properties on the tool surface itself** -- idempotent order
   submission, an explicit paper/sandbox vs. live-money mode, and clear
   error semantics for "did that order actually go through."

Once a broker satisfying `broker.py:Broker` is actually callable from a
session, wiring it in only touches `broker.py` -- `strategy.py`, `risk.py`,
and the rest of the risk controls stay exactly as validated in backtest and
paper trading.

## Suggested rollout

1. Backtest across a longer history and a wider liquid universe than the
   6-symbol default; look specifically at whether the daily-loss circuit
   breaker and trade cap ever bind, not just at total return.
2. Paper trade for at least several weeks, ideally spanning at least one
   drawdown, and confirm the risk controls fire as designed.
3. Only then consider live capital, starting at the low end of $500, and
   only once an actual broker connection exists and has been exercised in a
   sandbox/paper mode first.
4. Increase capital gradually and only if live performance is consistent
   with backtest/paper -- not as a reaction to a short hot streak.
