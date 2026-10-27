"""§MCPTEST30 (V0640): downloadBundleViaOnboard earns its row on a throwaway agent, and no row keeps a file's bytes.

The tool's request carries the agent's client secret and its answer, a zip, embeds it (.env.secret), so its row was
refusal-only (the safe-path lifecycle's bad shape) and earned_ad_devtools kept it on its "Not here" list. Pinned: the
lifecycle downloads a throwaway agent's bundle with its own credentials and writes the tool's row by hand (no argument,
no byte: whether a zip came back, its entries' names and sizes where the answer lists them); its refusals (an unknown
agent, a client id or a secret that is not the agent's, a template no registry has) are refusal rows; a 2xx that is
not a zip, or a bundle without its .env.secret, is a BUG-FIND; the throwaway goes in every case. zip_answer reads both
forms a binary answer takes (the first 300 characters as `raw`, or the manifest of fix/mcp-binary-answers), and a
row's excerpt never keeps `content_base64`, wherever its key stands. agentvault2-aa's two agent builder checks read a
zip the same way.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_agent_public as EAP
from agentvault_registry.api_tests.contracts import earned_fixtures as ef
from agentvault_registry.api_tests.contracts import mcp_lifecycles as M

DID = "did:theprotocol:11111111-2222-4333-8444-555555555555"
SECRET = "tp_secret_" + "s3cr3t" * 8
TOOL = EAP.ONBOARD_BUNDLE


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


RAW_ZIP = {"status": "ok", "raw": "PK\x03\x04\x14\x00\x00\x00\x08\x00 the first characters of a deflated file"}
MANIFEST = {"status": "ok", "content_type": "application/zip", "filename": "agent-x.zip", "size_bytes": 2048,
            "files": [{"name": ".env", "size": 120}, {"name": ".env.secret", "size": 90},
                      {"name": "docker-compose.yml", "size": 400}],
            "sha256": "ab" * 32, "content_base64": "UEsDBBQAAAAIAA" + "A" * 64}


def _run(monkeypatch, success=RAW_ZIP, own_ok=True, agent=True):
    calls, closed = [], []

    class _T:
        def __init__(self, *a, **k):
            pass

        async def developer(self, role, verify=True):
            return {"access_token": "owner-jwt", "email": "x@example.com", "password": "p"}

        async def agent(self, dev, label=""):
            if not agent:
                return {"why": "createAgent answered HTTP 503"}
            return {"did": DID, "client_id": "agent-own-client", "client_secret": SECRET, "agent_jwt": "a"}

        async def close(self):
            closed.append(True)

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, json.loads(json.dumps(args)), jwt))
        b = args["bundle_data"]
        if b["template_type"] != "minimal":
            return False, _error(f"HTTP 404: Template '{b['template_type']}' is not available on this registry; "
                                 "it has: minimal, ppao"), "404"
        if b["agent_did"] != DID:
            return False, _error(f"HTTP 404: Agent {b['agent_did']} not found"), "404"
        if b["client_id"] != "agent-own-client":
            return False, _error("HTTP 400: client_id does not match the agent record"), "400"
        if b["client_secret"] != SECRET:
            return False, _error("HTTP 400: client_secret does not match the agent record"), "400"
        if not own_ok:
            return False, _error("HTTP 500: Template 'minimal' not available. Contact administrator."), "500"
        return True, _answer(success), "200"

    monkeypatch.setattr(ef, "Throwaways", _T)
    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", flow_values={})
    asyncio.run(EAP.lifecycle_earned_onboard_bundle(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes, calls, closed


def test_zip_answer_reads_both_forms_and_nothing_else():
    assert ef.zip_answer(RAW_ZIP) == (True, [])
    assert ef.zip_answer(MANIFEST) == (True, [{"name": ".env", "size": 120}, {"name": ".env.secret", "size": 90},
                                              {"name": "docker-compose.yml", "size": 400}])
    # controls: an empty files list and a raw answer that is not a zip are not zips (the BUG-FIND still fires)
    assert ef.zip_answer({"status": "ok", "files": []}) == (False, [])
    assert ef.zip_answer({"status": "ok", "raw": "<!doctype html>"}) == (False, [])
    assert ef.zip_answer("PK") == (False, [])


def test_an_excerpt_never_keeps_a_files_content_wherever_its_key_stands():
    first = {"content_base64": "UEsDBBQ", "status": "ok", "a": 1, "b": 2, "c": 3, "d": 4}
    assert M.result_excerpt(first) == {"status": "ok", "a": 1, "b": 2, "c": 3, "d": 4}
    assert "content_base64" not in M.result_excerpt(MANIFEST)


def test_the_bundle_row_keeps_no_argument_and_no_byte(monkeypatch):
    outcomes, calls, closed = _run(monkeypatch)
    row = outcomes[TOOL]
    assert row["healthy"] and row["status_code"] == 200 and row["args_used"] == {}
    assert row["result_excerpt"] == {"zip": True, "entries": 0, "files": [], "template_type": "minimal"}
    blob = json.dumps(outcomes)
    assert SECRET not in blob and "deflated" not in blob
    own = [a["bundle_data"]["template_type"] for t, a, _j in calls if a["bundle_data"]["client_secret"] == SECRET]
    assert sorted(own) == ["apitest-no-such-template", "minimal"] and closed == [True]   # the download, the 404


def test_the_manifest_form_keeps_names_and_sizes_and_never_the_content(monkeypatch):
    outcomes, _calls, _closed = _run(monkeypatch, success=MANIFEST)
    row = outcomes[TOOL]
    assert row["healthy"] and row["result_excerpt"]["entries"] == 3
    assert [f["name"] for f in row["result_excerpt"]["files"]] == [".env", ".env.secret", "docker-compose.yml"]
    blob = json.dumps(outcomes)
    assert SECRET not in blob and MANIFEST["content_base64"] not in blob and MANIFEST["sha256"] not in blob


def test_the_refusals_are_refusal_rows(monkeypatch):
    outcomes, _calls, _closed = _run(monkeypatch)
    assert outcomes["refusal: downloadBundleViaOnboard for an agent that does not exist"]["healthy"]
    assert outcomes["refusal: downloadBundleViaOnboard with a client id that is not the agent's"]["healthy"]
    assert outcomes["refusal: downloadBundleViaOnboard with a secret that is not the agent's"]["healthy"]
    assert outcomes["refusal: downloadBundleViaOnboard for a template no registry has"]["healthy"]


def test_a_2xx_that_is_not_a_zip_or_lacks_the_secret_file_is_a_bug_find(monkeypatch):
    outcomes, _c, closed = _run(monkeypatch, success={"status": "ok", "raw": "<!doctype html>"})
    assert not outcomes[TOOL]["healthy"] and "BUG-FIND" in outcomes[TOOL]["fail_reason"] and closed == [True]
    lacking = dict(MANIFEST, files=[{"name": "README.md", "size": 10}])
    outcomes, _c, _closed = _run(monkeypatch, success=lacking)
    assert not outcomes[TOOL]["healthy"] and ".env.secret" in outcomes[TOOL]["fail_reason"]


def test_a_refused_download_fails_and_no_agent_is_not_measured(monkeypatch):
    outcomes, _c, closed = _run(monkeypatch, own_ok=False)
    assert not outcomes[TOOL]["healthy"] and "HTTP 500" in outcomes[TOOL]["fail_reason"] and closed == [True]
    outcomes, calls, closed = _run(monkeypatch, agent=False)
    assert outcomes[TOOL]["skip_reason"].startswith("NOT MEASURED") and not calls and closed == [True]


def test_the_safe_path_probe_is_a_refusal_row_and_the_builder_checks_read_a_zip_by_zip_answer():
    src = (pathlib.Path(M.__file__)).read_text(encoding="utf-8")
    assert '"a request without the agent\'s DID and credentials", codes=(422,)' in src
    dev = (pathlib.Path(M.__file__).parent / "earned_ad_devtools.py").read_text(encoding="utf-8")
    assert dev.count("not zip_answer(pkg)[0]") == 2 and 'startswith("PK")' not in dev
    assert {"name": "earned_onboard_bundle", "runner": EAP.lifecycle_earned_onboard_bundle} in EAP.LIFECYCLES
