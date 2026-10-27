"""
Operator Provisioning Engine — Phase 2

Generates a complete operator bundle after admin approval:
  1. x509pop attestation certificate (signed by SPIRE CA)
  2. SPIRE trust bundle export
  3. SPIRE workload entry registration (registry, svid-writer, teg)
  4. SPIRE agent.conf template
  5. nginx mTLS federation config + entrypoint
  6. Docker image registry credentials
  7. Packaged tar.gz bundle for operator download

All Docker SDK calls go through the mounted /var/run/docker.sock.
"""
import hashlib
import logging
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)

BUNDLES_DIR = os.getenv("OPERATOR_BUNDLES_DIR", "/app/operator-bundles")
CA_DIR = os.getenv("OPERATOR_CA_DIR", "/opt/spire-ca")
NGINX_TEMPLATES_DIR = os.getenv("NGINX_TEMPLATES_DIR", "/app/nginx-templates")
SPIRE_BINARY = "/opt/spire/bin/spire-server"


# P7 (2026-04-22): SPIRE* env vars are read lazily at CALL time rather than at
# module import. Previously these were module-level constants, which meant a
# registry container that didn't set them (e.g. prod registry-a without sandbox
# overrides) fell back to agentvault.com defaults at import. Any later code
# path that passed a different SPIRE_CONTAINER (via application-specific env)
# could still end up minting SPIFFE IDs against the wrong trust domain.
# Reading via these helpers at call time lets a caller override via
# `os.environ[...]` before calling provision_operator() without process
# restart, and makes the coupling between env var and usage explicit at the
# call site.

def _env_true(name: str) -> bool:
    """RP2 helper: treat only explicit truthy strings as on."""
    return (os.getenv(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


def _spire_container() -> str:
    return os.getenv("SPIRE_CONTAINER", "agentvault-spire-server")

def _trust_domain() -> str:
    return os.getenv("SPIRE_TRUST_DOMAIN", "agentvault.com")

def _federate_with() -> str:
    return os.getenv("SPIRE_FEDERATE_WITH", "")


def _load_parse_federation_list():
    """`frame_trust_manager.parse_federation_list`, however THIS module was loaded.

    Imported normally it is a sibling in the package. Loaded by path (host_work's one-shot, which must not touch
    `services/__init__` because that pulls the ORM and a settings object the container has no database for) there is
    no parent package, so the relative import cannot resolve and the sibling has to be loaded the same way. An
    absolute import is not the fix here: it would drag in the very package init the by-path load exists to avoid.
    ONE parser either way — the alternative is a second copy that rots on its own.
    """
    try:
        from .frame_trust_manager import parse_federation_list
        return parse_federation_list
    except ImportError:
        pass
    import importlib.util
    import sys
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame_trust_manager.py")
    spec = importlib.util.spec_from_file_location("_opdist_frame_trust_manager", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.parse_federation_list


def _entry_already_exists(*streams: str) -> bool:
    """SPIRE's way of saying the entry it was asked to create is already there.

    Both spellings the server has used are matched, because which one appears depends on whether the CLI reports the
    batch status or the gRPC error: `AlreadyExists` (the code) and `already exists` (the description).
    """
    blob = " ".join(x or "" for x in streams).lower()
    return "alreadyexists" in blob.replace(" ", "") or "already exists" in blob


def federation_from_spire_server(container) -> str:
    """§BATCH7 (2026-09-05) — the trust domains this SPIRE server ALREADY federates with, read live
    from `spire-server federation list` (ONE parser: frame_trust_manager.parse_federation_list),
    comma-joined in the SPIRE_FEDERATE_WITH shape.

    Measured on the fresh pair: JUICE↔BRRR approved at 21:02Z, juiceop-b provisioned at 21:05Z.
    The approve rail's entry pass (§FRAMEFED) cannot see entries that do not exist yet, no worker
    re-runs it, and SPIRE_FEDERATE_WITH is unset on a provisioned frame — so the operator's three
    entries carried no -federatesWith, its bundle held ONE root, and every cross-frame mTLS call
    from it died CERTIFICATE_VERIFY_FAILED. The env keeps precedence (an operator's federation is
    its parent's word); this is the fallback that makes a birth inherit what the parent holds.
    Never raises: an unreadable list is "" (the pre-§BATCH7 behaviour)."""
    try:
        res = container.exec_run(["/opt/spire/bin/spire-server", "federation", "list"], demux=True)
        rc = getattr(res, "exit_code", None)
        out = getattr(res, "output", None)
        if isinstance(out, tuple):
            out = out[0] or b""
        text = out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out or "")
        if rc not in (0, None):
            return ""
    except Exception as e:  # noqa: BLE001 — a fallback, reported, never fatal
        logger.warning(f"[provision] could not read the SPIRE federation list: {e}")
        return ""
    # ⚠ TWO STATES THAT PRINTED ONE SENTENCE. "the list is unreadable" is this rail working as designed on a frame
    # that federates with nobody; "we could not load our own parser" is a defect in THIS file, and until 2026-09-16
    # both logged the same warning and returned the same "". Under host_work's _load_provisioner this module is
    # loaded BY PATH under a name with no package, so `from .frame_trust_manager import ...` raised "attempted
    # relative import with no known parent package" on every runner-built provision — every operator of a federated
    # frame born with no -federatesWith, which is §BATCH7 returning by a door nobody had shut.
    try:
        parse_federation_list = _load_parse_federation_list()
    except Exception as e:  # noqa: BLE001
        logger.error(f"[provision] the federation-list PARSER could not be loaded ({type(e).__name__}: {e}). This is "
                     f"a defect in this file, not a property of the SPIRE server: an operator registered now "
                     f"inherits no federation. Treating the list as empty.")
        return ""
    try:
        return ",".join(td for td in parse_federation_list(text) if td)
    except Exception as e:  # noqa: BLE001 — a fallback, reported, never fatal
        logger.warning(f"[provision] could not read the SPIRE federation list: {e}")
        return ""

def _spire_server_address() -> str:
    return os.getenv("SPIRE_SERVER_ADDRESS", "spire.theprotocol.cloud")

def _spire_server_port() -> str:
    return os.getenv("SPIRE_SERVER_PORT", "8444")


@dataclass
class ProvisionResult:
    """Result of a successful operator provisioning."""
    bundle_path: str
    fingerprint: str
    docker_username: str
    docker_pull_token: str          # Plaintext dpt_ token (shown ONCE)
    docker_pull_token_hash: str     # SHA-256 hex for DB storage
    docker_pull_token_prefix: str   # First 8 chars for display
    cert_expiry: str
    entries_registered: int


def _get_docker_client():
    """Get a Docker SDK client connected to the local socket."""
    try:
        import docker
        return docker.DockerClient(base_url="unix:///var/run/docker.sock")
    except ImportError:
        raise RuntimeError("Docker SDK (docker package) is not installed")
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Docker socket: {e}")


def generate_attestation_certs(operator_name: str, output_dir: str) -> str:
    """
    Generate an x509pop attestation key+cert for a SPIRE agent, signed by the SPIRE CA.

    Returns the SHA-1 fingerprint of the DER-encoded certificate (used as SPIRE agent ID).
    """
    logger.info(f"[provision:{operator_name}] Generating attestation certificates")

    spire_dir = Path(output_dir) / "spire"
    spire_dir.mkdir(parents=True, exist_ok=True)

    ca_key_path = Path(CA_DIR) / "attestation-ca.key"
    ca_cert_path = Path(CA_DIR) / "attestation-ca.crt"

    if not ca_key_path.exists():
        raise FileNotFoundError(f"CA key not found at {ca_key_path}")
    if not ca_cert_path.exists():
        raise FileNotFoundError(f"CA cert not found at {ca_cert_path}")

    # Load CA key and cert
    ca_key_pem = ca_key_path.read_bytes()
    ca_cert_pem = ca_cert_path.read_bytes()

    ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)

    # Generate RSA-2048 key for the operator agent
    agent_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Build subject
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Bavaria"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Freilassing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TheProtocol"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Federation"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"spire-agent-{operator_name}"),
    ])

    # Build and sign certificate (730 days = ~2 years)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(agent_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=730))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Write private key (mode 0o600)
    key_path = spire_dir / "agent-attestation.key"
    key_path.write_bytes(
        agent_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)

    # Write certificate
    cert_path = spire_dir / "agent-attestation.crt"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    # Compute SHA-1 fingerprint of DER-encoded cert
    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    fingerprint = hashlib.sha1(der_bytes).hexdigest()

    logger.info(
        f"[provision:{operator_name}] Attestation cert generated: "
        f"fingerprint={fingerprint}, expires={cert.not_valid_after.isoformat()}"
    )

    return fingerprint


