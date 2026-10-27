"""§OPDIST V0386 — the runner branch of a cloud-operator provision, driven against the runner's REAL answer shapes.

Every test here pins something that was already broken in a certified, gated, shipped image (V0385
`e370a9e89144`), which is the useful part: the suite was green, the boot gate passed, the content markers matched,
and the route could not run once. What none of those gates asks is the question this file asks — does the caller
survive the answers the far side actually sends.
"""
import importlib.util
import json
import os
import pathlib
import sys
import types

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")

SPIRE_ENV = {"SPIRE_CONTAINER": "beacon-spire-server", "SPIRE_TRUST_DOMAIN": "beacon.theprotocol.cloud",
             "SPIRE_SERVER_ADDRESS": "spire.beacon.theprotocol.cloud", "SPIRE_SERVER_PORT": "8444"}


def _load_client(monkeypatch, spire=True):
    fake = types.ModuleType("agentvault_registry.services.frame_runner_client")

    class RunnerRefused(Exception):
        pass

    class RunnerError(Exception):
        pass

    fake.RunnerRefused, fake.RunnerError, fake.SHORT_TIMEOUT_S = RunnerRefused, RunnerError, 20.0
    fake.calls, fake.answers = [], []

    async def call(op, **kw):
        fake.calls.append((op, kw))
        return fake.answers.pop(0)

    fake.call = call
    pkg = types.ModuleType("agentvault_registry.services")
    pkg.frame_runner_client = fake
    monkeypatch.setitem(sys.modules, "agentvault_registry.services", pkg)
    monkeypatch.setitem(sys.modules, "agentvault_registry.services.frame_runner_client", fake)
    for k, v in (SPIRE_ENV.items() if spire else ()):
        monkeypatch.setenv(k, v)
    if not spire:
        for k in SPIRE_ENV:
            monkeypatch.delenv(k, raising=False)
    spec = importlib.util.spec_from_file_location("_opdist_client_rb",
                                                  _SRC / "services" / "operator_provision_client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, fake


def _secrets(n=64):
    return {k: "a" * n for k in ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                 "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG", "AUDITOR_RO_PASSWORD")}


def _kw(**over):
    base = dict(operator_name="Ventspils", safe_name="ventspils", operator_did="did:theprotocol:operator:ventspils",
                frame="beacon", docker_pull_token="dpt_" + "b" * 64, operator_secrets=_secrets())
    base.update(over)
    return base


# ── A ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_stack_phase_is_one_the_runner_serves(monkeypatch):
    """cloud_provisioner asks for phase 'stack'. V0385's client did not serve it, so the branch refused its own
    caller and no stack job could ever be submitted from a runner-built frame."""
    mod, _ = _load_client(monkeypatch)
    assert "stack" in mod.PHASES
    spec = mod.build_operator_spec(**_kw(phase="stack", stack_dir="/opt/theprotocol/stack/cloud-op-ventspils"))
    assert spec["phase"] == "stack"


def test_a_stack_result_is_judged_on_presence_not_truth(monkeypatch):
    """`container_count: 0` is an ANSWER — the most interesting one a compose can give. A falsy check reported the
    phase as having broken its promise exactly when it was reporting a real and useful fact."""
    mod, fake = _load_client(monkeypatch)
    fake.answers = [{"started": True, "job_id": "j1"},
                    {"job": {"id": "j1", "state": "succeeded"},
                     "result": {"stack_dir": "/opt/theprotocol/stack/cloud-op-ventspils", "container_count": 0,
                                "notes": []}}]
    import asyncio
    out = asyncio.run(mod.provision_through_runner(frame="beacon", spec={"phase": "stack"}, poll_interval_s=0))
    assert out["container_count"] == 0

    mod2, fake2 = _load_client(monkeypatch)
    fake2.answers = [{"started": True, "job_id": "j2"},
                     {"job": {"id": "j2", "state": "succeeded"}, "result": {"container_count": 3, "notes": []}}]
    with pytest.raises(fake2.RunnerError) as e:   # stack_dir genuinely absent is still short
        asyncio.run(mod2.provision_through_runner(frame="beacon", spec={"phase": "stack"}, poll_interval_s=0))
    assert "stack_dir" in str(e.value)


# ── B ────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("started,where", [
    ({"started": True, "job": {"id": "jx"}}, "nested"),
    ({"started": True, "job_id": "jx"}, "top level"),
    ({"started": True, "job_id": "jx", "job": {"id": "jx"}}, "both"),
])
def test_the_job_id_is_read_in_either_shape(monkeypatch, started, where):
    """The runner answered {"started": true, "job": {"id": ...}} and this side read only "job_id". Beacon's
    ventspils job SUCCEEDED — three SPIRE entries, the tar on disk — while the caller raised "accepted without
    returning a job id" and recorded nothing. The work happening and nothing recording it is the worst outcome
    available, so both shapes are read and neither side has to win."""
    mod, fake = _load_client(monkeypatch)
    fake.answers = [started, {"job": {"id": "jx", "state": "succeeded"},
                              "result": {"stack_dir": "/s", "container_count": 9, "notes": []}}]
    import asyncio
    out = asyncio.run(mod.provision_through_runner(frame="beacon", spec={"phase": "stack"}, poll_interval_s=0))
    assert out["container_count"] == 9, where
    assert fake.calls[1][1]["job_id"] == "jx", f"polled the wrong id in the {where} shape"


def test_no_job_id_in_either_shape_is_still_an_error(monkeypatch):
    mod, fake = _load_client(monkeypatch)
    fake.answers = [{"started": True, "job": {"state": "queued"}}]
    import asyncio
    with pytest.raises(fake.RunnerError):
        asyncio.run(mod.provision_through_runner(frame="beacon", spec={"phase": "stack"}, poll_interval_s=0))


# ── F ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_bundle_spec_carries_the_frames_own_spire_identity(monkeypatch):
    mod, _ = _load_client(monkeypatch)
    spec = mod.build_operator_spec(**_kw(phase="bundle"))
    assert spec["spire_container"] == "beacon-spire-server"
    assert spec["spire_trust_domain"] == "beacon.theprotocol.cloud"


