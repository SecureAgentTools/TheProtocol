"""V0658 (b): Agent Forge's featured default template is the starter, an external agent on the SDK.

The featured template ("full-capacity") left with Frame A (D6-822); the starter takes its place, built on the minimal
template the image ships (id "minimal"). A download of it is an agent a developer runs as it comes: its card, its A2A
endpoint, the agent's credentials, a health route, one example skill, the payment check of a paid call (the SDK's, live
once REGISTRY_URL and AGENT_DID are set), the reputation bond step, a Dockerfile and a compose file, and instructions
taken from the docs. Only our own code, under the SDK's licence (Apache-2.0), no key, no model provider.

The download through the real route (POST /onboard/download-bundle) and the real template directory; doubles: the
database session (the agent row and its card) and the registry's public address. The starter's own behaviour (the card
it serves, the skill, the payment check) is pinned by its own tests (minimal-template/tests), run in its own image with
the SDK; here the card it serves is put to this registry's own card validator.
RED on v0657/cut (e70fb58b2): the catalogue lists full-capacity first and the request defaults to it, and the minimal
download carries no compose file, no card, no registry address and no bond step.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import io
import json
import pathlib
import re
import zipfile
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import agent_bundle as B
from agentvault_registry.security import hash_password

TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "minimal-template"
DID = "did:theprotocol:sandbox-a.theprotocol.cloud:5d0c6a2e-1f3b-4c8d-9e7a-2b4f6c8d0e1a"
CLIENT_ID = "agent-5d0c6a2e1f3b4c8d"
SECRET = "tp_secret_" + "c3d4" * 16
CARD = {
    "protocolVersion": "1.0", "name": "Word Counter", "description": "Counts words for anyone who pays.",
    "humanReadableId": "dev/word-counter", "agentVersion": "1.0.0",
    "provider": {"name": "Example Dev", "url": "https://example.org"},
    "supportedInterfaces": [{"url": "https://wordcounter.example.org/a2a", "protocolBinding": "JSONRPC",
                             "protocolVersion": "1.0"}],
    "url": "https://wordcounter.example.org/a2a",
    "capabilities": {"streaming": False, "stateTransitionHistory": False, "pushNotifications": False},
    "securitySchemes": {}, "security": [], "tags": ["sdk"],
    "federation_metadata": {"source_registry": "spiffe://sandbox-a.theprotocol.cloud/service/registry"},
}


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _Db:
    """The route's two reads, in order: the agent, then its card."""

    def __init__(self, agent, card):
        self._answers = [agent, card]

    async def execute(self, _stmt):
        return _Result(self._answers.pop(0) if self._answers else None)


async def _body(resp) -> bytes:
    return b"".join([c if isinstance(c, bytes) else c.encode() async for c in resp.body_iterator])


def _download(monkeypatch, card=CARD, template_type=None, ui="https://sbx-alpha.theprotocol.cloud"):
    monkeypatch.setattr(B, "MINIMAL_TEMPLATE_DIR", TEMPLATE)
    monkeypatch.setenv("FRAME_CURRENCY", "SBXA")
    if ui:
        monkeypatch.setenv("PUBLIC_UI_URL", ui)
    else:
        monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
        monkeypatch.setattr(B, "credential_home_url", lambda: None)
    agent = SimpleNamespace(did=DID, creator_developer_id=7, client_id=CLIENT_ID,
                            hashed_client_secret=hash_password(SECRET))
    row = SimpleNamespace(name=card.get("name", "My Agent"), card_data=card)
    kw = {} if template_type is None else {"template_type": template_type}
    req = B.BundleRequest(agent_did=DID, client_id=CLIENT_ID, client_secret=SECRET, **kw)
    resp = asyncio.run(B.download_bundle(req, current_developer=SimpleNamespace(id=7), db=_Db(agent, row)))
    z = zipfile.ZipFile(io.BytesIO(asyncio.run(_body(resp))))
    return {n: z.read(n).decode() for n in z.namelist()}


def _env(text):
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("#"))


