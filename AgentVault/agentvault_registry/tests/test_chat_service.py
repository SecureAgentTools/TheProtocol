"""§OURSTATE-1 — unit tests for the chat logic core's PURE decision layer.

Scope: everything in services/chat_service.py that decides without a database
— card vocabulary validation (the closed set, law 1's enforcement point), pair
keys, the Requests state machine, unread math, previews, the deterministic
result client_ref. The DB-integrated flows (atomic seq, dedup race, block
silence, burn) are proven by the frame-c battery against a live registry —
a mocked session proving them would be the "test that cannot fail" class.

Run: python3 -m pytest tests/test_chat_service.py -q
"""
import re
import pytest

from agentvault_registry.services import chat_service as cs


# ---------------------------------------------------------------------------
# principal / pair keys
# ---------------------------------------------------------------------------

def test_principal_key_shapes():
    assert cs.principal_key("developer", 7) == "dev:7"
    assert cs.principal_key("agent", "did:theprotocol:ABC") == "agt:did:theprotocol:abc"
    with pytest.raises(ValueError):
        cs.principal_key("system", 1)


def test_pair_key_is_unordered_and_kind_prefixed():
    a, b = "dev:7", "agt:did:theprotocol:x"
    assert cs.pair_key("dm", a, b) == cs.pair_key("dm", b, a)
    assert cs.pair_key("dm", a, b).startswith("dm|")
    assert cs.pair_key("agent_service", a, b).startswith("svc|")
    # A dm and a service thread between the same pair never collide.
    assert cs.pair_key("dm", a, b) != cs.pair_key("agent_service", a, b)


def test_split_key_roundtrip():
    assert cs._split_key("dev:42") == ("developer", "42")
    assert cs._split_key("agt:did:theprotocol:z") == ("agent", "did:theprotocol:z")


# ---------------------------------------------------------------------------
# card vocabulary (the closed set — law 1's enforcement point)
# ---------------------------------------------------------------------------

def _card(ctype="pay.request", data=None, **extra):
    base = {"v": 1, "type": ctype,
            "data": data if data is not None else {"amount": "5", "currency": "BVT"}}
    base.update(extra)
    return base


def test_card_happy_path():
    assert cs.validate_card(_card()) is None
    assert cs.validate_card(_card("pay.receipt",
                                  {"amount": "1.5", "currency": "AVT"},
                                  refs={"tx_id": "t1"})) is None
    assert cs.validate_card(_card("agent.card", {"did": "did:theprotocol:abc"})) is None


def test_card_wrong_version_refused():
    assert "card.v" in cs.validate_card(_card() | {"v": 2})


def test_card_unknown_type_refused_closed_vocabulary():
    reason = cs.validate_card(_card("evil.markup", {"html": "<b>"}))
    assert reason is not None and "closed" in reason


def test_card_later_phase_types_named_not_generic():
    # §OURSTATE-2 batch 2b widened this: contract.offer / guild.order are now
    # client-postable POINTERS (see TestWorkCards). §OURSTATE-5c then built the
    # fiat door, so topup.offer stopped being "not built yet" and became "built
    # and locked" — the refusal names the DOOR now. The invariant under test is
    # unchanged: a refused type refuses specifically, never generically.
    reason = cs.validate_card(_card("topup.offer", {"x": 1}))
    assert reason is not None and "fiat door" in reason.lower()

    # And a type that genuinely is not built yet still says so by name.
    unbuilt = cs.LATER_PHASE_CARDS - {"topup.offer"}
    for t in unbuilt:
        r = cs.validate_card(_card(t, {"x": 1}))
        assert r is not None and "later" in r.lower() and t in r


def test_card_rail_only_types_refused_for_clients_allowed_for_rail():
    call = _card("service.call", {"ask": "weather?"})
    reason = cs.validate_card(call)
    assert reason is not None and "rail" in reason
    assert cs.validate_card(call, rail_author=True) is None


def test_card_envelope_unknown_keys_refused():
    assert "unknown keys" in cs.validate_card(_card() | {"onTap": "fetch('x')"})


def test_card_amount_must_be_positive_decimal():
    assert cs.validate_card(_card(data={"amount": "-3", "currency": "BVT"})) is not None
    assert cs.validate_card(_card(data={"amount": "abc", "currency": "BVT"})) is not None
    assert cs.validate_card(_card(data={"amount": "0", "currency": "BVT"})) is not None
    assert cs.validate_card(_card(data={"amount": "12.5", "currency": ""})) is not None


def test_card_size_cap():
    big = _card(data={"amount": "1", "currency": "BVT", "memo": "x" * (cs.CARD_MAX_BYTES + 1)})
    assert "limit" in cs.validate_card(big)


def test_agent_card_requires_did():
    assert cs.validate_card(_card("agent.card", {"name": "SYBIL"})) is not None


def test_body_cap():
    assert cs.validate_body("hi") is None
    assert cs.validate_body("x" * (cs.BODY_MAX_BYTES + 1)) is not None


# ---------------------------------------------------------------------------
# state machine + unread + preview
# ---------------------------------------------------------------------------

def test_state_machine_table():
    assert cs.transition_state("pending", "accept") == "active"
    assert cs.transition_state("pending", "decline") == "left"
    assert cs.transition_state("active", "leave") == "left"
    for bad in (("active", "accept"), ("left", "accept"), ("left", "leave"),
                ("active", "decline")):
        with pytest.raises(cs.ChatError):
            cs.transition_state(*bad)