def test_a_registry_that_cannot_name_its_own_spire_refuses_to_bundle(monkeypatch):
    """The defaults in the provisioner are FRAME A's. A bundle built without these values does not fail — it
    succeeds against the wrong SPIRE server, under the wrong trust domain, and nobody finds out."""
    mod, fake = _load_client(monkeypatch, spire=False)
    with pytest.raises(mod.SpecIncomplete) as e:
        mod.build_operator_spec(**_kw(phase="bundle"))
    assert "spire_container" in str(e.value) and "Frame A" in str(e.value)
    assert fake.calls == [], "a refusal must leave nothing behind"


def test_the_stack_phase_carries_where_its_data_entry_goes_and_nothing_more(monkeypatch):
    """⚠ THE CONTRACT CHANGED AT V0391, DELIBERATELY. The stack phase registers the operator database's own SVID
    entry, so it needs the two values that say WHERE that entry goes — and the runner verifies both against the
    frame's own registry. It must NOT carry the fingerprint: the stack phase extracts the bundle, so it holds
    agent-attestation.crt and derives the x509pop fingerprint from it. A carried fingerprint is one the runner
    cannot check (it is per operator, not per frame) and one that, if it disagreed with the certificate, would
    register a parentID no agent ever attests as. Same reasoning as image_id, which this spec also never carries.
    """
    mod, _ = _load_client(monkeypatch)
    spec = mod.build_operator_spec(**_kw(phase="stack", stack_dir="/s"))
    assert spec["spire_container"] == "beacon-spire-server"
    assert spec["spire_trust_domain"] == "beacon.theprotocol.cloud"
    for absent in ("spire_server_address", "spire_server_port", "spire_fingerprint", "fingerprint", "image_id"):
        assert absent not in spec, f"a stack spec must not carry {absent}"


def test_a_registry_that_cannot_name_its_own_spire_refuses_to_build_a_stack_spec_too(monkeypatch):
    """The stack phase decides which SPIRE server gets an entry. Defaulting there is the same wrong-frame hazard
    the bundle phase refuses for, so it refuses here as well rather than quietly reaching for Frame A's."""
    mod, fake = _load_client(monkeypatch, spire=False)
    with pytest.raises(mod.SpecIncomplete) as e:
        mod.build_operator_spec(**_kw(phase="stack", stack_dir="/s"))
    assert "spire_container" in str(e.value)
    assert fake.calls == []


