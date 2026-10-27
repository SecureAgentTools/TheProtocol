"""
Robo Wars Game Engine — Turn-based top-down extraction shooter.

Grid-based game state with simultaneous turn resolution.
40x40 map, fog of war, 4 weapons, items, storm circle.
"""
import random
import math
import uuid
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum


class TileType(str, Enum):
    FLOOR = "floor"
    WALL = "wall"
    BUSH = "bush"       # Cover — hidden from vision
    WATER = "water"     # Slow (costs 2 move actions)
    CRATE = "crate"     # Destructible, may contain loot
    EXTRACT = "extract" # Extraction zone


class WeaponType(str, Enum):
    PISTOL = "pistol"
    SHOTGUN = "shotgun"
    RIFLE = "rifle"
    GRENADE = "grenade"


class ItemType(str, Enum):
    HEALTH_KIT = "health_kit"
    AMMO_CRATE = "ammo_crate"
    ARMOR_VEST = "armor_vest"
    SCOPE = "scope"
    SHOTGUN = "shotgun"
    RIFLE = "rifle"
    GRENADE = "grenade"


WEAPON_STATS = {
    WeaponType.PISTOL:  {"range": 4, "damage": 15, "max_ammo": 12, "name": "Pistol"},
    WeaponType.SHOTGUN: {"range": 2, "damage": 45, "max_ammo": 6,  "name": "Shotgun"},
    WeaponType.RIFLE:   {"range": 8, "damage": 25, "max_ammo": 8,  "name": "Rifle"},
    WeaponType.GRENADE: {"range": 5, "damage": 60, "max_ammo": 2,  "name": "Grenade"},
}

DIRECTIONS = {
    "north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0),
    "northeast": (1, -1), "northwest": (-1, -1), "southeast": (1, 1), "southwest": (-1, 1),
}

MAP_SIZE = 40
VISION_RADIUS = 7        # bumped from 5: 40x40 maps + fog were starving combat
VISION_RADIUS_SCOPE = 10 # bumped from 8 to preserve scope's edge over base
STORM_SHRINK_INTERVAL = 15
STORM_DAMAGE = 5
MAX_TURNS = 100
TURN_TIMEOUT = 10  # seconds


@dataclass
class Weapon:
    type: WeaponType
    ammo: int

    @property
    def stats(self):
        return WEAPON_STATS[self.type]


@dataclass
class AgentState:
    agent_id: str       # DID
    name: str
    x: int
    y: int
    health: int = 100
    max_health: int = 100
    alive: bool = True
    active_weapon: Weapon = field(default_factory=lambda: Weapon(WeaponType.PISTOL, 12))
    inventory: List[Any] = field(default_factory=list)  # Items + backup weapons
    has_armor: bool = False
    has_scope: bool = False
    kills: int = 0
    damage_dealt: int = 0
    damage_taken: int = 0
    pending_action: Optional[Dict] = None

    @property
    def vision_radius(self):
        return VISION_RADIUS_SCOPE if self.has_scope else VISION_RADIUS


@dataclass
class MapItem:
    x: int
    y: int
    item_type: ItemType
    picked_up: bool = False


@dataclass
class TurnEvent:
    turn: int
    event_type: str  # move, shoot, hit, kill, pickup, use_item, storm_damage, extract
    agent_id: str
    data: Dict = field(default_factory=dict)


# ── Inventory codec ─────────────────────────────────────────────────────
# inventory: List[Any] holds either ItemType enum (for HEALTH_KIT) or Weapon
# dataclass (for picked-up backup weapons). JSON can't round-trip that
# ambiguity, so tag each slot with its kind.

def _inventory_slot_to_dict(slot: Any) -> Dict[str, Any]:
    if isinstance(slot, Weapon):
        return {"kind": "weapon", "type": slot.type.value, "ammo": slot.ammo}
    if isinstance(slot, ItemType):
        return {"kind": "item", "item_type": slot.value}
    # Defensive fallback — shouldn't happen in practice
    return {"kind": "raw", "repr": repr(slot)}


