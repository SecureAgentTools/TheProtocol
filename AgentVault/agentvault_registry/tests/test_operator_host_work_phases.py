"""§OPDIST — the one-shot's own door: what a spec must carry, and what it must NOT.

The runner checks the same properties before it launches this container (agentvault2-85, 599080a). Both doors check
deliberately: two that check disagree less often than one that assumes the other did. These pin THIS side, so a
change to the seam that only reaches one door is caught here rather than on a frame.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")


def _load():
    # It moved OUT of services/ on 2026-09-16: importing that package pulls the ORM and the settings object, which
    # need a database URL and an API key the one-shot must not hold, so the entry point died at import on every
    # frame. Both bases are accepted because OPDIST_SRC means the package root here and services/ in a sibling suite.
    path = _SRC / "host_work.py"
    if not path.exists():
        path = _SRC.parent / "host_work.py"
    spec = importlib.util.spec_from_file_location("_opdist_hostwork", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _spec(**over):
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    os.makedirs(frame_dir, exist_ok=True)
    base = dict(operator_name="Tartu", safe_name="tartu", operator_did="did:theprotocol:operator:tartu",
                frame="lantern", stack_root=root, frame_stack_dir=frame_dir, job_id="j1",
                docker_pull_token="dpt_" + "x" * 60,
                # Required of every bundle and full spec since 2026-09-16: without them the provisioner this
                # module loads falls to FRAME A's SPIRE server and trust domain.
                spire_container="lantern-spire-server", spire_trust_domain="lantern.theprotocol.cloud",
                spire_server_address="spire.lantern.theprotocol.cloud", spire_server_port="8444")
    base.update(over)
    return base


def _read(mod, spec):
    path = os.path.join(tempfile.mkdtemp(), "spec.json")
    with open(path, "w") as fh:
        json.dump(spec, fh)
    return mod.read_spec(path)


def test_a_bundle_spec_needs_no_secrets_and_a_full_one_does():
    mod = _load()
    assert _read(mod, _spec(phase="bundle"))["phase"] == "bundle"
    with pytest.raises(mod.HostWorkRefused) as e:
        _read(mod, _spec(phase="full"))
    assert "operator_secrets" in str(e.value) and "phase full" in str(e.value)


def test_secrets_in_a_bundle_spec_are_refused_rather_than_ignored():
    """Ignoring them would be the quiet wrong answer: the file is already on disk by then. Refusing says so while
    the caller can still stop sending them."""
    mod = _load()
    with pytest.raises(mod.HostWorkRefused) as e:
        _read(mod, _spec(phase="bundle", operator_secrets={"TEG_PROXY_TRUST_SECRET": "s" * 40}))
    assert "opens none of them" in str(e.value) and "Nothing was done" in str(e.value)


def test_an_unknown_phase_is_refused_not_defaulted():
    """Defaulting to the biggest thing would stand a stack up for a caller that asked for a bundle."""
    mod = _load()
    with pytest.raises(mod.HostWorkRefused) as e:
        _read(mod, _spec(phase="everything"))
    assert "is not one this module serves" in str(e.value)


def test_a_credential_at_any_depth_is_refused():
    """The full phase with its secrets, so that EVERY other field is satisfied and only the credential decides.

    A control that goes red for a different reason than the property it names is not a control: the first version of
    this test omitted operator_secrets, which the phase-aware rule makes legal and the older module refuses, so it
    would have reported the credential hunt as broken in a tree where it was fine.
    """
    mod = _load()
    secrets = {k: "s" * 40 for k in ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                     "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG")}
    assert _read(mod, _spec(phase="full", operator_secrets=secrets))["phase"] == "full"  # the same spec, clean
    with pytest.raises(mod.HostWorkRefused) as e:
        _read(mod, _spec(phase="full", operator_secrets=secrets,
                         env={"nested": {"DATABASE_URL": "postgres://u:p@h/db"}}))
    assert "DATABASE_URL" in str(e.value)


def test_the_bundle_goes_where_the_frames_registry_can_read_it():
    """The measurement that changed the design: this container's own /app/operator-bundles is destroyed when it
    returns, so a tar written there leaves the application row naming a path nothing can open."""
    mod = _load()
    notes = []
    spec = _spec(phase="bundle")
    out = mod._bundles_dir(spec, notes)
    assert out == os.path.join(spec["frame_stack_dir"], "operator-bundles") and os.path.isdir(out)

    with pytest.raises(mod.HostWorkRefused) as e:
        mod._bundles_dir({k: v for k, v in spec.items() if k != "frame_stack_dir"}, [])
    assert "destroyed when it returns" in str(e.value)

    with pytest.raises(mod.HostWorkRefused) as e:
        mod._bundles_dir(dict(spec, frame_stack_dir="/etc"), [])
    assert "not under the stack root" in str(e.value)


def test_the_entry_point_runs_with_no_database_and_no_api_key():
    """The one-shot is given neither, on purpose — so it must not need them to START.

    ⚠ MEASURED, NOT ASSUMED, and it was broken: while this module lived under `services`, running it as
    `python3 -m agentvault_registry.services.operator_host_work` ran that package's __init__, which imports
    webhook_service -> models -> database -> Settings, and Settings REQUIRES DATABASE_URL and API_KEY_SECRET. The
    container died at IMPORT on every frame, before reading a spec, and no refusal test could see it because the
    runner's refusals all happen before the container starts. This runs the real entry point with an environment
    carrying neither, and asserts it reaches its own contract.
    """
    import subprocess
    import sys

    src = _SRC if (_SRC / "host_work.py").exists() else _SRC.parent
    env = {"PYTHONPATH": str(src.parent), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    r = subprocess.run([sys.executable, "-m", "agentvault_registry.host_work"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2, f"exit {r.returncode}: {(r.stderr or r.stdout)[:400]}"
    assert "OPERATOR_SPEC and OPERATOR_RESULT must both be set" in (r.stdout + r.stderr)
    assert "DATABASE_URL" not in r.stderr and "ValidationError" not in r.stderr


def _stack_spec(root, frame_dir, **over):
    secrets = {k: "s" * 40 for k in ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                     "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG")}
    secrets["AUDITOR_RO_PASSWORD"] = "r" * 40
    spec = dict(operator_name="Tartu", safe_name="tartu", operator_did="did:theprotocol:operator:tartu",
                frame="lantern", stack_root=root, frame_stack_dir=frame_dir,
                frame_identity_network="lantern_network_identity", job_id="j1",
                docker_pull_token="dpt_" + "x" * 60, docker_username="operator-tartu",
                phase="stack", bundle_filename="tartu.tar.gz",
                operator_secrets=secrets,
                env={"FEDERATION_LICENSE_KEY": "flk_abc", "TEG_ID": "teg-tartu"},
                compose={"domain": "tartu.op.lantern.theprotocol.cloud", "reg_port": 31500, "fed_port": 31543,
                         "teg_port": 31580, "worker_count": 4, "identity_network": "a-caller-claim",
                         "es_url": "https://lantern-es.theprotocol.cloud"})
    spec.update(over)
    return spec


def _bundle_with_the_real_template(bundles_dir, name="tartu.tar.gz", with_federation_conf=False):
    """The SHIPPED template, so the adaptation is measured against the text an operator actually gets."""
    import tarfile
    tmpl = pathlib.Path("/opt/theprotocol/stack/Agentvault2/scripts/distribution/nginx-templates/"
                        "docker-compose.operator.yml")
    if not tmpl.exists():
        pytest.skip("the operator compose template is not on this host")
    work = tempfile.mkdtemp()
    (pathlib.Path(work) / "docker-compose.operator.yml").write_text(tmpl.read_text())
    members = ["docker-compose.operator.yml"]
    # ⚠ A REAL BUNDLE CARRIES THE GENERATOR, and this fixture did not until 2026-09-16 — so every stack-phase test
    # ran against an .env.operator missing the nine values the template interpolates with no default, and asserted
    # success. That is precisely the state that crash-looped beacon/jelgava's two Postgres containers. The fixture
    # was reproducing the defect and passing; the gate that now refuses it is what turned the fixture honest.
    # ⚠ THE COPY THE BUNDLE ACTUALLY CARRIES (nginx-templates, the file writer), not the stdout one a level up
    # that shares its name. Using the wrong one is how the suite agreed with a wrong fix.
    gen = pathlib.Path("/opt/theprotocol/stack/Agentvault2/scripts/distribution/nginx-templates/"
                       "generate-operator-env.sh")
    if not gen.exists():
        pytest.skip("the operator env generator is not on this host")
    (pathlib.Path(work) / "generate-operator-env.sh").write_text(gen.read_text())
    members.append("generate-operator-env.sh")
    # ⚠ AND EVERY FILE-SHAPED `./` SOURCE THE COMPOSE BINDS. A real bundle carries them (the provisioner adds the
    # nginx confs, the spire material and the ACL); this fixture did not, so it could not see that a missing bind
    # source is Docker's cue to create a ROOT-OWNED directory over it. Derived from the compose the fixture just
    # wrote, so it tracks the template instead of listing what the template happened to need today.
    import re as _re
    for src in sorted({m.group(1) for m in
                       _re.finditer(r"""^\s*-\s+["']?\./([^:"'\s]+)["']?:""", tmpl.read_text(), _re.M)}):
        if not os.path.splitext(src)[1]:
            continue                                   # bundle-storage: a DIRECTORY, and the one host_work makes
        if src == "redis-users.acl":
            # ⚠ NOT IN THE BUNDLE. Measured by listing a real one (beacon's jelgava.tar.gz: spire/*, nginx/*,
            # the compose, the generator, pgbouncer.ini — and nothing else). The ACL is written into the stack
            # dir by apply_operator_secrets DURING this phase, so a fixture that shipped it in the tar would be
            # testing a bundle that does not exist.
            continue
        p = pathlib.Path(work) / src
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture placeholder\n")
        members.append(src)
    if with_federation_conf:
        conf = pathlib.Path(work) / "nginx"
        conf.mkdir(exist_ok=True)   # the bind-source placeholders above may have made it
        (conf / "nginx-federation.conf").write_text(
            "server {\n    server_name nginx-federation;\n    set $upstream_teg teg-layer;\n}\n")
        members.append("nginx/nginx-federation.conf")
    path = os.path.join(bundles_dir, name)
    with tarfile.open(path, "w:gz") as t:
        for member in members:
            t.add(os.path.join(work, member), arcname=member)
    return path


def _stub_docker(mod, monkeypatch):
    """Everything that needs a socket, stubbed; everything that is this module's own logic, real."""
    import subprocess as sp                  # the REAL one: the module's own is stubbed below
    import types as _t

    def run(cmd, note, notes, timeout=600, cwd=None):
        # The extract runs for real, because an extract that fails silently leaves every later step working against
        # nothing — the defect this step exists to catch. THE ENV GENERATOR RUNS FOR REAL FOR THE SAME REASON, and
        # for want of that this stub hid the 2026-09-16 defect completely: `["true"]` returns empty stdout, which
        # is indistinguishable from a generator whose output this module drops on the floor. Neither needs a
        # socket. Everything else here does.
        # cwd is honoured, not swallowed: the generator the bundle carries writes .env.operator and pgbouncer.ini
        # RELATIVE to it, so a stub that dropped the argument would pass while the real thing wrote to /app.
        proc = sp.run(cmd if cmd[0] in ("tar", "bash") else ["true"], capture_output=True, text=True,
                      timeout=timeout, cwd=cwd)
        if proc.returncode != 0:
            raise mod.HostWorkRefused(f"{note} failed: {(proc.stderr or proc.stdout)[:200]}")
        notes.append(f"{note}: ok")
        return proc

    monkeypatch.setattr(mod, "_run", run)
    monkeypatch.setattr(mod, "_load_provisioner",
                        lambda: _t.SimpleNamespace(
                            # Writes the ACL the real one writes: this stub exists to remove the SOCKET, not the
                            # filesystem. Without it every stack test runs against a stack dir missing a file the
                            # compose binds, which V0389 correctly refuses — the tests would then all be asserting
                            # a state no provision can reach.
                            apply_operator_secrets=lambda target_dir, *a, **k: (
                                open(os.path.join(target_dir, "redis-users.acl"), "w").write("user default off\n")),
                            OPERATOR_SECRET_NAMES=("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                                   "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG",
                                                   "AUDITOR_RO_PASSWORD"),
                            OPERATOR_ENV_SECRET_NAMES=("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                                       "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG")))
    def _fake_run(cmd, *a, **k):
        # `compose ps -q` is counted by lines; `docker logs` is grepped for the first-boot banner; psql is the
        # parent peer row. Each answers as the real one does, so the step's OWN logic runs.
        if "logs" in cmd:
            return _t.SimpleNamespace(stdout="boot line\nFIRST-BOOT ADMIN PASSWORD: pw-from-the-log\n",
                                      stderr="", returncode=0)
        if "psql" in cmd:
            return _t.SimpleNamespace(stdout="INSERT 0 1", stderr="", returncode=0)
        return _t.SimpleNamespace(stdout="a\nb\nc\n", stderr="", returncode=0)

    monkeypatch.setattr(mod, "subprocess", _t.SimpleNamespace(run=_fake_run))
    monkeypatch.setattr(mod, "_await_registry",
                        lambda c, notes, deadline_s=240: {"registry_healthy": True, "registry_health_seconds": 12})


def test_the_stack_phase_reuses_the_activation_bundle_and_adapts_the_compose(monkeypatch):
    """The second half of a cloud operator, from the bundle activation already made.

    It must not build a second bundle: the application row already names this one's fingerprint and pull-token hash,
    so a rebuild would re-register SPIRE entries and leave the row describing a bundle nobody has.
    """
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)

    spec = _stack_spec(root, frame_dir, parent_peer={
        "name": "EU", "base_url": "https://lantern.theprotocol.cloud:8443",
        "admin_contact_email": "commander@theprotocol.cloud", "trust_domain": "lantern.theprotocol.cloud"})
    r = mod.do_host_work(spec)
    assert r["phase"] == "stack" and r["container_count"] == 3 and r["registry_healthy"] is True
    assert "bundle_path" not in r, "the stack phase must not report a bundle it did not build"
    # the operator's own first-boot credential comes back for the human who owns it, like the pull token went out
    assert r["admin_password"] == "pw-from-the-log"
    # and bilateral federation's other half: without the parent row the operator is half a peer
    assert r["parent_peer_registered"] is True

    compose = open(os.path.join(r["stack_dir"], "docker-compose.operator.yml")).read()
    assert '"31500:8000"' in compose and '"31543:8443"' in compose and '"31580:8080"' in compose
    # the identity network comes from the RUNNER's stamp, never the caller's claim beside it
    assert "lantern_network_identity:" in compose and "a-caller-claim" not in compose
    assert "tartu.op.lantern.theprotocol.cloud" in compose
    assert "https://lantern-es.theprotocol.cloud" in compose

    env_path = os.path.join(r["stack_dir"], ".env.operator")
    env = open(env_path).read()
    assert "FEDERATION_LICENSE_KEY=flk_abc" in env and env.count("s" * 40) == 4
    assert oct(os.stat(env_path).st_mode)[-3:] == "600"


def test_a_stack_phase_whose_bundle_is_not_on_the_frame_is_refused(monkeypatch):
    """A row naming a bundle the disk does not have is a disagreement a human must see, not one a rebuild hides."""
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    os.makedirs(os.path.join(frame_dir, "operator-bundles"))
    with pytest.raises(mod.HostWorkRefused) as e:
        mod.do_host_work(_stack_spec(root, frame_dir, bundle_filename="never-built.tar.gz"))
    assert "Nothing was done" in str(e.value) and "the disk does not have" in str(e.value)


def test_a_stack_spec_must_carry_what_only_the_registry_knows():
    """Ports, domain and the licence value are the registry's to resolve; a spec without them is refused here, where
    the caller can still fix it, rather than producing an operator that serves nothing."""
    mod = _load()
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    os.makedirs(frame_dir, exist_ok=True)
    for missing in ("bundle_filename", "compose", "operator_secrets"):
        spec = _stack_spec(root, frame_dir)
        spec.pop(missing)
        with pytest.raises(mod.HostWorkRefused) as e:
            _read(mod, spec)
        assert missing in str(e.value) and "phase stack" in str(e.value)


def test_a_parent_peer_value_that_cannot_be_checked_is_refused_not_escaped(monkeypatch):
    """Those values go into SQL TEXT. A value this module cannot check against a conservative shape is refused
    rather than hand-escaped, because hand-escaping is the thing that is wrong once and wrong forever."""
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)
    spec = _stack_spec(root, frame_dir, parent_peer={
        "name": "EU'); DROP TABLE peer_registries; --", "base_url": "https://x", "trust_domain": "x"})
    with pytest.raises(mod.HostWorkRefused) as e:
        mod.do_host_work(spec)
    assert "will not put in SQL text" in str(e.value)


def test_the_runner_branch_returns_before_any_step_that_needs_the_host():
    """The successor to the refusal that stood here while the host steps were unwired.

    Everything the registry can do — ports, env values, the licence and its EventStore sync — happens for both
    paths; everything that needs the host happens once, in the one-shot, and this function returns its facts. The
    property is ORDER again: no unguarded socket call may sit between the fork and that return, or a runner-built
    frame logs failures for work that is deliberately elsewhere and, worse, half-does it.
    """
    import ast
    src = (_SRC / "services" / "cloud_provisioner.py")
    if not src.exists():
        src = _SRC / "cloud_provisioner.py"
    tree = ast.parse(src.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "provision_cloud_operator")

    runner_ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If) and "_through_runner" in ast.unparse(n.test)]
    assert runner_ifs, "the provisioner must fork on _through_runner"
    early = [n for i in runner_ifs for n in ast.walk(i) if isinstance(n, ast.Return)]
    assert early, "the runner branch must return the one-shot's facts rather than falling through"
    return_line = min(r.lineno for r in early)

    guarded = set()
    for i in runner_ifs:
        for n in ast.walk(i):
            guarded.add(getattr(n, "lineno", -1))

    socket_calls = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call) or getattr(n, "lineno", 0) >= return_line:
            continue
        name = ast.unparse(n.func)
        if ("from_env" in name or "exec_run" in name or name.endswith("containers.get")
                or name == "_run" or name.endswith("apply_operator_secrets")):
            if n.lineno not in guarded:
                socket_calls.append((n.lineno, name))
    assert not socket_calls, f"these need the host and are not behind the fork: {socket_calls}"


