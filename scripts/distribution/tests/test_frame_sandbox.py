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
