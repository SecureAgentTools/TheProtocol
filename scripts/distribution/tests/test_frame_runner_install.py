"""§HELLOFRAME lane 6 (2026-09-18): frame-runner-install.py, the runner on a stranger's host.

Pure parts pinned directly; the host parts (group, files, systemd, the ping) run only under --dry-run here, which
must touch nothing and still print the contract line frame-up reads. Nothing here needs root, docker or systemd."""
import importlib.util
import pathlib
import re
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("frame_runner_install", HERE.parent / "frame-runner-install.py")
fri = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fri
SPEC.loader.exec_module(fri)

RUNNER_DIR = HERE.parents[2] / "tools" / "frame-runner"
UNIT = (RUNNER_DIR / "theprotocol-frame-runner.service").read_text()


def _export(tmp_path):
    """A fixture export: the REAL runner files (the installer loads the runner for its instance paths and its wire
    format), placeholders for the driver, the teardown and the template."""
    root = tmp_path / "export"
    for rel in fri.EXPORT_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.startswith("tools/frame-runner/"):
            p.write_text((RUNNER_DIR / p.name).read_text())
        else:
            p.write_text("# placeholder\n")
    fri._RUNNER.clear()
    return root


def _args(**over):
    argv = ["--export-root", over.pop("export_root"), "--stack-root", over.pop("stack_root")]
    for k, v in over.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return fri.build_parser().parse_args(argv)


def test_uids_are_parsed_and_refused():
    assert fri.parse_uids("0,1000") == [0, 1000]
    assert fri.parse_uids(" 1000, 0 ,1000") == [0, 1000]
    for bad in ("", "root", "0,-1", "1000,x"):
        with pytest.raises(fri.Refused) as e:
            fri.parse_uids(bad)
        assert e.value.code == 2


def test_image_lists_follow_the_prefix_and_version_and_take_overrides():
    lists = fri.image_lists("agentvault2", "v0398")
    assert lists == {"registry": ["agentvault2/registry:v0398"], "teg": ["agentvault2/teg-layer:v0398"],
                     "event_store": ["agentvault2/event-store:v0398"], "auditor": ["agentvault2/auditor:v0398"],
                     "directory": ["agentvault2/directory:v0398"]}
    assert fri.image_lists("agentvault2", "") == {k: [] for k, _ in fri.IMAGE_KEYS}
    lists = fri.image_lists("agentvault2", "v0398", {"registry": "agentvault2-registry-a:v0398, x/registry:v1"})
    assert lists["registry"] == ["agentvault2-registry-a:v0398", "x/registry:v1"]
    assert lists["teg"] == ["agentvault2/teg-layer:v0398"]
    with pytest.raises(fri.Refused):
        fri.image_lists("agentvault2", "latest")
    with pytest.raises(fri.Refused):
        fri.image_lists("agentvault2", "v1", {"teg": "agentvault2/teg-layer"})     # no tag at all


def test_the_policy_carries_the_flags_and_keeps_what_it_does_not_manage(tmp_path):
    a = _args(export_root=str(tmp_path), stack_root=str(tmp_path / "stack"), edge="caddy",
              domain="harbor.example", version="v0398", posture="sandbox", allowed_uids="0,1000",
              mail_server="smtp.example", mail_address="noreply@harbor.example")
    existing = {"dns": {"zone_id": "keepme", "ipv4": "203.0.113.5"}, "plan_timeout_s": 999,
                "edge": "nginx", "images": {"registry": ["old:1"]}, "mail": {"server": "old"}}
    pol = fri.build_policy(a, existing)
    assert pol["edge"] == "caddy" and pol["domain"] == "harbor.example" and pol["posture"] == "sandbox"
    assert pol["wire_prod"] is False and pol["socket_group"] == "deploy" and pol["allowed_uids"] == [0, 1000]
    assert pol["images"]["registry"] == ["agentvault2/registry:v0398"]
    assert pol["mail"] == {"server": "smtp.example", "address": "noreply@harbor.example", "port": 587,
                           "token_file": "/root/.noreply_smtp_token"}
    assert pol["dns"] == existing["dns"] and pol["plan_timeout_s"] == 999, "unmanaged keys survive"
    assert pol["max_load"] == 40.0 and pol["min_mem_gib"] == 15.0 and pol["min_free_gb"] == 60.0
    assert pol["_written_by"].startswith("frame-runner-install.py on 20")
    # no --mail-server: a previous mail block is carried over rather than dropped
    b = _args(export_root=str(tmp_path), stack_root=str(tmp_path / "stack"))
    assert fri.build_policy(b, {"mail": {"server": "old", "address": "a@b"}})["mail"] == {"server": "old", "address": "a@b"}
    with pytest.raises(fri.Refused):
        fri.build_policy(_args(export_root=str(tmp_path), stack_root=str(tmp_path), mail_server="smtp.example"), {})


