"""V0664, gwo_a0af9f35 (M8, session-tester seq 4099): POST /api/v1/workflow-templates/{tid}/certified answered 500 on every
call. DbStore.agent_attestations imported get_httpx_verify from core.tls_client, which has no such function (it lives in
es_ssl_helper), inside the function: the boot-import gate never runs it, pyflakes does not resolve a module's names, and the
route tests stub the method. These tests run it.

  1. agent_attestations itself, against a TEG double: the agent's own list (GET <teg>/attestation, the route
     routers/teg_integration.list_attestations calls), its token through prepare_teg_headers, the certificate type, the
     TEG's own page limit; a TEG that does not answer 200 is the library's 503.
  2. the sweep: every import inside a function of the three M4 files resolves, each name it imports exists, and every
     attribute a function reads off a module it imported that way exists on that module.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import pathlib
import types

import httpx
import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
M4_FILES = ("services/workflow_templates.py", "routers/workflow_templates.py", "mcp/tools_workflow_templates.py")


class _Db:
    def __init__(self, agent):
        self.agent = agent

    async def execute(self, stmt):
        return types.SimpleNamespace(scalar_one_or_none=lambda: self.agent)


def _teg(monkeypatch, handler):
    real = httpx.AsyncClient
    seen = []

    def client(**kw):
        kw.pop("verify", None)
        return real(transport=httpx.MockTransport(lambda req: (seen.append(req), handler(req))[1]), **kw)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    from agentvault_registry.routers import teg_integration as ti

    async def token(agent_id, did):
        return "teg-token-for-" + did
    monkeypatch.setattr(ti, "get_teg_token_for_agent", token)
    return seen


def test_agent_attestations_reads_the_agents_own_list_from_the_teg(monkeypatch):
    from agentvault_registry.routers import teg_integration as ti
    from agentvault_registry.services import workflow_templates as wt
    seen = _teg(monkeypatch, lambda req: httpx.Response(200, json=[
        {"submission_id": "sub_1", "attestation_type": wt.CERTIFICATE_TYPE, "attestation_hash": "h1"},
        {"attestation_id": "att_2", "attestation_type": wt.CERTIFICATE_TYPE, "attestation_hash": "h2"}]))
    out = asyncio.run(wt.DbStore(_Db(types.SimpleNamespace(id=7, did="did:a:me"))).agent_attestations("did:a:me"))
    assert out == [{"attestation_id": "sub_1", "attestation_type": wt.CERTIFICATE_TYPE, "hash": "h1"},
                   {"attestation_id": "att_2", "attestation_type": wt.CERTIFICATE_TYPE, "hash": "h2"}]
    [req] = seen
    assert req.url.path == f"{httpx.URL(ti.TEG_API_BASE_URL).path.rstrip('/')}{ti.TEG_API_V1_PREFIX}/attestation"
    assert req.url.params["attestation_type"] == wt.CERTIFICATE_TYPE and int(req.url.params["limit"]) <= 1000
    for k, v in ti.prepare_teg_headers("teg-token-for-did:a:me").items():
        assert req.headers.get(k) == v, k


def test_agent_attestations_a_teg_that_does_not_answer_is_the_librarys_503_and_an_unknown_agent_has_none(monkeypatch):
    from agentvault_registry.services import workflow_templates as wt
    _teg(monkeypatch, lambda req: httpx.Response(500, json={"detail": "down"}))
    with pytest.raises(wt.LibraryRefusal) as e:
        asyncio.run(wt.DbStore(_Db(types.SimpleNamespace(id=7, did="did:a:me"))).agent_attestations("did:a:me"))
    assert (e.value.status, e.value.code) == (503, "ledger_unavailable")
    assert asyncio.run(wt.DbStore(_Db(None)).agent_attestations("did:a:nobody")) == []


def _function_imports():
    """(file, function, bound name, module, imported name or None) for every import inside a function of the M4 files."""
    out = []
    for rel in M4_FILES:
        tree = ast.parse((SRC / rel).read_text())
        package = "agentvault_registry." + ".".join(pathlib.PurePosixPath(rel).with_suffix("").parts[:-1])
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        out.append((rel, fn, a.asname or a.name.split(".")[0], a.name, None))
                elif isinstance(node, ast.ImportFrom):
                    mod = importlib.util.resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module
                    for a in node.names:
                        out.append((rel, fn, a.asname or a.name, mod, a.name))
    return out


def test_every_import_inside_an_m4_function_resolves_and_every_name_read_off_it_exists():
    found, bad = _function_imports(), []
    assert len(found) >= 20, "the sweep found too few imports to be looking at the M4 files"
    for rel, fn, bound, mod, name in found:
        try:
            m = importlib.import_module(mod)
            obj = m if name is None else (getattr(m, name) if hasattr(m, name) else importlib.import_module(f"{mod}.{name}"))
        except Exception as e:                                         # noqa: BLE001  every failure is the finding
            bad.append(f"{rel}:{fn.name}: {mod}{'.' + name if name else ''}: {type(e).__name__}: {e}")
            continue
        if isinstance(obj, types.ModuleType):
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == bound \
                        and not hasattr(obj, node.attr):
                    bad.append(f"{rel}:{fn.name}: {bound}.{node.attr} is not in {obj.__name__}")
    assert bad == []
