from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    """Hard risk limits for the small-account system.

    Every field here maps directly to one of the constraints the account owner
    set before any live capital is involved. Nothing in strategy.py, risk.py,
    or simulator.py is allowed to bypass these.
    """

    starting_capital: float = 750.0

    # Position sizing: risk (entry - stop_loss) * shares must not exceed this
    # fraction of current equity.
    #
    # NOTE: at 7% risk/trade, a single stopped-out trade can lose far more
    # than max_daily_loss_pct (2% by default) in one shot -- the daily-loss
    # circuit breaker only blocks *new* entries after a loss lands, it does
    # not cap the loss on the trade that triggered it. These two numbers were
    # chosen independently; if you want the daily breaker to mean something
    # in practice, raise max_daily_loss_pct too (or accept that one bad trade
    # can and will blow through it).
    max_risk_per_trade_pct: float = 0.07

    # A single position's notional value (shares * entry_price) may not exceed
    # this fraction of equity, regardless of how far away the stop is.
    max_position_pct: float = 0.50

    max_trades_per_day: int = 3

    # Once (current_equity - equity_at_start_of_day) / equity_at_start_of_day
    # drops to this level, no new positions are opened for the rest of the day.
    # Existing stop-losses still execute.
    max_daily_loss_pct: float = 0.02

    allow_leverage: bool = False
    allow_averaging_down: bool = False

    # Robinhood supports fractional shares (down to a fraction of a cent of
    # notional, in practice) on most liquid stocks/ETFs. With $500-1000 of
    # capital and a 1% risk-per-trade cap, whole-share-only sizing on normal-
    # priced names (SPY, AAPL, ...) rounds most trades down to zero shares --
    # the math simply doesn't work at this account size otherwise. Live
    # implementation must still confirm each specific symbol is fractionable
    # via the broker before sizing (see broker.py:RobinhoodBroker).
    allow_fractional_shares: bool = True
    fractional_share_increment: float = 0.000001
    min_order_notional: float = 1.00

    # Liquidity filter: only symbols whose trailing average dollar volume
    # clears this bar are eligible at all.
    min_avg_dollar_volume: float = 20_000_000.0
    liquidity_lookback: int = 20

    # Costs used to make the backtest realistic. Robinhood charges no
    # commission, but regulatory pass-through fees on sells still apply, and
    # every fill is assumed to slip against the trader by slippage_bps.
    commission_per_share: float = 0.0
    sec_fee_rate: float = 0.0000278  # SEC Section 31 fee, approx per $1 of proceeds sold
    finra_taf_per_share: float = 0.000166  # FINRA Trading Activity Fee, per share sold
    finra_taf_cap: float = 8.30  # per-trade cap on the TAF
    slippage_bps: float = 5.0
