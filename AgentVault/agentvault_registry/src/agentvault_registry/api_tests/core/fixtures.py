"""Fixture engine (AAA+ refactor 2026-05-21).

Pytest-style fixtures with scopes and DAG dependency resolution.
Replaces the 32 `_setup_*` lazy dispatchers + 18 `_ensure_*` helpers + the
DYNAMIC_VALUES dict (which had 19 race-prone shared keys).

Each fixture is a coroutine that:
    - declares its dependencies via type hints
    - returns a value cached for the scope's lifetime

Scopes:
    "session"  — one instance per test run; cached in BootstrapContext
    "category" — one instance per category
    "endpoint" — fresh per endpoint
    "flow"     — fresh per flow run
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Registry of fixtures ─────────────────────────────────────────────────
_FIXTURES: Dict[str, "FixtureDef"] = {}


@dataclass
class FixtureDef:
    name: str
    scope: str  # session, category, endpoint, flow
    func: Callable[..., Awaitable[Any]]
    deps: List[str]  # names of fixtures this depends on
    tier: int = 0  # eager-bootstrap dependency tier (0 = no deps; auto-computed)


def fixture(scope: str = "endpoint", name: Optional[str] = None) -> Callable:
    """Decorator: registers a fixture.

    Usage:
        @fixture(scope="session")
        async def admin_token(): ...

        @fixture(scope="session")
        async def primary_agent(admin_token): ...
    """
    if scope not in ("session", "category", "endpoint", "flow"):
        raise ValueError(f"Invalid scope: {scope}")

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable:
        fixture_name = name or func.__name__
        sig = inspect.signature(func)
        deps = [p.name for p in sig.parameters.values() if p.name not in ("self", "ctx", "kwargs")]
        _FIXTURES[fixture_name] = FixtureDef(
            name=fixture_name,
            scope=scope,
            func=func,
            deps=deps,
        )
        return func

    return decorator


def get_fixture(name: str) -> Optional[FixtureDef]:
    return _FIXTURES.get(name)


def all_fixtures() -> Dict[str, FixtureDef]:
    return dict(_FIXTURES)


# ── Resolve eager-bootstrap tier (topological sort) ──────────────────────
def compute_tiers() -> Dict[str, int]:
    """Assign each fixture to a tier such that all deps have lower tier.

    Tier 0 = no dependencies among registered fixtures.
    Used for parallel eager-bootstrap: run all tier-N fixtures concurrently,
    then all tier-(N+1), etc.
    """
    tiers: Dict[str, int] = {}

    def resolve(name: str, stack: Set[str]) -> int:
        if name in tiers:
            return tiers[name]
        if name in stack:
            raise ValueError(f"Fixture cycle: {' -> '.join(stack)} -> {name}")
        if name not in _FIXTURES:
            # External or runtime arg — treat as tier 0
            return 0
        stack = stack | {name}
        deps = _FIXTURES[name].deps
        if not deps:
            tier = 0
        else:
            tier = max((resolve(d, stack) for d in deps), default=-1) + 1
        tiers[name] = tier
        _FIXTURES[name].tier = tier
        return tier

    for name in list(_FIXTURES.keys()):
        resolve(name, set())

    return tiers


# ── Bootstrap context ────────────────────────────────────────────────────
@dataclass
class BootstrapContext:
    """Holds resolved fixture instances across a test run."""
    session_cache: Dict[str, Any] = field(default_factory=dict)
    category_cache: Dict[str, Dict[str, Any]] = field(default_factory=lambda: defaultdict(dict))
    extras: Dict[str, Any] = field(default_factory=dict)  # for runtime args

    async def resolve(self, name: str, current_category: Optional[str] = None) -> Any:
        """Get or compute a fixture value."""
        if name in self.extras:
            return self.extras[name]

        if name not in _FIXTURES:
            raise KeyError(f"Unknown fixture: {name}")

        fd = _FIXTURES[name]

        if fd.scope == "session" and name in self.session_cache:
            return self.session_cache[name]
        if fd.scope == "category" and current_category and name in self.category_cache[current_category]:
            return self.category_cache[current_category][name]

        # Resolve deps
        dep_values = {}
        for dep_name in fd.deps:
            dep_values[dep_name] = await self.resolve(dep_name, current_category)

        value = await fd.func(**dep_values)

        if fd.scope == "session":
            self.session_cache[name] = value
        elif fd.scope == "category" and current_category:
            self.category_cache[current_category][name] = value

        return value

    async def eager_bootstrap(self) -> Dict[str, Any]:
        """Resolve all session-scope fixtures in parallel by tier.

        Returns a dict of resolved values.
        """
        compute_tiers()
        session_fixtures = [fd for fd in _FIXTURES.values() if fd.scope == "session"]
        by_tier: Dict[int, List[FixtureDef]] = defaultdict(list)
        for fd in session_fixtures:
            by_tier[fd.tier].append(fd)

        for tier in sorted(by_tier.keys()):
            await asyncio.gather(
                *(self.resolve(fd.name) for fd in by_tier[tier]),
                return_exceptions=False,
            )
            logger.info(
                f"Eager bootstrap tier {tier}: resolved {[fd.name for fd in by_tier[tier]]}"
            )

        return dict(self.session_cache)


# ── Global default context (one per request session, populated lazily) ────
_default_ctx: Optional[BootstrapContext] = None


def get_default_ctx() -> BootstrapContext:
    global _default_ctx
    if _default_ctx is None:
        _default_ctx = BootstrapContext()
    return _default_ctx


def reset_default_ctx() -> None:
    """Drop the default context (e.g., on /reset-flow-values)."""
    global _default_ctx
    _default_ctx = None
