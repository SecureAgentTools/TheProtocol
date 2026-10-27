"""§OPDIST (2026-09-16) — the operator's db-TLS override, as the live templates directory carries it.

Measured on beacon/jelgava: the frame's kit auditor connects PGSSLMODE=verify-full with a client certificate and the
operator's Postgres served no TLS (`rejected SSL upgrade`), so the venue lane could never connect. V0391's one-shot
(agentvault2-b5, host_work._db_tls_steps) copies three files from THIS directory into the operator stack, registers the
operator's data identity, and passes the override with -f. These tests pin what that directory has to hold:

  1. pg-tls-sync.sh is the frame's script byte for byte (a second copy exists only because the one-shot sees nothing
     outside its bind mount, and a copy that drifts is a second answer to one question);
  2. auditor_ro reaches the database only over TLS with a client certificate, refused in plaintext BEFORE any line that
     could admit it; every other role keeps the image's rules (the scoped decision: in-stack hops are a named residue);
  3. the hba method is scram-sha-256 because the image initialises SCRAM (Postgres 18 without the md5 init lines:
     password_encryption = scram-sha-256, the image default; until 2026-09-29 md5 with the md5 init, measured);
  4. the override adds only the data writer, changes db, and orders the TEG behind the database it delays (a bundle
     freezes the base at activation, this file is read live), with the label the data entry selects on;
  5. the BASE compose knows nothing of it: eu, asia, sbx-alpha and sbx-beta mount this directory on images that register
     no data entry, and a data writer in the base would leave their operators' databases waiting forever.
Parsed rather than run: bringing a stack up is the one-shot's job, and the render was proven by `docker compose config`.
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TPL = ROOT / "scripts" / "distribution" / "nginx-templates"
OVERRIDE = TPL / "docker-compose.operator.dbtls.yml"
BASE = TPL / "docker-compose.operator.yml"
HBA = TPL / "pg_hba_operator.conf"
SELECTOR_LABEL = "svid-writer-data-operator"   # operator_provisioner.register_operator_data_entry's selector (V0391)


def _hba_lines():
    out = []
    for raw in HBA.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line.split())
    return out


def test_the_operator_pg_tls_sync_is_the_frames_byte_for_byte():
    frame = ROOT / "templates" / "frame-test" / "kit" / "data-tls" / "pg-tls-sync.sh"
    assert (TPL / "pg-tls-sync.sh").read_bytes() == frame.read_bytes(), \
        "the operator's pg-tls-sync.sh drifted from the frame's; change both, or neither"


def _first_match(lines, user, ssl, family):
    """The line Postgres would use for a TCP connection from a NON-loopback address of `family` ("v4"/"v6"): first
    match on type (host = either, hostssl = TLS, hostnossl = plaintext), user, and address. A per-family evaluation,
    because a reject that covers only ::/0 leaves every IPv4 client to the next line (a mutation measured that)."""
    for f in lines:
        if f[0] not in ("host", "hostssl", "hostnossl"):
            continue
        if (f[0] == "hostssl" and not ssl) or (f[0] == "hostnossl" and ssl):
            continue
        if f[2] not in ("all", user):
            continue
        addr = f[3]
        if addr == "all" or (family == "v4" and addr == "0.0.0.0/0") or (family == "v6" and addr == "::/0"):
            return f
    return None


def test_auditor_ro_reaches_the_database_only_over_tls_with_a_client_certificate():
    lines = _hba_lines()
    for family in ("v4", "v6"):
        plain = _first_match(lines, "auditor_ro", ssl=False, family=family)
        assert plain and plain[0] == "hostnossl" and plain[2] == "auditor_ro" and plain[4] == "reject", \
            f"a plaintext auditor_ro connection over IP{family} must be rejected, and is decided by {plain}"
        tls = _first_match(lines, "auditor_ro", ssl=True, family=family)
        assert tls and tls[0] == "hostssl" and tls[2] == "auditor_ro" and "clientcert=verify-ca" in tls, \
            f"a TLS auditor_ro connection over IP{family} must need a client certificate, and is decided by {tls}"
        other = _first_match(lines, "registry", ssl=False, family=family)
        assert other and other[4] == "scram-sha-256", f"every other role keeps the image's rules (SCRAM) over IP{family}, got {other}"
    assert not any(f[0] != "local" and "trust" in f for f in lines), "trust belongs to the unix socket only"


def test_the_hba_method_matches_the_images_password_hashing():
    db_env = yaml.safe_load(BASE.read_text())["services"]["db"]["environment"]
    assert "POSTGRES_HOST_AUTH_METHOD" not in db_env and "md5" not in str(db_env.get("POSTGRES_INITDB_ARGS", "")), \
        "the base changed its auth method: re-measure password_encryption before changing the hba below"
    methods = {f[4] if f[0] in ("host", "hostssl", "hostnossl") else f[3] for f in _hba_lines()}
    assert "md5" not in methods, "a SCRAM-initialised database (Postgres 18, the image default) is matched by scram-sha-256; 18 deprecates md5"


def test_the_override_orders_the_teg_behind_the_database_it_delays():
    # a bundle freezes the BASE at activation, so the ordering the delay needs lives where the delay is (this file is
    # read live): jelgava's V0391 re-provisions failed twice on "could not translate host name pgbouncer"
    teg = yaml.safe_load(OVERRIDE.read_text())["services"]["teg-layer"]
    for host in ("pgbouncer", "redis"):
        assert teg["depends_on"][host] == {"condition": "service_healthy"}, f"teg-layer must wait for {host}"
    assert set(teg) == {"depends_on"}, "the override only orders the TEG; it changes nothing else about it"


def test_the_override_adds_only_the_data_writer_and_touches_only_db_and_the_teg_order():
    o = yaml.safe_load(OVERRIDE.read_text())
    assert set(o["services"]) == {"data-cert-writer", "db", "teg-layer"}
    labels = o["services"]["data-cert-writer"]["labels"]
    assert f"com.agentvault.service={SELECTOR_LABEL}" in labels, "the writer must carry the label the data entry selects"
    db = o["services"]["db"]
    assert db["depends_on"] == {"data-cert-writer": {"condition": "service_healthy"}}, \
        "the database must never start before its certificate exists"
    for v in db["volumes"]:
        src = v.split(":", 1)[0]
        if src.startswith("./"):
            assert (TPL / src[2:]).is_file(), f"the override binds {src}, which this directory does not carry"


def test_the_base_compose_knows_nothing_of_the_override():
    base = BASE.read_text()
    assert "data-cert-writer" not in base and "pg-tls-sync" not in base and SELECTOR_LABEL not in base, \
        "the base carries db-TLS pieces: frames on images that register no data entry would hang their operators"
