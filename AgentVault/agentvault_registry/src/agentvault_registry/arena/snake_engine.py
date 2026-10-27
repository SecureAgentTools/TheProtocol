"""
Snake Arena — Multiplayer snake game on a 30x30 grid.

Classic snake rules:
- Snakes grow by eating food
- Crash into walls, yourself, or another snake = death
- Last snake alive wins
- Food spawns periodically

Turn-based: each snake chooses a direction per turn.
"""
import random
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import deque


MAP_SIZE = 30
STARTING_LENGTH = 3
FOOD_COUNT = 5
FOOD_RESPAWN_TURNS = 3
MAX_TURNS = 300


@dataclass
class Food:
    x: int
    y: int
    value: int = 1  # Growth amount


@dataclass
class SnakeState:
    agent_id: str
    name: str
    body: deque  # deque of (x, y) — head is [0]
    direction: str = "east"
    alive: bool = True
    score: int = 0
    grow_pending: int = 0
    color_index: int = 0
    death_cause: str = ""

    @property
    def head(self) -> Tuple[int, int]:
        return self.body[0] if self.body else (0, 0)

    @property
    def length(self) -> int:
        return len(self.body)


DIRECTIONS = {
    "north": (0, -1), "south": (0, 1),
    "east": (1, 0), "west": (-1, 0),
}

OPPOSITES = {"north": "south", "south": "north", "east": "west", "west": "east"}


