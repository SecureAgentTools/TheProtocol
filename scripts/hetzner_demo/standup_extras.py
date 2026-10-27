"""§BATCH10 (2026-09-06) — the one-pass standup: everything batch 9 closed BY HAND, as driver code.

Called by standup_driver.py behind explicit flags. Each function is idempotent (a second run changes nothing) and
asserts on the ARTIFACT it produced (the rendered file, the job present, the card served), never on its own rc.
Secrets are read from files and containers and written to 600 files; nothing here prints a secret.

  render_vhosts / issue_cert   findings 2, §0.2–0.3 of the runbook: the five vhosts from templates, one cert, four SANs
  apex_ws_routes               finding 2: the apex/api ledger route for this frame (the FE opens what the JSON names)
  fresh_network_upsert         finding 2/16: the frame's entry in registry-a's FRESH_NETWORK_JSON (applies at its recreate)
  prometheus_jobs              finding 16: the scrape jobs + reload, from the frame's own names
  auditor_slot                 finding 7: the independent auditor's slot (AUDITOR_EXTRA_FRAMES_JSON) + network join + recreate
  identity_nets_append         finding 8
  ops_secret_file              finding 18: ONE shape for operator-admin secret files
  version_gate                 finding 12: the card reports the image's OWN constant (never the env)
  card_extras / put_jurisdiction   the card's tags, links (no GitHub), commitments, and the jurisdiction profile (his word)
  put_operator_card            the operator's card location = the city it is named for (his word: the agentworld derives it)
  seed_local_canary_paths      finding 19: two local canary paths (sender/receiver agents funded) so the canaries fire
  tester_fixture_env           finding 22: the API/MCP testers' fixture posture behind ONE flag
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = os.getenv("FRAME_REPO_ROOT", "/opt/theprotocol/stack/Agentvault2")   # §HELLOFRAME: the export's root on a foreign host
STACK = os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack")
DOMAIN = "theprotocol.cloud"
NGINX_AVAIL = "/etc/nginx/sites-available"
NGINX_ENABLED = "/etc/nginx/sites-enabled"
NGINX_BAK = "/etc/nginx/vhost-backups"
VHOST_TMPL_DIR = f"{REPO}/templates/frame-test/vhosts"
FEDERATED_BUNDLE_PEM = "/etc/nginx/fresh-federated-spire-bundle.pem"
PROM_YML = f"{REPO}/monitoring/prometheus.yml"
PROD_COMPOSE = f"{REPO}/docker-compose.production.yml"
AUDITOR_DIR = f"{REPO}/Agents/TheAuditor"
IDENTITY_NETS_FILE = "/etc/theprotocol/self-contained-identity-nets"
# §FRAMEPROV P1 (2026-09-13): the admin UI's runner keeps a UI-built frame's secrets in its own 0700 job dir.
# FRAME_SECRETS_DIR is read at import so every module instance agrees (the driver, standup_federate and
# sidecars each load their own copy of this module); unset, nothing changes.
SECRETS_DIR = os.getenv("FRAME_SECRETS_DIR") or f"{REPO}/sessionlogs2026"


def log(msg: str) -> None:
    print(f"[extras {time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def http(method: str, url: str, body: Any = None, headers: Optional[Dict[str, str]] = None,
         timeout: int = 30, form: bool = False) -> Tuple[int, Any]:
    data = None
    h = dict(headers or {})
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode(); h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            data = json.dumps(body).encode(); h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read().decode()
            try:
                return r.status, (json.loads(t) if t else {})
            except Exception:
                return r.status, {"raw": t[:400]}
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, {"raw": t[:400]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)[:200]}


def _bak(path: str, tag: str) -> None:
    p = Path(path)
    if p.exists():
        b = Path(NGINX_BAK) / f"{p.name}.bak-pre-{tag}" if str(p).startswith("/etc/nginx/") else p.with_name(p.name + f".bak-pre-{tag}")
        if not b.exists():
            shutil.copy(p, b)


# ── vhosts + certificate ──────────────────────────────────────────────────────────────────────────────────────────────
def vhost_names(name: str) -> Dict[str, str]:
    """The five vhost FILE names of a frame, the runbook's shape (console, es, spire, push, acme)."""
    return {"console": f"{name}-theprotocol", "es": f"{name}-es.{DOMAIN}", "spire": f"{name}-spire",
            "push": f"{name}-push", "acme": f"{name}-acme"}


# §FRAMELIC findings row 170 — THE DISCOVERY STRIP IS TWO HALVES AND THE REPROVISION DROPPED BOTH.
# The federated-index strip on /explore and Discovery is addressed by the registry's PUBLIC CONFIG
# (`directory_url` ← DIRECTORY_PUBLIC_URL), and the browser reaches the index through a SAME-ORIGIN
# proxy on the console vhost. Neither was in any template: both were hand-added to the rehearsal
# pair, so re-rendering the vhosts and writing a fresh env silently removed the whole lane — the
# strip did not error, it stopped existing. Now they are ONE fact in ONE place: pass the upstream
# and both halves are written together; pass nothing and neither is (no inert proxy claiming a
# capability that has no index behind it — §FXSTRAND).
def _directory_block(upstream: str) -> str:
    """The console vhost's Directory lane — which, since §MTLSGAP, there is not one.

    The index used to be reached by a hand-added `location /directory/ { proxy_pass
    http://127.0.0.1:8600/; }` — plain http on loopback, with no identity at either end, on a fleet
    where TEG and federation run `ssl_verify_client on`. It is now addressed as
    `/api/v1/public/directory` and served BY THE REGISTRY, which holds a live auto-rotating SVID and
    dials the index over mTLS. `location /` already proxies the registry, so the vhost needs no
    Directory lane at all.

    That is the point, not a side effect: §FRAMELIC's finding was that this one capability needed
    THREE hand-added things and a clean reprovision silently removed the whole feature — *"its always
    the allow same origin problem with a new standup."* A lane that does not exist cannot be
    forgotten.
    """
    if not upstream:
        return ("    # no federated index configured for this frame (--directory-upstream unset):\n"
                "    # DIRECTORY_PUBLIC_URL stays empty, so the console never dials one and the\n"
                "    # strip does not render.")
    return ("    # The federated index is read THROUGH the registry over mTLS\n"
            "    # (`/api/v1/public/directory`, §MTLSGAP 2026-09-08), so there is deliberately no\n"
            "    # `/directory/` lane here: it falls through `location /` like every other API path.\n"
            f"    # index upstream (registry-side, not served here): {upstream}")


# §FRAMELIC findings row 174 — A CONSOLE CAN ONLY STREAM A LEDGER ITS OWN VHOST PROXIES.
# The ledger strip and Mission Control read `/api/v1/public/fresh-network` and open ONE SOCKET PER
# FRAME, but a `ws_path` is SAME-ORIGIN by design (no CORS, no second hostname) — so naming a peer
# in FRESH_NETWORK_JSON does nothing unless this console also proxies that peer's EventStore. Both
# halves were empty after the reprovision: `FRESH_NETWORK_JSON=[]` on both frames AND no
# `/ws/events-<peer>` lane anywhere, so each console showed only its own ledger and nothing said why.
# Same one-flag rule as the directory lane: pass the peers and BOTH halves are written, or neither is.
def _peer_ledger_block(peers: Dict[str, int]) -> str:
    if not peers:
        return ("    # no peer ledgers configured (--peer-ledger unset): this console streams its own\n"
                "    # frame only, and FRESH_NETWORK_JSON names no peer to stream.")
    out = []
    for pname, pport in sorted(peers.items()):
        out.append(f"""    # peer ledger: {pname}'s EventStore, same-origin so the console needs no CORS
    location /ws/events-{pname} {{
        proxy_pass http://127.0.0.1:{pport}/ws/events;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }}""")
    return "\n".join(out) + "\n"


def render_vhost(kind: str, name: str, ports: Dict[str, int], bundle_pem: str = FEDERATED_BUNDLE_PEM,
                 directory_upstream: str = "", peer_ledgers: Optional[Dict[str, int]] = None,
                 cert_name: str = "") -> str:
    """`cert_name` (§PUSH 2026-10-06): the certificate a template that names {{CERT_NAME}} serves, by default the frame's
    own (`<name>.<domain>`, issue_cert's four-name certificate), so a frame this provisioner stood up renders exactly as
    before. A frame stood up before the runner owned its names has no such certificate for its push host and gets a
    dedicated one (scratchpad/push/push_frame.py, DNS-01 with the runner's token)."""
    tmpl = Path(VHOST_TMPL_DIR) / f"{kind}.conf.tmpl"
    s = tmpl.read_text()
    subs = {"NAME": name, "DOMAIN": DOMAIN, "PORT_REGISTRY": str(ports["registry"]), "PORT_ES": str(ports["es"]),
            "PORT_SPIRE_BUNDLE": str(ports["spire_bundle"]), "PORT_PUSH": str(ports["push"]), "BUNDLE_PEM": bundle_pem,
            "CERT_NAME": cert_name or f"{name}.{DOMAIN}",
            "DIRECTORY_BLOCK": _directory_block(directory_upstream),
            "PEER_LEDGER_BLOCK": _peer_ledger_block(peer_ledgers or {})}
    for k, v in subs.items():
        s = s.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", s)
    assert not left, f"{kind}: unrendered placeholders {left}"
    return s


ES_PROXY_SNIPPET_DIR = "/etc/nginx/snippets"
_ES_SECRET_RE = re.compile(r"^[A-Za-z0-9._~-]{32,}$")


def es_proxy_snippet_path(name: str, root: str = ES_PROXY_SNIPPET_DIR) -> str:
    return os.path.join(root, f"es-proxy-auth-{name}.conf")


def write_es_proxy_snippet(name: str, secret: str, root: str = ES_PROXY_SNIPPET_DIR) -> str:
    """§SOVKIT T2/T5 (2026-09-14, agentvault2-85's live shape): the ONE line the public <frame>-es vhost includes so the
    store can tell a header ITS terminator set from one a caller forged: `proxy_set_header X-ES-Proxy-Auth "<secret>";`.
    Its own file at mode 600, never inside the vhost (vhosts are copied into /etc/nginx/vhost-backups/ and diffed
    around). The value is validated by SHAPE only and never logged; a rewrite with the same content is a no-op."""
    if not _ES_SECRET_RE.fullmatch(secret or ""):
        raise ValueError("ES_PROXY_TRUST_SECRET must be 32+ characters of [A-Za-z0-9._~-] (the value is not printed)")
    os.makedirs(root, exist_ok=True)
    path = es_proxy_snippet_path(name, root)
    body = f'proxy_set_header X-ES-Proxy-Auth "{secret}";\n'
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            same = f.read() == body
        if same and (os.stat(path).st_mode & 0o777) == 0o600:
            return path
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, 0o600)
    return path


def remove_es_proxy_snippet(name: str, root: str = ES_PROXY_SNIPPET_DIR) -> bool:
    """Teardown's half: the snippet goes with the vhost that included it (nginx -t fails on a dangling include)."""
    path = es_proxy_snippet_path(name, root)
    if os.path.exists(path):
        os.remove(path); return True
    return False


