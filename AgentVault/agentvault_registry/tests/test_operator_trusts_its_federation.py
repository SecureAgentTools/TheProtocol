"""§MTLSGAP row 199 — an operator must trust the frame its own frame is federated with.

`TRUSTED_SPIFFE_DOMAINS` was written from a literal naming the 2026-07 federation
(`agentvault.com,frame-b…,frame-c…`). EU and ASIA were stood up without setting
`FRAME_TRUST_DOMAINS`, so every operator was born trusting three RETIRING frames and not its
peer. Measured on amsterdam: `spiffe://asia.theprotocol.cloud/service/registry` refused as an
untrusted domain once a minute since standup, and — because the mode falls through — reported
as *"Invalid or revoked federation license"*, a 403 that blames the wrong half.

The control that makes these tests worth having is the first one: with no live peer rows the
answer is exactly the old answer, so a green here is not the fixture agreeing with itself.
"""
import pytest

from agentvault_registry.services.cloud_provisioner import federation_trust_domains

LEGACY = "agentvault.com,frame-b.theprotocol.cloud,frame-c.theprotocol.cloud"


class _Rows:
    def __init__(self, values): self._v = values
    def scalars(self): return self
    def all(self): return list(self._v)


class _DB:
    """Answers the one select the helper makes; `raises=True` is the unreadable case."""
    def __init__(self, values, raises=False): self._v, self._raises = values, raises
    async def execute(self, _stmt):
        if self._raises:
            raise RuntimeError("peer rows unreadable")
        return _Rows(self._v)


@pytest.mark.asyncio
async def test_without_live_peers_the_answer_is_the_old_answer():
    """THE CONTROL. No peer rows ⇒ exactly what the literal produced before this fix. If this
    ever changes, the other tests below are measuring the fixture, not the fix."""
    got = await federation_trust_domains(
        _DB([]), own_td="eu.theprotocol.cloud",
        partner_td="frame-b.theprotocol.cloud", declared=LEGACY)
    assert got == ["eu.theprotocol.cloud", "frame-b.theprotocol.cloud",
                   "agentvault.com", "frame-c.theprotocol.cloud"]
    assert "asia.theprotocol.cloud" not in got   # the defect, reproduced


@pytest.mark.asyncio
async def test_the_live_peer_frame_is_trusted():
    """THE FIX. EU is federated with ASIA, so an operator EU provisions must accept ASIA's SVID."""
    got = await federation_trust_domains(
        _DB(["asia.theprotocol.cloud"]), own_td="eu.theprotocol.cloud",
        partner_td="frame-b.theprotocol.cloud", declared=LEGACY)
    assert "asia.theprotocol.cloud" in got
    assert got[0] == "eu.theprotocol.cloud", "own frame stays first"


@pytest.mark.asyncio
async def test_it_only_ever_widens():
    """Every domain the old expression produced must survive — an operator can never be born
    trusting LESS than it does today, whatever the peer rows say."""
    old = await federation_trust_domains(
        _DB([]), own_td="eu.theprotocol.cloud",
        partner_td="frame-b.theprotocol.cloud", declared=LEGACY)
    new = await federation_trust_domains(
        _DB(["asia.theprotocol.cloud"]), own_td="eu.theprotocol.cloud",
        partner_td="frame-b.theprotocol.cloud", declared=LEGACY)
    assert set(old) <= set(new)


@pytest.mark.asyncio
async def test_unreadable_peer_rows_do_not_narrow():
    """UNKNOWN IS NOT EMPTY. If the rows cannot be read, keep the declared set — never collapse
    an operator's trust to its own frame because a probe could not see."""
    got = await federation_trust_domains(
        _DB([], raises=True), own_td="eu.theprotocol.cloud",
        partner_td="frame-b.theprotocol.cloud", declared=LEGACY)
    assert "agentvault.com" in got and "frame-c.theprotocol.cloud" in got
    assert got[0] == "eu.theprotocol.cloud"


@pytest.mark.asyncio
async def test_no_duplicates_and_no_blanks():
    """A frame whose partner literal IS its live peer must not list it twice, and an empty
    declared string must not write a trailing empty domain."""
    got = await federation_trust_domains(
        _DB(["asia.theprotocol.cloud", "asia.theprotocol.cloud", "  "]),
        own_td="eu.theprotocol.cloud", partner_td="asia.theprotocol.cloud", declared="")
    assert got == ["eu.theprotocol.cloud", "asia.theprotocol.cloud"]
