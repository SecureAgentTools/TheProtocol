"""
Frame Test Provisioner (sandbox-only)

Provisions an ephemeral sovereign frame (~13-container stack with its own
SPIRE trust domain, Postgres trio, Redis, Redpanda, EventStore, TEG, Registry,
cert-writer, and nginx-federation) from inside the sandbox-a registry-test
container. Mirrors the structure of cloud_provisioner.py (which provisions
operators) but one layer up in the hierarchy: this provisions a *frame* that
is itself capable of provisioning operators.

All state is timestamped per run (volume + stack-dir + network names end in
_<ts>) so repeated invocations never collide with each other or with a
crashed prior run.

Entry points:
    provision_frame_test(context: FrameTestContext) -> FrameTestProvisionResult
    teardown_frame_test(context: FrameTestContext) -> FrameTestTeardownResult

Its callers: the frame runner's standup (scripts/hetzner_demo/standup_driver.py loads this file by path) and the
federation and revoke rails for its SPIRE helpers. The Frame-A-era test routers that once called provision_frame_test
directly are retired (§NIGHTLYPROV, 2026-09-27).
"""
import base64
import logging
import json
import os
import hashlib
import secrets
import shutil
import time
from dataclasses import dataclass, field
from typing import List, Optional

from agentvault_registry.core import operator_mail
from agentvault_registry.core.registry_slug import fund_origin_allowlist_value  # §MONEY-R50

logger = logging.getLogger(__name__)


# ── Defaults (overridable by env on registry-test) ────────────────────────

FRAME_TEST_TEMPLATE_DIR = os.getenv(
    "FRAME_TEST_TEMPLATE_DIR",
    "/app/templates/frame-test",
)

# Within the registry-test container, /host-stack is bind-mounted from the
# real /opt/theprotocol/stack on the host.
HOST_STACK_MOUNT = os.getenv("FRAME_HOST_STACK_MOUNT", "/host-stack")
# §HELLOFRAME (2026-09-18): the three roots a frame standup used to take from THIS host, as values a foreign host sets:
# where the stacks live, and where the checkout (the export) lives, for the nginx entrypoint every mTLS terminator
# mounts and the operator templates the registry packages bundles from. The defaults are this host's, unchanged.
STACK_ROOT = os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack")
REPO_ROOT = os.getenv("FRAME_REPO_ROOT", f"{HOST_STACK_MOUNT}/Agentvault2")

# Default ports — chosen to avoid collision with Frame B (8100/8102/8201/...)
# and sandbox-a (8002/8002-equivs). Validated free at plan time.
DEFAULT_PORT_REGISTRY = int(os.getenv("FRAME_TEST_PORT_REGISTRY", "8150"))
DEFAULT_PORT_TEG = int(os.getenv("FRAME_TEST_PORT_TEG", "8162"))
DEFAULT_PORT_EVENTSTORE = int(os.getenv("FRAME_TEST_PORT_EVENTSTORE", "8261"))
DEFAULT_PORT_SPIRE_GRPC = int(os.getenv("FRAME_TEST_PORT_SPIRE_GRPC", "8191"))
DEFAULT_PORT_SPIRE_BUNDLE = int(os.getenv("FRAME_TEST_PORT_SPIRE_BUNDLE", "8465"))
DEFAULT_PORT_NGINX_FED = int(os.getenv("FRAME_TEST_PORT_NGINX_FED", "30463"))
# Pocket push (2026-08-01): every frame now mints its own ntfy sidecar so the
# mobile experience works without a manual retrofit. LOOPBACK-bound; public
# exposure is a separate, deliberate step (scripts/hetzner_demo/apply_frame_push.sh)
# because it needs DNS + a certificate, which are ours and never the operator's.
# Doc: PRODUCTION_DOCS/08_SECURITY/Frame_Outbound_Mail_And_Push.md
DEFAULT_PORT_NTFY = int(os.getenv("FRAME_TEST_PORT_NTFY", "8199"))
# §SOVKIT (2026-09-14): the kit's two loopback doors (grafana, the solo auditor); opa, prometheus, alertmanager
# and the directory publish no host port (the registry and grafana reach them on the frame network).
DEFAULT_PORT_GRAFANA = int(os.getenv("FRAME_TEST_PORT_GRAFANA", "8201"))
DEFAULT_PORT_AUDITOR = int(os.getenv("FRAME_TEST_PORT_AUDITOR", "8202"))
# the kit's images: the auditor is built from Agents/TheAuditor, the Directory from directory/ (both by
# scripts/distribution/build.sh in the export); never `:latest`, the tag names the build
DEFAULT_AUDITOR_IMAGE = os.getenv("FRAME_TEST_AUDITOR_IMAGE", "agentvault2-auditor:sovkit1")
DEFAULT_DIRECTORY_IMAGE = os.getenv("FRAME_TEST_DIRECTORY_IMAGE", "theprotocol-directory:sovkit1")
# §HELLOFRAME: the SVID writer six sidecars run (three mTLS terminators, the kit, the directory, the data identity);
# built by build.sh from nginx/Dockerfile.cert-writer in the export. The literal below is this host's local build tag,
# which the template carried at six sites with no knob until 2026-09-18.
DEFAULT_CERT_WRITER_IMAGE = os.getenv("FRAME_TEST_CERT_WRITER_IMAGE", "agentvault2-cert-writer-test-a:latest")

DEFAULT_TRUST_DOMAIN = os.getenv("FRAME_TEST_TRUST_DOMAIN", "frame-test.sandbox")
DEFAULT_REGISTRY_NAME = os.getenv("FRAME_TEST_REGISTRY_NAME", "frame-test")

DEFAULT_WORKERS_REG = int(os.getenv("FRAME_TEST_WORKERS_REG", "4"))
DEFAULT_WORKERS_TEG = int(os.getenv("FRAME_TEST_WORKERS_TEG", "4"))
DEFAULT_WORKERS_ES = int(os.getenv("FRAME_TEST_WORKERS_ES", "2"))

# §DBPOOL (2026-10-10): the registry's database pool per gunicorn worker. With DB_POOL_SIZE / DB_MAX_OVERFLOW unset,
# database.pool_settings keeps 40 idle and 80 in all per worker, and a QueuePool never gives a connection back, so a
# frame's workers held their burst high-water mark against the database's max_connections of 100 (the sandbox pair's
# 8 workers filled theirs between rolls from 2026-10-03 on). A frame is born with the two sized from its worker count
# so that workers x (pool + overflow) stays inside this budget; the rest of the 100 is the auditor's, psql's, a dump's.
REGISTRY_DB_BUDGET = int(os.getenv("FRAME_TEST_REGISTRY_DB_BUDGET", "80"))