def export_trust_bundle(operator_name: str, output_dir: str) -> None:
    """
    Export the SPIRE trust bundle from the SPIRE server container and write it
    to the operator's spire/ directory.
    """
    logger.info(f"[provision:{operator_name}] Exporting SPIRE trust bundle")

    client = _get_docker_client()

    _spire_c = _spire_container()
    try:
        container = client.containers.get(_spire_c)
    except Exception as e:
        raise RuntimeError(f"Cannot find SPIRE server container '{_spire_c}': {e}")

    exit_code, output = container.exec_run(
        [SPIRE_BINARY, "bundle", "show", "-format", "pem"],
        demux=True,
    )

    stdout = output[0] if output[0] else b""
    stderr = output[1] if output[1] else b""

    if exit_code != 0:
        raise RuntimeError(
            f"SPIRE bundle export failed (exit={exit_code}): {stderr.decode(errors='replace')}"
        )

    if not stdout.strip():
        raise RuntimeError("SPIRE bundle export returned empty output")

    spire_dir = Path(output_dir) / "spire"
    spire_dir.mkdir(parents=True, exist_ok=True)

    bundle_path = spire_dir / "trust-bundle.crt"
    bundle_path.write_bytes(stdout)

    logger.info(
        f"[provision:{operator_name}] Trust bundle written: {bundle_path} ({len(stdout)} bytes)"
    )


def register_operator_data_entry(operator_name: str, fingerprint: str, dns_name: str) -> int:
    """The operator database's own SVID: one entry, never federated, with the db container name as its DNS SAN.

    ⚠ WHY IT IS SEPARATE FROM THE OTHER THREE. Those are registered at BUNDLE time and travel with the tar; this
    one is registered at STACK time, because an application whose bundle already exists (beacon's jelgava) would
    otherwise never get it and the database would wait forever on a cert nobody issued. Re-registration is safe:
    an entry that is already there counts as registered (§OPDIST V0386).

    ⚠ AND IT IS NEVER FEDERATED. The frame's auditor dials this database from inside the frame's own identity
    network; a federated data identity would offer the operator's database to every peer trust domain the parent
    federates with, which is authority nobody asked for. `register_spire_entries` applies SPIRE_FEDERATE_WITH to
    every entry it makes, which is exactly why this is not one of them.

    The DNS SAN is the name the CALLER verifies — the auditor connects PGSSLMODE=verify-full to the db container
    by name, so a cert without that name fails the hostname check however sound its chain (§XFRAMETEG, twice).
    """
    if not fingerprint or not dns_name:
        raise ValueError("the data entry needs both a fingerprint and the DNS name its reader verifies")
    return _register_stack_time_entry(operator_name, fingerprint, "data", "svid-writer-data-operator", dns_name)


