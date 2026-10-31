"""§TESTBED (2026-09-19): frame-sandbox.py, the engine the CLI and the MCP tester view's panel both run. Its pure parts:
the names (every public name one label under the parent's, so the kit's one `*.<name>` record covers them), the lanes,
the firewall specs, the set's shared secrets (created once, 600, reused on a resume). The standup itself is proven live
on a throwaway frame (sessionlogs2026/FINDINGS_2026-09-19_TESTBED.md), never here."""
import importlib.util
import json
import os
import stat

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_sandbox", os.path.join(HERE, "..", "frame-sandbox.py"))
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)

PARENT = {"name": "larch", "public_name": "larch.example.org"}


def test_names_sit_one_label_under_the_parent():
    one = fs.sandbox_names(PARENT, 1)
    assert [(s["key"], s["name"], s["public_name"]) for s in one] == [("a", "larchsbx", "sandbox.larch.example.org")]
    two = fs.sandbox_names(PARENT, 2)
    assert [s["public_name"] for s in two] == ["sandbox.larch.example.org", "sandbox-b.larch.example.org"]
    assert [s["operator"] for s in two] == ["larchsbxop", "larchsbxbop"]
    for s in two:   # a sandbox's operator is named <slug>.<parent public name>: one label, the same wildcard
        assert s["public_name"].count(".") == PARENT["public_name"].count(".") + 1


def test_lanes_are_three_free_ports_stepping_by_ten():
    assert fs.free_lanes(28553, set()) == [28553, 28554, 28555]
    assert fs.free_lanes(28553, {28554}) == [28563, 28564, 28565]


def test_ufw_specs_are_contiguous_ranges():
    assert fs.port_specs([28555, 28553, 28554]) == ["28553:28555/tcp"]
    assert fs.port_specs([31600, 31643, 31680, 31681]) == ["31600/tcp", "31643/tcp", "31680:31681/tcp"]
    assert fs.port_specs([]) == []


def test_the_set_secrets_are_made_once_600_and_reused(tmp_path):
    p1 = fs.fixture_secrets_file(str(tmp_path), "larchsbx")
    first = json.load(open(p1))
    assert set(first) == set(fs.FIXTURE_KEYS)
    assert stat.S_IMODE(os.stat(p1).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(p1)).st_mode) == 0o700
    assert json.load(open(fs.fixture_secrets_file(str(tmp_path), "larchsbx"))) == first   # a resume keeps them
    pw = fs.operator_dev_password(str(tmp_path), "larchsbx", "larchsbxop")
    assert pw == fs.operator_dev_password(str(tmp_path), "larchsbx", "larchsbxop")          # the account an earlier try made
    assert pw != fs.operator_dev_password(str(tmp_path), "larchsbx", "larchsbxbop")


def test_upsert_env_replaces_or_appends(tmp_path):
    env = tmp_path / ".env.frame-test"
    env.write_text("A=1\nB=2\n")
    fs.upsert_env(str(env), [("B", "3"), ("C", "x=y")])
    assert env.read_text() == "A=1\nB=3\nC=x=y\n"


def test_recorded_lanes_are_read_back_for_a_resume():
    rec = {"federation_lane": "https://s.example.org:28553", "bundle_endpoint": "https://s.example.org:28554/",
           "ledger_gateway": "https://s.example.org:28555"}
    assert fs.lanes_of(rec) == (28553, 28554, 28555)
    assert fs.lanes_of({"federation_lane": "https://s.example.org"}) is None


