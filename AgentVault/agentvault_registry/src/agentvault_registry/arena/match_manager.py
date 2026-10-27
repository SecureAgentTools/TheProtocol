"""
Match Manager — Handles match lifecycle, agent registration, turn processing.
"""
import asyncio
import logging
import uuid
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .engine import GameState, MAP_SIZE, TURN_TIMEOUT
from .betting import betting_manager
from .redis_state import RedisStringMap, game_registry
from .redis_object_store import RedisObjectStore

logger = logging.getLogger(__name__)


@dataclass
class MatchInfo:
    match_id: str
    mode: str
    max_agents: int
    min_agents: int
    game: GameState
    agent_actions: Dict[str, Dict] = field(default_factory=dict)
    spectator_callbacks: List[Any] = field(default_factory=list)  # per-worker, not persisted
    created_at: float = field(default_factory=time.time)
    turn_deadline: float = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id, "mode": self.mode,
            "max_agents": self.max_agents, "min_agents": self.min_agents,
            "game": self.game.to_dict(),
            "agent_actions": dict(self.agent_actions),
            "created_at": self.created_at,
            "turn_deadline": self.turn_deadline,
            "agent_dids": getattr(self, "_agent_dids", {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MatchInfo":
        obj = cls(
            match_id=data["match_id"], mode=data["mode"],
            max_agents=data["max_agents"], min_agents=data["min_agents"],
            game=GameState.from_dict(data["game"]),
            agent_actions=dict(data.get("agent_actions", {})),
            created_at=data.get("created_at", time.time()),
            turn_deadline=data.get("turn_deadline", 0),
        )
        if data.get("agent_dids"):
            obj._agent_dids = dict(data["agent_dids"])
        return obj


class MatchManager:
    """Manages active matches, turn processing, and agent connections.

    All match state lives in Redis (via RedisObjectStore) so any of the 16
    uvicorn workers can service any request. Methods are async and
    read-modify-write through the store on each call.
    """

    def __init__(self):
        # Redis-backed match store — shared across all uvicorn workers.
        self.matches: RedisObjectStore = RedisObjectStore(
            "rw_matches", MatchInfo.from_dict, MatchInfo.to_dict
        )
        # Agent-to-match mapping — synced to Redis for cross-worker visibility
        self.agent_to_match: RedisStringMap = RedisStringMap("rw_agent_to_match")
        self._bot_counter = 0

    async def create_match(self, mode: str = "battle_royale", max_agents: int = 4, min_agents: int = 2) -> MatchInfo:
        """Create a new match waiting for agents."""
        match_id = f"RW-{uuid.uuid4().hex[:8].upper()}"
        game = GameState(match_id=match_id, mode=mode)
        match = MatchInfo(
            match_id=match_id,
            mode=mode,
            max_agents=max_agents,
            min_agents=min_agents,
            game=game,
        )
        await self.matches.aset(match_id, match)
        logger.info(f"[Arena] Match created: {match_id} (mode={mode}, max={max_agents})")
        await game_registry.register_game(match_id, "robowars")
        return match

    async def join_match(self, match_id: str, agent_id: str, agent_name: str) -> Optional[Dict]:
        """Agent joins a match."""
        match = await self.matches.aget(match_id)
        if not match:
            return {"error": "Match not found"}
        if match.game.started:
            return {"error": "Match already started"}
        if len(match.game.agents) >= match.max_agents:
            return {"error": "Match is full"}
        if agent_id in match.game.agents:
            return {"error": "Already in this match"}

        agent = match.game.add_agent(agent_id, agent_name)
        self.agent_to_match[agent_id] = match_id
        await self.agent_to_match.aset(agent_id, match_id)

        logger.info(f"[Arena] {agent_name} ({agent_id[:20]}) joined {match_id} at ({agent.x},{agent.y})")

        # Auto-start when enough agents
        if len(match.game.agents) >= match.min_agents:
            self._start_match(match)

        await self.matches.aset(match_id, match)

        return {
            "match_id": match_id,
            "position": {"x": agent.x, "y": agent.y},
            "agents_joined": len(match.game.agents),
            "max_agents": match.max_agents,
            "started": match.game.started,
        }

    async def add_bot(self, match_id: str) -> Optional[Dict]:
        """Add a simple AI bot to the match."""
        self._bot_counter += 1
        bot_names = ["Terminator", "Reaper", "Shadow", "Vortex", "Phantom", "Sentinel", "Havoc", "Blitz"]
        name = f"BOT-{bot_names[self._bot_counter % len(bot_names)]}"
        bot_id = f"bot:{uuid.uuid4().hex[:8]}"
        return await self.join_match(match_id, bot_id, name)

    def _start_match(self, match: MatchInfo):
        """Start a match (sync; caller handles persistence)."""
        match.game.start_match()
        match.turn_deadline = time.time() + TURN_TIMEOUT
        # Close betting
        betting_manager.close_betting(match.match_id)
        logger.info(f"[Arena] Match {match.match_id} STARTED with {len(match.game.agents)} agents")

    async def submit_action(self, agent_id: str, action: str, params: Dict) -> Optional[Dict]:
        """Agent submits their action for the current turn."""
        match_id = await self.agent_to_match.aget(agent_id)
        if not match_id:
            return {"error": "Not in a match"}

        match = await self.matches.aget(match_id)
        if not match or not match.game.started or match.game.finished:
            return {"error": "Match not active"}

        # Process action immediately and return result
        result = match.game.process_action(agent_id, action, params)

        # Only commit the action (advance turn) when it succeeded. Failed
        # moves (wall blocks, out-of-bounds) and failed shoots (no target /
        # no ammo) stay retryable in the same turn — prevents agents from
        # burning turns by bumping into walls while the storm + bots tick on.
        if result.get("success"):
            match.agent_actions[agent_id] = {"action": action, "params": params, "result": result}

            # Check if all alive NON-BOT agents have acted → advance turn
            alive_humans = [a.agent_id for a in match.game.agents.values() if a.alive and not a.agent_id.startswith("bot:")]
            all_acted = all(aid in match.agent_actions for aid in alive_humans)

            if all_acted:
                self._advance_turn(match)

        await self.matches.aset(match_id, match)
        return result

    def _advance_turn(self, match: MatchInfo):
        """Process end-of-turn and advance."""
        # Run bots
        for agent_id, agent in match.game.agents.items():
            if agent_id.startswith("bot:") and agent.alive and agent_id not in match.agent_actions:
                self._bot_action(match, agent)

        match.game.process_turn_end()
        match.agent_actions.clear()
        match.turn_deadline = time.time() + TURN_TIMEOUT

        if match.game.finished:
            winner = match.game.agents.get(match.game.winner)
            winner_name = winner.name if winner else "unknown"
            total_kills = sum(a.kills for a in match.game.agents.values())
            logger.info(
                f"[Arena] Match {match.match_id} FINISHED — "
                f"winner: {winner_name} ({match.game.winner}), "
                f"turns: {match.game.turn}, kills: {total_kills}"
            )
            # Settle bets
            if match.game.winner:
                payouts = betting_manager.settle_match(match.match_id, match.game.winner)
                if payouts:
                    logger.info(f"[Arena] Bets settled for {match.match_id}: {len(payouts)} payouts")

            # Persist game results (async, non-blocking)
            self._persist_robowars_results(match)

    def _bot_action(self, match: MatchInfo, agent):
        """Aggressive bot AI — hunts, loots, uses items, swaps weapons."""
        import random as rng
        from .engine import DIRECTIONS, MAP_SIZE, WEAPON_STATS
        game = match.game

        visible_enemies = game.get_visible_agents(agent)
        visible_items = game.get_visible_items(agent)

        # Use health kit if hurt
        if agent.health < 60:
            from .engine import ItemType
            if ItemType.HEALTH_KIT in agent.inventory:
                result = game.process_action(agent.agent_id, "use_item", {"item": "health_kit"})
                match.agent_actions[agent.agent_id] = {"action": "use_item", "result": result}
                return

        # COMBAT: Shoot if enemy visible and in range
        if visible_enemies and agent.active_weapon.ammo > 0:
            nearest = min(visible_enemies, key=lambda e: abs(e["x"] - agent.x) + abs(e["y"] - agent.y))
            dist = abs(nearest["x"] - agent.x) + abs(nearest["y"] - agent.y)
            weapon_range = agent.active_weapon.stats["range"]

            if dist <= weapon_range:
                # Shoot
                dx = nearest["x"] - agent.x
                dy = nearest["y"] - agent.y
                # Pick best cardinal/diagonal direction
                direction = self._best_direction(dx, dy)
                result = game.process_action(agent.agent_id, "shoot", {"direction": direction})
                match.agent_actions[agent.agent_id] = {"action": "shoot", "result": result}
                return
            else:
                # Move toward enemy to get in range
                direction = self._best_direction(nearest["x"] - agent.x, nearest["y"] - agent.y)
                result = game.process_action(agent.agent_id, "move", {"direction": direction})
                if result.get("success"):
                    match.agent_actions[agent.agent_id] = {"action": "move", "result": result}
                    return

        # LOOT: Pick up items at current position
        for item in game.items:
            if not item.picked_up and item.x == agent.x and item.y == agent.y:
                result = game.process_action(agent.agent_id, "pickup", {})
                match.agent_actions[agent.agent_id] = {"action": "pickup", "result": result}
                return

        # LOOT: Move toward nearest valuable item
        if visible_items:
            # Prioritize weapons > ammo > health > armor
            def item_priority(i):
                if i["type"] in ("rifle", "shotgun", "grenade"):
                    return 0
                if i["type"] == "ammo_crate":
                    return 1 if agent.active_weapon.ammo < 4 else 5
                if i["type"] == "health_kit":
                    return 2 if agent.health < 80 else 6
                if i["type"] in ("armor_vest", "scope"):
                    return 3
                return 7

            sorted_items = sorted(visible_items, key=item_priority)
            target = sorted_items[0]
            dx = target["x"] - agent.x
            dy = target["y"] - agent.y
            if dx == 0 and dy == 0:
                result = game.process_action(agent.agent_id, "pickup", {})
            else:
                direction = self._best_direction(dx, dy)
                result = game.process_action(agent.agent_id, "move", {"direction": direction})
            match.agent_actions[agent.agent_id] = {"action": "move", "result": result}
            return

        # HUNT: Move toward center or roam aggressively
        center_x, center_y = MAP_SIZE // 2, MAP_SIZE // 2
        dx = center_x - agent.x
        dy = center_y - agent.y

        # Add randomness to prevent getting stuck
        if abs(dx) < 5 and abs(dy) < 5:
            # Near center — roam randomly
            dirs = list(DIRECTIONS.keys())
            rng.shuffle(dirs)
            for direction in dirs:
                result = game.process_action(agent.agent_id, "move", {"direction": direction})
                if result.get("success"):
                    match.agent_actions[agent.agent_id] = {"action": "move", "result": result}
                    return
        else:
            # Move toward center but with variation
            if rng.random() < 0.7:
                direction = self._best_direction(dx, dy)
            else:
                direction = rng.choice(list(DIRECTIONS.keys()))

            result = game.process_action(agent.agent_id, "move", {"direction": direction})
            if result.get("success"):
                match.agent_actions[agent.agent_id] = {"action": "move", "result": result}
                return

            # Wall hit — try other directions
            for direction in rng.sample(list(DIRECTIONS.keys()), len(DIRECTIONS)):
                result = game.process_action(agent.agent_id, "move", {"direction": direction})
                if result.get("success"):
                    match.agent_actions[agent.agent_id] = {"action": "move", "result": result}
                    return

        # Fallback — wait
        match.agent_actions[agent.agent_id] = {"action": "wait", "result": {"success": True}}

    def _best_direction(self, dx: int, dy: int) -> str:
        """Pick the best direction for a given dx/dy vector."""
        if dx > 0 and dy < 0: return "northeast"
        if dx > 0 and dy > 0: return "southeast"
        if dx < 0 and dy < 0: return "northwest"
        if dx < 0 and dy > 0: return "southwest"
        if abs(dx) >= abs(dy):
            return "east" if dx > 0 else "west"
        return "south" if dy > 0 else "north"

    async def force_advance_turn(self, match_id: str):
        """Force-advance if turn timeout expired."""
        match = await self.matches.aget(match_id)
        if match and match.game.started and not match.game.finished:
            if time.time() > match.turn_deadline:
                self._advance_turn(match)
                await self.matches.aset(match_id, match)

    async def get_match(self, match_id: str) -> Optional[MatchInfo]:
        return await self.matches.aget(match_id)

    async def get_agent_match(self, agent_id: str) -> Optional[MatchInfo]:
        match_id = await self.agent_to_match.aget(agent_id)
        return await self.matches.aget(match_id) if match_id else None

    async def list_matches(self) -> List[Dict]:
        """List all matches."""
        result = []
        for m in await self.matches.avalues():
            winner_name = None
            if m.game.winner:
                w = m.game.agents.get(m.game.winner)
                winner_name = w.name if w else None
            agent_names = [a.name for a in m.game.agents.values()]
            result.append({
                "match_id": m.match_id,
                "mode": m.mode,
                "agents": len(m.game.agents),
                "agent_names": agent_names,
                "max_agents": m.max_agents,
                "started": m.game.started,
                "finished": m.game.finished,
                "turn": m.game.turn,
                "winner": m.game.winner,
                "winner_name": winner_name,
            })
        # Active matches first, then recent finished
        result.sort(key=lambda x: (x["finished"], -x["turn"]))
        return result

    def _persist_robowars_results(self, match: MatchInfo):
        """Persist match results to DB (async, fire-and-forget)."""
        try:
            import asyncio
            from .game_persistence import persist_game_results

            agent_dids = getattr(match, '_agent_dids', {})
            sorted_agents = sorted(match.game.agents.values(), key=lambda a: (not a.alive, -a.kills))

            results = []
            for idx, agent in enumerate(sorted_agents):
                results.append({
                    "match_id": match.match_id,
                    "game_type": "robowars",
                    "agent_did": agent_dids.get(agent.agent_id),
                    "agent_name": agent.name,
                    "score": agent.kills,
                    "placement": idx + 1,
                    "turns": match.game.turn,
                    "stats": {
                        "kills": agent.kills,
                        "health": agent.health,
                        "weapon": agent.active_weapon.weapon_type if hasattr(agent, 'active_weapon') else "pistol",
                        "alive_at_end": agent.alive,
                    },
                    "is_bot": agent.agent_id.startswith("bot:"),
                })

            # Fire and forget — get or create event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(persist_game_results(results))
            except RuntimeError:
                asyncio.run(persist_game_results(results))
        except Exception as e:
            logger.error(f"[Arena] Failed to persist results for {match.match_id}: {e}")

    async def cleanup_finished(self, max_age: float = 3600):
        """Remove finished matches older than max_age seconds."""
        now = time.time()
        to_remove = []
        for mid, m in await self.matches.aitems():
            if m.game.finished and m.game.finished_at and (now - m.game.finished_at) > max_age:
                to_remove.append(mid)
        for mid in to_remove:
            # Clean agent mapping
            for aid in list(self.agent_to_match):
                if self.agent_to_match.get(aid) == mid:
                    del self.agent_to_match[aid]
            await self.matches.adel(mid)


# Singleton
match_manager = MatchManager()