def test_unread_math_floors():
    assert cs.unread_count(10, 4, None) == 6
    assert cs.unread_count(10, 4, 8) == 2       # burn floor beats read floor
    assert cs.unread_count(10, 12, None) == 0   # never negative
    assert cs.unread_count(0, 0, None) == 0


def test_preview_shapes():
    assert cs.preview_for("text", "hello world", None) == "hello world"
    # §CHATCOHERE D7 pinned the old `[ping]` bracket here as "named, not fixed".
    # It IS fixed now — system rows render as sentences; tests/test_system_preview.py
    # owns that family, including the cross-artifact drift gate against the FE brain.
    assert cs.preview_for("system", "ping", None) == "Someone pinged"
    assert cs.preview_for("system", "ping", None, "Ada") == "Ada pinged"
    assert len(cs.preview_for("text", "y" * 500, None)) == cs.PREVIEW_LEN


# ---------------------------------------------------------------------------
# §CHATCOHERE D7 — cards preview as a SENTENCE, never as their protocol type.
#
# Measured on a frame-c cold start: the thread list read `[service.result]`.
# These cases are built from cards taken off the LIVE frame-c `chat_messages`
# table, not from invented fixtures — the invented ones are exactly what let the
# `engagement.*` family (which denominates in `total`, not `amount`) lose its
# money silently until real data was run through the table.
# ---------------------------------------------------------------------------

def test_card_preview_is_a_sentence_not_a_type():
    out = cs.preview_for("card", None, {"type": "pay.request"})
    assert "[" not in out and "]" not in out
    assert out == "Payment requested"


def test_card_preview_service_result_states_the_charge():
    card = {"type": "service.result", "data": {
        "ok": True, "summary": "delivered",
        "paid_amount": "0.604177", "paid_currency": "BVT"}}
    assert cs.preview_for("card", None, card) == "Answered \u2014 0.604177 BVT charged"


def test_card_preview_failed_call_says_nothing_was_charged():
    card = {"type": "service.result", "data": {
        "ok": False, "error": "City not found.", "summary": "failed"}}
    out = cs.preview_for("card", None, card)
    assert "Not delivered" in out and "nothing charged" in out


def test_card_preview_engagement_family_reads_total_not_amount():
    """The engagement cards denominate in `total`; only `settled` uses `amount`.
    Reading the wrong key loses the money WITHOUT failing — the quiet class."""
    assert cs.preview_for("card", None, {"type": "engagement.accepted",
        "data": {"total": "2.5000000000", "currency": "BVT"}}) == \
        "Offer accepted — 2.5 BVT held in escrow"
    assert cs.preview_for("card", None, {"type": "engagement.settled",
        "data": {"amount": "2.0000000000", "currency": "BVT"}}) == "Settled — 2 BVT released"


def test_card_preview_never_prints_an_amount_without_its_currency():
    """§FOREIGNACT in a preview: empty unit, never wrong unit. A number with no
    unit beside it is a number a reader will assume is theirs."""
    only_amount = cs.preview_for("card", None, {"type": "pay.request", "data": {"amount": "12.5"}})
    only_ccy = cs.preview_for("card", None, {"type": "pay.request", "data": {"currency": "BVT"}})
    assert only_amount == "Payment requested" and "12.5" not in only_amount
    assert only_ccy == "Payment requested" and "BVT" not in only_ccy
    # and with BOTH, it says so
    assert "12.5 BVT" in cs.preview_for("card", None,
        {"type": "pay.request", "data": {"amount": "12.5", "currency": "BVT"}})


def test_card_preview_unknown_type_degrades_readably():
    """A card family added tomorrow should read as plain, never as a token."""
    out = cs.preview_for("card", None, {"type": "future.thing", "data": {}})
    assert out == "Future thing" and "[" not in out


def test_card_preview_respects_the_length_cap():
    long_ask = {"type": "service.call", "data": {"ask": "x" * 4000}}
    assert len(cs.preview_for("card", None, long_ask)) <= cs.PREVIEW_LEN


def test_every_known_card_type_has_a_sentence():
    """The vocabulary is CLOSED, so the sentence table must cover all of it.

    Coverage is asserted STRUCTURALLY — every type must have its own branch in
    `_card_sentence` — because the output test cannot tell "handled, and its
    empty-data sentence happens to read like the generic label" (contract.offer)
    from "not handled at all". The structural check is the one that actually
    fails the day someone adds a card type and forgets the sentence.
    """
    import inspect
    src = inspect.getsource(cs._card_sentence)
    for t in sorted(cs.KNOWN_CARD_TYPES):
        assert f'"{t}"' in src, f"{t} has no branch in _card_sentence"
        out = cs.preview_for("card", None, {"type": t, "data": {}})
        assert out and "[" not in out, f"{t} previewed as {out!r}"


def test_result_client_ref_deterministic_and_distinct():
    a = cs.result_client_ref("11111111-2222-3333-4444-555555555555")
    b = cs.result_client_ref("11111111-2222-3333-4444-555555555555")
    c = cs.result_client_ref("99999999-2222-3333-4444-555555555555")
    assert a == b and a != c
    assert a != "11111111-2222-3333-4444-555555555555"
    assert 8 <= len(a) <= 64