def register_operator_opa_entry(operator_name: str, fingerprint: str, dns_name: str) -> int:
    """The operator OPA's own SVID: one entry, never federated, with the OPA container name as its DNS SAN.

    §OPA (2026-10-06, his words "please roll out and enable opa for the whole production cluster", then "we need this
    whole ... provisioner fix"): the frames carried an OPA since §SOVKIT and no operator did, so every operator
    registry's OPA code stayed dark. The OPA serves TLS on this SVID and verifies its callers against the bundle that
    comes with it; the registry dials it by container name (OPA_URL), so that name is the SAN.

    Registered at STACK time like the data entry (host_work._opa_steps), so an operator whose bundle predates it
    gains it on its next stack phase or retrofit, and NEVER FEDERATED for the same reason: this OPA answers its own
    registry alone, and a federated identity would put peer trust domains' roots in the bundle it verifies callers
    against. Re-registration is safe: an entry that is already there counts as registered.
    """
    if not fingerprint or not dns_name:
        raise ValueError("the opa entry needs both a fingerprint and the DNS name its caller verifies")
    return _register_stack_time_entry(operator_name, fingerprint, "opa", "svid-writer-opa-operator", dns_name)


def _register_stack_time_entry(operator_name: str, fingerprint: str, role: str, label: str, dns_name: str) -> int:
    """One unfederated entry under the operator's agent: spiffe://<td>/operator/<name>/<role>, selected by the docker
    label `com.agentvault.service=<label>`, one DNS SAN. 1 when it is registered (or already was), 0 when it failed."""
    import docker            # imported here like every other docker user in this module: it is not a leaf import
    _td, _spire_c = _trust_domain(), _spire_container()
    client = docker.from_env()
    try:
        container = client.containers.get(_spire_c)
    except Exception as e:
        raise RuntimeError(f"Cannot find SPIRE server container '{_spire_c}': {e}")
    cmd = [
        SPIRE_BINARY, "entry", "create",
        "-parentID", f"spiffe://{_td}/spire/agent/x509pop/{fingerprint}",
        "-spiffeID", f"spiffe://{_td}/operator/{operator_name}/{role}",
        "-selector", f"docker:label:com.agentvault.service:{label}",
        "-dns", dns_name,
        "-x509SVIDTTL", "14400",
    ]
    exit_code, output = container.exec_run(cmd, demux=True)
    stdout = (output[0] or b"").decode(errors="replace")
    stderr = (output[1] or b"").decode(errors="replace")
    if exit_code == 0:
        logger.info(f"[provision:{operator_name}] {role} entry registered (dns={dns_name})")
        return 1
    if _entry_already_exists(stdout, stderr):
        logger.info(f"[provision:{operator_name}] {role} entry was already registered; keeping it")
        return 1
    logger.error(f"[provision:{operator_name}] {role} entry FAILED (exit={exit_code}): {stderr.strip()[:300]}")
    return 0