def registry_pool(workers) -> tuple:
    """(DB_POOL_SIZE, DB_MAX_OVERFLOW) for a frame registry with `workers` gunicorn workers: half of each worker's share
    of REGISTRY_DB_BUDGET kept idle, the other half overflow (8 workers 5 / 5, 4 workers 10 / 10, 1 worker 40 / 40,
    database.pool_settings' own defaults)."""
    per = max(2, REGISTRY_DB_BUDGET // max(1, int(workers)))
    return per // 2, per - per // 2

# The exact phrase a caller must type to grant a frame's registry host reach.
# Deliberately NOT a boolean: `grant_host_reach=True` is one keystroke and one
# copy-paste away from being set by accident. Typing this sentence is not.
HOST_REACH_CONFIRMATION_PHRASE = "I GRANT ROOT ON THIS HOST"

HOST_REACH_WARNING = """
════════════════════════════════════════════════════════════════════════════
  ⚠  HOST REACH REQUESTED FOR {registry_name}
════════════════════════════════════════════════════════════════════════════
  You are about to mount into this frame's REGISTRY container:

      /var/run/docker.sock      -> the Docker API of THIS machine
      /opt/theprotocol/stack    -> every compose file and .env on this host
      /etc/nginx/sites-enabled  -> the public edge configuration

  Anyone holding an ADMIN credential on this frame can then reach the host.
  Docker socket access IS root: no proxy or allowlist contains it, because
  cloud-operator provisioning legitimately needs container-create plus bind
  mounts, and that is the escape primitive itself. Mounting the socket ":ro"
  does NOT help - read-only applies to the socket FILE, not to the API.

  Grant this ONLY for a frame you operate yourself and whose admin credential
  never leaves your organisation.

  To proceed, pass host_reach_confirmation exactly:

      {phrase}
════════════════════════════════════════════════════════════════════════════
"""


class ProvisioningInputError(ValueError):
    """Raised before anything is created when required inputs are missing or
    a dangerous option was requested without its typed confirmation."""


def validate_provisioning_inputs(ctx: "FrameTestContext", *, strict: bool = True) -> list[str]:
    """Fail fast, BEFORE any container, volume or certificate exists.

    A half-provisioned frame is worse than a refused one: §OPGUIDE-2 showed a
    frame with no reachable relay locks every self-registered account out
    permanently, and the only remedy is an admin endpoint exposed in no UI.

    `strict=False` returns the problems instead of raising, for a dry-run
    "what would you need from me" preflight.
    """
    problems: list[str] = []

    # §FRAMEMAIL-3 — inherit the shared first-party relay BEFORE validating, so a
    # frame provisioned with no explicit mail still gets a working sender instead
    # of falling into the invite-only path by omission. Handed-over frames
    # (first_party=False) are skipped: they bring their own relay or run on
    # invite codes, but never hold our token.
    if ctx.first_party and not (ctx.mail_server or ctx.mail_address or ctx.mail_token):
        _shared = operator_mail.shared_identity()
        if _shared:
            ctx.mail_server = _shared["server"]
            ctx.mail_address = _shared["from_addr"]
            ctx.mail_token = _shared["password"]
            try:
                ctx.mail_port = int(_shared.get("port") or 587)
            except (TypeError, ValueError):
                ctx.mail_port = 587
            logger.info(
                "[frame-provision] inherited shared relay: %s",
                operator_mail.posture(first_party=True),
            )

    if not ctx.registry_name:
        problems.append("registry_name is required")
    if not ctx.trust_domain:
        problems.append("trust_domain is required")

    if strict and not ctx.public_hostname:
        problems.append(
            "public_hostname is required: it becomes BASE_URL, ALLOWED_ORIGINS and a "
            "WebAuthn rp-id candidate. A frame provisioned without it answers on a host "
            "its own credentials will not validate against."
        )

    # §CLOUDOPMCP 2026-09-04 (B10). NOT fatal — a frame that never provisions a
    # cloud operator is unaffected, and refusing here would break existing
    # standups. But it must never be SILENT: without a public ES URL every
    # operator this frame provisions is handed a docker-internal hostname it
    # cannot resolve from its isolated operator-net, and its reactors come up
    # with ZERO subscriptions. That failure is invisible from the frame side —
    # provisioning reports success and the operator simply never reacts.
    if strict and not ctx.event_store_public_url:
        logger.warning(
            "[frame-provision:%s] event_store_public_url is UNSET — falling back to the "
            "internal name http://%s-event-store:8200. Any cloud operator provisioned by "
            "this frame will be given that URL as its EVENT_STORE_URL and CANNOT resolve "
            "it from operator-net; its reactors will report 0 subscriptions. Set "
            "FRAME_TEST_EVENT_STORE_PUBLIC_URL (or ctx.event_store_public_url) to the "
            "frame's PUBLIC EventStore host before provisioning operators.",
            ctx.registry_name, ctx.registry_name,
        )

    # Mail: all-or-nothing. A half-configured sender renders fine in the UI and
    # bounces at the relay, which is the dishonest-UI class config.py warns about.
    mail_fields = {"mail_server": ctx.mail_server, "mail_address": ctx.mail_address,
                   "mail_token": ctx.mail_token}
    given = {k: v for k, v in mail_fields.items() if v}
    if given and len(given) != len(mail_fields):
        problems.append(
            "mail is half-configured (%s given, %s missing). Provide all of "
            "mail_server/mail_address/mail_token, or none."
            % (",".join(sorted(given)), ",".join(sorted(set(mail_fields) - set(given))))
        )
    if ctx.require_email_verification and not given:
        problems.append(
            "require_email_verification=True but no mail relay was provided. That is the "
            "§OPGUIDE-2 lockout: every self-registered account would be permanently locked "
            "out. Provide a relay, or set require_email_verification=False and gate "
            "registration with invite codes."
        )

    if ctx.push_hostname and ctx.push_hostname.startswith(("http://", "https://")):
        problems.append("push_hostname must be a bare hostname, not a URL")

    # The docker socket alone (a sandbox's tester): the same root, the same typed phrase.
    if ctx.grant_docker_socket and ctx.host_reach_confirmation.strip() != HOST_REACH_CONFIRMATION_PHRASE:
        problems.append(
            "grant_docker_socket=True requires host_reach_confirmation to be exactly "
            f"'{HOST_REACH_CONFIRMATION_PHRASE}' (the docker socket is root on this host)."
        )
    if ctx.grant_docker_socket and not str(ctx.docker_socket_gid or "").isdigit():
        problems.append("grant_docker_socket=True needs docker_socket_gid, the numeric group of /var/run/docker.sock on this host")

    # The dangerous one.
    if ctx.grant_host_reach:
        if ctx.host_reach_confirmation.strip() != HOST_REACH_CONFIRMATION_PHRASE:
            problems.append(
                "grant_host_reach=True requires host_reach_confirmation to be exactly "
                f"'{HOST_REACH_CONFIRMATION_PHRASE}'. "
                + HOST_REACH_WARNING.format(registry_name=ctx.registry_name or "<frame>",
                                            phrase=HOST_REACH_CONFIRMATION_PHRASE)
            )
        else:
            logger.warning(
                "[FRAME-TEST] HOST REACH GRANTED for %s: docker.sock + /host-stack + "
                "/host-nginx-sites will be mounted into the registry. Admin on this frame "
                "can reach the host. Confirmation phrase was supplied.", ctx.registry_name
            )
    elif ctx.host_reach_confirmation and not ctx.grant_docker_socket:
        problems.append(
            "host_reach_confirmation was supplied without grant_host_reach=True. "
            "Refusing to guess which one you meant."
        )

    if problems and strict:
        raise ProvisioningInputError(
            "Frame provisioning refused, %d problem(s):\n  - %s" % (len(problems), "\n  - ".join(problems))
        )
    return problems


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class FrameTestContext:
    """Mutable run context threaded through every stage so rollback can clean
    up whatever was created before failure."""
    ts: int
    registry_name: str = DEFAULT_REGISTRY_NAME
    trust_domain: str = DEFAULT_TRUST_DOMAIN
    stack_dir_host: str = ""
    stack_dir_container: str = ""
    port_registry: int = DEFAULT_PORT_REGISTRY
    port_teg: int = DEFAULT_PORT_TEG
    port_eventstore: int = DEFAULT_PORT_EVENTSTORE
    port_spire_grpc: int = DEFAULT_PORT_SPIRE_GRPC
    port_spire_bundle: int = DEFAULT_PORT_SPIRE_BUNDLE
    port_nginx_fed: int = DEFAULT_PORT_NGINX_FED
    port_ntfy: int = DEFAULT_PORT_NTFY
    port_grafana: int = DEFAULT_PORT_GRAFANA
    port_auditor: int = DEFAULT_PORT_AUDITOR
    auditor_image: str = DEFAULT_AUDITOR_IMAGE
    directory_image: str = DEFAULT_DIRECTORY_IMAGE
    cert_writer_image: str = DEFAULT_CERT_WRITER_IMAGE
    # §SOVKIT secrets, minted per frame in __post_init__
    grafana_admin_password: str = ""
    auditor_admin_token: str = ""
    auditor_ro_password: str = ""
    directory_import_secret: str = ""
    # §SOVKIT proxy markers (agentvault2-85's contract): the Directory index and the event store each trust the
    # X-SSL-Client-* headers ONLY beside a marker header only their own nginx sidecar can set.
    directory_proxy_trust_secret: str = ""
    es_proxy_trust_secret: str = ""
    # §MTLSHOPS G1/G2 (2026-09-15, agentvault2-85's markers): the TEG and the registry count a forwarded client certificate
    # only beside X-TEG-Proxy-Auth / X-Registry-Proxy-Auth equal to these, which only the frame's own terminators send.
    teg_proxy_trust_secret: str = ""
    registry_proxy_trust_secret: str = ""
    # §MTLSHOPS G3 (2026-09-15, agentvault2-85's shape measured on sbx-beta): the frame's Redis answers only its three clients,
    # each an ACL user whose password lives in the 600 env file and only as a SHA-256 in the ACL file (_write_redis_acl).
    redis_registry_password: str = ""
    redis_teg_password: str = ""
    redis_store_password: str = ""
    # §SOVKIT K1 (2026-09-14): the store's SCRAM password at the frame's ledger broker (RP_BOOTSTRAP_USER on the
    # broker, KAFKA_SASL_PASSWORD on the store; nothing else on the frame holds it).
    kafka_es_password: str = ""
    net_name: str = ""
    vol_prefix: str = ""
    # ── 2026-08-01: deployment inputs a real hand-over needs UP FRONT ─────────
    # Modern platforms demand every required input before they provision, rather
    # than producing a half-configured instance someone has to retrofit. These
    # are validated by validate_provisioning_inputs() BEFORE any container runs.
    #   public_hostname  - the frame's public URL host (BASE_URL/ALLOWED_ORIGINS,
    #                      and one of the WebAuthn rp-id candidates)
    #   push_hostname    - public ntfy host, pattern push.<frame>.theprotocol.cloud;
    #                      empty = push stays internal (Web Push still works)
    #   mail_*           - outbound relay. A frame with no relay CANNOT send
    #                      verification mail, which is the §OPGUIDE-2 lockout.
    public_hostname: str = ""
    push_hostname: str = ""
    mail_server: str = ""
    mail_port: int = 587
    mail_address: str = ""
    mail_token: str = ""
    require_email_verification: bool = True
    # first_party=False for any frame whose admin credential is held OUTSIDE this
    # org (the Hetzner frame). Such a frame never inherits the shared relay token
    # (PART 11b) — it either brings its own mail_* or runs on invite codes.
    first_party: bool = True
    # ── HOST REACH — OPT-IN, and never by accident (PART 11b) ────────────────
    # Mounting docker.sock + /host-stack + /host-nginx-sites into the frame's
    # REGISTRY is root on this host for whoever holds that frame's admin
    # credential. It exists only because cloud-operator self-provisioning needs
    # container-create + bind mounts, which IS the escape primitive.
    # Default OFF. Granting it requires typing the confirmation phrase below,
    # because a boolean is too easy to pass by accident from an API call.
    # The SPIRE AGENT keeps its own socket regardless: it needs it for workload
    # attestation, it is a different service block, and it must never be caught
    # by a blanket edit.
    grant_host_reach: bool = False
    host_reach_confirmation: str = ""
    # §TESTBED (2026-09-19): the docker socket ALONE, for a SANDBOX frame whose registry runs the MCP tester against
    # itself (the suite reaches its subject containers by `docker exec`). Root on the host all the same, so it takes the
    # same typed confirmation as host reach; unlike host reach it mounts no stack root and no nginx sites. The standup
    # driver sets it only for posture sandbox. docker_socket_gid is the socket's group on THIS host (the registry runs
    # as uid 1000 and joins that group); empty = not granted.
    grant_docker_socket: bool = False
    docker_socket_gid: str = ""
    # WS3/SF-3 cross-frame federation knobs (added 2026-04-25 for dual-frame
    # lifecycle test). Defaults preserve single-frame back-compat: per-frame
    # internal identity network + per-frame container DNS for handshake URLs.
    # The dual-frame orchestrator overrides these to use a shared identity
    # network ("sandbox_dual_frame_identity") so alpha + beta resolve each
    # other via Docker DNS.
    identity_net_name: str = ""
    identity_net_external: bool = False
    frame_local_bundle_endpoint_url: str = ""
    frame_local_federation_endpoint_url: str = ""
    # 2026-04-25 — Extra peer trust domains to trust for cross-frame mTLS.
    # The compose template's TRUSTED_SPIFFE_DOMAINS env always starts with
    # the local trust domain + sandbox-a.test (legacy chained-test peer).
    # The dual-frame orchestrator extends this with the OTHER frame's trust
    # domain so beta's nginx-federation accepts alpha's SVID and vice versa.
    # Single-frame test leaves this empty (back-compat).
    extra_trusted_spiffe_domains: list = field(default_factory=list)
    # §BATCH7 — the FX peer, so a frame is stood up already pointed at its partner (six env keys); empty = FX off
    fx_peer_slug: str = ""
    fx_peer_currency: str = ""
    fx_peer_es_url: str = ""
    # 🔴 findings row 191 — the PEER frame's @fx_router DID. `_fx_route_hop_execute` reads it as
    # `gd["router_did"]` and makes it the RECEIVER of the FX core swap, so an FX_ROUTE_PEERS entry
    # without it converts into a transfer to nobody. It cannot be derived: it is an agent minted on
    # the OTHER frame, so it is an input (--fx-peer-router-did), exactly like the licence key.
    fx_peer_router_did: str = ""
    admin_password: str = ""
    pg_pass_registry: str = ""
    pg_pass_teg: str = ""
    pg_pass_event_store: str = ""
    secret_key: str = ""
    jwt_secret_key: str = ""
    api_key_secret: str = ""
    teg_admin_api_key: str = ""
    event_store_internal_api_key: str = ""
    # ── Fleet baseline (2026-09-04) ──────────────────────────────────────
    # These were referenced by the compose template but supplied only by the
    # then-UNTRACKED .env.frame-test.tmpl (`.env.*` was gitignore'd; TRACKED as
    # frame-test.env.tmpl since D12 2026-09-05), so the repo
    # could not render a bootable frame on its own. Generated per run here.
    teg_token_signing_key: str = ""       # secure_config: Field(..., min_length=32)
    teg_avtp_system_api_key: str = ""     # secure_config: Field(..., min_length=32)
    mint_proxy_secret: str = ""           # MUST match on registry + TEG
    registry_signing_key_passphrase: str = ""
    two_factor_encryption_key: str = ""   # Fernet key (44 chars)
    federation_health_check_secret: str = ""
    # D12: two more per-run values the templates used to carry as LITERALS.
    federation_internal_secret: str = ""   # FRAME_TEST_FEDERATION_INTERNAL_SECRET overrides (shared HTTP sync)
    sandbox_reset_secret: str = ""         # FRAME_TEST_SANDBOX_RESET_SECRET, else this registry's own
    # Frame identity/economics. FRAME_CURRENCY drives FX self-identification;
    # a wrong value makes a cross-frame egress loop (see cloud_provisioner).
    frame_currency: str = ""
    # §CLOUDOPMCP 2026-09-04 (B10) — the PUBLIC EventStore URL handed to every
    # operator this frame provisions. cloud_provisioner.py:217 reads
    # EVENT_STORE_PUBLIC_URL and stamps it as the operator's EVENT_STORE_URL, and
    # an operator lives on its own isolated operator-net: a docker-internal name
    # cannot resolve there, so its reactors never subscribe. MEASURED end to end —
    # a freshly provisioned operator reported "only 0/19 subscriptions found" with
    # [Reactor:AgentSlashed] WS error against an unreachable host; pointing the
    # frame at its own PUBLIC ES took it straight to a passing subscription check.
    # There is no mechanical derivation from public_hostname: the registry vhost
    # does NOT serve ES paths (sandbox-a.theprotocol.cloud/api/v1/projections/... =
    # 404) and the ES has its own hostname. So it must be supplied, and when it is
    # not we say so loudly rather than hand out a URL that cannot work.
    event_store_public_url: str = ""
    # ⚠ own name FIRST and ALWAYS: a frame absent from its own allowlist
    # answers a genesis-class 403 when funding its satellites.
    extra_fund_origins: list = field(default_factory=list)
    mainframe_display_name: str = ""
    workers_reg: int = DEFAULT_WORKERS_REG
    workers_teg: int = DEFAULT_WORKERS_TEG
    workers_es: int = DEFAULT_WORKERS_ES
    errors: list = field(default_factory=list)

    def finalize_derivations(self):
        """Fill paths/names that depend on other fields. Idempotent."""
        if not self.stack_dir_host:
            self.stack_dir_host = f"{STACK_ROOT}/{self.registry_name}-{self.ts}"
        if not self.stack_dir_container:
            self.stack_dir_container = f"{HOST_STACK_MOUNT}/{self.registry_name}-{self.ts}"
        if not self.net_name:
            # Docker network names must match [a-zA-Z0-9][a-zA-Z0-9_.-]*
            self.net_name = f"{self.registry_name.replace('-', '_')}_network"
        if not self.vol_prefix:
            self.vol_prefix = self.registry_name.replace("-", "_")
        # Identity network — defaults to per-frame internal (back-compat).
        # Dual-frame orchestrator presets to shared name BEFORE calling this.
        if not self.identity_net_name:
            self.identity_net_name = f"{self.net_name}_identity"
        # Bundle/federation endpoint URLs — defaults to per-frame container
        # DNS (resolves on the per-frame internal identity net).
        # SPIRE 1.10 bundle_endpoint serves the SPIFFE JWK set at the root
        # path (`GET /`), not `/.well-known/spiffe/bundle`. Tested empirically
        # against the running container — only `/` returns 200.
        if not self.frame_local_bundle_endpoint_url:
            self.frame_local_bundle_endpoint_url = (
                f"https://{self.registry_name}-spire-server:8443/"
            )
        if not self.frame_local_federation_endpoint_url:
            self.frame_local_federation_endpoint_url = (
                f"https://{self.registry_name}-nginx-federation:8443"
            )
        # Passwords and secrets (fresh per run)
        if not self.admin_password:
            self.admin_password = secrets.token_urlsafe(18)
        for attr in (
            "pg_pass_registry", "pg_pass_teg", "pg_pass_event_store",
            "secret_key", "jwt_secret_key", "api_key_secret",
            "teg_admin_api_key", "event_store_internal_api_key",
            # Fleet baseline — 64 hex chars each, comfortably over the
            # min_length=32 that secure_config enforces on the two TEG keys.
            "teg_token_signing_key", "teg_avtp_system_api_key",
            "mint_proxy_secret", "federation_health_check_secret",
            "registry_signing_key_passphrase",
            # §SOVKIT: the kit's own secrets (grafana admin, the auditor's admin token, the read-only DB role
            # the auditor uses, the Directory's import-time dummy)
            "grafana_admin_password", "auditor_admin_token", "auditor_ro_password", "directory_import_secret",
            "directory_proxy_trust_secret", "es_proxy_trust_secret",
            "teg_proxy_trust_secret", "registry_proxy_trust_secret",   # §MTLSHOPS G1/G2: the terminators' markers
            "redis_registry_password", "redis_teg_password", "redis_store_password",   # §MTLSHOPS G3: the Redis ACL users
            "kafka_es_password",   # §SOVKIT K1: the ledger broker's SCRAM password (hex: safe in RP_BOOTSTRAP_USER)
        ):
            if not getattr(self, attr):
                setattr(self, attr, secrets.token_hex(32))
        # Fernet key: urlsafe base64 of exactly 32 bytes (44 chars). Generated
        # without importing `cryptography` — this IS the format Fernet expects,
        # and a wrong shape makes every 2FA enrolment fail at decrypt time.
        if not self.two_factor_encryption_key:
            self.two_factor_encryption_key = base64.urlsafe_b64encode(
                secrets.token_bytes(32)
            ).decode()
        # D12: a frame gets its own federation-internal secret unless the operator names one to
        # share (HTTP federation sync between two frames it also provisions).
        if not self.federation_internal_secret:
            self.federation_internal_secret = (
                os.getenv("FRAME_TEST_FEDERATION_INTERNAL_SECRET", "") or secrets.token_hex(32)
            )
        # D12: the API tester's reset rail compares this against the CALLER's value, so a frame
        # provisioned by this registry takes this registry's own secret by default — the old
        # template literal matched nobody (measured 2026-09-05: it differed from registry-a's).
        if not self.sandbox_reset_secret:
            self.sandbox_reset_secret = (
                os.getenv("FRAME_TEST_SANDBOX_RESET_SECRET", "")
                or os.getenv("SANDBOX_RESET_SECRET", "")
                or secrets.token_hex(32)
            )
        if not self.frame_currency:
            self.frame_currency = (
                os.getenv("FRAME_TEST_FRAME_CURRENCY", "AVT") or "AVT"
            ).strip().upper()
        if not self.event_store_public_url:
            self.event_store_public_url = (
                os.getenv("FRAME_TEST_EVENT_STORE_PUBLIC_URL", "") or ""
            ).strip()
        if not self.mainframe_display_name:
            self.mainframe_display_name = self.registry_name


@dataclass
class FrameTestProvisionResult:
    containers_started: int
    registry_port: int
    teg_port: int
    eventstore_port: int
    nginx_fed_port: int
    admin_email: str
    admin_password: str
    trust_domain: str
    stack_dir: str
    network_name: str


@dataclass
class FrameTestTeardownResult:
    containers_removed: int
    volumes_removed: int
    networks_removed: int
    stack_dir_removed: bool


# ── Docker-py SDK helpers ────────────────────────────────────────────────

def _docker_client():
    import docker as docker_sdk
    return docker_sdk.from_env()


def _run_docker_cli(
    command: str,
    *,
    working_dir: str,
    stack_dir_host: str,
    timeout: int = 240,
) -> tuple[int, str]:
    """Run a `docker compose ...` style command from inside a short-lived
    docker:cli container that has the host Docker socket + the generated stack
    directory mounted. Returns (exit_code, output_text)."""
    client = _docker_client()
    try:
        container = client.containers.run(
            "docker:cli",
            command=command,
            volumes={
                "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                stack_dir_host: {"bind": stack_dir_host, "mode": "rw"},
            },
            working_dir=working_dir,
            detach=True,
        )
        result = container.wait(timeout=timeout)
        out = container.logs(stdout=True, stderr=True).decode(errors="replace")
        try:
            container.remove(force=True)
        except Exception:
            pass
        return int(result.get("StatusCode", -1)), out
    except Exception as e:
        logger.exception(f"[FRAME-TEST] docker:cli run failed: {command}")
        return -1, f"docker:cli exception: {e}"


def _run_openssl(script: str, mount_dir_host: str, timeout: int = 60) -> tuple[int, str]:
    """Run an openssl script inside alpine/openssl with the generated cert
    directory mounted. Used to create x509pop CA + agent attestation cert."""
    client = _docker_client()
    try:
        container = client.containers.run(
            "alpine/openssl:latest",
            command=["sh", "-c", script],
            volumes={
                mount_dir_host: {"bind": "/work", "mode": "rw"},
            },
            working_dir="/work",
            entrypoint="",  # override alpine/openssl's default entrypoint
            detach=True,
        )
        result = container.wait(timeout=timeout)
        out = container.logs(stdout=True, stderr=True).decode(errors="replace")
        try:
            container.remove(force=True)
        except Exception:
            pass
        return int(result.get("StatusCode", -1)), out
    except Exception as e:
        logger.exception("[FRAME-TEST] openssl run failed")
        return -1, f"openssl exception: {e}"


# ── Template rendering ────────────────────────────────────────────────────

def _copy_kit_files(ctx: "FrameTestContext") -> tuple:
    """§SOVKIT (2026-09-14): copy the kit's non-rendered files into <stack>/kit/. Every source is named; a missing
    one refuses the standup rather than shipping a frame whose Prometheus has no rules or whose OPA has no policies
    (a policy directory that is empty is an OPA that answers `undefined` to every question, which reads as allow
    in shadow and as deny in enforce: the class where a gate that cannot fail wears a safety costume)."""
    import glob as _glob
    kit_src = os.path.join(FRAME_TEST_TEMPLATE_DIR, "kit")
    policies_src = os.path.normpath(os.path.join(FRAME_TEST_TEMPLATE_DIR, "..", "..", "identity-fabric", "policies"))
    kit_dst = os.path.join(ctx.stack_dir_container, "kit")
    copies = [
        (os.path.join(kit_src, "prometheus", "rules"), os.path.join(kit_dst, "prometheus", "rules"), "*.yml", 1),
        (os.path.join(kit_src, "alertmanager"), os.path.join(kit_dst, "alertmanager"), "alertmanager.yml", 1),
        (os.path.join(kit_src, "grafana", "provisioning", "dashboards"), os.path.join(kit_dst, "grafana", "provisioning", "dashboards"), "dashboards.yml", 1),
        (os.path.join(kit_src, "grafana", "provisioning", "dashboards", "json", "Frames"), os.path.join(kit_dst, "grafana", "provisioning", "dashboards", "json", "Frames"), "*.json", 1),
        (policies_src, os.path.join(kit_dst, "opa", "policies"), "*.rego", 5),
        # §MTLSHOPS T3 (2026-09-15): the data services' TLS: pg-tls-sync.sh, redis-tls-reload.sh and tls-client-sync.sh, and
        # Postgres's hba. Static files the containers read through a read-only bind of <stack>/kit/data-tls.
        (os.path.join(kit_src, "data-tls"), os.path.join(kit_dst, "data-tls"), "*.sh", 3),
        (os.path.join(kit_src, "data-tls"), os.path.join(kit_dst, "data-tls"), "pg_hba.conf", 1),
    ]
    for src_dir, dst_dir, pattern, floor in copies:
        files = sorted(_glob.glob(os.path.join(src_dir, pattern)))
        if len(files) < floor:
            return False, f"kit source incomplete: {src_dir}/{pattern} holds {len(files)} file(s), want >= {floor}"
        os.makedirs(dst_dir, exist_ok=True)
        for f in files:
            shutil.copy(f, os.path.join(dst_dir, os.path.basename(f)))
            os.chmod(os.path.join(dst_dir, os.path.basename(f)), 0o644)
    # the files the containers read must be readable by their own uids (prometheus nobody, grafana 472): this
    # tree's umask writes 750/640, which is how a bind mount reads as "permission denied" at boot
    for root, dirs, files in os.walk(kit_dst):
        os.chmod(root, 0o755)
        for f in files:
            os.chmod(os.path.join(root, f), 0o644)
    os.makedirs(os.path.join(kit_dst, "auditor", "frames"), exist_ok=True)
    os.chmod(os.path.join(kit_dst, "auditor", "frames"), 0o755)
    return True, "ok"


# §MTLSHOPS G3 (2026-09-15, agentvault2-85's shape, measured on sbx-beta with Redis 7.4.10). The frame's Redis had no
# password and protected mode off while it holds the leader locks, the limiter and the channels the websockets broadcast.
# Its three clients (the registry, db 0; the event store, db 1; the TEG, db 2) each become an ACL user; the default user
# keeps only PING, for the compose healthcheck. Named residue: ACL cannot pin a user to a DB and the keys carry no app
# prefix, so there is no key isolation between the three.
REDIS_ACL_UID = 999   # redis:7-alpine's redis user, the uid its docker-entrypoint.sh drops to (setpriv --reuid redis)
REDIS_APP_RULE = ("~* &* +@all -flushall -flushdb -config -debug -shutdown -acl -monitor -replicaof -slaveof -module -save "
                  "-bgsave -bgrewriteaof -failover -cluster -migrate -restore -sync -psync -swapdb")


def render_redis_acl(passwords: dict) -> str:
    """The frame's Redis ACL file. `passwords` maps each app user to its plaintext; the file carries only `#<sha256>`, so the
    plaintext stays in the 600 env file."""
    lines = ["user default on nopass resetkeys resetchannels -@all +ping"]
    for user in ("registry", "store", "teg"):
        secret = passwords[user]
        if len(secret) < 32:
            raise ValueError(f"the {user} Redis password is shorter than 32 characters (the value is not printed)")
        lines.append(f"user {user} on #{hashlib.sha256(secret.encode()).hexdigest()} {REDIS_APP_RULE}")
    return "\n".join(lines) + "\n"


def _write_redis_acl(ctx: "FrameTestContext") -> tuple:
    """Writes <stack>/redis/users.acl at 0600, owned by the redis image's uid. Redis reads it after dropping root, and a
    file it cannot read stops the server at boot, so a failed write or chown refuses the render instead of warning."""
    path = os.path.join(ctx.stack_dir_container, "redis", "users.acl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.chmod(os.path.dirname(path), 0o755)
        body = render_redis_acl({"registry": ctx.redis_registry_password, "store": ctx.redis_store_password,
                                 "teg": ctx.redis_teg_password})
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.chmod(path, 0o600)
        os.chown(path, REDIS_ACL_UID, REDIS_ACL_UID)
    except (OSError, ValueError) as e:
        return False, f"redis ACL file {path}: {e}"
    return True, ""


def _render_template(tmpl_path: str, out_path: str, values: dict) -> None:
    """Replace {{KEY}} placeholders in a template file + write to out_path."""
    with open(tmpl_path) as f:
        text = f.read()
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    with open(out_path, "w") as f:
        f.write(text)


def _render_host_mounts(ctx: FrameTestContext) -> str:
    """The registry's host-reach mounts, or nothing at all.

    Default (hardened) returns a single comment line so the rendered compose
    explains its own absence. §HETZNERLOCK removed these from the live Hetzner
    frame by hand; before this, a re-provision silently put them back
    (CLAUDE.md PART 11b rule 2). The SPIRE AGENT keeps its socket in its own
    service block and is deliberately not touched here.
    """
    if not ctx.grant_host_reach and ctx.grant_docker_socket:
        return ("# §TESTBED: a SANDBOX's tester reaches its subject containers by docker exec: the socket, and\n"
                "      # nothing else of the host (no /host-stack, no nginx sites). Root on this host, granted on purpose.\n"
                "      - /var/run/docker.sock:/var/run/docker.sock:ro")
    if not ctx.grant_host_reach:
        return ("# host reach NOT granted (default): no docker.sock, no /host-stack,\n"
                "      # no /host-nginx-sites. Cloud-operator self-provisioning is therefore\n"
                "      # unavailable on this frame, by design.")
    return ("- /var/run/docker.sock:/var/run/docker.sock:ro\n"
            "      - /opt/theprotocol/stack:/host-stack\n"
            "      - /etc/nginx/sites-enabled:/host-nginx-sites")


def _runner_socket_gid() -> str:
    return os.getenv("FRAME_RUNNER_SOCKET_GID", "988")


def _registry_docker_group(ctx: FrameTestContext) -> str:
    """The group_add line for the docker socket's group, or a comment. §NIGHTPROV (2026-09-27): on this host the runner
    socket's gid defaults to 988, which IS the docker socket's group, so a frame given the socket (the nightly pair's
    --tester-self) rendered `- "988"` twice and `docker compose config` refused the stack ("group_add items at 0 and 1 are
    equal", measured on nt260927x1a). A group already joined as the runner socket's is joined once."""
    gid = str(ctx.docker_socket_gid or "")
    if not ((ctx.grant_docker_socket or ctx.grant_host_reach) and gid.isdigit()):
        return "# no docker socket group (the socket is not mounted)"
    if gid == _runner_socket_gid():
        return f"# the docker socket's group {gid} is already joined above (the runner socket's gid on this host)"
    return f'- "{gid}"   # the docker socket\'s group (sandbox tester, §TESTBED)'


def _template_values(ctx: FrameTestContext) -> dict:
    # IDENTITY_NET_DEFINITION: line that goes inside the identity network's
    # YAML block. For external (dual-frame) the network is pre-created by the
    # orchestrator and referenced as external; for single-frame the compose
    # creates it as a fresh bridge. The single-line value preserves YAML
    # indentation when the placeholder is replaced verbatim.
    identity_net_definition = (
        "external: true" if ctx.identity_net_external else "driver: bridge"
    )
    extra_trusted = ""
    if ctx.extra_trusted_spiffe_domains:
        extra_trusted = "," + ",".join(ctx.extra_trusted_spiffe_domains)
    return {
        "REGISTRY_NAME": ctx.registry_name,
        "TRUST_DOMAIN": ctx.trust_domain,
        "TS": ctx.ts,
        "STACK_DIR": ctx.stack_dir_host,
        "VOL_PREFIX": ctx.vol_prefix,
        "NET_NAME": ctx.net_name,
        "IDENTITY_NET_NAME": ctx.identity_net_name,
        "IDENTITY_NET_DEFINITION": identity_net_definition,
        "FRAME_LOCAL_BUNDLE_ENDPOINT_URL": ctx.frame_local_bundle_endpoint_url,
        "FRAME_LOCAL_FEDERATION_ENDPOINT_URL": ctx.frame_local_federation_endpoint_url,
        "EXTRA_TRUSTED_SPIFFE_DOMAINS": extra_trusted,
        "FX_ENABLED": "true" if ctx.fx_peer_slug else "false",
        # 🔴 findings row 191 — THREE DEFECTS IN ONE LITERAL, each of which hid the next.
        #   registry_id was "" → the GS branch refused with "GD peer ␣ not ACTIVE on this frame",
        #     a message that could not name the peer it was looking for because there wasn't one.
        #   url was http://<slug>-registry:8000 → the delegate then talks PLAIN HTTP, so mTLS
        #     (federation auth Mode 1) cannot happen and it falls to Mode 2, presenting THIS
        #     cluster's internal secret to a SOVEREIGN peer that has a different one → 401
        #     "Invalid federation secret". Leaving `url` out entirely is the fix and the rule:
        #     `gd.get("url") or gd_peer.base_url` — and the peer ROW carries the authoritative
        #     mTLS federation address (CLAUDE.md: never a hardcoded gateway url).
        #   router_did was absent → the FX core swap would have had no receiver.
        # Measured end to end on EU/ASIA: amsterdam(ECU) → hochiminh(ACU) settled, 9.844672 ACU
        # credited, Δ=0.0 on both ledgers, only after all three were right.
        "FX_ROUTE_PEERS": (json.dumps([{
            "currency": ctx.fx_peer_currency,
            "registry_id": ctx.fx_peer_slug,
            "teg_id": f"teg-layer-{ctx.fx_peer_slug}",
            "router_did": ctx.fx_peer_router_did,
        }]) if ctx.fx_peer_slug else "[]"),
        "TEG_SIDECAR_MAP": (json.dumps({f"teg-layer-{ctx.fx_peer_slug}": f"{ctx.fx_peer_slug}-nginx-teg",
                                        f"registry-{ctx.fx_peer_slug}": f"{ctx.fx_peer_slug}-nginx-teg"}) if ctx.fx_peer_slug else "{}"),
        "FX_RESERVE_KEEPER_ENABLED": "true" if ctx.fx_peer_slug else "false",
        "EVENT_STORE_B_URL": ctx.fx_peer_es_url if ctx.fx_peer_slug else "",
        "PORT_REGISTRY": ctx.port_registry,
        "PORT_TEG": ctx.port_teg,
        "PORT_EVENTSTORE": ctx.port_eventstore,
        "PORT_SPIRE_GRPC": ctx.port_spire_grpc,
        "PORT_SPIRE_BUNDLE": ctx.port_spire_bundle,
        "PORT_NGINX_FED": ctx.port_nginx_fed,
        "PORT_NTFY": ctx.port_ntfy,
        # §SOVKIT (2026-09-14): the kit
        "PORT_GRAFANA": ctx.port_grafana,
        "PORT_AUDITOR": ctx.port_auditor,
        "AUDITOR_IMAGE": ctx.auditor_image,
        "DIRECTORY_IMAGE": ctx.directory_image,
        "CERT_WRITER_IMAGE": ctx.cert_writer_image,
        # §HELLOFRAME: the gid of the frame runner's socket group the registry joins to reach the operator socket
        # (this host's docker-socket group 988 by default; a foreign host names its own through FRAME_RUNNER_SOCKET_GID)
        "RUNNER_SOCKET_GID": _runner_socket_gid(),
        # the directory holding the runner's OPERATOR socket, mounted into the registry; an instance-scoped runner
        # (a second runner beside the host's own, §HELLOFRAME) names its own
        "RUNNER_OPERATOR_SOCKET_DIR": os.getenv("FRAME_RUNNER_OPERATOR_SOCKET_DIR", "/run/theprotocol/operator"),
        # §HELLOFRAME: the operator templates the registry packages bundles from, at the checkout's root on THIS host
        # (the compose carried the absolute path of this checkout until 2026-09-18)
        "NGINX_TEMPLATES_DIR": f"{REPO_ROOT}/scripts/distribution/nginx-templates",
        "GRAFANA_ADMIN_PASSWORD": ctx.grafana_admin_password,
        "AUDITOR_ADMIN_TOKEN": ctx.auditor_admin_token,
        "DIRECTORY_IMPORT_SECRET": ctx.directory_import_secret,
        "DIRECTORY_PROXY_TRUST_SECRET": ctx.directory_proxy_trust_secret,
        "ES_PROXY_TRUST_SECRET": ctx.es_proxy_trust_secret,
        "TEG_PROXY_TRUST_SECRET": ctx.teg_proxy_trust_secret,             # §MTLSHOPS G1
        "REGISTRY_PROXY_TRUST_SECRET": ctx.registry_proxy_trust_secret,   # §MTLSHOPS G2
        "REDIS_REGISTRY_PASSWORD": ctx.redis_registry_password,           # §MTLSHOPS G3
        "REDIS_TEG_PASSWORD": ctx.redis_teg_password,
        "REDIS_STORE_PASSWORD": ctx.redis_store_password,
        "KAFKA_ES_PASSWORD": ctx.kafka_es_password,   # §SOVKIT K1
        "AUDITOR_RO_PASSWORD": ctx.auditor_ro_password,
        # Host reach is rendered as a BLOCK, so the hardened default emits no
        # mount lines at all rather than commented-out ones a later edit could
        # revive. The spire-agent's own socket lives in its own service block
        # and is untouched by this.
        "REGISTRY_HOST_MOUNTS": _render_host_mounts(ctx),
        # the docker socket's group, joined only when the socket is mounted (a sandbox's tester, §TESTBED)
        "REGISTRY_DOCKER_GROUP": _registry_docker_group(ctx),
        "PUBLIC_HOSTNAME": ctx.public_hostname or f"localhost:{ctx.port_registry}",
        "PUBLIC_BASE_URL": (
            f"https://{ctx.public_hostname}" if ctx.public_hostname
            else f"http://localhost:{ctx.port_registry}"
        ),
        # D12: a VALUE, not a rendered line. Empty = not publicly exposed on this frame
        # (config.py reads "" exactly as it read the key being absent).
        "PUSH_NTFY_PUBLIC_URL": f"https://{ctx.push_hostname}" if ctx.push_hostname else "",
        "FEDERATION_INTERNAL_SECRET": ctx.federation_internal_secret,
        "SANDBOX_RESET_SECRET": ctx.sandbox_reset_secret,
        "REQUIRE_EMAIL_VERIFICATION": "true" if ctx.require_email_verification else "false",
        "WORKERS_REG": ctx.workers_reg,
        "WORKERS_TEG": ctx.workers_teg,
        "WORKERS_ES": ctx.workers_es,
        # §DBPOOL: the registry's pool per worker, sized from WORKERS_REG (registry_pool)
        "DB_POOL_SIZE": registry_pool(ctx.workers_reg)[0],
        "DB_MAX_OVERFLOW": registry_pool(ctx.workers_reg)[1],
        "PG_PASS_REGISTRY": ctx.pg_pass_registry,
        "PG_PASS_TEG": ctx.pg_pass_teg,
        "PG_PASS_EVENT_STORE": ctx.pg_pass_event_store,
        "SECRET_KEY": ctx.secret_key,
        "JWT_SECRET_KEY": ctx.jwt_secret_key,
        "API_KEY_SECRET": ctx.api_key_secret,
        "TEG_ADMIN_API_KEY": ctx.teg_admin_api_key,
        "EVENT_STORE_INTERNAL_API_KEY": ctx.event_store_internal_api_key,
        "ADMIN_PASSWORD": ctx.admin_password,
        # ── Fleet baseline (2026-09-04) ──────────────────────────────────
        "TEG_TOKEN_SIGNING_KEY": ctx.teg_token_signing_key,
        "TEG_AVTP_SYSTEM_API_KEY": ctx.teg_avtp_system_api_key,
        "MINT_PROXY_SECRET": ctx.mint_proxy_secret,
        "REGISTRY_SIGNING_KEY_PASSPHRASE": ctx.registry_signing_key_passphrase,
        "TWO_FACTOR_ENCRYPTION_KEY": ctx.two_factor_encryption_key,
        "FEDERATION_HEALTH_CHECK_SECRET": ctx.federation_health_check_secret,
        "FRAME_CURRENCY": ctx.frame_currency,
        # B10: supplied value wins; otherwise the old internal name, which is
        # preserved so a frame that never provisions an operator is unchanged.
        # `validate_frame_request` warns when this falls back.
        "EVENT_STORE_PUBLIC_URL": (
            ctx.event_store_public_url
            or f"http://{ctx.registry_name}-event-store:8200"
        ),
        # §MONEY-R50: rendered on the REGISTRY service (the guard in routers/teg_integration.py
        # is the only reader) through the guard's OWN slug rule, under BOTH names the frame may
        # carry as REGISTRY_NAME (container name + display name); own slug ALWAYS first — a frame
        # absent from its own allowlist cannot fund its satellites. The dual-frame orchestrator
        # adds the peer via extra_fund_origins.
        "CROSS_TEG_FUND_ORIGINS": fund_origin_allowlist_value(
            ctx.registry_name, ctx.mainframe_display_name, ctx.extra_fund_origins
        ),
        # `mainframe_gate.py` splits this on "," and matches REGISTRY_NAME
        # against it; the display name is carried too because the gate is also
        # consulted with the human-facing name on some rails.
        "MAINFRAME_REGISTRY_NAMES": ",".join(
            dict.fromkeys([ctx.registry_name, ctx.mainframe_display_name])
        ),
    }


# ── Cert generation ──────────────────────────────────────────────────────

# §MCPTEST30 (V0550): the x509pop attestation CA and agent certificate were signed for 30 days, a lifetime written for
# frames torn down after a test. Long-lived frames were stood up with it: measured 2026-10-02 (agentvault2-15 found it),
# sbx-alpha's and sbx-beta's expire 2026-10-03, EU's and ASIA's 2026-10-07. A SPIRE agent that must attest again after
# that (a recreate, a restart past its SVID: the frame agents keep no /opt/spire/data volume) is refused, and its
# frame's services lose their SVIDs. New frames get a CA for ten years and an agent certificate for two (the operators'
# lifetime), each overridable. Frames already standing need their certificates re-issued: an operation, not this code.
def x509pop_cert_days() -> tuple[int, int]:
    """(the CA's days, the agent certificate's days); the CA always outlives the certificate it signs."""
    def _days(var: str, default: int) -> int:
        try:
            v = int(os.getenv(var, "") or default)
        except ValueError:
            v = default
        return max(1, v)
    ca, agent = _days("FRAME_X509POP_CA_DAYS", 3650), _days("FRAME_X509POP_AGENT_DAYS", 730)
    return max(ca, agent), agent


def generate_spire_x509pop_certs(ctx: FrameTestContext) -> tuple[bool, str]:
    """Generate a self-signed x509pop CA + agent attestation cert into
    <stack_dir_host>/x509pop-certs/. Idempotent — overwrites existing files.
    Returns (ok, detail)."""
    certs_host = os.path.join(ctx.stack_dir_host, "x509pop-certs")
    certs_container = os.path.join(ctx.stack_dir_container, "x509pop-certs")
    os.makedirs(certs_container, exist_ok=True)
    os.chmod(certs_container, 0o755)

    # Single shell script executed inside alpine/openssl. Produces:
    #   attestation-ca.key / attestation-ca.crt (CA with keyCertSign)
    #   agent-attestation.key / agent-attestation.crt (signed by CA,
    #   with digitalSignature + keyEncipherment + clientAuth/serverAuth)
    # Paths are in /work which binds to <stack_dir_host>/x509pop-certs.
    # The agent-attestation ext set matches frame-b's existing cert so
    # SPIRE's x509pop NodeAttestor accepts it.
    ca_days, agent_days = x509pop_cert_days()
    script = (
        "set -e && cd /work && "
        "cat > agent-ext.cnf <<EOF\n"
        "basicConstraints = critical,CA:FALSE\n"
        "keyUsage = critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage = clientAuth,serverAuth\n"
        "EOF\n"
        "openssl genrsa -out attestation-ca.key 2048 && "
        f"openssl req -new -x509 -sha256 -days {ca_days} "
        "-key attestation-ca.key "
        f"-subj \"/CN={ctx.registry_name}-attestation-ca\" "
        "-out attestation-ca.crt && "
        "openssl genrsa -out agent-attestation.key 2048 && "
        "openssl req -new -sha256 "
        "-key agent-attestation.key "
        f"-subj \"/CN={ctx.registry_name}-agent\" "
        "-out agent-attestation.csr && "
        "openssl x509 -req -in agent-attestation.csr "
        "-CA attestation-ca.crt -CAkey attestation-ca.key -CAcreateserial "
        "-extfile agent-ext.cnf "
        f"-out agent-attestation.crt -days {agent_days} -sha256 && "
        "rm -f agent-attestation.csr attestation-ca.srl agent-ext.cnf && "
        # Sandbox-only: files must be world-readable so registry (uid=1000)
        # can load the CA from the read-only mount. chmod 644 for .key is
        # tolerable here because the frame + CA are destroyed at test teardown.
        "chmod 644 *.crt *.key && "
        "sync && ls -la /work"
    )
    rc, out = _run_openssl(script, mount_dir_host=certs_host, timeout=90)
    if rc != 0:
        return False, f"openssl exit={rc}; output={out[-500:]}"
    # Verify files exist
    required = [
        "attestation-ca.crt", "attestation-ca.key",
        "agent-attestation.crt", "agent-attestation.key",
    ]
    for fname in required:
        p = os.path.join(certs_container, fname)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            return False, f"missing/empty cert file: {fname}"
    return True, f"4 certs generated under {certs_host}"


# ── Template writing ─────────────────────────────────────────────────────

def write_stack_files(ctx: FrameTestContext) -> tuple[bool, str]:
    """Render compose + env + 2 SPIRE confs + 3 nginx confs (federation, TEG, EventStore)
    + copy nginx-entrypoint.sh into the generated stack dir."""
    # Refuse BEFORE the first directory exists. Everything after this point
    # creates state someone has to clean up, and a frame that is missing a
    # required input is not a frame that can be handed to anyone.
    validate_provisioning_inputs(ctx)
    os.makedirs(ctx.stack_dir_container, exist_ok=True)
    values = _template_values(ctx)

    mapping = [
        ("docker-compose.frame-test.yml.tmpl", "docker-compose.frame-test.yml"),
        # D12 (2026-09-05): the env template is TRACKED under a name `.env.*` does not
        # gitignore; it renders to the frame's own .env.frame-test (values), while the
        # compose template carries topology only (`${FT_...}` names).
        ("frame-test.env.tmpl", ".env.frame-test"),
        ("server.conf.tmpl", "server.conf"),
        ("agent.conf.tmpl", "agent.conf"),
        ("nginx-federation-frame-test.conf.tmpl", "nginx-federation-frame-test.conf"),
        # §XFRAMETEG (2026-09-04) — the frame's TEG mTLS sidecar. A PEER FRAME's
        # registry dials it for `/api/v1/admin/fx/reserve` under FX pool mode;
        # without the service that read fell through to the peer's REGISTRY vhost
        # and 404'd, so every cross-frame transfer answered 503.
        ("nginx-teg-frame-test.conf.tmpl", "nginx-teg-frame-test.conf"),
        # §MTLSGAP (2026-09-08) — the frame's EventStore mTLS sidecar. This template rendered a
        # federation gateway and a TEG gateway and NO ES equivalent, so no frame it ever built
        # had one and every registry wrote to its own ledger over plain http while the other two
        # rails were `ssl_verify_client on`. Stands up ALONGSIDE plain http; moving the writers
        # is a separate deliberate step.
        ("nginx-event-store-frame-test.conf.tmpl", "nginx-event-store-frame-test.conf"),
        # §SOVKIT (2026-09-14) — the frame's own Directory read leg, Prometheus and Grafana datasource
        ("nginx-directory-frame-test.conf.tmpl", "nginx-directory-frame-test.conf"),
        # §MTLSHOPS T2 (S4, 2026-09-15): the host edge, the only container that publishes an app's loopback port (to its socket)
        ("nginx-edge-frame-test.conf.tmpl", "nginx-edge-frame-test.conf"),
        # §MTLSHOPS T2 (S4, 2026-09-15): the registry's mTLS publish lane to ntfy's socket
        ("nginx-ntfy-frame-test.conf.tmpl", "nginx-ntfy-frame-test.conf"),
        # §MTLSHOPS T2 (S4, 2026-09-15): Prometheus's mTLS scrape lane to the auditor's socket
        ("nginx-auditor-frame-test.conf.tmpl", "nginx-auditor-frame-test.conf"),
        ("kit/prometheus/prometheus.yml.tmpl", "kit/prometheus/prometheus.yml"),
        ("kit/grafana/provisioning/datasources/prometheus.yml.tmpl", "kit/grafana/provisioning/datasources/prometheus.yml"),
        # §MTLSHOPS T2 (2026-09-15): the kit on its own SVID: OPA's authorization module (bound to this trust domain),
        # Prometheus and Alertmanager's TLS server configs (client_allowed_sans) and their healthchecks' clients, and
        # Grafana's egress to Prometheus.
        ("kit/opa/system_authz.rego.tmpl", "kit/opa/policies/system_authz.rego"),
        ("kit/prometheus/web.yml.tmpl", "kit/prometheus/web.yml"),
        ("kit/prometheus/client.yml.tmpl", "kit/prometheus/client.yml"),
        ("kit/alertmanager/web.yml.tmpl", "kit/alertmanager/web.yml"),
        ("kit/alertmanager/client.yml.tmpl", "kit/alertmanager/client.yml"),
        ("kit/grafana/egress.conf.tmpl", "kit/grafana/egress.conf"),
    ]
    for src_name, dest_name in mapping:
        src = os.path.join(FRAME_TEST_TEMPLATE_DIR, src_name)
        dest = os.path.join(ctx.stack_dir_container, dest_name)
        if not os.path.exists(src):
            return False, f"template missing: {src}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        _render_template(src, dest, values)
    # §SOVKIT — the kit's non-template files: the frame rules and Alertmanager routes, Grafana's dashboard
    # provider and dashboards, the OPA policies (identity-fabric/policies, beside the templates in every
    # checkout and in the export), and the directory the auditor's frames file lands in (the driver writes it).
    ok, why = _copy_kit_files(ctx)
    if not ok:
        return False, why
    # §MTLSHOPS G3: the ACL file the redis service mounts read-only (SHA-256 hashes only, owned by the image's redis uid).
    ok, why = _write_redis_acl(ctx)
    if not ok:
        return False, why

    # Copy nginx-entrypoint.sh (used by the nginx-federation container)
    nginx_entrypoint_src = f"{REPO_ROOT}/nginx/nginx-entrypoint.sh"
    nginx_entrypoint_dest = os.path.join(ctx.stack_dir_container, "nginx-entrypoint.sh")
    try:
        shutil.copy(nginx_entrypoint_src, nginx_entrypoint_dest)
        os.chmod(nginx_entrypoint_dest, 0o755)
    except Exception as e:
        return False, f"nginx-entrypoint.sh copy failed: {e}"

    # Pre-create operator-bundles dir with world-writable perms so the
    # registry (uid=1000) can write operator bundles into it. Named volumes
    # inherit root:root ownership which blocks the uid=1000 write path.
    bundles_dir = os.path.join(ctx.stack_dir_container, "operator-bundles")
    try:
        os.makedirs(bundles_dir, exist_ok=True)
        os.chmod(bundles_dir, 0o777)
    except Exception as e:
        return False, f"operator-bundles dir setup failed: {e}"

    return True, (
        f"7 templates rendered + nginx-entrypoint.sh + bundles dir "
        f"into {ctx.stack_dir_host}"
    )


# ── Provisioning (bring up the frame) ────────────────────────────────────

def provision_frame_test(ctx: FrameTestContext, timeout_seconds: int = 240) -> FrameTestProvisionResult:
    """Bring up the ephemeral test frame. Assumes write_stack_files() and
    generate_spire_x509pop_certs() have already run successfully."""
    ctx.finalize_derivations()

    compose_cmd = (
        "docker compose -f docker-compose.frame-test.yml "
        "--env-file .env.frame-test up -d"
    )
    rc, out = _run_docker_cli(
        compose_cmd,
        working_dir=ctx.stack_dir_host,
        stack_dir_host=ctx.stack_dir_host,
        timeout=timeout_seconds,
    )
    if rc != 0:
        logger.error(f"[FRAME-TEST] compose up failed rc={rc}\n{out[-1500:]}")
        raise RuntimeError(f"frame-test compose up failed rc={rc}: {out[-500:]}")

    # Under host load, docker compose up can leave a few containers in "Created"
    # state despite returning exit 0. Nudge them to start before we health-poll.
    # (Mirror of the Phase 12 sandbox-alpha quirk in SESSION_LOG_2026-04-22_PHASE12.md.)
    client = _docker_client()
    try:
        nudged = 0
        for c in client.containers.list(all=True, ignore_removed=True):
            if c.name.startswith(f"{ctx.registry_name}-") and c.status == "created":
                try:
                    c.start()
                    nudged += 1
                except Exception as e:
                    logger.warning(f"[FRAME-TEST] nudge start {c.name}: {e}")
        if nudged:
            logger.info(f"[FRAME-TEST] nudged {nudged} Created containers to start")
            time.sleep(3)  # let them catch up before health poll begins
    except Exception as e:
        logger.warning(f"[FRAME-TEST] nudge loop: {e}")

    # Health-poll the registry
    containers_started = 0
    reg_name = f"{ctx.registry_name}-registry"
    for i in range(36):  # 36 * 5 = 180s cap
        time.sleep(5)
        try:
            c = client.containers.get(reg_name)
            health = (c.attrs.get("State", {}).get("Health", {}) or {}).get("Status", "")
            if health == "healthy":
                containers_started = 23  # §SOVKIT: 16 + the kit's seven (a floor; the driver counts the running ones)
                logger.info(f"[FRAME-TEST] {reg_name} healthy after {(i+1)*5}s")
                break
        except Exception as e:
            logger.debug(f"[FRAME-TEST] health poll {i+1}/36: {e}")
    else:
        logger.warning(f"[FRAME-TEST] {reg_name} not healthy after 180s — continuing with partial")
        containers_started = -1

    # Capture first-boot admin credentials from registry logs. The
    # operator_seed module in the registry container emits its own random
    # password and an email computed from REGISTRY_NAME slug — our
    # .env ADMIN_EMAIL/PASSWORD values are NOT honored by operator_seed.
    # Mirror of cloud_provisioner.py:570-585's capture pattern.
    import re as _re
    admin_email = f"admin@{ctx.registry_name}.dev"   # slug(frame-test) → admin@frame-test.dev
    parsed_password = ""
    try:
        reg = client.containers.get(reg_name)
        raw_logs = reg.logs(tail=400).decode(errors="replace")
        m = _re.search(r'FIRST-BOOT ADMIN PASSWORD:\s*(\S+)', raw_logs)
        if m:
            parsed_password = m.group(1)
            logger.info(f"[FRAME-TEST] Captured admin password (len={len(parsed_password)})")
        else:
            logger.warning(f"[FRAME-TEST] Could not parse FIRST-BOOT ADMIN PASSWORD from logs")
    except Exception as e:
        logger.warning(f"[FRAME-TEST] admin password capture failed: {e}")

    # Make the captured password visible to the router via ctx
    if parsed_password:
        ctx.admin_password = parsed_password

    return FrameTestProvisionResult(
        containers_started=containers_started,
        registry_port=ctx.port_registry,
        teg_port=ctx.port_teg,
        eventstore_port=ctx.port_eventstore,
        nginx_fed_port=ctx.port_nginx_fed,
        admin_email=admin_email,
        admin_password=ctx.admin_password,
        trust_domain=ctx.trust_domain,
        stack_dir=ctx.stack_dir_host,
        network_name=ctx.net_name,
    )


# ── Teardown ─────────────────────────────────────────────────────────────

def teardown_frame_test(ctx: FrameTestContext) -> FrameTestTeardownResult:
    """Best-effort cleanup of one frame-test run. Safe to call even if
    provision_frame_test failed midway."""
    ctx.finalize_derivations()
    client = _docker_client()

    # 1) docker compose down -v (best-effort via docker:cli container)
    try:
        if os.path.exists(ctx.stack_dir_container):
            _run_docker_cli(
                "docker compose -f docker-compose.frame-test.yml "
                "--env-file .env.frame-test down -v --remove-orphans",
                working_dir=ctx.stack_dir_host,
                stack_dir_host=ctx.stack_dir_host,
                timeout=120,
            )
    except Exception as e:
        logger.warning(f"[FRAME-TEST] compose down failed: {e}")

    # 2) Force-remove any still-running containers matching the prefix
    containers_removed = 0
    try:
        for c in client.containers.list(all=True, ignore_removed=True):
            if c.name.startswith(f"{ctx.registry_name}-"):
                try:
                    c.remove(force=True, v=True)
                    containers_removed += 1
                except Exception as e:
                    logger.warning(f"[FRAME-TEST] force rm {c.name}: {e}")
    except Exception as e:
        logger.warning(f"[FRAME-TEST] containers.list failed: {e}")

    # 3) Remove named volumes
    volumes_removed = 0
    try:
        for v in client.volumes.list():
            if v.name.startswith(ctx.vol_prefix + "_"):
                try:
                    v.remove(force=True)
                    volumes_removed += 1
                except Exception as e:
                    logger.warning(f"[FRAME-TEST] volume rm {v.name}: {e}")
    except Exception as e:
        logger.warning(f"[FRAME-TEST] volumes.list failed: {e}")

    # 4) Remove networks
    # ctx.net_name is always per-frame internal — safe to remove.
    # ctx.identity_net_name is shared in dual-frame mode (identity_net_external=True);
    # the dual-frame orchestrator removes that one once at the end. In single-frame
    # mode it's per-frame and we remove it here.
    networks_removed = 0
    nets_to_remove = [ctx.net_name]
    if not ctx.identity_net_external:
        nets_to_remove.append(ctx.identity_net_name)
    for net_name in nets_to_remove:
        try:
            for n in client.networks.list(names=[net_name]):
                try:
                    n.remove()
                    networks_removed += 1
                except Exception as e:
                    logger.warning(f"[FRAME-TEST] network rm {n.name}: {e}")
        except Exception as e:
            logger.warning(f"[FRAME-TEST] networks.list({net_name}): {e}")

    # 5) Stack dir
    stack_dir_removed = False
    try:
        if os.path.exists(ctx.stack_dir_container):
            shutil.rmtree(ctx.stack_dir_container, ignore_errors=True)
            stack_dir_removed = not os.path.exists(ctx.stack_dir_container)
    except Exception as e:
        logger.warning(f"[FRAME-TEST] stack-dir rmtree: {e}")

    return FrameTestTeardownResult(
        containers_removed=containers_removed,
        volumes_removed=volumes_removed,
        networks_removed=networks_removed,
        stack_dir_removed=stack_dir_removed,
    )


# ── SPIRE entry registration for the test frame's own services ──────────

# ── §FRAMEFED (2026-09-04, his word: "fix the frame provisioner federatesWith too") ──────────
# Federation has three layers (HANDOVER_2026-09-03_SANDBOX_STANDUP §7.1): the bundle IMPORT, the
# SPIRE federation RELATIONSHIP, and `-federatesWith` on every WORKLOAD ENTRY. The provisioner
# created every entry without the third, so a fresh frame's SVIDs never carried a peer's bundle
# and every cross-frame mTLS call died CERTIFICATE_VERIFY_FAILED until someone re-created the
# entries by hand (§SBXFED: "6/6 entries on each frame now federate with the peer" — by hand).
#
# Two facts shape the fix:
#   · SPIRE refuses `-federatesWith spiffe://X` unless X's bundle is ALREADY in its datastore
#     (layer 1 first). At create time the provisioner therefore federates only with the peers
#     whose bundle is present (`bundle list`), and NAMES the ones it had to defer.
#   · `spire-server entry update` is a FULL REPLACE (R49): every selector, DNS name, TTL and
#     existing FederatesWith must be re-passed or it is silently dropped. Hence the parsers
#     and one argv builder below, pure so they are tested without a SPIRE server.
# `federate_frame_workload_entries()` is the second half: called by the frame-invitation approve
# rail right after a peer bundle lands, it adds that peer to every service/operator entry.

def parse_entry_show(text: str) -> List[dict]:
    """`spire-server entry show` text → one dict per entry (entry_id, spiffe_id, parent_id,
    selectors[], dns[], ttl, federates_with[]). Blank-line separated blocks; unknown keys ignored."""
    out: List[dict] = []
    cur: dict = {}
    for raw in (text or "").splitlines() + [""]:
        line = raw.rstrip()
        if not line:
            if cur.get("entry_id") and cur.get("spiffe_id"):
                out.append(cur)
            cur = {}
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if key == "Entry ID":
            cur["entry_id"] = val
        elif key == "SPIFFE ID":
            cur["spiffe_id"] = val
        elif key == "Parent ID":
            cur["parent_id"] = val
        elif key == "Selector":
            cur.setdefault("selectors", []).append(val)
        elif key == "DNS name":
            cur.setdefault("dns", []).append(val)
        elif key == "FederatesWith":
            td = val[len("spiffe://"):] if val.startswith("spiffe://") else val
            td = td.strip("/")
            if td and td not in cur.setdefault("federates_with", []):
                cur["federates_with"].append(td)
        elif key == "X509-SVID TTL":
            cur["ttl"] = val if val and val != "default" else None
    return out


def parse_bundle_list(text: str) -> List[str]:
    """`spire-server bundle list` text → the FEDERATED trust domains it holds (the `* <td>` lines
    between the star rules). Our own trust domain is never listed there."""
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("* "):
            td = line[2:].strip()
            td = td[len("spiffe://"):] if td.startswith("spiffe://") else td
            td = td.strip("/")
            if td and td not in out:
                out.append(td)
    return out


def merge_federates_with(existing: List[str], wanted: List[str]) -> List[str]:
    """Order-preserving union of bare trust domains (existing first, so a replace never drops one)."""
    out: List[str] = []
    for td in list(existing or []) + list(wanted or []):
        td = (td or "").strip()
        td = td[len("spiffe://"):] if td.startswith("spiffe://") else td
        td = td.strip("/")
        if td and td not in out:
            out.append(td)
    return out


def spire_entry_argv(action: str, *, spiffe_id: str, parent_id: str, selectors: List[str],
                     dns: List[str], ttl: Optional[str] = "14400",
                     federates_with: Optional[List[str]] = None,
                     entry_id: Optional[str] = None) -> List[str]:
    """The full argv for `entry create` or `entry update`. Deduplicated, order-preserving lists for
    -selector / -dns / -federatesWith (SPIRE enforces UNIQUE dns per entry; a repeat fails the whole
    command). An `update` must carry -entryID and re-pass EVERYTHING — it is a replace."""
    assert action in ("create", "update"), action
    argv = ["/opt/spire/bin/spire-server", "entry", action]
    if action == "update":
        assert entry_id, "entry update needs -entryID"
        argv += ["-entryID", entry_id]
    argv += ["-spiffeID", spiffe_id, "-parentID", parent_id]
    seen_sel: List[str] = []
    for sel in selectors or []:
        if sel and sel not in seen_sel:
            seen_sel.append(sel)
            argv += ["-selector", sel]
    if ttl:
        argv += ["-x509SVIDTTL", str(ttl)]
    seen_dns: List[str] = []
    for d in dns or []:
        if d and d not in seen_dns:
            seen_dns.append(d)
            argv += ["-dns", d]
    for td in merge_federates_with([], federates_with or []):
        argv += ["-federatesWith", f"spiffe://{td}"]
    return argv


def _exec_run_rc_out(container, cmd: List[str]) -> tuple:
    """(rc, text) from docker SDK exec_run, tolerant of both return shapes."""
    res = container.exec_run(cmd)
    rc = getattr(res, "exit_code", res[0] if isinstance(res, tuple) else 0)
    out = getattr(res, "output", res[1] if isinstance(res, tuple) else b"")
    return rc, (out or b"").decode(errors="replace")


def never_federated(path: str) -> bool:
    """Identities whose bundle stays the frame's own root alone, so no peer's SPIRE can mint a certificate they accept:
    the data identity (§MTLSHOPS T3) and the broker's `/service/<f>-redpanda` (§F5 stage 0, 2026-09-26, asked of the
    F6 hand by agentvault2-a1; the registration side keeps its own list)."""
    if path == "service/data":
        return True
    name = path[len("service/"):] if path.startswith("service/") else ""
    return bool(name) and "/" not in name and name.endswith("-redpanda") and len(name) > len("-redpanda")


def planned_service_entries(trust_domain: str, registry_name: str, public_hostname: str = "") -> List[tuple]:
    """§F5 (2026-09-26): the per-service identities of a frame beside the registry's two and the TEG's `teg-layer`,
    each as (label, spiffe id, selector, dns names). Pure, so a test can pin the plan without a SPIRE server.

    The store presents `/service/event-store` (a default service name at every store, so a peer reads it as a peer
    service; origin at its own store is the registry and `teg-layer`). Each nginx sidecar serves ONLY its own name
    (the federation gateway also the public host a peer dials); a server certificate is checked by chain and hostname,
    so a name that is not served must not be carried. The broker serves `<frame>-redpanda` to the store alone and is
    never federated (never_federated()).
    """
    f, td = registry_name, trust_domain
    sel = "docker:label:com.agentvault.service:svid-writer-{svc}-" + f
    fed_dns = [f"{f}-nginx-federation"] + ([public_hostname] if public_hostname else [])
    return [
        ("svid-writer-es", f"spiffe://{td}/service/event-store", sel.format(svc="es"), []),
        ("svid-writer-nginx-event-store", f"spiffe://{td}/service/{f}-nginx-event-store",
         sel.format(svc="nginx-event-store"), [f"{f}-nginx-event-store"]),
        ("svid-writer-nginx-teg", f"spiffe://{td}/service/{f}-nginx-teg", sel.format(svc="nginx-teg"), [f"{f}-nginx-teg"]),
        ("svid-writer-nginx-federation", f"spiffe://{td}/service/{f}-nginx-federation",
         sel.format(svc="nginx-federation"), fed_dns),
        ("svid-writer-redpanda", f"spiffe://{td}/service/{f}-redpanda", sel.format(svc="redpanda"), [f"{f}-redpanda"]),
    ]


def federate_frame_workload_entries(spire_container: str, peer_td: str, *,
                                    exec_fn=None, include_operators: bool = True) -> tuple:
    """Add `peer_td` to every service (and operator) workload entry on one SPIRE server —
    the third federation layer, run AFTER that peer's bundle was imported (else SPIRE refuses).

    `exec_fn(cmd) -> (rc, text)`; defaults to docker exec_run on `spire_container`. Returns
    (ok, detail) where detail counts updated / already / failed / skipped and names failures.
    Never raises on a per-entry failure — the caller decides how loud to be, with the numbers."""
    peer = merge_federates_with([], [peer_td])
    if not peer:
        return False, {"error": "empty peer trust domain"}
    peer_td = peer[0]
    runner = False
    if exec_fn is None:
        # §F6 WP6.1: FRAME_TRUST_SPIRE_VIA=runner reads the entries through the runner's spire_entry_show and adds the
        # peer with spire_entry_update_federates (the runner re-reads each entry and passes all of it back); a refusal
        # is a failure named in the detail, never a docker call
        from agentvault_registry.services import spire_ops_client as _soc
        try:
            runner = _soc.trust_via() == "runner"
        except _soc.SpireOpsUnavailable as exc:
            return False, {"error": str(exc)}
        if runner:
            def exec_fn(cmd):  # noqa: E306
                try:
                    rc, out, err = _soc.run_argv(cmd)
                except _soc.SpireOpsUnavailable as exc:
                    return 1, f"through the frame runner: {exc}"
                return rc, (out if rc == 0 else (err or out))
        else:
            client = _docker_client()
            cont = client.containers.get(spire_container)

            def exec_fn(cmd):  # noqa: E306
                return _exec_run_rc_out(cont, cmd)
    rc, text = exec_fn(["/opt/spire/bin/spire-server", "entry", "show"])
    if rc != 0:
        return False, {"error": f"entry show rc={rc}: {text[:200]}"}
    detail: dict = {"peer": peer_td, "updated": 0, "already": 0, "failed": [], "skipped": 0}
    for e in parse_entry_show(text):
        sid = e.get("spiffe_id", "")
        path = sid.split("://", 1)[-1].split("/", 1)[-1] if "://" in sid else sid
        is_service = path.startswith("service/")
        is_operator = path.startswith("operator/")
        if never_federated(path):
            detail["skipped"] += 1          # §MTLSHOPS T3 + §F5: data and the broker are never federated (their bundle is the frame's own root)
            continue
        if not (is_service or (include_operators and is_operator)):
            detail["skipped"] += 1          # agent identities, the SPIRE agent itself
            continue
        if peer_td in e.get("federates_with", []):
            detail["already"] += 1
            continue
        if runner:
            try:
                res = _soc.entry_update_federates(e["entry_id"], [peer_td])
                rc, out = int(res.get("rc", 1)), str(res.get("stderr") or res.get("stdout") or "")
            except _soc.SpireOpsUnavailable as exc:
                rc, out = 1, f"through the frame runner: {exc}"
        else:
            argv = spire_entry_argv(
                "update", entry_id=e["entry_id"], spiffe_id=sid, parent_id=e.get("parent_id", ""),
                selectors=e.get("selectors", []), dns=e.get("dns", []), ttl=e.get("ttl") or None,
                federates_with=merge_federates_with(e.get("federates_with", []), [peer_td]),
            )
            rc, out = exec_fn(argv)
        if rc == 0:
            detail["updated"] += 1
        else:
            detail["failed"].append(f"{sid} rc={rc}: {out[:160]}")
    ok = not detail["failed"]
    if not ok:
        logger.warning("[FRAMEFED] %d entry update(s) failed on %s: %s", len(detail["failed"]),
                       spire_container, "; ".join(detail["failed"]))
    return ok, detail


def register_test_frame_spire_entries(ctx: FrameTestContext) -> tuple[bool, str]:
    """After the test frame is up, register its default workload entries so
    TEG/Registry/EventStore can receive SVIDs. Without this cert-writer spins
    looking for entries and the nginx-federation can't start mTLS."""
    client = _docker_client()
    spire_container = f"{ctx.registry_name}-spire-server"
    agent_container = f"{ctx.registry_name}-spire-agent"

    # First: discover the attested agent's SPIFFE ID (x509pop fingerprint).
    try:
        srv = client.containers.get(spire_container)
        rc, out = srv.exec_run(
            ["/opt/spire/bin/spire-server", "agent", "list"],
            demux=False,
        )
        out_str = (out or b"").decode(errors="replace")
    except Exception as e:
        return False, f"agent list exec failed: {e}"

    fingerprint = None
    for line in out_str.splitlines():
        line = line.strip()
        if "SPIFFE ID" in line and "x509pop" in line:
            # line format: "SPIFFE ID         : spiffe://.../spire/agent/x509pop/<hex>"
            fingerprint = line.split("/")[-1].strip()
            break
    if not fingerprint:
        # Wait up to 30s for attestation to complete
        for _ in range(6):
            time.sleep(5)
            try:
                rc, out = srv.exec_run(["/opt/spire/bin/spire-server", "agent", "list"])
                out_str = (out or b"").decode(errors="replace")
                for line in out_str.splitlines():
                    line = line.strip()
                    if "SPIFFE ID" in line and "x509pop" in line:
                        fingerprint = line.split("/")[-1].strip()
                        break
                if fingerprint:
                    break
            except Exception:
                pass
    if not fingerprint:
        return False, f"agent not yet attested; out={out_str[:300]}"

    parent_id = f"spiffe://{ctx.trust_domain}/spire/agent/x509pop/{fingerprint}"

    # Register the default entries the frame needs. §F5 (2026-09-26, his word "approved ... do it fully"): ONE IDENTITY
    # PER SERVICE (DESIGN_2026-09-26_F5_F6.md §3). The registry keeps its two (the cert-writer's file identity and its
    # own Workload-API identity). The TEG's `/service/teg-layer` is selected by ITS WRITER's label: it used to be
    # selected by the TEG container's own label, and nothing ever fetched it (the TEG read the registry's files), so
    # the TEG spoke as the registry to its store and to every peer TEG. The store, the three sidecars and the broker
    # get their own entries (planned_service_entries), each selected by its writer's label, each carrying only the DNS
    # name it serves. Every name is accepted by every verifier already (the store's default and known service names,
    # the TEG's `/service/teg-*` rule, chain-and-hostname for servers): no presenter moves before its name is accepted.
    entries = [
        ("svid-writer-frame-test", f"spiffe://{ctx.trust_domain}/service/{ctx.registry_name}-registry",
         f"docker:label:com.agentvault.service:svid-writer-{ctx.registry_name}"),
        ("svid-writer-teg", f"spiffe://{ctx.trust_domain}/service/teg-layer",
         f"docker:label:com.agentvault.service:svid-writer-teg-{ctx.registry_name}"),
        ("registry-frame-test", f"spiffe://{ctx.trust_domain}/service/registry",
         f"docker:label:com.agentvault.service:registry-{ctx.registry_name}"),
    ]
    # §XFRAMETEG (2026-09-04) — the SVID must carry a DNS SAN for EVERY hostname a
    # peer will dial. It had only `-nginx-federation`, so when the TEG mTLS sidecar
    # arrived the handshake failed "certificate is not valid for
    # <frame>-nginx-teg" — the trust chain verified fine; the NAME was absent.
    #
    # ⚠ ORDER-PRESERVING DEDUPE, and it is not cosmetic. SPIRE enforces
    # `UNIQUE(dns_names.value)` per entry: passing the same `-dns` twice makes the
    # whole command exit non-zero, and §pass78c showed exactly this silently
    # leaving an operator with NO hostname SAN for weeks because the failure was
    # swallowed. Hence both the dedupe and the exit-code check below.
    # §F5 (2026-09-26): the registry's two identities are CLIENT identities now and carry no DNS name at all. The
    # names above (the three sidecars, the broker, the public host) moved to the entry of the service that SERVES each
    # one (planned_service_entries below): a server certificate is checked by chain and hostname, so each server needs
    # exactly its own name, and a sidecar can no longer serve as another sidecar. The history of why each name was
    # once here (§XFRAMETEG, §FRAMEFED, §MTLSGAP, §SOVKIT K1) lives with the per-service entries that carry it.
    dns_names: List[str] = []

    # §FRAMEFED: federate with every peer the context names — but SPIRE refuses a
    # -federatesWith whose bundle it does not hold yet, so only the peers whose bundle is
    # PRESENT go on the create; the rest are named here and picked up by the approve rail
    # (federate_frame_workload_entries) the moment their bundle lands.
    wanted_fed = merge_federates_with([], [
        td for td in (ctx.extra_trusted_spiffe_domains or []) if td and td != ctx.trust_domain
    ])
    present: List[str] = []
    try:
        _rc_b, _bl = _exec_run_rc_out(srv, ["/opt/spire/bin/spire-server", "bundle", "list"])
        present = parse_bundle_list(_bl) if _rc_b == 0 else []
    except Exception as e:  # noqa: BLE001 — a failed list means "assume none present"
        logger.warning("[FRAME-TEST] bundle list failed (%s); creating entries without federatesWith", e)
    fed_now = [td for td in wanted_fed if td in present]
    fed_deferred = [td for td in wanted_fed if td not in present]

    # §SOVKIT (2026-09-14) — the frame's own Directory presents this identity on its crawl and serves it on its
    # mTLS read leg; the registry dials `https://<name>-directory-nginx:8443` and verifies THAT name, so the SAN
    # must carry it (§XFRAMETEG's lesson a third time). Its own entry, its own selector label (the cert-writer
    # in the template carries `svid-writer-directory-<name>`), never a copy of the registry's.
    directory_entry = ("svid-writer-directory", f"spiffe://{ctx.trust_domain}/service/directory",
                       f"docker:label:com.agentvault.service:svid-writer-directory-{ctx.registry_name}")
    directory_dns = [f"{ctx.registry_name}-directory-nginx", "directory-nginx", "directory"]
    # §MTLSHOPS T2 (2026-09-15, IDs agreed with agentvault2-85): the kit's own identity. OPA, Prometheus and Alertmanager
    # serve with it and every client verifies those names; Prometheus and the Grafana egress dial with it. Its own entry and
    # selector label (the template's kit cert-writer carries `svid-writer-kit-<name>`), never a copy of the registry's.
    kit_entry = ("svid-writer-kit", f"spiffe://{ctx.trust_domain}/service/kit",
                 f"docker:label:com.agentvault.service:svid-writer-kit-{ctx.registry_name}")
    # §MTLSHOPS T2 (S4, 2026-09-15): nginx-ntfy serves the registry's publish lane on the kit's SVID under its own name.
    kit_dns = [f"{ctx.registry_name}-opa", f"{ctx.registry_name}-prometheus", f"{ctx.registry_name}-alertmanager",
               f"{ctx.registry_name}-nginx-ntfy"]
    # §MTLSHOPS T2 (S4, 2026-09-15): the solo auditor's own identity. It presents it on its one store read (through
    # nginx-event-store, never as one of the store's internal services), and nginx-auditor serves Prometheus's lane on it.
    auditor_entry = ("svid-writer-auditor", f"spiffe://{ctx.trust_domain}/service/auditor",
                     f"docker:label:com.agentvault.service:svid-writer-auditor-{ctx.registry_name}")
    auditor_dns = [f"{ctx.registry_name}-nginx-auditor"]
    # §MTLSHOPS T3 (2026-09-15, agentvault2-b5): the data identity. The frame's three Postgres servers and its Redis serve TLS
    # on it under the names their clients dial and verify, and they check every client certificate against its bundle. It
    # is never federated: that bundle then holds the frame's own root alone, so no peer's SPIRE can mint a certificate the
    # data services accept (federate_frame_workload_entries skips it as well). Its own selector label (the template's data
    # cert-writer carries `svid-writer-data-<name>`), never a copy of the registry's.
    data_entry = ("svid-writer-data", f"spiffe://{ctx.trust_domain}/service/data",
                  f"docker:label:com.agentvault.service:svid-writer-data-{ctx.registry_name}")
    data_dns = [f"{ctx.registry_name}-db", f"{ctx.registry_name}-teg-db", f"{ctx.registry_name}-es-db",
                f"{ctx.registry_name}-redis"]
    # §F5: the store, the three sidecars and the broker, each on its writer's label with only its own DNS name(s); the
    # broker's identity is never federated (never_federated(), the same predicate the approve rail applies).
    service_entries = planned_service_entries(ctx.trust_domain, ctx.registry_name, (ctx.public_hostname or "").strip())
    entries = list(entries) + [directory_entry, kit_entry, auditor_entry, data_entry] + [
        (label, svid, selector) for label, svid, selector, _dns in service_entries]
    entry_dns = {directory_entry[1]: directory_dns, kit_entry[1]: kit_dns, auditor_entry[1]: auditor_dns,
                 data_entry[1]: data_dns}
    entry_dns.update({svid: _dns for _label, svid, _selector, _dns in service_entries})

    def _federates(svid: str) -> bool:
        return not never_federated(svid.split("://", 1)[-1].split("/", 1)[-1])
    added, updated, failed = 0, 0, []
    for _, svid, selector in entries:
        _dns = entry_dns.get(svid, dns_names)
        try:
            # ⚠ exec_run returns (exit_code, output) — the old code discarded BOTH,
            # so a refused `entry create` counted as success. A provisioner that
            # cannot say which entries exist is how a frame boots looking healthy
            # and cannot speak mTLS to anyone.
            rc, out = _exec_run_rc_out(srv, spire_entry_argv(
                "create", spiffe_id=svid, parent_id=parent_id, selectors=[selector],
                dns=_dns, ttl="14400", federates_with=fed_now if _federates(svid) else [],
            ))
            if rc == 0:
                added += 1
                continue
            # A re-run: the entry exists. `entry create` refuses duplicates.
            _rc_s, _shown = _exec_run_rc_out(srv, ["/opt/spire/bin/spire-server", "entry", "show",
                                                   "-spiffeID", svid])
            existing = [e for e in parse_entry_show(_shown) if e.get("spiffe_id") == svid] if _rc_s == 0 else []
            if not existing:
                failed.append(f"{svid} rc={rc}: {out[:160]!r}")
                continue
            e = existing[0]
            if selector not in e.get("selectors", []):
                # §F5: the entry is keyed on ANOTHER label (the TEG's own container label before F5). `entry update`
                # MERGES selectors and SPIRE ANDs them, so a merged entry matches no container at all: the re-key is
                # DELETE then CREATE (SECFIX_2026-09-25.md §10, measured on the sandbox pair 2026-09-26).
                rc_d, out_d = _exec_run_rc_out(srv, ["/opt/spire/bin/spire-server", "entry", "delete", "-entryID", e["entry_id"]])
                if rc_d != 0:
                    failed.append(f"{svid} delete (re-key from {e.get('selectors')}) rc={rc_d}: {out_d[:160]!r}")
                    continue
                rc_c, out_c = _exec_run_rc_out(srv, spire_entry_argv(
                    "create", spiffe_id=svid, parent_id=e.get("parent_id") or parent_id, selectors=[selector],
                    dns=_dns, ttl=e.get("ttl") or "14400",
                    federates_with=(merge_federates_with(e.get("federates_with", []), fed_now) if _federates(svid) else []),
                ))
                if rc_c == 0:
                    updated += 1
                    continue
                failed.append(f"{svid} re-key create rc={rc_c}: {out_c[:160]!r}")
                continue
            # the same label: UPDATE, re-passing everything (a replace). The DNS list is REPLACED by what this run
            # wants, never appended: §F5 takes names OFF the registry's entries, and an append could never do that.
            rc2, out2 = _exec_run_rc_out(srv, spire_entry_argv(
                "update", entry_id=e["entry_id"], spiffe_id=svid,
                parent_id=e.get("parent_id") or parent_id,
                selectors=e.get("selectors", []),
                dns=_dns, ttl=e.get("ttl") or "14400",
                federates_with=(merge_federates_with(e.get("federates_with", []), fed_now) if _federates(svid) else []),
            ))
            if rc2 == 0:
                updated += 1
                continue
            failed.append(f"{svid} update rc={rc2}: {out2[:160]!r}")
        except Exception as e:
            failed.append(f"{svid}: {e!r}")

    msg = (f"parent={fingerprint[:12]}... added {added}/{len(entries)} entries"
           f"{f', updated {updated}' if updated else ''}, registry dns={dns_names or 'none (§F5)'}, "
           f"per-service={[(s.split('/service/')[1], d) for _l, s, _sel, d in service_entries]}, "
           f"federatesWith={fed_now or 'none'}"
           f"{f' (deferred until their bundle lands: {fed_deferred})' if fed_deferred else ''}")
    if failed:
        # Reported, not swallowed: without a DNS SAN the frame's sidecars serve a
        # cert no peer will accept, and the symptom appears far from here.
        logger.warning("[FRAME-TEST] spire entry failures: %s", "; ".join(failed))
        msg += f" — {len(failed)} FAILED: {failed[0]}"
    if fed_deferred:
        logger.warning("[FRAME-TEST] entries created WITHOUT federatesWith for %s — their bundle is "
                       "not imported yet; the frame-invitation approve rail adds them", fed_deferred)
    return True, msg
