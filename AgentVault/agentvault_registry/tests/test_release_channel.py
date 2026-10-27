"""§RELEASECHANNEL (2026-09-21) — the signed release channel: one document, one key, three readers.

What must hold:
  · a document verifies only with the key it was signed with, and every alteration (a byte in the body, a missing
    signature, a foreign kid, a wrong schema, an unknown kind) is refused with a reason;
  · kit versions order as people expect (final > rc > beta > alpha, numerically within a stage) and a registry built
    from the source tree still compares by its software version number;
  · the checker notifies the admin audience ONCE per version, with high priority for a hotfix or a security release,
    never on an unreachable channel, never on a document that does not verify, never when up to date; the scheduled
    window's reminder fires once;
  · the token server hands an anonymous client a pull token ONLY for the public namespace and ONLY while the switch
    is on; a push, another namespace or the switch off answer as before (None: the 401 path);
  · the public key is ONE copy across the registry, the CLI and the kit (when their files are beside this tree).
Controls: the tamper cases are the controls of the verify cases; the twice-run check is the control of "once".
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import re

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentvault_registry.core import release_channel as rc

HERE = pathlib.Path(__file__).resolve()


def _stack_root():
    """The stack checkout when this tree sits inside it (the CLI and the kit beside it); None in the image."""
    for parent in HERE.parents:
        if (parent / "tools" / "operator-cli").is_dir() and (parent / "scripts" / "distribution").is_dir():
            return parent
    return None


STACK = _stack_root()


def _keypair():
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return pem, base64.b64encode(pub).decode()


def _doc(*releases):
    return {"schema": rc.SCHEMA, "generated_at": "2026-09-21T08:00:00Z", "version": releases[0]["version"],
            "releases": list(releases)}


def _rel(version, kind="stable", sw="MoreCompliantThenYourWholeComplianceFrameworkV0416", **extra):
    r = {"version": version, "kind": kind, "released_at": "2026-09-21T08:00:00Z", "registry_software_version": sw,
         "kit": {"filename": f"kit-{version}.tar.gz", "sha256": "ab" * 32, "size_bytes": 1, "url": "https://x/kit"},
         "images": {"prefix": "images.example/theprotocol", "tag": version, "digests": {"registry": "sha256:" + "cd" * 32}},
         "min_upgrade_from": "1.0.0-beta.6", "rollback": "two steps", "notes": "n"}
    r.update(extra)
    return r


# ------------------------------------------------------------------------------------------------ signature
def test_sign_verify_and_every_tamper_is_refused():
    pem, pub = _keypair()
    signed = rc.sign(_doc(_rel("1.0.0-beta.11")), pem)
    assert rc.verify(signed, pub) == (True, "ok")
    assert rc.verify(signed) [0] is False                      # the baked key did not sign it
    assert rc.verify({k: v for k, v in signed.items() if k != "signature"}, pub)[1] == "unsigned"
    tampered = json.loads(json.dumps(signed)); tampered["releases"][0]["version"] = "9.9.9"
    assert rc.verify(tampered, pub)[0] is False
    foreign = json.loads(json.dumps(signed)); foreign["signature"]["kid"] = "0000000000000000"
    assert "does not carry" in rc.verify(foreign, pub)[1]
    bad_schema = rc.sign({**_doc(_rel("1.0.0-beta.11")), "schema": "other/9"}, pem)
    assert "schema" in rc.verify(bad_schema, pub)[1]
    bad_kind = rc.sign(_doc(_rel("1.0.0-beta.11", kind="beta")), pem)
    assert "kind" in rc.verify(bad_kind, pub)[1]
    assert rc.verify("not a dict", pub)[0] is False
    assert rc.verify({"schema": rc.SCHEMA, "releases": [], "signature": {}}, pub)[1] in ("unsupported signature algorithm None", "no releases")


def test_env_override_names_another_key(monkeypatch):
    pem, pub = _keypair()
    signed = rc.sign(_doc(_rel("1.0.0-beta.11")), pem)
    monkeypatch.setenv("RELEASE_CHANNEL_PUBKEY_B64", pub)
    assert rc.verify(signed) == (True, "ok")
    monkeypatch.delenv("RELEASE_CHANNEL_PUBKEY_B64")
    assert rc.verify(signed)[0] is False


# ------------------------------------------------------------------------------------------------ versions
def test_kit_version_order():
    order = ["1.0.0-alpha.3", "1.0.0-beta.9", "1.0.0-beta.10", "1.0.0-rc.1", "1.0.0", "1.0.1", "1.1.0-beta.1", "2.0.0"]
    parsed = [rc.parse_kit_version(v) for v in order]
    assert all(p is not None for p in parsed)
    assert parsed == sorted(parsed)
    assert rc.parse_kit_version("v1.0.0") is None and rc.parse_kit_version("1.0") is None
    assert rc.parse_software_version("MoreCompliantThenYourWholeComplianceFrameworkV0415") == 415
    assert rc.parse_software_version("Pass-NOTanUnlicensedCentralBankIPromiseV0133") == 133
    assert rc.parse_software_version("nope") is None


def test_is_newer_prefers_kit_versions_then_software_numbers():
    assert rc.is_newer(_rel("1.0.0-beta.11"), {"kit_version": "1.0.0-beta.10", "software_version": "xV0999"}) is True
    assert rc.is_newer(_rel("1.0.0-beta.10"), {"kit_version": "1.0.0-beta.10", "software_version": "xV0001"}) is False
    # a source-tree registry has no kit version: the software number decides
    assert rc.is_newer(_rel("1.0.0-beta.11", sw="xV0416"), {"kit_version": None, "software_version": "xV0415"}) is True
    assert rc.is_newer(_rel("1.0.0-beta.11", sw="xV0415"), {"kit_version": None, "software_version": "xV0415"}) is False
    assert rc.is_newer(_rel("1.0.0-beta.11", sw="nope"), {"kit_version": None, "software_version": "xV0415"}) is None


def test_assess_kind_and_comparability():
    doc = _doc(_rel("1.0.0-beta.12", kind="stable"), _rel("1.0.0-beta.11", kind="security"), _rel("1.0.0-beta.10"))
    v = rc.assess(doc, {"kit_version": "1.0.0-beta.10", "software_version": "xV0415"})
    assert [r["version"] for r in v["newer"]] == ["1.0.0-beta.12", "1.0.0-beta.11"]
    assert v["kind"] == "security" and v["update_available"] and v["comparable"] and v["latest"]["version"] == "1.0.0-beta.12"
    up = rc.assess(doc, {"kit_version": "1.0.0-beta.12", "software_version": "xV0415"})
    assert up["update_available"] is False and up["kind"] is None
    unknown = rc.assess(_doc(_rel("1.0.0-beta.12", sw="nope")), {"kit_version": None, "software_version": "xV0415"})
    assert unknown["comparable"] is False and unknown["update_available"] is False


# ------------------------------------------------------------------------------------------------ the checker
class _Recorder:
    def __init__(self):
        self.calls = []

    async def audience(self, type_key, **kw):
        self.calls.append((type_key, kw))
        return 1


@pytest.fixture
def channel(monkeypatch, tmp_path):
    from agentvault_registry.background_tasks import release_channel_checker as chk
    import agentvault_registry.background_tasks.push_notify as pn
    pem, pub = _keypair()
    monkeypatch.setenv("RELEASE_CHANNEL_PUBKEY_B64", pub)
    monkeypatch.setenv("RELEASE_CHANNEL_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("RELEASE_CHANNEL_CHECK_ENABLED", "true")
    monkeypatch.setattr(rc, "running_versions", lambda: {"kit_version": "1.0.0-beta.10", "software_version": "xV0415"})
    rec = _Recorder()
    monkeypatch.setattr(pn, "notify_audience", rec.audience)
    box = {"status": 200, "doc": None, "err": ""}

    async def fetch():
        if box["doc"] is None:
            return box["status"], None, box["err"] or f"HTTP {box['status']}"
        return 200, json.dumps(box["doc"]).encode(), ""

    return chk, rec, box, pem, fetch


@pytest.mark.asyncio
async def test_checker_notifies_once_with_high_priority_for_security(channel):
    chk, rec, box, pem, fetch = channel
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.11", kind="security")), pem)
    st = await chk.check_once(fetch=fetch)
    assert st["last_outcome"] == "ok" and st["update_available"] and st["kind"] == "security"
    assert len(rec.calls) == 1 and rec.calls[0][0] == chk.UPDATE_KEY and rec.calls[0][1]["priority"] == "high"
    assert "1.0.0-beta.11" in rec.calls[0][1]["title"] and rec.calls[0][1]["click"] == chk.ADMIN_PAGE
    st = await chk.check_once(fetch=fetch)
    assert len(rec.calls) == 1, "the same version notified twice"
    assert st["notified"]["1.0.0-beta.11"]
    # a newer one arrives: one more notification, default priority for a stable release
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.12", kind="stable"), _rel("1.0.0-beta.11", kind="security")), pem)
    st = await chk.check_once(fetch=fetch)
    assert len(rec.calls) == 2 and rec.calls[1][1]["priority"] == "high"   # security still among the newer ones


@pytest.mark.asyncio
async def test_checker_stays_silent_when_unreachable_or_unverified_or_current(channel):
    chk, rec, box, pem, fetch = channel
    box["status"] = 404
    st = await chk.check_once(fetch=fetch)
    assert st["last_outcome"] == "unreachable" and not rec.calls and st["update_available"] is False
    other_pem, _ = _keypair()
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.11", kind="hotfix")), other_pem)
    st = await chk.check_once(fetch=fetch)
    assert st["last_outcome"] == "invalid_signature" and not rec.calls
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.10")), pem)
    st = await chk.check_once(fetch=fetch)
    assert st["last_outcome"] == "ok" and st["update_available"] is False and not rec.calls


@pytest.mark.asyncio
async def test_schedule_reminder_fires_once_when_due(channel, monkeypatch):
    chk, rec, box, pem, fetch = channel
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.11")), pem)
    await chk.check_once(fetch=fetch)
    st = rc.load_state()
    st["schedule"] = {"version": "1.0.0-beta.11", "at": "2026-01-01T00:00:00Z", "note": "night", "reminded_at": None}
    rc.save_state(st)
    await chk.check_once(fetch=fetch)
    due = [c for c in rec.calls if c[0] == chk.ROLLOUT_DUE_KEY]
    assert len(due) == 1 and "1.0.0-beta.11" in due[0][1]["title"]
    await chk.check_once(fetch=fetch)
    assert len([c for c in rec.calls if c[0] == chk.ROLLOUT_DUE_KEY]) == 1
    far = rc.load_state(); far["schedule"] = {"version": "1.0.0-beta.11", "at": "2999-01-01T00:00:00Z", "reminded_at": None}
    rc.save_state(far)
    await chk.check_once(fetch=fetch)
    assert len([c for c in rec.calls if c[0] == chk.ROLLOUT_DUE_KEY]) == 1, "a window far away reminded early"


@pytest.mark.asyncio
async def test_a_reader_holds_the_stored_check_against_the_build_running_now(channel, monkeypatch):
    """After an update through the channel the registry runs the release the stored check found it behind on; the
    status and the dashboard block must say so before the next check (agentvault2-56, 2026-10-23: a kit frame updated
    from beta.22 to beta.23 still read "runs beta.22, update available"). Controls: the same build reads the stored
    verdict unchanged, and a rollback reads behind again."""
    chk, rec, box, pem, fetch = channel
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.11", kind="hotfix"), _rel("1.0.0-beta.10")), pem)
    await chk.check_once(fetch=fetch)                                  # checked while running beta.10
    same = rc.current_view(rc.load_state())
    assert same["update_available"] and same["kind"] == "hotfix" and [r["version"] for r in same["newer"]] == ["1.0.0-beta.11"]
    assert "checked_against" not in same
    monkeypatch.setattr(rc, "running_versions", lambda: {"kit_version": "1.0.0-beta.11", "software_version": "xV0416"})
    now = rc.current_view(rc.load_state())                             # updated, no check since
    assert now["running"]["kit_version"] == "1.0.0-beta.11" and now["checked_against"]["kit_version"] == "1.0.0-beta.10"
    assert now["update_available"] is False and now["newer"] == [] and now["kind"] is None
    assert now["latest"]["version"] == "1.0.0-beta.11", "the newest release is still named"
    dash = rc.dashboard_summary()
    assert dash["update_available"] is False and dash["running"]["kit_version"] == "1.0.0-beta.11"
    monkeypatch.setattr(rc, "running_versions", lambda: {"kit_version": "1.0.0-beta.9", "software_version": "xV0414"})
    back = rc.current_view(rc.load_state())                            # rolled back below what was checked
    assert back["update_available"] and back["kind"] == "hotfix" and back["newer"][0]["version"] == "1.0.0-beta.11"


@pytest.mark.asyncio
async def test_nothing_is_offered_or_reminded_for_the_release_already_running(channel, monkeypatch):
    """Up to date, the page offered a window and printed the apply command for the release the registry runs, and a
    window saved before the update still reminded that the rollout was due (agentvault2-56, 2026-10-23). Control: the
    same rail, behind, offers both and keeps the window."""
    from types import SimpleNamespace
    from fastapi import HTTPException
    from agentvault_registry.routers import admin_release_channel as rail
    chk, rec, box, pem, fetch = channel
    box["doc"] = rc.sign(_doc(_rel("1.0.0-beta.11")), pem)
    await chk.check_once(fetch=fetch)
    admin = SimpleNamespace(email="admin@test")
    behind = await rail.release_channel_schedule(rail.ScheduleBody(version="1.0.0-beta.11", at="2999-01-01T00:00:00Z"), admin=admin)
    assert behind["update_available"] and "--to-version 1.0.0-beta.11" in behind["rollout_command"]
    assert behind["schedule"]["version"] == "1.0.0-beta.11"
    monkeypatch.setattr(rc, "running_versions", lambda: {"kit_version": "1.0.0-beta.11", "software_version": "xV0416"})
    now = rail._status_doc()
    assert now["update_available"] is False and now["rollout_command"] is None and now["schedule"] is None
    with pytest.raises(HTTPException) as refused:
        await rail.release_channel_schedule(rail.ScheduleBody(version="1.0.0-beta.11", at="2999-01-01T00:00:00Z"), admin=admin)
    assert refused.value.status_code == 422 and "already runs 1.0.0-beta.11" in refused.value.detail
    st = rc.load_state(); st["schedule"]["at"] = "2026-01-01T00:00:00Z"; rc.save_state(st)    # the window is due now
    await chk.check_once(fetch=fetch)
    assert not [c for c in rec.calls if c[0] == chk.ROLLOUT_DUE_KEY], "a reminder for a rollout that is done"
    assert rc.load_state()["schedule"] is None


def test_worker_is_off_by_default(monkeypatch):
    from agentvault_registry.background_tasks.release_channel_checker import ReleaseChannelChecker
    monkeypatch.delenv("RELEASE_CHANNEL_CHECK_ENABLED", raising=False)
    assert ReleaseChannelChecker()._should_run() is False
    monkeypatch.setenv("RELEASE_CHANNEL_CHECK_ENABLED", "true")
    assert ReleaseChannelChecker()._should_run() is True


# ------------------------------------------------------------------------------------------------ the token server
def test_anonymous_pull_only_for_the_public_namespace_and_only_when_on(monkeypatch, tmp_path):
    from agentvault_registry.routers.docker_token_auth import _anonymous_public_pull, _parse_scope
    monkeypatch.delenv("RELEASE_CHANNEL_PUBLIC_PULL", raising=False)
    monkeypatch.setenv("RELEASE_CHANNEL_PUBLIC_PULL_FILE", str(tmp_path / "absent"))
    assert _anonymous_public_pull(_parse_scope("repository:theprotocol/registry:pull")) is None   # the switch is off
    monkeypatch.setenv("RELEASE_CHANNEL_PUBLIC_PULL", "true")
    assert _anonymous_public_pull(_parse_scope("repository:theprotocol/registry:pull")) == [
        {"type": "repository", "name": "theprotocol/registry", "actions": ["pull"]}]
    assert _anonymous_public_pull(_parse_scope("repository:theprotocol/registry:pull,push")) is None
    assert _anonymous_public_pull(_parse_scope("repository:registry:pull")) is None              # the private lineage
    assert _anonymous_public_pull(_parse_scope("repository:theprotocol/a/b:pull")) is None       # not one level
    assert _anonymous_public_pull(_parse_scope("repository:theprotocol/registry:pull repository:teg-layer:pull")) is None
    assert _anonymous_public_pull([]) == []                                                       # the /v2/ ping
    monkeypatch.delenv("RELEASE_CHANNEL_PUBLIC_PULL")
    (tmp_path / "absent").write_text("on\n")
    assert _anonymous_public_pull(_parse_scope("repository:theprotocol/registry:pull")) is not None  # the switch file


# ------------------------------------------------------------------------------------------------ declarations
def test_catalog_declares_the_two_types():
    from agentvault_registry.services.notification_catalog import get_type
    for key in ("release.update_available", "release.rollout_due"):
        entry = get_type(key)
        assert entry is not None and entry.audience == "admin", key


def test_mail_context_says_nothing_while_off(monkeypatch, tmp_path):
    monkeypatch.delenv("RELEASE_CHANNEL_PUBLIC_PULL", raising=False)
    monkeypatch.setenv("RELEASE_CHANNEL_PUBLIC_PULL_FILE", str(tmp_path / "absent"))
    monkeypatch.setenv("RELEASE_CHANNEL_STATE_PATH", str(tmp_path / "state.json"))
    assert rc.mail_context()["release_channel_public_pull"] is False
    monkeypatch.setenv("RELEASE_CHANNEL_PUBLIC_PULL", "true")
    monkeypatch.setattr(rc, "running_versions", lambda: {"kit_version": None, "software_version": "xV0415"})
    assert rc.mail_context()["release_channel_public_pull"] is False        # on, but no version to name yet
    rc.save_state({**rc.load_state(), "latest": {"version": "1.0.0-beta.11", "images_tag": "1.0.0-beta.11"}})
    ctx = rc.mail_context()
    assert ctx == {"release_channel_public_pull": True, "images_prefix": "images.theprotocol.cloud/theprotocol",
                   "images_tag": "1.0.0-beta.11"}


def test_public_key_is_one_copy_across_the_readers():
    if STACK is None:
        pytest.skip("the CLI and the kit are not beside this tree")
    copies = {}
    for rel in ("tools/operator-cli/tp_operator/release_channel.py", "scripts/distribution/release_channel.py"):
        p = STACK / rel
        if not p.is_file():
            pytest.skip(f"{rel} is not beside this tree")
        m = re.search(r'RELEASE_PUBKEY_B64\s*=\s*"([^"]+)"', p.read_text())
        assert m, rel
        copies[rel] = m.group(1)
    assert set(copies.values()) == {rc.RELEASE_PUBKEY_B64}, copies