def register_spire_entries(operator_name: str, fingerprint: str, domain: str = "") -> int:
    """
    Register 3 SPIRE workload entries for the operator (registry, svid-writer, teg).
    Uses Docker exec on the SPIRE server container.

    Args:
        operator_name: Operator name slug
        fingerprint: SHA-1 fingerprint of the attestation cert
        domain: Optional external domain for DNS SAN (e.g., 'acme.op.theprotocol.cloud')

    Returns the number of successfully registered entries.
    """
    logger.info(f"[provision:{operator_name}] Registering SPIRE entries (fingerprint={fingerprint}, domain={domain})")

    client = _get_docker_client()

    _spire_c = _spire_container()
    _td = _trust_domain()
    _fed = _federate_with()
    try:
        container = client.containers.get(_spire_c)
    except Exception as e:
        raise RuntimeError(f"Cannot find SPIRE server container '{_spire_c}': {e}")

    if not _fed:
        # §BATCH7: no SPIRE_FEDERATE_WITH on this frame → inherit the parent's live federation.
        _fed = federation_from_spire_server(container)
        if _fed:
            logger.info(f"[provision:{operator_name}] federation inherited from {_spire_c}: {_fed}")

    parent_id = f"spiffe://{_td}/spire/agent/x509pop/{fingerprint}"

    # svid-writer needs DNS SANs for both internal (nginx-federation) and external (domain)
    # `domain` may be a single str OR a list/tuple of domains (e.g. the CURRENT
    # `{slug}.op.theprotocol.cloud` + the legacy `{slug}.frame-b.theprotocol.cloud`),
    # so cross-frame federation mTLS verifies whichever hostname the dialer uses.
    # §2026-06-16 TEG-mTLS Phase 3: nginx-teg is the internal mTLS sidecar in front of the
    # op TEG; its server cert (this svid-writer SVID) must carry the `nginx-teg` SAN so the
    # op registry's check_hostname passes when dialing https://nginx-teg:8443.
    svid_writer_dns = ["nginx-federation", "nginx-teg"]
    if domain:
        if isinstance(domain, (list, tuple)):
            svid_writer_dns.extend([d for d in domain if d])
        else:
            svid_writer_dns.append(domain)

    entries = [
        {
            "name": "registry",
            "spiffe_id": f"spiffe://{_td}/operator/{operator_name}/registry",
            "selector": "docker:label:com.agentvault.service:registry",
        },
        {
            "name": "svid-writer",
            "spiffe_id": f"spiffe://{_td}/operator/{operator_name}/svid-writer",
            "selector": "docker:label:com.agentvault.service:svid-writer-operator",
            "dns": svid_writer_dns,
        },
        {
            "name": "teg",
            "spiffe_id": f"spiffe://{_td}/operator/{operator_name}/teg",
            "selector": "docker:label:com.agentvault.service:teg-layer",
        },
    ]

    success_count = 0


    already_count = 0
    for entry in entries:
        cmd = [
            SPIRE_BINARY, "entry", "create",
            "-parentID", parent_id,
            "-spiffeID", entry["spiffe_id"],
            "-selector", entry["selector"],
            "-x509SVIDTTL", "14400",
        ]
        if "dns" in entry:
            dns_val = entry["dns"]
            if isinstance(dns_val, list):
                for d in dns_val:
                    cmd.extend(["-dns", d])
            else:
                cmd.extend(["-dns", dns_val])
        if _fed:
            # 2026-07-16 FIX: SPIRE_FEDERATE_WITH may be a COMMA-SEPARATED list of
            # trust domains (e.g. "sandbox-b.test,sandbox-c.test"). Each needs its
            # OWN -federatesWith spiffe://<td> flag; the old single-prefix form
            # produced "spiffe://sandbox-b.test,sandbox-c.test" → SPIRE rejected
            # the whole entry (InvalidArgument: failed to convert entry), so EVERY
            # operator provision registered 0/3 SPIRE entries and got no real SVIDs.
            for _fd in _fed.split(","):
                _fd = _fd.strip()
                if not _fd:
                    continue
                _val = _fd if _fd.startswith("spiffe://") else f"spiffe://{_fd}"
                cmd.extend(["-federatesWith", _val])

        logger.info(
            f"[provision:{operator_name}] Registering SPIRE entry: {entry['name']} "
            f"(spiffeID={entry['spiffe_id']})"
        )

        exit_code, output = container.exec_run(cmd, demux=True)

        stdout = (output[0] or b"").decode(errors="replace")
        stderr = (output[1] or b"").decode(errors="replace")

        if exit_code == 0:
            success_count += 1
            logger.info(f"[provision:{operator_name}] Entry '{entry['name']}' registered: {stdout.strip()}")
        elif _entry_already_exists(stdout, stderr):
            # ⚠ AN ENTRY THAT IS ALREADY THERE IS A REGISTERED ENTRY. `entry create` exits non-zero for a duplicate,
            # so a re-bundle after a half-finished provision counted 0 of 3 and reported a SPIRE registration that
            # had in fact succeeded the first time (beacon's ventspils: 3 entries and a tar on disk, the row unaware).
            # Counting it keeps a recovery idempotent; the count still says how many of the three the operator has.
            already_count += 1
            success_count += 1
            logger.info(f"[provision:{operator_name}] Entry '{entry['name']}' was already registered; keeping it")
        else:
            logger.error(
                f"[provision:{operator_name}] Entry '{entry['name']}' failed "
                f"(exit={exit_code}): {stderr.strip()}"
            )

    if success_count < len(entries):
        # RP2 (2026-07-24): this used to be an INFO line and nothing else. An operator
        # provisioned with 0/3 entries gets no real SVIDs, so its mTLS federation is
        # dead on arrival while the provisioning API reports SUCCESS. Say it loudly
        # here; the caller refuses to continue (see provision_operator).
        logger.critical(
            f"[provision:{operator_name}] SPIRE entries INCOMPLETE: "
            f"{success_count}/{len(entries)} — this operator would have no working "
            f"mTLS identity. See the per-entry errors above."
        )
    else:
        logger.info(
            f"[provision:{operator_name}] SPIRE entries registered: {success_count}/{len(entries)}"
        )

    return success_count


def generate_agent_conf(operator_name: str, output_dir: str) -> None:
    """
    Generate a SPIRE agent.conf template for the operator bundle.
    Uses x509pop attestor with the generated attestation cert.
    """
    logger.info(f"[provision:{operator_name}] Generating agent.conf")

    spire_dir = Path(output_dir) / "spire"
    spire_dir.mkdir(parents=True, exist_ok=True)

    _ssa = _spire_server_address()
    _ssp = _spire_server_port()
    _td = _trust_domain()
    conf_content = f"""agent {{
  data_dir = "/opt/spire/data"
  log_level = "INFO"
  server_address = "{_ssa}"
  server_port = "{_ssp}"
  socket_path = "/opt/spire/sockets/agent.sock"
  trust_bundle_path = "/opt/spire/conf/trust-bundle.crt"
  trust_domain = "{_td}"
}}

plugins {{
  NodeAttestor "x509pop" {{
    plugin_data {{
      private_key_path = "/opt/spire/conf/agent-attestation.key"
      certificate_path = "/opt/spire/conf/agent-attestation.crt"
    }}
  }}

  KeyManager "disk" {{
    plugin_data {{
      directory = "/opt/spire/data"
    }}
  }}

  WorkloadAttestor "docker" {{
    plugin_data {{
      docker_socket_path = "unix:///var/run/docker.sock"
    }}
  }}
}}

health_checks {{
  listener_enabled = true
  bind_address = "0.0.0.0"
  bind_port = "8082"
  live_path = "/live"
  ready_path = "/ready"
}}
"""

    conf_path = spire_dir / "agent.conf"
    conf_path.write_text(conf_content)

    logger.info(f"[provision:{operator_name}] agent.conf written to {conf_path}")