def test_the_unit_points_every_runner_path_into_the_export_root():
    text = fri.render_unit(UNIT, export_root="/srv/tp", python="/usr/bin/python3.12", stack_root="/srv/frames")
    lines = text.splitlines()
    assert "ExecStart=/usr/bin/python3.12 -u /srv/tp/tools/frame-runner/frame_runner.py serve" in lines
    assert "Environment=FRAME_RUNNER_DRIVER=/srv/tp/scripts/hetzner_demo/standup_driver.py" in lines
    assert "Environment=FRAME_RUNNER_TEARDOWN=/srv/tp/scripts/hetzner_demo/teardown_hetzner_frame.sh" in lines
    assert "Environment=FRAME_RUNNER_TEMPLATE=/srv/tp/templates/frame-test/docker-compose.frame-test.yml.tmpl" in lines
    assert "Environment=FRAME_RUNNER_STACK_ROOT=/srv/frames" in lines
    assert "Environment=FRAME_RUNNER_CONFIG=/etc/theprotocol/frame-runner.json" in lines
    assert "Environment=FRAME_RUNNER_PYTHON=/usr/bin/python3.12" in lines
    assert sum(l.startswith("ExecStart=") for l in lines) == 1
    assert "/opt/theprotocol/stack/Agentvault2" not in text, "no path of the network's own host survives"
    for keep in ("RuntimeDirectory=theprotocol", "KillMode=process", "UMask=0027", "WantedBy=multi-user.target"):
        assert keep in lines, keep
    again = fri.render_unit(text, export_root="/srv/tp", python="/usr/bin/python3.12", stack_root="/srv/frames")
    assert again == text, "a second render is idempotent"
    with pytest.raises(fri.Refused):
        fri.render_unit("[Unit]\nDescription=not it\n", export_root="/x", python="/p", stack_root="/s")


def test_the_export_root_check_names_what_is_missing(tmp_path):
    root = _export(tmp_path)
    assert fri.check_export_root(str(root)) == []
    (root / "scripts" / "hetzner_demo" / "standup_driver.py").unlink()
    assert fri.check_export_root(str(root)) == ["scripts/hetzner_demo/standup_driver.py"]


