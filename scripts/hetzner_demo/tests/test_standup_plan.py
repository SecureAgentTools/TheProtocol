"""§FRAMEPROV P1 (2026-09-13): `--plan` answers what the run would refuse and derive, and writes nothing.

The admin UI shows the plan before its Start button enables, so a plan that WRITES (a stack dir, a vhost, a secret)
would be a standup nobody started. Every host probe is faked: the fakes answer like a healthy host, and a guard records
any write (open for write/append, makedirs, symlink, replace, chmod, unlink) and any command that is not a read.
"""
import builtins
import ast
import dataclasses
import importlib.util
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("standup_driver_plan", HERE.parent / "standup_driver.py")
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

READ_ONLY_COMMANDS = (("docker", "image", "inspect"), ("docker", "ps"), ("docker", "network", "inspect"),
                      ("docker", "manifest", "inspect"), ("docker", "run", "--rm"), ("ss",), ("dig",))

BASE_ARGV = ["--name", "juice", "--frame-label", "Juice", "--trust-domain", "juice.theprotocol.cloud",
             "--public-url", "https://juice.theprotocol.cloud", "--es-public-url", "https://juice-es.theprotocol.cloud",
             "--ticker", "JUC", "--registry-image", "agentvault2-registry-a:v0356",
             "--teg-image", "agentvault2-teg-layer:v0351", "--plan"]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(drv, "LOG_TO_STDERR", False)
    monkeypatch.setattr(drv, "PORTS", dict(drv.PORTS))
    monkeypatch.setattr(drv, "PROGRESS", None)
    for name in drv.frame_ports.ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FRAME_MAIL_SERVER", raising=False)


class HostFake:
    """A healthy host, recorded. `dns` maps host -> A answers (default: resolves); `cert` says whether the certificate
    exists. Any write raises AND is recorded; every command is recorded."""

    def __init__(self, monkeypatch, dns=None, cert=True):
        self.writes, self.commands = [], []
        self.dns = dns or {}
        real_open, real_exists, real_islink = builtins.open, os.path.exists, os.path.islink
        proc = {"/proc/loadavg": "1.00 1.00 1.00 1/1 1\n",
                "/proc/meminfo": f"MemTotal: 128000000 kB\nMemAvailable: {64 * 1024 * 1024} kB\n",
                "/proc/sys/fs/aio-max-nr": "1048576\n", "/proc/sys/fs/aio-nr": "0\n"}

        def fake_open(path, mode="r", *a, **kw):
            p = str(path)
            if p in proc:
                return io.StringIO(proc[p])
            if any(ch in mode for ch in "wax+"):
                self.writes.append(("open", p, mode))
                raise AssertionError(f"the plan opened {p} for writing")
            return real_open(path, mode, *a, **kw)

        def refuse(name):
            def _refused(*a, **kw):
                self.writes.append((name, a))
                raise AssertionError(f"the plan called os.{name}{a}")
            return _refused

        def fake_run(cmd, *a, **kw):
            c = [str(x) for x in cmd]
            self.commands.append(c)
            if c[:1] == ["dig"]:
                answers = self.dns.get(c[3], ["203.0.113.10"]) if c[4] == "A" else []
                return subprocess.CompletedProcess(c, 0, "".join(f"{x}\n" for x in answers), "")
            if c[:3] == ["docker", "run", "--rm"]:
                return subprocess.CompletedProcess(
                    c, 0, 'BUNDLED_IMAGE_TAG = "MoreCompliantThenYourWholeComplianceFrameworkV0356"\n', "")
            return subprocess.CompletedProcess(c, 0, "", "")

        monkeypatch.setattr(builtins, "open", fake_open)
        for name in ("makedirs", "mkdir", "symlink", "replace", "rename", "chmod", "unlink", "remove"):
            monkeypatch.setattr(os, name, refuse(name))
        monkeypatch.setattr(drv.subprocess, "run", fake_run)
        monkeypatch.setattr(drv, "port_free", lambda p: True)
        monkeypatch.setattr(os.path, "islink", lambda p: True if p == "/host-stack" else real_islink(p))
        monkeypatch.setattr(os.path, "exists",
                            lambda p: cert if str(p).startswith("/etc/letsencrypt/live/") else real_exists(p))
        monkeypatch.setattr(builtins, "input", refuse("input(prompt)"))
        monkeypatch.setattr(shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10 ** 13, 10 ** 12, 500 * 1024 ** 3))

    def mutating_commands(self):
        return [c for c in self.commands if not any(c[:len(p)] == list(p) for p in READ_ONLY_COMMANDS)]