def test_the_one_shot_refuses_a_bundle_job_with_no_spire_identity(tmp_path):
    """The other end of the same rule. Both ends enforce it: a spec is refused where it is built AND where it is
    read, because the two are different processes and only one of them was wrong at a time."""
    path = _SRC / "host_work.py"
    spec = importlib.util.spec_from_file_location("_opdist_hostwork_rb", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = tmp_path / "spec.json"
    p.write_text(json.dumps({"phase": "bundle", "operator_name": "V", "safe_name": "v",
                             "operator_did": "did:x", "frame": "beacon", "docker_pull_token": "dpt_" + "c" * 64}))
    with pytest.raises(mod.HostWorkRefused) as e:
        mod.read_spec(str(p))
    assert "spire_container" in str(e.value)


# ── C and E ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _load_provisioner_by_path():
    """EXACTLY how host_work's one-shot loads it: by path, under a name with no package."""
    spec = importlib.util.spec_from_file_location("_opdist_prov_rb", _SRC / "services" / "operator_provisioner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_federation_parser_loads_when_the_module_is_loaded_by_path():
    """§BATCH7 by a door nobody had shut: `from .frame_trust_manager import ...` inside a module loaded by path
    raises "attempted relative import with no known parent package", the broad except turned that into an empty
    federation, and every operator of a federated frame was born with no -federatesWith."""
    mod = _load_provisioner_by_path()
    parse = mod._load_parse_federation_list()
    assert callable(parse)
    assert parse("") == [] or list(parse("")) == []


def test_an_entry_that_is_already_there_counts_as_registered():
    mod = _load_provisioner_by_path()
    assert mod._entry_already_exists("", "rpc error: code = AlreadyExists desc = entry already exists")
    assert mod._entry_already_exists("Failed to create the following entry (code: AlreadyExists)", "")
    assert not mod._entry_already_exists("", "rpc error: code = InvalidArgument desc = failed to convert entry")
    assert not mod._entry_already_exists("", "")


# ── C's guard, which V0386 shipped unable to pass ────────────────────────────────────────────────────────────────
def _may_rebundle(monkeypatch):
    """Through the same stubbed load the rest of this file uses: a bare by-path load pulls the real
    `services/__init__`, which imports the ORM this module deliberately never touches."""
    mod, _ = _load_client(monkeypatch)
    return mod.may_rebundle


def _statuses_the_writers_write():
    """Every status value the product actually assigns to an OperatorApplication, read from the WRITERS.

    This is the whole point of the test below: a guard may only require a state something writes.
    """
    import re
    src = (_SRC / "routers" / "operator_applications.py").read_text(encoding="utf-8")
    return set(re.findall(r'app_record\.status\s*=\s*"([a-z]+)"', src)) | set(
        re.findall(r'\bstatus\s*=\s*"([a-z]+)"\s*,', src))


def test_the_guard_accepts_the_row_shape_activation_actually_leaves(monkeypatch):
    """/operators/activate stamps activated_at and leaves the status at "approved". That row, and only that row
    plus a real timestamp, is what an activated application looks like in this database."""
    import datetime
    may = _may_rebundle(monkeypatch)
    ok, why = may("approved", datetime.datetime(2026, 9, 16, tzinfo=datetime.timezone.utc))
    assert ok is True, f"the shape activation leaves was refused: {why}"


@pytest.mark.parametrize("status,activated,why_not", [
    ("approved", None, "never activated"),
    ("pending", "2026-09-16", "not yet approved"),
    ("rejected", "2026-09-16", "rejected"),
    ("revoked", "2026-09-16", "revoked: must not be handed fresh credentials"),
    ("suspended", "2026-09-16", "suspended: must not be handed fresh credentials"),
])
def test_the_guard_refuses_every_other_state(monkeypatch, status, activated, why_not):
    may = _may_rebundle(monkeypatch)
    ok, _ = may(status, activated)
    assert ok is False, why_not


def test_the_guard_never_requires_a_status_no_writer_writes(monkeypatch):
    """THE TEST THAT WOULD HAVE CAUGHT IT, and the reason this file exists at all.

    V0386 shipped `status == "activated"`, a value taken from models.py's docstring. The only occurrence of that
    string as a status anywhere in the tree was the guard reading it, so the recovery could not run for any
    application in any state and the route it rescues answered 500 naming a status the product does not have.
    Asserting the accepted set is drawn from what the WRITERS write pins the class, not the instance: any future
    guard that invents a state fails here, whatever the invented word happens to be.
    """
    import datetime
    may = _may_rebundle(monkeypatch)
    written = _statuses_the_writers_write()
    assert {"pending", "approved", "rejected", "revoked", "suspended"} <= written, (
        f"the writer census itself looks wrong ({sorted(written)}); fix the census before trusting this test")
    assert "activated" not in written, "if the product now writes 'activated', this test and the guard both move"
    now = datetime.datetime(2026, 9, 16, tzinfo=datetime.timezone.utc)
    accepted = {s for s in written | {"activated"} if may(s, now)[0]}
    assert accepted, "the guard accepts nothing at all, which is how V0386 shipped"
    assert accepted <= written, f"the guard accepts {sorted(accepted - written)}, which no writer ever writes"


# ── the operator's environment, driven against the REAL generator ────────────────────────────────────────────────
# ⚠ TWO SCRIPTS, ONE NAME, AND THE BUNDLE CARRIES THE SECOND. The first writes the environment to STDOUT; the
# second writes .env.operator and pgbouncer.ini as FILES, relative to the current directory. V0387 handled only
# the first, and this fixture named only the first, so the suite agreed with the mistake for the same reason the
# mistake was made. Both are exercised below, from a cwd that is not the stack dir, which is the only arrangement
# that can tell them apart. [[feedback_a_fixture_from_the_same_assumption_tests_the_assumption]]
_DIST = pathlib.Path("/opt/theprotocol/stack/Agentvault2/scripts/distribution")
_GEN_STDOUT = _DIST / "generate-operator-env.sh"                      # 2953 B, `> .env.operator`
_GEN_FILES = _DIST / "nginx-templates" / "generate-operator-env.sh"   # 3293 B, `cat > .env.operator`
_GEN = _GEN_STDOUT

# The nine the generator mints that the compose cannot start without. Named here ONLY as the regression's own
# witness; the gate in host_work derives its list from the compose, because a list in code rots and a derived
# one cannot.
_GENERATED = ("API_KEY_SECRET", "JWT_SECRET_KEY", "PG_PASS_REGISTRY", "PG_PASS_TEG", "SECRET_KEY",
              "TEG_ADMIN_API_KEY", "TEG_AVTP_SYSTEM_API_KEY", "TEG_REGISTRY_JWT_SECRET", "TEG_TOKEN_SIGNING_KEY")


def _hw():
    spec = importlib.util.spec_from_file_location("_opdist_hw_env", _SRC / "host_work.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not (_GEN_STDOUT.exists() and _GEN_FILES.exists()),
                    reason="both real generator scripts are needed and are not on this host")
@pytest.mark.parametrize("which", ["stdout generator", "the one the bundle carries"])
def test_the_generated_environment_reaches_the_file_the_compose_reads(tmp_path, monkeypatch, which):
    """THE REGRESSION, run against the REAL script from a DIFFERENT working directory.

    beacon/jelgava (job 743d3afefe944696): the generator writes every value to stdout and writes no file at all,
    `_run` captured that and dropped it, and .env.operator was created by the append alone. The compose
    interpolates the nine missing names with no default, so both Postgres containers came up with a BLANK
    password and crash-looped while seven services sat Created. Nothing raised: compose warns and continues.
    """
    src = _GEN_STDOUT if which == "stdout generator" else _GEN_FILES
    stack = tmp_path / "cloud-op-jelgava"
    stack.mkdir()
    (stack / "generate-operator-env.sh").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    (stack / "docker-compose.operator.yml").write_text(
        "services:\n  registry:\n    environment:\n"
        "      PG: ${PG_PASS_REGISTRY}\n      K: ${API_KEY_SECRET}\n      W: ${WORKERS:-4}\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)          # the one-shot's cwd is /app, never the stack dir

    mod = _hw()
    notes = []
    spec = {"env": {"CENTRAL_REGISTRY_URL": "https://beacon.theprotocol.cloud"},
            "operator_secrets": {k: "z" * 64 for k in
                                 ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                  "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG", "AUDITOR_RO_PASSWORD")}}
    env_path = mod._write_operator_env(spec, str(stack), "jelgava", notes)

    assert list(elsewhere.iterdir()) == [], "the generator's output landed in the cwd, not the stack dir"
    text = pathlib.Path(env_path).read_text(encoding="utf-8")
    names = {ln.split("=", 1)[0].strip() for ln in text.splitlines() if "=" in ln and not ln.lstrip().startswith("#")}
    missing = [n for n in _GENERATED if n not in names]
    assert not missing, f"the compose cannot start without these and they are absent: {missing}"
    assert "CENTRAL_REGISTRY_URL" in names, "the registry's own values must still be appended after the generated ones"
    assert oct(pathlib.Path(env_path).stat().st_mode)[-3:] == "600"


@pytest.mark.skipif(not _GEN.exists(), reason="the real generator script is not on this host")
def test_a_variable_the_compose_needs_and_nothing_sets_is_refused(tmp_path, monkeypatch):
    """The derived gate: the failure it guards is silent, because compose substitutes a blank and warns."""
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    (stack / "generate-operator-env.sh").write_text(_GEN.read_text(encoding="utf-8"), encoding="utf-8")
    (stack / "docker-compose.operator.yml").write_text(
        "services:\n  db:\n    environment:\n      P: ${A_NAME_NOTHING_EVER_SETS}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    mod = _hw()
    with pytest.raises(mod.HostWorkRefused) as e:
        mod._write_operator_env({"env": {}, "operator_secrets": {}}, str(stack), "x", [])
    assert "A_NAME_NOTHING_EVER_SETS" in str(e.value)


def test_a_failure_after_writes_is_not_reported_as_nothing_was_done():
    """Exit 3 means the caller may re-run unchanged; exit 4 means the frame has state. jelgava failed at
    `compose up` with a stack dir, an extracted bundle, updated SANs, ten containers and a chowned ACL file
    behind it, and was recorded as "nothing was done" — the one thing that was not true."""
    mod = _hw()
    assert mod._failure_class() is mod.HostWorkRefused, "before any write, a failure IS a refusal"
    mod._side_effect("stack dir /opt/theprotocol/stack/cloud-op-x")
    assert mod._failure_class() is mod.HostWorkFailed, "after a write it must never read as a refusal"
    assert not issubclass(mod.HostWorkFailed, mod.HostWorkRefused), (
        "HostWorkFailed must not be catchable as a refusal, or main() maps it to exit 3 again")


@pytest.mark.skipif(not _GEN_FILES.exists(), reason="the bundle's generator is not on this host")
def test_the_pooler_carries_the_same_passwords_as_the_environment(tmp_path, monkeypatch):
    """A placeholder pooler lets every container start and then fails every query behind them.

    Only the file-writing generator produces pgbouncer.ini, and only when it runs IN the stack dir, so this is the
    half that a captured-stdout fix cannot reach. The values are compared in memory and never read out.
    """
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    (stack / "generate-operator-env.sh").write_text(_GEN_FILES.read_text(encoding="utf-8"), encoding="utf-8")
    (stack / "docker-compose.operator.yml").write_text("services:\n  db:\n    image: x\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    mod = _hw()
    env_path = mod._write_operator_env({"env": {}, "operator_secrets": {}}, str(stack), "x", [])

    env = {ln.split("=", 1)[0].strip(): ln.split("=", 1)[1].strip()
           for ln in pathlib.Path(env_path).read_text(encoding="utf-8").splitlines()
           if "=" in ln and not ln.lstrip().startswith("#")}
    pgb = (stack / "pgbouncer.ini").read_text(encoding="utf-8")
    import re as _re
    for db, var in (("agentvault_registry", "PG_PASS_REGISTRY"), ("teg_layer", "PG_PASS_TEG")):
        line = next(l for l in pgb.splitlines() if l.strip().startswith(f"{db} ="))
        got = _re.search(r"password=(\S+)", line).group(1)
        assert env.get(var), f"{var} is not in the environment at all"
        assert got == env[var], f"the pooler's {db} password is not the one {var} sets"
    assert list(elsewhere.iterdir()) == [], "the generator wrote into the cwd instead of the stack dir"


@pytest.mark.skipif(not _GEN_FILES.exists(), reason="the bundle's generator is not on this host")
def test_a_pooler_left_holding_placeholders_is_refused(tmp_path, monkeypatch):
    stack = tmp_path / "cloud-op-y"
    stack.mkdir()
    (stack / "generate-operator-env.sh").write_text(_GEN_FILES.read_text(encoding="utf-8"), encoding="utf-8")
    (stack / "docker-compose.operator.yml").write_text("services:\n  db:\n    image: x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    mod = _hw()
    real = mod._write_operator_env
    # Let the generator run once, then take it away: a stack dir whose environment exists and whose pooler was
    # left holding the bundle's placeholders is exactly the state a partial or hand-finished provision leaves,
    # and it is the state the gate has to catch. Re-running WITH the generator present would simply regenerate a
    # correct pooler, which is the fix working and proves nothing about the gate.
    env_path = real({"env": {}, "operator_secrets": {}}, str(stack), "y", [])
    (stack / "generate-operator-env.sh").unlink()
    (stack / "pgbouncer.ini").write_text(
        "[databases]\nagentvault_registry = host=db port=5432 dbname=agentvault_registry user=registry "
        "password=CHANGEME\nteg_layer = host=teg-db port=5432 dbname=teg_layer user=teg password=CHANGEME\n",
        encoding="utf-8")
    with pytest.raises(mod.HostWorkRefused) as e:
        real({"env": {}, "operator_secrets": {}}, str(stack), "y", [])
    assert "pgbouncer.ini" in str(e.value) and "CHANGEME" not in str(e.value), (
        "the refusal must name the fields and never the values")
    assert pathlib.Path(env_path).exists()


# ── V0389: what beacon's first working stack phase found ─────────────────────────────────────────────────────────
def test_the_summary_line_asks_the_phase_for_its_keys(tmp_path):
    """A STACK job that did everything right exited 1 AFTER writing result.json, because the last line named
    bundle keys unconditionally. The runner marked it failed, the registry answered 500, and an operator with ten
    healthy containers got no edge, no ACL net and no links (job 7db049e854644bff)."""
    mod = _hw()
    import json as _json
    for phase, result in (
        ("stack", {"phase": "stack", "stack_dir": "/opt/theprotocol/stack/cloud-op-x", "container_count": 10,
                   "notes": ["a", "b"]}),
        ("bundle", {"phase": "bundle", "bundle_path": "/b/x.tar.gz", "bundle_filename": "x.tar.gz",
                    "spire_entries_registered": 3, "notes": []}),
    ):
        spec_p, res_p = tmp_path / f"{phase}.spec", tmp_path / f"{phase}.result"
        res_p.write_text(_json.dumps(result), encoding="utf-8")
        spec_p.write_text("{}", encoding="utf-8")
        # main()'s summary must survive every phase's own result shape, which is what RESULT_KEYS_BY_PHASE says.
        keys = mod.RESULT_KEYS_BY_PHASE[phase]
        summary = {"phase": result.get("phase")}
        for k in keys:
            if k in result and k != "notes":
                summary[k] = result[k]
        assert _json.dumps(summary), f"the {phase} summary must be serialisable from its own keys alone"
        assert "bundle_filename" not in summary or phase != "stack"


def test_every_directory_the_compose_binds_is_made_before_up(tmp_path):
    """Docker creates a missing bind source as a root-owned directory and says nothing. `./bundle-storage` was
    absent from the bundle, so the operator's uid-1000 registry could not write it, migration 0076 died on
    os.makedirs, the whole upgrade rolled back, and the operator served health on a database with ZERO tables."""
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    (stack / "nginx").mkdir(parents=True)
    (stack / "nginx" / "nginx-federation.conf").write_text("server {}\n", encoding="utf-8")
    compose = stack / "docker-compose.operator.yml"
    compose.write_text(
        "services:\n"
        "  registry:\n    volumes:\n"
        "      - ./bundle-storage:/app/bundle-storage\n"
        "      - ./nginx:/etc/nginx/conf.d:ro\n"
        "      - './spire/agent':/run/spire\n"
        "      - registry-data:/data\n"
        "      - /var/run/docker.sock:/var/run/docker.sock\n", encoding="utf-8")
    notes = []
    mod._ensure_bind_sources(str(compose), str(stack), notes)
    assert (stack / "bundle-storage").is_dir(), "the directory Docker would have made as root"
    assert (stack / "spire" / "agent").is_dir(), "a quoted, nested source counts too"
    assert oct((stack / "bundle-storage").stat().st_mode)[-3:] != "000"
    # named volumes and absolute host paths are not ours to create
    assert not (stack / "registry-data").exists()
    assert "bundle-storage" in notes[0]


def test_a_file_shaped_bind_source_the_bundle_did_not_carry_is_refused(tmp_path):
    """Creating a directory in its place would turn a clear absence into a mount that silently shadows the file."""
    mod = _hw()
    stack = tmp_path / "cloud-op-y"
    stack.mkdir()
    compose = stack / "docker-compose.operator.yml"
    compose.write_text("services:\n  db:\n    volumes:\n      - ./pgbouncer.ini:/etc/pgbouncer.ini:ro\n",
                       encoding="utf-8")
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._ensure_bind_sources(str(compose), str(stack), [])
    assert "pgbouncer.ini" in str(e.value)
    assert not (stack / "pgbouncer.ini").exists(), "it must not invent the file it is refusing about"


def test_a_dsn_is_redacted_rather_than_truncated():
    """`url[:50]` is the same credential with fewer characters. It put a live operator password's prefix into an
    operator's own log, and the same line existed in prod_seed, plus two in database.py that logged the WHOLE
    DSN at WARNING and ERROR on every registry that needed the asyncpg adjustment."""
    spec = importlib.util.spec_from_file_location("_opdist_dsn", _SRC / "core" / "dsn.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for url, secret in (
        ("postgresql+asyncpg://registry:S3cr3tP@ss@db:5432/agentvault_registry", "S3cr3tP"),
        ("postgresql://registry:hunter2@teg-db:5432/teg_layer", "hunter2"),
        ("postgresql://registry:p@ss@w0rd@db/x", "w0rd"),
    ):
        out = mod.redact_dsn(url)
        assert secret not in out, f"a fragment of the password survived: {out}"
        assert "<redacted>" in out
        assert out[:50] != url[:50] or "@" not in url, "the redaction must differ from the truncation it replaces"
    # the parts a log line is FOR are kept
    kept = mod.redact_dsn("postgresql+asyncpg://registry:x@db:5432/agentvault_registry")
    for part in ("registry", "db:5432", "agentvault_registry", "postgresql+asyncpg"):
        assert part in kept
    assert mod.redact_dsn("") == "<empty>" and mod.redact_dsn(None) == "<empty>"
    assert mod.redact_dsn("postgresql://db/nopassword") == "postgresql://db/nopassword"


_AUDITOR_SRC = pathlib.Path("/opt/theprotocol/stack/Agentvault2/Agents/TheAuditor/src/auditor/main.py")


@pytest.mark.skipif(not _AUDITOR_SRC.exists(), reason="the auditor's source is not on this host")
def test_the_auditor_role_can_read_exactly_what_the_auditor_reads():
    """DERIVED FROM THE AUDITOR'S OWN SQL, so the grant and the reader cannot drift apart.

    The grant named two tables and the auditor's venue path reads three: SHARE_LAST_PRICE, SHARE_ACTIVITY and
    SHARE_SPARK all read exchange_trades, so three of its five queries answered `permission denied` and the venue
    reported as unreachable — the same word a dead connection gets, which is how it stayed unexplained.
    """
    import re as _re
    mod = _hw()
    src = _AUDITOR_SRC.read_text(encoding="utf-8")
    wanted = set()
    for name in mod.AUDITOR_VENUE_QUERIES:
        m = _re.search(name + r"""\s*=\s*("{3}|'{3})(.*?)\1""", src, _re.S)
        assert m, f"{name} is not in the auditor's source under that name any more; this test must follow it"
        for t in _re.findall(r"(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)", m.group(2), _re.I):
            if t.lower() not in ("lateral",):
                wanted.add(t.lower())
    granted = set()
    for sql in mod._AUDITOR_RO_SQL:
        m = _re.search(r"GRANT SELECT ON (.+?) TO auditor_ro", sql)
        if m:
            granted |= {t.strip().lower() for t in m.group(1).split(",")}
    assert wanted, "the derivation found no tables, so it is measuring itself"
    assert wanted <= granted, f"the auditor reads {sorted(wanted - granted)} and the role cannot"
    # and the other direction: a grant wider than the reader is authority nobody asked for
    assert granted <= wanted, f"the role may read {sorted(granted - wanted)}, which the auditor never reads"


# ── V0391: the operator database's own identity ──────────────────────────────────────────────────────────────────
def _attestation_cert(stack_dir):
    """A real self-signed cert, so the fingerprint is derived the way the provisioner derived the original."""
    import datetime as _dt
    import hashlib as _hl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "operator-attestation")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(minutes=5))
            .not_valid_after(now + _dt.timedelta(days=1)).sign(key, hashes.SHA256()))
    d = pathlib.Path(stack_dir) / "spire"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent-attestation.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return _hl.sha1(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def test_the_fingerprint_is_derived_from_the_certificate_the_bundle_carries(tmp_path):
    """Carried, it could disagree with the certificate an agent presents and register a parentID nothing attests
    as. Derived, it cannot: it is the SHA-1 of the same DER generate_attestation_certs hashed."""
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    expected = _attestation_cert(str(stack))
    assert mod._fingerprint_from_attestation(str(stack)) == expected
    assert len(expected) == 40 and all(c in "0123456789abcdef" for c in expected)
    # absent is EMPTY and says so by being falsy, never a guess
    assert mod._fingerprint_from_attestation(str(tmp_path / "nothing-here")) == ""


def test_without_the_override_no_data_entry_is_registered(tmp_path, monkeypatch):
    """The override ships separately from this image, so until it exists the stack must behave exactly as before.
    Four running frames share the live templates directory; a change that needed both halves at once would break
    operator provisioning on all of them."""
    mod = _hw()
    called = []
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_data_entry=lambda *a, **k: called.append(a) or 1))
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    (tmp_path / "templates").mkdir()
    notes = []
    out = mod._db_tls_steps({"nginx_templates_dir": str(tmp_path / "templates")}, str(stack), "x", notes)
    assert out == {"db_tls": False} and called == []
    assert "no override" in notes[0]


def test_with_the_override_the_entry_is_registered_before_anything_starts(tmp_path, monkeypatch):
    mod = _hw()
    seen = {}
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_data_entry=lambda name, fp, dns: seen.update(name=name, fp=fp, dns=dns) or 1))
    stack = tmp_path / "cloud-op-jelgava"
    stack.mkdir()
    fp = _attestation_cert(str(stack))
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    # ⚠ A REAL OVERRIDE NAMES ITS COMPANIONS, and V0392 derives the copy list from those names rather than from
    # a hardcoded tuple. An override that referenced nothing was a fixture testing the old shape.
    (tmpl / mod.DB_TLS_OVERRIDE).write_text(
        "services:\n  db:\n    volumes:\n      - ./pg-tls-sync.sh:/usr/local/bin/pg-tls-sync.sh:ro\n"
        "      - ./pg_hba_operator.conf:/etc/postgresql/pg_hba.conf:ro\n    command: -c ssl=on\n",
        encoding="utf-8")
    (tmpl / "pg-tls-sync.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmpl / "pg_hba_operator.conf").write_text("hostnossl all auditor_ro 0.0.0.0/0 reject\n", encoding="utf-8")
    notes = []
    out = mod._db_tls_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "jelgava", notes)
    assert out["db_tls"] is True
    assert (stack / mod.DB_TLS_OVERRIDE).exists(), "materialised from the LIVE templates, not from the bundle"
    assert oct((stack / "pg-tls-sync.sh").stat().st_mode)[-3:] == "755"
    assert seen["fp"] == fp, "the entry must be registered under the certificate's own fingerprint"
    assert seen["dns"] == "cloud-op-jelgava-db", "the DNS SAN is the name the auditor verifies"
    assert (stack / "pg_hba_operator.conf").exists(), "a companion the override NAMES must be carried with it"


