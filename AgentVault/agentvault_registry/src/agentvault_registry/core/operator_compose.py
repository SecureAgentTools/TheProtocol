"""§OPDIST — every edit a provisioned cloud operator's compose needs, as one function with no hidden inputs.

⚠ IT LIVES HERE, IN `core`, AND NOT BESIDE THE PROVISIONER, FOR A MEASURED REASON (2026-09-16): the one-shot
container that provisions an operator on a runner-built frame holds NO database URL and NO API key, deliberately,
and `agentvault_registry.services.__init__` imports webhook_service -> models -> database -> Settings, which
REQUIRES both. Anything the one-shot must import therefore cannot live under `services`. `core` imports nothing.

The registry supplies VALUES and the one-shot supplies STRUCTURE: a compose the registry could write and the runner
would bring up as root is an escalation path straight through the seam the runner exists to be. This function takes
the template's own text and edits it; it never accepts one.
"""
from __future__ import annotations

import base64
import json
import re
from typing import List, Tuple, Dict, Optional


def plain_port_bind(edge_mode: str, bridge_gateway: str, override: Optional[str]) -> str:
    """The host address an operator's plain-http registry and TEG ports bind (the federation lane binds every interface).

    §SECFIX-8 (2026-09-25): under this host's nginx edge they bound EVERY interface, and Docker's published ports bypass
    ufw (the DOCKER-USER chain is empty), so an operator's plain registry and TEG answered the internet around host
    nginx, its vhost rules and CrowdSec. Host nginx proxies to 127.0.0.1:<reg_port> and Prometheus reaches the
    containers by name, so loopback loses nothing (measured on the running operators before the change). A Caddy edge
    keeps the bridge gateway it needs. OPERATOR_PLAIN_PORT_BIND overrides it; set EMPTY it restores every interface."""
    if edge_mode == "caddy":
        return bridge_gateway
    if override is not None:
        return override.strip()
    return "127.0.0.1"


def port_line(bind: str, host_port: int, container_port: int) -> str:
    """A compose port line as adapt_operator_compose writes it, quotes included."""
    return f'"{bind}:{host_port}:{container_port}"' if bind else f'"{host_port}:{container_port}"'