def _plan(argv, monkeypatch, capsys, **host):
    fake = HostFake(monkeypatch, **host)
    args = drv.build_parser().parse_args(argv)
    code = drv.plan(args)
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err, fake


def test_the_no_write_guard_catches_a_write(monkeypatch, tmp_path):
    fake = HostFake(monkeypatch)
    with pytest.raises(AssertionError):
        open(tmp_path / "control", "w")
    assert fake.writes and fake.writes[0][0] == "open" and not (tmp_path / "control").exists()


def test_a_healthy_plan_is_ok_writes_nothing_and_runs_only_reads(monkeypatch, capsys):
    code, doc, err, fake = _plan(BASE_ARGV, monkeypatch, capsys)
    assert code == 0 and doc["ok"] is True, doc["refusals"]
    assert fake.writes == [] and fake.mutating_commands() == []
    d = doc["derived"]
    assert d["trust_domain"] == "juice.theprotocol.cloud"
    assert d["federation_public_url"] == "https://juice.theprotocol.cloud:8443"
    assert d["image_tag"].endswith("V0356") and d["posture"] == "sandbox"
    assert set(d["ports"]) >= {"registry", "teg", "es", "spire_grpc", "spire_bundle", "nginx_fed", "push"}
    assert d["dns"]["juice-es.theprotocol.cloud"] == ["203.0.113.10"] and d["certificate"]["present"] is True
    assert "[standup]" in err and "[standup]" not in json.dumps(doc), "the log goes to stderr; stdout is one document"


def test_every_argument_refusal_is_collected_not_only_the_first(monkeypatch, capsys):
    argv = list(BASE_ARGV)
    argv[argv.index("--es-public-url") + 1] = "http://juice-es.theprotocol.cloud"
    argv += ["--posture", "production", "--tester-fixtures", "--directory-upstream", "directory-nginx:8443"]
    code, doc, _, fake = _plan(argv, monkeypatch, capsys)
    joined = "\n".join(doc["refusals"])
    assert code == 2 and doc["ok"] is False
    for flag in ("--es-public-url", "--tester-fixtures", "--directory-upstream", "mail relay"):
        assert flag in joined, flag
    assert fake.writes == []


def test_a_missing_ticker_is_a_refusal_never_a_prompt(monkeypatch, capsys):
    argv = list(BASE_ARGV)
    i = argv.index("--ticker")
    del argv[i:i + 2]
    code, doc, _, fake = _plan(argv, monkeypatch, capsys)
    assert code == 2 and any("--ticker is required" in r for r in doc["refusals"])
    assert fake.writes == []


def test_missing_dns_refuses_under_acme_and_only_warns_otherwise(monkeypatch, capsys):
    names = ("gamma", "gamma-es", "gamma-spire", "gamma-push")
    dns = {f"{n}.theprotocol.cloud": [] for n in names}
    argv = [x.replace("juice", "gamma") for x in BASE_ARGV]
    code, doc, _, _ = _plan(argv + ["--acme"], monkeypatch, capsys, dns=dns, cert=False)
    assert code == 2 and any(r.startswith("DNS first: gamma.theprotocol.cloud") for r in doc["refusals"])
    code, doc, _, _ = _plan(argv, monkeypatch, capsys, dns=dns, cert=True)
    assert code == 0, doc["refusals"]
    assert any("do not resolve at 1.1.1.1" in w for w in doc["warnings"])