def test_a_stack_with_no_pull_credentials_is_refused_before_up(monkeypatch):
    """Bringing the stack up without the per-stack docker config only defers the failure to the first pull, 401,
    with containers already created. §pass65's finding is that the host's auth is not inherited; the refusal makes
    the missing half visible while it can still be supplied."""
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)
    spec = _stack_spec(root, frame_dir)
    spec.pop("docker_username")
    with pytest.raises(mod.HostWorkRefused) as e:
        mod.do_host_work(spec)
    assert "pull its images" in str(e.value) and "Nothing was brought up" in str(e.value)


def test_the_stack_phase_writes_the_docker_config_and_the_federation_conf(monkeypatch):
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles, with_federation_conf=True)
    r = mod.do_host_work(_stack_spec(root, frame_dir))

    import base64
    import json as _json
    cfg_path = os.path.join(r["stack_dir"], ".docker", "config.json")
    cfg = _json.loads(open(cfg_path).read())
    assert base64.b64decode(cfg["auths"]["images.theprotocol.cloud"]["auth"]).decode().startswith("operator-tartu:")
    assert oct(os.stat(cfg_path).st_mode)[-3:] == "600"

    nginx = open(os.path.join(r["stack_dir"], "nginx", "nginx-federation.conf")).read()
    assert "server_name nginx-federation tartu.op.lantern.theprotocol.cloud _;" in nginx
    assert "set $upstream_teg cloud-op-tartu-teg;" in nginx


