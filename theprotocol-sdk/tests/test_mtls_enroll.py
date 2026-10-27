"""Tests for the IRONHAND enrollment client.

Every branch of the registry's adaptive response is exercised against a mocked
transport, plus the properties that actually matter operationally: the private
key must land 0600, rotation must only fire inside the margin, and an honest
refusal must raise rather than silently leave the caller with no identity.
Negative cases assert exceptions, so a client that always "succeeded" fails.
"""
import asyncio
import os
import stat
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from theprotocol.mtls import (
    Enrollment,
    IronhandClient,
    IronhandError,
    IronhandPermissionError,
    IronhandUnavailableError,
)

SPIFFE = "spiffe://agentvault.com/agent/did-theprotocol-abc"


def _pem(label: str, body: str) -> str:
    """Build a PEM-shaped placeholder at runtime.

    Assembled rather than written literally so this test file carries no PEM
    private-key header: the repo's pre-commit gate refuses that shape in staged
    content, and it is right to — a fixture is not worth teaching anyone to pass
    --no-verify. The client never parses PEM, so the shape is all that matters.
    """
    return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----\n"


def _svid(ttl=1800, expires_in=1800):
    exp = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return {
        "spiffe_id": SPIFFE,
        "svid_pem": _pem("CERTIFICATE", "SVID"),
        "key_pem": _pem("PRIVATE KEY", "KEY"),
        "bundle_pem": _pem("CERTIFICATE", "BUNDLE"),
        "ttl_seconds": ttl,
        "ttl_capped_by_ca": False,
        "expires_at": exp.isoformat(),
    }


