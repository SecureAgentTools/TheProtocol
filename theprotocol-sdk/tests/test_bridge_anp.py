"""Tests for ANP ↔ A2A bridge — DID:WBA, auth, translation, and full roundtrip."""

import datetime
import json
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from theprotocol.models import (
    Message, Task, TaskState, TextPart, DataPart,
    AgentCard, AgentProvider, AgentCapabilities, AgentAuthentication, AgentSkill,
)
from theprotocol.agent import BaseA2AAgent
from theprotocol.bridges.anp import (
    ANPBridge, DIDDocument, create_did_wba, resolve_did_wba,
    create_didwba_auth_header, verify_didwba_auth_header,
)
from theprotocol.bridges.anp.did_wba import (
    KeyPair, did_wba_from_cos, did_cos_from_wba, did_wba_to_url,
)
from theprotocol.bridges.anp.auth import parse_didwba_auth_header, _jcs_canonicalize
from theprotocol.bridges.anp.translation import (
    agent_card_to_anp_description, agent_card_to_openrpc_interface,
    anp_description_to_agent_card, anp_rpc_to_a2a_message, a2a_task_to_anp_response,
)


# ── Test Agent ──

class EchoAgent(BaseA2AAgent):
    def __init__(self):
        super().__init__(agent_metadata={"description": "ANP test agent"})
        self.tasks = {}

    async def handle_task_send(self, task_id, message):
        tid = task_id or "anp-task-1"
        text = ""
        for p in message.parts:
            if hasattr(p, 'content') and isinstance(p.content, str):
                text = p.content
        self.tasks[tid] = {"message": message, "response": f"ANP echo: {text}"}
        return tid

    async def handle_task_get(self, task_id):
        t = self.tasks.get(task_id)
        if not t:
            raise ValueError(f"Task {task_id} not found")
        now = datetime.datetime.now(datetime.timezone.utc)
        return Task(
            id=task_id, state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
            messages=[
                t["message"],
                Message(role="assistant", parts=[TextPart(content=t["response"])]),
            ],
        )

    async def handle_task_cancel(self, task_id):
        return task_id in self.tasks

    async def handle_subscribe_request(self, task_id):
        return; yield


# ═══════════════════════════════════════════════════════════
# DID:WBA Tests
# ═══════════════════════════════════════════════════════════

def test_keypair_generate():
    kp = KeyPair.generate()
    assert len(kp.private_key_bytes) == 32
    assert len(kp.public_key_bytes) == 32
    assert kp.kid  # Non-empty


def test_keypair_sign_verify():
    kp = KeyPair.generate()
    data = b"test message"
    sig = kp.sign(data)
    assert kp.verify(sig, data) is True
    assert kp.verify(sig, b"wrong message") is False


def test_keypair_serialize_roundtrip():
    kp = KeyPair.generate()
    d = kp.to_dict()
    kp2 = KeyPair.from_dict(d)
    assert kp.private_key_bytes == kp2.private_key_bytes
    assert kp.public_key_bytes == kp2.public_key_bytes
    assert kp.kid == kp2.kid


def test_keypair_jwk():
    kp = KeyPair.generate()
    jwk = kp.public_jwk
    assert jwk["kty"] == "OKP"
    assert jwk["crv"] == "Ed25519"
    assert "x" in jwk
    assert jwk["kid"] == kp.kid


def test_keypair_multibase():
    kp = KeyPair.generate()
    mb = kp.public_key_multibase
    assert mb.startswith("z")  # base58btc prefix


def test_did_wba_from_cos():
    assert did_wba_from_cos("did:cos:abc-123") == "did:wba:api.theprotocol.cloud:agents:abc-123"
    assert did_wba_from_cos("did:cos:abc-123", "registry.example.com") == "did:wba:registry.example.com:agents:abc-123"


def test_did_cos_from_wba():
    assert did_cos_from_wba("did:wba:api.theprotocol.cloud:agents:abc-123") == "did:cos:abc-123"
    assert did_cos_from_wba("did:wba:other.domain:agents:abc-123") is None  # Wrong domain


def test_did_wba_to_url():
    assert did_wba_to_url("did:wba:example.com") == "https://example.com/.well-known/did.json"
    assert did_wba_to_url("did:wba:example.com:user:alice") == "https://example.com/user/alice/did.json"
    assert did_wba_to_url("did:wba:example.com%3A8800:user:alice") == "https://example.com:8800/user/alice/did.json"


def test_did_wba_to_url_invalid():
    with pytest.raises(ValueError):
        did_wba_to_url("did:key:z6Mk...")


def test_create_did_document():
    kp = KeyPair.generate()
    doc = create_did_wba("did:cos:test-agent", kp)
    d = doc.to_dict()
    assert d["id"] == "did:wba:api.theprotocol.cloud:agents:test-agent"
    assert len(d["verificationMethod"]) == 1
    assert d["verificationMethod"][0]["type"] == "Ed25519VerificationKey2018"
    assert d["verificationMethod"][0]["publicKeyJwk"]["crv"] == "Ed25519"
    assert len(d["authentication"]) == 1
    assert len(d["service"]) == 1
    assert d["service"][0]["type"] == "AgentDescription"