# ---------------------------------------------------------------------------
# §OURSTATE-2 — room logic (pure halves)
# ---------------------------------------------------------------------------

class TestRoomPairKey:
    def test_one_room_per_org(self):
        assert cs.room_pair_key("org-123") == "org|org-123"
        assert cs.room_pair_key("org-123") == cs.room_pair_key("org-123")

    def test_room_key_never_collides_with_pair_keys(self):
        # The dm/svc prefixes and the org prefix partition the UNIQUE column.
        dm = cs.pair_key("dm", "dev:1", "agt:x")
        svc = cs.pair_key("agent_service", "dev:1", "agt:x")
        room = cs.room_pair_key("dev:1")   # adversarial: org id shaped like a key
        assert len({dm, svc, room}) == 3


class TestCanActOn:
    def test_operator_acts_downward_only(self):
        assert cs.can_act_on("owner", "admin") is True
        assert cs.can_act_on("owner", "member") is True
        assert cs.can_act_on("admin", "member") is True
        assert cs.can_act_on("admin", "guest") is True

    def test_never_upward_or_lateral(self):
        assert cs.can_act_on("admin", "owner") is False
        assert cs.can_act_on("admin", "admin") is False
        assert cs.can_act_on("owner", "owner") is False

    def test_non_operator_acts_on_nobody(self):
        assert cs.can_act_on("member", "guest") is False
        assert cs.can_act_on("guest", None) is False
        assert cs.can_act_on(None, "member") is False

    def test_roleless_target_is_actionable(self):
        # A room-joined agent holds no org role — operators can moderate it.
        assert cs.can_act_on("owner", None) is True
        assert cs.can_act_on("admin", None) is True


class TestRoomConstants:
    def test_actions_closed_set(self):
        # §ROOMBRAIN (V0211) added the two assistant presence ops to the closed
        # set; this assertion had been failing against deployed code ever since.
        # Corrected to what the vocabulary IS — an inherited red test is a
        # disabled test, and this one is NOT from this batch.
        assert set(cs.ROOM_ACTIONS) == {"kick", "mute", "unmute", "mode", "topic",
                                        "motd", "assistant_on", "assistant_off"}

    def test_ops_roles(self):
        assert set(cs.ROOM_OPS_ROLES) == {"owner", "admin"}
        # every ops role outranks member
        for r in cs.ROOM_OPS_ROLES:
            assert cs.ROOM_ROLE_RANK[r] > cs.ROOM_ROLE_RANK["member"]

    def test_genesis_bounds(self):
        assert cs.GENESIS_MAX == 2000
        assert cs.GENESIS_HISTORY_KEEP >= 1


# ---------------------------------------------------------------------------
# §OURSTATE-2 batch 2b — WORK cards + Away mode (pure halves)
# ---------------------------------------------------------------------------

class TestWorkCards:
    def test_work_cards_are_client_postable_pointers(self):
        for t in ("contract.offer", "guild.order"):
            assert t in cs.CLIENT_POSTABLE_CARDS
            card = {"v": 1, "type": t, "data": {"ref": "ctr_abc123", "title": "Translate the handbook"}}
            assert cs.validate_card(card) is None

    # ── §OURCHAT-ORG: the venue pointer ──────────────────────────────────
    def test_listing_is_a_client_postable_pointer(self):
        assert "exchange.listing" in cs.CLIENT_POSTABLE_CARDS
        card = {"v": 1, "type": "exchange.listing",
                "data": {"symbol": "SMKD", "display_name": "Samarkand Freight Lines"}}
        assert cs.validate_card(card) is None

    def test_listing_needs_a_symbol_and_it_must_be_a_ticker(self):
        assert "data.symbol" in cs.validate_card(
            {"v": 1, "type": "exchange.listing", "data": {"display_name": "x"}})
        assert "alphanumeric" in cs.validate_card(
            {"v": 1, "type": "exchange.listing", "data": {"symbol": "SM KD"}})

    def test_listing_price_must_name_its_currency(self):
        """§FOREIGNACT, on the card most likely to be read across frames: an
        amount and its unit travel together or neither is stated."""
        base = {"v": 1, "type": "exchange.listing", "data": {"symbol": "SMKD"}}
        no_ccy = {**base, "data": {**base["data"], "last_price": "20.26"}}
        assert "currency is required" in cs.validate_card(no_ccy)
        ok = {**base, "data": {**base["data"], "last_price": "20.26", "currency": "BVT"}}
        assert cs.validate_card(ok) is None

    def test_listing_cannot_become_an_order_slip(self):
        """A card carrying a side and a size is somebody else's order, and a
        human tapping it would be confirming a trade they did not compose."""
        for banned in ("side", "qty", "quantity", "order", "url", "endpoint"):
            problem = cs.validate_card({"v": 1, "type": "exchange.listing",
                                        "data": {"symbol": "SMKD", banned: "buy"}})
            assert problem and banned in problem, f"{banned} was not refused by name"

    def test_pointer_needs_a_ref_and_a_title(self):
        assert "data.ref" in cs.validate_card(
            {"v": 1, "type": "guild.order", "data": {"title": "x"}})
        assert "data.title" in cs.validate_card(
            {"v": 1, "type": "guild.order", "data": {"ref": "o1"}})

    def test_amount_when_present_needs_a_currency_and_must_parse(self):
        base = {"v": 1, "type": "contract.offer", "data": {"ref": "c1", "title": "t"}}
        bad_amt = {**base, "data": {**base["data"], "amount": "not-a-number"}}
        assert "decimal string" in cs.validate_card(bad_amt)
        no_ccy = {**base, "data": {**base["data"], "amount": "5"}}
        assert "currency" in cs.validate_card(no_ccy)
        good = {**base, "data": {**base["data"], "amount": "5", "currency": "BVT"}}
        assert cs.validate_card(good) is None

    def test_topup_offer_still_refused_by_name(self):
        """§OURSTATE-5c moved the refusal from "later phase" to the fiat door
        itself. It is still refused BY NAME with no door resolved, which was
        always the property under test — the wording changed because the
        feature exists now."""
        r = cs.validate_card({"v": 1, "type": "topup.offer", "data": {}})
        assert r and "fiat door" in r