# §MTLSHOPS (2026-09-16) — the operator's own posture, rendered per operator rather than baked into the templates.
#
# The two terminator templates ship the marker as a PLACEHOLDER because the secret is per operator, which makes the
# substitution mandatory rather than optional: a conf shipped with the placeholder still in it sends a marker the app
# cannot match and every mTLS call through that terminator is refused. The refusal below names the file and the
# placeholder rather than failing blankly, because the next reader is someone whose operator will not talk.
# The token the templates carry in front of each marker line, so an older provisioner copies a conf that behaves exactly
# as today's does and only this code turns the marker on.
MARKER_COMMENT = "#OPDIST-MARKER#"
MARKER_HEADERS = {"TEG_PROXY_TRUST_SECRET": "X-TEG-Proxy-Auth",
                  "REGISTRY_PROXY_TRUST_SECRET": "X-Registry-Proxy-Auth"}
MARKER_PLACEHOLDERS = {
    "nginx-teg.conf": ("__TEG_PROXY_TRUST_SECRET__", "TEG_PROXY_TRUST_SECRET"),
    "nginx-federation.conf": ("__REGISTRY_PROXY_TRUST_SECRET__", "REGISTRY_PROXY_TRUST_SECRET"),
}
# nginx-federation also proxies the operator's own TEG on its cross-teg block, so it carries BOTH markers.
EXTRA_PLACEHOLDERS = {"nginx-federation.conf": [("__TEG_PROXY_TRUST_SECRET__", "TEG_PROXY_TRUST_SECRET")]}
# One ACL user per client, the rule set the frames use: everything the app needs, nothing administrative.
REDIS_APP_RULES = (
    "~* &* +@all -flushall -flushdb -config -debug -shutdown -acl -monitor -replicaof -slaveof -module -save "
    "-bgsave -bgrewriteaof -failover -cluster -migrate -restore -sync -psync -swapdb"
)
# The default user keeps PING because the container's own healthcheck is `redis-cli ping`, and nothing else.
REDIS_DEFAULT_RULES = "on nopass resetkeys resetchannels -@all +ping"
OPERATOR_SECRET_NAMES = (
    "TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET", "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG",
    # §OPDIST (2026-09-16): the credential the FRAME'S AUDITOR reads this operator's share register with. It is
    # minted here with the others because it is the operator's to hold and this is the one place that mints them,
    # but ⚠ IT IS NOT WRITTEN INTO .env.operator: the operator's own apps never use it, and the rule that decides
    # what crosses a seam — what will the far side DO with it — decides what lands in a file too. The one-shot
    # creates the role with it and the frame's auditor is given the DSN.
    "AUDITOR_RO_PASSWORD",
)

# The subset the operator's own containers read. Everything else is minted FOR the operator without being handed
# to it, which is why the env writer takes this list rather than the dict's keys.
OPERATOR_ENV_SECRET_NAMES = tuple(n for n in OPERATOR_SECRET_NAMES if n != "AUDITOR_RO_PASSWORD")


def generate_operator_secrets() -> dict:
    """The values an operator is born with: one marker per terminator, one Redis password per client, and the
    read-only database credential its frame's auditor will read its share register with."""
    return {name: secrets.token_hex(32) for name in OPERATOR_SECRET_NAMES}


def write_redis_acl(target_dir: str, values: dict, operator_name: str = "") -> str:
    """The ACL file the operator's Redis reads, beside its compose. Hashes only: the passwords live in .env.operator."""
    lines = [f"user default {REDIS_DEFAULT_RULES}"]
    for user, key in (("registry", "REDIS_PASSWORD_REGISTRY"), ("teg", "REDIS_PASSWORD_TEG")):
        digest = hashlib.sha256(values[key].encode()).hexdigest()
        lines.append(f"user {user} on #{digest} {REDIS_APP_RULES}")
    path = os.path.join(target_dir, "redis-users.acl")
    # §SECFIX (2026-09-26): written beside the target and RENAMED over it, never opened in place. The chown below gives
    # the file to Redis's uid, so the next write by the same uid-1000 writer (a re-provision after a failed attempt)
    # could not open it: measured on secfixt, "PermissionError: [Errno 13] ... redis-users.acl" on the retry after an
    # earlier attempt had written and chowned it. A rename needs write permission on the directory, not on the file,
    # so a retry replaces what it cannot open; the one-shot's socket chown then gives the new file to Redis again.
    fd, tmp = tempfile.mkstemp(prefix=".redis-users.acl.", dir=target_dir)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # Redis in the operator image runs as uid 999; the file must be readable by it and by nobody else.
    try:
        os.chown(path, 999, 1000)
    except PermissionError:  # a bundle built somewhere without the right to chown: the operator host fixes it
        logger.warning(f"[provision:{operator_name}] could not chown {path} to the redis uid; the operator host must")
    logger.info(f"[provision:{operator_name}] wrote {path} (one ACL user per client, sha256 hashes only)")
    return path