def render_vhosts(name: str, ports: Dict[str, int], with_tls: bool,
                  directory_upstream: str = "",
                  peer_ledgers: Optional[Dict[str, int]] = None,
                  bundle_pem: str = FEDERATED_BUNDLE_PEM) -> List[str]:
    """Write the frame's vhosts into sites-available (the driver's enable_vhosts symlinks them). Before the certificate
    exists only the ACME vhost can load, so `with_tls=False` writes the four TLS vhosts to sites-available only and enables
    the ACME one; `with_tls=True` (after issue_cert) enables the rest. Returns the file names written."""
    names = vhost_names(name)
    Path(NGINX_AVAIL).mkdir(parents=True, exist_ok=True)
    written = []
    for kind, fname in names.items():
        body = render_vhost(kind, name, ports, bundle_pem=bundle_pem, directory_upstream=directory_upstream,
                            peer_ledgers=peer_ledgers)
        dst = Path(NGINX_AVAIL) / fname
        if dst.exists() and dst.read_text() == body:
            written.append(fname); continue
        _bak(str(dst), "render")
        dst.write_text(body); written.append(fname)
    # the ACME vhost is enabled at once (port 80 only); the TLS ones after the certificate
    for kind, fname in names.items():
        link = Path(NGINX_ENABLED) / fname
        want = kind == "acme" or with_tls
        if want and not link.exists():
            link.symlink_to(Path(NGINX_AVAIL) / fname)
    rc = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    assert rc.returncode == 0, f"nginx -t failed after rendering {name}'s vhosts: {rc.stderr[-400:]}"
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    log(f"vhosts rendered for {name}: {written} (tls {'enabled' if with_tls else 'staged, acme enabled'})")
    return written


def issue_cert(name: str) -> str:
    """One certificate, four SANs, webroot ACME through the frame's acme vhost (DNS must resolve first)."""
    hosts = [f"{name}.{DOMAIN}", f"{name}-es.{DOMAIN}", f"{name}-spire.{DOMAIN}", f"{name}-push.{DOMAIN}"]
    live = Path(f"/etc/letsencrypt/live/{name}.{DOMAIN}/fullchain.pem")
    if live.exists():
        log(f"certificate present: {live}"); return str(live)
    # §FRAMEFORM showcase (2026-09-14): ask until each name answers, inside the runner's own propagation bound. One
    # question was not enough: after a name is asked before it exists (every plan asks), the anycast nodes behind
    # 1.1.1.1 disagree for up to the zone's negative TTL (1800 s), so hansa's standup stopped here a minute after its
    # runner had seen all four names answer (job 1892e9dbbc4c4187), on a node still serving "no such name".
    deadline = time.monotonic() + float(os.getenv("FRAME_DNS_WAIT_S", "300"))
    for h in hosts:
        asked = 0
        while True:
            asked += 1
            r = subprocess.run(["dig", "+short", "@1.1.1.1", h, "A"], capture_output=True, text=True)
            c = subprocess.run(["dig", "+short", "@1.1.1.1", h, "CNAME"], capture_output=True, text=True)
            if r.stdout.strip() or c.stdout.strip():
                break
            assert time.monotonic() < deadline, f"{h} does not resolve at 1.1.1.1 — DNS first (runbook §0.1)"
            time.sleep(5)
        if asked > 1:
            log(f"{h} answered at 1.1.1.1 on question {asked}")
    subprocess.run(["resolvectl", "flush-caches"], capture_output=True)
    cmd = ["certbot", "certonly", "--webroot", "-w", "/var/www/html", "--non-interactive", "--agree-tos",
           "--cert-name", f"{name}.{DOMAIN}"]
    for h in hosts:
        cmd += ["-d", h]
    rc = subprocess.run(cmd, capture_output=True, text=True)
    assert live.exists(), f"certbot did not produce {live}: {(rc.stdout + rc.stderr)[-600:]}"
    log(f"certificate issued for {', '.join(hosts)}")
    return str(live)


# ── the production side ───────────────────────────────────────────────────────────────────────────────────────────────
_WS_BLOCK = """    location /ws/events-{slug} {{
        proxy_pass http://127.0.0.1:{es_port}/ws/events;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400s;
    }}
"""


def apex_ws_routes(slug: str, es_port: int, vhosts=("theprotocol-apex", "api-theprotocol")) -> int:
    """The apex and api vhosts proxy /ws/events-<slug> to the frame's EventStore (the FE opens what the JSON names).
    Inserted before the first `location /ws/events…` block of every server block that has one; idempotent by the location line."""
    added = 0
    for v in vhosts:
        p = Path(NGINX_ENABLED) / v
        s = p.read_text()
        if f"location /ws/events-{slug} " in s:
            continue
        _bak(str(p), f"ws-{slug}")
        block = _WS_BLOCK.format(slug=slug, es_port=es_port)
        out, pos, n = [], 0, 0
        # anchor = the FIRST `location /ws/events…` block of each server block (the apex has no `/ws/` catch-all —
        # finding 43); nginx picks the longest matching prefix, so the order among the socket blocks is irrelevant
        anchors = [m for m in re.finditer(r"^    location /ws/events[^ ]* \{", s, re.M)]
        firsts, seen_server = [], set()
        for m in anchors:
            server_idx = s.count("server {", 0, m.start())
            if server_idx not in seen_server:
                seen_server.add(server_idx); firsts.append(m)
        for m in firsts:
            out.append(s[pos:m.start()]); out.append(block); pos = m.start(); n += 1
        out.append(s[pos:])
        assert n >= 1, f"{v}: no `location /ws/events…` block to anchor on"
        p.write_text("".join(out)); added += n
    if added:
        rc = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        assert rc.returncode == 0, f"nginx -t failed after the ws routes: {rc.stderr[-300:]}"
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    log(f"apex/api ws route /ws/events-{slug} → 127.0.0.1:{es_port}: {added} block(s) added")
    return added


def fresh_network_upsert(entry: Dict[str, Any], compose_path: str = PROD_COMPOSE) -> List[str]:
    """Upsert (by slug) one frame into registry-a's FRESH_NETWORK_JSON compose line. Applies at registry-a's next
    recreate — the driver SAYS so; it never recreates production."""
    p = Path(compose_path); s = p.read_text()
    m = re.search(r"^(\s+)FRESH_NETWORK_JSON: '(.*)'$", s, re.M)
    assert m, "FRESH_NETWORK_JSON line not found in the production compose"
    frames = json.loads(m.group(2))
    frames = [f for f in frames if f.get("slug") != entry["slug"]] + [entry]
    val = json.dumps(frames, separators=(",", ":")); assert "'" not in val
    _bak(compose_path, f"fresh-{entry['slug']}")
    p.write_text(s[:m.start()] + f"{m.group(1)}FRESH_NETWORK_JSON: '{val}'" + s[m.end():])
    log(f"FRESH_NETWORK_JSON: {[f['slug'] for f in frames]} (registry-a recreate PENDING — a deliberate, gated step)")
    return [f["slug"] for f in frames]


def prometheus_jobs(slug: str, env_label: str, operators: List[str], prom_path: str = PROM_YML, join=None) -> int:
    """Scrape jobs for the frame's registry / TEG / EventStore and each operator's registry / TEG, by container name (the
    Prometheus container joins the frame's network), idempotent by job_name; then a lifecycle reload.
    `join(container, net, aliases)` does the network join when given (sidecars.ensure_on_network: with the aliases the
    registry's code defaults resolve, §FRAMEKIT P3.1); the bare `docker network connect` otherwise."""
    p = Path(prom_path); s = p.read_text()
    jobs = [(f"{slug}-registry", f"{slug}-registry:8000", "registry", slug), (f"{slug}-teg", f"{slug}-teg:8080", "teg", slug),
            (f"{slug}-event-store", f"{slug}-event-store:8200", "event-store", slug)]
    for op in operators:
        jobs += [(f"{op}-registry", f"cloud-op-{op}-registry:8000", "registry", op), (f"{op}-teg", f"cloud-op-{op}-teg:8080", "teg", op)]
    add = ""
    for job, target, comp, frame in jobs:
        if f"job_name: '{job}'" in s:
            continue
        add += (f"  - job_name: '{job}'\n    scrape_interval: 15s\n    metrics_path: '/metrics'\n    static_configs:\n"
                f"      - targets: ['{target}']\n        labels: {{ component: '{comp}', frame: '{frame}', env: '{env_label}' }}\n")
    if add:
        _bak(prom_path, f"jobs-{slug}")
        p.write_text(s.rstrip("\n") + "\n" + add)
    n = add.count("job_name")
    # the Prometheus container must reach the frame's network by container name
    for net in (f"{slug.replace('-', '_')}_network",) + tuple(f"cloud-op-{op}_operator-net" for op in operators):   # provisioner:355
        if join is not None:
            join("agentvault-prometheus", net, [])
        else:
            subprocess.run(["docker", "network", "connect", net, "agentvault-prometheus"], capture_output=True)
    rl = subprocess.run(["docker", "exec", "agentvault-prometheus", "wget", "-q", "--post-data=", "-O", "-",
                         "http://localhost:9090/-/reload"], capture_output=True, text=True)
    log(f"prometheus: {n} job(s) added for {slug} (+{len(operators)} operators), reload rc={rl.returncode}")
    return n


AUDITOR_OVERRIDE_NAME = "docker-compose.override.yml"


def auditor_override_networks(auditor_dir: str) -> List[str]:
    """§MTLSHOPS (a) (2026-09-15, agentvault2-85's find): the frame networks the host auditor joins through its untracked
    compose override (render_auditor_override writes it; compose loads it beside the tracked docker-compose.yml)."""
    p = Path(auditor_dir) / AUDITOR_OVERRIDE_NAME
    if not p.exists():
        return []
    return list(dict.fromkeys(mm.group(1) for mm in re.finditer(r"^      - ([A-Za-z0-9_.-]+)\s*$", p.read_text(), re.M)))


def render_auditor_override(auditor_dir: str, service: str, networks: List[str]) -> Path:
    """§MTLSHOPS (a) (2026-09-15, agentvault2-85's find): a frame network the host auditor joins lives in an untracked
    docker-compose.override.yml, never in the tracked compose, where a revert, a stash or a clean rebuild would drop the
    join and blind that frame's database reads. Compose loads the override by default (no caller passes -f). With no
    networks left the file is removed."""
    p = Path(auditor_dir) / AUDITOR_OVERRIDE_NAME
    nets = sorted(dict.fromkeys(n for n in networks if n))
    if not nets:
        if p.exists():
            p.unlink()
        return p
    body = ["# Rendered by scripts/hetzner_demo/standup_extras.render_auditor_override: the frame networks the host auditor",
            "# joins. Untracked; compose loads it beside docker-compose.yml. Change it through the standup, not by hand.",
            "services:", f"  {service}:", "    networks:"]
    body += [f"      - {n}" for n in nets]
    body += ["networks:"]
    for n in nets:
        body += [f"  {n}:", "    external: true"]
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("\n".join(body) + "\n")
    os.replace(tmp, p)
    return p


def auditor_slot_shapes(admin_url: str, timeout: int = 15) -> List[str]:
    """§MTLSHOPS (a): the slot shapes the running host auditor lists on GET /api/auditor/modes (slot_shapes). An auditor that
    does not answer, or lists none, reads [], so no public_only or public_read slot is written for it."""
    try:
        with urllib.request.urlopen(f"{admin_url.rstrip('/')}/api/auditor/modes", timeout=timeout) as r:
            data = json.loads(r.read().decode() or "{}")
    except Exception:  # noqa: BLE001
        return []
    return [str(x) for x in (data.get("slot_shapes") or [])] if isinstance(data, dict) else []


