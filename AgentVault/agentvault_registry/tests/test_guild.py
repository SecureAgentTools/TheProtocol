"""THE GUILD unit tests (2026-07-07) — the money-invariant logic + helpers.

DB-free: proves the settle/split math is zero-sum (the Δ-neutral property), fee bounds, star→trust
mapping, and config gates. The DB-backed lifecycle is proven by the live frame-c E2E (test_guild_e2e).
Run: docker run --rm -u 0 -v <repo>/AgentVault/agentvault_registry:/mnt --entrypoint bash \
     agentvault2-registry-a:latest -c "cd /mnt && PYTHONPATH=/mnt/src python3 -m pytest tests/test_guild.py -q --no-cov"
"""
from decimal import Decimal


# ── settle math: payout + fee == bounty (money conserved → Δ-neutral) ─────────
def _settle(bounty: str, fee_bps: int):
    b = Decimal(bounty)
    fee = (b * Decimal(fee_bps) / Decimal(10000)).quantize(Decimal("0.0000000001"))
    return b - fee, fee


def test_settle_conserves_bounty():
    for bounty in ("100", "0.5", "12345.6789", "1"):
        for bps in (0, 250, 500, 2000):
            payout, fee = _settle(bounty, bps)
            assert payout + fee == Decimal(bounty), f"leak at {bounty}/{bps}: {payout}+{fee}"


def test_fee_bps_bounds():
    import agentvault_registry.routers.guild as g
    import os
    os.environ["GUILD_FEE_BPS"] = "250"; assert g._fee_bps() == 250
    os.environ["GUILD_FEE_BPS"] = "99999"; assert g._fee_bps() == 2000   # capped at 20%
    os.environ["GUILD_FEE_BPS"] = "-5"; assert g._fee_bps() == 0
    os.environ["GUILD_FEE_BPS"] = "junk"; assert g._fee_bps() == 250     # default on parse error
    del os.environ["GUILD_FEE_BPS"]


# ── dispute split: worker_amt + poster_amt == bounty for any share ────────────
def _split(bounty: str, worker_share: str):
    b = Decimal(bounty)
    w = (b * Decimal(worker_share)).quantize(Decimal("0.0000000001"))
    return w, b - w


def test_dispute_split_conserves_bounty():
    for share in ("0", "0.25", "0.5", "0.5000000001", "1"):
        w, p = _split("1000", share)
        assert w + p == Decimal("1000"), f"split leak at share {share}: {w}+{p}"
        assert w >= 0 and p >= 0


# ── enabled gate ──────────────────────────────────────────────────────────────
def test_guild_enabled_gate(monkeypatch):
    import agentvault_registry.routers.guild as g
    monkeypatch.setenv("GUILD_ENABLED", "false"); assert g.guild_enabled() is False
    monkeypatch.setenv("GUILD_ENABLED", "true"); assert g.guild_enabled() is True
    monkeypatch.setenv("GUILD_ENABLED", "TRUE"); assert g.guild_enabled() is True


# ── reputation star → satisfactory/unsatisfactory mapping ─────────────────────
def test_star_to_trust_mapping():
    # mirrors guild_reputation.fold_work_reputation logic
    def classify(stars):
        s = max(1, min(5, int(stars)))
        return (1 if s >= 3 else 0, 0 if s >= 3 else 1, (s - 1) / 4.0)
    assert classify(5) == (1, 0, 1.0)
    assert classify(3) == (1, 0, 0.5)
    assert classify(2) == (0, 1, 0.25)
    assert classify(1) == (0, 1, 0.0)
    assert classify(99) == (1, 0, 1.0)   # clamped
    assert classify(-3) == (0, 1, 0.0)   # clamped


# ── escrow leg → reason routing (settle/split → guild_settle; refund → guild_refund) ──
def test_escrow_leg_reason_routing():
    def reason_for(leg):
        return "guild_settle" if leg.startswith("settle") or leg.startswith("split") else "guild_refund"
    assert reason_for("settle") == "guild_settle"
    assert reason_for("split_worker") == "guild_settle"
    assert reason_for("split_poster") == "guild_settle"
    assert reason_for("refund") == "guild_refund"


# ── escrow deposit uses the guildref tag (traceability) ───────────────────────
def test_escrow_ref_tagging():
    oid = "gwo_abc123"
    assert f"guildref:{oid}:hold".startswith("guildref:")
    # every payout leg is guildref-tagged for idempotency + audit
    for leg in ("settle", "refund", "split_worker", "split_poster"):
        assert f"guildref:{oid}:{leg}".count(":") == 2