# ── the catalogue ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_starter_is_the_catalogues_first_and_the_requests_default(monkeypatch, tmp_path):
    (tmp_path / "ppao").mkdir()
    monkeypatch.setattr(B, "MINIMAL_TEMPLATE_DIR", TEMPLATE)
    monkeypatch.setattr(B, "PPAO_TEMPLATE_DIR", tmp_path / "ppao")
    assert [tid for tid, _ in B._template_dirs()] == ["minimal", "ppao"]   # full-capacity is gone (D6-822)
    assert asyncio.run(B.bundle_templates(current_developer=SimpleNamespace(id=7))) == {
        "templates": ["minimal", "ppao"], "default": "minimal"}
    assert B.BundleRequest(agent_did=DID, client_id=CLIENT_ID, client_secret=SECRET).template_type == "minimal"


# ── the download ─────────────────────────────────────────────────────────────────────────────────────────────────────

STARTER_FILES = {".env", ".env.secret", ".gitignore", ".dockerignore", "Dockerfile", "compose.yaml", "LICENSE",
                 "README.md", "agent-card.json", "card.py", "main.py", "onboard.py", "requirements.txt",
                 "requirements-dev.txt", "skills.py", "tests/test_starter.py"}


def test_a_download_without_a_pick_is_the_starter_with_every_file_it_runs_from(monkeypatch):
    files = _download(monkeypatch)
    assert set(files) == STARTER_FILES, sorted(set(files) ^ STARTER_FILES)


def test_its_env_names_the_agent_the_registry_its_unit_and_the_agents_public_address(monkeypatch):
    env = _env(_download(monkeypatch)[".env"])
    assert env["AGENT_NAME"] == "Word Counter" and env["AGENT_DID"] == DID
    assert env["REGISTRY_URL"] == "https://sbx-alpha.theprotocol.cloud"     # where the agent's credential is used
    assert env["PUBLIC_URL"] == "https://wordcounter.example.org"           # the host the registry reads the card from
    assert env["CURRENCY"] == "SBXA" and env["PRICE"] == "1" and env["PAYMENT_REQUIRED"] == "true"


def test_an_address_the_registry_does_not_know_stays_empty_never_a_placeholder(monkeypatch):
    card = {k: v for k, v in CARD.items() if k not in ("supportedInterfaces", "url")}
    files = _download(monkeypatch, card=card, ui=None)
    env = _env(files[".env"])
    assert env["REGISTRY_URL"] == "" and env["PUBLIC_URL"] == ""
    assert not [n for n, t in files.items() if "PLACEHOLDER" in t], [n for n, t in files.items() if "PLACEHOLDER" in t]


def test_the_credentials_are_in_env_secret_and_nowhere_else(monkeypatch):
    files = _download(monkeypatch)
    secret = _env(files[".env.secret"])
    assert secret == {"AGENT_DID": DID, "CLIENT_ID": CLIENT_ID, "CLIENT_SECRET": SECRET}
    assert [n for n, t in files.items() if SECRET in t] == [".env.secret"]
    assert ".env.secret" in files[".gitignore"].split() and ".env.secret" in files[".dockerignore"].split()


def test_the_compose_and_the_readme_name_the_agents_service(monkeypatch):
    files = _download(monkeypatch)
    compose = files["compose.yaml"]
    assert "word-counter-agent:" in compose and "container_name: word-counter-agent" in compose
    assert "my-agent" not in compose and "- .env\n" in compose and "- .env.secret\n" in compose
    readme = files["README.md"]
    assert "docker compose exec word-counter-agent python onboard.py all" in readme
    assert f"- **DID**: `{DID}`" in readme and "- **Name**: Word Counter" in readme


def test_the_agent_card_is_the_registrys_copy_of_the_agents_card(monkeypatch):
    assert json.loads(_download(monkeypatch)["agent-card.json"]) == CARD