def auditor_slot(slug: str, name: str, currency: str, es_container: str, es_db_container: str, mode: str = "sandbox",
                 teg_db_container: str = "", reg_db_container: str = "", frames_file: str = "",
                 admin_url: str = "http://127.0.0.1:8045", auditor_container: str = "auditor-agent",
                 auditor_service: str = "auditor-agent", public_url: str = "", public_only: bool = False,
                 public_read: bool = False) -> None:
    """The independent auditor audits the frame: one entry in AUDITOR_EXTRA_FRAMES_JSON (.env, 600, DSN + key read from the
    EventStore containers' env — never printed), the frame network joined in the compose, the auditor recreated.

    2026-09-09 (§EUASIAWIRING): the entry used to carry ONLY the EventStore address and key, so three of the
    auditor's checks were structurally blind on every frame this driver ever stood up:
      · teg_dsn  — without it `_staked_cross_check` returns None and the band reads "not checked". That is the
                   auditor's ONLY cross-store assertion; Delta compares the EventStore against itself, so a lock
                   deleted from one store and not the other keeps Delta at zero while the books diverge.
      · reg_dsn  — without it the AGORA share registry has nothing to read and listed stocks are simply absent.
      · fx_router_did — without it the FX router residue check cannot name the account it watches.
    Read from each DB container's own POSTGRES_* rather than a service DATABASE_URL, which may point at a pooler;
    a missing container is skipped and NAMED, never silently omitted."""
    def cenv(container: str) -> Dict[str, str]:
        out = subprocess.run(["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
                             capture_output=True, text=True).stdout
        return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    # §MTLSHOPS (a) (2026-09-15, his decision; agentvault2-85's calls): a public read goes to the frame's public supply audit
    # with no key; public_only also holds no DSN and joins no network. Such a slot is written only for a host auditor that
    # lists the shape (an older one fills a keyless slot's key with its mode key and sends this host's key to the frame's
    # address), and only through the frames file, never through the env carrier and a recreate.
    public_read = public_read or public_only
    shape = "public_only" if public_only else ("public_read" if public_read else "")
    if shape:
        _ff = Path(frames_file or (Path(AUDITOR_DIR) / "frames" / "frames.json"))
        if not public_url:
            raise ValueError(f"auditor_slot {slug}: a {shape} slot needs the frame's public es address")
        if not _ff.parent.is_dir():
            raise RuntimeError(f"auditor_slot {slug}: a {shape} slot is written through the frames file only ({_ff.parent} is absent)")
        if shape not in auditor_slot_shapes(admin_url):
            raise RuntimeError(f"auditor_slot {slug}: the running host auditor does not list the {shape} slot shape")
    e = {} if public_only else cenv(es_container)
    dsn = re.sub(r"^postgresql\+[a-z0-9]+://", "postgresql://", e.get("DATABASE_URL_SYNC") or e.get("DATABASE_URL", ""))
    key = e.get("INTERNAL_API_KEY", "")
    assert public_only or (dsn.startswith("postgresql://") and "@" in dsn and (key or public_read)), f"{es_container}: no DSN/key in its env"

    def db_dsn(container: str) -> str:
        """postgresql://user:pw@<container>:5432/db from the DB container's own env. The password is
        URL-encoded: an un-encoded '+' arrives as a space and '%'/'&' break the field (§FEDSYNCTRUTH-2)."""
        if not container:
            return ""
        d = cenv(container)
        u, pw, db = d.get("POSTGRES_USER", ""), d.get("POSTGRES_PASSWORD", ""), d.get("POSTGRES_DB", "")
        if not (u and pw and db):
            log(f"auditor_slot: {container} has no POSTGRES_USER/PASSWORD/DB — that check stays unwired")
            return ""
        return f"postgresql://{u}:{urllib.parse.quote(pw, safe='')}@{container}:5432/{db}"

    teg_dsn = "" if public_only else db_dsn(teg_db_container or f"{slug}-teg-db")
    reg_dsn = "" if public_only else db_dsn(reg_db_container or f"{slug}-db")
    fx_router_did = ""
    if reg_dsn:
        q = subprocess.run(["docker", "exec", "-i", reg_db_container or f"{slug}-db", "psql",
                            "-U", cenv(reg_db_container or f"{slug}-db").get("POSTGRES_USER", "registry"),
                            "-d", cenv(reg_db_container or f"{slug}-db").get("POSTGRES_DB", "frame_test_registry"),
                            "-tAc", "SELECT agent_did FROM agent_cards WHERE name = '@fx_router' "
                                    f"AND agent_did LIKE '%%:{slug}.%%' LIMIT 1;"],
                           capture_output=True, text=True)
        fx_router_did = (q.stdout or "").strip().splitlines()[0].strip() if q.returncode == 0 and q.stdout.strip() else ""
    log(f"auditor_slot: teg_dsn={'yes' if teg_dsn else 'NO'} reg_dsn={'yes' if reg_dsn else 'NO'} "
        f"fx_router_did={'yes' if fx_router_did else 'NO'}")
    entry = {"mode": mode, "id": slug, "name": name, "currency": currency, "url": f"http://{es_container}:8200", "dsn": dsn,
             "key": key, "teg_dsn": teg_dsn, "reg_dsn": reg_dsn, "fx_router_did": fx_router_did}
    if public_only:
        entry = {"mode": mode, "id": slug, "name": name, "currency": currency, "url": public_url.rstrip("/"), "public_only": True}
    elif public_read:
        entry.pop("key", None)
        entry.update({"url": public_url.rstrip("/"), "public_read": True})
    # §FRAMEKIT P3.1 (2026-09-12): the list lives in a FILE the auditor re-reads on POST /admin/reload-frames (no
    # recreate: a recreate re-audits every tier at once). The env carrier is written only when the running auditor
    # predates the route (404) — then the recreate is the only way the entry reaches it.
    ff = Path(frames_file or (Path(AUDITOR_DIR) / "frames" / "frames.json"))
    file_mode = ff.parent.is_dir()
    if file_mode:
        cur = json.loads(ff.read_text()) if ff.exists() and ff.read_text().strip() else []
        frames = [f for f in cur if f.get("id") != slug] + [entry]
        tmp = ff.with_suffix(".json.tmp"); tmp.write_text(json.dumps(frames, indent=1) + "\n"); tmp.chmod(0o600); os.replace(tmp, ff)
    else:
        envp = Path(AUDITOR_DIR) / ".env"; s = envp.read_text()
        m = re.search(r"^AUDITOR_EXTRA_FRAMES_JSON=(.*)$", s, re.M)
        frames = json.loads(m.group(1)) if m and m.group(1).strip() else []
        frames = [f for f in frames if f.get("id") != slug] + [entry]
        line = "AUDITOR_EXTRA_FRAMES_JSON=" + json.dumps(frames, separators=(",", ":"))
        s = re.sub(r"^AUDITOR_EXTRA_FRAMES_JSON=.*$", lambda _m: line, s, flags=re.M) if m else s.rstrip("\n") + "\n" + line + "\n"
        envp.write_text(s); envp.chmod(0o600)
    comp = Path(AUDITOR_DIR) / "docker-compose.yml"; t = comp.read_text()
    net = f"{slug.replace('-', '_')}_network"   # the provisioner's rule (frame_test_provisioner.py:355): sbx-alpha -> sbx_alpha_network
    # §MTLSHOPS (a) (2026-09-15, agentvault2-85's find): the join lives in the untracked compose override, never in the
    # tracked compose; a frame the tracked file already names (a join from before this change) keeps it there.
    if not public_only and f"      - {net}\n" not in t:
        joined = auditor_override_networks(AUDITOR_DIR)
        if net not in joined:
            render_auditor_override(AUDITOR_DIR, auditor_service, joined + [net])
    if "AUDITOR_EXTRA_FRAMES_JSON" not in t:
        _bak(str(comp), "extra-frames")
        t = comp.read_text()
        anchor = "      SBX_EVENT_STORE_KEY:"
        assert anchor in t, "auditor compose: SBX_EVENT_STORE_KEY anchor"
        t = t.replace(anchor, "      AUDITOR_EXTRA_FRAMES_JSON: ${AUDITOR_EXTRA_FRAMES_JSON:-[]}\n" + anchor, 1)
        comp.write_text(t)
    rc = subprocess.run(["docker", "compose", "config", "-q"], cwd=AUDITOR_DIR, capture_output=True, text=True)
    assert rc.returncode == 0, f"auditor compose invalid: {rc.stderr[-300:]}"
    # the live join (the override above keeps it across a recreate); then the reload, else the recreate
    if not public_only:
        subprocess.run(["docker", "network", "connect", net, auditor_container], capture_output=True)
    st, body = auditor_reload(admin_url, _auditor_admin_token(AUDITOR_DIR)) if file_mode else (0, "")
    if st == 200:
        joined_note = "no network joined" if public_only else f"network {net} joined"
        log(f"auditor: slot {slug} ({mode}, {currency}{', ' + shape if shape else ''}) written to {ff.name}, {joined_note}, "
            f"reloaded in place: {body[:160]}")
        return
    if shape:
        raise RuntimeError(f"auditor_slot {slug}: the host auditor did not reload the {shape} slot (it answered {st}); "
                           f"no fallback to the env carrier and a recreate")
    if file_mode:
        # an older auditor (404) or one with no admin token (503): the env carrier is what it boots from
        envp = Path(AUDITOR_DIR) / ".env"; s = envp.read_text()
        m = re.search(r"^AUDITOR_EXTRA_FRAMES_JSON=(.*)$", s, re.M)
        line = "AUDITOR_EXTRA_FRAMES_JSON=" + json.dumps(frames, separators=(",", ":"))
        s = re.sub(r"^AUDITOR_EXTRA_FRAMES_JSON=.*$", lambda _m: line, s, flags=re.M) if m else s.rstrip("\n") + "\n" + line + "\n"
        envp.write_text(s); envp.chmod(0o600)
        log(f"auditor: reload answered {st} ({str(body)[:80]}) — the env carrier was written and the auditor is recreated instead")
    subprocess.run(["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", auditor_service], cwd=AUDITOR_DIR,
                   capture_output=True, text=True)
    log(f"auditor: slot {slug} ({mode}, {currency}) written, network {net} joined, auditor recreated")


def _auditor_admin_token(auditor_dir: str) -> str:
    """AUDITOR_ADMIN_TOKEN from the auditor's own .env, by NAME; never logged."""
    p = Path(auditor_dir) / ".env"
    if not p.exists():
        return ""
    m = re.search(r"^AUDITOR_ADMIN_TOKEN=(.*)$", p.read_text(), re.M)
    return (m.group(1).strip().strip('"') if m else "")


def auditor_reload(admin_url: str, token: str, timeout: int = 90) -> Tuple[int, str]:
    """POST /api/auditor/admin/reload-frames. (status, body): 200 applied · 404 an auditor older than the route ·
    503 no admin token set · 0 unreachable. Never raises."""
    if not admin_url:
        return 0, "no admin url"
    req = urllib.request.Request(f"{admin_url.rstrip('/')}/api/auditor/admin/reload-frames", method="POST",
                                 headers={"X-Auditor-Admin": token or "", "Content-Type": "application/json"}, data=b"{}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200]
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"[:200]


BUNDLE_LIST = "/etc/theprotocol/fresh-federated-bundle.list"


def bundle_list_append(pem_path: str, path: str = BUNDLE_LIST) -> bool:
    """Register a frame's SPIRE bundle PEM with the host cron that concatenates the federated bundle
    (`/usr/local/bin/fresh-federated-bundle.sh`, §BATCH10). Idempotent; returns True when added."""
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    lines = [l.strip() for l in p.read_text().splitlines()] if p.exists() else []
    if pem_path in lines:
        return False
    p.write_text("\n".join([*lines, pem_path]) + "\n"); p.chmod(0o640)
    return True


def sni_route(name: str, fed_port: int) -> int:
    """The frame's line in the host SNI stream map (`<name>.<domain> → 127.0.0.1:<nginx-federation port>`), written by the
    product's own `scripts/extend_stream_sni_map.sh` (idempotent, validates + reloads nginx). Without it the frame's mTLS
    federation address falls through to Frame A's nginx and every peer's card pull dies on CERTIFICATE_VERIFY_FAILED
    (finding 48). Returns the script's rc (0 = present)."""
    script = str(Path(__file__).resolve().parents[1] / "extend_stream_sni_map.sh")
    rc = subprocess.run(["bash", script, f"{name}.{DOMAIN}", str(fed_port)], capture_output=True, text=True)
    log(f"SNI route {name}.{DOMAIN} → 127.0.0.1:{fed_port}: rc={rc.returncode} {(rc.stdout or rc.stderr).strip().splitlines()[-1][:100] if (rc.stdout or rc.stderr).strip() else ''}")
    assert rc.returncode == 0, f"extend_stream_sni_map.sh failed rc={rc.returncode}: {rc.stderr[-200:]}"
    return rc.returncode


def identity_nets_append(net: str, path: str = IDENTITY_NETS_FILE) -> bool:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    nets = [l.strip() for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    if net in nets:
        return False
    p.write_text("\n".join(nets + [net]) + "\n"); log(f"identity nets: {net} appended to {path}")
    return True


def ops_secret_file(frame_name: str, slug: str, record: Dict[str, Any]) -> str:
    """ONE shape: sessionlogs2026/.<frame>_ops.secret.json = {slug: {admin_email, admin_password, registry_port, domain,
    federation_license_key}} (600). Values come from the provisioning response; nothing is printed."""
    path = Path(SECRETS_DIR) / f".{frame_name.lower()}_ops.secret.json"
    d = json.loads(path.read_text()) if path.exists() else {}
    d[slug] = {k: record.get(k) for k in ("admin_email", "admin_password", "registry_port", "domain", "federation_license_key")}
    path.write_text(json.dumps(d, indent=1)); path.chmod(0o600)
    log(f"operator secrets for {slug} written to {path.name} (password present: {bool(record.get('admin_password'))})")
    return str(path)


def image_constant(image: str, timeout: int = 90):
    """The BUNDLED_IMAGE_TAG constant inside a registry image, or None. §HELLOFRAME: a release image ships bytecode only
    (no .py to grep), so the constant is IMPORTED from the image first; the source grep stays as the fallback for an image
    whose import needs an env this probe does not carry. ONE reader: the driver's tag derivation and version_gate share it."""
    try:
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "python3", image, "-c",
                              "import sys; sys.path.insert(0, '/app/src'); "
                              "from agentvault_registry.core.registry_identity import BUNDLED_IMAGE_TAG; print(BUNDLED_IMAGE_TAG)"],
                             capture_output=True, text=True, timeout=timeout).stdout.strip().splitlines()
        tag = out[-1].strip() if out else ""
        if re.fullmatch(r"[A-Za-z0-9._-]{4,80}", tag):
            return tag
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", image, "-c",
                              "grep -o 'BUNDLED_IMAGE_TAG = \"[^\"]*\"' /app/src/agentvault_registry/core/registry_identity.py"],
                             capture_output=True, text=True, timeout=timeout).stdout
        m = re.search(r'"([^"]+)"', out or "")
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001 — a probe that cannot answer returns None, and the caller says so
        return None


