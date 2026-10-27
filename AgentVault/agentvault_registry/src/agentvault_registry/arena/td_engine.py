"""
Tower Defense Game Engine — Endless waves, escalating difficulty.

Grid-based tower defense on a 50x30 map.
Enemies spawn on the left, path to the right.
Agent places/upgrades towers via MCP tool calls.
Each wave gets harder. Highscore = waves survived.
"""
import random
import math
import uuid
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from collections import deque


MAP_W = 50
MAP_H = 30
STARTING_GOLD = 200
STARTING_LIVES = 20
GOLD_PER_KILL = 10
GOLD_PER_WAVE = 50
WAVE_DELAY_TURNS = 1  # Turns between waves for building


class TileType(str, Enum):
    GRASS = "grass"
    PATH = "path"
    SPAWN = "spawn"
    EXIT = "exit"
    TOWER = "tower"
    WATER = "water"
    ROCK = "rock"


class TowerType(str, Enum):
    BASIC = "basic"       # Cheap, balanced
    SNIPER = "sniper"     # Long range, slow, high damage
    SPLASH = "splash"     # Area damage, short range
    SLOW = "slow"         # Slows enemies, low damage
    LASER = "laser"       # High DPS, short range, piercing


TOWER_STATS = {
    TowerType.BASIC:  {"cost": 50,  "damage": 15, "range": 4, "speed": 1.0, "name": "Cannon",   "upgrades": 3, "upgrade_cost": 30},
    TowerType.SNIPER: {"cost": 100, "damage": 40, "range": 8, "speed": 0.5, "name": "Sniper",   "upgrades": 3, "upgrade_cost": 60},
    TowerType.SPLASH: {"cost": 80,  "damage": 20, "range": 3, "speed": 0.8, "name": "Mortar",   "upgrades": 3, "upgrade_cost": 45},
    TowerType.SLOW:   {"cost": 60,  "damage": 5,  "range": 3, "speed": 1.0, "name": "Freezer",  "upgrades": 2, "upgrade_cost": 40},
    TowerType.LASER:  {"cost": 120, "damage": 35, "range": 3, "speed": 1.5, "name": "Laser",    "upgrades": 3, "upgrade_cost": 70},
}


@dataclass
class Tower:
    id: str
    type: TowerType
    x: int
    y: int
    level: int = 1
    cooldown: float = 0
    total_kills: int = 0
    total_damage: int = 0

    @property
    def stats(self):
        base = TOWER_STATS[self.type]
        mult = 1 + (self.level - 1) * 0.4  # 40% boost per level
        return {
            "damage": int(base["damage"] * mult),
            "range": base["range"] + (self.level - 1),
            "speed": base["speed"],
            "name": f"{base['name']} Lv{self.level}",
        }


@dataclass
class Enemy:
    id: str
    x: float
    y: float
    health: int
    max_health: int
    speed: float = 1.0
    reward: int = 10
    path_index: int = 0
    slowed: int = 0  # Turns of slow remaining
    enemy_type: str = "grunt"
    alive: bool = True

    @property
    def effective_speed(self):
        return self.speed * 0.5 if self.slowed > 0 else self.speed


@dataclass
class WaveConfig:
    wave_num: int
    enemies: List[Dict]  # List of {type, count, health, speed, reward}


