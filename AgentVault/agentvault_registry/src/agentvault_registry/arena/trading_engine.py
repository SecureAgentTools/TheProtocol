"""
Market Mayhem — Trading War Game Engine.

4-8 agents trade 5 volatile commodities over 50 rounds.
Prices move on supply/demand. Random events shake the market.
Richest agent at the end wins.
"""

import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# ── Constants ──
MAX_ROUNDS = 50
STARTING_CREDITS = 10000
MIN_PRICE = 1
MAX_PRICE = 10000
PRICE_IMPACT_FACTOR = 0.02  # How much each unit traded moves the price
VOLATILITY = 0.03  # Base random volatility per round
SHORT_INTEREST_RATE = 0.02  # Per-round cost of holding shorts


class Commodity(str, Enum):
    ENERGY = "ENERGY"
    DATA = "DATA"
    COMPUTE = "COMPUTE"
    TRUST = "TRUST"
    DARK = "DARK"


COMMODITY_BASE_PRICES = {
    Commodity.ENERGY: 100,
    Commodity.DATA: 80,
    Commodity.COMPUTE: 120,
    Commodity.TRUST: 60,
    Commodity.DARK: 200,
}

COMMODITY_VOLATILITY = {
    Commodity.ENERGY: 0.03,
    Commodity.DATA: 0.04,
    Commodity.COMPUTE: 0.025,
    Commodity.TRUST: 0.05,
    Commodity.DARK: 0.06,
}

# ── Market Events ──
MARKET_EVENTS = [
    {"name": "Energy Crisis", "commodity": Commodity.ENERGY, "effect": 0.35, "desc": "Global energy shortage drives prices up"},
    {"name": "Energy Surplus", "commodity": Commodity.ENERGY, "effect": -0.30, "desc": "Oversupply crashes energy prices"},
    {"name": "Data Breach", "commodity": Commodity.DATA, "effect": -0.40, "desc": "Major breach tanks data trust"},
    {"name": "Data Gold Rush", "commodity": Commodity.DATA, "effect": 0.45, "desc": "New AI models spike data demand"},
    {"name": "Compute Shortage", "commodity": Commodity.COMPUTE, "effect": 0.50, "desc": "GPU shortage sends compute soaring"},
    {"name": "Compute Glut", "commodity": Commodity.COMPUTE, "effect": -0.25, "desc": "New fabs flood the market"},
    {"name": "Trust Scandal", "commodity": Commodity.TRUST, "effect": -0.45, "desc": "Major agent caught lying — trust collapses"},
    {"name": "Trust Renaissance", "commodity": Commodity.TRUST, "effect": 0.40, "desc": "New verification protocol boosts trust"},
    {"name": "Dark Pool Leak", "commodity": Commodity.DARK, "effect": -0.35, "desc": "Dark pool exposed — prices plummet"},
    {"name": "Dark Demand Surge", "commodity": Commodity.DARK, "effect": 0.55, "desc": "Anonymous compute demand explodes"},
    {"name": "Market Panic", "commodity": None, "effect": -0.20, "desc": "Broad selloff across all commodities"},
    {"name": "Bull Run", "commodity": None, "effect": 0.15, "desc": "Everything rallies — risk appetite returns"},
    {"name": "Flash Crash", "commodity": None, "effect": -0.30, "desc": "Algorithmic cascade triggers broad crash"},
    {"name": "Regulatory Boost", "commodity": None, "effect": 0.10, "desc": "Favorable regulation lifts all markets"},
]


@dataclass
class Order:
    """A pending limit order."""
    order_id: str
    agent_id: str
    commodity: Commodity
    side: str  # "buy" or "sell"
    quantity: int
    limit_price: float
    created_round: int


@dataclass
class Trade:
    """An executed trade record."""
    trade_id: str
    agent_id: str
    commodity: Commodity
    side: str
    quantity: int
    price: float
    total: float
    round_num: int


@dataclass
class ShortPosition:
    """An open short position."""
    commodity: Commodity
    quantity: int
    entry_price: float
    opened_round: int