def test_the_edge_is_carried_through_unchanged(monkeypatch):
    """The runner writes the vhost and reloads nginx; it must not also RENDER one.

    Two renderings of an operator's edge would drift the day either changed, and these are not lines to keep in two
    places: the header pins in that vhost are row 194, where an operator console accepted a self-signed certificate
    in a plain header as proof of identity. One definition (core/operator_compose.operator_vhost), rendered by the
    side that holds every value, carried through this container byte for byte.
    """
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)
    vhost = "server {\n    server_name tartu.op.lantern.theprotocol.cloud;\n}\n"
    r = mod.do_host_work(_stack_spec(root, frame_dir, host_vhost=vhost,
                                     sni_entry="tartu.op.lantern.theprotocol.cloud  127.0.0.1:31543;"))
    assert r["host_vhost"] == vhost, "byte for byte, or it is a second rendering"
    assert r["sni_entry"].endswith("127.0.0.1:31543;")

    # and when the caller sends none, the result says so rather than leaving the runner to infer it
    r2 = mod.do_host_work(_stack_spec(root, frame_dir))
    assert "host_vhost" not in r2
    assert any("nothing to write" in n for n in r2["notes"])


def test_both_callers_pass_the_shared_renderer_the_right_sources():
    """agentvault2-85's question, applied here: a unit test of a rule is not a test that the CALLER asks for it.

    `adapt_operator_compose` is tested directly and the stack phase is driven end to end, but nothing checked what
    the SOCKET path hands it — and swapping `identity_network=IDENTITY_NETWORK` for the partner network, or the
    fed port for the registry port, would leave every one of those tests green while every operator provisioned by
    EU or ASIA came out on the wrong network. This pins the call site's SOURCES, which is the half a direct test
    structurally cannot see.
    """
    import ast
    src = (_SRC / "services" / "cloud_provisioner.py")
    if not src.exists():
        src = _SRC / "cloud_provisioner.py"
    call = next(n for n in ast.walk(ast.parse(src.read_text()))
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "adapt_operator_compose")
    passed = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    for arg, want in (("safe", "safe"), ("domain", "domain"), ("reg_port", "reg_port"), ("fed_port", "fed_port"),
                      ("teg_port", "teg_port"), ("worker_count", "worker_count"),
                      ("identity_network", "IDENTITY_NETWORK"),
                      ("partner_identity_network", "PARTNER_IDENTITY_NETWORK"),
                      ("partner_domain_suffix", "PARTNER_DOMAIN_SUFFIX")):
        assert passed.get(arg) == want, f"the socket path passes {arg}={passed.get(arg)!r}, expected {want}"
    assert "_frame_public_es_url" in src.read_text(), "the ES url must still be derived, not a literal"