def apply_operator_secrets(target_dir: str, values: dict, operator_name: str = "") -> None:
    """Substitute each terminator's marker into the conf that sends it, then REFUSE if any placeholder survived.

    A surviving placeholder is worse than no marker: the terminator would send a value the app cannot match, so every
    call through it is refused. It happens to fail safe today only because the placeholder is 26 characters against the
    app's 32-character minimum, which is arithmetic rather than design and would disappear the day either number moves.
    """
    nginx_dir = os.path.join(target_dir, "nginx")
    for conf, (placeholder, key) in MARKER_PLACEHOLDERS.items():
        path = os.path.join(nginx_dir, conf)
        if not os.path.exists(path):
            raise RuntimeError(
                f"[provision:{operator_name}] {path} is missing, so its marker cannot be rendered and the operator's "
                f"terminator would forward certificates the app refuses"
            )
        text = open(path).read()
        pairs = [(placeholder, key)] + EXTRA_PLACEHOLDERS.get(conf, [])
        # ⚠ THE MARKER SHIPS COMMENTED OUT, and this is why. These confs are ONE host bind mount shared by every registry
        # on the box, while the code that renders them ships per image. A frame still on the older image copies the conf
        # verbatim and has no substitution step, so an uncommented placeholder would reach a live operator's terminator
        # and its apps would refuse every forwarded certificate. Commented, that frame gets exactly today's behaviour;
        # here, uncommenting is the first half of rendering and the refusals below cover the rest.
        text = text.replace(f"{MARKER_COMMENT} proxy_set_header", "proxy_set_header")
        for ph, k in pairs:
            text = text.replace(ph, values[k])
        if MARKER_COMMENT in text:
            raise RuntimeError(
                f"[provision:{operator_name}] {path} still carries {MARKER_COMMENT} after rendering: a marker that stays "
                f"a comment is a terminator that sends nothing and apps that refuse every forwarded certificate"
            )
        left = [ph for ph, _ in pairs if ph in text] + [ph for ph, _ in MARKER_PLACEHOLDERS.values() if ph in text]
        if left:
            raise RuntimeError(
                f"[provision:{operator_name}] {path} still contains {sorted(set(left))} after substitution: the "
                f"terminator would send a marker the app cannot match and every mTLS call through it would be refused"
            )
        # ⚠ THE OTHER ORDERING FAILS TOO, AND SILENTLY. These confs are a HOST BIND MOUNT shared by every frame on the
        # box (/opt/theprotocol/stack/Agentvault2/scripts/distribution/nginx-templates -> /app/nginx-templates, same
        # inode inside and out), while this code ships in the image. New code against OLD confs finds no placeholder,
        # substitutes nothing, and would provision an operator whose apps have been given a marker their terminators
        # never send: every mTLS call refused, with nothing in any log to say why. So assert the marker is PRESENT with
        # a real value, not merely that no placeholder is left.
        for _ph, k in pairs:
            header = MARKER_HEADERS[k]
            # ⚠ ASSERT THE DIRECTIVE IS ACTIVE, NOT THAT THE TEXT IS PRESENT (agentvault2-85 caught this). A COMMENTED
            # directive contains both the header name and the value, so a substring check over the file passes on a conf
            # where the substitution worked and the uncommenting did not — which is the one new failure mode the shipped
            # comment introduces, and nginx would ignore the line while the apps demand the marker. Match the directive
            # anchored at the start of its own line, with no '#' in front of it.
            live = re.search(
                rf'^[ \t]*proxy_set_header[ \t]+{re.escape(header)}[ \t]+"?{re.escape(values[k])}"?[ \t]*;',
                text, re.M)
            if not live:
                commented = re.search(rf'^[ \t]*#.*proxy_set_header[ \t]+{re.escape(header)}', text, re.M)
                why = ("it is still COMMENTED OUT, so nginx ignores it while the app demands it" if commented else
                       "this conf predates the marker work while this code expects it")
                raise RuntimeError(
                    f"[provision:{operator_name}] {path} carries no LIVE {header} directive: {why}, so the operator's "
                    f"apps would require a marker their terminator never sends and refuse every mTLS call."
                )
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, 0o600)
        logger.info(f"[provision:{operator_name}] rendered {conf}'s marker(s) and set it 600")
    write_redis_acl(target_dir, values, operator_name)


def copy_nginx_config(operator_name: str, output_dir: str) -> None:
    """
    Copy nginx mTLS federation config and entrypoint script to the operator bundle.
    """
    logger.info(f"[provision:{operator_name}] Copying nginx config templates")

    nginx_dir = Path(output_dir) / "nginx"
    nginx_dir.mkdir(parents=True, exist_ok=True)

    templates_dir = Path(NGINX_TEMPLATES_DIR)

    # Copy nginx-federation.conf
    src_conf = templates_dir / "nginx-federation.conf"
    dst_conf = nginx_dir / "nginx-federation.conf"
    if src_conf.exists():
        shutil.copy2(str(src_conf), str(dst_conf))
        logger.info(f"[provision:{operator_name}] Copied {src_conf} -> {dst_conf}")
    else:
        logger.warning(
            f"[provision:{operator_name}] nginx-federation.conf not found at {src_conf}, "
            f"writing default template"
        )
        _write_default_nginx_conf(dst_conf)

    # §2026-06-16 TEG-mTLS Phase 3 — Copy nginx-teg.conf (the internal TEG mTLS sidecar config).
    src_teg = templates_dir / "nginx-teg.conf"
    dst_teg = nginx_dir / "nginx-teg.conf"
    if src_teg.exists():
        shutil.copy2(str(src_teg), str(dst_teg))
        logger.info(f"[provision:{operator_name}] Copied {src_teg} -> {dst_teg}")
    else:
        logger.warning(
            f"[provision:{operator_name}] nginx-teg.conf not found at {src_teg} "
            f"(new op TEG mTLS sidecar will fail to start)"
        )

    # ⚠ The two confs above carry their marker as a PLACEHOLDER. Whoever renders this operator's environment has to
    # call apply_operator_secrets() on the directory, or the terminators forward certificates the apps refuse.
    logger.info(
        f"[provision:{operator_name}] nginx confs carry marker placeholders; apply_operator_secrets() must render them"
    )

    # Copy nginx-entrypoint.sh
    src_entry = templates_dir / "nginx-entrypoint.sh"
    dst_entry = nginx_dir / "nginx-entrypoint.sh"
    if src_entry.exists():
        shutil.copy2(str(src_entry), str(dst_entry))
    else:
        logger.warning(
            f"[provision:{operator_name}] nginx-entrypoint.sh not found at {src_entry}, "
            f"writing default template"
        )
        _write_default_nginx_entrypoint(dst_entry)

    dst_entry.chmod(0o755)

    logger.info(f"[provision:{operator_name}] nginx config files ready in {nginx_dir}")


