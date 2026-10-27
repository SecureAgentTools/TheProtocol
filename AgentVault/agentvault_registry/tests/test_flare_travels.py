"""§FLARETRAVEL — a peer's own flare must not be dropped as an echo from a stranger.

MEASURED ON THE LIVE PAIR. Shadowban Sheldon wears a shadow_chancellor encirclement and a rank
overlay on EU, set deliberately. On ASIA the same mirrored card rendered a plain avatar: the
encirclement and the overlay were gone, while the rank TEXT and the earned collar were fine, which
is what made it easy to miss.

The ingest's echo-prevent compares the flare's claimed `source_registry` against the peer that
delivered it, using canonical_equals — which compares (trust_domain, NAME). `_build_flare_sidecar`
stamps that field from the registry's own SVID, and on this cluster that is still the legacy
`spiffe://<td>/ns/agentvault/sa/registry-main` template. So:

    flare origin  spiffe://eu.theprotocol.cloud/ns/agentvault/sa/registry-main -> ('eu…', 'main')
    peer svid     spiffe://eu.theprotocol.cloud/registry/EU                    -> ('eu…', 'eu')

Equal registries, different labels, verdict "not the immediate peer and not any active trusted
peer" — and the flare was stripped. Doctrine already carries this rule for a different surface:
never derive a peer's identity from that legacy string; the trust domain is the identity.

Accepting on a matching trust domain widens nothing, which is what the control here pins.
"""
from agentvault_registry.services.spiffe_canonical import extract_canonical

LEGACY_EU = "spiffe://eu.theprotocol.cloud/ns/agentvault/sa/registry-main"
PEER_EU = "spiffe://eu.theprotocol.cloud/registry/EU"
FOREIGN = "spiffe://evil.example.com/ns/agentvault/sa/registry-main"


def test_the_name_segment_is_why_it_was_dropped():
    """Pin the CAUSE, so a future reader does not re-derive it from the symptom."""
    f, p = extract_canonical(LEGACY_EU), extract_canonical(PEER_EU)
    assert f[0] == p[0] == "eu.theprotocol.cloud", "same registry by trust domain"
    assert f[1] != p[1], "different name segment — this is the whole bug"


def test_same_trust_domain_is_accepted():
    f, p = extract_canonical(LEGACY_EU), extract_canonical(PEER_EU)
    assert f[0] and f[0] == p[0]


def test_a_foreign_origin_is_still_refused():
    """THE CONTROL. The echo-prevent exists to stop a peer injecting a flare it did not stamp.
    Matching on the trust domain must not open that door."""
    f, p = extract_canonical(FOREIGN), extract_canonical(PEER_EU)
    assert f[0] != p[0], "a foreign trust domain must not match"


def test_the_ingest_consults_the_trust_domain():
    """Pin the call site. The helper being right has never been the problem in this program."""
    import inspect
    from agentvault_registry.crud import crud_peer_registry as c
    src = inspect.getsource(c)
    i_eq = src.find("_canon_eq_flare(_flare_origin, peer_svid)")
    assert i_eq != -1, "the echo-prevent must still compare against the delivering peer"
    tail = src[i_eq:i_eq + 1800]
    assert "_fo[0] == _po[0]" in tail, (
        "a flare whose origin shares the peer's TRUST DOMAIN must be accepted; comparing only "
        "the name segment drops a peer's own flare when the SVID uses the legacy template"
    )