def test_the_one_shot_prefers_the_runners_stamp_over_the_callers_claim():
    """The same question for the other caller, and here the SOURCE is the security property: the frame's identity
    network is stamped by the runner (which built the frame) and merely echoed by the caller, so the one-shot must
    read the stamp and fall back to the claim, never the other way round."""
    import ast
    hw = _SRC / "host_work.py"
    if not hw.exists():
        hw = _SRC.parent / "host_work.py"
    call = next(n for n in ast.walk(ast.parse(hw.read_text()))
                if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "adapt_operator_compose")
    passed = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
    got = passed.get("identity_network", "")
    assert got.startswith("spec.get('frame_identity_network')"), (
        f"identity_network is {got!r}: the runner's stamp must come first, the caller's claim only as a fallback")


def test_the_result_carries_the_identity_spire_minted_not_one_composed(monkeypatch):
    """The runner writes this into the frame's directory readers list, so it must be what SPIRE says the entry IS.

    Composing `spiffe://<trust domain>/operator/<safe>/svid-writer` on the reading side would put that shape in a
    second place, and a second copy of an identity rots exactly like a second copy of a version string. The entry's
    own `SPIFFE ID` line wins; the composed form is the fallback for an entry that does not print one.
    """
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)

    import types as _t
    shown = ("Entry ID         : 9f2c\n"
             "SPIFFE ID        : spiffe://lantern.theprotocol.cloud/operator/tartu/svid-writer\n"
             "FederatesWith    : eu.theprotocol.cloud\n")

    def _fake_run(cmd, *a, **k):
        if "entry" in cmd and "show" in cmd:
            return _t.SimpleNamespace(stdout=shown, stderr="", returncode=0)
        if "logs" in cmd:
            return _t.SimpleNamespace(stdout="FIRST-BOOT ADMIN PASSWORD: pw\n", stderr="", returncode=0)
        return _t.SimpleNamespace(stdout="a\nb\nc\n", stderr="", returncode=0)

    monkeypatch.setattr(mod, "subprocess", _t.SimpleNamespace(run=_fake_run))
    spec = _stack_spec(root, frame_dir, spire_fingerprint="ab12", spire_container="lantern-spire-server",
                       spire_trust_domain="lantern.theprotocol.cloud")
    r = mod.do_host_work(spec)
    assert r["operator_spiffe_id"] == "spiffe://lantern.theprotocol.cloud/operator/tartu/svid-writer"
    assert any("federatesWith preserved" in n for n in r["notes"]), "the federation set must be carried, not dropped"


