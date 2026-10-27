"""§PUSH (2026-10-06, agentvault2-09): the operator's own push relay, through the provisioning flow.

His words: "afterwards we do the same with push", "provisioner should also provision them", "fix the things you find on
the way make it secure". Every operator ran with push switched off (no PUSH_NOTIFY_ENABLED), so neither Web Push nor
Pocket's phone pairing reached an operator's users. host_work now carries an override (the frames' ntfy relay on the
operator's own network) and writes its values; the registry renders a SUBSCRIBE-ONLY public vhost the runner writes beside
the console's. These pin the rules every half derives from, and the one shape that must never regress: a public push door
that refuses ntfy's GET publish and delete forms.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pathlib
import re
import types

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
_TEMPLATES = pathlib.Path(os.environ.get("OPA_TEMPLATES_DIR")
                          or "/opt/theprotocol/stack/Agentvault2/scripts/distribution/nginx-templates")
oc = importlib.import_module("agentvault_registry.core.operator_compose")
ALLOW = r'location ~ "^/[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*/(json|sse|raw|ws|auth)$"'


def _hw():
    spec = importlib.util.spec_from_file_location("_push_hw", _SRC / "host_work.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _locations(text):
    out, cur, depth, buf = {}, None, 0, []
    for line in text.splitlines():
        s = line.strip()
        if cur is None and s.startswith("location ") and s.endswith("{"):
            cur, depth, buf = s[:-1].strip(), 1, []
            continue
        if cur is not None:
            depth += s.count("{") - s.count("}")
            if depth <= 0:
                out[cur] = "\n".join(buf)
                cur = None
            else:
                buf.append(s)
    return out


def test_the_push_name_is_one_label_under_the_operators_suffix():
    assert oc.operator_push_host("amsterdam.op.theprotocol.cloud") == "amsterdam-push.op.theprotocol.cloud"
    assert oc.operator_push_host("x.frame.example") == "x-push.frame.example"
    for bad in ("", "nodot", ".op.theprotocol.cloud"):
        with pytest.raises(ValueError):
            oc.operator_push_host(bad)


def test_the_push_port_is_the_blocks_fixed_offset():
    assert oc.PUSH_PORT_OFFSET == 99 and oc.operator_push_port(31300) == 31399


def test_the_push_vhost_is_subscribe_only_and_serves_one_name_and_one_port():
    v = oc.operator_push_vhost(push_host="amsterdam-push.op.theprotocol.cloud", push_port=31399,
                               ssl_cert_name="op.theprotocol.cloud")
    locs = _locations(v)
    assert set(locs) == {"location = /v1/health", ALLOW, "location /"}, sorted(locs)
    assert locs["location /"].strip() == "return 403;", "every other path, the GET publish forms included, is refused"
    assert re.findall(r"\bserver_name\s+([^;]+);", v) == ["amsterdam-push.op.theprotocol.cloud"]
    assert set(re.findall(r"\bproxy_pass\s+(\S+?);", v)) == {"http://127.0.0.1:31399"}
    assert all("/op.theprotocol.cloud/" in c for c in re.findall(r"\bssl_certificate(?:_key)?\s+(\S+?);", v))
    assert "include snippets/" not in v, "the frame push vhost's own three headers: a console subscribe is cross-origin"
    rx = re.compile(r"^/[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*/(json|sse|raw|ws|auth)$")
    for path in ("/t/publish", "/t/send", "/t/trigger", "/t/abc/delete", "/t/abc/read", "/t/abc/clear", "/t"):
        assert not rx.match(path), path


def test_without_the_override_the_operator_runs_no_relay(tmp_path):
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    (tmp_path / "templates").mkdir()
    notes = []
    assert mod._push_steps({"nginx_templates_dir": str(tmp_path / "templates")}, str(stack), "x", notes) == {"push": False}
    assert not (stack / mod.PUSH_OVERRIDE).exists() and "no override" in notes[0]


def test_with_the_override_it_is_carried_from_the_live_templates(tmp_path):
    mod = _hw()
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    tmpl = tmp_path / "templates"
    tmpl.mkdir()
    (tmpl / mod.PUSH_OVERRIDE).write_text("services: {}\n", encoding="utf-8")
    assert mod._push_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "x", []) == {"push": True}
    assert (stack / mod.PUSH_OVERRIDE).exists() and oct((stack / mod.PUSH_OVERRIDE).stat().st_mode)[-3:] == "644"


def test_the_env_carries_the_push_values_only_with_the_override(tmp_path, monkeypatch):
    mod = _hw()
    monkeypatch.chdir(tmp_path)
    stack = tmp_path / "cloud-op-lisbon"
    stack.mkdir()
    (stack / "docker-compose.operator.yml").write_text("services:\n  registry:\n    image: x\n", encoding="utf-8")
    spec = {"env": {}, "operator_secrets": {}, "compose": {"domain": "lisbon.op.theprotocol.cloud", "reg_port": 31400}}
    env_path = mod._write_operator_env(spec, str(stack), "lisbon", [])
    assert "PUSH_" not in pathlib.Path(env_path).read_text(encoding="utf-8"), "no override, no push values"
    (stack / mod.PUSH_OVERRIDE).write_text(
        "services:\n  ntfy:\n    image: ${OPERATOR_NTFY_IMAGE:?x}\n    ports:\n      - \"127.0.0.1:${OPERATOR_PUSH_PORT:?y}:80\"\n",
        encoding="utf-8")
    (stack / ".env.operator").unlink()
    env_path = mod._write_operator_env(spec, str(stack), "lisbon", [])
    kv = dict(ln.split("=", 1) for ln in pathlib.Path(env_path).read_text(encoding="utf-8").splitlines()
              if "=" in ln and not ln.startswith("#"))
    assert kv["PUSH_NOTIFY_ENABLED"] == "true"
    assert kv["PUSH_NTFY_URL"] == "http://cloud-op-lisbon-ntfy", "publishing stays on the operator's own network"
    assert kv["PUSH_NTFY_PUBLIC_URL"] == "https://lisbon-push.op.theprotocol.cloud"
    assert kv["PUSH_APP_BASE_URL"] == "https://lisbon.op.theprotocol.cloud", "links and the rp-id: the operator's console"
    assert kv["OPERATOR_PUSH_PORT"] == "31499" and kv["OPERATOR_NTFY_IMAGE"] == mod.NTFY_IMAGE
    assert oct(pathlib.Path(env_path).stat().st_mode)[-3:] == "600"


def test_the_allocator_reserves_the_push_offset():
    """A block is free only when the relay's port is too; otherwise the next operator could be given a block whose +99
    another process already holds and fail at `up`."""
    cp = importlib.import_module("agentvault_registry.services.cloud_provisioner")
    assert cp._BLOCK_OFFSETS == (0, 43, 80, oc.PUSH_PORT_OFFSET)


@pytest.mark.skipif(not (_TEMPLATES / "docker-compose.operator.push.yml").exists(),
                    reason="the stack's operator templates are not beside this checkout")
def test_the_real_override_agrees_with_the_provisioner():
    mod = _hw()
    text = (_TEMPLATES / mod.PUSH_OVERRIDE).read_text(encoding="utf-8")
    assert re.search(r"container_name: \$\{REGISTRY_NAME:-operator\}-ntfy\n", text), \
        "PUSH_NTFY_URL dials cloud-op-<slug>-ntfy and REGISTRY_NAME is cloud-op-<slug>"
    needed = mod._compose_interpolations(text)
    assert needed == {"OPERATOR_NTFY_IMAGE", "OPERATOR_PUSH_PORT"}, needed
    assert needed <= set(mod.push_env_values("x", "x.op.theprotocol.cloud", 31300))
    assert '"127.0.0.1:${OPERATOR_PUSH_PORT:?' in text, "the relay listens on loopback only; the public side is the vhost"