class SnakeGameState:
    """Complete state of a snake arena match."""

    def __init__(self, match_id: str, seed: Optional[int] = None):
        self.match_id = match_id
        self.seed = seed or random.randint(0, 999999)
        self.rng = random.Random(self.seed)
        self.turn = 0
        self.started = False
        self.finished = False
        self.winner: Optional[str] = None
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

        self.snakes: Dict[str, SnakeState] = {}
        self.food: List[Food] = []
        self.walls: set = set()  # (x, y) wall positions

        self._generate_walls()

    def _generate_walls(self):
        """Add border walls and some internal obstacles."""
        # Border walls
        for x in range(MAP_SIZE):
            self.walls.add((x, 0))
            self.walls.add((x, MAP_SIZE - 1))
        for y in range(MAP_SIZE):
            self.walls.add((0, y))
            self.walls.add((MAP_SIZE - 1, y))

        # A few internal wall clusters
        for _ in range(self.rng.randint(3, 6)):
            cx = self.rng.randint(5, MAP_SIZE - 6)
            cy = self.rng.randint(5, MAP_SIZE - 6)
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    if self.rng.random() < 0.5:
                        self.walls.add((cx + dx, cy + dy))

    def _find_safe_spawn(self) -> List[Tuple[int, int]]:
        """Find a safe spawn position for a snake of STARTING_LENGTH."""
        for _ in range(100):
            x = self.rng.randint(4, MAP_SIZE - 5)
            y = self.rng.randint(4, MAP_SIZE - 5)
            body = [(x - i, y) for i in range(STARTING_LENGTH)]
            # Check all body tiles are free
            occupied = set()
            for s in self.snakes.values():
                occupied.update(s.body)
            all_free = all(
                (bx, by) not in self.walls and (bx, by) not in occupied
                for bx, by in body
            )
            if all_free:
                return body
        return [(MAP_SIZE // 2, MAP_SIZE // 2)]

    def add_snake(self, agent_id: str, name: str) -> SnakeState:
        body = deque(self._find_safe_spawn())
        color_idx = len(self.snakes)
        snake = SnakeState(
            agent_id=agent_id, name=name,
            body=body, direction="east",
            color_index=color_idx,
        )
        self.snakes[agent_id] = snake
        return snake

    def start_match(self):
        self.started = True
        self.started_at = time.time()
        self.turn = 1
        self._spawn_food()

    def _spawn_food(self):
        """Spawn food until we have FOOD_COUNT items."""
        occupied = set()
        for s in self.snakes.values():
            occupied.update(s.body)
        occupied.update(self.walls)
        occupied.update((f.x, f.y) for f in self.food)

        while len(self.food) < FOOD_COUNT:
            for _ in range(100):
                x = self.rng.randint(1, MAP_SIZE - 2)
                y = self.rng.randint(1, MAP_SIZE - 2)
                if (x, y) not in occupied:
                    # Occasional super food
                    value = 3 if self.rng.random() < 0.1 else 1
                    self.food.append(Food(x=x, y=y, value=value))
                    occupied.add((x, y))
                    break

    def set_direction(self, agent_id: str, direction: str) -> Dict:
        """Set snake's direction for next turn."""
        snake = self.snakes.get(agent_id)
        if not snake or not snake.alive:
            return {"success": False, "message": "Snake is dead"}

        if direction not in DIRECTIONS:
            return {"success": False, "message": f"Invalid direction: {direction}. Use: north/south/east/west"}

        # Can't reverse
        if direction == OPPOSITES.get(snake.direction):
            return {"success": False, "message": f"Can't reverse! Currently heading {snake.direction}"}

        snake.direction = direction
        return {"success": True, "direction": direction, "head": {"x": snake.head[0], "y": snake.head[1]}}

    def get_view(self, agent_id: str) -> Dict:
        """What the snake can see."""
        snake = self.snakes.get(agent_id)
        if not snake:
            return {"error": "Not in game"}

        hx, hy = snake.head
        # See everything (no fog of war in snake)
        other_snakes = []
        for s in self.snakes.values():
            if s.agent_id == agent_id:
                continue
            other_snakes.append({
                "name": s.name, "alive": s.alive,
                "head": {"x": s.head[0], "y": s.head[1]} if s.alive else None,
                "length": s.length, "score": s.score,
                "body": [{"x": bx, "y": by} for bx, by in s.body] if s.alive else [],
            })

        return {
            "position": {"x": hx, "y": hy},
            "direction": snake.direction,
            "length": snake.length,
            "score": snake.score,
            "alive": snake.alive,
            "body": [{"x": bx, "y": by} for bx, by in snake.body],
            "food": [{"x": f.x, "y": f.y, "value": f.value} for f in self.food],
            # Only INTERNAL walls; the 1-tile border at x=0, x=MAP_SIZE-1,
            # y=0, y=MAP_SIZE-1 is implicit (derivable from map_size).
            "walls": [[wx, wy] for wx, wy in sorted(self.walls)
                      if 0 < wx < MAP_SIZE - 1 and 0 < wy < MAP_SIZE - 1],
            "border_implicit": True,
            "other_snakes": other_snakes,
            "turn": self.turn,
            "snakes_alive": sum(1 for s in self.snakes.values() if s.alive),
            "map_size": MAP_SIZE,
            # Compact ASCII rendering of the full 30x30 board. Easier for
            # LLM callers than the separate walls/food/snakes arrays.
            "ascii_map": self.render_ascii_view(agent_id),
        }

    def process_turn(self) -> List[Dict]:
        """Move all snakes, check collisions, spawn food."""
        if self.finished:
            return []

        events = []
        self.turn += 1

        # Move all snakes
        new_heads = {}
        for snake in self.snakes.values():
            if not snake.alive:
                continue
            dx, dy = DIRECTIONS[snake.direction]
            nx, ny = snake.head[0] + dx, snake.head[1] + dy
            new_heads[snake.agent_id] = (nx, ny)

        # Check collisions
        all_bodies = set()
        for s in self.snakes.values():
            if s.alive:
                all_bodies.update(list(s.body)[1:])  # Exclude head (it's moving)

        for agent_id, (nx, ny) in new_heads.items():
            snake = self.snakes[agent_id]

            # Wall collision
            if (nx, ny) in self.walls:
                snake.alive = False
                snake.death_cause = "wall"
                events.append({"type": "death", "snake": snake.name, "cause": "wall"})
                continue

            # Self collision (check against own body excluding tail if not growing)
            own_body = set(list(snake.body)[:-1] if snake.grow_pending == 0 else list(snake.body))
            if (nx, ny) in own_body:
                snake.alive = False
                snake.death_cause = "self"
                events.append({"type": "death", "snake": snake.name, "cause": "self"})
                continue

            # Other snake collision
            hit_other = False
            for other in self.snakes.values():
                if other.agent_id == agent_id or not other.alive:
                    continue
                if (nx, ny) in set(other.body):
                    snake.alive = False
                    snake.death_cause = f"crashed into {other.name}"
                    events.append({"type": "death", "snake": snake.name, "cause": f"crashed into {other.name}"})
                    hit_other = True
                    break
            if hit_other:
                continue

            # Head-to-head collision
            for other_id, (ox, oy) in new_heads.items():
                if other_id == agent_id:
                    continue
                if (nx, ny) == (ox, oy):
                    snake.alive = False
                    self.snakes[other_id].alive = False
                    snake.death_cause = f"head-on vs {self.snakes[other_id].name}"
                    self.snakes[other_id].death_cause = f"head-on vs {snake.name}"
                    events.append({"type": "death", "snake": snake.name, "cause": "head-on collision"})
                    events.append({"type": "death", "snake": self.snakes[other_id].name, "cause": "head-on collision"})
                    break

            if not snake.alive:
                continue

            # Move
            snake.body.appendleft((nx, ny))
            if snake.grow_pending > 0:
                snake.grow_pending -= 1
            else:
                snake.body.pop()

            # Food check
            eaten = []
            for food in self.food:
                if food.x == nx and food.y == ny:
                    snake.score += food.value * 10
                    snake.grow_pending += food.value
                    eaten.append(food)
                    events.append({"type": "eat", "snake": snake.name, "value": food.value, "score": snake.score})
            for f in eaten:
                self.food.remove(f)

        # Respawn food
        if self.turn % FOOD_RESPAWN_TURNS == 0:
            self._spawn_food()

        # Win check
        alive = [s for s in self.snakes.values() if s.alive]
        if len(alive) <= 1 and len(self.snakes) > 1:
            self.finished = True
            self.finished_at = time.time()
            if alive:
                self.winner = alive[0].agent_id
                events.append({"type": "win", "snake": alive[0].name, "score": alive[0].score})

        if self.turn >= MAX_TURNS:
            self.finished = True
            self.finished_at = time.time()
            best = max(self.snakes.values(), key=lambda s: (s.alive, s.score))
            self.winner = best.agent_id
            events.append({"type": "win", "snake": best.name, "score": best.score, "reason": "time_limit"})

        return events

    def get_spectator_state(self) -> Dict:
        return {
            "match_id": self.match_id,
            "turn": self.turn,
            "finished": self.finished,
            "winner": self.winner,
            "snakes": [
                {
                    "id": s.agent_id, "name": s.name, "alive": s.alive,
                    "score": s.score, "length": s.length,
                    "color_index": s.color_index,
                    "head": {"x": s.head[0], "y": s.head[1]} if s.body else None,
                    "body": [{"x": bx, "y": by} for bx, by in s.body],
                    "direction": s.direction,
                    "death_cause": s.death_cause,
                }
                for s in self.snakes.values()
            ],
            "food": [{"x": f.x, "y": f.y, "value": f.value} for f in self.food],
            "snakes_alive": sum(1 for s in self.snakes.values() if s.alive),
            "map_size": MAP_SIZE,
        }

    def get_walls(self) -> List[Tuple[int, int]]:
        return sorted(self.walls)

    # ── ASCII rendering ────────────────────────────────────────────────
    # A compact single-string view of the whole 30x30 board, easier for
    # LLM callers to parse than the separate walls/food/snakes lists.
    _ASCII_LEGEND = (
        ". empty  # wall  o food(1)  O bonus(3)  "
        "@ your head  s your body  H enemy head  b enemy body  X dead"
    )

    def render_ascii_view(self, agent_id: str) -> Dict[str, Any]:
        rows = [["." for _ in range(MAP_SIZE)] for _ in range(MAP_SIZE)]
        # Walls
        for wx, wy in self.walls:
            if 0 <= wx < MAP_SIZE and 0 <= wy < MAP_SIZE:
                rows[wy][wx] = "#"
        # Food
        for f in self.food:
            if 0 <= f.x < MAP_SIZE and 0 <= f.y < MAP_SIZE:
                rows[f.y][f.x] = "O" if f.value >= 2 else "o"
        # Snakes — other snakes first, then self on top.
        me = self.snakes.get(agent_id)
        for s in self.snakes.values():
            if s is me:
                continue
            is_dead = not s.alive
            body = list(s.body)
            if not body:
                continue
            head = body[0]
            if 0 <= head[0] < MAP_SIZE and 0 <= head[1] < MAP_SIZE:
                rows[head[1]][head[0]] = "X" if is_dead else "H"
            for bx, by in body[1:]:
                if 0 <= bx < MAP_SIZE and 0 <= by < MAP_SIZE:
                    if rows[by][bx] == ".":  # don't overwrite heads
                        rows[by][bx] = "X" if is_dead else "b"
        if me and me.body:
            head = me.body[0]
            if 0 <= head[0] < MAP_SIZE and 0 <= head[1] < MAP_SIZE:
                rows[head[1]][head[0]] = "@" if me.alive else "X"
            for bx, by in list(me.body)[1:]:
                if 0 <= bx < MAP_SIZE and 0 <= by < MAP_SIZE:
                    if rows[by][bx] == ".":
                        rows[by][bx] = "s" if me.alive else "X"
        grid = "\n".join("".join(r) for r in rows)
        return {"grid": grid, "width": MAP_SIZE, "height": MAP_SIZE,
                "legend": self._ASCII_LEGEND}

    # ── Redis serialization ─────────────────────────────────────────────
    # deque → list, set → list of 2-tuples, random.Random → getstate tuple.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_id": self.match_id,
            "seed": self.seed,
            "rng_state": _snake_encode_rng(self.rng),
            "turn": self.turn,
            "started": self.started,
            "finished": self.finished,
            "winner": self.winner,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "snakes": {aid: _snake_state_to_dict(s) for aid, s in self.snakes.items()},
            "food": [{"x": f.x, "y": f.y, "value": f.value} for f in self.food],
            "walls": [list(w) for w in self.walls],
            "agent_dids": getattr(self, "_agent_dids", {}),
            "persisted": getattr(self, "_persisted", False),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnakeGameState":
        obj = cls.__new__(cls)
        obj.match_id = data["match_id"]
        obj.seed = data["seed"]
        obj.rng = _snake_decode_rng(data.get("rng_state"), data["seed"])
        obj.turn = data["turn"]
        obj.started = data["started"]
        obj.finished = data["finished"]
        obj.winner = data.get("winner")
        obj.started_at = data.get("started_at")
        obj.finished_at = data.get("finished_at")
        obj.snakes = {aid: _snake_state_from_dict(sd) for aid, sd in data["snakes"].items()}
        obj.food = [Food(x=f["x"], y=f["y"], value=f["value"]) for f in data["food"]]
        obj.walls = set((w[0], w[1]) for w in data["walls"])
        if data.get("agent_dids"):
            obj._agent_dids = dict(data["agent_dids"])
        if data.get("persisted"):
            obj._persisted = True
        return obj


# ── Snake codec helpers ─────────────────────────────────────────────────

def _snake_state_to_dict(s: "SnakeState") -> Dict[str, Any]:
    return {
        "agent_id": s.agent_id, "name": s.name,
        "body": [list(b) for b in s.body],  # deque of (x,y) → list of [x,y]
        "direction": s.direction, "alive": s.alive,
        "score": s.score, "grow_pending": s.grow_pending,
        "color_index": s.color_index, "death_cause": s.death_cause,
    }


def _snake_state_from_dict(d: Dict[str, Any]) -> "SnakeState":
    body = deque((b[0], b[1]) for b in d["body"])
    return SnakeState(
        agent_id=d["agent_id"], name=d["name"], body=body,
        direction=d["direction"], alive=d["alive"],
        score=d["score"], grow_pending=d["grow_pending"],
        color_index=d["color_index"], death_cause=d.get("death_cause", ""),
    )


def _snake_encode_rng(rng: random.Random) -> List[Any]:
    ver, state, gauss = rng.getstate()
    return [ver, list(state), gauss]


def _snake_decode_rng(raw: Optional[List[Any]], seed: int) -> random.Random:
    rng = random.Random(seed)
    if not raw:
        return rng
    try:
        ver, state, gauss = raw
        rng.setstate((ver, tuple(state), gauss))
    except Exception:
        pass
    return rng