def test_an_override_whose_entry_did_not_register_refuses_before_up(tmp_path, monkeypatch):
    """A stack dir carrying the override with no entry is a database waiting forever for a certificate nobody
    issued, and compose blocks on it to the job's ceiling. Refused instead."""
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_data_entry=lambda *a, **k: 0))
    stack = tmp_path / "cloud-op-y"
    stack.mkdir()
    _attestation_cert(str(stack))
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    (tmpl / mod.DB_TLS_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._db_tls_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "y", [])
    assert "wait forever" in str(e.value) and "Nothing was brought up" in str(e.value)


def test_an_override_with_no_attestation_certificate_refuses(tmp_path, monkeypatch):
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_data_entry=lambda *a, **k: 1))
    stack = tmp_path / "cloud-op-z"
    stack.mkdir()
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    (tmpl / mod.DB_TLS_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._db_tls_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "z", [])
    assert "agent-attestation.crt" in str(e.value)


def test_a_companion_the_override_names_and_nothing_carries_is_refused(tmp_path, monkeypatch):
    """Derived, not listed: the copy set comes from the override's own `./` references. A name it uses and the
    templates lack would otherwise be created by Docker as a root-owned directory and mounted over the file."""
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_data_entry=lambda *a, **k: 1))
    stack = tmp_path / "cloud-op-w"
    stack.mkdir()
    _attestation_cert(str(stack))
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    (tmpl / mod.DB_TLS_OVERRIDE).write_text(
        "services:\n  db:\n    volumes:\n      - ./a-file-nobody-ships.conf:/etc/x:ro\n", encoding="utf-8")
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._db_tls_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "w", [])
    assert "a-file-nobody-ships.conf" in str(e.value)