@dataclass
class Trader:
    """An agent in the trading game."""
    agent_id: str
    name: str
    credits: float = STARTING_CREDITS
    holdings: Dict[str, int] = field(default_factory=dict)  # commodity → quantity
    short_positions: List[ShortPosition] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    insider_tip: Optional[Dict] = None  # Next round's event (if they got the tip)
    joined_round: int = 0

    @property
    def is_bot(self) -> bool:
        return self.agent_id.startswith("bot:")

    def net_worth(self, prices: Dict[str, float]) -> float:
        """Calculate total net worth = credits + holdings value - short liabilities."""
        total = self.credits
        for comm, qty in self.holdings.items():
            total += qty * prices.get(comm, 0)
        for sp in self.short_positions:
            # Short liability = current_price * quantity (you owe the shares)
            total -= prices.get(sp.commodity.value, 0) * sp.quantity
        return total


class TradingGameState:
    """Full state for one Market Mayhem game."""

    def __init__(self, match_id: str):
        self.match_id = match_id
        self.round_num = 0
        self.max_rounds = MAX_ROUNDS
        self.started = False
        self.finished = False
        self.winner: Optional[str] = None
        self.traders: Dict[str, Trader] = {}
        self.created_at = time.time()

        # Prices
        self.prices: Dict[str, float] = {c.value: p for c, p in COMMODITY_BASE_PRICES.items()}
        self.price_history: Dict[str, List[float]] = {c.value: [p] for c, p in COMMODITY_BASE_PRICES.items()}

        # Orders & events
        self.pending_orders: List[Order] = []
        self.round_events: List[Dict] = []
        self.event_log: List[Dict] = []
        self.trade_log: List[Trade] = []

        # Next event (for insider tips)
        self._next_event: Optional[Dict] = None
        self._prepare_next_event()

    def add_trader(self, agent_id: str, name: str) -> Trader:
        if agent_id in self.traders:
            return self.traders[agent_id]
        trader = Trader(
            agent_id=agent_id,
            name=name,
            holdings={c.value: 0 for c in Commodity},
            joined_round=self.round_num,
        )
        self.traders[agent_id] = trader
        logger.info(f"[Trading] {name} joined {self.match_id}")
        return trader

    def start_game(self):
        self.started = True
        self.round_num = 1
        # Give each trader some starting commodity
        for trader in self.traders.values():
            for c in Commodity:
                trader.holdings[c.value] = 5  # Start with 5 of each
        logger.info(f"[Trading] Game {self.match_id} started with {len(self.traders)} traders")

    def _prepare_next_event(self):
        """Pre-roll the next market event (for insider tips)."""
        if random.random() < 0.4:  # 40% chance of event each round
            self._next_event = random.choice(MARKET_EVENTS).copy()
        else:
            self._next_event = None

    # ── Actions ──

    def market_buy(self, agent_id: str, commodity: str, quantity: int) -> Dict:
        """Execute a market buy at current price."""
        trader = self.traders.get(agent_id)
        if not trader:
            return {"success": False, "error": "Not in game"}
        if not self.started or self.finished:
            return {"success": False, "error": "Game not active"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be positive"}

        comm = commodity.upper()
        if comm not in self.prices:
            return {"success": False, "error": f"Unknown commodity: {commodity}"}

        price = self.prices[comm]
        total_cost = price * quantity

        if total_cost > trader.credits:
            max_qty = int(trader.credits / price)
            if max_qty <= 0:
                return {"success": False, "error": f"Insufficient credits. Need {total_cost:.0f}, have {trader.credits:.0f}"}
            quantity = max_qty
            total_cost = price * quantity

        # Execute
        trader.credits -= total_cost
        trader.holdings[comm] = trader.holdings.get(comm, 0) + quantity

        # Price impact (buying pushes price up)
        impact = quantity * PRICE_IMPACT_FACTOR
        self.prices[comm] = min(MAX_PRICE, self.prices[comm] * (1 + impact))

        trade = Trade(
            trade_id=f"T-{uuid.uuid4().hex[:6]}",
            agent_id=agent_id, commodity=Commodity(comm),
            side="buy", quantity=quantity, price=price,
            total=total_cost, round_num=self.round_num,
        )
        trader.trades.append(trade)
        self.trade_log.append(trade)

        logger.info(f"[Trading] {trader.name} BUY {quantity} {comm} @ {price:.1f} = {total_cost:.0f}")
        resp = {
            "success": True, "side": "buy", "commodity": comm,
            "quantity": quantity, "price": round(price, 2),
            "total_cost": round(total_cost, 2),
            "credits_remaining": round(trader.credits, 2),
            "holdings": trader.holdings[comm],
            "price_impact_pct": round(impact * 100, 1),
        }
        if impact >= 0.10:  # order moved price by 10% or more
            suggested = max(2, quantity // 5)
            resp["slippage_warning"] = (
                f"Large order: price moved by ~{impact*100:.0f}% "
                f"({PRICE_IMPACT_FACTOR*100:.0f}% per unit). "
                f"Split into ~{suggested} smaller orders across rounds to reduce slippage."
            )
        return resp

    def market_sell(self, agent_id: str, commodity: str, quantity: int) -> Dict:
        """Execute a market sell at current price."""
        trader = self.traders.get(agent_id)
        if not trader:
            return {"success": False, "error": "Not in game"}
        if not self.started or self.finished:
            return {"success": False, "error": "Game not active"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be positive"}

        comm = commodity.upper()
        if comm not in self.prices:
            return {"success": False, "error": f"Unknown commodity: {commodity}"}

        held = trader.holdings.get(comm, 0)
        if quantity > held:
            if held <= 0:
                return {"success": False, "error": f"No {comm} to sell. Holdings: {held}"}
            quantity = held  # Sell all

        price = self.prices[comm]
        total_revenue = price * quantity

        # Execute
        trader.credits += total_revenue
        trader.holdings[comm] -= quantity

        # Price impact (selling pushes price down)
        impact = quantity * PRICE_IMPACT_FACTOR
        self.prices[comm] = max(MIN_PRICE, self.prices[comm] * (1 - impact))

        trade = Trade(
            trade_id=f"T-{uuid.uuid4().hex[:6]}",
            agent_id=agent_id, commodity=Commodity(comm),
            side="sell", quantity=quantity, price=price,
            total=total_revenue, round_num=self.round_num,
        )
        trader.trades.append(trade)
        self.trade_log.append(trade)

        logger.info(f"[Trading] {trader.name} SELL {quantity} {comm} @ {price:.1f} = {total_revenue:.0f}")
        resp = {
            "success": True, "side": "sell", "commodity": comm,
            "quantity": quantity, "price": round(price, 2),
            "total_revenue": round(total_revenue, 2),
            "credits_remaining": round(trader.credits, 2),
            "holdings": trader.holdings[comm],
            "price_impact_pct": round(impact * 100, 1),
        }
        if impact >= 0.10:
            suggested = max(2, quantity // 5)
            resp["slippage_warning"] = (
                f"Large order: price moved by ~{impact*100:.0f}% "
                f"({PRICE_IMPACT_FACTOR*100:.0f}% per unit). "
                f"Split into ~{suggested} smaller orders across rounds to reduce slippage."
            )
        return resp

    def short_sell(self, agent_id: str, commodity: str, quantity: int) -> Dict:
        """Open a short position (bet the price goes down)."""
        trader = self.traders.get(agent_id)
        if not trader:
            return {"success": False, "error": "Not in game"}
        if not self.started or self.finished:
            return {"success": False, "error": "Game not active"}
        if quantity <= 0:
            return {"success": False, "error": "Quantity must be positive"}

        comm = commodity.upper()
        if comm not in self.prices:
            return {"success": False, "error": f"Unknown commodity: {commodity}"}

        price = self.prices[comm]
        # Require 50% margin
        margin_required = price * quantity * 0.5
        if margin_required > trader.credits:
            return {"success": False, "error": f"Insufficient margin. Need {margin_required:.0f}, have {trader.credits:.0f}"}

        # Execute: receive credits now, owe the shares later
        trader.credits += price * quantity
        trader.short_positions.append(ShortPosition(
            commodity=Commodity(comm),
            quantity=quantity,
            entry_price=price,
            opened_round=self.round_num,
        ))

        # Price impact
        impact = quantity * PRICE_IMPACT_FACTOR
        self.prices[comm] = max(MIN_PRICE, self.prices[comm] * (1 - impact))

        logger.info(f"[Trading] {trader.name} SHORT {quantity} {comm} @ {price:.1f}")
        resp = {
            "success": True, "side": "short", "commodity": comm,
            "quantity": quantity, "entry_price": round(price, 2),
            "margin_locked": round(margin_required, 2),
            "credits_remaining": round(trader.credits, 2),
            "total_short_exposure": sum(sp.quantity * self.prices[sp.commodity.value] for sp in trader.short_positions),
            "price_impact_pct": round(impact * 100, 1),
        }
        if impact >= 0.10:
            suggested = max(2, quantity // 5)
            resp["slippage_warning"] = (
                f"Large short: price moved by ~{impact*100:.0f}% "
                f"({PRICE_IMPACT_FACTOR*100:.0f}% per unit). "
                f"Split into ~{suggested} smaller shorts to reduce slippage."
            )
        return resp

    def place_limit_order(self, agent_id: str, commodity: str, side: str, quantity: int, limit_price: float) -> Dict:
        """Place a limit order (executes when price reaches limit)."""
        trader = self.traders.get(agent_id)
        if not trader:
            return {"success": False, "error": "Not in game"}
        if side not in ("buy", "sell"):
            return {"success": False, "error": "Side must be 'buy' or 'sell'"}
        if quantity <= 0 or limit_price <= 0:
            return {"success": False, "error": "Quantity and price must be positive"}

        comm = commodity.upper()
        if comm not in self.prices:
            return {"success": False, "error": f"Unknown commodity: {commodity}"}

        order = Order(
            order_id=f"O-{uuid.uuid4().hex[:6]}",
            agent_id=agent_id, commodity=Commodity(comm),
            side=side, quantity=quantity,
            limit_price=limit_price, created_round=self.round_num,
        )
        self.pending_orders.append(order)

        return {
            "success": True, "order_id": order.order_id,
            "side": side, "commodity": comm,
            "quantity": quantity, "limit_price": round(limit_price, 2),
            "current_price": round(self.prices[comm], 2),
        }

    # ── Round Processing ──

    def advance_round(self, agent_id: Optional[str] = None) -> Dict:
        """Process one round: execute limit orders, apply event, update prices, charge shorts.

        If `agent_id` is provided and that trader has been granted an insider
        tip about the next round's event, the tip is included in the response
        so callers who only use `trade_step` (not `trade_look`) still see it.
        """
        if not self.started or self.finished:
            return {"error": "Game not active"}

        events_this_round = []

        # 1. Execute limit orders
        filled_orders = self._execute_limit_orders()

        # 2. Apply market event (if any)
        event = self._next_event
        if event:
            self._apply_event(event)
            events_this_round.append(event)
            self.event_log.append({"round": self.round_num, **event})

        # 3. Random price movement (volatility)
        for comm in Commodity:
            vol = COMMODITY_VOLATILITY[comm]
            change = random.gauss(0, vol)
            # Add momentum (prices tend to continue direction)
            if len(self.price_history[comm.value]) >= 2:
                last_change = (self.price_history[comm.value][-1] - self.price_history[comm.value][-2]) / self.price_history[comm.value][-2]
                change += last_change * 0.1  # 10% momentum
            self.prices[comm.value] = max(MIN_PRICE, min(MAX_PRICE, self.prices[comm.value] * (1 + change)))

        # 4. Charge short interest
        for trader in self.traders.values():
            for sp in trader.short_positions:
                interest = sp.quantity * self.prices[sp.commodity.value] * SHORT_INTEREST_RATE
                trader.credits -= interest

        # 5. Record prices
        for comm in Commodity:
            self.price_history[comm.value].append(round(self.prices[comm.value], 2))

        # 6. Prepare next event + assign insider tip
        self._prepare_next_event()
        self._assign_insider_tip()

        # 7. Run bot strategies
        self._run_bots()

        # 8. Check game end — end AT max_rounds (not max_rounds + 1).
        # Previously `round_num += 1` then `if > max_rounds` meant the last
        # reported round was `max_rounds + 1`, which confused callers.
        if self.round_num >= self.max_rounds:
            self._end_game()
        else:
            self.round_num += 1

        self.round_events = events_this_round

        resp = {
            "round": self.round_num,
            "events": [{"name": e["name"], "desc": e["desc"]} for e in events_this_round],
            "prices": {k: round(v, 2) for k, v in self.prices.items()},
            "filled_orders": len(filled_orders),
            "finished": self.finished,
        }
        # Surface the caller's insider tip (if any) so `trade_step`-only
        # clients don't miss it — tips were previously only in `trade_look`.
        if agent_id and agent_id in self.traders:
            tip = self.traders[agent_id].insider_tip
            if tip:
                resp["insider_tip"] = tip
        return resp

    def _execute_limit_orders(self) -> List[Order]:
        """Execute any limit orders whose price condition is met."""
        filled = []
        remaining = []
        for order in self.pending_orders:
            price = self.prices[order.commodity.value]
            should_fill = (
                (order.side == "buy" and price <= order.limit_price) or
                (order.side == "sell" and price >= order.limit_price)
            )
            if should_fill:
                if order.side == "buy":
                    self.market_buy(order.agent_id, order.commodity.value, order.quantity)
                else:
                    self.market_sell(order.agent_id, order.commodity.value, order.quantity)
                filled.append(order)
            elif self.round_num - order.created_round > 5:
                pass  # Expire old orders
            else:
                remaining.append(order)
        self.pending_orders = remaining
        return filled

    def _apply_event(self, event: Dict):
        """Apply a market event to prices."""
        if event.get("commodity"):
            comm = event["commodity"].value if isinstance(event["commodity"], Commodity) else event["commodity"]
            self.prices[comm] *= (1 + event["effect"])
            self.prices[comm] = max(MIN_PRICE, min(MAX_PRICE, self.prices[comm]))
        else:
            # Broad market event — affects all commodities
            for comm in Commodity:
                self.prices[comm.value] *= (1 + event["effect"])
                self.prices[comm.value] = max(MIN_PRICE, min(MAX_PRICE, self.prices[comm.value]))

    def _assign_insider_tip(self):
        """Give one random trader the next event as an insider tip."""
        # Clear all tips
        for t in self.traders.values():
            t.insider_tip = None
        # 30% chance someone gets a tip
        if self._next_event and random.random() < 0.3:
            non_bot_traders = [t for t in self.traders.values() if not t.is_bot]
            all_traders = non_bot_traders if non_bot_traders else list(self.traders.values())
            if all_traders:
                lucky = random.choice(all_traders)
                lucky.insider_tip = {
                    "commodity": self._next_event["commodity"].value if self._next_event.get("commodity") else "ALL",
                    "direction": "UP" if self._next_event["effect"] > 0 else "DOWN",
                    "magnitude": abs(self._next_event["effect"]),
                    "hint": f"Rumors suggest {'bullish' if self._next_event['effect'] > 0 else 'bearish'} pressure on {self._next_event['commodity'].value if self._next_event.get('commodity') else 'the broad market'} next round.",
                }
                logger.info(f"[Trading] Insider tip given to {lucky.name}")

    def _run_bots(self):
        """Simple bot trading strategy."""
        for trader in self.traders.values():
            if not trader.is_bot:
                continue
            # Bots use a momentum + mean-reversion hybrid
            for comm in Commodity:
                price = self.prices[comm.value]
                base = COMMODITY_BASE_PRICES[comm]
                held = trader.holdings.get(comm.value, 0)
                history = self.price_history[comm.value]

                # Mean reversion: buy if price < 70% of base, sell if > 150% of base
                if price < base * 0.7 and trader.credits > price * 3:
                    qty = random.randint(1, 3)
                    self.market_buy(trader.agent_id, comm.value, qty)
                elif price > base * 1.5 and held > 0:
                    qty = min(held, random.randint(1, 3))
                    self.market_sell(trader.agent_id, comm.value, qty)
                # Momentum: follow recent trend
                elif len(history) >= 3:
                    recent_change = (history[-1] - history[-3]) / history[-3]
                    if recent_change > 0.1 and trader.credits > price * 2:
                        self.market_buy(trader.agent_id, comm.value, random.randint(1, 2))
                    elif recent_change < -0.1 and held > 0:
                        self.market_sell(trader.agent_id, comm.value, min(held, random.randint(1, 2)))

                # Random small trades for liquidity
                if random.random() < 0.15:
                    if random.random() < 0.5 and trader.credits > price:
                        self.market_buy(trader.agent_id, comm.value, 1)
                    elif held > 0:
                        self.market_sell(trader.agent_id, comm.value, 1)

    def _end_game(self):
        """End the game, determine winner."""
        self.finished = True
        # Close all short positions at current prices
        for trader in self.traders.values():
            for sp in trader.short_positions:
                # Buy back: pay current price
                close_cost = sp.quantity * self.prices[sp.commodity.value]
                trader.credits -= close_cost
            trader.short_positions.clear()

        # Determine winner by net worth
        rankings = sorted(
            self.traders.values(),
            key=lambda t: t.net_worth(self.prices),
            reverse=True,
        )
        if rankings:
            self.winner = rankings[0].agent_id
            logger.info(
                f"[Trading] Game {self.match_id} FINISHED — "
                f"Winner: {rankings[0].name} with {rankings[0].net_worth(self.prices):.0f} net worth"
            )

    # ── Views ──

    def get_market_view(self, agent_id: str) -> Dict:
        """What the trader can see."""
        trader = self.traders.get(agent_id)
        if not trader:
            return {"error": "Not in game"}

        # Recent trades by others (public info)
        recent_trades = [
            {"agent": self.traders[t.agent_id].name if t.agent_id in self.traders else "?",
             "commodity": t.commodity.value, "side": t.side,
             "quantity": t.quantity, "price": round(t.price, 2)}
            for t in self.trade_log[-10:] if t.agent_id != agent_id
        ]

        return {
            "round": self.round_num,
            "max_rounds": self.max_rounds,
            "prices": {k: round(v, 2) for k, v in self.prices.items()},
            "price_changes": {
                k: round(((v - self.price_history[k][-2]) / self.price_history[k][-2] * 100) if len(self.price_history[k]) >= 2 else 0, 1)
                for k, v in self.prices.items()
            },
            "your_credits": round(trader.credits, 2),
            "your_holdings": dict(trader.holdings),
            "your_net_worth": round(trader.net_worth(self.prices), 2),
            "your_short_positions": [
                {"commodity": sp.commodity.value, "quantity": sp.quantity,
                 "entry_price": round(sp.entry_price, 2),
                 "current_price": round(self.prices[sp.commodity.value], 2),
                 "pnl": round((sp.entry_price - self.prices[sp.commodity.value]) * sp.quantity, 2)}
                for sp in trader.short_positions
            ],
            "insider_tip": trader.insider_tip,
            "recent_trades": recent_trades,
            "recent_events": [{"name": e["name"], "desc": e["desc"]} for e in self.event_log[-3:]],
            "pending_orders": [
                {"order_id": o.order_id, "commodity": o.commodity.value,
                 "side": o.side, "quantity": o.quantity, "limit_price": round(o.limit_price, 2)}
                for o in self.pending_orders if o.agent_id == agent_id
            ],
        }

    def get_portfolio(self, agent_id: str) -> Dict:
        """Detailed portfolio view."""
        trader = self.traders.get(agent_id)
        if not trader:
            return {"error": "Not in game"}

        holdings_value = {}
        for comm, qty in trader.holdings.items():
            price = self.prices[comm]
            holdings_value[comm] = {"quantity": qty, "price": round(price, 2), "value": round(qty * price, 2)}

        return {
            "credits": round(trader.credits, 2),
            "holdings": holdings_value,
            "total_holdings_value": round(sum(v["value"] for v in holdings_value.values()), 2),
            "short_positions": len(trader.short_positions),
            "short_exposure": round(sum(sp.quantity * self.prices[sp.commodity.value] for sp in trader.short_positions), 2),
            "net_worth": round(trader.net_worth(self.prices), 2),
            "total_trades": len(trader.trades),
            "rank": self._get_rank(agent_id),
        }

    def _get_rank(self, agent_id: str) -> int:
        rankings = sorted(self.traders.values(), key=lambda t: t.net_worth(self.prices), reverse=True)
        for i, t in enumerate(rankings):
            if t.agent_id == agent_id:
                return i + 1
        return 0

    def get_leaderboard(self) -> List[Dict]:
        rankings = sorted(self.traders.values(), key=lambda t: t.net_worth(self.prices), reverse=True)
        return [
            {"rank": i + 1, "name": t.name, "agent_id": t.agent_id,
             "net_worth": round(t.net_worth(self.prices), 2),
             "credits": round(t.credits, 2),
             "is_bot": t.is_bot}
            for i, t in enumerate(rankings)
        ]

    def get_price_history(self, commodity: Optional[str] = None) -> Dict:
        if commodity:
            comm = commodity.upper()
            if comm in self.price_history:
                return {"commodity": comm, "prices": self.price_history[comm]}
            return {"error": f"Unknown commodity: {commodity}"}
        return {comm: prices for comm, prices in self.price_history.items()}

    def get_spectator_state(self) -> Dict:
        """Full state for spectator view."""
        return {
            "match_id": self.match_id,
            "round": self.round_num,
            "max_rounds": self.max_rounds,
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "prices": {k: round(v, 2) for k, v in self.prices.items()},
            "price_history": {k: [round(p, 2) for p in v] for k, v in self.price_history.items()},
            "traders": [
                {"name": t.name, "agent_id": t.agent_id, "is_bot": t.is_bot,
                 "net_worth": round(t.net_worth(self.prices), 2),
                 "credits": round(t.credits, 2),
                 "holdings": dict(t.holdings)}
                for t in sorted(self.traders.values(), key=lambda x: x.net_worth(self.prices), reverse=True)
            ],
            "recent_events": [{"round": e["round"], "name": e["name"], "desc": e["desc"]} for e in self.event_log[-5:]],
            "recent_trades": [
                {"agent": self.traders[t.agent_id].name if t.agent_id in self.traders else "?",
                 "commodity": t.commodity.value, "side": t.side,
                 "quantity": t.quantity, "price": round(t.price, 2), "round": t.round_num}
                for t in self.trade_log[-15:]
            ],
        }

    # ── Redis serialization ─────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "round_num": self.round_num,
            "max_rounds": self.max_rounds,
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "created_at": self.created_at,
            "traders": {aid: _trader_to_dict(t) for aid, t in self.traders.items()},
            "prices": dict(self.prices),
            "price_history": {k: list(v) for k, v in self.price_history.items()},
            "pending_orders": [_order_to_dict(o) for o in self.pending_orders],
            "round_events": list(self.round_events),
            "event_log": list(self.event_log),
            "trade_log": [_trade_to_dict(t) for t in self.trade_log],
            "next_event": _event_to_dict(self._next_event),
            "agent_dids": getattr(self, "_agent_dids", {}),
            "persisted": getattr(self, "_persisted", False),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradingGameState":
        obj = cls.__new__(cls)
        obj.match_id = data["match_id"]
        obj.round_num = data["round_num"]
        obj.max_rounds = data["max_rounds"]
        obj.started = data["started"]
        obj.finished = data["finished"]
        obj.winner = data.get("winner")
        obj.created_at = data["created_at"]
        obj.traders = {aid: _trader_from_dict(td) for aid, td in data["traders"].items()}
        obj.prices = dict(data["prices"])
        obj.price_history = {k: list(v) for k, v in data["price_history"].items()}
        obj.pending_orders = [_order_from_dict(o) for o in data["pending_orders"]]
        obj.round_events = list(data.get("round_events", []))
        obj.event_log = list(data.get("event_log", []))
        obj.trade_log = [_trade_from_dict(t) for t in data.get("trade_log", [])]
        obj._next_event = _event_from_dict(data.get("next_event"))
        if data.get("agent_dids"):
            obj._agent_dids = dict(data["agent_dids"])
        if data.get("persisted"):
            obj._persisted = True
        return obj


# ── Trading codec helpers ───────────────────────────────────────────────

def _order_to_dict(o: Order) -> Dict[str, Any]:
    return {
        "order_id": o.order_id, "agent_id": o.agent_id,
        "commodity": o.commodity.value, "side": o.side,
        "quantity": o.quantity, "limit_price": o.limit_price,
        "created_round": o.created_round,
    }


def _order_from_dict(d: Dict[str, Any]) -> Order:
    return Order(
        order_id=d["order_id"], agent_id=d["agent_id"],
        commodity=Commodity(d["commodity"]), side=d["side"],
        quantity=d["quantity"], limit_price=d["limit_price"],
        created_round=d["created_round"],
    )


def _trade_to_dict(t: Trade) -> Dict[str, Any]:
    return {
        "trade_id": t.trade_id, "agent_id": t.agent_id,
        "commodity": t.commodity.value, "side": t.side,
        "quantity": t.quantity, "price": t.price, "total": t.total,
        "round_num": t.round_num,
    }


def _trade_from_dict(d: Dict[str, Any]) -> Trade:
    return Trade(
        trade_id=d["trade_id"], agent_id=d["agent_id"],
        commodity=Commodity(d["commodity"]), side=d["side"],
        quantity=d["quantity"], price=d["price"], total=d["total"],
        round_num=d["round_num"],
    )


def _short_to_dict(sp: ShortPosition) -> Dict[str, Any]:
    return {
        "commodity": sp.commodity.value, "quantity": sp.quantity,
        "entry_price": sp.entry_price, "opened_round": sp.opened_round,
    }


def _short_from_dict(d: Dict[str, Any]) -> ShortPosition:
    return ShortPosition(
        commodity=Commodity(d["commodity"]), quantity=d["quantity"],
        entry_price=d["entry_price"], opened_round=d["opened_round"],
    )


def _trader_to_dict(t: Trader) -> Dict[str, Any]:
    return {
        "agent_id": t.agent_id, "name": t.name, "credits": t.credits,
        "holdings": dict(t.holdings),
        "short_positions": [_short_to_dict(sp) for sp in t.short_positions],
        "trades": [_trade_to_dict(tr) for tr in t.trades],
        "insider_tip": t.insider_tip,  # already flat dict of primitives
        "joined_round": t.joined_round,
    }


def _trader_from_dict(d: Dict[str, Any]) -> Trader:
    return Trader(
        agent_id=d["agent_id"], name=d["name"], credits=d["credits"],
        holdings=dict(d.get("holdings", {})),
        short_positions=[_short_from_dict(s) for s in d.get("short_positions", [])],
        trades=[_trade_from_dict(t) for t in d.get("trades", [])],
        insider_tip=d.get("insider_tip"),
        joined_round=d.get("joined_round", 0),
    )


def _event_to_dict(ev: Optional[Dict]) -> Optional[Dict]:
    if ev is None:
        return None
    out = dict(ev)
    c = out.get("commodity")
    if isinstance(c, Commodity):
        out["commodity"] = c.value
    return out


def _event_from_dict(d: Optional[Dict]) -> Optional[Dict]:
    if d is None:
        return None
    out = dict(d)
    c = out.get("commodity")
    if isinstance(c, str):
        try:
            out["commodity"] = Commodity(c)
        except ValueError:
            pass
    return out