class TestAwayGate:
    CFG = {"enabled": True, "agent_did": "did:theprotocol:stand-in"}

    def test_answers_a_stranger_dm_only(self):
        assert cs.away_should_answer(self.CFG, "dm", "pending", "c1") is True

    def test_never_for_an_accepted_thread(self):
        assert cs.away_should_answer(self.CFG, "dm", "active", "c1") is False

    def test_never_in_a_room_or_a_service_thread(self):
        assert cs.away_should_answer(self.CFG, "org", "pending", "c1") is False
        assert cs.away_should_answer(self.CFG, "agent_service", "pending", "c1") is False

    def test_off_by_default_and_needs_a_designation(self):
        assert cs.away_should_answer(None, "dm", "pending", "c1") is False
        assert cs.away_should_answer({"enabled": False, "agent_did": "did:x"}, "dm", "pending", "c1") is False
        assert cs.away_should_answer({"enabled": True}, "dm", "pending", "c1") is False

    def test_per_thread_kill_switch(self):
        cfg = {**self.CFG, "threads_off": ["c1"]}
        assert cs.away_should_answer(cfg, "dm", "pending", "c1") is False
        assert cs.away_should_answer(cfg, "dm", "pending", "c2") is True


class TestAwayDisclosure:
    def test_says_it_is_software_first_and_names_both(self):
        line = cs.away_disclosure("Stand-In", "ruFFa")
        assert line.startswith("Stand-In here — I am software")
        assert "ruFFa is away" in line

    def test_states_what_it_cannot_do(self):
        line = cs.away_disclosure("A", "B")
        for claim in ("cannot accept work", "sign anything", "move money"):
            assert claim in line

    def test_owner_note_rides_along_bounded(self):
        line = cs.away_disclosure("A", "B", "back monday " + "x" * 500)
        assert "left a note" in line
        assert len(line) < 900


# ---------------------------------------------------------------------------
# §OURSTATE-3 — handles (an ADDRESS, not an identity)
# ---------------------------------------------------------------------------

class TestHandles:
    def test_shape_rule_states_the_whole_rule(self):
        r = cs.validate_handle("ab")
        assert r and "3-32 characters" in r and "letters, digits" in r

    def test_accepts_a_reasonable_name(self):
        assert cs.validate_handle("ruFFa") is None
        assert cs.validate_handle("@ruFFa") is None      # the @ is decoration
        assert cs.validate_handle("a-b_c9") is None

    def test_refuses_what_would_confuse_an_address(self):
        for bad in ("with space", "-leading", "sym!bol", "x" * 33, "ab", ""):
            assert cs.validate_handle(bad) is not None, bad

    def test_reserved_words_refuse_naming_themselves(self):
        r = cs.validate_handle("admin")
        assert r and "reserved" in r and "admin" in r
        assert cs.validate_handle("Assistant") is not None   # case-insensitive

    def test_normalize_strips_the_at(self):
        assert cs.normalize_handle("@ruFFa") == "ruFFa"
        assert cs.normalize_handle("  ruFFa  ") == "ruFFa"


# ---------------------------------------------------------------------------
# §OURSTATE-3b — federation addressing (pure halves)
# ---------------------------------------------------------------------------