def adapt_operator_compose(
    compose: str,
    *,
    safe: str,
    domain: str,
    reg_port: int,
    fed_port: int,
    teg_port: int,
    worker_count: int,
    identity_network: str,
    partner_identity_network: str = "",
    partner_domain_suffix: str = "",
    spire_addr: str = "",
    spire_trust_domain: str = "",
    es_url: str = "",
    bind_address: str = "",
) -> Tuple[str, List[str]]:
    """Every edit a provisioned operator's compose needs, as ONE function with no hidden inputs.

    §OPDIST (2026-09-16): this was four hundred lines into `provision_cloud_operator`, reading module constants and
    the process environment directly, which is fine while exactly one process does the work. A runner-built frame's
    one-shot does the same work in a different container, and the frame's identity network is NOT derivable from its
    name (measured by agentvault2-85 across the fleet: lantern `lantern_network_identity`, EU and ASIA both
    `fresh-identity`). So every input is a PARAMETER: the caller that knows each value passes it, and the two callers
    cannot drift into adapting a compose two different ways.

    ⚠ The registry supplies VALUES and the one-shot supplies STRUCTURE, and this function is where that line is
    drawn: a compose the registry could write and the runner would bring up as root is an escalation path straight
    through the seam the runner exists to be. This takes the template's own text and edits it; it never accepts one.

    Returns the adapted text and the notes worth reporting (a pattern that matched nothing is a template that moved,
    which the caller must be able to say out loud rather than discover at compose up).
    """
    notes: List[str] = []

    # Port mappings
    # §HELLOFRAME lane 6 (2026-09-18): under a frame's own Caddy edge the registry and TEG ports bind ONE host
    # address (the docker bridge gateway: the edge and the portal hop reach them there) instead of every interface,
    # so a foreign host does not publish an operator's plain-http registry to the internet. The federation port stays
    # public on purpose: it is the mTLS lane peers dial. Empty (every frame on the network's own host) leaves the
    # three lines byte-identical to what they were.
    _bind = f"{str(bind_address or '').strip()}:" if str(bind_address or "").strip() else ""
    compose = compose.replace('"12443:8443"', f'"{fed_port}:8443"')
    # CB-324 (2026-10-16): the bundle template binds its plain registry and TEG ports to loopback
    # ("127.0.0.1:12000:8000"), so the bundle as shipped exposes neither; older templates wrote them on every
    # interface ("12000:8000"). Either form is the placeholder this rewrites to the operator's own bind and port.
    for _ph in ('"12000:8000"', '"127.0.0.1:12000:8000"'):
        compose = compose.replace(_ph, f'"{_bind}{reg_port}:8000"')
    # TEG host port — replaces template placeholder so Prometheus can scrape.
    # Backward-compat: if template doesn't have the placeholder yet, fall back
    # to injecting `ports:` block under teg-layer service definition.
    _teg_ph = [ph for ph in ('"12080:8080"', '"127.0.0.1:12080:8080"') if ph in compose]
    if _teg_ph:
        for _ph in _teg_ph:
            compose = compose.replace(_ph, f'"{_bind}{teg_port}:8080"')
    else:
        _teg_ports_pattern = (
            r'(\n  teg-layer:\n'
            r'    image: [^\n]*/teg-layer:[^\n]+\n'
            r'    container_name: \$\{REGISTRY_NAME:-operator\}-teg\n'
            r'    restart: unless-stopped\n)'
        )
        _teg_ports_replacement = (
            r'\1'
            f'    ports:\n'
            f'      - "{_bind}{teg_port}:8080"\n'
        )
        compose, _n_teg = re.subn(_teg_ports_pattern, _teg_ports_replacement, compose, count=1)
        if _n_teg == 0:
            notes.append("could not inject teg-layer ports — template mismatch")

    # Identity network(s) for nginx-federation (with domain alias).
    _nginx_net_pattern = (
        r'(container_name: \$\{REGISTRY_NAME:-operator\}-nginx-federation\b'
        r'.*?networks:\n)'
        r'(\s+- operator-net\n)'
    )
    _net_block = (
        f'      operator-net:\n'
        f'      {identity_network}:\n'
        f'        aliases:\n'
        f'          - {domain}\n'
    )
    if partner_identity_network and partner_domain_suffix:
        partner_domain = f"{safe}.{partner_domain_suffix}"
        _net_block += (
            f'      {partner_identity_network}:\n'
            f'        aliases:\n'
            f'          - {partner_domain}\n'
        )
    _nginx_net_replacement = r'\1' + _net_block
    compose, n = re.subn(_nginx_net_pattern, _nginx_net_replacement, compose, count=1, flags=re.DOTALL)
    if n == 0:
        notes.append("could not patch nginx-federation networks")

    # Sandbox mode only: the parent's SPIRE and mTLS terminators are reachable through the host gateway.
    if spire_addr == "host.docker.internal":
        _spire_agent_pattern = (
            r'(container_name: \$\{REGISTRY_NAME:-operator\}-spire-agent\b.*?)'
            r'(\n    volumes:)'
        )
        _spire_agent_replacement = (
            r'\1\n    extra_hosts:\n'
            r'      - "host.docker.internal:host-gateway"\2'
        )
        compose, _n = re.subn(_spire_agent_pattern, _spire_agent_replacement, compose, count=1, flags=re.DOTALL)
        notes.append("spire-agent extra_hosts injected" if _n else
                     "could not inject extra_hosts on spire-agent (template mismatch)")
        _registry_pattern = (
            r'(container_name: \$\{REGISTRY_NAME:-operator\}-registry\b\n'
            r'    restart: unless-stopped)'
            r'(\n    ports:)'
        )
        _registry_replacement = (
            r'\1\n    extra_hosts:\n'
            r'      - "nginx-test-a:host-gateway"\n'
            r'      - "nginx-test-b:host-gateway"\n'
            r'      - "nginx-test-c:host-gateway"\2'
        )
        compose, _n2 = re.subn(_registry_pattern, _registry_replacement, compose, count=1, flags=re.DOTALL)
        notes.append("registry extra_hosts injected" if _n2 else
                     "could not inject extra_hosts on registry (template mismatch)")

    # The external network declarations at the bottom, once each.
    _bottom_nets_section = compose.split('networks:\n  operator-net:')[-1]
    if f'{identity_network}:' not in _bottom_nets_section:
        compose = compose.rstrip() + f'\n  {identity_network}:\n    external: true\n'
    if partner_identity_network and f'{partner_identity_network}:' not in compose.split(
            'networks:\n  operator-net:')[-1]:
        compose = compose.rstrip() + f'\n  {partner_identity_network}:\n    external: true\n'

    _wc = max(2, int(worker_count))
    compose = compose.replace('--workers 8 -c /app/gunicorn_conf.py', f'--workers {_wc} -c /app/gunicorn_conf.py')
    compose = compose.replace('--workers 4 --proxy-headers', f'--workers {_wc} --proxy-headers')
    compose = compose.replace('--workers 4"', f'--workers {_wc}"')

    if es_url:
        compose = compose.replace(
            "EVENT_STORE_URL: https://events.theprotocol.cloud",
            f"EVENT_STORE_URL: {es_url}",
        )

    _legacy_registry_cmd = (
        '["sh", "-c", "cd /app && PYTHONPATH=/app/src python -c '
        '\\"from agentvault_registry.database import Base; '
        'from agentvault_registry import models; '
        'from sqlalchemy import create_engine; '
        'import os; '
        "e=create_engine(os.environ['DATABASE_URL_SYNC'].replace('pgbouncer:6432','db:5432')); "
        'Base.metadata.create_all(e); '
        'print(f\'DB ready: {len(Base.metadata.tables)} tables\')\\" '
        '&& alembic stamp heads 2>/dev/null; '
    )
    _new_registry_cmd_prefix = (
        '["sh", "-c", "cd /app && PYTHONPATH=/app/src python -m '
        'agentvault_registry.migration_bridge && cd /app && '
        'PYTHONPATH=/app/src alembic upgrade head 2>/dev/null; '
    )
    if _legacy_registry_cmd in compose:
        compose = compose.replace(_legacy_registry_cmd, _new_registry_cmd_prefix)
        notes.append("registry startup migrated: create_all+stamp-heads → migration_bridge+alembic-upgrade-head")
    else:
        notes.append("legacy registry command not found — template may already be updated")

    return compose, notes