def test_dns_by_runner_turns_the_missing_dns_refusal_into_a_warning(monkeypatch, capsys):
    # §FRAMEPROV P5: the frame runner creates the names at Start and waits for 1.1.1.1 before the driver runs.
    names = ("gamma", "gamma-es", "gamma-spire", "gamma-push")
    dns = {f"{n}.theprotocol.cloud": [] for n in names}
    argv = [x.replace("juice", "gamma") for x in BASE_ARGV] + ["--acme"]
    code, doc, _, fake = _plan(argv + ["--dns-by-runner"], monkeypatch, capsys, dns=dns, cert=False)
    assert code == 0, doc["refusals"]
    assert any("the frame runner creates them" in w for w in doc["warnings"])
    assert fake.writes == []
    code, doc, _, _ = _plan(argv, monkeypatch, capsys, dns=dns, cert=False)      # the control: without the flag it refuses
    assert code == 2 and any(r.startswith("DNS first:") for r in doc["refusals"])


def test_the_runner_creates_exactly_the_hosts_the_plan_and_the_certificate_name(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("frame_dns", HERE.parents[2] / "tools" / "frame-runner" / "frame_dns.py")
    frame_dns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frame_dns)
    code, doc, _, _ = _plan(BASE_ARGV, monkeypatch, capsys)
    assert code == 0, doc["refusals"]
    assert list(doc["derived"]["dns"]) == frame_dns.names("juice", drv.extras.DOMAIN)


def test_a_plan_with_allocated_ports_derives_them_from_the_host(monkeypatch, capsys):
    monkeypatch.setattr(drv.frame_ports, "taken_ports", lambda *a, **kw: {8500})
    code, doc, _, fake = _plan(BASE_ARGV + ["--allocate-ports"], monkeypatch, capsys)
    assert code == 0, doc["refusals"]
    ports = doc["derived"]["ports"]
    assert (ports["registry"], ports["es"], ports["nginx_fed"], ports["push"]) == (8600, 8611, 30613, 8649)
    assert fake.writes == []


def test_allocated_ports_beside_a_declared_port_are_refused(monkeypatch, capsys):
    monkeypatch.setenv("FRAME_TEST_PORT_REGISTRY", "8750")
    code, doc, _, _ = _plan(BASE_ARGV + ["--allocate-ports"], monkeypatch, capsys)
    assert code == 2 and any("two declarations" in r for r in doc["refusals"])


def test_the_run_still_dies_on_the_first_argument_refusal(monkeypatch, capsys):
    argv = [a for a in BASE_ARGV if a != "--plan"] + ["--es-public-url", "http://nope.example"]
    monkeypatch.setattr(sys, "argv", ["standup_driver.py"] + argv)
    with pytest.raises(SystemExit) as exc:
        drv.main()
    assert exc.value.code == 1 and "--es-public-url" in capsys.readouterr().err


def test_the_secrets_dir_reaches_every_module_instance(monkeypatch, tmp_path):
    mods = (drv.extras, drv.federate, drv.federate.extras, drv.sidecars.extras)
    for mod in mods:
        monkeypatch.setattr(mod, "SECRETS_DIR", mod.SECRETS_DIR)
    path = drv._use_secrets_dir(str(tmp_path / "secrets"), create=True)
    assert oct(os.stat(path).st_mode & 0o777) == "0o700"
    assert {m.SECRETS_DIR for m in mods} == {path}
    written = drv.extras.write_frame_admin_secret("juice", "admin@juice.theprotocol.cloud", "x" * 24,
                                                  registry_port=8750, domain=None, stack_dir="/nowhere")
    assert written.startswith(path) and oct(os.stat(written).st_mode & 0o777) == "0o600"


