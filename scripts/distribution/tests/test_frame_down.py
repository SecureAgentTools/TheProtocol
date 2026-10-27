"""frame-down takes a frame's operators down over the same compose files their `up` read (§OPA + §PUSH, 2026-10-06).

Every override the provisioning one-shot copies into an operator's stack declares its own services AND volumes: the db-TLS
file since V0391, the OPA file (opa-certs) and the push file (ntfy-cache) since V0582. `docker compose down -v` removes only
the volumes the files it is given declare, so a list naming the db-TLS file alone left the OPA's and the relay's volumes
behind (their containers went as orphans). The frame runner's operator_teardown already globs the overrides; this is the
same rule in the kit's own teardown.
"""
import importlib.util
import json
import os
import types

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_down", os.path.join(HERE, "..", "frame-down.py"))
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)

OVERRIDES = ("docker-compose.operator.dbtls.yml", "docker-compose.operator.opa.yml", "docker-compose.operator.push.yml")


def _tree(root, overrides):
    frame = root / "frm-1700000000"
    frame.mkdir()
    (frame / "docker-compose.frame-test.yml").write_text("services: {}\n")
    (frame / "hetzner-demo-run.json").write_text(json.dumps({"trust_domain": "frm.example"}))
    op = root / "cloud-op-frmop"
    (op / "spire").mkdir(parents=True)
    (op / "spire" / "agent.conf").write_text('agent { trust_domain = "frm.example" }\n')
    (op / "docker-compose.operator.yml").write_text("services: {}\n")
    (op / ".env.operator").write_text("A=1\n")
    for name in overrides:
        (op / name).write_text("services: {}\n")
    other = root / "cloud-op-elsewhere"   # an operator of ANOTHER frame: never touched
    (other / "spire").mkdir(parents=True)
    (other / "spire" / "agent.conf").write_text('agent { trust_domain = "other.example" }\n')
    (other / "docker-compose.operator.yml").write_text("services: {}\n")
    return op, other


def _down(monkeypatch, root):
    calls = []

    def fake_run(argv, **kw):
        calls.append((list(argv), kw.get("cwd")))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fd, "run", fake_run)
    monkeypatch.setattr(fd.frame_names, "frame_resources", lambda name, stack_root=None: {"containers": [], "volumes": [], "networks": []})
    a = types.SimpleNamespace(stack_root=str(root), yes=True, keep_secrets=False)
    fd.down(a, "frm", ask=False)
    return [argv for argv, cwd in calls if argv[:2] == ["docker", "compose"] and "-p" in argv
            and argv[argv.index("-p") + 1].startswith("cloud-op-")]


def test_every_override_in_the_operators_stack_goes_down_with_it(tmp_path, monkeypatch):
    op, other = _tree(tmp_path, OVERRIDES)
    downs = _down(monkeypatch, tmp_path)
    assert len(downs) == 1, downs
    argv = downs[0]
    files = [argv[i + 1] for i, x in enumerate(argv) if x == "-f"]
    assert files == ["docker-compose.operator.yml", *OVERRIDES], files
    assert argv[-3:] == ["down", "-v", "--remove-orphans"]
    assert not op.exists() and other.exists(), "the frame's operator is removed, another frame's stays"


def test_an_operator_without_overrides_reads_the_base_alone(tmp_path, monkeypatch):
    _tree(tmp_path, ())
    downs = _down(monkeypatch, tmp_path)
    assert [[x for i, x in enumerate(a) if i and a[i - 1] == "-f"] for a in downs] == [["docker-compose.operator.yml"]]
