"""V0659 (a): tp-proxy, the proxy's command, and its logs. init writes a spec from the Agent Forge starter's files that
names the credentials and never holds them, then reads the registry's answers; validate names every problem; run
--dry-run sends nothing; status, dead, replay, pause and resume act on the outbox file; no log line carries a secret.
Red before V0659: theprotocol.proxy.cli does not exist.
"""
from __future__ import annotations

import io
import json
import logging

import pytest
import yaml

import proxy_fake as F


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")


def _starter(tmp_path, *, secret=True):
    d = tmp_path / "my-agent"
    d.mkdir()
    (d / ".env").write_text(f"AGENT_NAME=Gate Scanner 3\nAGENT_DID={F.DID}\nREGISTRY_URL=https://registry.test\n"
                            "PUBLIC_URL=\nPRICE=0\n")
    if secret:
        (d / ".env.secret").write_text(f"CLIENT_ID={F.CLIENT_ID}\nCLIENT_SECRET={F.CLIENT_SECRET}\n")
    return d


def _main(argv, capsys, **kw):
    from theprotocol.proxy.cli import main
    code = main(argv, **kw)
    out = capsys.readouterr()
    return code, out.out, out.err


def _json_docs(text):
    """The JSON documents the command printed (each indented document, or one per line)."""
    dec, i, out = json.JSONDecoder(), 0, []
    text = text.strip()
    while i < len(text):
        doc, j = dec.raw_decode(text, i)
        out.append(doc)
        i = j
        while i < len(text) and text[i] in " \n":
            i += 1
    return out


# ── init ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_init_writes_a_spec_that_names_the_credentials_and_reads_the_registrys_answers(tmp_path, capsys):
    d = _starter(tmp_path)
    reg = F.FakeRegistry()
    code, out, err = _main(["init", "--from", str(d)], capsys, transport=reg.transport)
    assert code == 0, err
    text = (d / "proxy.yaml").read_text()
    assert F.CLIENT_SECRET not in text and F.CLIENT_ID not in text, "the spec names the credentials, never holds them"
    doc = yaml.safe_load(text)
    assert doc["identity"] == {"agent_did": F.DID, "client_id": "file:.env.secret#CLIENT_ID",
                               "client_secret": "file:.env.secret#CLIENT_SECRET",
                               "mtls": {"enabled": False, "dir": "./certs"}}
    assert doc["name"] == "gate-scanner-3" and doc["registry"] == "https://registry.test"
    written, report = _json_docs(out)
    assert written["written"]["agent_did"] == F.DID
    assert report["credentials"].endswith(f"issued a token for {F.DID}")
    assert report["card"]["active"] is True
    assert report["bond"]["status"] == "none" and report["bond"]["required_for_a_provider"] == "250"
    assert report["permissions"]["needed"] == {"attest": ["reputation.signal"]}
    assert "attestor role" in report["permissions"]["how"]
    assert F.CLIENT_SECRET not in out and all(t not in out for t in reg.tokens)
    assert [c["path"] for c in reg.calls] == ["/api/v1/auth/agent/token", f"/api/v1/agent-cards/{F.DID}",
                                              "/api/v1/agents/reputation-bond/status"]


def test_init_says_what_is_missing_and_writes_nothing(tmp_path, capsys):
    d = _starter(tmp_path, secret=False)
    code, out, err = _main(["init", "--from", str(d), "--no-check"], capsys)
    assert code == 2 and ".env.secret" in err and not (d / "proxy.yaml").exists()


def test_init_refuses_to_write_over_a_spec_and_reports_refused_credentials(tmp_path, capsys):
    d = _starter(tmp_path)
    assert _main(["init", "--from", str(d), "--no-check"], capsys)[0] == 0
    code, _out, err = _main(["init", "--from", str(d), "--no-check"], capsys)
    assert code == 2 and "--force" in err
    reg = F.FakeRegistry(client_secret="the-registry-knows-another")
    code, out, _err = _main(["init", "--from", str(d), "--force"], capsys, transport=reg.transport)
    assert code == 3 and "Incorrect client_id" in out


# ── validate, run --dry-run, and the outbox commands ─────────────────────────────────────────────────────────────────

def _spec_file(tmp_path, **kw):
    doc = F.spec_doc(tmp_path, **kw)
    p = tmp_path / "proxy.yaml"
    p.write_text(yaml.safe_dump(doc))
    return str(p)


