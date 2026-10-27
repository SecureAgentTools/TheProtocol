"""Tests for KeyManager credential resolution."""

import os
import json
import tempfile
from pathlib import Path

from theprotocol.client import KeyManager


def test_key_from_env(monkeypatch):
    monkeypatch.setenv("THEPROTOCOL_KEY_MYSERVICE", "secret123")
    km = KeyManager(use_keyring=False)
    assert km.get_key("myservice") == "secret123"


def test_key_not_found():
    km = KeyManager(use_keyring=False)
    assert km.get_key("nonexistent") is None


def test_key_from_json_file():
    data = {"myagent": "key-abc-123"}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        f.flush()
        km = KeyManager(key_file_path=f.name, use_keyring=False)
    assert km.get_key("myagent") == "key-abc-123"
    os.unlink(f.name)


def test_key_from_json_nested():
    data = {"svc": {"apiKey": "nested-key", "oauth": {"clientId": "cid", "clientSecret": "csec"}}}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        f.flush()
        km = KeyManager(key_file_path=f.name, use_keyring=False)
    assert km.get_key("svc") == "nested-key"
    assert km.get_oauth_client_id("svc") == "cid"
    assert km.get_oauth_client_secret("svc") == "csec"
    os.unlink(f.name)


def test_oauth_from_env(monkeypatch):
    monkeypatch.setenv("THEPROTOCOL_OAUTH_MYAPP_CLIENT_ID", "id-123")
    monkeypatch.setenv("THEPROTOCOL_OAUTH_MYAPP_CLIENT_SECRET", "sec-456")
    km = KeyManager(use_keyring=False)
    assert km.get_oauth_client_id("myapp") == "id-123"
    assert km.get_oauth_client_secret("myapp") == "sec-456"


def test_file_priority_over_env(monkeypatch):
    monkeypatch.setenv("THEPROTOCOL_KEY_SVC", "from-env")
    data = {"svc": "from-file"}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f)
        f.flush()
        km = KeyManager(key_file_path=f.name, use_keyring=False)
    assert km.get_key("svc") == "from-file"
    os.unlink(f.name)


# ── name=value key files (0.7.6) ───────────────────────────────────────────────────────────────────────────────────

def test_oauth_pair_from_an_env_file(tmp_path):
    """Both lines of the pair come back; up to 0.7.5 the first line marked the pair 'file' and the second was dropped."""
    f = tmp_path / "creds.env"
    f.write_text("THEPROTOCOL_OAUTH_MYAPP_CLIENT_ID=id-file\nTHEPROTOCOL_OAUTH_MYAPP_CLIENT_SECRET=sec-file\n")
    km = KeyManager(key_file_path=f, use_env_vars=False, use_keyring=False)
    assert km.get_oauth_client_id("myapp") == "id-file"
    assert km.get_oauth_client_secret("myapp") == "sec-file"


def test_oauth_pair_in_an_env_file_beats_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("THEPROTOCOL_OAUTH_MYAPP_CLIENT_ID", "id-env")
    monkeypatch.setenv("THEPROTOCOL_OAUTH_MYAPP_CLIENT_SECRET", "sec-env")
    f = tmp_path / "creds.env"
    f.write_text("THEPROTOCOL_OAUTH_MYAPP_CLIENT_SECRET=sec-file\nTHEPROTOCOL_OAUTH_MYAPP_CLIENT_ID=id-file\n")
    km = KeyManager(key_file_path=f, use_keyring=False)
    assert (km.get_oauth_client_id("myapp"), km.get_oauth_client_secret("myapp")) == ("id-file", "sec-file")


def test_a_file_named_exactly_dot_env_is_read(tmp_path):
    f = tmp_path / ".env"
    f.write_text("THEPROTOCOL_KEY_MYSERVICE=key-from-dotenv\n")
    km = KeyManager(key_file_path=f, use_env_vars=False, use_keyring=False)
    assert km.get_key("myservice") == "key-from-dotenv"


def test_an_api_key_in_an_env_file_is_found_by_its_service_id(tmp_path, monkeypatch):
    """THEPROTOCOL_KEY_<SERVICE_ID> in a key file is the key of <service id>, as in the environment, and the file wins."""
    monkeypatch.setenv("THEPROTOCOL_KEY_MYSERVICE", "from-env")
    f = tmp_path / "creds.env"
    f.write_text("THEPROTOCOL_KEY_MYSERVICE=from-file\nOTHER_SERVICE=plain-name\n")
    km = KeyManager(key_file_path=f, use_keyring=False)
    assert km.get_key("myservice") == "from-file"
    assert km.get_key("other_service") == "plain-name"


def test_a_key_file_of_another_type_is_reported_not_silently_ignored(tmp_path, caplog):
    f = tmp_path / "creds.txt"
    f.write_text("THEPROTOCOL_KEY_MYSERVICE=never-read\n")
    with caplog.at_level("WARNING", logger="theprotocol.client.credentials"):
        km = KeyManager(key_file_path=f, use_env_vars=False, use_keyring=False)
    assert km.get_key("myservice") is None
    assert any("was not read" in r.getMessage() for r in caplog.records)