def adapt_federation_conf(nginx: str, *, safe: str, domain: str) -> Tuple[str, List[str]]:
    """The operator's nginx-federation.conf, named for the operator it actually fronts.

    Moved out of `provision_cloud_operator` with its behaviour intact (§OPDIST 2026-09-16) so the one-shot that
    provisions on a runner-built frame makes the same edits: the sidecar has to answer for this operator's own
    domain and proxy to THIS operator's TEG, and a template left at `teg-layer` sends every cross-TEG call to
    whichever container answers that name first.
    """
    notes: List[str] = []
    nginx = nginx.replace(
        'server_name nginx-federation;',
        f'server_name nginx-federation {domain} _;'
    )
    before = nginx
    nginx = nginx.replace(
        'set $upstream_teg teg-layer;',
        f'set $upstream_teg cloud-op-{safe}-teg;'
    )
    if 'set $upstream_teg' not in nginx:
        nginx = nginx.replace(
            'proxy_pass http://teg-layer:8080;',
            f'proxy_pass http://cloud-op-{safe}-teg:8080;'
        )
    if nginx == before:
        notes.append("the TEG upstream was already this operator's, or the template moved")
    nginx = re.sub(
        r'(location /api/v1/cross-teg/.*?proxy_set_header Host\s+)\$host;',
        r'\1teg-layer;',
        nginx, flags=re.DOTALL
    )
    notes.append(f"nginx-federation.conf: server_name and TEG upstream set for {safe}")
    return nginx, notes