def version_gate(registry_base: str, image: str) -> str:
    """The card's software_version must END with the image's own BUNDLED_IMAGE_TAG (the env carrier could lie)."""
    tag = image_constant(image); assert tag, f"no BUNDLED_IMAGE_TAG in {image} (neither importable nor greppable)"
    st, card = http("GET", f"{registry_base}/.well-known/registry-card.json")
    ver = str(((card or {}).get("identity") or {}).get("software_version") or "")
    assert st == 200 and ver.endswith(tag), f"version gate: card says {ver!r}, image constant {tag!r}"
    log(f"version gate: card {ver[-6:]} = image constant {tag[-6:]}")
    return tag


# ── the card, the jurisdiction, the operators' cards ──────────────────────────────────────────────────────────────────
def card_extras(card_json_path: Optional[str]) -> Dict[str, Any]:
    """tags · links (never github_source) · commitments · display_name, merged over the driver's card body."""
    if not card_json_path:
        return {}
    d = json.loads(Path(card_json_path).read_text())
    allowed = {"display_name", "tags", "links", "commitments", "description", "operator"}
    extra = {k: v for k, v in d.items() if k in allowed}
    if "links" in extra:
        extra["links"] = {k: v for k, v in extra["links"].items() if k != "github_source" and v}
    return extra


def put_jurisdiction(registry_base: str, headers: Dict[str, str], profile_path: Optional[str]) -> Optional[int]:
    if not profile_path:
        return None
    profile = json.loads(Path(profile_path).read_text())
    st, r = http("PUT", f"{registry_base}/api/v1/admin/jurisdiction-profile", profile, headers=headers, timeout=30)
    assert st == 200, f"jurisdiction profile PUT {st}: {str(r)[:200]}"
    st2, cur = http("GET", f"{registry_base}/api/v1/admin/jurisdiction-profile", headers=headers)
    log(f"jurisdiction profile: {profile.get('name')} v{profile.get('version')} PUT {st} (read back {st2})")
    return st


def put_operator_card(op_base: str, admin_email: str, admin_password: str, body: Dict[str, Any]) -> int:
    """PUT the operator's own registry card as its admin: operator {display_name, location_label, latitude, longitude},
    description, tags, links (no github). Read back the served card and assert the location landed."""
    st, r = http("POST", f"{op_base}/api/v1/auth/login", {"username": admin_email, "password": admin_password}, form=True)
    assert st == 200 and r.get("access_token"), f"operator admin login {st}"
    H = {"Authorization": f"Bearer {r['access_token']}"}
    if "links" in body:
        body["links"] = {k: v for k, v in body["links"].items() if k != "github_source" and v}
    st, r = http("PUT", f"{op_base}/api/v1/admin/registry-card", body, headers=H)
    assert st == 200, f"operator card PUT {st}: {str(r)[:200]}"
    st, card = http("GET", f"{op_base}/.well-known/registry-card.json")
    op = (card or {}).get("operator") or {}
    want = body.get("operator") or {}
    assert st == 200 and str(op.get("location_label")) == str(want.get("location_label")), \
        f"operator card location not served: {op.get('location_label')!r} vs {want.get('location_label')!r}"
    log(f"operator card: {want.get('location_label')} ({want.get('latitude')}, {want.get('longitude')}) served")
    return st


# ── canaries: two local paths so the rails fire ───────────────────────────────────────────────────────────────────────
def seed_local_canary_paths(registry_base: str, headers: Dict[str, str], db_container: str, db_name: str, db_user: str,
                            frame_slug: str, count: int = 2, amount: str = "1.000000", interval_sec: int = 120) -> int:
    """Create `count` sender/receiver agent pairs under the admin, seed the senders from the treasury, insert canary_paths
    rows (backend intra) — the runner in local mode reads its own table. Idempotent by path_id."""
    made = 0
    for i in range(1, count + 1):
        pid = f"{frame_slug}-local-{i}"
        exists = subprocess.run(["docker", "exec", db_container, "psql", "-U", db_user, "-d", db_name, "-tAc",
                                 f"select count(*) from canary_paths where path_id='{pid}'"], capture_output=True, text=True).stdout.strip()
        if exists == "1":
            continue
        ids = []
        for role in ("sender", "receiver"):
            st, r = http("POST", f"{registry_base}/api/v1/onboard/bootstrap/request-token", {}, headers=headers)
            bt = (r or {}).get("bootstrap_token"); assert bt, f"bootstrap token {st}"
            hri = f"canary/{frame_slug}-{i}-{role}"
            card = {"protocolVersion": "1.0", "name": f"Canary {frame_slug} {i} {role}", "description": "local canary path agent (§BATCH10)",
                    "humanReadableId": hri, "agentVersion": "1.0.0", "url": f"https://{frame_slug}.{DOMAIN}/agents/{hri.split('/')[1]}",
                    "authSchemes": [{"scheme": "none"}], "capabilities": {},
                    "skills": [{"id": "canary", "name": "Canary", "description": "answers canary fires", "tags": ["canary"]}],
                    "provider": {"name": "TheProtocol canaries", "url": f"https://{frame_slug}.{DOMAIN}"}}
            st, r = http("POST", f"{registry_base}/api/v1/onboard/create_agent", {"agent_did_method": "theprotocol", "agent_card": card},
                         headers={"Bootstrap-Token": bt})
            assert st in (200, 201), f"canary agent {role} {st}: {str(r)[:160]}"
            did = r.get("agent_did") or r.get("did")
            # the create response carries the credentials ONCE — read them BEFORE the funding call reuses `r` (finding 41)
            cid, csec = (r.get("client_id") or ""), (r.get("client_secret") or "")
            if role == "sender":
                st, r = http("POST", f"{registry_base}/api/v1/teg/treasury/fund-agent",
                             {"target_agent_did": did, "amount": "500.000000", "reason": "canary sender float (§BATCH10)", "reference_id": f"canary-{pid}"},
                             headers=headers, timeout=90)
                assert st == 200, f"canary sender fund {st}"
            # §BATCH10 finding 38/40: the paths reference canary_agents (the runner's own roster with the agent's client
            # credentials, mirrored from the product's sandbox_canary_bootstrap.upsert_canary_agent), never `agents`.
            assert cid and csec, f"canary agent {role}: the create response carried no client credentials"
            csql = ("insert into canary_agents (agent_did, client_id, client_secret, registry_id, registry_url, frame, is_active, prefund_amount, notes, created_at) "
                    f"values ($q${did}$q$, $q${cid}$q$, $q${csec}$q$, $q${frame_slug}-registry$q$, $q$http://{frame_slug}-registry:8000$q$, "
                    f"$q$frame-{frame_slug}$q$, true, 500, $q$canary-{pid}-{role}$q$, now()) "
                    "on conflict (agent_did) do update set client_id = excluded.client_id, client_secret = excluded.client_secret, is_active = true "
                    "returning id")
            crc = subprocess.run(["docker", "exec", db_container, "psql", "-U", db_user, "-d", db_name, "-v", "ON_ERROR_STOP=1", "-tAc", csql],
                                 capture_output=True, text=True)
            aid = (crc.stdout.strip().splitlines() or [""])[0].strip()   # psql -c prints the RETURNING row, then the command tag
            assert crc.returncode == 0 and aid.isdigit(), f"canary_agents upsert for {role} failed: rc={crc.returncode} out={crc.stdout[:80]!r} err={crc.stderr[-200:]}"
            ids.append(aid)
        # columns read from the live table (§BATCH10 finding 38): is_active, transport default 'bearer'; the count() above is the dedup
        sql = (f"insert into canary_paths (path_id, sender_agent_id, receiver_agent_id, backend, amount, interval_sec, is_active, created_at) "
               f"values ('{pid}', {ids[0]}, {ids[1]}, 'intra', {amount}, {interval_sec}, true, now())")
        rc = subprocess.run(["docker", "exec", db_container, "psql", "-U", db_user, "-d", db_name, "-v", "ON_ERROR_STOP=1", "-c", sql],
                            capture_output=True, text=True)
        assert rc.returncode == 0, f"canary_paths insert failed: {rc.stderr[-300:]}"
        made += 1
    log(f"canary paths on {frame_slug}: {made} created ({count} wanted)")
    return made