def test_a_dry_run_touches_nothing_and_ends_with_the_contract_line(tmp_path, capsys):
    root = _export(tmp_path)
    rc = fri.main(["--export-root", str(root), "--stack-root", str(tmp_path / "stack"), "--edge", "caddy",
                   "--domain", "harbor.example", "--version", "v0398", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    last = out.rstrip("\n").splitlines()[-1]
    assert re.fullmatch(r"FRAME_RUNNER_SOCKET_GID=-?\d+ SOCKET=/run/theprotocol/frame-runner\.sock "
                        r"OPERATOR_SOCKET=/run/theprotocol/operator/frame-runner\.sock "
                        r"OPERATOR_SOCKET_DIR=/run/theprotocol/operator EDGE=caddy", last), last
    assert '"edge": "caddy"' in out and "ExecStart=/usr/bin/python3 -u " + str(root) in out
    assert not (tmp_path / "stack").exists(), "a dry run creates nothing"
    assert "dry run: the policy that would be written" in out and "dry run: the unit that would be written" in out
    assert '"wire_prod": false' in out and '"images": {' in out and '"agentvault2/registry:v0398"' in out


def test_an_incomplete_export_root_is_refused_with_exit_2(tmp_path, capsys):
    root = _export(tmp_path)
    (root / "tools" / "frame-runner" / "frame_dns.py").unlink()
    rc = fri.main(["--export-root", str(root), "--stack-root", str(tmp_path), "--dry-run"])
    assert rc == 2
    assert "lacks ['tools/frame-runner/frame_dns.py']" in capsys.readouterr().out


def test_a_bad_edge_or_posture_is_refused_by_the_parser(tmp_path):
    root = _export(tmp_path)
    for flag, value in (("--edge", "traefik"), ("--posture", "prod")):
        with pytest.raises(SystemExit) as e:
            fri.main(["--export-root", str(root), "--stack-root", str(tmp_path), flag, value, "--dry-run"])
        assert e.value.code == 2


def test_the_contract_line_is_one_line_frame_up_can_split():
    line = fri.last_line(989, "caddy")
    parts = dict(p.split("=", 1) for p in line.split())
    assert parts == {"FRAME_RUNNER_SOCKET_GID": "989", "SOCKET": "/run/theprotocol/frame-runner.sock",
                     "OPERATOR_SOCKET": "/run/theprotocol/operator/frame-runner.sock",
                     "OPERATOR_SOCKET_DIR": "/run/theprotocol/operator", "EDGE": "caddy"}
    line = fri.last_line(989, "caddy", socket="/run/theprotocol/hello/frame-runner.sock",
                         operator_socket="/run/theprotocol/hello/operator/frame-runner.sock")
    parts = dict(p.split("=", 1) for p in line.split())
    assert parts["SOCKET"] == "/run/theprotocol/hello/frame-runner.sock"
    assert parts["OPERATOR_SOCKET_DIR"] == "/run/theprotocol/hello/operator"


# ---- instances: a second runner beside a host's production one ------------------------------------------------

def test_the_paths_come_from_the_runners_own_rule(tmp_path):
    root = _export(tmp_path)
    single = fri.runner_paths(str(root), "")
    assert single["unit"] == "theprotocol-frame-runner" and single["config"] == fri.POLICY
    assert single["operator_socket"] == fri.OPERATOR_SOCKET and single["instance"] == ""
    assert single["unit_path"] == "/etc/systemd/system/theprotocol-frame-runner.service"
    hello = fri.runner_paths(str(root), "hello")
    assert hello == {"instance": "hello", "unit": "theprotocol-frame-runner-hello",
                     "unit_path": "/etc/systemd/system/theprotocol-frame-runner-hello.service",
                     "config": "/etc/theprotocol/frame-runner-hello.json",
                     "socket": "/run/theprotocol/hello/frame-runner.sock",
                     "operator_socket": "/run/theprotocol/hello/operator/frame-runner.sock",
                     "state": "/var/lib/theprotocol/frame-runner-hello",
                     "runtime_dir": "theprotocol/hello", "state_dir": "theprotocol/frame-runner-hello"}
    with pytest.raises(fri.Refused) as e:
        fri.runner_paths(str(root), "Hello World")
    assert e.value.code == 2


def test_an_instance_unit_scopes_its_directories_and_names_its_paths(tmp_path):
    root = _export(tmp_path)
    paths = fri.runner_paths(str(root), "hello")
    text = fri.render_unit(UNIT, export_root="/srv/tp", python="/usr/bin/python3", stack_root="/srv/frames",
                           config=paths["config"], paths=paths)
    lines = text.splitlines()
    assert "RuntimeDirectory=theprotocol/hello" in lines and "RuntimeDirectory=theprotocol" not in lines
    assert "StateDirectory=theprotocol/frame-runner-hello" in lines and "StateDirectory=theprotocol/frame-runner" not in lines
    assert any(l.startswith("Description=") and l.endswith("[instance hello]") for l in lines)
    for want in ("Environment=FRAME_RUNNER_INSTANCE=hello",
                 "Environment=FRAME_RUNNER_SOCKET=/run/theprotocol/hello/frame-runner.sock",
                 "Environment=FRAME_RUNNER_OPERATOR_SOCKET=/run/theprotocol/hello/operator/frame-runner.sock",
                 "Environment=FRAME_RUNNER_STATE=/var/lib/theprotocol/frame-runner-hello",
                 "Environment=FRAME_RUNNER_CONFIG=/etc/theprotocol/frame-runner-hello.json",
                 "Environment=FRAME_RUNNER_PROTECTED_LIST=/etc/theprotocol/protected-frames.list"):
        assert want in lines, want
    assert "ExecStart=/usr/bin/python3 -u /srv/tp/tools/frame-runner/frame_runner.py serve" in lines
    # the single runner's unit is byte-identical whether or not the argument is passed as None
    plain = fri.render_unit(UNIT, export_root="/srv/tp", python="/usr/bin/python3", stack_root="/srv/frames")
    assert plain == fri.render_unit(UNIT, export_root="/srv/tp", python="/usr/bin/python3", stack_root="/srv/frames",
                                    paths=None)
    assert "FRAME_RUNNER_INSTANCE" not in plain and "RuntimeDirectory=theprotocol\n" in plain
    with pytest.raises(fri.Refused):
        fri.render_unit(UNIT.replace("RuntimeDirectory=theprotocol\n", ""), export_root="/x", python="/p",
                        stack_root="/s", config=paths["config"], paths=paths)


def test_a_dry_run_with_an_instance_names_the_instance_everywhere(tmp_path, capsys):
    root = _export(tmp_path)
    rc = fri.main(["--export-root", str(root), "--stack-root", str(tmp_path / "stack"), "--edge", "caddy",
                   "--domain", "hello.example", "--version", "v1", "--instance", "hello", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would be written to /etc/theprotocol/frame-runner-hello.json" in out
    assert "would be written to /etc/systemd/system/theprotocol-frame-runner-hello.service" in out
    assert '"_instance": "hello"' in out and "Environment=FRAME_RUNNER_INSTANCE=hello" in out
    last = out.rstrip("\n").splitlines()[-1]
    parts = dict(p.split("=", 1) for p in last.split())
    assert parts["SOCKET"] == "/run/theprotocol/hello/frame-runner.sock"
    assert parts["OPERATOR_SOCKET"] == "/run/theprotocol/hello/operator/frame-runner.sock"
    assert parts["OPERATOR_SOCKET_DIR"] == "/run/theprotocol/hello/operator" and parts["EDGE"] == "caddy"
    # the single runner's files are named in the unit's own comment header, never as a write target here
    assert "would be written to /etc/theprotocol/frame-runner.json" not in out
    assert "would be written to /etc/systemd/system/theprotocol-frame-runner.service" not in out
    rc = fri.main(["--export-root", str(root), "--stack-root", str(tmp_path), "--instance", "Hello", "--dry-run"])
    assert rc == 2 and "named like a frame" in capsys.readouterr().out
