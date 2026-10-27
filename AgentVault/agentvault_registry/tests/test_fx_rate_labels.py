"""§BATCH9 (2026-09-06, §BATCH7 residue) — /fx/rate named every pair AVT/BVT.

On the JUICE/BRRR pool the public rate carried `pair: "AVT/BVT"` and the two sides swapped. The
payload now names the currencies actually on each side; the legacy avt_per_bvt/bvt_per_avt keys
survive ONLY on a real AVT/BVT pool, with the exact pre-fix arithmetic (the control that the
production bridge is unchanged), and are omitted anywhere they would be a lie."""
from decimal import Decimal

from agentvault_registry.routers.teg_integration import _fx_pool_payload


def test_a_non_avt_pair_is_named_honestly_and_carries_no_legacy_keys():
    p = _fx_pool_payload("JUICE", "BRRR", Decimal("100010"), Decimal("99990.050995"), "t")
    assert p["pair"] == "JUICE/BRRR" and p["local_currency"] == "JUICE" and p["peer_currency"] == "BRRR"
    assert Decimal(p["local_per_peer"]) == (Decimal("100010") / Decimal("99990.050995")).quantize(Decimal("0.000001"))
    assert Decimal(p["peer_per_local"]) == (Decimal("99990.050995") / Decimal("100010")).quantize(Decimal("0.000001"))
    assert "avt_per_bvt" not in p and "bvt_per_avt" not in p


def test_the_avt_bvt_pool_keeps_the_legacy_keys_with_the_old_arithmetic_on_both_frames():
    # frame A: local AVT — x = local (AVT), y = dest (BVT); avt_per_bvt == local_per_peer
    a = _fx_pool_payload("AVT", "BVT", Decimal("3000000"), Decimal("1000000"), "t")
    assert a["pair"] == "AVT/BVT" and a["avt_per_bvt"] == "3.000000" and a["bvt_per_avt"] == "0.333333"
    assert a["local_per_peer"] == a["avt_per_bvt"]
    # frame C: local BVT — x = dest (AVT), y = local (BVT); avt_per_bvt == peer_per_local, exactly as before
    c = _fx_pool_payload("BVT", "AVT", Decimal("1000000"), Decimal("3000000"), "t")
    assert c["pair"] == "BVT/AVT" and c["avt_per_bvt"] == "3.000000" and c["bvt_per_avt"] == "0.333333"
    assert c["peer_per_local"] == c["avt_per_bvt"] and c["local_per_peer"] == "0.333333"