def test_did_document_json():
    kp = KeyPair.generate()
    doc = create_did_wba("did:cos:test", kp)
    j = doc.to_json()
    parsed = json.loads(j)
    assert parsed["@context"][0] == "https://www.w3.org/ns/did/v1"


# ═══════════════════════════════════════════════════════════
# DIDWba Auth Tests
# ═══════════════════════════════════════════════════════════

def test_jcs_canonicalize():
    obj = {"b": 2, "a": 1}
    canonical = _jcs_canonicalize(obj)
    assert canonical == b'{"a":1,"b":2}'


def test_create_auth_header():
    kp = KeyPair.generate()
    header = create_didwba_auth_header(
        did="did:wba:example.com:agent:test",
        keypair=kp,
        service_domain="example.com",
    )
    assert header.startswith("DIDWba ")
    assert 'did="did:wba:example.com:agent:test"' in header
    assert 'nonce="' in header
    assert 'timestamp="' in header
    assert 'signature="' in header


def test_parse_auth_header():
    kp = KeyPair.generate()
    header = create_didwba_auth_header("did:wba:x.com:a", kp, "x.com")
    parsed = parse_didwba_auth_header(header)
    assert parsed is not None
    assert parsed["did"] == "did:wba:x.com:a"
    assert "nonce" in parsed
    assert "timestamp" in parsed
    assert "verification_method" in parsed
    assert "signature" in parsed


def test_parse_auth_header_invalid():
    assert parse_didwba_auth_header("Bearer token123") is None
    assert parse_didwba_auth_header("DIDWba incomplete") is None


@pytest.mark.asyncio
async def test_verify_auth_header_roundtrip():
    """Full crypto roundtrip: create header → verify signature."""
    kp = KeyPair.generate()
    did = "did:wba:api.theprotocol.cloud:agents:test-verify"

    # Create DID document (simulates what the registry would serve)
    doc = create_did_wba("did:cos:test-verify", kp)

    # Create auth header
    header = create_didwba_auth_header(
        did=did,
        keypair=kp,
        service_domain="api.theprotocol.cloud",
    )

    # Verify — pass the doc directly (skip HTTP resolution)
    result = await verify_didwba_auth_header(
        header_value=header,
        expected_service="api.theprotocol.cloud",
        did_document=doc,
    )
    assert result == did


@pytest.mark.asyncio
async def test_verify_auth_header_wrong_key():
    """Verify fails with wrong keypair."""
    kp1 = KeyPair.generate()
    kp2 = KeyPair.generate()  # Different key
    did = "did:wba:api.theprotocol.cloud:agents:wrong-key"

    # Create header with kp1
    header = create_didwba_auth_header(did=did, keypair=kp1, service_domain="api.theprotocol.cloud")

    # Create DID doc with kp2 (wrong public key)
    doc = create_did_wba("did:cos:wrong-key", kp2)

    result = await verify_didwba_auth_header(
        header_value=header,
        expected_service="api.theprotocol.cloud",
        did_document=doc,
    )
    assert result is None  # Should fail


@pytest.mark.asyncio
async def test_verify_auth_header_expired():
    """Verify fails with expired timestamp."""
    kp = KeyPair.generate()
    did = "did:wba:api.theprotocol.cloud:agents:expired"
    doc = create_did_wba("did:cos:expired", kp)

    header = create_didwba_auth_header(did=did, keypair=kp, service_domain="api.theprotocol.cloud")

    # Verify with 0-second max age (always expired)
    result = await verify_didwba_auth_header(
        header_value=header,
        expected_service="api.theprotocol.cloud",
        did_document=doc,
        max_age_seconds=0,
    )
    assert result is None


# ═══════════════════════════════════════════════════════════
# Translation Tests
# ═══════════════════════════════════════════════════════════

def _make_card():
    return AgentCard(
        protocolVersion="0.3.0",
        humanReadableId="theprotocol/echo",
        agentVersion="1.0.0",
        name="Echo Agent",
        description="Echoes messages",
        url="https://api.theprotocol.cloud/agents/echo/a2a",
        provider=AgentProvider(name="TheProtocol"),
        capabilities=AgentCapabilities(streaming=True),
        authSchemes=[AgentAuthentication(scheme="none")],
        skills=[AgentSkill(id="echo", name="Echo", description="Echo text back")],
        tags=["test", "echo"],
    )


def test_agent_card_to_anp_description():
    card = _make_card()
    ad = agent_card_to_anp_description(card, "did:wba:api.theprotocol.cloud:agents:echo")
    assert ad["protocolType"] == "ANP"
    assert ad["name"] == "Echo Agent"
    assert ad["did"] == "did:wba:api.theprotocol.cloud:agents:echo"
    assert ad["owner"]["name"] == "TheProtocol"
    assert ad["security"] == "didwba_sc"
    assert len(ad["interfaces"]) >= 1


