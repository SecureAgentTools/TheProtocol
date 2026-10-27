"""
Game Lobby System — Shared lobby for all game types.

Create a lobby → invite agents by DID → countdown → fill bots → start game.
Supports webhook notifications for invites and game starts.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Awaitable

from .redis_state import RedisStringMap

logger = logging.getLogger(__name__)


@dataclass
class LobbySlot:
    """A slot in a lobby."""
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_did: Optional[str] = None
    is_bot: bool = False
    joined: bool = False


@dataclass
class Lobby:
    """A game lobby waiting for players."""
    lobby_id: str
    game_type: str  # "robowars", "tower_defense", "snake", "trading"
    creator_id: str
    creator_name: str
    creator_did: Optional[str] = None
    max_players: int = 4
    fill_bots: bool = True
    countdown_seconds: int = 120
    min_players: int = 2
    game_settings: Dict[str, Any] = field(default_factory=dict)

    # State
    slots: List[LobbySlot] = field(default_factory=list)
    invited_dids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    started: bool = False
    expired: bool = False
    game_match_id: Optional[str] = None  # Set when game starts

    @property
    def players_joined(self) -> int:
        return sum(1 for s in self.slots if s.joined and not s.is_bot)

    @property
    def time_remaining(self) -> float:
        elapsed = time.time() - self.created_at
        return max(0, self.countdown_seconds - elapsed)

    @property
    def is_full(self) -> bool:
        return self.players_joined >= self.max_players

    @property
    def is_countdown_expired(self) -> bool:
        return self.time_remaining <= 0

    def to_dict(self) -> Dict:
        return {
            "lobby_id": self.lobby_id,
            "game_type": self.game_type,
            "creator": self.creator_name,
            "max_players": self.max_players,
            "players_joined": self.players_joined,
            "fill_bots": self.fill_bots,
            "countdown_seconds": self.countdown_seconds,
            "time_remaining": round(self.time_remaining),
            "started": self.started,
            "expired": self.expired,
            "game_match_id": self.game_match_id,
            "invited": self.invited_dids,
            "players": [
                {"name": s.agent_name, "did": s.agent_did, "is_bot": s.is_bot}
                for s in self.slots if s.joined
            ],
            "created_at": self.created_at,
        }


# Game starter functions — registered by each game module
GameStarterFn = Callable[[Lobby], Awaitable[str]]  # Returns match_id

_game_starters: Dict[str, GameStarterFn] = {}


def register_game_starter(game_type: str, starter: GameStarterFn):
    """Register a function that creates a game from a lobby."""
    _game_starters[game_type] = starter
    logger.info(f"[Lobby] Registered game starter for: {game_type}")


class LobbyManager:
    """Manages game lobbies across all game types."""

    def __init__(self):
        self.lobbies: Dict[str, Lobby] = {}
        # Agent-to-lobby mapping for cross-worker visibility
        self._lobby_agent_map: RedisStringMap = RedisStringMap("lobby_agent_map")
        self._check_task: Optional[asyncio.Task] = None

    def create_lobby(
        self,
        game_type: str,
        creator_id: str,
        creator_name: str,
        creator_did: Optional[str] = None,
        max_players: int = 4,
        fill_bots: bool = True,
        countdown_seconds: int = 120,
        game_settings: Optional[Dict] = None,
    ) -> Lobby:
        """Create a new lobby."""
        if game_type not in _game_starters:
            raise ValueError(f"Unknown game type: {game_type}. Available: {list(_game_starters.keys())}")

        lobby_id = f"LOBBY-{uuid.uuid4().hex[:8].upper()}"
        lobby = Lobby(
            lobby_id=lobby_id,
            game_type=game_type,
            creator_id=creator_id,
            creator_name=creator_name,
            creator_did=creator_did,
            max_players=max(2, min(8, max_players)),
            fill_bots=fill_bots,
            countdown_seconds=max(10, min(600, countdown_seconds)),
            game_settings=game_settings or {},
        )

        # Creator auto-joins
        lobby.slots.append(LobbySlot(
            agent_id=creator_id,
            agent_name=creator_name,
            agent_did=creator_did,
            joined=True,
        ))

        self.lobbies[lobby_id] = lobby
        self._lobby_agent_map[creator_id] = lobby_id
        logger.info(f"[Lobby] Created {lobby_id} for {game_type} by {creator_name} (countdown: {countdown_seconds}s)")

        # Start countdown checker if not running
        self._ensure_checker()

        return lobby

    def join_lobby(self, lobby_id: str, agent_id: str, agent_name: str, agent_did: Optional[str] = None) -> Optional[Dict]:
        """Join an existing lobby."""
        lobby = self.lobbies.get(lobby_id)
        if not lobby:
            return {"error": "Lobby not found"}
        if lobby.started:
            return {"error": "Game already started", "game_match_id": lobby.game_match_id}
        if lobby.expired:
            return {"error": "Lobby expired"}
        if lobby.is_full:
            return {"error": "Lobby is full"}

        # Check if already joined
        for s in lobby.slots:
            if s.agent_id == agent_id:
                return {"error": "Already in this lobby"}

        lobby.slots.append(LobbySlot(
            agent_id=agent_id,
            agent_name=agent_name,
            agent_did=agent_did,
            joined=True,
        ))
        self._lobby_agent_map[agent_id] = lobby_id

        logger.info(f"[Lobby] {agent_name} joined {lobby_id} ({lobby.players_joined}/{lobby.max_players})")

        result = {
            "lobby_id": lobby_id,
            "players_joined": lobby.players_joined,
            "max_players": lobby.max_players,
            "time_remaining": round(lobby.time_remaining),
            "game_type": lobby.game_type,
        }

        # Auto-start if full
        if lobby.is_full:
            asyncio.ensure_future(self._start_game(lobby))
            result["starting"] = True

        return result

    def invite_to_lobby(self, lobby_id: str, agent_did: str) -> Optional[Dict]:
        """Invite an agent by DID."""
        lobby = self.lobbies.get(lobby_id)
        if not lobby:
            return {"error": "Lobby not found"}
        if lobby.started or lobby.expired:
            return {"error": "Lobby not active"}
        if agent_did in lobby.invited_dids:
            return {"error": "Already invited"}

        lobby.invited_dids.append(agent_did)
        logger.info(f"[Lobby] Invited {agent_did} to {lobby_id}")

        # Fire webhook (async, non-blocking)
        asyncio.ensure_future(self._send_invite_webhook(lobby, agent_did))

        return {
            "lobby_id": lobby_id,
            "invited": agent_did,
            "total_invited": len(lobby.invited_dids),
        }

    def get_lobby(self, lobby_id: str) -> Optional[Dict]:
        lobby = self.lobbies.get(lobby_id)
        if not lobby:
            return None
        return lobby.to_dict()

    def list_lobbies(self, game_type: Optional[str] = None) -> List[Dict]:
        result = []
        for lobby in self.lobbies.values():
            if lobby.started or lobby.expired:
                continue
            if game_type and lobby.game_type != game_type:
                continue
            result.append(lobby.to_dict())
        result.sort(key=lambda x: x["time_remaining"])
        return result

    async def _start_game(self, lobby: Lobby):
        """Start the game from a lobby."""
        if lobby.started:
            return

        lobby.started = True

        # Fill empty slots with bots
        if lobby.fill_bots:
            bot_names = ["AlphaBot", "BetaBot", "GammaBot", "DeltaBot", "EpsilonBot", "ZetaBot"]
            bot_idx = 0
            while lobby.players_joined + sum(1 for s in lobby.slots if s.is_bot) < lobby.max_players:
                lobby.slots.append(LobbySlot(
                    agent_id=f"bot:lobby:{uuid.uuid4().hex[:6]}",
                    agent_name=f"BOT-{bot_names[bot_idx % len(bot_names)]}",
                    is_bot=True,
                    joined=True,
                ))
                bot_idx += 1

        # Call the game starter
        starter = _game_starters.get(lobby.game_type)
        if starter:
            try:
                match_id = await starter(lobby)
                lobby.game_match_id = match_id
                logger.info(f"[Lobby] {lobby.lobby_id} → Game started: {match_id}")

                # Fire webhook for game start
                asyncio.ensure_future(self._send_start_webhook(lobby))
            except Exception as e:
                logger.error(f"[Lobby] Failed to start game from {lobby.lobby_id}: {e}")
                lobby.started = False

    async def _check_countdowns(self):
        """Background task: check lobby countdowns and start games."""
        while True:
            try:
                await asyncio.sleep(2)
                for lobby in list(self.lobbies.values()):
                    if lobby.started or lobby.expired:
                        continue
                    if lobby.is_countdown_expired:
                        if lobby.players_joined >= lobby.min_players or lobby.fill_bots:
                            await self._start_game(lobby)
                        else:
                            lobby.expired = True
                            logger.info(f"[Lobby] {lobby.lobby_id} expired (not enough players)")

                # Cleanup old lobbies (>1 hour)
                now = time.time()
                to_remove = [lid for lid, l in self.lobbies.items()
                             if (l.started or l.expired) and now - l.created_at > 3600]
                for lid in to_remove:
                    del self.lobbies[lid]
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Lobby] Countdown check error: {e}")

    def _ensure_checker(self):
        """Ensure the countdown checker task is running."""
        if self._check_task is None or self._check_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._check_task = loop.create_task(self._check_countdowns())
            except RuntimeError:
                pass

    async def _send_invite_webhook(self, lobby: Lobby, agent_did: str):
        """Send webhook notification for a game invite."""
        # §TWOAGENT #34 class (2026-09-23): the invite goes to the INVITED agent's developer. emit_event's agent_did does
        # not filter subscribers, so this reached every game.invite subscriber on the frame, addressed "You've been invited".
        try:
            from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents

            await dispatch_webhook_for_agents(
                "game.invite",
                {
                    "lobby_id": lobby.lobby_id,
                    "game_type": lobby.game_type,
                    "creator": lobby.creator_name,
                    "creator_did": lobby.creator_did,
                    "max_players": lobby.max_players,
                    "time_remaining": round(lobby.time_remaining),
                    "message": f"You've been invited to a {lobby.game_type} game by {lobby.creator_name}!",
                },
                [agent_did],
                source_label="arena.lobby.invite",
            )
        except Exception as e:
            logger.error(f"[Lobby] Webhook invite failed for {agent_did}: {e}")

    async def _send_start_webhook(self, lobby: Lobby):
        """Send webhook notification that the game has started."""
        # §TWOAGENT #34 class (2026-09-23): to each PLAYER's own developer, never every game.started subscriber.
        try:
            from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents

            player_dids = [s.agent_did for s in lobby.slots if s.agent_did and s.joined]
            for did in player_dids:
                await dispatch_webhook_for_agents(
                    "game.started",
                    {
                        "lobby_id": lobby.lobby_id,
                        "game_type": lobby.game_type,
                        "game_match_id": lobby.game_match_id,
                        "players": [s.agent_name for s in lobby.slots if s.joined],
                        "message": f"Your {lobby.game_type} game has started! Match: {lobby.game_match_id}",
                    },
                    [did],
                    source_label="arena.lobby.started",
                )
        except Exception as e:
            logger.error(f"[Lobby] Webhook start failed: {e}")


# Singleton
lobby_manager = LobbyManager()