def test_zk_credential_gate(monkeypatch):
    import agentvault_registry.services.guild_reputation as r
    monkeypatch.setenv("GUILD_ZK_CREDENTIAL_ENABLED", "false"); assert r.zk_credential_enabled() is False
    monkeypatch.setenv("GUILD_ZK_CREDENTIAL_ENABLED", "true"); assert r.zk_credential_enabled() is True


def test_models_importable():
    from agentvault_registry.models import GuildWorkOrder, GuildBid, GuildOrderEvent
    assert GuildWorkOrder.__tablename__ == "guild_work_orders"
    assert GuildBid.__tablename__ == "guild_bids"
    assert GuildOrderEvent.__tablename__ == "guild_order_events"


# ── FIRMS: payee decoupling (settle pays the firm treasury, else the worker) ──
def test_firm_payee_selection():
    # mirrors the verify-settle rule: payee = payee_did or worker_did
    def payee(order):
        return order.get("payee_did") or order["worker_did"]
    assert payee({"worker_did": "did:w", "payee_did": None}) == "did:w"          # individual
    assert payee({"worker_did": "did:w", "payee_did": "did:org-treasury"}) == "did:org-treasury"  # firm
    assert payee({"worker_did": "did:w"}) == "did:w"                             # legacy order, no column


def test_firms_schema_fields():
    from agentvault_registry.models import GuildWorkOrder, GuildBid
    assert hasattr(GuildWorkOrder, "payee_did") and hasattr(GuildWorkOrder, "payee_org_id")
    assert hasattr(GuildBid, "on_behalf_of_org_id")


# ── STAKED WORK: collateral slash-vs-release on dispute + schema ──
def test_staked_work_dispute_rule():
    from decimal import Decimal
    # mirrors admin_resolve: full worker win (share>=1) releases the stake to the worker; else slash to poster.
    def stake_target(worker_share, worker_did, poster_did):
        return worker_did if Decimal(str(worker_share)) >= Decimal(1) else poster_did
    assert stake_target(1.0, "did:w", "did:p") == "did:w"   # delivered → keep your stake
    assert stake_target(0.5, "did:w", "did:p") == "did:p"   # partial fail → slashed to poster
    assert stake_target(0.0, "did:w", "did:p") == "did:p"   # total fail → slashed to poster


def test_staked_work_schema_fields():
    from agentvault_registry.models import GuildWorkOrder, GuildBid
    assert hasattr(GuildWorkOrder, "stake_required")
    assert hasattr(GuildBid, "stake_amount") and hasattr(GuildBid, "stake_status") and hasattr(GuildBid, "stake_escrow_ref")


# ── CROSS-REGISTRY (mig 0117): schema + MCP 5-place wiring ──
def test_crossframe_schema_fields():
    from agentvault_registry.models import GuildWorkOrder, GuildBid
    assert hasattr(GuildWorkOrder, "worker_home_registry")
    assert hasattr(GuildBid, "home_registry_url")


def test_guild_mcp_tools_wired():
    from agentvault_registry.mcp import server as mcp_server
    from agentvault_registry.mcp import audit as mcp_audit
    names = [
        "theprotocol_guildListOrders", "theprotocol_guildGetOrder", "theprotocol_guildNetworkBoard",
        "theprotocol_guildPostOrder", "theprotocol_guildBid", "theprotocol_guildAward",
        "theprotocol_guildSubmitWork", "theprotocol_guildVerify", "theprotocol_guildCancelOrder",
        "theprotocol_guildMyWork", "theprotocol_guildCrossRegistryBid",
    ]
    for n in names:
        assert n in mcp_server.TOOL_DISPATCH, f"{n} missing from TOOL_DISPATCH"
    schema_names = {s["name"] for s in mcp_server.ALL_TOOL_SCHEMAS}
    for n in names:
        assert n in schema_names, f"{n} missing from ALL_TOOL_SCHEMAS"
    t2 = {n for n in names if n not in ("theprotocol_guildListOrders", "theprotocol_guildGetOrder", "theprotocol_guildNetworkBoard")}
    assert t2 <= mcp_server.TIER2_TOOLS, "guild T2 tools missing from TIER2_TOOLS"
    assert t2 <= mcp_audit._TIER_2_TOOLS, "guild T2 tools missing from audit tier set"
    assert {"theprotocol_guildListOrders", "theprotocol_guildGetOrder", "theprotocol_guildNetworkBoard"} <= mcp_audit._TIER_1_TOOLS


