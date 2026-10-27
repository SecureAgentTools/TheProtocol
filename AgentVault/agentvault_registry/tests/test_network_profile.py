"""§MONEY-M2 — the network profile loader.

The profile exists so that every money amount lives in one readable file instead
of being a literal at its call site. The property that makes it safe to ship is
PRECEDENCE: an env var still wins, and with no profile selected every knob falls
back to the literal it replaced. These tests pin that, in both directions.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agentvault_registry.core import network_profile as np


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    monkeypatch.delenv("NETWORK_PROFILE_DIR", raising=False)
    np.reset_cache()
    yield
    np.reset_cache()


# ── rule 2: no profile selected ⇒ nothing changes ───────────────────────────

def test_no_profile_selected_returns_the_callers_fallback():
    assert np.money_knob("SOME_AMOUNT", "10.0") == Decimal("10.0")
    assert np.int_knob("SOME_COUNT", 7) == 7
    assert np.bool_knob("SOME_FLAG", True) is True
    assert np.load() == {}


# ── rule 1: env wins over the profile ───────────────────────────────────────

def test_env_beats_profile(tmp_path, monkeypatch):
    (tmp_path / "network_profile.t.env").write_text("A_KNOB=5\n")
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    monkeypatch.setenv("A_KNOB", "9")
    np.reset_cache()
    # the profile must actually be loaded, or this test passes for the wrong
    # reason: "env wins" is indistinguishable from "no profile was found".
    assert np.load() == {"A_KNOB": "5"}
    assert np.money_knob("A_KNOB", "1") == Decimal("9")


def test_profile_beats_the_fallback(tmp_path, monkeypatch):
    (tmp_path / "network_profile.t.env").write_text("A_KNOB=5\n")
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    assert np.money_knob("A_KNOB", "1") == Decimal("5")


def test_an_empty_env_value_does_not_shadow_the_profile(tmp_path, monkeypatch):
    """`FOO=` in a compose file is "unset", not "zero" — otherwise a blank line
    in a carrier silently zeroes a money knob."""
    (tmp_path / "network_profile.t.env").write_text("A_KNOB=5\n")
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    monkeypatch.setenv("A_KNOB", "   ")
    np.reset_cache()
    assert np.money_knob("A_KNOB", "1") == Decimal("5")


# ── a config file must never take a money rail down ─────────────────────────

def test_a_missing_profile_file_is_not_fatal(monkeypatch):
    monkeypatch.setenv("NETWORK_PROFILE", "does-not-exist-anywhere")
    np.reset_cache()
    assert np.money_knob("A_KNOB", "3") == Decimal("3")


def test_a_malformed_amount_falls_back_rather_than_raising(tmp_path, monkeypatch):
    (tmp_path / "network_profile.t.env").write_text("A_KNOB=not-a-number\n")
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    assert np.money_knob("A_KNOB", "3") == Decimal("3")


def test_an_unreadable_directory_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path / "nope"))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    assert np.money_knob("A_KNOB", "3") == Decimal("3")


# ── parsing ─────────────────────────────────────────────────────────────────

def test_parse_handles_comments_quotes_and_export(tmp_path, monkeypatch):
    (tmp_path / "network_profile.t.env").write_text(
        "# a comment\n"
        "\n"
        "export A=1\n"
        'B="two"\n'
        "C='three'\n"
        "   D=4   \n"
        "NOT_A_LINE\n"
    )
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    got = np.load()
    assert got == {"A": "1", "B": "two", "C": "three", "D": "4"}


def test_a_json_knob_keeps_its_hash(tmp_path, monkeypatch):
    """FLARE_SHOP_PRICES is JSON and may contain '#'. Stripping inline comments
    would corrupt it, so the parser deliberately does not."""
    (tmp_path / "network_profile.t.env").write_text('P={"a":"#ff0000"}\n')
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    assert np.load()["P"] == '{"a":"#ff0000"}'


def test_a_path_selector_works_as_well_as_a_name(tmp_path, monkeypatch):
    f = tmp_path / "custom.env"
    f.write_text("A_KNOB=42\n")
    monkeypatch.setenv("NETWORK_PROFILE", str(f))
    np.reset_cache()
    assert np.money_knob("A_KNOB", "1") == Decimal("42")
