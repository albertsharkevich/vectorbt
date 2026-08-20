import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class RiskViolation(Exception):
    """Raised when code asks the risk engine to do something the rules forbid."""


@dataclass
class Position:
    symbol: str
    shares: float
    entry_price: float
    stop_loss: float
    entry_date: object


@dataclass
class RiskManager:
    """Stateful risk engine shared by backtest, paper, and (eventually) live trading.

    This is the single place every one of the account owner's constraints is
    enforced, so that the exact same code path that gets validated in the
    backtest is what runs paper trades and, later, live orders. It never sizes
    or approves an order on its own initiative -- callers propose an order and
    the engine either sizes/executes it or rejects it with a reason.
    """

    config: object
    cash: float = field(init=False)
    positions: Dict[str, Position] = field(default_factory=dict)
    trade_log: List[dict] = field(default_factory=list)

    _current_day: object = field(default=None, init=False, repr=False)
    _trades_today: int = field(default=0, init=False, repr=False)
    _day_start_equity: float = field(default=0.0, init=False, repr=False)
    _halted_today: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self.cash = self.config.starting_capital

    def equity(self, marks: Dict[str, float]) -> float:
        value = self.cash
        for symbol, pos in self.positions.items():
            value += pos.shares * marks.get(symbol, pos.entry_price)
        return value

    def _roll_day(self, date, marks):
        if date != self._current_day:
            self._current_day = date
            self._trades_today = 0
            self._halted_today = False
            self._day_start_equity = self.equity(marks)

    def halted_today(self) -> bool:
        return self._halted_today

    def can_open(self, symbol, date, marks):
        self._roll_day(date, marks)
        if self._halted_today:
            return False, "daily loss limit reached; trading halted for the day"
        if self._trades_today >= self.config.max_trades_per_day:
            return False, "max trades per day reached"
        if symbol in self.positions:
            return False, "already holding a position in this symbol (no averaging down)"
        return True, None

    def size_order(self, entry_price, stop_loss, marks):
        if stop_loss is None or not (stop_loss < entry_price):
            raise RiskViolation("every order requires a stop-loss strictly below the entry price")

        equity = self.equity(marks)
        risk_budget = equity * self.config.max_risk_per_trade_pct
        stop_distance = entry_price - stop_loss
        shares = risk_budget / stop_distance

        max_notional = equity * self.config.max_position_pct
        shares = min(shares, max_notional / entry_price)

        if not self.config.allow_leverage:
            shares = min(shares, self.cash / entry_price)

        if self.config.allow_fractional_shares:
            increment = self.config.fractional_share_increment
            shares = math.floor(shares / increment) * increment
            if shares * entry_price < self.config.min_order_notional:
                return 0.0
            return shares

        return math.floor(shares) if shares >= 1 else 0.0

    def open_position(self, symbol, date, entry_price, stop_loss, marks, fees=0.0):
        ok, reason = self.can_open(symbol, date, marks)
        if not ok:
            return None, reason

        shares = self.size_order(entry_price, stop_loss, marks)
        if shares <= 0:
            return None, "computed position size rounds to zero shares"

        cost = shares * entry_price + fees
        if cost > self.cash + 1e-6:
            return None, "insufficient cash (no margin/leverage allowed)"

        self.cash -= cost
        position = Position(symbol, shares, entry_price, stop_loss, date)
        self.positions[symbol] = position
        self._trades_today += 1
        self.trade_log.append(
            {
                "date": date,
                "symbol": symbol,
                "side": "buy",
                "shares": shares,
                "price": entry_price,
                "stop_loss": stop_loss,
                "fees": fees,
                "reason": "entry",
            }
        )
        return position, None

    def close_position(self, symbol, date, exit_price, marks, fees=0.0, reason="signal_exit"):
        position = self.positions.pop(symbol, None)
        if position is None:
            return None

        self._roll_day(date, marks)
        proceeds = position.shares * exit_price - fees
        self.cash += proceeds
        pnl = proceeds - position.shares * position.entry_price
        self.trade_log.append(
            {
                "date": date,
                "symbol": symbol,
                "side": "sell",
                "shares": position.shares,
                "price": exit_price,
                "fees": fees,
                "reason": reason,
                "pnl": pnl,
            }
        )
        self._check_daily_loss(date, marks)
        return pnl

    def _check_daily_loss(self, date, marks):
        if self._day_start_equity <= 0:
            return
        equity = self.equity(marks)
        drawdown = (equity - self._day_start_equity) / self._day_start_equity
        if drawdown <= -self.config.max_daily_loss_pct:
            self._halted_today = True

    def to_state(self) -> dict:
        """Serialize cash/positions/trade_log so a paper (or later live) run
        can persist and resume across separate process invocations."""
        return {
            "cash": self.cash,
            "positions": {
                symbol: {
                    "shares": pos.shares,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "entry_date": str(pos.entry_date),
                }
                for symbol, pos in self.positions.items()
            },
            "trade_log": [
                {**entry, "date": str(entry["date"])} for entry in self.trade_log
            ],
        }

    @classmethod
    def from_state(cls, config, state: dict) -> "RiskManager":
        rm = cls(config)
        rm.cash = state["cash"]
        rm.positions = {
            symbol: Position(
                symbol=symbol,
                shares=p["shares"],
                entry_price=p["entry_price"],
                stop_loss=p["stop_loss"],
                entry_date=p["entry_date"],
            )
            for symbol, p in state.get("positions", {}).items()
        }
        rm.trade_log = list(state.get("trade_log", []))
        return rm