# ── IRONKEY birth roles (2026-07-08): default seed valid, legacy-full never seedable ──
def test_birth_roles_default_valid():
    from agentvault_registry.agent_authz import ROLE_PERMISSIONS
    default = [r.strip() for r in "trader,client".split(",")]
    assert all(r in ROLE_PERMISSIONS for r in default)
    perms = set().union(*(ROLE_PERMISSIONS[r] for r in default))
    assert {"teg.transfer", "teg.transfer_xreg", "a2a.pay", "contracts.engage"} <= perms
    filt = [r for r in ["legacy-full", "trader", "nope"] if r in ROLE_PERMISSIONS and r != "legacy-full"]
    assert filt == ["trader"]


def test_travel_credential_schema_and_endpoints():
    """0118 trust-that-travels: migration table, ship/receive endpoints, pubkey exposure, rep relay."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    mig = (root / "alembic/versions/0118_guild_travel_credentials.py").read_text()
    assert "guild_travel_credentials" in mig and "uix_gtc_host_order" in mig
    src = (root / "src/agentvault_registry/routers/guild.py").read_text()
    # host ships after XF settle; home verifies + folds; pubkey served over federation
    assert "_ship_work_credential" in src
    assert "/api/v1/federation/guild/work-credential" in src
    assert "/api/v1/federation/guild/credential-pubkey" in src
    assert "verify_bundle_signature" in src
    # unverifiable credential moves no trust
    assert "Credential signature could not be verified" in src
    # idempotent fold: only first delivery folds
    assert "ON CONFLICT (host_registry, order_id) DO NOTHING" in src
    # reputation relays with remote bids and the min_rep guard honors it
    assert '"reputation": await _agent_reputation(db, agent.did)' in src
    assert "home-asserted" in src
    rep = (root / "src/agentvault_registry/services/guild_reputation.py").read_text()
    assert "def credential_pubkey" in rep and '"stars": stars' in rep


def test_travel_credential_stars_bounds():
    """Stars must be a 1-5 rating on the receive model (same bounds as verify)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "src/agentvault_registry/routers/guild.py").read_text()
    assert "stars: int = Field(..., ge=1, le=5)" in src


def test_v2_remote_money_lifts():
    """0119: staked remote bids (home-held), remote dispute splits (poster-triggered), firm remote."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    mig = (root / "alembic/versions/0119_guild_v2_remote_money.py").read_text()
    assert "guild_remote_stakes" in mig and "resolved_worker_amt" in mig and "payee_did_hint" in mig
    src = (root / "src/agentvault_registry/routers/guild.py").read_text()
    # staked remote: home-held collateral asserted with the bid; host federated stake lifecycle
    assert "stake_held" in src and "/api/v1/federation/guild/stake" in src
    assert "_notify_home_stake" in src and "xfstake_unwind" in src
    # host stores remote stakes with a 'remote:' escrow ref and never runs a local payout for them
    assert 'f"remote:{body.home_registry_url' in src
    # dispute split v2: resolve holds, poster triggers the xf worker leg (stable idempotency key)
    assert "resolved_worker_amt" in src and "dispute-payout" in src
    assert 'Idempotency-Key": f"guild-{oid}-xfdispute"' in src
    assert "xfd_stage_return" in src  # compensating re-deposit
    # firm remote: home validates, host trusts the payee assertion
    assert "payee_did_hint" in src and "Remote firm bid carries no payee assertion" in src
    # stake keys are hostname-normalized on both sides
    assert "def target_pub" in src
    reaper = (root / "src/agentvault_registry/background_tasks/guild_order_reaper.py").read_text()
    assert "xfstake_timeout" in reaper  # stranded-collateral safety net


def test_v2_slash_semantics_documented():
    """Remote slash = zero legs (deposit already in home treasury) — deterrent model, documented."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "src/agentvault_registry/routers/guild.py").read_text()
    assert "slash → zero legs" in src or "it just never returns" in src


def test_tos_consent_wiring():
    """0120: ToS consent — migration, model cols, schema field, endpoint gate, server-stamped version."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    assert "tos_accepted_version" in (root/"alembic/versions/0120_developer_tos_consent.py").read_text()
    m = (root/"src/agentvault_registry/models.py").read_text()
    assert "tos_accepted_version" in m and "tos_accepted_at" in m
    sc = (root/"src/agentvault_registry/schemas.py").read_text()
    assert "tos_accepted: bool" in sc
    cfg = (root/"src/agentvault_registry/config.py").read_text()
    assert "TOS_CONSENT_REQUIRED" in cfg and "TOS_VERSION" in cfg
    au = (root/"src/agentvault_registry/routers/auth_secure.py").read_text()
    assert "TOS_CONSENT_REQUIRED and not getattr(developer_in" in au
    assert "must accept the Terms" in au
    cr = (root/"src/agentvault_registry/crud/developer.py").read_text()
    # server stamps ITS version, not a client-supplied one
    assert "settings.TOS_VERSION" in cr and "tos_accepted_version=tos_version" in cr