def _write_default_nginx_conf(path: Path) -> None:
    """Write a default nginx-federation.conf if the template is missing."""
    path.write_text("""\
# nginx mTLS Federation Sidecar -- Operator Registry
server {
    listen 8080;
    server_name _;
    location /health {
        return 200 '{"status":"healthy","service":"nginx-operator","mode":"mtls-sidecar"}\\n';
        add_header Content-Type application/json;
    }
}

server {
    listen 8443 ssl;
    server_name nginx-federation;

    ssl_certificate       /certs/svid.0.pem;
    ssl_certificate_key   /certs/svid.0.key;
    ssl_client_certificate /certs/bundle.0.pem;
    ssl_verify_client      on;
    ssl_verify_depth       2;
    ssl_protocols          TLSv1.2 TLSv1.3;
    ssl_ciphers            HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache      shared:SSL:1m;
    ssl_session_timeout    5m;

    location /api/v1/federation/ {
        proxy_pass http://registry:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-SSL-Client-Cert   $ssl_client_escaped_cert;
        proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
        proxy_set_header X-SSL-Client-S-DN   $ssl_client_s_dn;
        proxy_set_header X-Federation-Secret    "";
        proxy_set_header X-Federation-SPIFFE-ID "";
        proxy_connect_timeout 30s;
        proxy_read_timeout    60s;
        proxy_send_timeout    30s;
    }

    location / {
        return 404 '{"error":"Only federation endpoints are served via mTLS proxy"}\\n';
        add_header Content-Type application/json;
    }
}
""")


def _write_default_nginx_entrypoint(path: Path) -> None:
    """Write a default nginx-entrypoint.sh if the template is missing."""
    path.write_text("""\
#!/bin/sh
set -e
CERT_DIR="${CERT_DIR:-/certs}"
RELOAD_SEC="${RELOAD_SEC:-300}"
SERVICE_NAME="${SERVICE_NAME:-unknown}"

echo "[nginx:${SERVICE_NAME}] Waiting for SVID certificates in ${CERT_DIR}..."

WAIT_COUNT=0
MAX_WAIT=120
while [ ! -f "${CERT_DIR}/.ready" ]; do
    WAIT_COUNT=$((WAIT_COUNT + 1))
    if [ ${WAIT_COUNT} -ge ${MAX_WAIT} ]; then
        echo "[nginx:${SERVICE_NAME}] ERROR: Certificates not ready after ${MAX_WAIT}s"
        exit 1
    fi
    sleep 1
done

echo "[nginx:${SERVICE_NAME}] Certificates found"
nginx -t 2>&1 || exit 1
nginx -g 'daemon off;' &
NGINX_PID=$!

while kill -0 ${NGINX_PID} 2>/dev/null; do
    sleep "${RELOAD_SEC}"
    if kill -0 ${NGINX_PID} 2>/dev/null; then
        nginx -s reload 2>&1 || true
    fi
done

wait ${NGINX_PID}
""")


def generate_docker_credentials(operator_name: str) -> tuple[str, str]:
    """
    Generate Docker image registry pull token for the operator.
    Creates a username and dpt_ prefixed token validated by the
    Docker Registry v2 token auth server (f050).

    Returns (username, plaintext_token).
    The caller must store the SHA-256 hash in the database.
    """
    import hashlib as _hashlib

    logger.info(f"[provision:{operator_name}] Generating Docker pull token (f050 token auth)")

    username = f"operator-{operator_name}"
    plaintext_token = f"dpt_{secrets.token_hex(32)}"  # 68-char token

    logger.info(f"[provision:{operator_name}] Docker pull token generated for {username}")

    return username, plaintext_token


def package_bundle(operator_name: str, output_dir: str) -> str:
    """
    Package the operator provisioning output into a tar.gz bundle.
    Includes spire/ and nginx/ directories.

    Returns the path to the generated tar.gz file.
    """
    logger.info(f"[provision:{operator_name}] Packaging operator bundle")

    bundles_path = Path(BUNDLES_DIR)
    bundles_path.mkdir(parents=True, exist_ok=True)

    bundle_filename = f"{operator_name}.tar.gz"
    bundle_path = bundles_path / bundle_filename

    output = Path(output_dir)

    templates_dir = Path(NGINX_TEMPLATES_DIR)

    with tarfile.open(str(bundle_path), "w:gz") as tar:
        # Add spire/ directory
        spire_dir = output / "spire"
        if spire_dir.exists():
            tar.add(str(spire_dir), arcname="spire")
            logger.info(f"[provision:{operator_name}] Added spire/ to bundle")

        # Add nginx/ directory
        nginx_dir = output / "nginx"
        if nginx_dir.exists():
            tar.add(str(nginx_dir), arcname="nginx")
            logger.info(f"[provision:{operator_name}] Added nginx/ to bundle")

        # Add operator stack files from templates
        for template_file in ["docker-compose.operator.yml", "generate-operator-env.sh", "pgbouncer.ini"]:
            src = templates_dir / template_file
            if src.exists():
                tar.add(str(src), arcname=template_file)
                logger.info(f"[provision:{operator_name}] Added {template_file} to bundle")
            else:
                logger.warning(f"[provision:{operator_name}] Template missing: {src}")

    bundle_size = bundle_path.stat().st_size
    logger.info(
        f"[provision:{operator_name}] Bundle packaged: {bundle_path} ({bundle_size} bytes)"
    )

    return str(bundle_path)