def test_the_bind_gate_reads_the_override_too(tmp_path):
    """A gate that looks at fewer files than the command it guards is not guarding it. The override is passed to
    `up` with its own -f, so its `./` binds are as real as the base file's."""
    mod = _hw()
    stack = tmp_path / "cloud-op-v"
    stack.mkdir()
    base = stack / "docker-compose.operator.yml"
    base.write_text("services:\n  registry:\n    volumes:\n      - ./bundle-storage:/app/bundle-storage\n",
                    encoding="utf-8")
    override = stack / mod.DB_TLS_OVERRIDE
    override.write_text("services:\n  db:\n    volumes:\n      - ./certs-data:/certs\n", encoding="utf-8")
    notes = []
    mod._ensure_bind_sources(str(base), str(stack), notes, extra_composes=[str(override)])
    assert (stack / "bundle-storage").is_dir()
    assert (stack / "certs-data").is_dir(), "a directory only the override binds is still Docker's to create"


@pytest.mark.parametrize("status,reason,action,why", [
    ("INACTIVE", "teardown", "revive", "the state a teardown leaves, and the one a re-provision undoes"),
    # ⚠ THE STATE THAT ACTUALLY EXISTED. After jelgava's successful re-provision the row read ACTIVE with
    # deactivated_reason still "teardown": something other than the provision path flips the status and leaves
    # the fields. A predicate that only fired on INACTIVE would never have run against the real row.
    ("ACTIVE", "teardown", "clear_stale", "an ACTIVE row must not go on claiming it was torn down"),
    ("INACTIVE", "self_echo", "", "a guard-set row from the boot reclassify pass"),
    ("INACTIVE", "duplicate_frame", "", "another guard-set row"),
    ("INACTIVE", "federation_revoked", "", "a revoked federation is not this operator's teardown"),
    ("INACTIVE", "admin_deactivated", "", "an admin took it down for a reason a provision does not know"),
    ("ACTIVE", "admin_deactivated", "", "and the same is true once something has flipped the status"),
    ("INACTIVE", "", "", "no recorded reason is not a teardown"),
    ("INACTIVE", None, "", "nor is none at all"),
    ("ACTIVE", None, "", "already up and carrying nothing stale"),
    ("PENDING", None, "", "never approved"),
])
def test_a_re_provision_fixes_only_what_its_own_teardown_left(monkeypatch, status, reason, action, why):
    """A re-provision is the admin provisioning the SAME application again, which is what "never auto-revived"
    exists to protect; it is not an amnesty for every other way a row can be down or mislabelled."""
    mod, _ = _load_client(monkeypatch)
    got, _ = mod.peer_row_action(status, reason)
    assert got == action, why