def test_a_resume_continues_the_application_an_earlier_try_left():
    body = {"applications": [
        {"id": "old", "name": "larchsbxop", "status": "rejected", "created_at": "2026-09-19T10:00:00"},
        {"id": "a1", "name": "larchsbxop", "status": "approved", "activated_at": "2026-09-19T11:00:00",
         "created_at": "2026-09-19T10:30:00"},
        {"id": "b1", "name": "larchsbxbop", "status": "pending", "created_at": "2026-09-19T10:40:00"}]}
    live = fs.live_applications(body, "larchsbxop")
    assert [x["id"] for x in live] == ["a1"]                 # a rejected one is over and never resumed
    assert fs.live_applications({"applications": []}, "larchsbxop") == []
    assert fs.live_applications({"detail": "x"}, "larchsbxop") == []
    # the stage is read from what the writers write: activate stamps activated_at and leaves the status "approved"
    assert fs.application_stage({"status": "pending"}) == "pending"
    assert fs.application_stage({"status": "approved"}) == "approved"
    assert fs.application_stage({"status": "approved", "activated_at": "t"}) == "activated"
    assert fs.application_stage({"status": "approved", "activated_at": "t", "cloud_hosted": True}) == "provisioned"
    assert fs.application_stage({"status": "approved", "activated_at": "t", "cloud_hosted": True,
                                 "cloud_torn_down_at": "t2"}) == "activated"


def test_the_activation_code_is_kept_600_before_it_is_spent(tmp_path):
    fs.fixture_secrets_file(str(tmp_path), "larchsbx")            # the set's secrets directory exists first
    assert fs.kept_activation_code(str(tmp_path), "larchsbx", "a1") is None
    fs.keep_activation_code(str(tmp_path), "larchsbx", "a1", "code-1")
    fs.keep_activation_code(str(tmp_path), "larchsbx", "b1", "code-2")
    assert fs.kept_activation_code(str(tmp_path), "larchsbx", "a1") == "code-1"
    assert fs.kept_activation_code(str(tmp_path), "larchsbx", "b1") == "code-2"
    path = fs.operator_code_file(str(tmp_path), "larchsbx")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_the_panel_lists_the_steps_the_engine_reports():
    """The MCP tester view folds this engine's progress by its own copy of the step order; a step the view does not list
    becomes a stray row, and a listed step the engine never reports stays "not reached" on a finished job (both measured
    on larch with an image older than the engine). One order, pinned from both sides."""
    import re
    import pytest
    ts = os.path.join(HERE, "..", "..", "..", "AgentVault", "agentvault_registry", "src", "agentvault_registry", "static",
                      "new_registry_frontend", "src", "services", "sandboxSteps.ts")
    if not os.path.isfile(ts):
        pytest.skip("the registry source is not beside this tree")
    src = open(ts).read()

    def listed(name):
        m = re.search(rf"export const {name}: readonly string\[\] = \[(.*?)\]", src, re.S)
        assert m, f"{name} is not declared in sandboxSteps.ts"
        return tuple(re.findall(r"'([a-z_]+)'", m.group(1)))

    assert listed("SANDBOX_UP_STEPS") == fs.STEPS_UP
    assert listed("SANDBOX_DOWN_STEPS") == fs.STEPS_DOWN


def test_a_resumed_sandbox_reuses_the_lanes_its_partial_stack_publishes(tmp_path):
    """Measured on the dev4 sandbox: the first standup stopped before frame-up wrote frame-up.json, the resume took FRESH
    lanes (the old ones were busy, held by the sandbox's own containers), and the record named 28563-28565 while the
    containers published 28553-28555. The driver's run meta names the published ones."""
    sd = tmp_path / "larchsbx-1789840396"; sd.mkdir()
    (sd / "docker-compose.frame-test.yml").write_text("services: {}\n")
    (sd / "hetzner-demo-run.json").write_text(json.dumps({
        "ports": {"registry": 8700, "spire_bundle": 28554, "nginx_fed": 28553},
        "es_public_url": "https://sandbox.larch.theprotocol.cloud:28555"}))
    assert fs.partial_lanes(str(tmp_path), "larchsbx") == (28553, 28554, 28555)
    assert fs.partial_lanes(str(tmp_path), "larch") is None          # another frame's name reads nothing
    (sd / "hetzner-demo-run.json").write_text(json.dumps({"ports": {"nginx_fed": 28553}}))
    assert fs.partial_lanes(str(tmp_path), "larchsbx") is None        # an incomplete record is no answer


