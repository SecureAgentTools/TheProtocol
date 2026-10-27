"""D8 — the legacy money surfaces are retired behind flags (default ON: every running node byte-identical)."""
import pathlib
from agentvault_registry.core import legacy_surfaces as ls

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def test_default_on_and_only_an_explicit_off_retires(monkeypatch):
    for n in ls.LEGACY_SURFACES:
        monkeypatch.delenv(n, raising=False)
        assert ls.surface_enabled(n) is True
    monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", "false"); assert ls.surface_enabled("TOKEN_BRIDGE_ENABLED") is False
    monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", "OFF"); assert ls.surface_enabled("TOKEN_BRIDGE_ENABLED") is False
    monkeypatch.setenv("TOKEN_BRIDGE_ENABLED", "nonsense"); assert ls.surface_enabled("TOKEN_BRIDGE_ENABLED") is True, "a typo must not retire a surface"
    assert "D8" in ls.retired_sentence("ARENA_BETTING_ENABLED") and "ARENA_BETTING_ENABLED" in ls.retired_sentence("ARENA_BETTING_ENABLED")


def test_the_mounts_and_the_bet_read_their_flags():
    main = (SRC / "main.py").read_text(encoding="utf-8")
    assert 'if _surface_enabled("LEGACY_CONTRACTS_ENABLED"):\n        app.include_router(contracts.router)' in main
    assert 'if _surface_enabled("TOKEN_BRIDGE_ENABLED"):  # D8\n        app.include_router(token_bridge.router)' in main
    arena = (SRC / "arena" / "mcp_server.py").read_text(encoding="utf-8")
    assert 'if not _se("ARENA_BETTING_ENABLED"):' in arena and arena.index('_se("ARENA_BETTING_ENABLED")') < arena.index("betting_manager.place_bet(")
