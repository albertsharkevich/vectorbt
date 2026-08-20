"""Broker abstraction.

The strategy and risk engine never talk to a broker directly -- they go
through this interface. That means the exact same RiskManager-gated logic
that runs in the backtest can run against a paper broker today and a live
broker later without touching strategy.py, risk.py, or simulator.py.
"""

from abc import ABC, abstractmethod


class Broker(ABC):
    @abstractmethod
    def get_account(self) -> dict:
        """Return {'cash': float, 'equity': float, 'buying_power': float}."""

    @abstractmethod
    def get_positions(self) -> dict:
        """Return {symbol: {'shares': float, 'avg_price': float}}."""

    @abstractmethod
    def get_quote(self, symbol: str) -> dict:
        """Return {'price': float, 'bid': float, 'ask': float, 'timestamp': ...}."""

    @abstractmethod
    def place_order(self, symbol: str, side: str, shares: float, order_type: str, limit_price=None) -> dict:
        """Submit an order and return a broker order id / status."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        ...


class RobinhoodBroker(Broker):
    """Not implemented in this environment.

    This session has no callable tool for Robinhood -- searching the tool
    surface for anything under an `mcp__robinhood-trading__*` prefix returns
    nothing, even though a local `claude mcp add` registered the server for
    this account's own CLI config. To actually place, monitor, or cancel a
    real order from an agent session, the following needs to exist and be
    exposed as callable tools (an MCP server is the natural shape, but a
    typed REST wrapper would also work):

      1. Authenticated account access
         - OAuth/session credentials for the target Robinhood account, scoped
           to at least read (account/positions/quotes) and trade permissions.
         - A way to prove *this* is the account intended for real money before
           any order tool is exposed (never just a "trust the URL" step).

      2. Account/position/quote read tools
         - get_account: cash, equity, buying power, day-trade count.
         - get_positions: symbol, shares, average cost, current price.
         - get_quote: last price, bid/ask, for the liquidity/price checks
           the risk engine depends on before sizing an order.

      3. Order tools
         - place_order: symbol, side, quantity, order type (market/limit),
           limit price, time-in-force. Must return a real broker order id.
         - get_order_status: poll fills/partial fills/rejections by order id.
         - cancel_order: cancel a resting order by id.

      4. Safety properties on the tool surface itself
         - Idempotency (a retried place_order must not double-submit).
         - A way to distinguish paper/sandbox mode from live money mode, so
           this system can be pointed at a sandbox before it is ever pointed
           at the real account.
         - Rate limits / error semantics that the RiskManager's caller can
           reason about (e.g. does a timeout mean "unknown state, must poll"
           or "definitely not submitted"?).

    Until a broker implementing this interface is actually wired into the
    session's tool surface, only PaperBroker (see below) can run.
    """

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "No Robinhood trading tool is available to this session. See this "
            "class's docstring for exactly what needs to be connected before "
            "RobinhoodBroker can be implemented."
        )

    def get_account(self):
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def get_quote(self, symbol):
        raise NotImplementedError

    def place_order(self, symbol, side, shares, order_type, limit_price=None):
        raise NotImplementedError

    def get_order_status(self, order_id):
        raise NotImplementedError

    def cancel_order(self, order_id):
        raise NotImplementedError


class PaperBroker(Broker):
    """Simulates fills against real market data, using the same RiskManager.

    Positions and cash live entirely in the RiskManager passed in; this class
    only adds the notion of "fill at the latest available quote" so a daily
    paper-trading run behaves like a live run would, minus real order risk.
    """

    def __init__(self, risk_manager, price_lookup):
        """price_lookup: callable(symbol) -> latest trade price (float)."""
        self.risk_manager = risk_manager
        self.price_lookup = price_lookup

    def get_account(self):
        marks = {s: self.price_lookup(s) for s in self.risk_manager.positions}
        return {
            "cash": self.risk_manager.cash,
            "equity": self.risk_manager.equity(marks),
            "buying_power": self.risk_manager.cash,
        }

    def get_positions(self):
        return {
            symbol: {"shares": pos.shares, "avg_price": pos.entry_price}
            for symbol, pos in self.risk_manager.positions.items()
        }

    def get_quote(self, symbol):
        price = self.price_lookup(symbol)
        return {"price": price, "bid": price, "ask": price}

    def place_order(self, symbol, side, shares, order_type, limit_price=None):
        raise NotImplementedError(
            "PaperBroker fills are driven by simulator/run_paper.py through "
            "RiskManager directly, not through place_order."
        )

    def get_order_status(self, order_id):
        raise NotImplementedError

    def cancel_order(self, order_id):
        raise NotImplementedError