def test_validate_answers_the_spec_or_every_problem(tmp_path, capsys):
    spec = _spec_file(tmp_path)
    code, out, _ = _main(["validate", spec], capsys)
    assert code == 0 and json.loads(out)["permissions"] == {"attest": ["reputation.signal"]}
    from pathlib import Path
    doc = yaml.safe_load(Path(spec).read_text())
    doc["identity"]["client_secret"] = F.CLIENT_SECRET
    doc["mappings"][0]["to"] = "nowhere"
    Path(spec).write_text(yaml.safe_dump(doc))
    code, out, err = _main(["validate", spec], capsys)
    assert code == 2 and "identity.client_secret" in err and "nowhere" in err
    assert F.CLIENT_SECRET not in err, "the refusal names the path, not the value"


def test_run_dry_run_prints_what_it_would_send_and_sends_nothing(tmp_path, capsys):
    spec = _spec_file(tmp_path, items=[{"id": "r1", "v": 7}])
    reg = F.FakeRegistry()
    code, out, err = _main(["run", spec, "--dry-run", "--once", "--no-service"], capsys, transport=reg.transport)
    assert code == 0, err
    shown = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(shown) == 1 and shown[0]["status"] == "dry_run"
    assert shown[0]["data"]["request"]["attestation_data"]["claim"] == {"value": 7, "id": "r1"}
    assert reg.calls == []
    assert not (tmp_path / "state.db").exists(), "a dry run keeps nothing"


def test_status_dead_replay_pause_and_resume_act_on_the_outbox(tmp_path, capsys):
    spec = _spec_file(tmp_path, items=[{"id": "r1", "v": 1}, {"id": "r2", "v": 2}])
    reg = F.FakeRegistry()
    reg.mode = "refuse"
    assert _main(["run", spec, "--once", "--no-service"], capsys, transport=reg.transport)[0] == 0
    code, out, _ = _main(["status", spec], capsys)
    st = json.loads(out)
    assert code == 0 and st["outbox"] == {"pending": 0, "done": 0, "dead": 2}
    code, out, _ = _main(["dead", spec], capsys)
    dead = [json.loads(line) for line in out.splitlines()]
    assert [d["record_id"] for d in dead] == ["r1", "r2"] and "reputation.signal" in dead[0]["why"]
    assert _main(["replay", spec], capsys)[0] == 2, "replay what: it names its selector"
    assert json.loads(_main(["pause", spec, "reading"], capsys)[1])["mappings"]["reading"]["paused"] is True
    code, out, _ = _main(["replay", spec, "--all"], capsys)
    assert json.loads(out) == {"replayed": 2}
    reg.mode = "ok"
    _main(["run", spec, "--once", "--no-service"], capsys, transport=reg.transport)
    assert reg.effects == [], "paused: nothing sent"
    st = json.loads(_main(["resume", spec, "reading"], capsys)[1])
    assert st["mappings"]["reading"]["paused"] is False
    _main(["run", spec, "--once", "--no-service"], capsys, transport=reg.transport)
    assert len(reg.effects) == 2
    assert json.loads(_main(["status", spec], capsys)[1])["outbox"] == {"pending": 0, "done": 2, "dead": 0}


def test_status_before_a_run_says_there_is_no_outbox(tmp_path, capsys):
    code, _out, err = _main(["status", _spec_file(tmp_path)], capsys)
    assert code == 2 and "has not run" in err


# ── the logs ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_log_line_carries_a_secret(tmp_path):
    from theprotocol.proxy.logs import setup
    buf = io.StringIO()
    token = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0.c2ln"
    setup(secrets=lambda: (F.CLIENT_SECRET, token), stream=buf, logger="theprotocol.proxy.test_logs")
    lg = logging.getLogger("theprotocol.proxy.test_logs")
    lg.warning("the registry answered %s for %s", "401", F.CLIENT_SECRET, extra={"proxy": {"auth": f"Bearer {token}"}})
    try:
        raise RuntimeError(f"boom with {F.CLIENT_SECRET} inside")
    except RuntimeError:
        lg.exception("failed")
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    assert len(lines) == 2 and lines[0]["auth"] == "Bearer [redacted]" and "[redacted]" in lines[0]["msg"]
    assert F.CLIENT_SECRET not in buf.getvalue() and token not in buf.getvalue()
    assert lines[1]["level"] == "error" and "RuntimeError" in lines[1]["error"]
