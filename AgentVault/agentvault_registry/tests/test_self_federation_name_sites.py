"""§AGORASIM-2 (2026-09-22): the name a registry gives peers for ITSELF is its federation name, everywhere.

On a cloud operator REGISTRY_NAME is the stack label (`cloud-op-sbxalphaop`) and REGISTRY_FEDERATION_NAME the name its
card publishes and every peer row stores (`sbxalphaop`); measured on both sandbox operators and on amsterdam. The
DevCard signed `home_registry` from REGISTRY_NAME, and a venue resolves the home's JWKS by that string, so every
passport order an unlisted clerk placed from an operator answered 502 "no ACTIVE peer registry 'cloud-op-sbxalphaop'"
(the venue cannot place a clerk through the card mesh and falls back to the DevCard's name). The cross-frame vote
treated "self" as FEDERATION_NAME or REGISTRY_NAME, so an operator's own federation name read as a foreign frame.
"""
import inspect

from agentvault_registry.config import settings
from agentvault_registry.routers import dev_card, exchange


def test_the_devcard_home_is_the_federation_name_on_an_operator(monkeypatch):
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbxalphaop")
    monkeypatch.setenv("REGISTRY_NAME", "cloud-op-sbxalphaop")
    monkeypatch.setattr(settings, "REGISTRY_NAME", "cloud-op-sbxalphaop", raising=False)
    assert dev_card._home_registry_name() == "sbxalphaop"


def test_a_frame_without_a_federation_name_keeps_its_registry_name(monkeypatch):
    monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
    monkeypatch.setattr(settings, "REGISTRY_NAME", "Sandbox Alpha", raising=False)
    assert dev_card._home_registry_name() == "Sandbox Alpha"


def test_the_devcard_asks_the_one_rule():
    src = inspect.getsource(dev_card._home_registry_name)
    assert "self_federation_name()" in src
    assert src.index("self_federation_name()") < src.index('os.getenv("REGISTRY_NAME")'), \
        "the stack label is consulted before the federation name"


def test_the_vote_counts_the_federation_name_as_self():
    src = inspect.getsource(exchange.exchange_cast_vote)
    assert "self_federation_name as _self_fed" in src and "(_self_fed() or \"\").lower()" in src