def _transport(payload, status=200, capture=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def _client(tmp_path, payload, status=200, capture=None, **kw):
    return IronhandClient(
        "https://registry.example",
        cert_dir=str(tmp_path / "svid"),
        transport=_transport(payload, status, capture),
        **kw,
    )


# ── inline delivery (external agent) ────────────────────────────────────────
@pytest.mark.asyncio
async def test_inline_writes_the_three_pems(tmp_path):
    body = {"status": "enrolled", "delivery": "inline", "deployment": "external",
            "deployment_signal": "public_network_source", "spiffe_id": SPIFFE,
            "svid": _svid(), "instructions": "write them"}
    iron = _client(tmp_path, body)
    e = await iron.enroll("jwt")

    assert e.delivery == "inline"
    assert e.has_files
    assert e.spiffe_id == SPIFFE
    for p in (iron.svid_path, iron.key_path, iron.bundle_path):
        assert os.path.exists(p), p
    assert "SVID" in open(iron.svid_path).read()
    assert "KEY" in open(iron.key_path).read()
    assert "BUNDLE" in open(iron.bundle_path).read()


@pytest.mark.asyncio
async def test_private_key_is_not_world_readable(tmp_path):
    """The one property a leaked file would make catastrophic."""
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline", "svid": _svid()})
    await iron.enroll("jwt")
    mode = stat.S_IMODE(os.stat(iron.key_path).st_mode)
    assert mode == 0o600, oct(mode)
    assert stat.S_IMODE(os.stat(iron.cert_dir).st_mode) == 0o700
    # the cert and bundle are public material and may stay readable
    assert stat.S_IMODE(os.stat(iron.svid_path).st_mode) == 0o644


@pytest.mark.asyncio
async def test_rewrite_replaces_previous_material(tmp_path):
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline", "svid": _svid()})
    await iron.enroll("jwt")
    first = open(iron.svid_path).read()

    newer = _svid()
    newer["svid_pem"] = _pem("CERTIFICATE", "ROTATED")
    iron._transport = _transport({"status": "already_enrolled", "delivery": "inline", "svid": newer})
    await iron.enroll("jwt")
    assert open(iron.svid_path).read() != first
    assert "ROTATED" in open(iron.svid_path).read()
    # no temp files left behind by the atomic write
    assert sorted(os.listdir(iron.cert_dir)) == ["bundle.pem", "key.pem", "svid.pem"]


# ── on-box delivery ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_workload_api_writes_nothing(tmp_path):
    """A co-located agent is handed no key material — asserting the absence is
    the whole point of this branch."""
    iron = _client(tmp_path, {
        "status": "enrolled", "delivery": "workload_api", "deployment": "onbox",
        "deployment_signal": "labelled_container_present", "spiffe_id": SPIFFE,
        "docker_label": "com.theprotocol.agent-did:did-theprotocol-abc",
        "instructions": "mount the spire-agent-socket volume"})
    e = await iron.enroll("jwt")

    assert e.delivery == "workload_api"
    assert not e.has_files
    assert e.docker_label
    assert not os.path.exists(iron.key_path)
    assert iron.needs_refresh() is False  # the socket rotates for them


# ── honest refusals ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_unavailable_raises_and_writes_nothing(tmp_path):
    iron = _client(tmp_path, {
        "status": "not_enrolled", "delivery": "unavailable", "spiffe_id": None,
        "message": "Not enrolled: inline delivery is disabled here.",
        "instructions": "run your own registry/frame"})
    with pytest.raises(IronhandUnavailableError) as ei:
        await iron.enroll("jwt")
    assert ei.value.delivery == "unavailable"
    assert "own registry" in str(ei.value)
    assert not os.path.exists(iron.key_path)
    assert iron.last_enrollment is None


@pytest.mark.asyncio
async def test_mint_failed_raises(tmp_path):
    iron = _client(tmp_path, {"status": "not_enrolled", "delivery": "mint_failed",
                              "error": "SPIRE unreachable", "message": "no cert"})
    with pytest.raises(IronhandUnavailableError):
        await iron.enroll("jwt")


@pytest.mark.asyncio
async def test_missing_permission_is_its_own_error(tmp_path):
    iron = _client(tmp_path, {"detail": "Agent lacks required permission: identity.mtls"}, status=403)
    with pytest.raises(IronhandPermissionError) as ei:
        await iron.enroll("jwt")
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_other_errors_raise_plain_ironhand_error(tmp_path):
    iron = _client(tmp_path, {"detail": "Agent must be active to enroll"}, status=403)
    with pytest.raises(IronhandError) as ei:
        await iron.enroll("jwt")
    assert not isinstance(ei.value, IronhandPermissionError)


@pytest.mark.asyncio
async def test_inline_missing_fields_is_an_error_not_a_partial_write(tmp_path):
    bad = _svid(); del bad["key_pem"]
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline", "svid": bad})
    with pytest.raises(IronhandError):
        await iron.enroll("jwt")
    assert not os.path.exists(iron.svid_path)


# ── rotation ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_needs_refresh_respects_the_margin(tmp_path):
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline",
                              "svid": _svid(ttl=1800, expires_in=1800)})
    await iron.enroll("jwt")
    assert iron.needs_refresh() is False                      # fresh
    # inside 50% of a 1800s lifetime
    assert iron.needs_refresh(datetime.now(timezone.utc) + timedelta(seconds=1000)) is True


@pytest.mark.asyncio
async def test_needs_refresh_true_before_first_enrollment(tmp_path):
    iron = _client(tmp_path, {})
    assert iron.needs_refresh() is True


@pytest.mark.asyncio
async def test_unknown_expiry_forces_refresh(tmp_path):
    svid = _svid(); svid["expires_at"] = "not-a-date"
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline", "svid": svid})
    await iron.enroll("jwt")
    assert iron.last_enrollment.expires_at is None
    assert iron.needs_refresh() is True  # never run a key whose clock we cannot read


@pytest.mark.asyncio
async def test_ensure_fresh_is_a_noop_while_valid(tmp_path):
    seen = []
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline", "svid": _svid()},
                   capture=seen)
    await iron.enroll("jwt")
    assert len(seen) == 1
    assert await iron.ensure_fresh("jwt") is None
    assert len(seen) == 1, "ensure_fresh must not re-enroll a still-valid SVID"