def test_the_reason_is_read_from_wherever_the_runner_put_it(monkeypatch):
    """`reason` was taught to the refused branch and not the failed one, so a provision that died on a dependency
    logged "no reason given" while operator_status carried the sentence (job 908a9513d677432c)."""
    mod, _ = _load_client(monkeypatch)
    assert mod._reason_from({"reason": "container is unhealthy"}, {}) == "container is unhealthy"
    assert mod._reason_from({"refused_reason": "spec mismatch"}, {}) == "spec mismatch"
    assert mod._reason_from({"error": "boom"}, {}) == "boom"
    assert mod._reason_from({}, {"error": "outer"}) == "outer"
    assert mod._reason_from({"refused": True}, {}) == "", "a bare flag is not a reason"
    assert mod._reason_from({}, {}) == ""
    # precedence: the runner's own sentence wins over a generic error
    assert mod._reason_from({"reason": "the real cause", "error": "generic"}, {}) == "the real cause"


def test_a_failed_job_says_whether_the_one_shot_had_already_written(monkeypatch):
    """Exit 4 is the one-shot reporting that the frame has state. A caller must not read it as the clean,
    re-runnable failure a refusal is."""
    import asyncio
    mod, fake = _load_client(monkeypatch)
    fake.answers = [{"started": True, "job_id": "j9"},
                    {"job": {"id": "j9", "state": "failed", "exit_code": 4,
                             "reason": "dependency failed to start: container cloud-op-x-teg is unhealthy"}}]
    with pytest.raises(fake.RunnerError) as e:
        asyncio.run(mod.provision_through_runner(frame="beacon", spec={"phase": "stack"}, poll_interval_s=0))
    assert "already written" in str(e.value)
    assert "cloud-op-x-teg is unhealthy" in str(e.value), "the runner's reason must reach the caller's error"


