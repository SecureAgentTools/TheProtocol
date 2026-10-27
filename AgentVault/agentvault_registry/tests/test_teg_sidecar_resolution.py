"""An ambiguous TEG id must resolve to NOTHING, never to a guess.

§XFRAMETEG (2026-09-04). `_dest_teg_sidecar_host` mapped the BARE literal
`teg-layer` to `nginx-teg-a` — Frame A's TEG mTLS sidecar. But `teg-layer` is
what EVERY frame's own TEG stamps for itself: measured live, frame-b, frame-c
and both sandbox frames all stamp exactly `TEG_ID=teg-layer`, while Frame A
stamps `teg-layer-a`. So a target carrying the bare literal is BY CONSTRUCTION
not Frame A, and that branch could only ever fire on a wrong answer.

It did not fail loudly. `getaddrinfo("nginx-teg-a", 8443)` succeeds for any
caller on `agentvault_main_network`, so the dial went through to the wrong
frame's TEG. The current consumer is the `FX_RATE_MODE=pool` AMM, which prices a
cross-frame swap off BOTH frames' `fx_reserve` — so the damage is a wrong RATE
on a swap that stays Δ-neutral per frame. The supply invariant cannot see it.
`FX_RATE_MODE=pool` is live on registry-a and set for frame-b/frame-c.
"""
import pytest

from agentvault_registry.routers.teg_integration import _dest_teg_sidecar_host


@pytest.mark.parametrize("teg_id", ["teg-layer", " teg-layer ", ""])
def test_an_ambiguous_or_empty_teg_id_derives_nothing(monkeypatch, teg_id):
    """The bare `teg-layer` is every frame's self-stamp — it identifies no peer."""
    monkeypatch.delenv("TEG_SIDECAR_MAP", raising=False)
    assert _dest_teg_sidecar_host(teg_id, "sbx-beta") == "", (
        f"{teg_id!r} resolved to a sidecar; an ambiguous key must fall through to the "
        f"registry-keyed resolver, not guess a frame")


def test_frame_a_still_derives_from_its_own_unambiguous_stamp(monkeypatch):
    """Frame A stamps `teg-layer-a`, which names exactly one frame."""
    monkeypatch.delenv("TEG_SIDECAR_MAP", raising=False)
    assert _dest_teg_sidecar_host("teg-layer-a", "") == "nginx-teg-a"


def test_an_explicit_map_still_wins_for_an_ambiguous_id(monkeypatch):
    """`TEG_SIDECAR_MAP` is how a frame names a peer's sidecar unambiguously.

    This is the supported route for frames, precisely BECAUSE their teg_id is
    ambiguous — so the map must still be consulted for the bare literal, keyed
    either by teg_id or by registry id.
    """
    monkeypatch.setenv("TEG_SIDECAR_MAP", '{"sbx-beta": "sbx-beta-nginx-teg"}')
    assert _dest_teg_sidecar_host("teg-layer", "sbx-beta") == "sbx-beta-nginx-teg"
    monkeypatch.setenv("TEG_SIDECAR_MAP", '{"teg-layer": "sbx-beta-nginx-teg"}')
    assert _dest_teg_sidecar_host("teg-layer", "") == "sbx-beta-nginx-teg"


def test_a_malformed_map_does_not_resurrect_the_guess(monkeypatch):
    """A broken map falls back to derivation — which must still refuse to guess."""
    monkeypatch.setenv("TEG_SIDECAR_MAP", "{not json")
    assert _dest_teg_sidecar_host("teg-layer", "sbx-beta") == ""