def _inventory_slot_from_dict(d: Dict[str, Any]) -> Any:
    kind = d.get("kind")
    if kind == "weapon":
        return Weapon(type=WeaponType(d["type"]), ammo=d["ammo"])
    if kind == "item":
        return ItemType(d["item_type"])
    return None  # raw slots are dropped — no way to rehydrate


def _weapon_to_dict(w: Weapon) -> Dict[str, Any]:
    return {"type": w.type.value, "ammo": w.ammo}


def _weapon_from_dict(d: Dict[str, Any]) -> Weapon:
    return Weapon(type=WeaponType(d["type"]), ammo=d["ammo"])


def _agent_state_to_dict(a: AgentState) -> Dict[str, Any]:
    return {
        "agent_id": a.agent_id, "name": a.name, "x": a.x, "y": a.y,
        "health": a.health, "max_health": a.max_health, "alive": a.alive,
        "active_weapon": _weapon_to_dict(a.active_weapon),
        "inventory": [_inventory_slot_to_dict(i) for i in a.inventory],
        "has_armor": a.has_armor, "has_scope": a.has_scope,
        "kills": a.kills, "damage_dealt": a.damage_dealt, "damage_taken": a.damage_taken,
        "pending_action": a.pending_action,
    }


def _agent_state_from_dict(d: Dict[str, Any]) -> AgentState:
    inv = [_inventory_slot_from_dict(s) for s in d.get("inventory", [])]
    inv = [s for s in inv if s is not None]
    return AgentState(
        agent_id=d["agent_id"], name=d["name"], x=d["x"], y=d["y"],
        health=d["health"], max_health=d["max_health"], alive=d["alive"],
        active_weapon=_weapon_from_dict(d["active_weapon"]),
        inventory=inv,
        has_armor=d["has_armor"], has_scope=d["has_scope"],
        kills=d["kills"], damage_dealt=d["damage_dealt"], damage_taken=d["damage_taken"],
        pending_action=d.get("pending_action"),
    )


def _map_item_to_dict(m: MapItem) -> Dict[str, Any]:
    return {"x": m.x, "y": m.y, "item_type": m.item_type.value, "picked_up": m.picked_up}


def _map_item_from_dict(d: Dict[str, Any]) -> MapItem:
    return MapItem(x=d["x"], y=d["y"], item_type=ItemType(d["item_type"]), picked_up=d["picked_up"])


def _turn_event_to_dict(e: TurnEvent) -> Dict[str, Any]:
    return {"turn": e.turn, "event_type": e.event_type, "agent_id": e.agent_id, "data": dict(e.data)}


def _turn_event_from_dict(d: Dict[str, Any]) -> TurnEvent:
    return TurnEvent(turn=d["turn"], event_type=d["event_type"], agent_id=d["agent_id"], data=dict(d.get("data", {})))


def _arena_encode_rng(rng: random.Random) -> List[Any]:
    ver, state, gauss = rng.getstate()
    return [ver, list(state), gauss]


def _arena_decode_rng(raw: Optional[List[Any]], seed: int) -> random.Random:
    rng = random.Random(seed)
    if not raw:
        return rng
    try:
        ver, state, gauss = raw
        rng.setstate((ver, tuple(state), gauss))
    except Exception:
        pass
    return rng


