"""§AGORASIM-2 (2026-09-22): a registry that requires a beta invite code refuses a service account's registration
without one (the sandbox operators answered 403 "Beta access requires an invite code"). create_service_accounts takes
one code per account and puts it in the register body; with no codes the body is exactly what it always was."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "hetzner_demo"))

import standup_extras as X  # noqa: E402


def _record(monkeypatch):
    calls = []

    def fake_http(method, url, body=None, headers=None, **kw):
        calls.append((method, url, dict(body or {})))
        if url.endswith("/api/v1/auth/register"):
            return 201, {"message": "ok"}
        return 200, {}

    monkeypatch.setattr(X, "http", fake_http)
    monkeypatch.setattr(X, "developer_id_by_email", lambda base, hdr, email: 7)
    monkeypatch.setattr(X, "log", lambda *a, **k: None)
    return calls


def test_each_account_registers_with_its_own_code(monkeypatch):
    calls = _record(monkeypatch)
    out = X.create_service_accounts("http://reg", {}, "op", only=["svc-sim", "svc-market"],
                                    invite_codes={"svc-sim": "CODE-A", "svc-market": "CODE-B"})
    regs = [b for m, u, b in calls if u.endswith("/api/v1/auth/register")]
    assert [r.get("invite_code") for r in regs] == ["CODE-A", "CODE-B"]
    assert set(out) == {"svc-sim", "svc-market"}


def test_without_codes_the_register_body_is_unchanged(monkeypatch):
    """The control: every existing caller passes no codes and sends name, email and password only."""
    calls = _record(monkeypatch)
    X.create_service_accounts("http://reg", {}, "eu", only=["svc-sim"])
    regs = [b for m, u, b in calls if u.endswith("/api/v1/auth/register")]
    assert len(regs) == 1 and set(regs[0]) == {"name", "email", "password"}
