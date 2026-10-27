"""§OPDIST — the registry's half of the seam: a complete spec, and the two failures kept apart.

The registry resolves everything and the one-shot holds no database, so a spec that is short of anything is a
provision that fails on the far side for a reason this side could see. And a runner REFUSAL is not a runner
FAILURE: the first means nothing started and the caller's one-time activation code is still good, the second means
something may have run. A rail that could not tell those apart spent an activation code this morning.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import sys
import types

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")


@pytest.fixture(autouse=True)
def _frame_names_its_own_spire(monkeypatch):
    """Every spec a real registry builds carries these; without them build_operator_spec refuses (2026-09-16).
    The refusal itself is pinned in test_operator_runner_branch.py, which unsets them deliberately."""
    for k, v in (("SPIRE_CONTAINER", "lantern-spire-server"),
                 ("SPIRE_TRUST_DOMAIN", "lantern.theprotocol.cloud"),
                 ("SPIRE_SERVER_ADDRESS", "spire.lantern.theprotocol.cloud"),
                 ("SPIRE_SERVER_PORT", "8444")):
        monkeypatch.setenv(k, v)


def _load_client(monkeypatch):
    """Load the caller with a stub runner client, so the seam's SHAPE is tested without a runner."""
    fake = types.ModuleType("agentvault_registry.services.frame_runner_client")

    class RunnerRefused(Exception):
        pass

    class RunnerError(Exception):
        pass

    fake.RunnerRefused = RunnerRefused
    fake.RunnerError = RunnerError
    fake.SHORT_TIMEOUT_S = 20.0
    fake.calls = []

    async def call(op, **kw):
        fake.calls.append((op, kw))
        return fake.answers.pop(0)

    fake.call = call
    fake.answers = []
    pkg = types.ModuleType("agentvault_registry.services")
    pkg.frame_runner_client = fake
    monkeypatch.setitem(sys.modules, "agentvault_registry.services", pkg)
    monkeypatch.setitem(sys.modules, "agentvault_registry.services.frame_runner_client", fake)
    spec = importlib.util.spec_from_file_location("_opdist_client", _SRC / "services" / "operator_provision_client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, fake


def _secrets(n=64):
    # Five since §OPDIST 2026-09-16: the fifth is the read-only credential the FRAME'S AUDITOR reads this
    # operator's share register with — minted for the operator, never written into its env.
    return {k: "a" * n for k in ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                 "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG", "AUDITOR_RO_PASSWORD")}


def _kw(**over):
    base = dict(operator_name="Tartu", safe_name="tartu", operator_did="did:theprotocol:x", frame="lantern",
                docker_pull_token="dpt_" + "b" * 64, operator_secrets=_secrets())
    base.update(over)
    return base


def test_a_complete_spec_carries_exactly_what_the_far_side_reads(monkeypatch):
    mod, _ = _load_client(monkeypatch)
    spec = mod.build_operator_spec(**_kw(env={"CENTRAL_REGISTRY_URL": "https://lantern.theprotocol.cloud"}))
    # ⚠ THE SPEC'S SHAPE IS THE CONTRACT, so this set is updated deliberately and never widened to make a red go
    # away. The four spire_* keys were added on 2026-09-16: without them the one-shot's provisioner falls back to
    # Frame A's SPIRE server and trust domain, and a bundle built for any other frame registers its operator in
    # the wrong SPIRE entirely. They are absent from a stack spec, which opens none of them.
    assert set(spec) == {"phase", "operator_name", "safe_name", "operator_did", "frame", "docker_pull_token",
                         "operator_secrets", "env",
                         "spire_container", "spire_trust_domain", "spire_server_address", "spire_server_port"}
    assert set(spec["operator_secrets"]) == set(mod.SECRET_KEYS)
    # the credentials the seam exists to keep on this side must not be anywhere in it
    flat = repr(spec)
    for forbidden in ("DATABASE_URL", "API_KEY_SECRET", "JWT_SECRET_KEY"):
        assert forbidden not in flat