# ── the testers' fixture posture ──────────────────────────────────────────────────────────────────────────────────────
TESTER_FIXTURE_ENV: Dict[str, str] = {
    # §APITEST (2026-09-03) ported: the API/MCP testers' fixture configuration, minus OPA, fiat secrets and the old topology
    "SANDBOX_MODE": "true", "SANDBOX_BYPASS_RATE_LIMIT": "true",
    # CB-320: no RATE_LIMIT_PUBLIC / _DEVELOPER / _AGENT here. The registry reads them into a table nothing consults
    # (slowapi limits per route); SANDBOX_BYPASS_RATE_LIMIT is what turns this frame's limiter off.
    "EXCHANGE_ENABLED": "true", "FORGE_ENABLED": "true", "PHONE_FABRIC_ENABLED": "true", "FEDERATION_ENABLED": "true",
    "EVENT_STORE_ENABLED": "true", "A2A_DID_JWT_AUTOGEN": "true", "ATTESTATION_SCHEDULE_CRON_ENABLED": "true",
    "ATTESTATION_SCHEDULE_CRON_INTERVAL_SECONDS": "3600", "OPERATOR_CLI_AUDIT_EMIT_ENABLED": "true",
    "ZKP_PHASE_1_ENABLED": "true", "ZKP_PHASE_2_ENABLED": "true", "ZKP_PHASE_3_ENABLED": "true", "ZKP_PHASE_4_ENABLED": "true",
    "ZKP_PHASE_5_ENABLED": "true", "ZKP_PHASE_6_ENABLED": "true", "ZKP_BUNDLE_SIGNING_ENABLED": "true",
    "ZKP_BUNDLE_VALID_DAYS": "90", "ZKP_DEFAULT_EXPIRY_DAYS": "90",
    "FX_FEE_PCT": "0.5", "FX_SLIPPAGE_MAX": "0.02", "FX_BREAKER_PCT": "0.05", "FX_BREAKER_WINDOW_SEC": "300",
    "API_TEST_EXECUTION_ENABLED": "true", "API_TEST_SHARED_PREREQS": "true",
    "MCP_TESTER_SWEEP_CONCURRENCY": "8", "MCP_TESTER_PROBE_CONCURRENCY": "8", "MCP_TESTER_LIFECYCLE_CONCURRENCY": "6",
    "MCP_TESTER_FED_CONCURRENCY": "4", "GUNICORN_TIMEOUT": "900",
    # §TESTBED (2026-09-19): the rails the MCP tester's contracts expect to answer, on as they are on the network's own
    # sandbox (sbx-alpha), so a kit sandbox's baseline is comparable to ours. Measured on the first kit sandbox run
    # (larchsbx, 758 tools): with these off the sweep read 12 extra reds, every one a switched-off rail and none a defect:
    # the admin simulation (8), fiat (3: FIAT_GENESIS_REGISTRY makes the frame the fiat genesis, as on sbx-alpha),
    # legacy contracts (2, off in the kit template by D8). A sandbox is where these may run; a production frame keeps its own.
    "ADMIN_SIMULATION_ENABLED": "true", "FIAT_ONRAMP_ENABLED": "true", "FIAT_GENESIS_REGISTRY": "true",
    "LEGACY_CONTRACTS_ENABLED": "true",
}


def tester_fixture_env() -> Dict[str, str]:
    return dict(TESTER_FIXTURE_ENV)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# §FRAMELIC (2026-09-07) — what a PRODUCTION standup needs that the rehearsal did by hand.
# His word: service accounts instead of the Commander, a frame licence from the anchor, the frame's
# OWN showcase, and "jurisdiction everything approve as DEMO similar to registry-a but you can refine".
# ══════════════════════════════════════════════════════════════════════════════════════════════════

# The four concerns a standup touches, and the authority each one actually needs. One developer per
# concern, per frame — each its own `security_audit_logs` actor and independently revocable, so a
# leaked sim credential cannot provision an operator and a leaked provisioning credential cannot
# move the market. `agents_unlisted_by_default` is on for all four: everything these accounts create
# is infrastructure, and infrastructure has no business in a visitor's discovery results.
SERVICE_ACCOUNTS: Dict[str, Dict[str, Any]] = {
    "svc-provisioning": {
        "purpose": "creates the system agents and provisions operators",
        "flags": {"admin_federation": True},
    },
    "svc-sim": {
        "purpose": "owns the EigenTrust simulation roster and its funding",
        "flags": {"admin_treasury": True},
    },
    "svc-canary": {
        "purpose": "owns the canary senders and receivers",
        "flags": {"admin_treasury": True},
    },
    "svc-market": {
        "purpose": "owns the seeded market listings and the market maker",
        "flags": {"admin_treasury": True},
    },
}


def _service_account_password(length: int = 28) -> str:
    """A password that MEETS the registration policy by construction, not by luck.

    `secrets.token_urlsafe` draws from [A-Za-z0-9_-], which contains no character the registry
    counts as special — so two of four service accounts were refused with 422 "Password must
    contain at least one special character" and two happened to pass, which is worse than all four
    failing because it looks like a flake. Build one of each required class first, then fill.

    The special set is §SBROTATE's: `$ # \' " ` \\ | ; { } [ ] < > , . :` are excluded because they
    are eaten by .env parsing and compose ${} interpolation, and these credentials are written to
    files that both read.
    """
    import string
    specials = "!@%^&*()_+-=?"
    pools = [string.ascii_uppercase, string.ascii_lowercase, string.digits, specials]
    chars = [secrets.choice(p) for p in pools]
    alphabet = "".join(pools)
    chars += [secrets.choice(alphabet) for _ in range(max(0, length - len(pools)))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def developer_id_by_email(registry_base: str, admin_headers: Dict[str, str], email: str) -> Optional[int]:
    """Ask the server for a developer's id. Never infer it from a response that may not carry one.

    🔴 MEASURED 2026-09-08 on the live EU/ASIA cluster. `POST /auth/register` answers
    `RegistrationResponse`, which is `{message, recovery_keys}` and has NEVER carried an id — so
    `(r or {}).get("id") or (r or {}).get("developer_id")` was None on every standup this driver has
    ever run, and the `if dev_id:` guarding the next two calls silently skipped BOTH of them for all
    four service accounts, on every frame ever stood up. The evidence: zero `DeveloperAdminFlags`
    audit rows on either frame, `svc-provisioning` without the `admin_federation` doctrine says it
    holds, and `agents_unlisted_by_default` false on all eight accounts — while this function logged
    "created, agents hidden by default" for each one. A `.get()` on a key that does not exist is
    indistinguishable from a key whose value is null, and both look exactly like a working standup.
    """
    q = urllib.parse.urlencode({"search": email, "limit": 50, "include_federated": "false"})
    st, r = http("GET", f"{registry_base}/api/v1/admin/developers?{q}", headers=admin_headers)
    if st != 200 or not isinstance(r, dict):
        log(f"!! developer lookup for {email}: {st} ({str(r)[:160]})")
        return None
    for d in (r.get("developers") or []):
        if isinstance(d, dict) and (d.get("email") or "").lower() == email.lower():
            try:
                return int(d["id"])
            except (KeyError, TypeError, ValueError):
                return None
    log(f"!! developer lookup for {email}: 200 but no exact match in {len(r.get('developers') or [])} rows")
    return None


def write_frame_admin_secret(frame_name: str, admin_email: str, admin_password: str,
                             registry_port: Any = None, domain: Optional[str] = None,
                             stack_dir: Optional[str] = None) -> str:
    """Persist the FRAME ADMIN beside the service accounts, mode 600.

    The password was never actually lost — the driver writes it to `<stack_dir>/.env.frame-test`
    (600) as FIRST_ADMIN_PASSWORD, and `prod_seed.py` seeds the admin from exactly that. What it
    was not, was WHERE every other frame credential lives. On 2026-09-08 a session needing ASIA's
    frame admin looked in `sessionlogs2026/`, found only a stale `.eu_asia_accounts.secret.json`
    from a torn-down rehearsal pair, and concluded the account had none — then reset both frames'
    admins to recover access they already had. One file in the expected place is the whole fix;
    a credential that exists but cannot be found is, operationally, a credential that does not.
    """
    path = Path(SECRETS_DIR) / f".{frame_name.lower()}_frame_admin.secret.json"
    body = {
        "admin_email": admin_email,
        "admin_password": admin_password,
        "registry_port": registry_port,
        "domain": domain,
        "stack_dir": stack_dir,
        "note": ("Frame admin, seeded by prod_seed.py from FIRST_ADMIN_* in the stack's "
                 ".env.frame-test. This file is the discoverable copy, not a second source of truth."),
    }
    path.write_text(json.dumps(body, indent=1))
    os.chmod(path, 0o600)
    return str(path)


def create_service_accounts(
    registry_base: str, admin_headers: Dict[str, str], frame_slug: str,
    *, only: Optional[List[str]] = None, invite_codes: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    """Create this frame's four purpose-named service developers. HIS DECISION 2026-09-07:
    *"i want to do all the onboarding not with the commander account i want special service accounts"*.

    The frame admin CREATES them and then does not run the standup. Each gets only the admin flags
    its own rail needs, and `agents_unlisted_by_default=true` so its agents never reach discovery —
    which is also his *"option to hide system agents like eigentrust sim agents fx router etc"*.

    Returns {name: {email, password, developer_id}}. The caller writes them to a 600 secret file;
    they are never logged.

    `invite_codes` ({name: code}): a registry with BETA_INVITE_REQUIRED refuses a registration that carries no
    code (measured 2026-09-22 on the sandbox operators: 403 "Beta access requires an invite code"). The admin
    issues one single-use code per account (POST /api/v1/admin/invite-codes/generate) and passes it here; a code
    is never logged.
    """
    out: Dict[str, Dict[str, str]] = {}
    wanted = only or list(SERVICE_ACCOUNTS)
    for name in wanted:
        spec = SERVICE_ACCOUNTS[name]
        email = f"{name}@{frame_slug}.svc"
        password = _service_account_password()
        body = {"name": f"{name}-{frame_slug}", "email": email, "password": password}
        if (invite_codes or {}).get(name):
            body["invite_code"] = invite_codes[name]
        st, r = http("POST", f"{registry_base}/api/v1/auth/register", body)
        if st not in (200, 201):
            # Already there from an earlier attempt: keep going, but say so — a standup that
            # silently reuses an account whose password we do not hold is a standup that will
            # fail three steps later with an unexplained 401.
            log(f"service account {name}: register {st} ({str(r)[:120]}) — NOT created here")
            continue
        # The register response carries no id (see developer_id_by_email) — read it back.
        dev_id = (r or {}).get("id") or (r or {}).get("developer_id") \
            or developer_id_by_email(registry_base, admin_headers, email)
        if not dev_id:
            # LOUD, not a shrug: without the id this account gets none of its authority and none
            # of its posture, and every symptom appears three steps later as an unexplained 403.
            log(f"!! service account {name}: no developer id — FLAGS AND VERIFY SKIPPED "
                f"(it holds none of {sorted(spec['flags'])} and its agents are NOT hidden)")
        # verify the email through the admin rail so the account can log in
        if dev_id:
            # §LANTERNT3 (2026-09-16): the path was `force-verify-email`; the route is
            # `force-email-verify` (admin_developers.py:691). Two words transposed, 404 on every standup since
            # it was written, and NOTHING READ THE STATUS — the sibling admin-flags PUT below checks its own and
            # says so loudly, this one did not. It stayed invisible because a sandbox-posture frame runs with
            # REQUIRE_EMAIL_VERIFICATION off, so an unverified service account logs in anyway. The first
            # production-posture frame found it immediately: all four service accounts locked out of their own
            # frame, `Login blocked: developer 2 unverified` in the registry log.
            # 400 "already verified" is a success for our purposes; anything else is a real refusal.
            stv, rv = http("POST", f"{registry_base}/api/v1/admin/developers/{dev_id}/force-email-verify",
                           {}, headers=admin_headers)
            if stv != 200 and not (stv == 400 and "already verified" in str(rv).lower()):
                log(f"!! service account {name}: force-email-verify {stv} ({str(rv)[:160]}) — this account "
                    f"CANNOT LOG IN on a frame that requires email verification")
            flags = dict(spec["flags"])
            flags["agents_unlisted_by_default"] = True
            st2, r2 = http("PUT", f"{registry_base}/api/v1/admin/developers/{dev_id}/admin-flags",
                           flags, headers=admin_headers)
            if st2 != 200:
                log(f"!! service account {name}: admin-flags PUT {st2} ({str(r2)[:160]}) — "
                    f"this account has NO authority and its agents are NOT hidden")
        out[name] = {"email": email, "password": password, "developer_id": str(dev_id or "")}
        log(f"service account {name} ({spec['purpose']}) — created"
            + (", agents hidden by default" if dev_id else " WITHOUT flags (see above)"))
    return out


def mint_fx_router(
    registry_base: str, svc_headers: Dict[str, str], frame_slug: str, currency: str, public_url: str = "",
) -> str:
    """Create this frame's `@fx_router` transit agent and return its DID. (findings row 191)

    🔴 THE FLAG WAS NEVER THE MISSING PIECE — THE IDENTITY WAS. `frame-test.env.tmpl` shipped
    `FX_ROUTE_ENABLED=true` for months while nothing ever created this agent, so the route engine
    refused at its first check on every frame ever stood up and no cloud operator could originate a
    cross-currency transfer. §FXSTRAND made the template honest (flag false, R9 gate); this is the
    other half — the standup now CREATES the identity, so the flag can be true and mean it.

    Created by `svc-provisioning`, never the Commander, and its agents are unlisted by default, so
    the router does not appear in discovery (his *"option to hide system agents … fx router"*).

    ⚠ THE CREDENTIAL IS DELIBERATELY NOT RETURNED OR STORED — his standing word. The rail issues a
    registry JWT server-side when it needs to act as the router (`get_teg_token_for_agent`), and the
    admin sweep rail acts as it without one; nothing needs the client_secret, so nothing keeps it.
    """
    st, tok = http("POST", f"{registry_base}/api/v1/onboard/bootstrap/request-token",
                   {"agent_type_hint": "system"}, headers=svc_headers)
    bt = (tok or {}).get("bootstrap_token") if isinstance(tok, dict) else None
    if st not in (200, 201) or not bt:
        log(f"!! fx_router: bootstrap {st}: {str(tok)[:200]}")
        return ""
    card = {
        "schemaVersion": "1.0", "humanReadableId": f"system/{frame_slug}-fx-router",
        "agentVersion": "1.0.0", "name": "@fx_router",
        "description": (f"Cross-frame FX transit account for {frame_slug.upper()}. Holds {currency} "
                        f"in flight for one hop of a cross-currency route and nothing else."),
        "provider": {"name": f"{frame_slug.upper()} frame"},
        "capabilities": {"a2aVersion": "1.0"},
        "authSchemes": [{"scheme": "none"}],
        "tags": ["system", "fx", frame_slug],
        # §ONESHOT F6 (2026-09-12): the card validator (since §CARDLINK) requires an endpoint, so an issuance
        # without one answered 400 and every frame stood up since 09-08 was born with NO FX router — the
        # §FXSTRAND shape the issuance exists to prevent. The address must be SERVED, READ, or not published
        # (§CARDLINK): the FX rail this identity belongs to is public and answers 200, so it is that.
        # (EU's router, created before the validator tightened, was hand-given `/system/fx-router`, which the
        # frame answers 404 — the dead-address class on a system card nobody lists.)
        "url": f"{(public_url or registry_base).rstrip('/')}/api/v1/teg/fx/rates",
    }
    st, res = http("POST", f"{registry_base}/api/v1/onboard/create_agent",
                   {"agent_card": card, "agent_did_method": "theprotocol"},
                   headers={"Bootstrap-Token": bt})
    did = (res or {}).get("agent_did") if isinstance(res, dict) else None
    if st not in (200, 201) or not did:
        log(f"!! fx_router: create_agent {st}: {str(res)[:240]}")
        return ""
    log(f"fx_router created for {frame_slug}: {did[-12:]} (credential discarded, by his standing word)")
    return did


def mint_showcase_payer(
    registry_base: str, svc_headers: Dict[str, str], frame_slug: str, currency: str, public_url: str = "",
) -> Dict[str, str]:
    """Create this frame's showcase PAYER and return {did, client_id, client_secret} (empty dict on failure).

    ⚠ WHY A FRAME NEEDS ITS OWN (measured 2026-09-26): every showcase call on EU answered 402. The public rail
    (`/api/v1/public/showcase/call`, used by /services, the service runner embedded in /blueprints, the landing
    page and /monetize) logs in as the payer (`SHOWCASE_PPAO_CLIENT_ID` / `_SECRET`), authorizes an A2A payment,
    and calls the agent with that token. No standup ever created a payer, so the login answered 422, no token was
    issued, the agent refused, and the rail fell back to its relay: `SHOWCASE_RELAY_URL`, default
    api.theprotocol.cloud, the frame that used to host the payer. Since §APEXEU that name serves EU itself, so EU
    relayed to itself and answered 502. A frame that runs showcase agents pays for its own demo calls.

    Created by `svc-provisioning` (never the Commander; unlisted by default like every system agent). Unlike the
    FX router this credential IS needed and returned: the registry logs in as the payer on every call, so it
    goes into the frame's env file (0600, read by the registry alone) and nowhere else. Never log the result.
    """
    st, tok = http("POST", f"{registry_base}/api/v1/onboard/bootstrap/request-token",
                   {"agent_type_hint": "system"}, headers=svc_headers)
    bt = (tok or {}).get("bootstrap_token") if isinstance(tok, dict) else None
    if st not in (200, 201) or not bt:
        log(f"!! showcase payer: bootstrap {st}: {str(tok)[:200]}")
        return {}
    base = (public_url or registry_base).rstrip("/")
    card = {
        "schemaVersion": "1.0", "humanReadableId": f"system/{frame_slug}-showcase-payer",
        "agentVersion": "1.0.0", "name": "@showcase_payer",
        "description": (f"Pays for the public showcase's demo calls on {frame_slug.upper()} in {currency}, so a "
                        f"visitor can try a service agent without an account. Holds a small float and nothing else."),
        "provider": {"name": f"{frame_slug.upper()} frame"},
        "capabilities": {"a2aVersion": "1.0"},
        "authSchemes": [{"scheme": "none"}],
        "tags": ["system", "showcase", frame_slug],
        # §CARDLINK: an address must be SERVED, READ, or not published. This identity belongs to the public
        # showcase rail, whose catalog answers 200 there.
        "url": f"{base}/api/v1/public/showcase/agents",
    }
    st, res = http("POST", f"{registry_base}/api/v1/onboard/create_agent",
                   {"agent_card": card, "agent_did_method": "theprotocol"},
                   headers={"Bootstrap-Token": bt})
    ok = st in (200, 201) and isinstance(res, dict) and res.get("agent_did") and res.get("client_id") \
        and res.get("client_secret")
    if not ok:
        # a refused create carries no credential; still print only the status and the error's own words
        detail = (res or {}).get("detail") if isinstance(res, dict) else None
        log(f"!! showcase payer: create_agent {st}: {str(detail)[:200]}")
        return {}
    log(f"showcase payer created for {frame_slug}: {res['agent_did'][-12:]} (credential kept for the env file only)")
    return {"did": res["agent_did"], "client_id": res["client_id"], "client_secret": res["client_secret"]}


def showcase_payer_env_lines(payer: Dict[str, str]) -> List[Tuple[str, str]]:
    """The env keys the showcase rail reads (main.py), and the relay turned off: a frame with its own payer relays
    nowhere (the default relay names api.theprotocol.cloud, which since §APEXEU is EU itself)."""
    return [("SHOWCASE_PPAO_DID", payer["did"]), ("SHOWCASE_PPAO_CLIENT_ID", payer["client_id"]),
            ("SHOWCASE_PPAO_CLIENT_SECRET", payer["client_secret"]), ("SHOWCASE_RELAY_URL", "")]


def fund_agent_in_pieces(registry_base: str, admin_headers: Dict[str, str], did: str, total: str, piece: str,
                         reference: str) -> Decimal:
    """Fund `did` from the treasury through the canonical admin rail (FLOW 4), `piece` at a time up to `total`.
    Each piece carries its own Idempotency-Key, so a retried piece cannot pay twice. Returns what landed."""
    landed, tot, pc = Decimal("0"), Decimal(str(total)), Decimal(str(piece))
    n = 0
    while landed < tot:
        amt = min(pc, tot - landed)
        n += 1
        st, res = http("POST", f"{registry_base}/api/v1/teg/treasury/fund-agent",
                       {"target_agent_did": did, "amount": str(amt), "reason": "admin_grant",
                        "reference_id": f"{reference}:{n}"},
                       headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())})
        if st not in (200, 201):
            log(f"!! fund {did[-12:]} piece {n}: {st} {str((res or {}).get('detail') if isinstance(res, dict) else res)[:160]}")
            break
        landed += amt
    log(f"funded {did[-12:]} with {landed} of {tot} in {n} piece(s) of at most {pc}")
    return landed