def test_the_auditor_credential_is_minted_for_the_operator_but_not_handed_to_it(monkeypatch):
    """agentvault2-6a's finding: all 13 fleet venue DSNs use the database OWNER, so every auditor holds a
    credential that can rewrite the register it audits. This role can SELECT two tables — and its password must
    NOT reach .env.operator, because the operator's own apps never read it and a secret written where nothing
    reads it is a secret with only downside."""
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)

    r = mod.do_host_work(_stack_spec(root, frame_dir))
    assert r["auditor_ro_created"] is True

    env = open(os.path.join(r["stack_dir"], ".env.operator")).read()
    assert "AUDITOR_RO_PASSWORD" not in env, "the auditor's credential must not be written into the operator's env"
    assert "r" * 40 not in env, "nor its value under any other name"
    assert env.count("s" * 40) == 4, "the operator's own four secrets are still written"
    assert any("not handed to it" in n for n in r["notes"])


def test_a_quote_in_the_auditor_password_is_refused_rather_than_escaped(monkeypatch):
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)
    spec = _stack_spec(root, frame_dir)
    spec["operator_secrets"] = dict(spec["operator_secrets"], AUDITOR_RO_PASSWORD="a'; DROP ROLE registry; --")
    with pytest.raises(mod.HostWorkRefused) as e:
        mod.do_host_work(spec)
    assert "refused rather than escaped" in str(e.value)