class GameState:
    """Complete state of a single match."""

    def __init__(self, match_id: str, mode: str = "battle_royale", map_seed: Optional[int] = None):
        self.match_id = match_id
        self.mode = mode
        self.seed = map_seed or random.randint(0, 999999)
        self.rng = random.Random(self.seed)
        self.turn = 0
        self.started = False
        self.finished = False
        self.winner: Optional[str] = None
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

        # Map
        self.tiles: List[List[TileType]] = []
        self.items: List[MapItem] = []
        self.agents: Dict[str, AgentState] = {}
        self.events: List[TurnEvent] = []
        self.storm_edge = MAP_SIZE  # Storm starts at full map

        # Generate map
        self._generate_map()

    def _generate_map(self):
        """Procedural map generation."""
        rng = self.rng
        self.tiles = [[TileType.FLOOR for _ in range(MAP_SIZE)] for _ in range(MAP_SIZE)]

        # Walls — random clusters
        for _ in range(rng.randint(30, 50)):
            cx, cy = rng.randint(5, MAP_SIZE - 6), rng.randint(5, MAP_SIZE - 6)
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if rng.random() < 0.6:
                        nx, ny = cx + dx, cy + dy
                        if 1 <= nx < MAP_SIZE - 1 and 1 <= ny < MAP_SIZE - 1:
                            self.tiles[ny][nx] = TileType.WALL

        # Bushes — cover clusters
        for _ in range(rng.randint(20, 35)):
            cx, cy = rng.randint(3, MAP_SIZE - 4), rng.randint(3, MAP_SIZE - 4)
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if rng.random() < 0.5:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < MAP_SIZE and 0 <= ny < MAP_SIZE and self.tiles[ny][nx] == TileType.FLOOR:
                            self.tiles[ny][nx] = TileType.BUSH

        # Crates — destructible
        for _ in range(rng.randint(10, 18)):
            x, y = self._random_floor_tile()
            self.tiles[y][x] = TileType.CRATE

        # Extraction zones (4 corners, mode: extraction)
        if self.mode == "extraction":
            for ex, ey in [(2, 2), (MAP_SIZE - 3, 2), (2, MAP_SIZE - 3), (MAP_SIZE - 3, MAP_SIZE - 3)]:
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        nx, ny = ex + dx, ey + dy
                        if 0 <= nx < MAP_SIZE and 0 <= ny < MAP_SIZE:
                            self.tiles[ny][nx] = TileType.EXTRACT

        # Items
        item_types = (
            [ItemType.HEALTH_KIT] * rng.randint(8, 12) +
            [ItemType.AMMO_CRATE] * rng.randint(6, 8) +
            [ItemType.SHOTGUN] * rng.randint(2, 3) +
            [ItemType.RIFLE] * rng.randint(2, 3) +
            [ItemType.GRENADE] * rng.randint(1, 2) +
            [ItemType.ARMOR_VEST] * rng.randint(1, 2) +
            [ItemType.SCOPE] * rng.randint(1, 2)
        )
        for item_type in item_types:
            x, y = self._random_floor_tile()
            self.items.append(MapItem(x=x, y=y, item_type=item_type))

    def _random_floor_tile(self) -> Tuple[int, int]:
        """Find a random walkable tile."""
        for _ in range(100):
            x = self.rng.randint(1, MAP_SIZE - 2)
            y = self.rng.randint(1, MAP_SIZE - 2)
            if self.tiles[y][x] in (TileType.FLOOR, TileType.BUSH):
                return x, y
        return MAP_SIZE // 2, MAP_SIZE // 2

    def add_agent(self, agent_id: str, name: str) -> AgentState:
        """Add agent to match, spawn at random edge."""
        # Spawn at a random edge position
        edge = self.rng.choice(["top", "bottom", "left", "right"])
        for _ in range(50):
            if edge == "top":
                x, y = self.rng.randint(2, MAP_SIZE - 3), self.rng.randint(1, 3)
            elif edge == "bottom":
                x, y = self.rng.randint(2, MAP_SIZE - 3), self.rng.randint(MAP_SIZE - 4, MAP_SIZE - 2)
            elif edge == "left":
                x, y = self.rng.randint(1, 3), self.rng.randint(2, MAP_SIZE - 3)
            else:
                x, y = self.rng.randint(MAP_SIZE - 4, MAP_SIZE - 2), self.rng.randint(2, MAP_SIZE - 3)

            if self.tiles[y][x] in (TileType.FLOOR, TileType.BUSH):
                # Check no other agent here
                if not any(a.x == x and a.y == y for a in self.agents.values()):
                    break

        agent = AgentState(agent_id=agent_id, name=name, x=x, y=y)
        self.agents[agent_id] = agent
        return agent

    def start_match(self):
        """Begin the match."""
        self.started = True
        self.started_at = time.time()
        self.turn = 1

    def get_visible_tiles(self, agent: AgentState) -> List[list]:
        """What an agent can see from their position.

        Returns `[x, y, type]` tuples (as 3-element JSON arrays) rather than
        `{x, y, type}` dicts — same info, ~35% fewer tokens per response.
        """
        visible = []
        r = agent.vision_radius
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                nx, ny = agent.x + dx, agent.y + dy
                if 0 <= nx < MAP_SIZE and 0 <= ny < MAP_SIZE:
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist <= r:
                        visible.append([nx, ny, self.tiles[ny][nx].value])
        return visible

    def get_visible_agents(self, agent: AgentState) -> List[Dict]:
        """Other agents visible to this agent (fog of war)."""
        visible = []
        r = agent.vision_radius
        for other in self.agents.values():
            if other.agent_id == agent.agent_id or not other.alive:
                continue
            dist = math.sqrt((other.x - agent.x) ** 2 + (other.y - agent.y) ** 2)
            if dist <= r:
                # In bush = hidden (unless rifle which ignores bush)
                if self.tiles[other.y][other.x] == TileType.BUSH:
                    if agent.active_weapon.type != WeaponType.RIFLE:
                        continue
                visible.append({
                    "id": other.agent_id, "name": other.name,
                    "x": other.x, "y": other.y,
                    "health": other.health, "weapon": other.active_weapon.type.value,
                })
        return visible

    def get_visible_items(self, agent: AgentState) -> List[Dict]:
        """Items visible to this agent."""
        r = agent.vision_radius
        visible = []
        for item in self.items:
            if item.picked_up:
                continue
            dist = math.sqrt((item.x - agent.x) ** 2 + (item.y - agent.y) ** 2)
            if dist <= r:
                visible.append({"x": item.x, "y": item.y, "type": item.item_type.value})
        return visible

    # ── ASCII view ──────────────────────────────────────────────────────
    _ASCII_TILE_ARENA = {
        TileType.FLOOR: ".",
        TileType.WALL: "#",
        TileType.BUSH: "+",
        TileType.WATER: "~",
        TileType.CRATE: "x",
        TileType.EXTRACT: "E",
    }
    _ASCII_LEGEND_ARENA = (
        ". floor  # wall  + bush  ~ water  x crate  E extract  "
        "@ you  A enemy  ! item  (space = out of vision)"
    )

    def render_ascii_view(self, agent: AgentState) -> Dict[str, Any]:
        """Visible region as a compact string grid (radius x radius square).

        Only tiles within the agent's vision radius are rendered — the rest
        is spaces. The agent is always centered. Enemies (A) and items (!)
        overlay tile symbols; the agent itself (@) overlays everything.
        """
        r = agent.vision_radius
        # Grid side = 2r+1 centered on the agent.
        side = 2 * r + 1
        rows = [[" " for _ in range(side)] for _ in range(side)]
        # Fill tiles within the circular vision radius.
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue
                mx, my = agent.x + dx, agent.y + dy
                if not (0 <= mx < MAP_SIZE and 0 <= my < MAP_SIZE):
                    continue
                rows[dy + r][dx + r] = self._ASCII_TILE_ARENA.get(self.tiles[my][mx], "?")
        # Overlay items
        for item in self.items:
            if item.picked_up:
                continue
            dx, dy = item.x - agent.x, item.y - agent.y
            if dx * dx + dy * dy <= r * r:
                rows[dy + r][dx + r] = "!"
        # Overlay enemies
        for other in self.agents.values():
            if other.agent_id == agent.agent_id or not other.alive:
                continue
            dx, dy = other.x - agent.x, other.y - agent.y
            if dx * dx + dy * dy <= r * r:
                rows[dy + r][dx + r] = "A"
        # Agent at center
        rows[r][r] = "@"
        grid = "\n".join("".join(r_) for r_ in rows)
        return {"grid": grid, "radius": r, "side": side,
                "center": {"x": agent.x, "y": agent.y},
                "legend": self._ASCII_LEGEND_ARENA}

    def process_action(self, agent_id: str, action: str, params: Dict) -> Dict:
        """Process a single agent's action and return result."""
        agent = self.agents.get(agent_id)
        if not agent or not agent.alive:
            return {"success": False, "message": "Agent is dead or not in match"}

        if action == "move":
            return self._do_move(agent, params)
        elif action == "shoot":
            return self._do_shoot(agent, params)
        elif action == "pickup":
            return self._do_pickup(agent)
        elif action == "use_item":
            return self._do_use_item(agent, params)
        elif action == "swap_weapon":
            return self._do_swap_weapon(agent, params)
        elif action == "extract":
            return self._do_extract(agent)
        elif action == "wait":
            return {"success": True, "message": "Waiting..."}
        elif action == "look":
            return self._do_look(agent)
        elif action == "status":
            return self._do_status(agent)
        else:
            return {"success": False, "message": f"Unknown action: {action}"}

    def _do_look(self, agent: AgentState) -> Dict:
        return {
            "success": True,
            "position": {"x": agent.x, "y": agent.y},
            "vision_radius": agent.vision_radius,
            "visible_tiles": self.get_visible_tiles(agent),
            "visible_agents": self.get_visible_agents(agent),
            "visible_items": self.get_visible_items(agent),
            "storm_edge": self.storm_edge,
            "turn": self.turn,
            "agents_alive": sum(1 for a in self.agents.values() if a.alive),
            # Compact ASCII view centered on the agent — a (2r+1)x(2r+1)
            # grid. Easier for LLM callers than visible_tiles/agents/items.
            "ascii_map": self.render_ascii_view(agent),
        }

    def _do_status(self, agent: AgentState) -> Dict:
        inv_names = []
        for item in agent.inventory:
            if isinstance(item, Weapon):
                inv_names.append(f"{item.type.value} ({item.ammo} ammo)")
            else:
                inv_names.append(item.value if hasattr(item, 'value') else str(item))
        return {
            "success": True,
            "health": agent.health,
            "max_health": agent.max_health,
            "armor": agent.has_armor,
            "scope": agent.has_scope,
            "position": {"x": agent.x, "y": agent.y},
            "active_weapon": agent.active_weapon.type.value,
            "ammo": agent.active_weapon.ammo,
            "inventory": inv_names,
            "kills": agent.kills,
            "damage_dealt": agent.damage_dealt,
            "turn": self.turn,
            "agents_alive": sum(1 for a in self.agents.values() if a.alive),
            "storm_edge": self.storm_edge,
            "mode": self.mode,
        }

    def _open_directions_from(self, x: int, y: int) -> List[str]:
        """Return the subset of DIRECTIONS whose target tile is walkable
        from (x, y). Used to hint at valid moves when one fails."""
        open_dirs = []
        for name, (dx, dy) in DIRECTIONS.items():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < MAP_SIZE and 0 <= ny < MAP_SIZE):
                continue
            if self.tiles[ny][nx] == TileType.WALL:
                continue
            open_dirs.append(name)
        return open_dirs

    def _do_move(self, agent: AgentState, params: Dict) -> Dict:
        direction = params.get("direction", "").lower()
        if direction not in DIRECTIONS:
            return {"success": False, "message": f"Invalid direction: {direction}. Use: {list(DIRECTIONS.keys())}"}

        dx, dy = DIRECTIONS[direction]
        nx, ny = agent.x + dx, agent.y + dy

        if not (0 <= nx < MAP_SIZE and 0 <= ny < MAP_SIZE):
            return {
                "success": False,
                "message": "Can't move out of bounds",
                "valid_directions": self._open_directions_from(agent.x, agent.y),
            }

        tile = self.tiles[ny][nx]
        if tile == TileType.WALL:
            return {
                "success": False,
                "message": "Wall blocks movement",
                "valid_directions": self._open_directions_from(agent.x, agent.y),
            }

        agent.x, agent.y = nx, ny
        self.events.append(TurnEvent(self.turn, "move", agent.agent_id, {"direction": direction, "x": nx, "y": ny}))

        return {
            "success": True,
            "new_position": {"x": nx, "y": ny},
            "tile_type": tile.value,
            "message": f"Moved {direction}",
        }

    def _do_shoot(self, agent: AgentState, params: Dict) -> Dict:
        direction = params.get("direction", "").lower()
        if direction not in DIRECTIONS:
            return {"success": False, "message": f"Invalid direction: {direction}"}

        weapon = agent.active_weapon
        if weapon.ammo <= 0:
            return {"success": False, "message": "No ammo! Pick up an ammo crate or swap weapon."}

        weapon.ammo -= 1
        dx, dy = DIRECTIONS[direction]
        stats = weapon.stats
        hit_target = None

        # Grenade: area damage
        if weapon.type == WeaponType.GRENADE:
            tx, ty = agent.x + dx * 3, agent.y + dy * 3  # Throw 3 tiles
            for target in self.agents.values():
                if target.agent_id == agent.agent_id or not target.alive:
                    continue
                dist = math.sqrt((target.x - tx) ** 2 + (target.y - ty) ** 2)
                if dist <= 1.5:  # Blast radius
                    dmg = stats["damage"]
                    if target.has_armor:
                        dmg = int(dmg * 0.7)
                    target.health -= dmg
                    target.damage_taken += dmg
                    agent.damage_dealt += dmg
                    hit_target = target
                    # Destroy crates in blast
                    for bx in range(max(0, tx - 1), min(MAP_SIZE, tx + 2)):
                        for by in range(max(0, ty - 1), min(MAP_SIZE, ty + 2)):
                            if self.tiles[by][bx] == TileType.CRATE:
                                self.tiles[by][bx] = TileType.FLOOR
        else:
            # Line-of-fire: check tiles in direction up to range
            for step in range(1, stats["range"] + 1):
                tx, ty = agent.x + dx * step, agent.y + dy * step
                if not (0 <= tx < MAP_SIZE and 0 <= ty < MAP_SIZE):
                    break
                # Wall blocks shot
                if self.tiles[ty][tx] == TileType.WALL:
                    break
                # Bush blocks shot (unless rifle)
                if self.tiles[ty][tx] == TileType.BUSH and weapon.type != WeaponType.RIFLE:
                    break
                # Check for agent at this position
                for target in self.agents.values():
                    if target.agent_id == agent.agent_id or not target.alive:
                        continue
                    if target.x == tx and target.y == ty:
                        dmg = stats["damage"]
                        # Shotgun bonus at close range
                        if weapon.type == WeaponType.SHOTGUN and step <= 1:
                            dmg = int(dmg * 1.3)
                        if target.has_armor:
                            dmg = int(dmg * 0.7)
                        target.health -= dmg
                        target.damage_taken += dmg
                        agent.damage_dealt += dmg
                        hit_target = target
                        break
                if hit_target:
                    break

        self.events.append(TurnEvent(self.turn, "shoot", agent.agent_id, {
            "direction": direction, "weapon": weapon.type.value,
            "hit": hit_target is not None,
            "target": hit_target.name if hit_target else None,
        }))

        result = {
            "success": True,
            "weapon": weapon.type.value,
            "ammo_remaining": weapon.ammo,
            "hit": hit_target is not None,
        }

        if hit_target:
            # Check kill
            if hit_target.health <= 0:
                hit_target.health = 0
                hit_target.alive = False
                agent.kills += 1
                self.events.append(TurnEvent(self.turn, "kill", agent.agent_id, {
                    "victim": hit_target.name, "victim_id": hit_target.agent_id,
                    "weapon": weapon.type.value,
                }))
                # Drop items
                for item in hit_target.inventory:
                    if isinstance(item, Weapon):
                        self.items.append(MapItem(hit_target.x, hit_target.y, ItemType(item.type.value)))
                result["target"] = {
                    "id": hit_target.agent_id, "name": hit_target.name,
                    "damage": stats["damage"], "remaining_health": 0, "killed": True,
                }
                result["message"] = f"Eliminated {hit_target.name}!"
            else:
                result["target"] = {
                    "id": hit_target.agent_id, "name": hit_target.name,
                    "damage": stats["damage"], "remaining_health": hit_target.health, "killed": False,
                }
                result["message"] = f"Hit {hit_target.name} for {stats['damage']} damage!"
        else:
            result["message"] = f"Shot {direction} — missed"

        return result

    def _do_pickup(self, agent: AgentState) -> Dict:
        for item in self.items:
            if item.picked_up or item.x != agent.x or item.y != agent.y:
                continue

            item.picked_up = True
            self.events.append(TurnEvent(self.turn, "pickup", agent.agent_id, {"item": item.item_type.value}))

            if item.item_type == ItemType.HEALTH_KIT:
                agent.inventory.append(item.item_type)
                return {"success": True, "item": "health_kit", "message": "Picked up Health Kit"}
            elif item.item_type == ItemType.AMMO_CRATE:
                agent.active_weapon.ammo = WEAPON_STATS[agent.active_weapon.type]["max_ammo"]
                return {"success": True, "item": "ammo_crate", "message": f"Ammo refilled! {agent.active_weapon.type.value}: {agent.active_weapon.ammo}"}
            elif item.item_type == ItemType.ARMOR_VEST:
                agent.has_armor = True
                return {"success": True, "item": "armor_vest", "message": "Equipped Armor Vest (30% damage reduction)"}
            elif item.item_type == ItemType.SCOPE:
                agent.has_scope = True
                return {"success": True, "item": "scope", "message": f"Equipped Scope (vision radius: {agent.vision_radius})"}
            elif item.item_type in (ItemType.SHOTGUN, ItemType.RIFLE, ItemType.GRENADE):
                wtype = WeaponType(item.item_type.value)
                new_weapon = Weapon(wtype, WEAPON_STATS[wtype]["max_ammo"])
                agent.inventory.append(new_weapon)
                return {"success": True, "item": item.item_type.value, "message": f"Picked up {WEAPON_STATS[wtype]['name']} ({new_weapon.ammo} ammo)"}

        return {"success": False, "message": "No items at your position"}

    def _do_use_item(self, agent: AgentState, params: Dict) -> Dict:
        item_name = params.get("item", "")
        if item_name == "health_kit":
            if ItemType.HEALTH_KIT in agent.inventory:
                agent.inventory.remove(ItemType.HEALTH_KIT)
                old_hp = agent.health
                agent.health = min(agent.max_health, agent.health + 40)
                self.events.append(TurnEvent(self.turn, "use_item", agent.agent_id, {"item": "health_kit"}))
                return {"success": True, "health_before": old_hp, "health_after": agent.health, "message": f"Used Health Kit. HP: {old_hp} → {agent.health}"}
            return {"success": False, "message": "No Health Kit in inventory"}
        return {"success": False, "message": f"Unknown item: {item_name}"}

    def _do_swap_weapon(self, agent: AgentState, params: Dict) -> Dict:
        weapon_name = params.get("weapon", "")
        for i, item in enumerate(agent.inventory):
            if isinstance(item, Weapon) and item.type.value == weapon_name:
                # Swap
                old = agent.active_weapon
                agent.active_weapon = item
                agent.inventory[i] = old
                return {"success": True, "active_weapon": agent.active_weapon.type.value, "ammo": agent.active_weapon.ammo}
        return {"success": False, "message": f"No {weapon_name} in inventory"}

    def _do_extract(self, agent: AgentState) -> Dict:
        if self.mode != "extraction":
            return {"success": False, "message": "Extraction not available in Battle Royale mode"}
        if self.tiles[agent.y][agent.x] != TileType.EXTRACT:
            return {"success": False, "message": "Not on an extraction zone"}
        # Win!
        self.winner = agent.agent_id
        self.finished = True
        self.finished_at = time.time()
        return {"success": True, "message": "Extraction successful! You win!"}

    def process_turn_end(self):
        """End-of-turn processing: storm, death check, win check."""
        turn_events = []

        # Storm shrink — accelerates over time
        # Phase 1 (turns 1-30): shrink 2 every 10 turns (gentle)
        # Phase 2 (turns 31-60): shrink 3 every 5 turns (aggressive)
        # Phase 3 (turns 61+): shrink 2 every 2 turns (lethal closing)
        if self.turn > 0:
            if self.turn <= 30 and self.turn % 10 == 0:
                self.storm_edge = max(3, self.storm_edge - 2)
            elif self.turn <= 60 and self.turn % 5 == 0:
                self.storm_edge = max(2, self.storm_edge - 3)
            elif self.turn > 60 and self.turn % 2 == 0:
                self.storm_edge = max(1, self.storm_edge - 2)

        # Storm damage — increases over time
        # Phase 1: 5 damage, Phase 2: 10, Phase 3 (sudden death): 25
        if self.turn <= 30:
            storm_dmg = STORM_DAMAGE
        elif self.turn <= 60:
            storm_dmg = STORM_DAMAGE * 2
        else:
            storm_dmg = STORM_DAMAGE * 5  # Sudden death — 25 damage/turn

        center = MAP_SIZE // 2
        for agent in self.agents.values():
            if not agent.alive:
                continue
            dist_from_center = max(abs(agent.x - center), abs(agent.y - center))
            if dist_from_center > self.storm_edge // 2:
                agent.health -= storm_dmg
                agent.damage_taken += storm_dmg
                turn_events.append(TurnEvent(self.turn, "storm_damage", agent.agent_id, {"damage": storm_dmg}))
                if agent.health <= 0:
                    agent.health = 0
                    agent.alive = False
                    turn_events.append(TurnEvent(self.turn, "kill", "storm", {"victim": agent.name, "victim_id": agent.agent_id}))

        self.events.extend(turn_events)

        # Win check — 1 or 0 alive
        alive = [a for a in self.agents.values() if a.alive]
        if len(alive) <= 1:
            self.finished = True
            self.finished_at = time.time()
            if alive:
                self.winner = alive[0].agent_id

        # Hard cap — if still not finished at MAX_TURNS, highest HP wins
        if not self.finished and self.turn >= MAX_TURNS:
            self.finished = True
            self.finished_at = time.time()
            if not self.winner:
                best = max(self.agents.values(), key=lambda a: (a.alive, a.health, a.kills, a.damage_dealt))
                self.winner = best.agent_id

        self.turn += 1

    def get_spectator_state(self) -> Dict:
        """Full state for spectators (no fog of war)."""
        return {
            "match_id": self.match_id,
            "mode": self.mode,
            "turn": self.turn,
            "storm_edge": self.storm_edge,
            "agents": [
                {
                    "id": a.agent_id, "name": a.name,
                    "x": a.x, "y": a.y,
                    "health": a.health, "alive": a.alive,
                    "weapon": a.active_weapon.type.value,
                    "ammo": a.active_weapon.ammo,
                    "kills": a.kills, "armor": a.has_armor,
                }
                for a in self.agents.values()
            ],
            "items": [
                {"x": i.x, "y": i.y, "type": i.item_type.value}
                for i in self.items if not i.picked_up
            ],
            "events": [
                {"type": e.event_type, "agent": e.agent_id, "data": e.data}
                for e in self.events if e.turn == self.turn - 1
            ],
            "agents_alive": sum(1 for a in self.agents.values() if a.alive),
            "finished": self.finished,
            "winner": self.winner,
        }

    def get_map_data(self) -> List[List[str]]:
        """Full map for spectator rendering."""
        return [[self.tiles[y][x].value for x in range(MAP_SIZE)] for y in range(MAP_SIZE)]

    # ── Redis serialization ─────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "mode": self.mode,
            "seed": self.seed,
            "rng_state": _arena_encode_rng(self.rng),
            "turn": self.turn,
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "tiles": [[t.value for t in row] for row in self.tiles],
            "items": [_map_item_to_dict(i) for i in self.items],
            "agents": {aid: _agent_state_to_dict(a) for aid, a in self.agents.items()},
            "events": [_turn_event_to_dict(e) for e in self.events[-200:]],  # keep recent 200
            "storm_edge": self.storm_edge,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameState":
        obj = cls.__new__(cls)
        obj.match_id = data["match_id"]
        obj.mode = data["mode"]
        obj.seed = data["seed"]
        obj.rng = _arena_decode_rng(data.get("rng_state"), data["seed"])
        obj.turn = data["turn"]
        obj.started = data["started"]
        obj.finished = data["finished"]
        obj.winner = data.get("winner")
        obj.started_at = data.get("started_at")
        obj.finished_at = data.get("finished_at")
        obj.tiles = [[TileType(v) for v in row] for row in data["tiles"]]
        obj.items = [_map_item_from_dict(i) for i in data["items"]]
        obj.agents = {aid: _agent_state_from_dict(a) for aid, a in data["agents"].items()}
        obj.events = [_turn_event_from_dict(e) for e in data.get("events", [])]
        obj.storm_edge = data["storm_edge"]
        return obj