def docker_auth_config(*, username: str, token: str, registry_host: str = "images.theprotocol.cloud") -> str:
    """The per-stack docker config.json that lets `compose up` PULL at all.

    §pass65's finding, unchanged and now in one place: the client that runs compose looks for auth in its own
    ~/.docker/config.json, the host's is not inherited, and without this every pull against the image registry is
    401 and the whole stack fails to start. Per-stack scope means revocation is deleting the stack.
    """
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    return json.dumps({"auths": {registry_host: {"auth": auth}}})


def svid_dns_sans(*, domain: str, safe: str = "", partner_identity_network: str = "",
                  partner_domain_suffix: str = "") -> List[str]:
    """The hostnames an operator's svid-writer SVID must be valid for, deduplicated and order-preserving.

    Moved here whole (§OPDIST 2026-09-16) BECAUSE OF ITS SCARS, which are the reason it must not be retyped:
      · SPIRE enforces UNIQUE(entry, dns), so emitting the same host twice makes `entry update` fail and the SVID
        silently keeps no hostname SAN at all — which is what happens whenever the cloud and partner domain
        suffixes collapse to the same string (§pass78c: op-riyadh had no SAN, op-telaviv only worked because the
        two suffixes still differed that week);
      · `nginx-teg` was never in the list, while every operator ships TEG_API_BASE_URL=https://nginx-teg:8443 and
        ONE svid-writer SVID serves both sidecars, so every treasury and balance call 500'd on a hostname mismatch
        from birth, invisible to delta because no money moves when the rail is simply dead (§MONEY-R48);
      · a partner frame reaches the operator as `<safe>.<partner suffix>`, so that name has to be valid too or
        cross-frame mTLS fails hostname verification.
    """
    sans: List[str] = []
    for host in ("nginx-federation", "nginx-teg", domain):
        if host and host not in sans:
            sans.append(host)
    if partner_identity_network and partner_domain_suffix:
        partner_dns = f"{safe}.{partner_domain_suffix}"
        if partner_dns and partner_dns not in sans:
            sans.append(partner_dns)
    return sans

