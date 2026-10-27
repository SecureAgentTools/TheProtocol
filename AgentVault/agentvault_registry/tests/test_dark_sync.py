"""§DARKSYNC (2026-09-22, his words "figure out why dark agents dont synch. fix it properly"): UNLISTED means "not in
discovery", not "never leaves home".

Measured on the sandbox before the fix: 19 of sbx-alpha's 21 unlisted native agents (svc-sim's clerks, svc-market's
funders) had no mirror on sbx-beta, while 50 of 50 listed ones did. The export sent every unlisted card as a content-free
tombstone and the receiver refused to create a mirror from one, so a card BORN unlisted (every service account's agent
since §FRAMELIC) never existed on any peer, and whatever places an agent through the card mesh failed for it.

Now: a puller that sends `listing_carry` receives the full card with the listing block and the envelope flag, stores the
mirror with `unlisted` set, and every discovery surface on both sides filters that column; a puller that does not ask
keeps getting the tombstone, so an older peer can never create a LISTED mirror of a dark agent.
"""
import inspect

from agentvault_registry.services import listing_propagation as lp


def _full_card(unlisted=True):
    cd = {"did": "did:theprotocol:x", "name": "clerk", "url": "https://sub-x.agents.local", "skills": [],
          "federation_metadata": {"origin_registry_name": "Sandbox Alpha"}}
    if unlisted:
        cd = lp.inject_extension(cd, lp.tombstone_state())
    return {"id": "00000000-0000-0000-0000-000000000001", "name": "clerk", "is_active": True, "card_data": cd,
            "unlisted": unlisted}


def _legacy_tombstone():
    return {"id": "00000000-0000-0000-0000-000000000002", "name": lp.TOMBSTONE_NAME, "is_active": False,
            "card_data": lp.tombstone_card_data("did:theprotocol:y", lp.tombstone_state(), "spiffe://sandbox-a/registry")}


def test_the_tombstone_and_a_full_dark_card_are_told_apart():
    assert lp.is_legacy_tombstone(_legacy_tombstone())
    assert not lp.is_legacy_tombstone(_full_card(unlisted=True))
    assert not lp.is_legacy_tombstone(_full_card(unlisted=False))
    assert lp.unlisted_from_card(_full_card(unlisted=True)["card_data"]) is True
    assert lp.unlisted_from_card(_full_card(unlisted=False)["card_data"]) is None


def test_the_export_carries_the_full_dark_card_only_to_a_puller_that_asks():
    from agentvault_registry.routers import federation_sync as fs
    src = inspect.getsource(fs.get_agent_cards_for_sync)
    assert "listing_carry: bool = Query(" in src
    assert ('_carry_unlisted = bool(listing_carry) and _listing_mode == "enforce" and '
            'bool(getattr(card, "unlisted", False))') in src
    # the block goes on after every other extension and BEFORE the v0.3 projection, which strips extensions
    # §ECHO-2 (2026-09-28): the block's state is derived once per unlisted card (naming a relayed card's home)
    i_inject = src.index("export_card_data = _lp.inject_extension(export_card_data, _listing_state)")
    i_v03 = src.index("render_for_v03_peer(export_card_data)")
    i_bond = src.index("_rb.inject_extension(export_card_data")
    assert i_bond < i_inject < i_v03
    assert "unlisted=_carry_unlisted," in src
    assert fs.AgentCardSyncData.model_fields["unlisted"].default is False


def test_the_puller_asks_for_dark_cards():
    from agentvault_registry.background_tasks import federation_sync as bfs
    src = inspect.getsource(bfs)
    assert "'listing_carry': 'true'" in src


def test_the_receiver_stores_a_full_dark_card_as_an_unlisted_mirror():
    from agentvault_registry.crud import crud_peer_registry as cpr
    src = inspect.getsource(cpr.upsert_agent_cards_from_peer)
    assert "_carried_unlisted = _says_unlisted and not _lp.is_legacy_tombstone(agent_card)" in src
    assert "_says_unlisted = bool(agent_card.get('unlisted')) or _lp.unlisted_from_card(agent_card.get('card_data')) is True" in src
    # not under enforce: not imported at all (a LISTED mirror would put a dark agent into discovery)
    i_car = src.index("if _carried_unlisted:")
    assert src.index('if _lp_early != "enforce":', i_car) < src.index("await _set_mirror_unlisted(db, card_uuid, peer_svid)", i_car)
    assert "unlisted=bool(_carried_unlisted)," in src
    assert "and not _carried_unlisted):" in src          # the insert refusal is for the tombstone only
    setter = inspect.getsource(cpr._set_mirror_unlisted)
    assert "SET unlisted = TRUE" in setter and "updated_at" not in setter.split('"""')[2], \
        "the column flip must not move the mirror's clock (the content path compares it)"
    assert "source_registry}') IS NOT NULL" in setter      # a mirror only, never a native card


def test_every_discovery_surface_hides_dark_cards():
    from agentvault_registry.crud import agent_card as crud_ac
    from agentvault_registry.routers import agent_cards, agent_discovery, anp_discovery, agent_locations
    from agentvault_registry import federation_helper
    assert "filters.append(models.AgentCard.unlisted.is_(False))" in inspect.getsource(crud_ac.list_agent_cards)
    lst = inspect.getsource(agent_cards.list_agent_cards)
    assert "listed_only = not (owned_only or (include_unlisted and current_developer is not None" in lst
    assert "listed_only=listed_only," in lst and '"listed_only": bool(listed_only),' in lst
    assert "models.AgentCard.unlisted.is_(False) if listed_only else" in lst                 # the flare augmentation
    assert "models.AgentCard.unlisted.is_(False))" in inspect.getsource(agent_cards._list_focused_subset)
    disc = inspect.getsource(agent_discovery)
    assert disc.count("AgentCard.unlisted.is_(False)") >= 2                                   # list, count
    # the mirrors pass discovery's one population rule (V0640), which carries the unlisted check
    assert "text(CARD_POPULATION_SQL).bindparams(**card_population_params())" in disc
    assert "c.unlisted = FALSE" in agent_cards.CARD_POPULATION_SQL
    assert inspect.getsource(anp_discovery).count("AgentCard.unlisted.is_(False)") == 2
    loc = inspect.getsource(agent_locations)
    assert loc.count("AND NOT unlisted") == 3 and loc.count("~models.Agent.did.in_(_dark_dids)") == 3
    assert 'card.get("unlisted")' in inspect.getsource(federation_helper)


def test_a_dark_gateway_stays_dark_on_the_buyer():
    from agentvault_registry.services import exchange_passport as ep
    src = inspect.getsource(ep)
    assert '"unlisted": _gw_dark,' in src and "_lp.inject_extension(_cd, _lp.tombstone_state(gw_row.updated_at))" in src


def test_direct_lookups_stay_unfiltered():
    """A dark agent must still RESOLVE by DID (that is the point of syncing it): the per-DID lookups and the venue's
    home resolution carry no listing filter."""
    from agentvault_registry.routers import agent_cards
    from agentvault_registry.services import exchange_passport as ep
    assert "unlisted" not in inspect.getsource(ep._home_registry_of)
    for name in ("_resolve_agent_card", "_find_card_by_agent_did"):
        fn = getattr(agent_cards, name, None)
        if fn is not None:
            assert "unlisted.is_(False)" not in inspect.getsource(fn)
