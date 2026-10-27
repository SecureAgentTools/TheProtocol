"""docker-compose.standalone.yml, read as text (the kit's tests are stdlib only).

CB-012: the stack has no TLS terminator in front of its event store, so the registry and the TEG write their events with
the internal key, which the store (EVENTSTORE_MTLS_REQUIRED on by default) refused for every change: the ledger stayed
empty while the TEG moved balances. The store's own rule (agentvault-event-store/src/es_auth.py) decides here.
CB-018: the solo auditor named the unit "AVT" whatever the frame's FRAME_CURRENCY said.
CB-019: the registry mounted no volume, so /app/data (its bundle signing key, the status history) died with every
recreate.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
COMPOSE = HERE / "docker-compose.standalone.yml"
ES_AUTH = ROOT / "agentvault-event-store" / "src" / "es_auth.py"


def _service(text, name):
    """One service's block: from `  <name>:` to the next service or top-level key."""
    m = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\s*$|^\S)", text)
    assert m, f"no service {name}"
    return m.group(1)


def _interpolate(text, env):
    """Compose's ${NAME:-default} and ${NAME}, enough for these values."""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}",
                  lambda m: env.get(m.group(1)) or (m.group(2) or ""), text)


@pytest.mark.skipif(not ES_AUTH.exists(), reason="the event store's source is not beside this kit")
def test_the_standalone_ledger_takes_the_registrys_writes():
    es = _service(COMPOSE.read_text(), "event-store")
    assert not re.search(r"^\s+EVENTSTORE_MTLS_REQUIRED:", es, re.M), "the rule below assumes the store's default"
    m = re.search(r'^\s+EVENTSTORE_INTERNAL_KEY_WRITES:\s*"?([A-Za-z]+)"?\s*$', es, re.M)
    setting = m.group(1) if m else None
    spec = importlib.util.spec_from_file_location("es_auth_kit", ES_AUTH)
    es_auth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es_auth)
    assert es_auth.internal_key_may_change("POST", True, setting) is True, (
        "the store refuses the registry's and the TEG's events: it has no terminator to present a certificate through")


def test_the_auditor_names_the_frames_own_unit():
    auditor = _service(COMPOSE.read_text(), "auditor")
    m = re.search(r"AUDITOR_EXTRA_FRAMES_JSON: >-\n((?:\s{8,}.*\n)+)", auditor)
    raw = " ".join(line.strip() for line in m.group(1).splitlines())
    frames = json.loads(_interpolate(raw, {"FRAME_CURRENCY": "ECU", "REGISTRY_NAME": "solo"}))
    assert [f["currency"] for f in frames] == ["ECU"]


def test_the_registrys_app_data_outlives_a_recreate():
    text = COMPOSE.read_text()
    reg = _service(text, "registry")
    m = re.search(r"^\s+-\s+([a-z][a-z0-9-]*):/app/data\s*$", reg, re.M)
    assert m, "the registry mounts no named volume at /app/data"
    assert m.group(1) != "registry-data", "registry-data is the database's volume"
    top = text[text.index("\nvolumes:\n"):]
    assert re.search(rf"(?m)^  {re.escape(m.group(1))}:", top), f"{m.group(1)} is not declared"