# ── V0650 (k), the kit half (agentvault2-7c, 2026-10-31): the same-host lane in each sandbox's own carriers ─────────────
COMPOSE = """services:
  larchsbx-spire-server:
    image: ghcr.io/spiffe/spire-server:1.15.3
    restart: unless-stopped
    volumes:
      - /s/server.conf:/opt/spire/conf/server.conf:ro
    ports:
      - "28581:8081"
  larchsbx-registry:
    image: reg
    volumes:
      - /s/kit/data-tls:/opt/data-tls:ro   # T3
      - /s/operator-bundles:/app/operator-bundles
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      net:
        aliases:
          - registry-test
"""
NAMES = ["sandbox.larch.example.org", "sandbox-b.larch.example.org"]


def test_the_lane_adds_the_names_and_the_mount_once():
    out, n = fs.same_host_compose(COMPOSE, "larchsbx-registry", "larchsbx-spire-server", NAMES, "/s/kit/peer-ca")
    assert n == 5   # two names in the registry, the mount, two names in the SPIRE server's new extra_hosts
    reg = out.split("  larchsbx-registry:")[1]
    spire = out.split("  larchsbx-registry:")[0].split("  larchsbx-spire-server:")[1]
    for name in NAMES:
        assert f'      - "{name}:host-gateway"' in reg and f'      - "{name}:host-gateway"' in spire
    assert "      - /s/kit/peer-ca:/run/peer-ca:ro" in reg and "peer-ca" not in spire
    assert spire.index("    extra_hosts:") < spire.index("    volumes:")
    again, n2 = fs.same_host_compose(out, "larchsbx-registry", "larchsbx-spire-server", NAMES, "/s/kit/peer-ca")
    assert (again, n2) == (out, 0)
    try:
        import yaml
    except ImportError:
        return
    svc = yaml.safe_load(out)["services"]
    assert sorted(svc["larchsbx-registry"]["extra_hosts"]) == sorted(["host.docker.internal:host-gateway"] +
                                                                    [f"{n}:host-gateway" for n in NAMES])
    assert "/s/kit/peer-ca:/run/peer-ca:ro" in svc["larchsbx-registry"]["volumes"]
    assert sorted(svc["larchsbx-spire-server"]["extra_hosts"]) == sorted(f"{n}:host-gateway" for n in NAMES)


def test_without_an_edge_root_no_mount_is_added():
    out, n = fs.same_host_compose(COMPOSE, "larchsbx-registry", "larchsbx-spire-server", NAMES, None)
    assert n == 4 and "peer-ca" not in out


def test_a_missing_anchor_refuses_and_edits_nothing():
    import pytest
    with pytest.raises(ValueError, match="host.docker.internal"):
        fs.same_host_compose(COMPOSE.replace('      - "host.docker.internal:host-gateway"\n', ""),
                             "larchsbx-registry", "larchsbx-spire-server", NAMES)
    with pytest.raises(ValueError, match="no service larchsbx-spire-server"):
        fs.same_host_compose(COMPOSE.replace("larchsbx-spire-server", "other"), "larchsbx-registry",
                             "larchsbx-spire-server", NAMES)
    with pytest.raises(ValueError, match="data-tls"):
        fs.same_host_compose(COMPOSE.replace(":/opt/data-tls:ro", ":/opt/other:ro"), "larchsbx-registry",
                             "larchsbx-spire-server", NAMES, "/s/kit/peer-ca")


def test_the_frame_template_still_renders_the_anchors_the_lane_edits():
    import re
    tmpl = open(os.path.join(HERE, "..", "..", "..", "templates", "frame-test", "docker-compose.frame-test.yml.tmpl")).read()
    text = re.sub(r"\{\{[A-Z0-9_]+\}\}", "X", tmpl.replace("{{REGISTRY_NAME}}", "larchsbx"))
    out, n = fs.same_host_compose(text, "larchsbx-registry", "larchsbx-spire-server", NAMES, "/s/kit/peer-ca")
    assert n == 5