def test_the_base_compose_comes_from_the_live_templates_not_the_frozen_bundle(tmp_path, monkeypatch):
    """jelgava's bundle compose was 32 lines behind the template by the time it was provisioned, so a fix to the
    base could not reach it while the override, read live, could. Two halves of one `up` from two generations is
    the staleness the override design refuses; the base is not an exception to it."""
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    frozen = "services:\n  teg-layer:\n    depends_on:\n      teg-db: {condition: service_healthy}\n"
    (stack / "docker-compose.operator.yml").write_text(frozen, encoding="utf-8")
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    live = ("services:\n  teg-layer:\n    depends_on:\n      teg-db: {condition: service_healthy}\n"
            "      pgbouncer: {condition: service_healthy}\n      redis: {condition: service_healthy}\n")
    (tmpl / "docker-compose.operator.yml").write_text(live, encoding="utf-8")

    # drive just the step that chooses, by calling the private helper the stack phase uses for its templates dir
    notes = []
    _tmpl_base = str(tmpl / "docker-compose.operator.yml")
    assert os.path.exists(_tmpl_base)
    # emulate the choice the stack phase makes, and assert the property it must have
    import shutil as _sh
    _sh.copyfile(_tmpl_base, str(stack / "docker-compose.operator.yml"))
    got = (stack / "docker-compose.operator.yml").read_text(encoding="utf-8")
    assert "pgbouncer" in got, "the live base must win over the bundle's frozen copy"
    assert got != frozen

    # and the module names the behaviour it implements, so the choice is not a silent one
    src = (_SRC / "host_work.py").read_text(encoding="utf-8")
    assert "base taken from the live templates" in src, "the note that tells a reader which generation ran"
    assert "the templates carry no base" in src, "and the other outcome, said rather than assumed"


def test_the_live_base_is_taken_before_the_gate_that_reads_it():
    """⚠ THE ORDER IS THE DEFECT, so the order is what this reads.

    V0393 took the live base AFTER the env step, so the coverage gate read the BUNDLE's compose while `up` ran
    the live one: a no-default variable only the live base interpolates would have reached `up` blank — the very
    failure the gate exists to stop, reintroduced by the fix for a different staleness (agentvault2-6a read it in
    the V0393 image). My first attempt at this test drove the two helpers directly, in the order the TEST chose,
    so it passed against V0393's own ordering: a test that could not fail for the thing it was named after. The
    ordering lives in _stack_steps' statement list, so that is what is read.
    """
    import ast as _ast
    tree = _ast.parse((_SRC / "host_work.py").read_text(encoding="utf-8"))
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and n.name == "_stack_steps")
    order = []
    for node in _ast.walk(fn):
        if isinstance(node, _ast.Call) and getattr(node.func, "id", "") in ("_take_live_base",
                                                                           "_write_operator_env"):
            order.append((node.lineno, node.func.id))
    names = [n for _, n in sorted(order)]
    assert "_take_live_base" in names and "_write_operator_env" in names, f"one of the two is gone: {names}"
    assert names.index("_take_live_base") < names.index("_write_operator_env"), (
        f"the gate would read the bundle's generation while `up` runs the live one: {names}")


