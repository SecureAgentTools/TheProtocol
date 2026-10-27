"""§FRAMELIC (2026-09-07) — gates for the three rails this batch adds.

His word: *"frames get a license from new eu frame when stood up so already test this here …
showcase shows its own agents … we also need an option to hide system agents like eigentrust sim
agents fx router etc from discovery."*

Each gate has a CONTROL that fails on the pre-fix shape, because a gate that cannot fail measures
nothing (PART 1). The structural gates read the AST rather than the text: a `grep` for
`_issue_frame_license` would pass on a call sitting in a comment or in the wrong function, and the
wrong-function case is exactly the mistake this batch made once and pyflakes caught.
"""
import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def _tree(rel: str) -> ast.Module:
    return ast.parse((SRC / rel).read_text(encoding="utf-8"))


def _func(tree: ast.AST, name: str):
    """The FUNCTION named `name`, anywhere in the tree (these live inside a factory)."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _calls(node) -> set:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ---------------------------------------------------------------------------
# 1. The frame licence is issued INSIDE approve, and the key reaches the peer
# ---------------------------------------------------------------------------

def test_approve_issues_the_frame_licence_itself():
    """The licence must be minted in `approve_frame_invitation`, not in `finalize`.

    This gate exists because the first cut of this change landed the call in `finalize` — which
    reads almost identically at the anchor line and has no `current_admin` — and only pyflakes'
    undefined-name pass noticed. A gate on the file would have passed.
    """
    tree = _tree("routers/frame_invitations.py")
    approve = _func(tree, "approve_frame_invitation")
    assert "_issue_frame_license" in _calls(approve), (
        "approve_frame_invitation must issue the joining frame's licence as part of the handshake"
    )
    finalize = _func(tree, "finalize_frame_invitation")
    assert "_issue_frame_license" not in _calls(finalize), (
        "finalize runs on the JOINING side — it has no admin and no authority to issue a licence"
    )


def test_the_plain_key_is_carried_to_the_peer_and_shown_once():
    """A key nobody receives is a licence nobody can present."""
    src = (SRC / "routers/frame_invitations.py").read_text(encoding="utf-8")
    # §FEDLICENCE (2026-09-28): the call may carry the network licence after these arguments (**_deliver)
    assert "_post_bilateral_finalize(inv, our_bundle_result[0], license_key, initiator_bundle_body=bundle_body" in src, (
        "the approve path must hand the plain key to the /finalize callback"
    )
    assert '"federation_license_key": license_key' in src, (
        "the approving admin must see the key once, in case the callback did not land"
    )
    # the receiving side echoes what it was handed, exactly once
    finalize = _func(_tree("routers/frame_invitations.py"), "finalize_frame_invitation")
    body = ast.unparse(finalize)
    assert "issued_license_key" in body and "federation_license_key" in body


def test_finalize_schema_accepts_the_key_and_stays_optional():
    """Optional, so an approver on an older image still completes the handshake."""
    from agentvault_registry.schemas import FrameInvitationFinalize
    f = FrameInvitationFinalize.model_fields
    assert "federation_license_key" in f
    assert f["federation_license_key"].default is None, (
        "a frame that is handed no key must still federate — that is the pre-0176 state"
    )


# ---------------------------------------------------------------------------
# 2. licensee_type — the discriminator, and the refusal it buys
# ---------------------------------------------------------------------------

def test_licence_model_carries_licensee_type_defaulting_to_operator():
    from agentvault_registry.models import FederationLicense
    col = FederationLicense.__table__.c.licensee_type
    assert col.nullable is False
    assert "operator" in str(col.server_default.arg), (
        "every pre-0176 row IS an operator licence; that is what the backfill must say"
    )


@pytest.mark.asyncio
async def test_require_licensee_type_refuses_the_wrong_class():
    """An operator key presented on a frame rail is a LIVE key doing a job it was not issued for."""
    from fastapi import HTTPException
    from agentvault_registry.routers.federation_licenses import require_licensee_type

    class _Lic:
        licensee_type = "operator"
        operator_name = "cloud-op-amsterdam"

    dep = require_licensee_type("frame")
    with pytest.raises(HTTPException) as ei:
        await dep(federation_license=_Lic())
    assert ei.value.status_code == 403
    assert "licensee_type_mismatch" in str(ei.value.detail)

    # ... and the matching class passes through untouched
    _Lic.licensee_type = "frame"
    assert await dep(federation_license=_Lic()) is not None


@pytest.mark.asyncio
async def test_a_row_written_before_the_migration_reads_as_an_operator():
    """CONTROL for the backfill: an object with NO licensee_type attribute at all
    must be treated as an operator licence, never rejected outright."""
    from agentvault_registry.routers.federation_licenses import require_licensee_type

    class _OldRow:            # no licensee_type attribute — a pre-0176 row
        operator_name = "cloud-op-london"

    dep = require_licensee_type("operator")
    assert await dep(federation_license=_OldRow()) is not None


# ---------------------------------------------------------------------------
# 3. Service accounts hide their agents
# ---------------------------------------------------------------------------

def test_developer_carries_the_service_account_flag():
    from agentvault_registry.models import Developer
    col = Developer.__table__.c.agents_unlisted_by_default
    assert col.nullable is False
    assert "false" in str(col.server_default.arg).lower()


def test_card_creation_reads_the_flag_off_the_owning_developer():
    """The stamp must come from the OWNER, so an account that gains an agent tomorrow
    is covered without anyone remembering at the mint site."""
    create = _func(_tree("crud/agent_card.py"), "create_agent_card")
    body = ast.unparse(create)
    assert "agents_unlisted_by_default" in body
    assert "unlisted=_unlisted_at_birth" in body, (
        "the AgentCard row must actually receive the flag — reading it and not passing it "
        "is the dead-branch class"
    )


def test_the_stamp_cannot_block_a_mint():
    """CONTROL: if the owner read raises, the card is still created — LISTED.
    A hidden-by-accident agent is a support ticket; a mint that fails is an outage."""
    create = _func(_tree("crud/agent_card.py"), "create_agent_card")
    body = ast.unparse(create)
    i = body.index("_unlisted_at_birth = False")
    j = body.index("db_agent_card = models.AgentCard")
    window = body[i:j]
    assert "try:" in window and "except" in window, "the owner read must be guarded"
    assert window.index("_unlisted_at_birth = False") < window.index("try:"), (
        "the safe default must be bound BEFORE the guarded read, or the except path "
        "raises NameError instead of falling back"
    )


# ---------------------------------------------------------------------------
# 4. The showcase catalog belongs to the frame
# ---------------------------------------------------------------------------

def test_showcase_catalog_is_overridable_and_refuses_a_broken_one():
    src = (SRC / "main.py").read_text(encoding="utf-8")
    assert "SHOWCASE_CATALOG_JSON" in src
    i = src.index("_catalog_raw = ")
    window = src[i:i + 2600]
    assert "_SHOWCASE_DIDS = _dids" in window and "_SHOWCASE_AGENTS = _agents" in window, (
        "the override must replace BOTH maps — a DID map from Frame A beside this frame's "
        "endpoints is the mixture that is worse than either"
    )
    assert "raise ValueError" in window, "a malformed entry must refuse, not half-apply"
    assert "the showcase stays on the built-in catalog" in window


def test_showcase_prices_fall_back_to_this_frames_currency():
    """A literal 'AVT' fallback labelled ECU prices as AVT on the EU frame."""
    src = (SRC / "main.py").read_text(encoding="utf-8")
    assert 'card_price.get(key, (info["price"], local_ccy))' in src
    assert 'card_price.get(key, (info["price"], "AVT"))' not in src, (
        "CONTROL: the old hardcoded-AVT fallback must be gone"
    )


# ---------------------------------------------------------------------------
# 5. The migration exists, is chained, and its id is legal
# ---------------------------------------------------------------------------

def test_migration_0176_is_well_formed():
    mig = pathlib.Path(__file__).resolve().parents[1] / "alembic/versions/0176_frame_licence_and_svc.py"
    src = mig.read_text(encoding="utf-8")
    rev = [l for l in src.splitlines() if l.startswith("revision = ")][0].split('"')[1]
    down = [l for l in src.splitlines() if l.startswith("down_revision = ")][0].split('"')[1]
    assert len(rev) <= 32, "alembic revision ids over 32 chars crash-loop on the version UPDATE"
    assert down == "0175_teg_audit_policy_rows"
    assert "licensee_type" in src and "agents_unlisted_by_default" in src
    assert "def downgrade" in src and src.count("op.drop_column") == 2


# ---------------------------------------------------------------------------
# 6. Both provisioning doors hand over the pull credential (findings row 131)
# ---------------------------------------------------------------------------

def test_both_provisioning_paths_pass_the_docker_pull_credential():
    """§pass65 wired the plaintext pull token through the SELF-SERVICE path only. The ADMIN path —
    the one the standup driver and the admin console use — called the same provisioner without it,
    so no `<stack>/.docker/config.json` was written and every image pull answered
    `unauthorized: Missing or invalid Authorization header`, which the operator then reported as
    0/9 containers "host load high".

    The gate is on BOTH call sites by name, because the defect was never in the provisioner: it is
    a fix applied at one call site when the callee has two callers.
    """
    for rel in ("routers/cloud_operators.py", "routers/operator_self_service.py"):
        tree = _tree(rel)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "provision_cloud_operator":
                kw = {k.arg for k in node.keywords}
                assert "docker_pull_token" in kw and "docker_username" in kw, (
                    f"{rel}: provision_cloud_operator called without the pull credential — "
                    f"its image pulls will 401"
                )
                found = True
        assert found, f"{rel}: no provision_cloud_operator call found"


def test_the_admin_path_commits_the_token_hash_before_provisioning():
    """§pass65's own note: the pull's token-auth endpoint runs in a separate READ COMMITTED
    session and cannot see an uncommitted row. A flush here is a 401 later."""
    src = (SRC / "routers/cloud_operators.py").read_text(encoding="utf-8")
    i = src.index("docker_pull_token_hash =")
    j = src.index("result = await provision_cloud_operator")
    assert "await db.commit()" in src[i:j], (
        "the token hash must be COMMITTED before the sidecar tries to pull with it"
    )


def test_a_token_that_could_not_be_persisted_is_not_handed_over():
    """CONTROL: a token authenticating against a hash nobody stored fails in a way that reads
    like a registry outage. The failure path must clear it, not pass it."""
    src = (SRC / "routers/cloud_operators.py").read_text(encoding="utf-8")
    i = src.index("except Exception as _tok_err")
    j = src.index("result = await provision_cloud_operator")
    assert "_pull_token = None" in src[i:j] and "await db.rollback()" in src[i:j]