def test_a_short_secret_is_refused_before_anything_is_sent(monkeypatch):
    """Short is not weak here, it is OFF: below 32 the apps turn the header path off and refuse every certificate."""
    mod, fake = _load_client(monkeypatch)
    with pytest.raises(mod.SpecIncomplete) as e:
        mod.build_operator_spec(**_kw(operator_secrets=_secrets(8)))
    assert "OFF" in str(e.value) and "Nothing was sent" in str(e.value)
    assert fake.calls == [], "a refusal on this side must not have reached the runner"


def test_a_refusal_and_a_failure_do_not_read_the_same(monkeypatch):
    mod, fake = _load_client(monkeypatch)
    fake.answers = [{"job_id": "j1"}, {"job": {"state": "refused", "refused": "this runner did not build that frame"}}]
    with pytest.raises(fake.RunnerRefused) as e:
        asyncio.run(mod.provision_through_runner(frame="lantern", spec={"x": 1}, poll_interval_s=0))
    assert "nothing was done" in str(e.value)

    fake.answers = [{"job_id": "j2"}, {"job": {"state": "failed", "exit_code": 4, "error": "compose up exited 1"}}]
    with pytest.raises(fake.RunnerError):
        asyncio.run(mod.provision_through_runner(frame="lantern", spec={"x": 1}, poll_interval_s=0))


def test_a_finish_without_the_contracted_result_is_an_error_not_a_success(monkeypatch):
    """A job that says 'done' and returns nothing is the shape that reads as success and leaves no operator."""
    mod, fake = _load_client(monkeypatch)
    fake.answers = [{"job_id": "j3"}, {"job": {"state": "succeeded"}, "result": {"notes": ["ok"]}}]
    with pytest.raises(fake.RunnerError) as e:
        asyncio.run(mod.provision_through_runner(frame="lantern", spec={"x": 1}, poll_interval_s=0))
    assert "which the full phase promises" in str(e.value)


def test_a_deadline_says_it_may_still_be_running(monkeypatch):
    """The dangerous advice after a timeout is 'try again': a second provision against a half-built stack."""
    mod, fake = _load_client(monkeypatch)
    fake.answers = [{"job_id": "j4"}] + [{"job": {"state": "running"}} for _ in range(50)]
    with pytest.raises(fake.RunnerError) as e:
        asyncio.run(mod.provision_through_runner(frame="lantern", spec={"x": 1}, deadline_s=0.05,
                                                 poll_interval_s=0.01))
    assert "may still be running" in str(e.value) and "rather than provisioning again" in str(e.value)


def test_the_spec_never_names_an_image(monkeypatch):
    """The caller does not choose the container, on purpose, and the runner refuses a caller that tries.

    Settled with agentvault2-85 (599080a) after this side measured that no frame's env carries an image id at all:
    the runner takes it from the frame's OWN registry container, which is the only party that can tell what the
    frame is actually running. A value nobody is asked for is a value nobody can lie about — and there is then
    nothing on this side to keep in step with the image.
    """
    mod, _ = _load_client(monkeypatch)
    monkeypatch.setenv("REGISTRY_IMAGE_ID", "sha256:" + "a" * 64)  # even when one is lying around
    spec = mod.build_operator_spec(**_kw())
    assert "image_id" not in spec and not hasattr(mod, "registry_image_id")


def test_a_phase_the_runner_does_not_serve_is_refused_before_sending(monkeypatch):
    mod, _ = _load_client(monkeypatch)
    with pytest.raises(mod.SpecIncomplete) as e:
        mod.build_operator_spec(**_kw(phase="teardown"))
    assert "is not one the runner serves" in str(e.value)