@pytest.mark.skipif(not _GEN_STDOUT.exists(), reason="the real generator script is not on this host")
def test_the_gate_reads_the_live_content_once_it_is_there(tmp_path, monkeypatch):
    """And the content half: with the live base in place, a variable only IT needs is caught."""
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    # the bundle's frozen copy needs nothing the generator does not set
    (stack / "docker-compose.operator.yml").write_text(
        "services:\n  db:\n    environment:\n      P: ${PG_PASS_REGISTRY}\n", encoding="utf-8")
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    (tmpl / "generate-operator-env.sh").write_text(_GEN_STDOUT.read_text(encoding="utf-8"), encoding="utf-8")
    # the LIVE base needs one more, which no generator mints
    (tmpl / "docker-compose.operator.yml").write_text(
        "services:\n  db:\n    environment:\n      P: ${PG_PASS_REGISTRY}\n      Q: ${ONLY_THE_LIVE_BASE_WANTS_THIS}\n",
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    notes = []
    mod._take_live_base(str(stack), str(tmpl), notes)
    assert "base taken from the live templates" in notes[0]
    with pytest.raises(mod.HostWorkRefused) as e:
        mod._write_operator_env({"env": {}, "operator_secrets": {}}, str(stack), "x", [])
    assert "ONLY_THE_LIVE_BASE_WANTS_THIS" in str(e.value), (
        "the gate must read the generation `up` will run, not the one the bundle froze")


def test_the_generator_comes_from_the_same_generation_as_the_compose(tmp_path):
    """§SECFIX (2026-09-25): the compose mounts what the generator writes (userlist.txt), so the two travel together.

    Measured on the test frame secfixt: an operator activated BEFORE the pooler change was re-provisioned with the live
    compose (which mounts userlist.txt) and the bundle's generator (which never wrote it), and the bind check refused.
    The live base now brings the live generator; without a live base, both stay the bundle's."""
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    (stack / "docker-compose.operator.yml").write_text("services:\n  db:\n    image: old\n", encoding="utf-8")
    (stack / "generate-operator-env.sh").write_text("# the bundle's generation\n", encoding="utf-8")
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    (tmpl / "docker-compose.operator.yml").write_text("services:\n  db:\n    image: new\n", encoding="utf-8")
    (tmpl / "generate-operator-env.sh").write_text("# the live generation\n", encoding="utf-8")
    notes = []
    mod._take_live_base(str(stack), str(tmpl), notes)
    assert (stack / "generate-operator-env.sh").read_text(encoding="utf-8") == "# the live generation\n"
    assert any("generator: taken from the live templates" in n for n in notes), notes
    # no live base: nothing moves, the pair stays the bundle's
    stack2 = tmp_path / "cloud-op-y"
    stack2.mkdir()
    (stack2 / "generate-operator-env.sh").write_text("# the bundle's generation\n", encoding="utf-8")
    empty = tmp_path / "no-templates"
    empty.mkdir()
    (empty / "generate-operator-env.sh").write_text("# the live generation\n", encoding="utf-8")
    mod._take_live_base(str(stack2), str(empty), [])
    assert (stack2 / "generate-operator-env.sh").read_text(encoding="utf-8") == "# the bundle's generation\n"


def test_a_variable_named_only_in_a_comment_is_not_an_interpolation(tmp_path):
    """The override's only regex hit is ${REGISTRY_NAME} inside its own header comment. A raw-text gate would
    demand a variable nothing substitutes, and a gate that refuses a correct stack costs as much as one that
    passes a broken one."""
    mod = _hw()
    text = ("# the writer renders ${REGISTRY_NAME}-db into the SAN\n"
            "services:\n  db:\n    environment:\n      A: ${REAL_ONE}   # trailing ${NOT_THIS} either\n"
            "      B: ${HAS_A_DEFAULT:-fine}\n")
    got = mod._compose_interpolations(text)
    assert got == {"REAL_ONE"}, got


def test_the_env_gate_reads_the_override_too(tmp_path, monkeypatch):
    """`up` passes base and override, so the coverage gate reads both."""
    mod = _hw()
    stack = tmp_path / "cloud-op-y"
    stack.mkdir()
    (stack / "docker-compose.operator.yml").write_text("services:\n  db:\n    image: x\n", encoding="utf-8")
    (stack / mod.DB_TLS_OVERRIDE).write_text(
        "services:\n  db:\n    environment:\n      Z: ${ONLY_THE_OVERRIDE_WANTS_THIS}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(mod.HostWorkRefused) as e:
        mod._write_operator_env({"env": {}, "operator_secrets": {}}, str(stack), "y", [])
    assert "ONLY_THE_OVERRIDE_WANTS_THIS" in str(e.value)


def test_the_provision_route_does_not_override_the_policy_the_service_applied():
    """⚠ THE UNIDENTIFIED RAIL, FOUND. For three versions we named "something that flips a peer row's status
    without its deactivation fields" as an open residue. It is the provision route itself: it wrote
    `existing_peer.status = "ACTIVE"` bare, a few lines below the service call that had just done the same job
    through the choke point. That is how a row came to read ACTIVE while still claiming it was torn down.

    Worse than the stale fields: the service asks peer_row_action, which deliberately REFUSES to revive a row
    deactivated for anything but its own teardown — and this line reactivated it anyway, so an admin's
    deactivation was undone by a provision, silently, with the admin's reason left stamped on the ACTIVE row.
    Read structurally because the route needs a database; the property is that the bare write is gone and the
    predicate and choke point are both consulted.
    """
    src = (_SRC / "routers" / "cloud_operators.py").read_text(encoding="utf-8")
    assert 'existing_peer.status = "ACTIVE"' not in src, (
        "the bare write is the defect: it moves the status and leaves the deactivation fields behind")
    assert "peer_row_action" in src, "the route must ask the same predicate the service asks"
    assert "update_peer_registry_status" in src, "and move the status through the one writer that clears both"
    # and the refusal must be LOUD: an operator provisioned into a row this frame will not federate with is a
    # half-state somebody has to decide about, not something to discover later from a quiet federation.
    assert "will not federate with it until that row is decided" in src


def test_the_prober_revives_only_rows_that_recorded_no_decision():
    """⚠ THE GUARD WAS A DENYLIST, SO A RECORDED REASON OUTSIDE IT WAS REVIVABLE — including free text.
    `deactivate?reason=...` passes the text through verbatim, so an admin who said WHY lost the row to the
    prober after two probes while an admin who said nothing kept it (the writer defaults to admin_deactivated,
    which is guarded). The careful answer was punished and the careless one protected; measured on beacon, a row
    with a free-text reason came back in 35 seconds. The worker's own docstring names what it is for — rows
    flipped by restarts, sync races and rename fan-outs, which record NO reason — so that is the rule.
    """
    src = (_SRC / "background_tasks" / "peer_revival_prober.py").read_text(encoding="utf-8")
    assert "_no_reason = [p for p in rows if not (p.deactivated_reason or \"\").strip()]" in src, (
        "the candidate set must be rows that recorded no decision, not everything outside a denylist")
    assert "PEER_DEACTIVATION_GUARD_REASONS" in src, "the denylist stays as the second, redundant check"
    # a row it declines must be said out loud, or a system path that starts stamping a reason goes quiet forever
    assert "carry a recorded reason and are left alone" in src
    # and the revival log must read the fields BEFORE the write that clears them
    assert "_was_reason, _was_since = peer.deactivated_reason, peer.deactivated_at" in src
    i_capture = src.index("_was_reason, _was_since = peer.deactivated_reason")
    i_write = src.index('db, peer, "ACTIVE", reason="auto_revival"')
    assert i_capture < i_write, "captured after the write, the line cannot say what it revived"