def test_the_role_grants_only_the_tables_an_auditor_reads():
    """Structural: the SQL is read rather than run, so a later GRANT that widens it is caught here.

    ⚠ THE COUNT WAS IN THE NAME, AND THE NAME WAS THE BUG. This pinned "the two tables" while the auditor's venue
    path reads three, so it defended the defect: exchange_trades was missing, three of the five queries answered
    `permission denied`, and the venue reported as unreachable. A test may pin the RULE (read-only, exactly what
    the reader reads) and must not pin a number it can derive — the derivation from the auditor's own source
    lives in tests/test_operator_runner_branch.py, and this one guards the shape.
    """
    mod = _load()
    sql = " ".join(mod._AUDITOR_RO_SQL)
    assert "GRANT SELECT ON org_share_positions, exchange_listings, exchange_trades TO auditor_ro;" in sql
    assert "INSERT" not in sql and "UPDATE" not in sql and "DELETE" not in sql and "ALL PRIVILEGES" not in sql
    assert "CREATE ROLE auditor_ro LOGIN PASSWORD" in sql and "ALTER ROLE auditor_ro LOGIN PASSWORD" in sql


def test_the_exclusion_is_derived_from_the_provisioner_not_restated(monkeypatch):
    """The build gate found this: the exclusion was a literal here while OPERATOR_ENV_SECRET_NAMES sat in the
    provisioner DEFINED AND NEVER READ — two statements of one rule, one of them inert. A sixth secret must decide
    its own fate where it is declared, so this derives the difference between the two lists."""
    import types as _t
    mod = _load()
    module = _t.SimpleNamespace(
        OPERATOR_SECRET_NAMES=("A", "B", "C"), OPERATOR_ENV_SECRET_NAMES=("A", "B"))
    assert mod.env_excluded_secrets(module) == ("C",)
    # an older provisioner with neither list hands over everything it always did, rather than withholding blindly
    assert mod.env_excluded_secrets(_t.SimpleNamespace()) == ()