def issue_frame_license(
    anchor_base: str, anchor_headers: Dict[str, str], *,
    frame_name: str, frame_trust_domain: str, tier: str = "sovereign",
) -> Optional[str]:
    """§FRAMELIC — the ANCHOR issues a joining frame its federation licence, before the frame exists.

    The invitation approve path issues one automatically at the handshake; this is the other order,
    which is the one a planned standup uses: EU issues ASIA's licence, the driver seeds it into
    ASIA's env as FEDERATION_LICENSE_KEY, and ASIA is licensed from its very first boot rather than
    from its first federation. Returns the plain key ONCE (never logged).
    """
    body = {
        "operator_name": frame_name,
        "operator_did": f"spiffe://{frame_trust_domain}",
        "licensee_type": "frame",
        "federation_tier": tier,
        "max_agents": 100000,
        "max_events_per_minute": 100000,
    }
    st, r = http("POST", f"{anchor_base}/api/v1/admin/federation/licenses/generate", body,
                 headers=anchor_headers, timeout=30)
    if st not in (200, 201):
        log(f"frame licence for {frame_name}: generate {st} ({str(r)[:200]})")
        return None
    key = (r or {}).get("license_key")
    log(f"frame licence issued to {frame_name} ({(r or {}).get('license_id')}), "
        f"tier={tier}, prefix={(key or '')[:12]}")
    return key


# ── the DEMO jurisdiction profile, complete ───────────────────────────────────────────────────────
# His word: "jurisdiction everything aprove as DEMO similar to registry-a but you can refine".
# registry-a publishes four regulated actions in SHADOW plus four authorizations with reference ids
# and evidence hashes. Two refinements over it: the authority is named for THIS frame (registry-a
# says "Frame-A Demo Authority" on every frame that copied it), and the reference ids carry the
# frame so two frames' attestations are never confusable.
REGULATED_ACTIONS = ("exchange.ipo", "exchange.listing", "fiat.lane", "registry.operation")
# mirrors services/regulatory_auth._DEFAULT_SCOPE — a per-subject act declared at registry scope
# would be a different claim, so the two must not drift
_DEFAULT_SCOPE = {"exchange.listing": "per_subject", "exchange.ipo": "per_subject",
                  "fiat.lane": "registry", "registry.operation": "registry"}
_REF_SLUG = {"exchange.ipo": "IPO", "exchange.listing": "EXCH",
             "fiat.lane": "FIAT", "registry.operation": "REG"}


def demo_jurisdiction_profile(
    *, frame_label: str, profile_name: str, jurisdiction_label: str,
    authority: str, features: Optional[Dict[str, bool]] = None,
    max_transfer_amount: int = 250000, version: int = 1,
) -> Dict[str, Any]:
    """The profile document the VALIDATOR accepts — which is not the shape the CARD publishes.

    ⚠ The first cut of this built the card's OUTPUT shape (`features_denied`, `declared_by`,
    `regulated_actions`) and the PUT answered 422 "unknown top-level key" on all three, because
    those are DERIVED views: `features_denied` is the false entries of `features`, and
    `regulated_actions` is how the card renders `requires_authorization`. `services/jurisdiction.py`
    accepts exactly `name · version · features · limits · declared_at · note ·
    requires_authorization`, and `declared_at` is stamped server-side. Read the validator, never
    the rendered card.

    Mode is `shadow` on every action: a DEMO authority must never be able to BLOCK a real act, and
    shadow is what keeps the published claim honest — declared, not asserted.
    """
    return {
        "name": profile_name,
        "version": version,
        "features": dict(features or {
            "exchange": True, "fx": True, "guild": True,
            "forge": True, "fiat": False, "cross_transfer": True,
        }),
        "limits": {"max_transfer_amount": max_transfer_amount},
        "note": (f"DEMONSTRATION jurisdiction profile for {frame_label} ({jurisdiction_label}). "
                 f"Every regulated action is declared in SHADOW under {authority}, a demo "
                 f"authority: the declaration is published and auditable, and it gates nothing. "
                 f"It asserts nothing about any real regulator."),
        "requires_authorization": {
            action: {
                "authority": authority,
                "scope": _DEFAULT_SCOPE[action],
                "mode": "shadow",
                "note": f"DEMO — declared by {frame_label}, not a real regulatory approval",
            }
            for action in REGULATED_ACTIONS
        },
    }