def provision_operator(operator_name: str, operator_did: str, docker_pull_token: str = "") -> ProvisionResult:
    """
    Master orchestrator: provisions a complete operator bundle.

    Steps:
      1. Generate x509pop attestation certificates
      2. Export SPIRE trust bundle
      3. Register SPIRE workload entries
      4. Generate SPIRE agent.conf
      5. Copy nginx mTLS config
      6. Generate Docker image registry credentials
      7. Package everything into a tar.gz bundle

    On failure, cleans up the temp directory and re-raises.

    Returns a ProvisionResult with all metadata.
    """
    import tempfile

    logger.info(
        f"[provision:{operator_name}] === Starting operator provisioning === "
        f"(operator_did={operator_did})"
    )

    temp_dir = tempfile.mkdtemp(prefix=f"operator-{operator_name}-")
    logger.info(f"[provision:{operator_name}] Working directory: {temp_dir}")

    try:
        # Step 1: Generate attestation certificates
        fingerprint = generate_attestation_certs(operator_name, temp_dir)

        # Step 2: Export SPIRE trust bundle
        export_trust_bundle(operator_name, temp_dir)

        # Step 3: Register SPIRE entries
        entries_registered = register_spire_entries(operator_name, fingerprint)

        # RP2 (2026-07-24, wiring audit): provisioning used to report SUCCESS with
        # 0/3 entries registered — the operator boots, federates over plain trust,
        # and nobody learns its mTLS identity was never created until a corridor
        # dies weeks later. Fail closed. The escape hatch exists for a deliberate
        # SPIRE-less bring-up (air-gapped / lab), and it still marks the result.
        _expected_entries = 3
        if entries_registered < _expected_entries:
            if not _env_true("OPERATOR_PROVISION_ALLOW_PARTIAL_SPIRE"):
                raise RuntimeError(
                    f"SPIRE registration incomplete for '{operator_name}': "
                    f"{entries_registered}/{_expected_entries} entries. The operator would "
                    f"have no working mTLS identity, so provisioning is aborted. Fix the "
                    f"SPIRE server error above, or set "
                    f"OPERATOR_PROVISION_ALLOW_PARTIAL_SPIRE=true to provision anyway."
                )
            logger.critical(
                f"[provision:{operator_name}] continuing with {entries_registered}/"
                f"{_expected_entries} SPIRE entries because "
                f"OPERATOR_PROVISION_ALLOW_PARTIAL_SPIRE is set — mTLS federation will NOT work."
            )

        # Step 4: Generate agent.conf
        generate_agent_conf(operator_name, temp_dir)

        # Step 5: Copy nginx config
        copy_nginx_config(operator_name, temp_dir)

        # Step 6: Docker pull token (f050 — DB-backed token auth).
        # §OPDIST (2026-09-16): the caller may MINT IT and pass it in, and the host one-shot always does. The token's
        # hash is a database row, and the registry is the only side of the seam that writes rows, so the side that
        # stores the hash is the side that should mint the secret. A token minted here and lost with a failed provision
        # is inert (nothing stored it), which is why passing it in is safe where passing an activation code would not be.
        if docker_pull_token:
            docker_username = f"operator-{operator_name}"   # the same form generate_docker_credentials uses
            logger.info(f"[provision:{operator_name}] using the pull token the caller minted (prefix {docker_pull_token[:8]})")
        else:
            docker_username, docker_pull_token = generate_docker_credentials(operator_name)
        import hashlib as _hl
        docker_pull_token_hash = _hl.sha256(docker_pull_token.encode()).hexdigest()
        docker_pull_token_prefix = docker_pull_token[:8]

        # Step 7: Package bundle
        bundle_path = package_bundle(operator_name, temp_dir)

        # Compute cert expiry from the generated cert
        cert_path = Path(temp_dir) / "spire" / "agent-attestation.crt"
        cert_data = cert_path.read_bytes()
        cert_obj = x509.load_pem_x509_certificate(cert_data)
        cert_expiry = cert_obj.not_valid_after.isoformat()

        result = ProvisionResult(
            bundle_path=bundle_path,
            fingerprint=fingerprint,
            docker_username=docker_username,
            docker_pull_token=docker_pull_token,
            docker_pull_token_hash=docker_pull_token_hash,
            docker_pull_token_prefix=docker_pull_token_prefix,
            cert_expiry=cert_expiry,
            entries_registered=entries_registered,
        )

        logger.info(
            f"[provision:{operator_name}] === Provisioning complete === "
            f"bundle={bundle_path}, fingerprint={fingerprint}, "
            f"entries={entries_registered}, cert_expires={cert_expiry}"
        )

        return result

    except Exception:
        logger.exception(f"[provision:{operator_name}] Provisioning failed, cleaning up {temp_dir}")
        raise
    finally:
        # Always clean up temp directory
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"[provision:{operator_name}] Cleaned up temp directory {temp_dir}")