def test_the_one_root_only_step_is_done_here_because_the_timing_leaves_no_afterwards(monkeypatch):
    """Redis starts with `--aclfile`; a Redis that cannot read it EXITS, `restart: unless-stopped` makes that a
    crash loop, its healthcheck never passes, and `compose up -d` WAITS on `condition: service_healthy` — so the
    job would block to the 900 s ceiling and fail. "The runner chowns it after the job" has no afterwards. It
    happens here, through the socket this container already holds, rather than by running the whole one-shot as
    root and making this the only root-owned operator stack on the box."""
    mod = _load()
    _stub_docker(mod, monkeypatch)
    root = tempfile.mkdtemp()
    frame_dir = os.path.join(root, "lantern-1789542771")
    bundles = os.path.join(frame_dir, "operator-bundles")
    os.makedirs(bundles)
    _bundle_with_the_real_template(bundles)

    # 1. THE NORMAL CASE. The provisioner writes the ACL during this phase (it is not in the bundle: a real one
    #    carries spire/*, nginx/*, the compose, the generator and pgbouncer.ini, measured on beacon's jelgava
    #    tar). It lands owned by whoever runs the one-shot, so the chown through the socket is ATTEMPTED and its
    #    failure REPORTED rather than assumed away — the stub docker returns success but cannot really chown.
    r = mod.do_host_work(_stack_spec(root, frame_dir))
    assert r["redis_acl_path"].endswith("redis-users.acl")
    assert r["redis_acl_chown_needed"] is True
    assert any("Redis cannot start until this is fixed" in n for n in r["notes"])

    # 2. ⚠ AND THE CASE THIS TEST USED TO ASSERT AN "ABSENT" VERDICT FOR, which V0389 made unreachable in a real
    #    provision — a better answer than reporting it. The compose binds `./redis-users.acl` into Redis; reaching
    #    `up` without one means Docker creates a ROOT-OWNED DIRECTORY and mounts it over the ACL file. Refused
    #    before anything starts, rather than brought up carrying a verdict nothing acts on.
    import types as _t2
    monkeypatch.setattr(mod, "_load_provisioner", lambda: _t2.SimpleNamespace(
        apply_operator_secrets=lambda *a, **k: None,      # the case: nothing wrote the ACL
        OPERATOR_SECRET_NAMES=("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                               "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG", "AUDITOR_RO_PASSWORD"),
        OPERATOR_ENV_SECRET_NAMES=("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                                   "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG")))
    root2 = tempfile.mkdtemp()
    frame2 = os.path.join(root2, "lantern-1789542771")
    os.makedirs(os.path.join(frame2, "operator-bundles"))
    _bundle_with_the_real_template(os.path.join(frame2, "operator-bundles"))
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as _e:
        mod.do_host_work(_stack_spec(root2, frame2))
    assert "redis-users.acl" in str(_e.value) and "Docker would mount" in str(_e.value)


def test_the_chown_goes_through_a_throwaway_container_not_a_root_process():
    """Structural: the privilege must stay visible. If this ever becomes os.chown, the one-shot needs uid 0 and
    every operator it provisions becomes root-owned."""
    import ast
    hw = _SRC / "host_work.py"
    if not hw.exists():
        hw = _SRC.parent / "host_work.py"
    fn = next(n for n in ast.walk(ast.parse(hw.read_text()))
              if isinstance(n, ast.FunctionDef) and n.name == "_fix_redis_acl_owner")
    body = ast.unparse(fn)
    assert "docker" in body and "chown" in body and "999:1000" in body
    assert "os.chown" not in body, "a direct chown would require the one-shot to run as root"