def demo_authorizations(
    *, frame_label: str, jurisdiction_label: str, authority: str, valid_days: int = 365,
) -> List[Dict[str, Any]]:
    """One attestation per regulated action. `evidence_hash` is a hash of THIS frame's own
    declaration text — a real hash of a real (demo) document, never a copied constant, so two
    frames never publish the same evidence for different claims."""
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=valid_days)
    out = []
    for action in REGULATED_ACTIONS:
        doc = (f"DEMO AUTHORIZATION\nframe={frame_label}\naction={action}\n"
               f"authority={authority}\njurisdiction={jurisdiction_label}\ndeclared={now.isoformat()}\n"
               f"This is a DEMONSTRATION attestation on a demonstration network. It asserts nothing "
               f"about any real regulator.\n")
        out.append({
            "action": action,
            "authority": authority,
            "jurisdiction": jurisdiction_label,
            "reference_id": f"DEMO-2026/{frame_label.upper()}-{_REF_SLUG[action]}-0001",
            "valid_from": now.isoformat(),
            "valid_until": until.isoformat(),
            "evidence_hash": "sha256:" + hashlib.sha256(doc.encode()).hexdigest(),
            "evidence_note": f"DEMO attestation for {frame_label} — not a real regulatory approval",
        })
    return out


def put_regulatory_authorizations(
    registry_base: str, headers: Dict[str, str], records: List[Dict[str, Any]],
) -> int:
    """Record each authorization. Idempotent by reference_id at the rail; a 409 is a pass."""
    ok = 0
    for rec in records:
        # PART 1 rule 4 — a 404 is verified against the ROUTER, never guessed: the admin router is
        # mounted at /api/v1/admin/jurisdiction-profile (routers/admin_jurisdiction.py:29), so the
        # authorizations live UNDER it. My first guess dropped the "-profile" and 404'd four times.
        st, r = http("POST", f"{registry_base}/api/v1/admin/jurisdiction-profile/authorizations",
                     rec, headers=headers, timeout=30)
        if st in (200, 201):
            ok += 1
        elif st == 409:
            ok += 1
            log(f"authorization {rec['reference_id']}: already recorded")
        else:
            log(f"authorization {rec['reference_id']}: POST {st} ({str(r)[:200]})")
    log(f"regulatory authorizations: {ok}/{len(records)} recorded")
    return ok


# ── §FRAMELIC (2026-09-07, findings row 158) ────────────────────────────────────────────────
def assert_real_svid(frame: str, stack_dir: str, log=print, recreate: bool = True) -> bool:
    """Refuse to leave a frame whose registry is running on a MOCK identity.

    MEASURED on the EU standup: the registry container starts, retries the SPIRE Workload API
    for a few seconds, gets `no identity issued` because its own agent has not attested yet,
    and falls back to mock SVIDs — logging **"Mock SVID Client initialized successfully"**. The
    agent issued the real SVID **12 seconds later** (`Creating X509-SVID … spiffe://<td>/service/registry`)
    and nothing asked again: the fallback latches for the life of the container.

    The frame then looks entirely healthy — `/health` 200, card served, console up, operators
    provisioned — and federates with NOBODY, because every outbound mTLS call goes out certless
    and every peer's edge answers `400 No required SSL certificate was sent`. The only visible
    symptom is `Federation sync cycle completed: 0/3 successful` in a log nobody reads at 3am.
    One `--force-recreate` of the registry fixed it on both frames: `SVID Client initialized
    successfully with real SVIDs`, and sync went to 3/5 within one cycle.

    ⚠ THE SIGNAL MUST BE THE CONTAINER'S LOG, NOT A PROBE. A fresh `docker exec python` that
    calls `svid_client.initialize()` gets a REAL SVID (the agent is issuing by then) and would
    report health while the running app holds mock — the §V0221 unloaded-singleton trap, inverted.
    The metric does not discriminate either: `registry_svid_last_poll_unixtime` reads 0.0 in both
    states. What the app logged at ITS startup is the only honest answer.
    """
    import subprocess as _sp
    import time as _t

    cname = f"{frame}-registry"

    def _state():
        r = _sp.run(["docker", "logs", cname], capture_output=True, text=True, timeout=120)
        blob = (r.stdout or "") + (r.stderr or "")
        real = blob.count("initialized successfully with real SVIDs")
        mock = blob.count("Mock SVID Client initialized")
        return real, mock

    real, mock = _state()
    if real and not mock:
        log(f"[svid] {cname}: real SVIDs ({real} workers) — federation can present a client cert")
        return True

    log(f"[svid] !! {cname} is on MOCK SVIDs (real={real} mock={mock}) — it would federate with "
        f"nobody: every peer's mTLS edge answers 400 'No required SSL certificate was sent'")
    if not recreate:
        return False

    log(f"[svid] recreating {cname} now that its SPIRE agent is issuing")
    _sp.run(["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
             "-v", f"{stack_dir}:{stack_dir}", "-w", stack_dir, "docker:cli", "sh", "-c",
             "docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test "
             f"up -d --no-deps --no-build --force-recreate {cname}"],
            capture_output=True, text=True, timeout=600)
    for _ in range(12):
        _t.sleep(10)
        real, mock = _state()
        # a recreate replays the whole log, so judge on the LAST initialisation, not the counts
        r2 = _sp.run(["docker", "logs", "--since", "3m", cname], capture_output=True, text=True, timeout=120)
        recent = (r2.stdout or "") + (r2.stderr or "")
        if "initialized successfully with real SVIDs" in recent and "Mock SVID Client initialized" not in recent:
            log(f"[svid] {cname}: real SVIDs after recreate")
            return True
    log(f"[svid] !! {cname} STILL on mock after a recreate — this frame cannot federate. "
        f"Check `docker exec {frame}-spire-agent /opt/spire/bin/spire-agent api fetch x509 "
        f"-socketPath /opt/spire/sockets/agent.sock` and the registry's entry selector "
        f"(`docker:label:com.agentvault.service:registry-{frame}`).")
    return False


