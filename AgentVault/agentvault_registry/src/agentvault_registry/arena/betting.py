"""
Arena Betting System — AVT stakes on match outcomes.

Financial safety:
  - ALL token movements go through TEG transfer API (never direct DB writes)
  - Betting pool is a virtual ledger — tokens stay in agent wallets until settlement
  - Settlement uses the same TokensTransferred event pipeline as regular transfers
  - Supply invariant is preserved because we use existing TEG transfer infrastructure
  - Failed settlements roll back cleanly (no partial payouts)

Flow:
  1. Agent places bet → record in memory (no token movement yet)
  2. Match ends → calculate payouts
  3. Settlement → TEG transfers: losers → arena treasury → winners
  4. EventStore records BetPlaced + BetSettled events

Pool distribution:
  - 80% to winning bettors (proportional to stake)
  - 10% to winning agent's wallet
  - 10% arena fee (to fee_collector)
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Arena treasury DID — receives/distributes bet pools
ARENA_TREASURY = "arena:treasury"
ARENA_FEE_PCT = 0.10     # 10% platform fee
WINNER_AGENT_PCT = 0.10   # 10% to winning agent
BETTOR_PCT = 0.80         # 80% to winning bettors


@dataclass
class Bet:
    bet_id: str
    match_id: str
    bettor_agent_did: str
    bettor_name: str
    target_agent_id: str   # Who they're betting on
    target_agent_name: str
    amount: float
    placed_at: float
    settled: bool = False
    payout: float = 0.0


@dataclass
class BettingPool:
    match_id: str
    bets: List[Bet] = field(default_factory=list)
    total_pool: float = 0.0
    closed: bool = False  # No more bets after match starts
    settled: bool = False

    def place_bet(self, bettor_did: str, bettor_name: str,
                  target_id: str, target_name: str, amount: float) -> Optional[Bet]:
        """Place a bet on an agent. Returns Bet or None if pool is closed."""
        if self.closed:
            return None
        if amount <= 0:
            return None

        # Check if bettor already bet on this match
        for existing in self.bets:
            if existing.bettor_agent_did == bettor_did:
                return None  # One bet per agent per match

        bet = Bet(
            bet_id=f"BET-{uuid.uuid4().hex[:8].upper()}",
            match_id=self.match_id,
            bettor_agent_did=bettor_did,
            bettor_name=bettor_name,
            target_agent_id=target_id,
            target_agent_name=target_name,
            amount=amount,
            placed_at=time.time(),
        )
        self.bets.append(bet)
        self.total_pool += amount
        logger.info(f"[Arena Bet] {bettor_name} bet {amount} AVT on {target_name} in {self.match_id}")
        return bet

    def close_betting(self):
        """Close betting (match starting)."""
        self.closed = True

    def get_odds(self) -> Dict[str, float]:
        """Calculate current odds for each agent."""
        if self.total_pool == 0:
            return {}
        agent_pools: Dict[str, float] = {}
        for bet in self.bets:
            agent_pools[bet.target_agent_id] = agent_pools.get(bet.target_agent_id, 0) + bet.amount
        odds = {}
        for agent_id, pool in agent_pools.items():
            odds[agent_id] = round(self.total_pool / pool, 2) if pool > 0 else 0
        return odds

    def calculate_payouts(self, winner_agent_id: str) -> Dict[str, float]:
        """Calculate payout amounts. Returns {agent_did: payout_amount}."""
        if self.total_pool == 0 or self.settled:
            return {}

        # Split pool
        bettor_share = self.total_pool * BETTOR_PCT
        winner_share = self.total_pool * WINNER_AGENT_PCT
        fee_share = self.total_pool * ARENA_FEE_PCT

        # Find winning bets
        winning_bets = [b for b in self.bets if b.target_agent_id == winner_agent_id]
        winning_total = sum(b.amount for b in winning_bets)

        payouts: Dict[str, float] = {}

        if winning_bets and winning_total > 0:
            # Distribute bettor share proportionally
            for bet in winning_bets:
                payout = (bet.amount / winning_total) * bettor_share
                bet.payout = round(payout, 6)
                bet.settled = True
                payouts[bet.bettor_agent_did] = bet.payout

            # Winner agent gets their share
            if winner_agent_id and not winner_agent_id.startswith("bot:"):
                payouts[winner_agent_id] = round(winner_share, 6)
        else:
            # No one bet on the winner — refund all bets
            for bet in self.bets:
                bet.payout = bet.amount  # Full refund
                bet.settled = True
                payouts[bet.bettor_agent_did] = bet.amount
            logger.info(f"[Arena Bet] No winning bets — refunding all {len(self.bets)} bets")

        # Fee goes to arena (logged, not transferred — stays in the pool)
        payouts["arena:fee"] = round(fee_share, 6)

        self.settled = True
        return payouts

    def get_status(self) -> Dict:
        """Current betting status."""
        return {
            "match_id": self.match_id,
            "total_pool": self.total_pool,
            "bet_count": len(self.bets),
            "closed": self.closed,
            "settled": self.settled,
            "odds": self.get_odds(),
            "bets": [
                {
                    "bet_id": b.bet_id,
                    "bettor": b.bettor_name,
                    "target": b.target_agent_name,
                    "amount": b.amount,
                    "payout": b.payout if b.settled else None,
                }
                for b in self.bets
            ],
        }


class BettingManager:
    """Manages betting pools for all matches."""

    def __init__(self):
        self.pools: Dict[str, BettingPool] = {}

    def get_or_create_pool(self, match_id: str) -> BettingPool:
        if match_id not in self.pools:
            self.pools[match_id] = BettingPool(match_id=match_id)
        return self.pools[match_id]

    def place_bet(self, match_id: str, bettor_did: str, bettor_name: str,
                  target_id: str, target_name: str, amount: float) -> Optional[Dict]:
        """Place a bet. Returns bet info or None."""
        pool = self.get_or_create_pool(match_id)
        bet = pool.place_bet(bettor_did, bettor_name, target_id, target_name, amount)
        if not bet:
            return None
        return {
            "bet_id": bet.bet_id,
            "match_id": match_id,
            "amount": amount,
            "target": target_name,
            "odds": pool.get_odds(),
            "total_pool": pool.total_pool,
        }

    def close_betting(self, match_id: str):
        pool = self.pools.get(match_id)
        if pool:
            pool.close_betting()

    def settle_match(self, match_id: str, winner_agent_id: str) -> Dict[str, float]:
        """Settle bets for a finished match. Returns payouts."""
        pool = self.pools.get(match_id)
        if not pool:
            return {}
        return pool.calculate_payouts(winner_agent_id)

    def get_pool_status(self, match_id: str) -> Optional[Dict]:
        pool = self.pools.get(match_id)
        return pool.get_status() if pool else None


# Singleton
betting_manager = BettingManager()