def test_env_declares_reads_bare_and_quoted_values():
    assert fs.env_declares("A=1\nFRAME_POSTURE=sandbox\n", "FRAME_POSTURE", "sandbox")
    assert fs.env_declares('FRAME_POSTURE="sandbox"\n', "FRAME_POSTURE", "sandbox")
    assert not fs.env_declares("FRAME_POSTURE=production\n", "FRAME_POSTURE", "sandbox")
    assert not fs.env_declares("XFRAME_POSTURE=sandbox\n", "FRAME_POSTURE", "sandbox")


class _Frame:
    def __init__(self, name, sd, public):
        self.name, self.rec = name, {"stack_dir": sd, "public_name": public}

    def healthy(self):
        return True


class _Progress:
    def __init__(self):
        self.notes = []

    def note(self, msg):
        self.notes.append(msg)


def _sandbox(tmp_path, name, public, posture="sandbox"):
    sd = tmp_path / name
    (sd / "edge").mkdir(parents=True)
    (sd / ".env.frame-test").write_text(f"A=1\nFRAME_POSTURE={posture}\n")
    (sd / "docker-compose.frame-test.yml").write_text(COMPOSE.replace("larchsbx-", f"{name}-"))
    return _Frame(name, str(sd), public)


PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def test_the_lane_refuses_a_frame_that_does_not_declare_sandbox(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(fs, "edge_root_pem", lambda parent: None)
    a = _sandbox(tmp_path, "larchsbx", NAMES[0], posture="production")
    b = _sandbox(tmp_path, "larchsbxb", NAMES[1])
    with pytest.raises(fs.StepFailed, match="FRAME_POSTURE=sandbox"):
        fs.prepare_same_host(a, b, {"stack_dir": str(tmp_path)}, _Progress())


def test_the_lane_opens_once_and_a_second_run_recreates_nothing(tmp_path, monkeypatch):
    calls = []

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(argv, **kw):
        calls.append(argv)
        return _R()
    monkeypatch.setattr(fs, "edge_root_pem", lambda parent: PEM)
    monkeypatch.setattr(fs.subprocess, "run", fake_run)
    a, b = _sandbox(tmp_path, "larchsbx", NAMES[0]), _sandbox(tmp_path, "larchsbxb", NAMES[1])
    parent = {"stack_dir": str(tmp_path / "parent")}
    bundle = fs.prepare_same_host(a, b, parent, _Progress())
    ups = [c for c in calls if "up" in c]
    assert [c[-2:] for c in ups] == [["larchsbx-spire-server", "larchsbx-registry"], ["larchsbxb-spire-server", "larchsbxb-registry"]]
    for fr in (a, b):
        sd = fr.rec["stack_dir"]
        env = open(os.path.join(sd, ".env.frame-test")).read()
        assert "FRAME_INVITATIONS_SAME_HOST_PEERS=true" in env
        assert "FRAME_INVITATIONS_PEER_CA_FILE=/run/peer-ca/frame-edge-ca.pem" in env
        assert "REGISTRY_ENVIRONMENT" not in env   # R42: a kit frame never states sandbox to the tester
        ca = os.path.join(sd, "kit", "peer-ca", "frame-edge-ca.pem")
        assert open(ca).read() == PEM and stat.S_IMODE(os.stat(ca).st_mode) == 0o644
        assert os.path.exists(os.path.join(sd, "docker-compose.frame-test.yml.bak-pre-samehost"))
    assert bundle and open(bundle).read().endswith(PEM)
    calls.clear()
    progress = _Progress()
    fs.prepare_same_host(a, b, parent, progress)
    assert not [c for c in calls if "up" in c]
    assert sum("open already" in n for n in progress.notes) == 2