def test_agent_card_to_openrpc():
    card = _make_card()
    iface = agent_card_to_openrpc_interface(card)
    assert iface["openrpc"] == "1.3.2"
    method_names = [m["name"] for m in iface["methods"]]
    assert "tasks/send" in method_names
    assert "tasks/get" in method_names
    assert "skills/echo" in method_names  # Custom skill


def test_anp_description_to_agent_card():
    ad = {
        "name": "External Bot",
        "did": "did:wba:external.com:bot:alice",
        "url": "https://external.com/bot/alice",
        "description": "An external ANP agent",
        "owner": {"name": "External Corp", "url": "https://external.com"},
        "interfaces": [{"url": "https://external.com/bot/alice/rpc"}],
    }
    card = anp_description_to_agent_card(ad)
    assert card.name == "External Bot"
    assert card.provider.name == "External Corp"
    assert "anp" in card.tags


def test_anp_rpc_to_a2a_tasks_send():
    msg = anp_rpc_to_a2a_message("tasks/send", {
        "message": {"role": "user", "parts": [{"text": "hello from ANP"}]},
    })
    assert msg.role == "user"
    assert msg.parts[0].content == "hello from ANP"


def test_anp_rpc_to_a2a_custom_method():
    msg = anp_rpc_to_a2a_message("custom/analyze", {"data": [1, 2, 3]})
    assert msg.role == "user"
    assert msg.parts[0].type == "data"
    assert msg.parts[0].content["anp_method"] == "custom/analyze"


def test_a2a_task_to_anp_response():
    now = datetime.datetime.now(datetime.timezone.utc)
    task = Task(
        id="t1", state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
        messages=[Message(role="assistant", parts=[TextPart(content="done")])],
    )
    resp = a2a_task_to_anp_response(task)
    assert resp["task_id"] == "t1"
    assert resp["state"] == "task_state_completed"
    assert resp["messages"][0]["parts"][0]["text"] == "done"


# ═══════════════════════════════════════════════════════════
# Integration: Full ANP Endpoint Roundtrip
# ═══════════════════════════════════════════════════════════

def _make_app():
    agent = EchoAgent()
    kp = KeyPair.generate()
    bridge = ANPBridge(
        agent_did_cos="did:cos:test-anp-agent",
        keypair=kp,
        domain="test.theprotocol.cloud",
    )
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/anp")
    return app, bridge


def test_anp_did_document_endpoint():
    app, bridge = _make_app()
    client = TestClient(app)
    resp = client.get("/anp/did.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "did:wba:test.theprotocol.cloud:agents:test-anp-agent"
    assert data["@context"][0] == "https://www.w3.org/ns/did/v1"
    assert len(data["verificationMethod"]) == 1
    assert data["verificationMethod"][0]["publicKeyJwk"]["crv"] == "Ed25519"


def test_anp_agent_description_endpoint():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/anp/agent/ad.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["protocolType"] == "ANP"
    assert data["did"].startswith("did:wba:")
    assert "securityDefinitions" in data


def test_anp_interface_endpoint():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.get("/anp/agent/interface.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["openrpc"] == "1.3.2"
    method_names = [m["name"] for m in data["methods"]]
    assert "tasks/send" in method_names


def test_anp_rpc_tasks_send():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.post("/anp/agent/rpc", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tasks/send",
        "params": {
            "message": {"role": "user", "parts": [{"text": "hello ANP"}]},
        },
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    assert data["result"]["state"] == "task_state_completed"
    assert any("ANP echo" in m["parts"][0].get("text", "") for m in data["result"]["messages"] if m.get("parts"))


def test_anp_rpc_tasks_get():
    app, _ = _make_app()
    client = TestClient(app)
    # Create task first
    client.post("/anp/agent/rpc", json={
        "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
        "params": {"message": {"role": "user", "parts": [{"text": "get test"}]}},
    })
    # Get task
    resp = client.post("/anp/agent/rpc", json={
        "jsonrpc": "2.0", "id": 2, "method": "tasks/get",
        "params": {"id": "anp-task-1"},
    })
    assert resp.status_code == 200
    assert resp.json()["result"]["state"] == "task_state_completed"


def test_anp_rpc_tasks_cancel():
    app, _ = _make_app()
    client = TestClient(app)
    client.post("/anp/agent/rpc", json={
        "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
        "params": {"message": {"role": "user", "parts": [{"text": "cancel me"}]}},
    })
    resp = client.post("/anp/agent/rpc", json={
        "jsonrpc": "2.0", "id": 2, "method": "tasks/cancel",
        "params": {"id": "anp-task-1"},
    })
    assert resp.status_code == 200
    assert resp.json()["result"]["success"] is True


def test_anp_rpc_custom_method():
    app, _ = _make_app()
    client = TestClient(app)
    resp = client.post("/anp/agent/rpc", json={
        "jsonrpc": "2.0", "id": 1, "method": "custom/analyze",
        "params": {"data": [1, 2, 3]},
    })
    assert resp.status_code == 200
    assert "result" in resp.json()