def operator_vhost(*, domain: str, reg_port: int, ssl_cert_name: str, ws_events_host: str) -> str:
    """The host vhost a provisioned cloud operator is served by, rendered in ONE place.

    §OPDIST (2026-09-16), and the reason it moved here rather than being re-typed on the side that WRITES it:
    a T3 frame's registry has no /host-nginx-sites mount (the same template line that withholds the docker
    socket withholds this), so on a runner-built frame the runner does the write. Two renderings of what an
    operator's edge looks like would drift the day either changed, and the header pins below are not the kind
    of thing to keep in two places: row 194 is here, where an operator console accepted a SELF-SIGNED
    certificate in a plain header as proof of identity because this template pinned none of them.
    """
    return f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{ssl_cert_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{ssl_cert_name}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    # 🔴 findings row 196 — an operator console served NO security headers at all. One source
    # of truth (§SEOPASS-3); SERVER level because an add_header inside a location wipes every
    # inherited one, so no location in this vhost may set one.
    include snippets/theprotocol-security-headers.conf;

    # Live event stream — proxy to parent frame for global event feed
    location /ws/events {{
        proxy_pass https://{ws_events_host}/ws/events;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host {ws_events_host};
        proxy_read_timeout 86400s;
        proxy_ssl_server_name on;
    }}

    # Authenticated WebSocket (local — notifications, agent updates)
    location /ws/ {{
        proxy_pass http://127.0.0.1:{reg_port}/api/v1/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }}

    location /api/v1/ws {{
        proxy_pass http://127.0.0.1:{reg_port}/api/v1/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;
    }}

    # All other requests
    location / {{
        proxy_pass http://127.0.0.1:{reg_port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 🔴 findings row 194 — PIN THE HEADERS THE APP TREATS AS PROOF OF IDENTITY.
        # `mtls_auth.get_client_spiffe_id` parses X-SSL-Client-Cert OUT OF THE REQUEST HEADERS
        # and trusts the SPIFFE ID inside it: no CA verification, no check of X-SSL-Client-Verify.
        # Safe only while the edge guarantees a client cannot supply it — and this template pinned
        # none of them, so every operator it provisioned accepted a SELF-SIGNED certificate in a
        # plain header as proof of identity on its public console. PROVEN on all four EU/ASIA
        # operators 2026-09-07 with an UNTRUSTED trust domain (each registry answered "Client
        # SPIFFE ID from untrusted domain", i.e. it had already accepted the header as a
        # certificate); a trusted domain in the SAN would have authenticated as the operator's own
        # parent frame. The exploit was not completed. $ssl_client_* are EMPTY on a vhost that
        # requests no client certificate, which is exactly what we want here: the only way to
        # present a certificate to an operator is its mTLS lane.
        proxy_set_header X-SSL-Client-Cert   $ssl_client_escaped_cert;
        proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
        proxy_set_header X-SSL-Client-S-DN   $ssl_client_s_dn;
        # ⚠ The two lines below are a DELIBERATE passthrough and are left as they were. They are
        # inert on an operator (no FEDERATION_INTERNAL_SECRET is configured, so Mode 2 matches
        # nothing) and row 195 refuses the internal-secret rail for any caller that came through
        # an edge, so this cannot authenticate from outside regardless. Removing them is a
        # separate decision about a rail someone wrote on purpose, not part of closing row 194.
        proxy_set_header X-Federation-Secret $http_x_federation_secret;
        proxy_set_header X-Federation-SPIFFE-ID $http_x_federation_spiffe_id;
    }}
}}
"""


def sni_map_entry(*, domain: str, fed_port: int) -> str:
    """The host stream-SNI map line that routes an operator's federation hostname to its own sidecar.

    One line, rendered where the values live. Without it, cross-operator federation arriving at the host stream on
    :8443 falls through to the default and is answered by whichever server that names — the class §BATCH5 met as
    "every unknown SNI on 18443 falls through to nginx-a", where a caller verifying the hostname got someone
    else's certificate and read it as a trust failure.
    """
    return f"{domain}  127.0.0.1:{fed_port};"


# §PUSH (2026-10-06, agentvault2-09; his words "afterwards we do the same with push", "provisioner should also provision
# them", "fix the things you find on the way make it secure"): an operator's own push relay (ntfy), so Pocket can pair a
# phone to an operator's console as it can to a frame's. Every operator had push switched off. The relay's loopback port
# sits at a FIXED offset in the operator's port block (base, +43, +80 are taken; allocate_port_block reserves +99 too),
# so the allocator, the env, the vhost and the runner's check derive it from this one rule and cannot disagree.
PUSH_PORT_OFFSET = 99


def operator_push_port(reg_port: int) -> int:
    return int(reg_port) + PUSH_PORT_OFFSET


def operator_push_host(domain: str) -> str:
    """`<safe>-push.<suffix>` for an operator at `<safe>.<suffix>`. ONE label, so the frame's `*.<suffix>` wildcard covers
    it twice over: the DNS answer and the certificate (`push.<safe>.<suffix>` would be two labels deep, outside both)."""
    d = str(domain or "").strip().rstrip(".")
    label, _, rest = d.partition(".")
    # nothing is stripped from the front: ".op.theprotocol.cloud" is not an operator's domain, and stripping its dot
    # would have named a host one zone up (op-push.theprotocol.cloud)
    if not label or "." not in rest:
        raise ValueError(f"not an operator domain (<safe>.<suffix>, the suffix two labels or more): {domain!r}")
    return f"{label}-push.{rest}"


def operator_push_vhost(*, push_host: str, push_port: int, ssl_cert_name: str) -> str:
    """The operator's public push endpoint, SUBSCRIBE-ONLY by PATH: the frame template's push vhost (the live EU/ASIA
    shape, b5's measured allowlist). `limit_except GET` alone is not subscribe-only, because ntfy publishes on GET too
    (<topic>/publish?message=, /send, /trigger) and since v2.16 deletes and clears on GET; anyone who learned a topic
    name could push to a paired phone. Publishing stays inside the operator's network (registry -> its ntfy).

    Its own file and its own server block, never part of operator_vhost: the runner checks each against what spec.edge
    declares (push_host, push_port), so a push name can never widen what the console vhost may serve. The three headers
    are the frame push vhost's, not the console's snippet: a subscribe from the console is cross-origin."""
    port = int(push_port)
    return f"""# {push_host}: an operator's ntfy push endpoint (§PUSH, core/operator_compose.operator_push_vhost); 443 only
server {{
    listen 443 ssl http2;
    server_name {push_host};
    ssl_certificate /etc/letsencrypt/live/{ssl_cert_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{ssl_cert_name}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location = /v1/health {{
        limit_except GET {{ deny all; }}
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    # subscribe only: one or more comma-separated topics, then json | sse | raw | ws; auth is the app's access check
    location ~ "^/[-_A-Za-z0-9]{{1,64}}(,[-_A-Za-z0-9]{{1,64}})*/(json|sse|raw|ws|auth)$" {{
        limit_except GET {{ deny all; }}
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade           $http_upgrade;
        proxy_set_header Connection        "upgrade";
        proxy_buffering off;
        proxy_read_timeout 350s;
        proxy_send_timeout 350s;
    }}

    location / {{
        return 403;
    }}
}}
"""


def images_prefix_is_local(prefix: str) -> bool:
    """Is an image prefix a LOCAL tag namespace rather than a registry host? Docker's own rule: the first path segment
    is a registry host only when it carries a dot or a colon, or is `localhost`. `agentvault2` is a local namespace
    (the export's own step loads the images under it); `images.theprotocol.cloud` and `registry:5000` are hosts. A
    local namespace needs no pull credential, so the provisioner sends none. (§HELLOFRAME lane 6, 2026-09-18)"""
    head = str(prefix or "").strip().strip("/").split("/", 1)[0]
    if not head:
        return False
    return not ("." in head or ":" in head or head == "localhost")


def operator_public_urls(*, safe: str, suffix: str, lane_port: int = 8443) -> Dict[str, str]:
    """The three public addresses an operator's env carries, from ONE rule: `<safe>.<suffix>`. `suffix` is the frame's
    CLOUD_DOMAIN_SUFFIX (`op.theprotocol.cloud` on the network's own host; a foreign frame's own public name under a
    Caddy edge). `lane_port` is the federation lane peers dial: 8443 behind the host SNI router, the operator's own
    fed_port under a Caddy edge, where nothing multiplexes 8443. The trio used to be three literals naming the
    network's suffix, which is what put an operator on a stranger's host under our name. (§HELLOFRAME lane 6)"""
    host = f"{str(safe or '').strip()}.{str(suffix or '').strip().strip('.')}"
    return {"PUBLIC_URL": f"https://{host}", "BILATERAL_PEER_URL": f"https://{host}:{int(lane_port)}",
            "PUBLIC_UI_URL": f"https://{host}"}