class TestRemoteKeys:
    def test_parses_handle_at_registry(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed.parse_remote_key("ruffa@https://frame-c.theprotocol.cloud") == \
            ("ruffa", "https://frame-c.theprotocol.cloud")

    def test_splits_on_the_LAST_at_so_a_handle_cannot_smuggle_an_address(self):
        from agentvault_registry.services import chat_federation as fed
        h, base = fed.parse_remote_key("evil@evil.example@https://real.example")
        assert base == "https://real.example"
        assert h == "evil@evil.example"

    def test_bare_host_defaults_to_https_never_http(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed.parse_remote_key("x@reg.example")[1] == "https://reg.example"

    def test_a_path_or_query_is_dropped_from_the_address(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed.parse_remote_key("x@https://reg.example/ui#/pocket?a=1")[1] == "https://reg.example"

    def test_refuses_the_unaddressable(self):
        from agentvault_registry.services import chat_federation as fed
        for bad in ("", "nohandle", "@", "x@", "@https://reg.example"):
            assert fed.parse_remote_key(bad) is None, bad

    def test_round_trip(self):
        from agentvault_registry.services import chat_federation as fed
        k = fed.remote_key("@ruffa", "https://reg.example/")
        assert k == "ruffa@https://reg.example"
        assert fed.parse_remote_key(k) == ("ruffa", "https://reg.example")


class TestFederationPosture:
    def test_off_by_default(self, monkeypatch):
        from agentvault_registry.services import chat_federation as fed
        monkeypatch.delenv("CHAT_FEDERATION_ENABLED", raising=False)
        assert fed.federation_enabled() is False

    def test_on_only_for_an_explicit_yes(self, monkeypatch):
        from agentvault_registry.services import chat_federation as fed
        for v, want in (("true", True), ("1", True), ("YES", True),
                        ("false", False), ("maybe", False), ("", False)):
            monkeypatch.setenv("CHAT_FEDERATION_ENABLED", v)
            assert fed.federation_enabled() is want, v

    def test_backoff_is_bounded_and_climbs(self):
        from agentvault_registry.services import chat_federation as fed
        b = fed.BACKOFF_SECONDS
        assert list(b) == sorted(b) and b[0] >= 1 and b[-1] <= 3600
        assert fed.MAX_ATTEMPTS >= len(b)   # every step is reachable before giving up


class TestLocalKeyExtraction:
    def test_picks_only_the_participants_who_live_here(self):
        from agentvault_registry.services import chat_federation as fed
        parts = [{"key": "me@https://ours.example"},
                 {"key": "them@https://theirs.example"},
                 {"key": "broken"}]
        assert fed._local_keys_from(parts, "https://ours.example") == ["me"]

    def test_no_local_participant_is_an_empty_list_not_a_guess(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed._local_keys_from([{"key": "them@https://theirs.example"}],
                                    "https://ours.example") == []


class TestPeerPublicForm:
    """The mTLS endpoint is NOT the address a chat delivery can land on."""

    def test_strips_the_federation_port(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed.public_form("https://op-abudhabi.op.theprotocol.cloud:8443") == \
            "https://op-abudhabi.op.theprotocol.cloud"

    def test_leaves_a_portless_peer_alone(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed.public_form("https://op-london.op.theprotocol.cloud") == \
            "https://op-london.op.theprotocol.cloud"

    def test_matches_what_a_remote_key_parses_to(self):
        # The two halves MUST agree, or a thread addressed to a peer would be
        # queued against an address the peer table does not recognise.
        from agentvault_registry.services import chat_federation as fed
        peer = fed.public_form("https://op-london.op.theprotocol.cloud:8443")
        assert fed.parse_remote_key(f"someone@{peer}")[1] == peer

    def test_refuses_a_hostless_or_bare_name(self):
        from agentvault_registry.services import chat_federation as fed
        assert fed.public_form("") == ""
        assert fed.public_form("localhost:8000") == ""   # no dot: not an address


# ---------------------------------------------------------------------------
# §OURSTATE-4 PULSE — moments from an attested record, never presence
# ---------------------------------------------------------------------------

class TestPulseTiers:
    def test_ladder_matches_the_earned_mark_collar(self):
        from agentvault_registry.services import pulse as pl
        assert [n for n, _ in pl.TIERS] == [
            "Proven", "Established", "Seasoned", "Veteran", "Expert", "Master", "Sovereign"]
        assert [t for _, t in pl.TIERS] == [1, 5, 10, 25, 50, 100, 250]

    def test_tier_for_picks_the_highest_reached(self):
        from agentvault_registry.services import pulse as pl
        assert pl.tier_for(0) is None
        assert pl.tier_for(1) == "Proven"
        assert pl.tier_for(4) == "Proven"
        assert pl.tier_for(5) == "Established"
        assert pl.tier_for(999) == "Sovereign"


class TestPulseMoments:
    def _s(self, **kw):
        base = {"jobs_verified": 0, "avg_stars": None, "cross_registry_jobs": 0,
                "distinct_hosts": 0, "last_verified_at": "2026-08-01T00:00:00+00:00"}
        base.update(kw)
        return base

    def test_no_record_no_moments(self):
        from agentvault_registry.services import pulse as pl
        assert pl.moments_from_summary("A", "did:x", self._s()) == []

    def test_a_verified_job_earns_the_first_tier_sentence(self):
        from agentvault_registry.services import pulse as pl
        m = pl.moments_from_summary("Caspian", "did:x", self._s(jobs_verified=1))
        assert len(m) == 1 and m[0]["kind"] == "tier"
        assert "Proven" in m[0]["text"] and "Caspian" in m[0]["text"]

    def test_every_moment_names_the_field_it_came_from(self):
        from agentvault_registry.services import pulse as pl
        m = pl.moments_from_summary("A", "did:x", self._s(
            jobs_verified=12, avg_stars=4.5, _starred=3, cross_registry_jobs=2, distinct_hosts=2))
        assert {x["kind"] for x in m} == {"tier", "stars", "cross_registry"}
        for x in m:
            assert x["source"].startswith("track_record."), x

    def test_stars_are_only_claimed_when_someone_actually_starred(self):
        """The producer sets `avg_stars` ONLY when at least one job was starred
        and deletes its `_starred` accumulator, so a null average IS the "nobody
        rated this" signal. The first version of this test passed `_starred=0`
        alongside a real average — a state the producer cannot emit — and so it
        certified a gate that could never fire at all."""
        from agentvault_registry.services import pulse as pl
        m = pl.moments_from_summary("A", "did:x", self._s(jobs_verified=3, avg_stars=None))
        assert not any(x["kind"] == "stars" for x in m)
        rated = pl.moments_from_summary("A", "did:x", self._s(jobs_verified=3, avg_stars=5.0))
        assert any(x["kind"] == "stars" for x in rated)

    def test_no_moment_ever_mentions_a_balance_or_presence(self):
        from agentvault_registry.services import pulse as pl
        m = pl.moments_from_summary("A", "did:x", self._s(
            jobs_verified=30, avg_stars=4.9, _starred=9, cross_registry_jobs=4, distinct_hosts=3))
        blob = " ".join(x["text"] for x in m).lower()
        for banned in ("balance", "online", "last seen", "typing", "active now", "earned "):
            assert banned not in blob, banned


class TestPulseReadsTheProducersKeys:
    """A CONTRACT test, not a coverage test.

    The pulse reads fields that services/track_record.py produces. Two ways
    that broke already, both silently:

      1. INVENTED NAMES. The first cut read `verified_jobs` / `last_job_at`;
         the producer emits `jobs_verified` / `last_verified_at`. Every summary
         read as empty and the feature said "nothing attested" about an agent
         that had just been paid five stars.
      2. DELETED KEYS. `_starred` IS in the producer's source — as an internal
         accumulator it deletes before returning (`del s["_star_sum"],
         s["_starred"]`). A gate that only checked the source text passed while
         the stars moment could never fire.

    So this asserts both: the name exists, AND the producer does not delete it.
    """

    READS = ("jobs_verified", "avg_stars", "cross_registry_jobs",
             "distinct_hosts", "last_verified_at")

    def _producer_source(self):
        import inspect
        from agentvault_registry.services import track_record
        return inspect.getsource(track_record)

    def _deleted_keys(self, src):
        """Every key removed by any `del s[...]`, including multi-target dels."""
        out = set()
        for stmt in re.findall(r"del\s+([^\n]+)", src):
            out.update(re.findall(r'\[\s*"([^"]+)"\s*\]', stmt))
        return out

    def test_the_gate_can_see_a_multi_target_del(self):
        """The gate below is worthless if it cannot parse the real statement."""
        assert self._deleted_keys('del s["a"], s["b"]') == {"a", "b"}

    def test_every_key_the_pulse_reads_exists_and_survives(self):
        src = self._producer_source()
        deleted = self._deleted_keys(src)
        for key in self.READS:
            assert f'"{key}"' in src, f"{key} is not a producer field"
            assert key not in deleted, f"{key} is deleted before the caller sees it"

    def test_no_read_key_is_an_internal_accumulator(self):
        """Control: the producer really does delete something, so the check
        above is answering a question that has a non-empty answer."""
        assert self._deleted_keys(self._producer_source())

    def test_every_moment_names_a_field_the_producer_actually_has(self):
        """A moment says which attested field it came from. If that name is not
        a real producer field the sentence is unverifiable — a citation to
        nothing. This asserts the citation, not just the prefix."""
        from agentvault_registry.services import pulse as pl
        src = self._producer_source()
        moments = pl.moments_from_summary("A", "did:x", {
            "jobs_verified": 7, "avg_stars": 4.8,
            "cross_registry_jobs": 2, "distinct_hosts": 2,
            "last_verified_at": "2026-08-01T00:00:00+00:00",
        })
        assert len(moments) == 3, [m["kind"] for m in moments]
        for m in moments:
            field = m["source"].split(".", 1)[1]
            assert f'"{field}"' in src, f'{m["source"]} names no producer field'


class TestContactPolicy:
    """§OURSTATE-5a — priced first contact.

    The pure half is the half that decides, so it is the half that is tested:
    `effective_policy` is asked by BOTH the create gate and the card, which is
    why a price can never be enforced by one and denied by the other.
    """

    def _cp(self):
        from agentvault_registry.services import contact_policy as cp
        return cp

    def test_open_is_the_default_and_stays_open(self):
        cp = self._cp()
        assert cp.effective_policy("open", None, None, None) == ("open", None)

    def test_a_price_needs_all_three_facts_to_be_in_force(self):
        cp = self._cp()
        import decimal
        d = decimal.Decimal("5")
        assert cp.effective_policy("priced", d, "BVT", "did:x") == ("priced", None)
        # Each missing fact falls back to OPEN and NAMES what is missing —
        # never to "refuse everyone", which would punish strangers for the
        # owner's misconfiguration.
        for price, cur, purse, why in (
            (d, "BVT", None, "no agent is named to receive it"),
            (None, "BVT", "did:x", "no amount is set"),
            (d, None, "did:x", "no currency is set"),
            (decimal.Decimal("0"), "BVT", "did:x", "no amount is set"),
        ):
            eff, reason = cp.effective_policy("priced", price, cur, purse)
            assert eff == "open", (price, cur, purse)
            assert reason == why

    def test_contacts_only_is_never_softened(self):
        """Unlike a price, `contacts` needs no configuration to be meaningful,
        so it is enforced exactly as declared."""
        cp = self._cp()
        assert cp.effective_policy("contacts", None, None, None) == ("contacts", None)

    def test_the_card_keeps_stated_and_enforced_apart(self):
        cp = self._cp()
        card = cp.genesis_card({
            "policy": "priced", "effective": "priced", "price": "5",
            "currency": "BVT", "purse_did": "did:x",
            "genesis": {"stated": "I answer within a day."},
        }, "ruFFa")
        assert card["type"] == "person.genesis"
        assert card["data"]["stated"] == "I answer within a day."
        labels = [c["label"] for c in card["data"]["enforced"]]
        assert any("5 BVT" in x for x in labels)
        # The free text is never promoted into the enforced register.
        assert not any("within a day" in x for x in labels)

    def test_an_inert_price_says_so_on_the_owners_own_card(self):
        cp = self._cp()
        card = cp.genesis_card({
            "policy": "priced", "effective": "open", "price": "5",
            "currency": "BVT", "purse_did": None,
            "inert_reason": "no agent is named to receive it", "genesis": None,
        }, "ruFFa")
        labels = [c["label"] for c in card["data"]["enforced"]]
        assert any("not in force" in x for x in labels)
        assert any("anyone may start a thread" in x for x in labels)


class TestFiatDoorGate:
    """§OURSTATE-5c — the card half of the fiat door.

    The lock lives in `services/fiat_door.py` (three conditions, a database
    read); what is testable purely — and what matters most — is that the
    validator cannot be talked into opening it by omission.
    """

    def _card(self):
        return {"v": 1, "type": "topup.offer",
                "data": {"amount": "20", "currency": "EUR"}}

    def test_an_unresolved_door_refuses(self):
        """The dangerous case: a caller that forgot to check. "Nobody asked"
        must never render as "allowed"."""
        r = cs.validate_card(self._card())
        assert r and "not resolved" in r

    def test_a_closed_door_refuses_with_its_own_reason(self):
        r = cs.validate_card(self._card(), fiat_door="this registry does not run a fiat onramp")
        assert r == "this registry does not run a fiat onramp"

    def test_only_the_open_sentinel_opens_it(self):
        assert cs.validate_card(self._card(), fiat_door=cs.FIAT_DOOR_OPEN) is None
        # A near-miss string is a refusal, not an approval.
        assert cs.validate_card(self._card(), fiat_door="open") is not None
        assert cs.validate_card(self._card(), fiat_door="") is not None

    def test_the_open_door_still_validates_the_card_body(self):
        bad = {"v": 1, "type": "topup.offer", "data": "not-an-object"}
        assert cs.validate_card(bad, fiat_door=cs.FIAT_DOOR_OPEN) is not None

    def test_other_later_phase_cards_keep_the_phase_wording(self):
        """The gate is about the fiat door specifically — an unbuilt card type
        must not start reporting a jurisdiction problem it does not have."""
        assert "topup.offer" in cs.LATER_PHASE_CARDS
        others = cs.LATER_PHASE_CARDS - {"topup.offer"}
        for t in others:
            r = cs.validate_card({"v": 1, "type": t, "data": {}})
            assert r and "later OurState phase" in r


class TestMediaCard:
    """§OURSTATE-5e — the media POINTER.

    The card must stay a reference. Every field that could carry content is
    refused here, because a card that can hold bytes is a card that will, and
    then a thread read costs whatever the sender felt like attaching.
    """

    def _c(self, **over):
        d = {"attachment_id": "att-1", "name": "invoice.pdf",
             "mime": "application/pdf", "bytes": 1234}
        d.update(over)
        return {"v": 1, "type": "media", "data": d}

    def test_a_well_formed_pointer_is_accepted(self):
        assert cs.validate_card(self._c()) is None

    def test_every_required_field_is_named_when_missing(self):
        for f in ("attachment_id", "name", "mime", "bytes"):
            c = self._c()
            del c["data"][f]
            r = cs.validate_card(c)
            assert r and f in r, f

    def test_bytes_must_be_a_positive_integer(self):
        assert cs.validate_card(self._c(bytes="1234")) is not None
        assert cs.validate_card(self._c(bytes=0)) is not None
        assert cs.validate_card(self._c(bytes=-1)) is not None

    def test_a_pointer_cannot_smuggle_content(self):
        """The actual attack: base64 in the card, or a url the client renders."""
        for banned in ("data", "content", "b64", "url", "src"):
            r = cs.validate_card(self._c(**{banned: "AAAA"}))
            assert r and banned in r, banned

    def test_media_is_client_postable_not_rail_only(self):
        """A person sends a file; no rail authors it on their behalf."""
        assert "media" in cs.CLIENT_POSTABLE_CARDS
        assert "media" not in cs.RAIL_ONLY_CARDS


class TestMediaGate:
    """The upload validator: an allowlist, magic numbers, and named refusals."""

    def _m(self):
        from agentvault_registry.services import chat_media
        return chat_media

    def test_svg_and_html_are_refused_by_name(self):
        m = self._m()
        assert "script" in m.NAMED_REFUSALS["image/svg+xml"].lower()
        assert "program" in m.NAMED_REFUSALS["text/html"].lower()

    def test_the_type_list_is_an_allowlist(self):
        m = self._m()
        # Anything not enumerated is refused — including types nobody has
        # thought of yet, which is the entire point.
        assert "image/svg+xml" not in m.ALLOWED_MIME
        assert "text/html" not in m.ALLOWED_MIME
        assert "application/octet-stream" not in m.ALLOWED_MIME
        assert set(m.ALLOWED_MIME) == {
            "image/png", "image/jpeg", "image/webp", "image/gif",
            "application/pdf", "text/plain"}

    def test_contents_are_sniffed_not_trusted(self):
        m = self._m()
        assert m._sniff(b"\x89PNG\r\n\x1a\n....") == "image/png"
        assert m._sniff(b"%PDF-1.7 ...") == "application/pdf"
        assert m._sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
        assert m._sniff(b"<svg xmlns=...") is None
        assert m._sniff(b"MZ\x90\x00") is None

    def test_filenames_cannot_escape_or_inject(self):
        m = self._m()
        assert "/" not in m.safe_filename("../../etc/passwd")
        assert ".." not in m.safe_filename("../../etc/passwd")
        assert "\\" not in m.safe_filename("..\\..\\windows\\system32")
        assert m.safe_filename("") == "file"
        assert "\x00" not in m.safe_filename("evil\x00.png")


class TestAppletCard:
    """§OURSTATE-5f — the declarative mini-app.

    The threat this card exists to survive is simple: an agent that can send UI
    can send a login form. So every test below is about what an applet CANNOT
    express, and the vocabulary being closed is the whole security argument.
    """

    def _a(self, **over):
        d = {"title": "Book a slot",
             "fields": [{"kind": "choice", "key": "day", "label": "Day",
                         "choices": ["Mon", "Tue"]},
                        {"kind": "text", "key": "note", "label": "Anything else?"}],
             "action": {"kind": "open_work", "label": "Open work"}}
        d.update(over)
        return {"v": 1, "type": "applet", "data": d}

    def test_a_well_formed_applet_is_accepted(self):
        assert cs.validate_card(self._a()) is None

    def test_markup_is_refused_by_name(self):
        for key in ("html", "markup", "script", "iframe", "style"):
            r = cs.validate_card(self._a(**{key: "<b>hi</b>"}))
            assert r is not None, key
        assert "markup" in cs.validate_card(self._a(html="<b>x</b>"))

    def test_links_are_refused_by_name(self):
        r = cs.validate_card(self._a(url="https://evil.example"))
        assert r and "link" in r

    def test_hidden_fields_are_refused_with_the_reason(self):
        r = cs.validate_card(self._a(hidden={"amount": "999"}))
        assert r and "cannot see" in r

    def test_the_field_vocabulary_is_closed(self):
        bad = self._a(fields=[{"kind": "file", "key": "f", "label": "Upload"}])
        r = cs.validate_card(bad)
        assert r and "vocabulary is closed" in r

    def test_the_action_list_is_closed(self):
        r = cs.validate_card(self._a(action={"kind": "POST /teg/transfer"}))
        assert r and "doors this app already has" in r

    def test_an_amount_without_a_currency_is_refused(self):
        """The §FOREIGNACT rule reaches applets too: three currencies live
        here, so a bare number is not an amount."""
        r = cs.validate_card(self._a(action={"kind": "open_pay", "amount": "20"}))
        assert r and "currency" in r
        assert cs.validate_card(
            self._a(action={"kind": "open_pay", "amount": "20", "currency": "BVT"})) is None

    def test_bounds_are_enforced(self):
        many = [{"kind": "text", "key": f"k{i}", "label": "x"} for i in range(9)]
        assert cs.validate_card(self._a(fields=many)) is not None
        assert cs.validate_card(self._a(title="")) is not None
        assert cs.validate_card(self._a(title="x" * 200)) is not None

    def test_duplicate_keys_are_refused(self):
        dup = [{"kind": "text", "key": "a", "label": "one"},
               {"kind": "text", "key": "a", "label": "two"}]
        r = cs.validate_card(self._a(fields=dup))
        assert r and "duplicate" in r

    def test_an_applet_needs_exactly_one_action(self):
        d = self._a()
        del d["data"]["action"]
        assert cs.validate_card(d) is not None


class TestReceiptArrival:
    """§OURSTATE-6 — a receipt that states an arrival states its unit.

    The 2026-08-24 send debited 102 BVT and credited 85.709085 AVT. A receipt
    that carried the arrival NUMBER without the arrival CURRENCY would be the
    §FOREIGNACT defect reappearing on the one card the recipient reads.
    """

    def _r(self, **over):
        d = {"amount": "102", "currency": "BVT", "method": "fx"}
        d.update(over)
        return {"v": 1, "type": "pay.receipt", "data": d}

    def test_a_plain_receipt_still_validates(self):
        assert cs.validate_card(self._r()) is None

    def test_an_arrival_amount_without_a_currency_is_refused(self):
        r = cs.validate_card(self._r(received_amount="85.709085"))
        assert r and "currency" in r

    def test_both_halves_together_validate(self):
        assert cs.validate_card(
            self._r(received_amount="85.709085", received_currency="AVT")) is None

    def test_a_currency_alone_is_harmless(self):
        """Only the number needs the unit; a unit with no number says nothing
        false, so it is not worth a refusal."""
        assert cs.validate_card(self._r(received_currency="AVT")) is None