def test_the_ppao_template_still_downloads_with_its_own_credentials(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("# PPAO\n")
    monkeypatch.setattr(B, "PPAO_TEMPLATE_DIR", tmp_path)
    files = _download(monkeypatch, template_type="ppao")
    assert _env(files[".env.secret"]) == {"PPAO_AGENT_DID": DID, "PPAO_CLIENT_ID": CLIENT_ID,
                                          "PPAO_CLIENT_SECRET": SECRET}
    assert "agent-card.json" not in files and not any(n.endswith(".gitkeep") for n in files)


# ── the starter itself ───────────────────────────────────────────────────────────────────────────────────────────────

def _card_module():
    spec = importlib.util.spec_from_file_location("starter_card", TEMPLATE / "card.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_card_the_starter_serves_passes_this_registrys_validator():
    from agentvault_registry import schemas
    from agentvault_registry.routers import utils
    assert utils._agentvault_lib_available, "the card library is not importable: the validator would only skip"
    m = _card_module()
    card = m.build_card(CARD, name="Word Counter", public_url="https://wordcounter.example.org",
                        price=m.price_of("1.5"), currency="SBXA", payment_required=True)
    out = asyncio.run(utils.validate_agent_card(schemas.AgentCardValidationRequest(card_data=card)))
    assert out.is_valid, out.detail
    assert card["supportedInterfaces"][0]["url"] == "https://wordcounter.example.org/a2a"
    assert [s["id"] for s in card["skills"]] == ["text-stats"] and "federation_metadata" not in card
    assert [e for e in card["extensions"] if e["uri"] == m.PAYMENT_EXTENSION_URI] == [
        {"uri": m.PAYMENT_EXTENSION_URI, "required": True,
         "params": {"base_rate": "1.5", "currency": "SBXA", "pricing_model": "per_request"}}]


@pytest.mark.parametrize("raw,want", [("1", "1"), (" 2.50 ", "2.50"), ("0", "0"), ("", "0"), ("-1", "0"),
                                      ("abc", "0"), ("NaN", "0"), ("Infinity", "0")])
def test_a_price_is_a_positive_number_or_the_agent_is_free(raw, want):
    assert str(_card_module().price_of(raw)) == want


_SDK_IMPORTS = {"theprotocol", "fastapi", "httpx"}


def test_the_starter_is_our_own_code_under_the_sdks_licence_with_no_key_and_no_model_provider():
    py = sorted(TEMPLATE.rglob("*.py"))
    assert {p.name for p in py} >= {"main.py", "card.py", "skills.py", "onboard.py", "test_starter.py"}
    import sys
    stdlib = set(sys.stdlib_module_names)
    local = {p.stem for p in py}
    for p in py:
        compile(p.read_text(), str(p), "exec")   # it compiles (nothing written beside it)
        tree = ast.parse(p.read_text())
        roots = {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        foreign = roots - stdlib - local - _SDK_IMPORTS - {"pytest", ""}
        assert not foreign, (p.name, foreign)
    reqs = [re.split(r"[\[<>=]", line.strip())[0] for f in ("requirements.txt", "requirements-dev.txt")
            for line in (TEMPLATE / f).read_text().splitlines() if line.strip() and not line.startswith(("#", "-r"))]
    assert reqs == ["theprotocol-sdk", "uvicorn", "pytest"], reqs
    for f in [*py, TEMPLATE / "Dockerfile", TEMPLATE / "compose.yaml"]:
        assert "SPDX-License-Identifier: Apache-2.0" in f.read_text().splitlines()[0], f.name
    assert (TEMPLATE / "LICENSE").read_text().startswith("Apache License\nVersion 2.0, January 2004")
    text = "\n".join(p.read_text(errors="replace") for p in TEMPLATE.rglob("*") if p.is_file() and p.name != "LICENSE")
    for shape in (r"tp_secret_[0-9a-f]{8,}", r"avreg_[A-Za-z0-9]{8,}", r"sk-[A-Za-z0-9]{16,}", r"PRIVATE KEY-----",
                  r"(?i)\b(openai|anthropic|langchain|ollama)\b"):
        assert not re.search(shape, text), shape


def test_the_readme_takes_its_steps_from_the_docs():
    readme = (TEMPLATE / "README.md").read_text()
    for step in ("/api/v1/auth/agent/token", "/api/v1/utils/validate-card", "/api/v1/reputation-bond/config",
                 "/api/v1/agents/reputation-bond/deposit", "/api/v1/a2a-payment/authorize",
                 "/api/v1/a2a-payment/verify", "/api/v1/a2a-payment/settle", "X-Payment-Token", "IronhandClient",
                 "PAYMENT_REQUIRED=false", "https://docs.theprotocol.cloud/build/running-your-agent"):
        assert step in readme, step
