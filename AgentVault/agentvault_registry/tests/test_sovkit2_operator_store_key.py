"""§SOVKIT-2 R2 (2026-09-14): a cloud operator is provisioned WITHOUT its parent frame's store key.

An operator writes to its parent's event store by SVID through the parent's mTLS edge, where nginx clears X-Internal-Key.
The env writer used to hand every new operator EVENT_STORE_INTERNAL_API_KEY, from EVENT_STORE_INTERNAL_API_KEY_TEMPLATE
or a literal fallback (a retired sandbox store's value): a second origin path nothing used. These tests pin its absence,
including when the provisioning parent itself carries every store key name (nothing may inherit one).
"""
import os
import pathlib

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

STORE_KEY_NAMES = {"EVENT_STORE_INTERNAL_API_KEY", "EVENT_STORE_API_KEY", "EVENT_STORE_INTERNAL_KEY"}
_HERE = pathlib.Path(__file__).resolve()
_CANDIDATES = [
    pathlib.Path(os.environ["STORE_KEY_SRC"]) if os.environ.get("STORE_KEY_SRC") else None,
    _HERE.parents[1] / "src" / "agentvault_registry",
    pathlib.Path("/w/src/agentvault_registry"),
    pathlib.Path("/app/src/agentvault_registry"),
]
SRC = next(p for p in _CANDIDATES if p is not None and p.is_dir())


def test_the_operator_env_carries_no_store_key_even_when_the_parent_does(tmp_path, monkeypatch):
    for name in STORE_KEY_NAMES | {"EVENT_STORE_INTERNAL_API_KEY_TEMPLATE"}:
        monkeypatch.setenv(name, "a" * 64)
    from agentvault_registry.services.cloud_provisioner import _generate_env_file
    env_file = tmp_path / ".env.operator"
    _generate_env_file(str(env_file), "probe")
    names = {line.split("=", 1)[0] for line in env_file.read_text().splitlines() if "=" in line and not line.startswith("#")}
    assert "REGISTRY_NAME" in names, "the writer did not run (the test is not looking at the env file)"
    assert not names & STORE_KEY_NAMES, f"the operator env carries {sorted(names & STORE_KEY_NAMES)}"


def test_the_provisioner_holds_no_literal_store_key():
    assert "sandbox-event-store-api-key-2026" not in (SRC / "services" / "cloud_provisioner.py").read_text()