# ── §FRAMELIC (2026-09-07, findings row 159) ────────────────────────────────────────────────
def join_tester_network(frame: str, stack_dir: str, network: str, log=print) -> bool:
    """Give the frame's registry a DIRECT lane to the tester's target, in the compose.

    Row 146 found that driving the API/MCP tester through a PUBLIC vhost subjects every call to
    that vhost's `proxy_read_timeout`: the first sweep from EU's console died at five minutes with
    `504 Gateway Time-out … nginx/1.24.0`. The tester's calls are long by design; nginx's timeout
    is not. The fix was a direct container lane — and it was applied BY HAND to the pair, so the
    teardown took it with it and the next standup had no lane at all. That is the third time this
    batch that a hand-fix died with its frame (the SNI line, the bundle cron, the logo), which is
    why it lives here now: *"update the driver. so if we might have to reprovision clean we can do
    it again smoothly, not like this."*

    The join goes in the COMPOSE, not just `docker network connect`, or it does not survive the
    next `--force-recreate`.

    ⚠ The registry service's `networks:` is a MAPPING whose entries carry `aliases:` bodies, so a
    new key must go AFTER a previous entry's body, not between the key and its body. I broke this
    file exactly that way while writing this function — the same shape as row 142, where a
    line-oriented edit left valid-looking wreckage that surfaced two frames later. Hence the rule
    this function enforces: **edit, then let the file's own tool judge it, and revert if it says no.**
    """
    import shutil
    import subprocess as _sp
    from pathlib import Path

    comp = Path(stack_dir) / "docker-compose.frame-test.yml"
    text = comp.read_text()
    if f"{network}:" in text and network in text.split("\nnetworks:")[-1]:
        log(f"[tester-lane] {network} already joined")
    else:
        bak = comp.with_name(comp.name + ".bak-pre-testerlane")
        shutil.copy(comp, bak)
        lines = text.split("\n")
        out, done_service, i = [], False, 0
        while i < len(lines):
            line = lines[i]
            out.append(line)
            # inside the registry service, find its `networks:` and append after the LAST entry
            if not done_service and line.strip() == "networks:" and line.startswith("    "):
                i += 1
                while i < len(lines) and (lines[i].startswith("      ") or not lines[i].strip()):
                    out.append(lines[i]); i += 1
                out.append(f"      {network}: {{}}")
                done_service = True
                continue
            i += 1
        text2 = "\n".join(out)
        # and declare it external at the top level
        text2 = text2.replace("\nnetworks:\n", f"\nnetworks:\n  {network}:\n    external: true\n", 1)
        comp.write_text(text2)
        r = _sp.run(["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
                     "-v", f"{stack_dir}:{stack_dir}", "-w", stack_dir, "docker:cli", "sh", "-c",
                     "docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test config -q"],
                    capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            shutil.copy(bak, comp)
            log(f"[tester-lane] !! compose refused the edit — REVERTED. {(r.stderr or '')[:200]}")
            return False
        log(f"[tester-lane] {network} joined in the compose (validated)")

    _sp.run(["docker", "network", "connect", network, f"{frame}-registry"],
            capture_output=True, text=True, timeout=120)
    r = _sp.run(["docker", "inspect", f"{frame}-registry", "--format",
                 "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}"],
                capture_output=True, text=True, timeout=60)
    ok = network in (r.stdout or "")
    log(f"[tester-lane] {frame}-registry on {network}: {ok}")
    return ok


def _sh(argv):
    """(rc, stdout) — the driver's small shell helper."""
    import subprocess as _sp
    r = _sp.run(argv, capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or "")


# ── §MTLSGAP (2026-09-08) — A FRAME CANNOT BE MINTED WITH A PLAINTEXT RAIL ────────────────────
# His word: *"it can never mint a frame like this."* Every instance of this class was invisible
# for the same reason: a hop with no gateway raises nothing, logs nothing and passes every health
# check. The EventStore had no gateway on ANY frame this driver has ever built — because the
# template rendered two sidecars and never a third — and nobody noticed for as long as nobody
# looked. So the driver LOOKS, at the end of every standup, and refuses to call the frame live if
# a rail is open.
#
# ⚠ THIS IS A CENSUS, NOT AN ASSERTION ABOUT CONFIG. R10 in the template contract already refuses
# a template with no ES sidecar; that is a claim about a file. This asks the RUNNING frame which
# gateways exist and what each one does with a client certificate, because the two can disagree
# (a service that is defined and not started, a conf mounted from a path that does not exist, a
# cert-writer that never wrote). Config is an argument; a handshake is evidence.

# §SOVKIT (2026-09-14): the Directory's read leg is a gateway too (ssl_verify_client on)
MTLS_REQUIRED_SIDECARS = ("nginx-federation", "nginx-teg", "nginx-event-store", "directory-nginx")


def mtls_census(name: str) -> dict:
    """Which gateways this frame has, and what each does with a client certificate."""
    out: dict = {"present": {}, "verify": {}, "missing": [], "open": []}
    for svc in MTLS_REQUIRED_SIDECARS:
        c = f"{name}-{svc}"
        rc, st = _sh(["docker", "inspect", c, "--format", "{{.State.Status}}"])
        running = (rc == 0 and st.strip() == "running")
        out["present"][svc] = running
        if not running:
            out["missing"].append(svc)
            continue
        # ⚠ STRIP COMMENTS FIRST. A source-reading gate finds its OWN DOCUMENTATION: the ES
        # sidecar conf explains in prose why `ssl_verify_client on` matters, and the first draft
        # of this census matched that sentence — so a conf that merely MENTIONS the directive in a
        # comment would have passed as if it set it. Third instance of this class in the tree
        # (§JSONCAST-3, §EMITKEY): prose next to a rule names the CLASS, never the setting.
        rc, conf = _sh(["docker", "exec", c, "sh", "-c",
                        "sed 's/#.*//' /etc/nginx/conf.d/*.conf 2>/dev/null | grep ssl_verify_client"])
        v = " ".join(conf.split()) if rc == 0 else ""
        out["verify"][svc] = v or "(none)"
        # the template renders `ssl_verify_client on` on every terminator (§MTLSHOPS T1); this flags only a
        # terminator with no ssl_verify_client at all, an OPEN rail.
        if "ssl_verify_client" not in v:
            out["open"].append(svc)
    return out


def assert_card_addresses(registry_url: str, log=print) -> None:
    """Refuse the standup if a card it published advertises an address that is not there.

    §CARDLINK (2026-09-08). His report: *"the link on the registry cards are wrong … dont provide
    a link for them that is dead."* Measured on EU: THIRTY of thirty-four listed cards published
    a 404 — the eleven showcase agents (the frame never served the address Frame A's nginx serves
    by hand) and the eleven sovereigns (their endpoint was CONSTRUCTED from a hand-written path).

    ⚠ THIS IS A GATE AND NOT A NOTE BECAUSE THE INSTRUMENT AGREED WITH THE DEFECT. The
    agent-health worker probed `scheme://host/health` — the FRAME's own page, 200 by definition —
    and called all thirty `healthy`. A standup that asks only "is the frame up" cannot see this.

    404/410 is the only "not there". A 405 (GET on a JSON-RPC route) and a 402 (an unpaid A2A
    call) both mean the address EXISTS and answered, which is the question a published endpoint
    has to survive.
    """
    import urllib.error as _ue, urllib.parse as _up, urllib.request as _ur

    def _answers(url):
        for m in ("HEAD", "GET"):
            try:
                with _ur.urlopen(_ur.Request(url, method=m), timeout=12) as r:
                    return (r.status not in (404, 410)), f"{m} {r.status}"
            except _ue.HTTPError as e:
                if e.code in (404, 410):
                    continue
                return True, f"{m} {e.code}"
            except Exception as e:
                return False, f"{m} {type(e).__name__}"
        return False, "404"

    base = registry_url.rstrip("/")
    try:
        with _ur.urlopen(f"{base}/api/v1/agent-cards/discover?limit=100", timeout=25) as r:
            items = (json.loads(r.read().decode()) or {}).get("items") or []
    except Exception as exc:
        raise SystemExit(f"[cards] REFUSING — cannot read discover on {base}: {exc}")
    if not items:
        # An empty population proves nothing about the addresses; say so instead of passing.
        log("[cards] NOT MEASURED — nothing is listed on this frame yet")
        return
    dead, checked = [], 0
    for it in items:
        try:
            with _ur.urlopen(f"{base}/api/v1/agent-cards/"
                             f"{_up.quote(str(it.get('id')), safe='')}", timeout=20) as r:
                cd = (json.loads(r.read().decode()) or {}).get("card_data") or {}
        except Exception:
            continue
        urls = [cd.get("url")] + [i.get("url") for i in (cd.get("supportedInterfaces") or [])
                                  if isinstance(i, dict)]
        urls = [u for u in urls if u and str(u).startswith("https://")]
        if not urls:
            continue
        checked += 1
        good, why = _answers(urls[0])
        if not good:
            dead.append(f"{it.get('name')} -> {urls[0]} ({why})")
    if dead:
        raise SystemExit(
            f"[cards] REFUSING TO CALL {base} LIVE — {len(dead)} of {checked} published addresses "
            f"do not answer:\n  " + "\n  ".join(dead[:12]) +
            "\nA card is a published claim. Serve the address (runbook §16.2), read it from the "
            "agent's own card (§16.3), or do not publish one.")
    log(f"[cards] {checked} published addresses, all answering")


def assert_mtls_everywhere(name: str, log=print) -> None:
    """Refuse the standup if a rail has no gateway, or a gateway does not ask for a certificate."""
    c = mtls_census(name)
    for svc in MTLS_REQUIRED_SIDECARS:
        log(f"[mtls] {name}-{svc}: "
            + ("MISSING" if svc in c["missing"] else c["verify"].get(svc, "?")))
    if c["missing"] or c["open"]:
        raise SystemExit(
            f"[mtls] REFUSING TO CALL {name} LIVE — "
            + (f"no gateway for: {c['missing']}. " if c["missing"] else "")
            + (f"gateway asks for no client certificate: {c['open']}. " if c["open"] else "")
            + "Every rail a peer or a writer reaches must terminate mTLS. The EventStore had no "
              "gateway on every frame built before 2026-09-08 and nothing reported it, which is "
              "why this is a gate and not a note (§MTLSGAP, runbook §15).")
    log(f"[mtls] {name}: all {len(MTLS_REQUIRED_SIDECARS)} rails terminate mTLS")


# An OPERATOR is a different shape: it has no EventStore of its own (it writes to its parent's
# ledger through the TEG balance outbox), so it has TWO sidecars, not three. What it must ALSO be
# true of is the direction nobody looks at — the address it uses to reach its PARENT.
MTLS_REQUIRED_OP_SIDECARS = ("nginx-federation", "nginx-teg")
_PARENT_ADDRESS_KEYS = ("CENTRAL_REGISTRY_URL", "MAINFRAME_PUBLIC_URL", "MAINFRAME_PROXY_URL")


def assert_operator_mtls(slug: str, log=print) -> None:
    """Refuse an operator whose gateways are open, or which reaches its parent in plaintext.

    §MTLSGAP row 203 (2026-09-08). Measured on all four operators of the EU/ASIA cluster:
    `CENTRAL_REGISTRY_URL` was an INTERNAL docker name (plaintext, and unresolvable — an operator
    shares no network with its frame) and `MAINFRAME_PUBLIC_URL` was NOT SET, so
    `operator_portal_actions._mainframe_base()` fell through to its hardcoded
    `https://api.theprotocol.cloud`: every operator pointed its portal actions at **Frame A**, a
    frame being retired that was never its parent. Nobody found out because a wrong parent still
    answers 200.

    ⚠ Also checks the registry HOLDS an SVID. It is the client half of every mutual hop the
    operator makes — its parent's EventStore vhost runs `ssl_verify_client optional`, so a
    certless operator is silently downgraded to the shared-key rail rather than refused.
    """
    c = f"cloud-op-{slug}-registry"
    problems = []
    for svc in MTLS_REQUIRED_OP_SIDECARS:
        sc = f"cloud-op-{slug}-{svc}"
        rc, st = _sh(["docker", "inspect", sc, "--format", "{{.State.Status}}"])
        if rc != 0 or st.strip() != "running":
            problems.append(f"no {svc} gateway")
            continue
        rc, conf = _sh(["docker", "exec", sc, "sh", "-c",
                        "sed 's/#.*//' /etc/nginx/conf.d/*.conf 2>/dev/null | grep ssl_verify_client"])
        v = " ".join(conf.split()) if rc == 0 else ""
        log(f"[mtls] cloud-op-{slug}-{svc}: {v or '(none)'}")
        if "ssl_verify_client" not in v:
            problems.append(f"{svc} asks for no client certificate")
    rc, env = _sh(["docker", "inspect", c, "--format", "{{range .Config.Env}}{{println .}}{{end}}"])
    plain = [l for l in env.splitlines()
             if l.split("=", 1)[0] in _PARENT_ADDRESS_KEYS and l.split("=", 1)[-1].startswith("http://")]
    if plain:
        problems.append(f"plaintext parent address: {[l.split('=',1)[0] for l in plain]}")
    if not any(l.startswith("MAINFRAME_PUBLIC_URL=https://") for l in env.splitlines()):
        problems.append("MAINFRAME_PUBLIC_URL unset — the portal falls back to a literal that "
                        "names ANOTHER frame (api.theprotocol.cloud)")
    rc, _ls = _sh(["docker", "exec", c, "sh", "-c", "ls /certs/svid.0.pem /certs/svid.0.key"])
    if rc != 0:
        problems.append("the registry holds no SVID — it cannot present a client certificate, and "
                        "its parent's ES vhost (`ssl_verify_client optional`) silently downgrades "
                        "it to the shared-key rail instead of refusing it")
    if problems:
        raise SystemExit(f"[mtls] REFUSING TO CALL cloud-op-{slug} LIVE — " + "; ".join(problems)
                         + " (§MTLSGAP row 203, runbook §15)")
    log(f"[mtls] cloud-op-{slug}: both rails terminate mTLS, parent reached over TLS, SVID held")


# ── §FRAMESHOWCASE: a genesis issuance larger than the registry's per-call ceiling ──────────────────────────────────────────
# His word 2026-09-14 ("your recommendation. but not cap at 1m"): the driver issues in pieces. hansa asked for 5,000,000;
# the registry's mint rail refused the single call (TEG_MINT_MAX_AVT is 1,000,000 in a runner-built frame's network
# profile) and the driver logged the refusal and went on, so the frame came up with an empty treasury until the rest was
# issued by hand. The ceiling is asked of the running registry, never assumed: its validator reads
# money_knob("TEG_MINT_MAX_AVT", "100000000"), and the frame's env or network profile decides the answer.
MINT_CEILING_FALLBACK = Decimal("1000000")
_CEILING_PY = ("from agentvault_registry.core.network_profile import knob_source, money_knob; "
               "print(money_knob('TEG_MINT_MAX_AVT', '100000000'), knob_source('TEG_MINT_MAX_AVT') or 'code-default')")


def registry_mint_ceiling(name: str, run=subprocess.run) -> Tuple[Decimal, str]:
    """(ceiling, where it came from) as the frame's own registry answers; the fallback, and saying so, when it cannot."""
    try:
        done = run(["docker", "exec", "-w", "/app", "-e", "PYTHONPATH=/app/src", f"{name}-registry",
                    "python", "-c", _CEILING_PY], capture_output=True, text=True, timeout=60)
        words = ((done.stdout or "").strip().splitlines() or [""])[-1].split()
        ceiling = Decimal(words[0]) if done.returncode == 0 and words else None
        if ceiling is not None and ceiling > 0:
            return ceiling, f"the registry ({words[1] if len(words) > 1 else 'source not said'})"
        detail = f"rc={done.returncode} {((done.stderr or done.stdout) or '').strip()[-120:]}"
    except (OSError, subprocess.SubprocessError, ArithmeticError, IndexError) as exc:
        detail = str(exc)[:120]
    return MINT_CEILING_FALLBACK, f"not read ({detail}); the fallback"


def mint_in_pieces(post, amount, ceiling, reason: str, minted_before="0", on_piece=None):
    """Issue `amount` through the registry's issuance rail in pieces no larger than `ceiling`.

    `post(amount_text, reason_text)` makes one issuance call and answers (status, body). After every accepted piece
    `on_piece(total_minted)` runs, so a run that dies half way has recorded exactly what landed; a resume passes that
    total back as `minted_before` and issues only the rest. A refused piece stops at once.
    Returns (total issued, pieces accepted in this call, None), or the same with "HTTP <status>: <body>" last.
    """
    total, ceiling, minted = Decimal(str(amount)), Decimal(str(ceiling)), Decimal(str(minted_before))
    if total <= 0 or ceiling <= 0 or minted < 0 or minted > total:
        raise ValueError(f"cannot issue {total} in pieces of at most {ceiling} after {minted}")
    count = int(((total - minted) / ceiling).to_integral_value(rounding=ROUND_CEILING))
    made = 0
    while minted < total:
        piece = min(ceiling, total - minted)
        status, body = post(format(piece, "f"), f"{reason} (part {made + 1} of {count})")
        if status != 200:
            return minted, made, f"HTTP {status}: {str(body)[:300]}"
        minted += piece
        made += 1
        if on_piece is not None:
            on_piece(minted)
    return minted, made, None