def test_a_bundle_job_is_judged_by_what_the_bundle_phase_promises(monkeypatch):
    """The reason the contract had to become phase-aware: activation asks for a bundle, which has no stack_dir, and
    the first version of this check would have read a perfectly good bundle job as a broken one."""
    mod, fake = _load_client(monkeypatch)
    done = {"job": {"state": "succeeded"},
            "result": {"bundle_path": "/opt/theprotocol/stack/lantern-1/operator-bundles/tartu.tar.gz",
                       "bundle_filename": "tartu.tar.gz", "fingerprint": "fp", "notes": ["phase: bundle"]}}
    fake.answers = [{"job_id": "j9"}, done]
    result = asyncio.run(mod.provision_through_runner(
        frame="lantern", spec={"phase": "bundle"}, poll_interval_s=0))
    assert result["bundle_filename"] == "tartu.tar.gz"

    # and the control: the SAME result under the full phase is short of stack_dir and must be an error
    mod2, fake2 = _load_client(monkeypatch)
    fake2.answers = [{"job_id": "j10"}, done]
    with pytest.raises(fake2.RunnerError) as e:
        asyncio.run(mod2.provision_through_runner(frame="lantern", spec={"phase": "full"}, poll_interval_s=0))
    assert "stack_dir" in str(e.value)


def test_a_bundle_spec_carries_no_operator_secrets(monkeypatch):
    """What crosses is decided by what the far side will DO with it.

    The one-shot writes the operator's env and markers in the steps only the full phase runs, so a bundle job that
    carried the four secrets would leave them in a spec file on disk for a job that never opens them. The full phase
    still refuses without them, which is the control below.
    """
    mod, _ = _load_client(monkeypatch)
    spec = mod.build_operator_spec(**_kw(phase="bundle", operator_secrets=None))
    # ABSENT, not empty: an absent field says this does not apply, an empty one claims it applies and is empty,
    # and the runner refuses secrets in a bundle spec either way (599080a).
    assert "operator_secrets" not in spec and spec["phase"] == "bundle"
    assert not any("REDIS_PASSWORD" in repr(v) for v in spec.values())

    with pytest.raises(mod.SpecIncomplete) as e:
        mod.build_operator_spec(**_kw(phase="full", operator_secrets=None))
    assert "32 characters" in str(e.value)


def test_the_deadline_exceeds_the_far_sides_own_ceilings(monkeypatch):
    """A caller that gives up while the far side is still working reports a failure for a job that succeeds, and an
    operator then runs on the frame with no row describing it. Derived from the one-shot's OWN timeouts rather than
    a remembered number, so a step that gains a longer ceiling moves this gate instead of quietly outgrowing it."""
    import re as _re
    mod, _ = _load_client(monkeypatch)
    hw = _SRC / "host_work.py"
    if not hw.exists():
        hw = _SRC.parent / "host_work.py"
    src = hw.read_text()
    ceilings = [int(m) for m in _re.findall(r"timeout=(\d+)", src)]
    ceilings += [int(m) for m in _re.findall(r"deadline_s: int = (\d+)", src)]  # the health wait is a ceiling too
    assert ceilings, "the one-shot's steps should carry explicit timeouts"
    assert mod.PROVISION_DEADLINE_S >= sum(ceilings), (
        f"the caller waits {mod.PROVISION_DEADLINE_S}s while the one-shot's own ceilings sum to {sum(ceilings)}s")


def test_a_full_spec_without_the_auditor_credential_is_refused_here(monkeypatch):
    """The runner requires it too (agentvault2-6a, 21f66d6), so a spec missing it is refused BEFORE a job exists.
    Two doors, and this one is the side that can still fix the spec."""
    mod, fake = _load_client(monkeypatch)
    short = {k: v for k, v in _secrets().items() if k != "AUDITOR_RO_PASSWORD"}
    with pytest.raises(mod.SpecIncomplete) as e:
        mod.build_operator_spec(**_kw(operator_secrets=short))
    assert "AUDITOR_RO_PASSWORD" in str(e.value)
    assert fake.calls == [], "a spec refused here must not have been sent"