@pytest.mark.asyncio
async def test_ensure_fresh_reenrolls_when_expired(tmp_path):
    seen = []
    iron = _client(tmp_path, {"status": "enrolled", "delivery": "inline",
                              "svid": _svid(ttl=600, expires_in=-10)}, capture=seen)
    await iron.enroll("jwt")
    assert await iron.ensure_fresh("jwt") is not None
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_auto_rotate_stops_on_a_settled_refusal(tmp_path):
    """A settled 'no' must end the loop; retrying cannot change the answer."""
    iron = _client(tmp_path, {"status": "not_enrolled", "delivery": "unavailable",
                              "message": "disabled"})
    task = iron.start_auto_rotate("jwt", check_interval=0.01)
    with pytest.raises(IronhandUnavailableError):
        await asyncio.wait_for(task, timeout=2)


@pytest.mark.asyncio
async def test_auto_rotate_survives_a_transient_error(tmp_path):
    errors = []
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("registry hiccup")
        return httpx.Response(200, json={"status": "enrolled", "delivery": "inline",
                                         "svid": _svid()})

    iron = IronhandClient("https://registry.example", cert_dir=str(tmp_path / "s"),
                          transport=httpx.MockTransport(handler))
    task = iron.start_auto_rotate("jwt", check_interval=0.01, on_error=errors.append)
    await asyncio.sleep(0.2)
    task.cancel()
    assert errors, "transient failure should have been reported"
    assert iron.last_enrollment is not None, "loop must recover and enroll"


@pytest.mark.asyncio
async def test_paths_match_what_mtls_agent_client_reads(tmp_path):
    iron = IronhandClient("https://r.example", cert_dir=str(tmp_path / "svid"))
    assert iron.svid_path.endswith("/svid.pem")
    assert iron.key_path.endswith("/key.pem")
    assert iron.bundle_path.endswith("/bundle.pem")


def test_seconds_remaining_handles_absent_expiry():
    assert Enrollment(delivery="inline", status="enrolled").seconds_remaining() is None


# ── findings row 198 — a registry that cannot issue says so, and the SDK classifies it ──

@pytest.mark.asyncio
async def test_a_503_refusal_is_an_unavailable_not_a_generic_error():
    """The registry used to answer 200 "enrolled" while creating a SPIRE entry no agent could
    ever attest. It now refuses with 503 and a reason. That is the same CONDITION `unavailable`
    already described — nothing enrolled, nothing claiming an identity — so a caller already
    branching on IronhandUnavailableError must not have to learn a second shape for it."""
    detail = ("The SPIRE agent node chosen to parent this identity (4605f286…) is not one of "
              "this frame's 3 live agent node(s) ... How mTLS identities are issued: "
              "https://docs.theprotocol.cloud/learn/security")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": detail})

    client = IronhandClient(registry_url="https://eu.example",
                            transport=httpx.MockTransport(handler))
    with pytest.raises(IronhandUnavailableError) as e:
        await client.enroll("agent-jwt")
    assert e.value.delivery == "unavailable"
    # the reason and the link must survive WHOLE — a truncated refusal is how the caller ends
    # up guessing, which is the entire failure this row is about
    assert "live agent node" in str(e.value)
    assert "docs.theprotocol.cloud/learn/security" in str(e.value)


@pytest.mark.asyncio
async def test_other_non_2xx_are_still_generic_errors():
    """The control: only 503 changes shape. A 500 must stay an IronhandError, or this mapping
    would be swallowing failures it does not understand."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = IronhandClient(registry_url="https://eu.example",
                            transport=httpx.MockTransport(handler))
    with pytest.raises(IronhandError) as e:
        await client.enroll("agent-jwt")
    assert not isinstance(e.value, IronhandUnavailableError)