class TDGameState:
    """Complete state of a tower defense match."""

    def __init__(self, match_id: str, seed: Optional[int] = None):
        self.match_id = match_id
        self.seed = seed or random.randint(0, 999999)
        self.rng = random.Random(self.seed)

        # Map
        self.tiles: List[List[TileType]] = []
        self.path: List[Tuple[int, int]] = []  # Enemy walking path

        # State
        self.turn = 0
        self.wave = 0
        self.lives = STARTING_LIVES
        self.gold = STARTING_GOLD
        self.score = 0
        self.towers: Dict[str, Tower] = {}
        self.enemies: List[Enemy] = []
        self.wave_active = False
        self.wave_spawns_remaining: List[Dict] = []
        self.turns_until_next_wave = 3
        self.game_over = False
        self.started = False
        self.started_at: Optional[float] = None
        self.total_kills = 0
        self.total_damage_dealt = 0

        # Agent
        self.agent_id: Optional[str] = None
        self.agent_name: str = "Commander"

        # Generate map
        self._generate_map()

    def _generate_map(self):
        """Generate map with a winding path from left to right."""
        rng = self.rng
        self.tiles = [[TileType.GRASS for _ in range(MAP_W)] for _ in range(MAP_H)]

        # Create winding path
        path_points = []
        y = MAP_H // 2
        x = 0

        # Spawn zone
        for sy in range(max(0, y - 1), min(MAP_H, y + 2)):
            self.tiles[sy][0] = TileType.SPAWN
            self.tiles[sy][1] = TileType.SPAWN

        path_points.append((0, y))
        path_points.append((1, y))

        x = 2
        while x < MAP_W - 2:
            # Move right 3-6 tiles
            segment = rng.randint(3, 6)
            for dx in range(segment):
                if x + dx < MAP_W - 2:
                    path_points.append((x + dx, y))
            x += segment

            if x >= MAP_W - 2:
                break

            # Turn up or down 2-5 tiles
            direction = rng.choice([-1, 1])
            turn_len = rng.randint(2, 5)
            for dy in range(turn_len):
                ny = y + direction
                if 2 <= ny < MAP_H - 2:
                    y = ny
                    path_points.append((x, y))

        # Final stretch to exit
        for fx in range(x, MAP_W):
            path_points.append((fx, y))

        # Exit zone
        for sy in range(max(0, y - 1), min(MAP_H, y + 2)):
            self.tiles[sy][MAP_W - 1] = TileType.EXIT
            self.tiles[sy][MAP_W - 2] = TileType.EXIT

        # Paint path
        self.path = path_points
        for px, py in path_points:
            if 0 <= px < MAP_W and 0 <= py < MAP_H:
                self.tiles[py][px] = TileType.PATH

        # Widen path (make it 3 tiles wide in some spots for visual variety)
        for px, py in path_points[::3]:
            for dy in [-1, 1]:
                ny = py + dy
                if 0 <= ny < MAP_H and self.tiles[ny][px] == TileType.GRASS:
                    if rng.random() < 0.3:
                        self.tiles[ny][px] = TileType.PATH

        # Add decorative water/rocks
        for _ in range(rng.randint(5, 10)):
            rx, ry = rng.randint(2, MAP_W - 3), rng.randint(1, MAP_H - 2)
            if self.tiles[ry][rx] == TileType.GRASS:
                self.tiles[ry][rx] = TileType.WATER if rng.random() < 0.5 else TileType.ROCK

    def set_agent(self, agent_id: str, name: str):
        self.agent_id = agent_id
        self.agent_name = name
        self.started = True
        self.started_at = time.time()

    def _generate_wave(self, wave_num: int) -> List[Dict]:
        """Generate enemies for a wave. Escalating difficulty."""
        base_hp = 30 + wave_num * 15
        count = 3 + wave_num * 2
        speed = 1.0 + wave_num * 0.05

        enemies = []

        # Grunts (always)
        enemies.extend([{
            "type": "grunt", "health": base_hp, "speed": speed,
            "reward": GOLD_PER_KILL
        }] * count)

        # Fast runners (wave 3+)
        if wave_num >= 3:
            fast_count = max(1, wave_num // 3)
            enemies.extend([{
                "type": "runner", "health": int(base_hp * 0.6), "speed": speed * 1.8,
                "reward": GOLD_PER_KILL + 5
            }] * fast_count)

        # Tanks (wave 5+)
        if wave_num >= 5:
            tank_count = max(1, wave_num // 5)
            enemies.extend([{
                "type": "tank", "health": base_hp * 3, "speed": speed * 0.5,
                "reward": GOLD_PER_KILL * 3
            }] * tank_count)

        # Boss (every 10 waves)
        if wave_num > 0 and wave_num % 10 == 0:
            enemies.append({
                "type": "boss", "health": base_hp * 10, "speed": speed * 0.3,
                "reward": GOLD_PER_KILL * 10
            })

        self.rng.shuffle(enemies)
        return enemies

    def start_next_wave(self):
        """Begin the next wave."""
        self.wave += 1
        self.wave_active = True
        self.wave_spawns_remaining = self._generate_wave(self.wave)
        self.gold += GOLD_PER_WAVE
        self.turns_until_next_wave = 0

    def place_tower(self, x: int, y: int, tower_type: str) -> Dict:
        """Place a tower at position."""
        if not (0 <= x < MAP_W and 0 <= y < MAP_H):
            return {"success": False, "message": "Out of bounds"}

        if self.tiles[y][x] != TileType.GRASS:
            return {"success": False, "message": f"Can only place on grass (this tile is {self.tiles[y][x].value})"}

        tt = TowerType(tower_type) if tower_type in [t.value for t in TowerType] else None
        if not tt:
            return {"success": False, "message": f"Unknown tower type: {tower_type}. Available: {[t.value for t in TowerType]}"}

        cost = TOWER_STATS[tt]["cost"]
        if self.gold < cost:
            return {"success": False, "message": f"Not enough gold ({self.gold}/{cost})"}

        tower_id = f"T-{len(self.towers) + 1}"
        tower = Tower(id=tower_id, type=tt, x=x, y=y)
        self.towers[tower_id] = tower
        self.tiles[y][x] = TileType.TOWER
        self.gold -= cost

        return {
            "success": True,
            "tower_id": tower_id,
            "type": tt.value,
            "name": tower.stats["name"],
            "cost": cost,
            "gold_remaining": self.gold,
            "position": {"x": x, "y": y},
            "stats": tower.stats,
        }

    def upgrade_tower(self, tower_id: str) -> Dict:
        """Upgrade a tower."""
        tower = self.towers.get(tower_id)
        if not tower:
            return {"success": False, "message": f"Tower {tower_id} not found"}

        max_lvl = TOWER_STATS[tower.type]["upgrades"]
        if tower.level >= max_lvl:
            return {"success": False, "message": f"Already max level ({max_lvl})"}

        cost = TOWER_STATS[tower.type]["upgrade_cost"] * tower.level
        if self.gold < cost:
            return {"success": False, "message": f"Not enough gold ({self.gold}/{cost})"}

        tower.level += 1
        self.gold -= cost

        return {
            "success": True,
            "tower_id": tower_id,
            "new_level": tower.level,
            "cost": cost,
            "gold_remaining": self.gold,
            "new_stats": tower.stats,
        }

    def sell_tower(self, tower_id: str) -> Dict:
        """Sell a tower for 50% of what it cost in all."""
        tower = self.towers.get(tower_id)
        if not tower:
            return {"success": False, "message": f"Tower {tower_id} not found"}

        base_cost = TOWER_STATS[tower.type]["cost"]
        upgrade_cost = sum(TOWER_STATS[tower.type]["upgrade_cost"] * i for i in range(1, tower.level))
        refund = int((base_cost + upgrade_cost) * 0.5)

        self.tiles[tower.y][tower.x] = TileType.GRASS
        del self.towers[tower_id]
        self.gold += refund

        return {"success": True, "refund": refund, "gold_remaining": self.gold}

    def process_turn(self) -> List[Dict]:
        """Process one turn: spawn enemies, move enemies, towers shoot, check exits."""
        events = []

        if self.game_over:
            return events

        self.turn += 1

        # Spawn phase
        if self.wave_active and self.wave_spawns_remaining:
            # Spawn up to 8 enemies per turn — tuned for AI-playing speed
            spawns = min(8, len(self.wave_spawns_remaining))
            for _ in range(spawns):
                if not self.wave_spawns_remaining:
                    break
                edata = self.wave_spawns_remaining.pop(0)
                spawn_x, spawn_y = self.path[0]
                enemy = Enemy(
                    id=f"E-{self.turn}-{len(self.enemies)}",
                    x=float(spawn_x), y=float(spawn_y),
                    health=edata["health"], max_health=edata["health"],
                    speed=edata["speed"], reward=edata["reward"],
                    enemy_type=edata["type"],
                )
                self.enemies.append(enemy)
                events.append({"type": "spawn", "enemy": enemy.enemy_type, "id": enemy.id})

        # Move enemies along path — tuned for AI-playing speed
        for enemy in self.enemies:
            if not enemy.alive:
                continue
            move_speed = enemy.effective_speed
            steps = max(3, int(move_speed * 3.5))
            for _ in range(steps):
                if enemy.path_index < len(self.path) - 1:
                    enemy.path_index += 1
                    enemy.x, enemy.y = float(self.path[enemy.path_index][0]), float(self.path[enemy.path_index][1])
                else:
                    # Reached exit — lose a life (clamp to 0 so events never
                    # ship negative; wave-wipes that would go below zero just
                    # stop at 0 and trigger game_over in the same tick).
                    enemy.alive = False
                    self.lives = max(0, self.lives - 1)
                    events.append({"type": "leak", "enemy": enemy.enemy_type, "lives": self.lives})
                    if self.lives == 0:
                        self.game_over = True
                        events.append({"type": "game_over", "wave": self.wave, "score": self.score, "kills": self.total_kills})
                        return events  # stop processing further enemies this tick
                    break

            if enemy.slowed > 0:
                enemy.slowed -= 1

        # Tower shooting phase
        for tower in self.towers.values():
            tower.cooldown = max(0, tower.cooldown - 1)
            if tower.cooldown > 0:
                continue

            stats = tower.stats
            targets = []
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                dist = math.sqrt((enemy.x - tower.x) ** 2 + (enemy.y - tower.y) ** 2)
                if dist <= stats["range"]:
                    targets.append((dist, enemy))

            if not targets:
                continue

            targets.sort(key=lambda t: t[0])  # Nearest first

            if tower.type == TowerType.SPLASH:
                # Area damage — hit all in range
                for _, enemy in targets[:5]:
                    dmg = stats["damage"]
                    enemy.health -= dmg
                    tower.total_damage += dmg
                    self.total_damage_dealt += dmg
            elif tower.type == TowerType.SLOW:
                # Slow + small damage
                for _, enemy in targets[:3]:
                    enemy.health -= stats["damage"]
                    enemy.slowed = 3  # 3 turns of slow
                    tower.total_damage += stats["damage"]
                    self.total_damage_dealt += stats["damage"]
            elif tower.type == TowerType.LASER:
                # Pierce through first 2 enemies
                for _, enemy in targets[:2]:
                    dmg = stats["damage"]
                    enemy.health -= dmg
                    tower.total_damage += dmg
                    self.total_damage_dealt += dmg
            else:
                # Single target (basic, sniper)
                _, target = targets[0]
                dmg = stats["damage"]
                target.health -= dmg
                tower.total_damage += dmg
                self.total_damage_dealt += dmg
                events.append({"type": "shot", "tower": tower.id, "target": target.id, "damage": dmg})

            tower.cooldown = 1.0 / stats["speed"]

        # Death check
        for enemy in self.enemies:
            if enemy.alive and enemy.health <= 0:
                enemy.alive = False
                self.gold += enemy.reward
                self.score += enemy.reward
                self.total_kills += 1
                events.append({"type": "kill", "enemy": enemy.enemy_type, "reward": enemy.reward, "gold": self.gold})
                # Credit kill to nearest tower
                nearest_tower = None
                min_dist = 999
                for t in self.towers.values():
                    d = math.sqrt((enemy.x - t.x) ** 2 + (enemy.y - t.y) ** 2)
                    if d < min_dist:
                        min_dist = d
                        nearest_tower = t
                if nearest_tower:
                    nearest_tower.total_kills += 1

        # Clean up dead enemies
        self.enemies = [e for e in self.enemies if e.alive]

        # Wave complete check
        if self.wave_active and not self.wave_spawns_remaining and not self.enemies:
            self.wave_active = False
            self.turns_until_next_wave = WAVE_DELAY_TURNS
            events.append({"type": "wave_complete", "wave": self.wave, "gold": self.gold, "score": self.score})

        # Auto-start next wave after delay
        if not self.wave_active and not self.game_over:
            self.turns_until_next_wave -= 1
            if self.turns_until_next_wave <= 0:
                self.start_next_wave()
                events.append({"type": "wave_start", "wave": self.wave, "enemies": len(self.wave_spawns_remaining)})

        # Game over check
        if self.lives <= 0:
            self.lives = 0
            self.game_over = True
            events.append({"type": "game_over", "wave": self.wave, "score": self.score, "kills": self.total_kills})

        return events

    def get_status(self) -> Dict:
        return {
            "match_id": self.match_id,
            "turn": self.turn,
            "wave": self.wave,
            "lives": self.lives,
            "gold": self.gold,
            "score": self.score,
            "towers": len(self.towers),
            "enemies_alive": len([e for e in self.enemies if e.alive]),
            "wave_active": self.wave_active,
            "turns_until_next_wave": self.turns_until_next_wave if not self.wave_active else 0,
            "game_over": self.game_over,
            "total_kills": self.total_kills,
            "path_coverage": self.get_path_coverage(),
            "next_wave_preview": None if self.game_over else self.preview_next_wave(),
        }

    def get_spectator_state(self) -> Dict:
        return {
            "match_id": self.match_id,
            "agent_name": self.agent_name,
            "turn": self.turn,
            "wave": self.wave,
            "lives": self.lives,
            "gold": self.gold,
            "score": self.score,
            "game_over": self.game_over,
            "towers": [
                {"id": t.id, "type": t.type.value, "x": t.x, "y": t.y, "level": t.level,
                 "name": t.stats["name"], "kills": t.total_kills, "damage": t.total_damage,
                 # next_upgrade_cost = base_upgrade_cost * current_level
                 # (see TOWER_STATS). null when tower is already max level.
                 "next_upgrade_cost": (TOWER_STATS[t.type]["upgrade_cost"] * t.level
                                        if t.level < TOWER_STATS[t.type]["upgrades"] else None),
                 "max_level": TOWER_STATS[t.type]["upgrades"]}
                for t in self.towers.values()
            ],
            "enemies": [
                {"id": e.id, "type": e.enemy_type, "x": e.x, "y": e.y,
                 "health": e.health, "max_health": e.max_health, "slowed": e.slowed > 0}
                for e in self.enemies if e.alive
            ],
            "wave_active": self.wave_active,
            "total_kills": self.total_kills,
        }

    def get_map_data(self) -> List[List[str]]:
        return [[self.tiles[y][x].value for x in range(MAP_W)] for y in range(MAP_H)]

    def get_buildable_tiles(self) -> List[Dict]:
        """Return all tiles where towers can be placed."""
        tiles = []
        for y in range(MAP_H):
            for x in range(MAP_W):
                if self.tiles[y][x] == TileType.GRASS:
                    # Check adjacency to path (only build near path)
                    near_path = False
                    for dx in range(-2, 3):
                        for dy in range(-2, 3):
                            nx, ny = x + dx, y + dy
                            if 0 <= nx < MAP_W and 0 <= ny < MAP_H:
                                if self.tiles[ny][nx] == TileType.PATH:
                                    near_path = True
                                    break
                        if near_path:
                            break
                    if near_path:
                        tiles.append({"x": x, "y": y})
        return tiles

    # ── ASCII rendering + coverage + wave preview ───────────────────────

    # Legend for render_ascii_map (tile glyph; towers/enemies overlay).
    _ASCII_TILE = {
        TileType.GRASS: ".",
        TileType.PATH:  "=",
        TileType.SPAWN: "S",
        TileType.EXIT:  "E",
        TileType.TOWER: "T",
        TileType.WATER: "~",
        TileType.ROCK:  "^",
    }
    _ASCII_LEGEND = (
        ". grass  = path  S spawn  E exit  ~ water  ^ rock  "
        "T tower  * enemy"
    )

    def render_ascii_map(self, show_enemies: bool = True) -> Dict[str, Any]:
        """Return the board as a compact string grid for LLM callers.

        Map layer comes from self.tiles; towers are already painted onto the
        tiles (TileType.TOWER) on placement; enemies are overlaid dynamically
        at their current rounded position.
        """
        # Start from the static tile grid.
        rows = [[self._ASCII_TILE.get(self.tiles[y][x], "?") for x in range(MAP_W)]
                for y in range(MAP_H)]
        # Overlay live enemies.
        if show_enemies:
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                ex, ey = int(round(enemy.x)), int(round(enemy.y))
                if 0 <= ex < MAP_W and 0 <= ey < MAP_H:
                    rows[ey][ex] = "*"
        grid = "\n".join("".join(r) for r in rows)
        return {
            "grid": grid,
            "width": MAP_W,
            "height": MAP_H,
            "legend": self._ASCII_LEGEND,
        }

    def get_path_coverage(self) -> Dict[str, Any]:
        """What fraction of the path is in range of at least one tower?
        Returns coverage_pct and the first 10 uncovered path tiles, in order.
        """
        total = len(self.path)
        if total == 0:
            return {"covered_tiles": 0, "total_path_tiles": 0,
                    "coverage_pct": 0.0, "uncovered_path_tiles": []}
        uncovered: List[List[int]] = []
        covered = 0
        for px, py in self.path:
            in_range = False
            for tower in self.towers.values():
                stats = tower.stats
                dx, dy = px - tower.x, py - tower.y
                if (dx * dx + dy * dy) ** 0.5 <= stats["range"]:
                    in_range = True
                    break
            if in_range:
                covered += 1
            else:
                if len(uncovered) < 10:
                    uncovered.append([px, py])
        return {
            "covered_tiles": covered,
            "total_path_tiles": total,
            "coverage_pct": round(100.0 * covered / total, 1),
            "uncovered_path_tiles": uncovered,
        }

    def preview_next_wave(self) -> Optional[Dict[str, Any]]:
        """Peek at the upcoming wave's composition without mutating game RNG."""
        # Clone RNG state so the preview is identical to what _generate_wave
        # will actually roll on start_next_wave(). The real shuffle order is
        # still the same because we restore the state before returning.
        saved = self.rng.getstate()
        try:
            enemies = self._generate_wave(self.wave + 1)
        finally:
            self.rng.setstate(saved)
        by_type: Dict[str, int] = {}
        total_hp = 0
        leader_speed = 0.0
        for e in enemies:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
            total_hp += e["health"]
            leader_speed = max(leader_speed, e["speed"])
        return {
            "wave_num": self.wave + 1,
            "enemies_by_type": by_type,
            "total_count": len(enemies),
            "total_hp": total_hp,
            "leader_speed": round(leader_speed, 2),
        }

    # ── Redis serialization ─────────────────────────────────────────────
    # Round-trip the full game state through JSON so any of the 16 uvicorn
    # workers can service a tool call. Reconstruction skips __init__ (which
    # would re-generate the map + RNG) and rehydrates fields directly.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "seed": self.seed,
            "rng_state": _encode_rng_state(self.rng),
            "tiles": [[t.value for t in row] for row in self.tiles],
            "path": [list(p) for p in self.path],
            "turn": self.turn,
            "wave": self.wave,
            "lives": self.lives,
            "gold": self.gold,
            "score": self.score,
            "towers": {tid: _tower_to_dict(t) for tid, t in self.towers.items()},
            "enemies": [_enemy_to_dict(e) for e in self.enemies],
            "wave_active": self.wave_active,
            "wave_spawns_remaining": list(self.wave_spawns_remaining),
            "turns_until_next_wave": self.turns_until_next_wave,
            "game_over": self.game_over,
            "started": self.started,
            "started_at": self.started_at,
            "total_kills": self.total_kills,
            "total_damage_dealt": self.total_damage_dealt,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "agent_did": getattr(self, "_agent_did", None),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TDGameState":
        obj = cls.__new__(cls)
        obj.match_id = data["match_id"]
        obj.seed = data["seed"]
        obj.rng = _decode_rng_state(data.get("rng_state"), data["seed"])
        obj.tiles = [[TileType(v) for v in row] for row in data["tiles"]]
        obj.path = [tuple(p) for p in data["path"]]
        obj.turn = data["turn"]
        obj.wave = data["wave"]
        obj.lives = data["lives"]
        obj.gold = data["gold"]
        obj.score = data["score"]
        obj.towers = {tid: _tower_from_dict(td) for tid, td in data["towers"].items()}
        obj.enemies = [_enemy_from_dict(ed) for ed in data["enemies"]]
        obj.wave_active = data["wave_active"]
        obj.wave_spawns_remaining = list(data["wave_spawns_remaining"])
        obj.turns_until_next_wave = data["turns_until_next_wave"]
        obj.game_over = data["game_over"]
        obj.started = data["started"]
        obj.started_at = data["started_at"]
        obj.total_kills = data["total_kills"]
        obj.total_damage_dealt = data["total_damage_dealt"]
        obj.agent_id = data.get("agent_id")
        obj.agent_name = data.get("agent_name", "Commander")
        did = data.get("agent_did")
        if did:
            obj._agent_did = did
        return obj


# ── Codec helpers (module-level so from_dict/to_dict stay small) ──────────

def _tower_to_dict(t: Tower) -> Dict[str, Any]:
    return {
        "id": t.id, "type": t.type.value, "x": t.x, "y": t.y,
        "level": t.level, "cooldown": t.cooldown,
        "total_kills": t.total_kills, "total_damage": t.total_damage,
    }


def _tower_from_dict(d: Dict[str, Any]) -> Tower:
    return Tower(
        id=d["id"], type=TowerType(d["type"]), x=d["x"], y=d["y"],
        level=d["level"], cooldown=d["cooldown"],
        total_kills=d["total_kills"], total_damage=d["total_damage"],
    )


def _enemy_to_dict(e: Enemy) -> Dict[str, Any]:
    return {
        "id": e.id, "x": e.x, "y": e.y, "health": e.health, "max_health": e.max_health,
        "speed": e.speed, "reward": e.reward, "path_index": e.path_index,
        "slowed": e.slowed, "enemy_type": e.enemy_type, "alive": e.alive,
    }


def _enemy_from_dict(d: Dict[str, Any]) -> Enemy:
    return Enemy(
        id=d["id"], x=d["x"], y=d["y"], health=d["health"], max_health=d["max_health"],
        speed=d["speed"], reward=d["reward"], path_index=d["path_index"],
        slowed=d["slowed"], enemy_type=d["enemy_type"], alive=d["alive"],
    )


def _encode_rng_state(rng: random.Random) -> List[Any]:
    """random.Random.getstate() returns (version, tuple_of_ints, gauss_cached).
    JSON can't hold tuples, so flatten to a list. Index 2 may be None or a float."""
    ver, state, gauss = rng.getstate()
    return [ver, list(state), gauss]


def _decode_rng_state(raw: Optional[List[Any]], seed: int) -> random.Random:
    """Restore an RNG from the encoded state, or re-seed if absent/broken."""
    rng = random.Random(seed)
    if not raw:
        return rng
    try:
        ver, state, gauss = raw
        rng.setstate((ver, tuple(state), gauss))
    except Exception:
        pass
    return rng