def test_frame_secrets_dir_is_read_at_import(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAME_SECRETS_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("extras_env", HERE.parent / "standup_extras.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SECRETS_DIR == str(tmp_path)

def test_the_operator_port_base_answers_the_question_preflight_asks():
    blocked = {31100, 31243, 31380}            # each of the old window's three blocks holds one port
    assert drv._free_cloud_port_base(taken=blocked) == 31400
    one_of_three = {31543, 31680}             # 31400's window keeps only its first block free: refused like preflight
    assert drv._free_cloud_port_base(taken=blocked | one_of_three) == 31700


def test_a_label_with_a_comma_is_refused_before_anything_is_rendered(monkeypatch, capsys):
    # §FRAMEPROV P4 (2026-09-13): the mainframe gate splits MAINFRAME_REGISTRY_NAMES on commas, and the label is in it.
    argv = list(BASE_ARGV)
    argv[argv.index("--frame-label") + 1] = "Juice, Inc."
    code, doc, _, fake = _plan(argv, monkeypatch, capsys)
    assert code == 2 and any("contains a comma" in r for r in doc["refusals"]), doc["refusals"]
    assert fake.writes == []


def test_the_label_reaches_both_allowlists_the_registry_process_reads(monkeypatch):
    # §FRAMEPROV P4 (2026-09-13), measured on plum: the process ran REGISTRY_NAME="Plum Proof" (a compose mutation) with
    # MAINFRAME_REGISTRY_NAMES=plum and CROSS_TEG_FUND_ORIGIN_ALLOWLIST=plum, the provisioner's render of a context whose
    # display name defaulted to the slug, so its own canary issuance answered 503 at the emission step.
    HostFake(monkeypatch)
    argv = [x.replace("juice", "plum") for x in BASE_ARGV]
    argv[argv.index("--frame-label") + 1] = "Plum Proof"
    args = drv.build_parser().parse_args(argv)
    assert drv.validate_args(args) == []
    prov = drv.load_provisioner()
    ctx = drv.build_ctx(args, 1789290319, prov)
    values = prov._template_values(ctx)
    seen = {"REGISTRY_NAME": args.frame_label, "MAINFRAME_REGISTRY_NAMES": values["MAINFRAME_REGISTRY_NAMES"],
            "IS_CENTRAL_REGISTRY": "true"}
    assert drv.mainframe_identity_problems(seen) == [], values["MAINFRAME_REGISTRY_NAMES"]
    assert values["CROSS_TEG_FUND_ORIGINS"].split(",") == ["plum", "plum-proof"]
    # the control: the context as the driver built it before the fix, its display name left at the slug
    before = prov._template_values(dataclasses.replace(ctx, mainframe_display_name=ctx.registry_name))
    assert drv.mainframe_identity_problems({**seen, "MAINFRAME_REGISTRY_NAMES": before["MAINFRAME_REGISTRY_NAMES"]})
    assert before["CROSS_TEG_FUND_ORIGINS"] == "plum"


def test_the_mainframe_check_is_the_gates_own_rule():
    gate = HERE.parents[2] / "AgentVault" / "agentvault_registry" / "src" / "agentvault_registry" / "core" / "mainframe_gate.py"
    builtin = next(node.value for node in ast.walk(ast.parse(gate.read_text()))
                   if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "builtin" for t in node.targets))
    assert tuple(ast.literal_eval(builtin)) == drv.MAINFRAME_BUILTIN_NAMES
    plum = {"REGISTRY_NAME": "Plum Proof", "MAINFRAME_REGISTRY_NAMES": "plum", "IS_CENTRAL_REGISTRY": "true"}
    assert drv.mainframe_identity_problems(plum) == ["REGISTRY_NAME 'Plum Proof' is not in MAINFRAME_REGISTRY_NAMES 'plum'"]
    assert drv.mainframe_identity_problems({**plum, "MAINFRAME_REGISTRY_NAMES": "plum,Plum Proof"}) == []
    assert drv.mainframe_identity_problems({**plum, "MAINFRAME_REGISTRY_NAMES": "plum,Plum Proof", "IS_CENTRAL_REGISTRY": "false"})
    assert drv.mainframe_identity_problems({"REGISTRY_NAME": "registry-test", "IS_CENTRAL_REGISTRY": "true"}) == []
    assert drv.mainframe_identity_problems(["REGISTRY_NAME=EU", "MAINFRAME_REGISTRY_NAMES=eu", "IS_CENTRAL_REGISTRY=true"]) == []
