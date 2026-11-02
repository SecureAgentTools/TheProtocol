"""V0653 (am), item 5 (the hardening list in the sessions' room): a trust domain is compared whole, never by a substring.

Each site, after reading what its answer decides. consul_admin._infer_frame_from_trust_domain gives the CONSUL admin page a
frame letter (a display): "frame-b" in td let a look-alike domain wear Frame B's letter. BASE (a5ef48ddd, V0652): the
look-alikes read B, C or A.
"""
from __future__ import annotations

import pytest

from agentvault_registry.routers import consul_admin as ca


@pytest.mark.parametrize("td,letter", [
    ("agentvault.com", "A"), ("frame-b.theprotocol.cloud", "B"), ("frame-c.theprotocol.cloud", "C"),
    ("FRAME-B.theprotocol.cloud", "B"), ("frame-c.theprotocol.cloud.", "C"), (" agentvault.com ", "A"),
])
def test_the_live_trust_domains_keep_their_letters(td, letter):
    assert ca._infer_frame_from_trust_domain(td) == letter


@pytest.mark.parametrize("td", [
    "evil-frame-b.example", "frame-b.theprotocol.cloud.evil.test", "notagentvault.com", "agentvault.com.evil.test",
    "frame-c", "eu.theprotocol.cloud", "", None,
])
def test_a_look_alike_or_another_domain_reads_unknown(td):
    assert ca._infer_frame_from_trust_domain(td) == "?"


# services/spiffe_canonical._trust_domain_to_frame resolves a peer's cluster frame letter (resolve_frame_via_peers and the
# card stamps' canonical form): the same table; an unknown domain is None, "not a cluster frame"
from agentvault_registry.services import spiffe_canonical as sc   # noqa: E402


@pytest.mark.parametrize("td,letter", [
    ("agentvault.com", "A"), ("frame-b.theprotocol.cloud", "B"), ("Frame-C.theprotocol.cloud", "C"),
    ("evil-frame-b.example", None), ("frame-b.theprotocol.cloud.evil.test", None), ("notagentvault.com", None),
    ("eu.theprotocol.cloud", None), ("", None), (None, None),
])
def test_the_canonical_frame_letter_reads_the_whole_domain(td, letter):
    assert sc._trust_domain_to_frame(td) == letter


def test_one_table_for_both():
    assert ca._TD_FRAME is sc.CLUSTER_TRUST_DOMAINS
