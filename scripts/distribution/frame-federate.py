#!/usr/bin/env python3
"""frame-federate.py — federate THIS frame with a peer, from the frame's own host (§HELLOFRAME D2, 2026-09-18).

Run as root on the host that runs the frame (it uses `docker cp` and `docker exec` on the frame's own containers).
Python 3.11, standard library only.

    frame-federate.py --stack-dir /opt/theprotocol/stack/<frame>-<ts> --with https://<peer console> \
        [--peer-bundle-endpoint https://<peer>-spire.<domain>/] [--contact-email you@example.org] \
        [--admin-secret-file /path/.<frame>_frame_admin.secret.json] [--description "one line"] [--timeout-min 20] \
        [--fresh] [--no-licence] [--dry-run]

What it does, one printed line per step:
  1. reads the frame's facts from <stack>/.env.frame-test and its rendered compose (the registry name, the trust domain,
     the SPIRE server container, the registry's loopback port, the terminators that carry /certs/bundle.0.pem);
  2. GETs the peer's /.well-known/registry-card.json and takes identity.trust_domain and federation.spire_bundle_endpoint
     (or --peer-bundle-endpoint); refuses a docker-internal or unresolvable endpoint with a sentence; --dry-run stops here;
  3. fetches the peer's bundle from that endpoint, stages it into the SPIRE server container (`docker cp`; the SPIRE image
     is distroless, there is no shell to `cat` into), `spire-server bundle set`, then the federation relationship exactly
     as the registry's own approve rail derives it (https_spiffe, endpoint spiffe://<td>/spire/server), then every
     service and operator workload entry gains `-federatesWith spiffe://<td>` (the registry's federate_frame_workload_entries);
  4. waits until every terminator's /certs/bundle.0.pem carries more roots (the cert-writer's REFRESH_SEC cycle; a peer
     whose CA is rotating publishes two);
  5. logs in as the frame admin over loopback and asks the frame's own admin endpoint to create the OUTBOUND invitation
     (POST /api/v1/admin/federation/frame-invitations/outbound with spire_bundle_imported=true), printing the id the
     PEER assigned; a re-run resumes an earlier invitation to the same peer instead (--fresh sends a new one);
  6. polls that invitation until the peer's admin approved it and the callback completed it, then prints the peer row
     and the licence prefix (a rejection is mailed to the contact and never reaches this frame: the wait times out);
  7. takes the delivered licence key once (GET .../frame-invitations/<id>/licence-key), writes it into the stack's env
     file as FEDERATION_LICENSE_KEY and recreates the registry alone (--no-licence stops before this).
The printed lines are [1/7] to [7/7]; PUBLIC_DOCS/FRAME_FEDERATION.md lists every call both frames make, in order.

The peer's bundle is fetched with TLS verification OFF: that is the posture the registry's approve rail uses for the
same fetch (frame_trust_manager.fetch_remote_bundle), because a SPIRE bundle endpoint presents a SPIRE-issued
certificate no public CA signs; what the fetch returns is exactly what `bundle set` is told to trust, so the address you
pass here is the trust decision. The admin password is read from the secret file by shape, held in memory, sent only in
the login form over loopback, and never printed or placed on a command line.

Exit codes: 0 done · 2 refused before touching anything · 3 a step failed · 4 a wait timed out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

SPIRE_BIN = "/opt/spire/bin/spire-server"
FEDERATION_PROFILE = "https_spiffe"          # frame_trust_manager.FEDERATION_PROFILE_DEFAULT
BUNDLE_FILE = "bundle.0.pem"                 # what every cert-writer keeps fresh under the frame's cert dir
CARD_PATH = "/.well-known/registry-card.json"
API = "/api/v1"
DEFAULT_REFRESH_SEC = 300
ROOT_WAIT_MARGIN_SEC = 30
POLL_SEC = 5
HTTP_TIMEOUT = 20


class Refused(Exception):
    """Nothing was touched; the message is one sentence a beginner can act on."""


class StepFailed(Exception):
    """A step ran and failed; the message says which and what to look at."""


class TimedOut(Exception):
    """A wait ran out; the message names the clock that decides it."""


# ── 1. the frame's own facts ───────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Facts:
    stack_dir: str
    name: str
    trust_domain: str
    spire_container: str
    registry_port: int
    refresh_sec: int
    cert_dir: str
    terminators: List[str] = field(default_factory=list)   # containers whose /certs/bundle.0.pem must gain the root
    missing: List[str] = field(default_factory=list)       # expected terminators the compose does not name


def parse_env(text: str) -> Dict[str, str]:
    """KEY=VALUE lines of a compose env file; quotes stripped; comments and blanks ignored. Values are never printed
    by this program; the caller reads the few keys it needs by name."""
    out: Dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def compose_container_names(compose_text: str) -> List[str]:
    return re.findall(r"^\s*container_name:\s*([A-Za-z0-9._-]+)\s*$", compose_text or "", re.M)


def registry_loopback_port(compose_text: str) -> Optional[int]:
    """The host port the registry publishes on loopback (`127.0.0.1:<port>:8000`), the way standup_federate reads it."""
    m = re.search(r'127\.0\.0\.1:(\d+):8000"?', compose_text or "")
    return int(m.group(1)) if m else None


def frame_facts(stack_dir: str, env_text: str, compose_text: str) -> Facts:
    env = parse_env(env_text)
    name = env.get("REGISTRY_NAME") or env.get("FT_REG_REGISTRY_NAME") or ""
    if not name:
        raise Refused(f"{stack_dir}/.env.frame-test names no REGISTRY_NAME; is this a frame stack directory?")
    td = env.get("SPIRE_TRUST_DOMAIN") or env.get("FT_SPIRE_TRUST_DOMAIN") or ""
    if not td:
        raise Refused(f"{stack_dir}/.env.frame-test names no SPIRE_TRUST_DOMAIN; a frame cannot federate without one.")
    spire = env.get("FT_REG_SPIRE_CONTAINER") or f"{name}-spire-server"
    port = registry_loopback_port(compose_text)
    if not port:
        raise Refused(f"{stack_dir}/docker-compose.frame-test.yml publishes no registry port on 127.0.0.1 "
                      f"(a line like '127.0.0.1:<port>:8000' under the registry service).")
    try:
        refresh = int(env.get("FT_CW_REFRESH_SEC") or DEFAULT_REFRESH_SEC)
    except ValueError:
        refresh = DEFAULT_REFRESH_SEC
    cert_dir = env.get("FT_CERT_DIR") or "/certs"
    names = set(compose_container_names(compose_text))
    wanted = [f"{name}-nginx-federation", f"{name}-nginx-teg", f"{name}-nginx-event-store", f"{name}-registry"]
    present = [c for c in wanted if c in names]
    missing = [c for c in wanted if c not in names]
    if spire not in names:
        raise Refused(f"the compose names no container {spire}; set FT_REG_SPIRE_CONTAINER in .env.frame-test to the "
                      f"frame's SPIRE server container.")
    if not present:
        raise Refused(f"the compose names none of the terminators {', '.join(wanted)}; this does not look like a "
                      f"frame rendered from templates/frame-test.")
    return Facts(stack_dir=stack_dir, name=name, trust_domain=normalize_td(td), spire_container=spire,
                 registry_port=port, refresh_sec=refresh, cert_dir=cert_dir, terminators=present, missing=missing)


def load_facts(stack_dir: str) -> Facts:
    envp = os.path.join(stack_dir, ".env.frame-test")
    comp = os.path.join(stack_dir, "docker-compose.frame-test.yml")
    for p in (envp, comp):
        if not os.path.isfile(p):
            raise Refused(f"{p} does not exist; --stack-dir must be the frame's stack directory "
                          f"(the one holding .env.frame-test and docker-compose.frame-test.yml).")
    return frame_facts(stack_dir, open(envp).read(), open(comp).read())


# ── mirrors of the registry's own builders (services/frame_trust_manager.py, services/frame_test_provisioner.py) ───

def normalize_td(td: str) -> str:
    td = (td or "").strip().lower()
    if td.startswith("spiffe://"):
        td = td[len("spiffe://"):]
    return td.rstrip("/")


def spire_endpoint_from_url(url: str) -> str:
    """scheme + host[:port] of a bundle-endpoint URL: SPIRE serves its bundle at `/` and the https_spiffe profile
    dials the server itself (frame_trust_manager.spire_bundle_endpoint_from_url)."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    scheme, _, rest = u.partition("://")
    host = rest.split("/", 1)[0].strip()
    return f"{scheme}://{host}" if host else ""


def federation_create_argv(td: str, url: str, profile: str = FEDERATION_PROFILE,
                           endpoint_spiffe_id: str = "") -> List[str]:
    return [SPIRE_BIN, "federation", "create",
            "-trustDomain", td,
            "-bundleEndpointURL", url,
            "-bundleEndpointProfile", profile,
            "-endpointSpiffeID", endpoint_spiffe_id or f"spiffe://{td}/spire/server"]


def plan_relationship(existing: Dict[str, dict], td: str, bundle_endpoint_url: str) -> Tuple[str, Optional[List[str]], dict]:
    """(decision, argv, detail): `already` (left alone), `create` (argv), `skip` (no endpoint derivable);
    frame_trust_manager.plan_federation_relationship without overrides."""
    td = normalize_td(td)
    url = spire_endpoint_from_url(bundle_endpoint_url).rstrip("/")
    spiffe_id = f"spiffe://{td}/spire/server"
    if td in existing:
        return "already", None, {"trust_domain": td, **existing[td]}
    if not url:
        return "skip", None, {"trust_domain": td, "reason": "no bundle endpoint URL to derive from"}
    return "create", federation_create_argv(td, url, FEDERATION_PROFILE, spiffe_id), \
        {"trust_domain": td, "url": url, "profile": FEDERATION_PROFILE, "endpoint_spiffe_id": spiffe_id}


def parse_federation_list(text: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    cur: Optional[str] = None
    for raw in (text or "").splitlines():
        key, sep, val = raw.partition(":")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if key == "Trust domain":
            cur = normalize_td(val)
            out[cur] = {"url": "", "profile": "", "endpoint_spiffe_id": ""}
        elif cur and key == "Bundle endpoint URL":
            out[cur]["url"] = val
        elif cur and key == "Bundle endpoint profile":
            out[cur]["profile"] = val
        elif cur and key == "Endpoint SPIFFE ID":
            out[cur]["endpoint_spiffe_id"] = val
    return out


def parse_bundle_list(text: str) -> List[str]:
    """`spire-server bundle list` names each FEDERATED trust domain on a `* <td>` line above its PEM."""
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("* "):
            td = normalize_td(line[2:])
            if td and td not in out:
                out.append(td)
    return out


def parse_entry_show(text: str) -> List[dict]:
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
            td = normalize_td(val)
            if td and td not in cur.setdefault("federates_with", []):
                cur["federates_with"].append(td)
        elif key == "X509-SVID TTL":
            cur["ttl"] = val if val and val != "default" else None
    return out


def merge_federates_with(existing: List[str], wanted: List[str]) -> List[str]:
    out: List[str] = []
    for td in list(existing or []) + list(wanted or []):
        td = normalize_td(td)
        if td and td not in out:
            out.append(td)
    return out


def entry_update_argv(entry: dict, federates_with: List[str]) -> List[str]:
    """`entry update` is a REPLACE: -entryID plus everything the entry carries, de-duplicated (SPIRE refuses a repeated
    -dns); frame_test_provisioner.spire_entry_argv('update', ...)."""
    argv = [SPIRE_BIN, "entry", "update", "-entryID", entry["entry_id"],
            "-spiffeID", entry["spiffe_id"], "-parentID", entry.get("parent_id", "")]
    seen: List[str] = []
    for sel in entry.get("selectors", []) or []:
        if sel and sel not in seen:
            seen.append(sel)
            argv += ["-selector", sel]
    ttl = entry.get("ttl") or None
    if ttl:
        argv += ["-x509SVIDTTL", str(ttl)]
    seen_dns: List[str] = []
    for d in entry.get("dns", []) or []:
        if d and d not in seen_dns:
            seen_dns.append(d)
            argv += ["-dns", d]
    for td in merge_federates_with([], federates_with):
        argv += ["-federatesWith", f"spiffe://{td}"]
    return argv


def federate_entries(exec_fn: Callable[[List[str]], Tuple[int, str]], peer_td: str) -> dict:
    """Add peer_td to every service and operator workload entry (frame_test_provisioner.federate_frame_workload_entries):
    the data identity is never federated, agent identities are skipped, an entry already federated counts as `already`."""
    peer_td = normalize_td(peer_td)
    rc, text = exec_fn([SPIRE_BIN, "entry", "show"])
    if rc != 0:
        raise StepFailed(f"`spire-server entry show` failed (rc={rc}): {text.strip()[:200]}")
    detail = {"peer": peer_td, "updated": 0, "already": 0, "failed": [], "skipped": 0}
    for e in parse_entry_show(text):
        sid = e.get("spiffe_id", "")
        path = sid.split("://", 1)[-1].split("/", 1)[-1] if "://" in sid else sid
        if path == "service/data" or not (path.startswith("service/") or path.startswith("operator/")):
            detail["skipped"] += 1
            continue
        if peer_td in e.get("federates_with", []):
            detail["already"] += 1
            continue
        argv = entry_update_argv(e, merge_federates_with(e.get("federates_with", []), [peer_td]))
        rc, out = exec_fn(argv)
        if rc == 0:
            detail["updated"] += 1
        else:
            detail["failed"].append(f"{sid} rc={rc}: {out.strip()[:160]}")
    return detail


def bundle_set_argv(td: str, staged_path: str, fmt: str) -> List[str]:
    return [SPIRE_BIN, "bundle", "set", "-id", f"spiffe://{normalize_td(td)}", "-path", staged_path, "-format", fmt]


def detect_bundle_format(body: str) -> str:
    return "pem" if (body or "").lstrip().startswith("-----BEGIN") else "spiffe"


def bundle_stage_path(td: str, fmt: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", normalize_td(td))
    return f"/tmp/frame_bundle_{safe}.{fmt}"


def count_roots(pem_text: str) -> int:
    return (pem_text or "").count("BEGIN CERT")


def root_counts(exec_in: Callable[[str, List[str]], Tuple[int, str]], containers: List[str], cert_dir: str) -> Dict[str, Optional[int]]:
    """`grep -c "BEGIN CERT" <cert_dir>/bundle.0.pem` in each container; None when the container cannot answer."""
    out: Dict[str, Optional[int]] = {}
    for c in containers:
        rc, text = exec_in(c, ["grep", "-c", "BEGIN CERT", f"{cert_dir}/{BUNDLE_FILE}"])
        try:
            out[c] = int(text.strip().splitlines()[-1]) if text.strip() else (0 if rc == 1 else None)
        except ValueError:
            out[c] = None
    return out


def wait_for_roots(exec_in, containers: List[str], cert_dir: str, before: Dict[str, Optional[int]],
                   refresh_sec: int, *, clock=time.monotonic, sleep=time.sleep, log=print) -> Dict[str, Optional[int]]:
    """Wait until every container's bundle carries MORE roots than `before` (a rotation refreshes the file every
    REFRESH_SEC; two cycles plus a margin is the bound). Raises TimedOut naming that clock."""
    deadline = clock() + 2 * refresh_sec + ROOT_WAIT_MARGIN_SEC
    pending = list(containers)
    now: Dict[str, Optional[int]] = dict(before)
    while True:
        counts = root_counts(exec_in, pending, cert_dir)
        now.update(counts)
        pending = [c for c in pending if counts.get(c) is None or (before.get(c) or 0) >= counts[c]]
        if not pending:
            return now
        if clock() >= deadline:
            raise TimedOut(
                f"{', '.join(pending)} still carry {', '.join(str(now.get(c)) for c in pending)} root(s) after "
                f"{2 * refresh_sec + ROOT_WAIT_MARGIN_SEC} s; the cert-writer copies the bundle every "
                f"FT_CW_REFRESH_SEC={refresh_sec} s (docker logs {containers[0].rsplit('-', 2)[0]}-cert-writer), "
                f"check it runs, then re-run this command (every step is idempotent).")
        log(f"    waiting: {', '.join(f'{c}={now.get(c)}' for c in pending)} (need more than "
            f"{', '.join(str(before.get(c) or 0) for c in pending)})")
        sleep(POLL_SEC)


# ── 2. the peer's card and its bundle endpoint ───────────────────────────────────────────────────────────────────

def card_facts(card: dict) -> Tuple[str, str]:
    ident = card.get("identity") if isinstance(card, dict) else None
    fed = card.get("federation") if isinstance(card, dict) else None
    td = normalize_td((ident or {}).get("trust_domain") or "")
    ep = str((fed or {}).get("spire_bundle_endpoint") or "").strip()
    if not td:
        raise Refused("the peer's registry card carries no identity.trust_domain; ask the peer which frame you are "
                      "federating with and pass its console URL to --with.")
    return td, ep


def is_loopback(addr: str) -> bool:
    return addr.startswith("127.") or addr == "::1" or addr.startswith("0:0:0:0:0:0:0:1")


def endpoint_refusal(url: str, resolve=socket.getaddrinfo) -> Optional[str]:
    """One sentence when a bundle endpoint cannot be fetched from a foreign host, else None."""
    u = (url or "").strip()
    if not u:
        return ("the peer's card names no federation.spire_bundle_endpoint; pass --peer-bundle-endpoint "
                "https://<their spire bundle address>/ (ask the peer's admin, it is public)")
    if not u.lower().startswith("https://"):
        return f"the bundle endpoint {u} is not https; SPIRE bundle endpoints are always https."
    host = urllib.parse.urlparse(u).hostname or ""
    if not host:
        return f"the bundle endpoint {u} has no hostname."
    if "." not in host and not host.replace(":", "").isdigit():
        return (f"the bundle endpoint {u} names {host}, a docker-internal service name that only resolves inside the "
                f"peer's own host; ask the peer for its public bundle address (a <name>-spire.<domain> vhost or its "
                f"published port) and pass it as --peer-bundle-endpoint.")
    try:
        infos = resolve(host, None)
    except OSError as exc:
        return f"the bundle endpoint host {host} does not resolve from this host ({type(exc).__name__}); check the name."
    addrs = [i[4][0] for i in infos if i and i[4]]
    if addrs and all(is_loopback(a) for a in addrs):
        return f"the bundle endpoint host {host} resolves only to loopback here; that is this host, not the peer."
    return None


def licence_prefix(review_notes: Optional[str]) -> Optional[str]:
    m = re.search(r"licence issued by approver, prefix (\S+)", review_notes or "")
    return m.group(1) if m else None


def read_admin_secret(path: str) -> Tuple[str, str]:
    """The standup's `.<frame>_frame_admin.secret.json` shape: admin_email + admin_password. Read by shape; the values
    are returned to the caller and never logged."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        raise Refused(f"the admin secret file {path} does not exist; pass --admin-secret-file <the "
                      f".<frame>_frame_admin.secret.json the standup wrote> (mode 600).")
    except (OSError, ValueError) as exc:
        raise Refused(f"the admin secret file {path} is not readable JSON ({type(exc).__name__}).")
    if not isinstance(data, dict) or not data.get("admin_email") or not data.get("admin_password"):
        raise Refused(f"the admin secret file {path} does not carry admin_email and admin_password; it is not the "
                      f"standup's frame admin file.")
    return str(data["admin_email"]), str(data["admin_password"])


# ── transport: docker on this host, http over loopback and to the peer ─────────────────────────────────────────

def run(argv: List[str], timeout: int = 120) -> Tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise StepFailed(f"{argv[0]} is not installed on this host.")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout} s"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def docker_exec(container: str, argv: List[str], timeout: int = 120) -> Tuple[int, str]:
    return run(["docker", "exec", container, *argv], timeout=timeout)


def docker_cp(src: str, container: str, dest: str) -> None:
    rc, out = run(["docker", "cp", src, f"{container}:{dest}"])
    if rc != 0:
        raise StepFailed(f"docker cp into {container} failed (rc={rc}): {out.strip()[:200]}")


def http(method: str, url: str, *, body: Optional[dict] = None, form: Optional[dict] = None,
         headers: Optional[dict] = None, verify: bool = True, timeout: int = HTTP_TIMEOUT) -> Tuple[int, str]:
    data = None
    hdrs = {"Accept": "application/json", **(headers or {})}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()  # noqa: SLF001 — the approver's posture for the bundle fetch
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        return 0, f"{type(e).__name__}: {getattr(e, 'reason', e)}"


def http_json(method: str, url: str, **kw) -> Tuple[int, object]:
    st, text = http(method, url, **kw)
    try:
        return st, json.loads(text) if text else None
    except ValueError:
        return st, text


# ── the steps ──────────────────────────────────────────────────────────────────────────────────────────────────────

def step1_facts(stack_dir: str, log=print) -> Facts:
    f = load_facts(stack_dir)
    log(f"[1/7] frame {f.name}: trust domain {f.trust_domain}, SPIRE {f.spire_container}, registry 127.0.0.1:{f.registry_port}, "
        f"terminators {', '.join(f.terminators)}"
        + (f" (not in the compose: {', '.join(f.missing)})" if f.missing else ""))
    return f


def step2_peer(with_url: str, override_endpoint: Optional[str], own_td: str, log=print) -> Tuple[str, str]:
    base = with_url.strip().rstrip("/")
    if not base.lower().startswith("https://"):
        raise Refused(f"--with must be the peer's https console URL, not {with_url}.")
    st, card = http_json("GET", base + CARD_PATH)
    if st != 200 or not isinstance(card, dict):
        raise Refused(f"{base}{CARD_PATH} answered {st or 'no connection'}; --with must be a frame's public console "
                      f"(its registry card is served there).")
    td, ep = card_facts(card)
    if td == own_td:
        raise Refused(f"{base} is this frame itself ({td}); a frame cannot federate with itself.")
    if override_endpoint:
        ep, source = override_endpoint.strip(), "--peer-bundle-endpoint"
    else:
        source = "the peer's card"
    why = endpoint_refusal(ep)
    if why:
        raise Refused(why)
    log(f"[2/7] peer {td}: bundle endpoint {ep} (from {source}); the relationship will dial "
        f"{spire_endpoint_from_url(ep)} as spiffe://{td}/spire/server")
    return td, ep


def step3_import(facts: Facts, peer_td: str, endpoint: str, *, exec_in=docker_exec, cp=docker_cp, fetch=http,
                 log=print) -> dict:
    st, body = fetch("GET", endpoint, verify=False)   # the approver's posture: a SPIRE-issued cert, no public CA
    if st != 200 or not body.strip():
        hint = ""
        if st in (400, 495, 496) and "SSL certificate" in str(body):
            # §EXTREACH 2026-10-14: EU's and ASIA's cards named their federation terminator here, which requires a
            # client certificate; say what to do instead of only what happened.
            hint = (" That address sits behind a client certificate (the peer's federation terminator, not its SPIRE "
                    "bundle endpoint), which a frame that is not federated yet cannot present: ask the peer's admin "
                    "for the public bundle endpoint (its SPIRE server's, e.g. https://<peer>:8665/) and rerun with "
                    "--peer-bundle-endpoint <it>.")
        raise StepFailed(f"the bundle endpoint {endpoint} answered {st or 'no connection'}: {str(body)[:120]}; a "
                         f"SPIRE bundle endpoint answers 200 with a JWK set, a <name>-spire vhost the same.{hint}")
    fmt = detect_bundle_format(body)
    if fmt == "spiffe":
        try:
            keys = json.loads(body).get("keys")
        except (ValueError, AttributeError):
            keys = None
        if not keys:
            raise StepFailed(f"{endpoint} answered 200 but not a SPIFFE bundle (no `keys`): the address is a console or "
                             f"a lane, not the SPIRE bundle endpoint; pass --peer-bundle-endpoint with the right one.")
    rc, listing = exec_in(facts.spire_container, [SPIRE_BIN, "bundle", "list"])
    if rc != 0:
        raise StepFailed(f"`spire-server bundle list` in {facts.spire_container} failed (rc={rc}): is the container "
                         f"running and is this host the frame's host?")
    already_held = peer_td in parse_bundle_list(listing)
    staged = bundle_stage_path(peer_td, fmt)
    with tempfile.NamedTemporaryFile("w", suffix=f".{fmt}", delete=False) as tmp:
        tmp.write(body)
        local = tmp.name
    try:
        cp(local, facts.spire_container, staged)
    finally:
        try:
            os.unlink(local)
        except OSError:
            pass
    rc, out = exec_in(facts.spire_container, bundle_set_argv(peer_td, staged, fmt))
    if rc != 0:
        raise StepFailed(f"`spire-server bundle set` for {peer_td} failed (rc={rc}): {out.strip()[:200]}")
    rc, fl = exec_in(facts.spire_container, [SPIRE_BIN, "federation", "list"])
    if rc != 0:
        raise StepFailed(f"`spire-server federation list` failed (rc={rc}): {fl.strip()[:200]}")
    decision, argv, detail = plan_relationship(parse_federation_list(fl), peer_td, endpoint)
    if decision == "create":
        rc, out = exec_in(facts.spire_container, argv)
        if rc != 0:
            raise StepFailed(f"`spire-server federation create` for {peer_td} failed (rc={rc}): {out.strip()[:200]}")
    elif decision == "skip":
        raise StepFailed(f"no SPIRE endpoint could be derived from {endpoint}.")
    entries = federate_entries(lambda argv: exec_in(facts.spire_container, argv), peer_td)
    log(f"[3/7] bundle for {peer_td}: {len(body)} bytes ({fmt}), set into {facts.spire_container}"
        f"{' (root already held)' if already_held else ''}; relationship {decision} "
        f"({detail.get('url') or detail.get('reason') or 'as listed'}, {detail.get('profile') or FEDERATION_PROFILE}); "
        f"workload entries updated {entries['updated']}, already {entries['already']}, skipped {entries['skipped']}"
        + (f", FAILED {len(entries['failed'])}: {'; '.join(entries['failed'])[:300]}" if entries["failed"] else ""))
    if entries["failed"]:
        raise StepFailed(f"{len(entries['failed'])} workload entry update(s) failed; see the line above.")
    return {"format": fmt, "already_held": already_held, "relationship": decision, "entries": entries}


def step4_roots(facts: Facts, before: Dict[str, Optional[int]], already_held: bool, *, exec_in=docker_exec, log=print) -> None:
    if already_held:
        now = root_counts(exec_in, facts.terminators, facts.cert_dir)
        log(f"[4/7] roots: the peer root was already held, the terminators carry "
            f"{', '.join(f'{c}={n}' for c, n in now.items())}; nothing to wait for")
        return
    now = wait_for_roots(exec_in, facts.terminators, facts.cert_dir, before, facts.refresh_sec, log=log)
    log(f"[4/7] roots: {', '.join(f'{c} {before.get(c)}->{now.get(c)}' for c in facts.terminators)}")


def admin_login(facts: Facts, email: str, password: str, *, post=http_json) -> str:
    base = f"http://127.0.0.1:{facts.registry_port}{API}"
    st, tok = post("POST", f"{base}/auth/login", form={"username": email, "password": password})
    if st != 200 or not isinstance(tok, dict) or not tok.get("access_token"):
        raise StepFailed(f"the frame admin login at 127.0.0.1:{facts.registry_port} answered {st}; the secret file's "
                         f"admin_email/admin_password do not log in on this frame (a rotated password, or another frame's file).")
    return tok["access_token"]


def pick_resumable(rows: list, target: str) -> Optional[dict]:
    """The outbound row a re-run RESUMES instead of inviting again (§HELLOFRAME Phase 3: a second pass sent a second
    invitation, and the peer's approve of the second carried no key because the licence had been issued on the first).
    An outbound row names its target in review_notes (`[outbound] target <url>`). Preference: a completed row whose
    notes carry a licence prefix (its key can still be taken), else the newest row still pending or approved, else None: a new invitation is due, because a completed row
    without a key means the peer delivered none and a new handshake (the approve rotates) is the only way to one."""
    mine = [r for r in rows if isinstance(r, dict) and f"[outbound] target {target}" in str(r.get("review_notes") or "")]
    with_key = [r for r in mine if r.get("status") == "completed" and licence_prefix(r.get("review_notes"))]
    if with_key:
        return sorted(with_key, key=lambda r: str(r.get("created_at") or ""))[-1]
    live = [r for r in mine if r.get("status") in ("pending", "approved")]
    return sorted(live, key=lambda r: str(r.get("created_at") or ""))[-1] if live else None


def existing_outbound(facts: Facts, target: str, token: str, *, get=http_json) -> Optional[dict]:
    base = f"http://127.0.0.1:{facts.registry_port}{API}"
    # the listing shows PENDING rows unless asked for all: a completed row (whose key can still be taken) is invisible otherwise
    st, data = get("GET", f"{base}/admin/federation/frame-invitations?status=all&limit=200", headers={"Authorization": f"Bearer {token}"})
    rows = data if isinstance(data, list) else ((data.get("items") or data.get("invitations") or []) if isinstance(data, dict) else [])
    return pick_resumable(rows, target)


def step5_outbound(facts: Facts, target: str, token: str, contact_email: str,
                   description: str, *, post=http_json, log=print) -> str:
    base = f"http://127.0.0.1:{facts.registry_port}{API}"
    st, data = post("POST", f"{base}/admin/federation/frame-invitations/outbound",
                    headers={"Authorization": f"Bearer {token}"},
                    body={"target_registry_url": target, "contact_email": contact_email,
                          "description": description, "spire_bundle_imported": True})
    if st not in (200, 201) or not isinstance(data, dict) or not data.get("id"):
        detail = data.get("detail") if isinstance(data, dict) else data
        if st == 404:
            raise StepFailed("this frame's registry has no outbound invitation endpoint "
                             "(POST /api/v1/admin/federation/frame-invitations/outbound): its image predates it; roll it.")
        raise StepFailed(f"the outbound invitation answered {st}: {str(detail)[:300]}")
    log(f"[5/7] outbound invitation {data['id']} sent to {target} and recorded on this frame (status {data.get('status') or 'pending'}); "
        f"the peer's admin now approves it in Frame Management")
    return data["id"]


def step6_wait(facts: Facts, inv_id: str, token: str, timeout_min: float, *, get=http_json, clock=time.monotonic,
               sleep=time.sleep, log=print) -> dict:
    base = f"http://127.0.0.1:{facts.registry_port}{API}"
    deadline = clock() + timeout_min * 60
    last = ""
    while True:
        st, inv = get("GET", f"{base}/admin/federation/frame-invitations/{inv_id}", headers={"Authorization": f"Bearer {token}"})
        if st == 200 and isinstance(inv, dict):
            status = str(inv.get("status") or "")
            if status != last:
                log(f"    invitation {inv_id}: {status}")
                last = status
            if status == "completed":
                return inv
            if status in ("rejected", "revoked"):
                raise StepFailed(f"the peer {status} the invitation: {inv.get('rejection_reason') or inv.get('revoked_reason') or 'no reason given'}")
        elif st == 401:
            raise StepFailed("this frame's admin token stopped working while waiting (a password change or a restart "
                             "logs every session out); re-run this command, every step is idempotent.")
        if clock() >= deadline:
            raise TimedOut(f"the invitation {inv_id} is still '{last or 'unknown'}' after {timeout_min:g} minutes; the "
                           f"peer's admin has not approved it yet, or its callback to this frame has not landed; re-run "
                           f"this command later (it resumes at the wait).")
        sleep(POLL_SEC)


def upsert_env_line(text: str, key: str, value: str) -> str:
    """One `KEY=value` line in the frame's env file: replaced where it exists, appended where it does not."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def step7_licence(facts: Facts, inv_id: str, token: str, *, get=http_json, run_fn=run, exec_in=docker_exec,
                  sleep=time.sleep, clock=time.monotonic, log=print) -> dict:
    """The licence key the peer delivered, applied: taken ONCE from this frame's registry (it parks it for an hour),
    written as FEDERATION_LICENSE_KEY into the stack's env file, the registry recreated alone (--no-deps) and read back
    by NAME. The key is never printed and never on a command line."""
    base = f"http://127.0.0.1:{facts.registry_port}{API}"
    st, data = get("GET", f"{base}/admin/federation/frame-invitations/{inv_id}/licence-key", headers={"Authorization": f"Bearer {token}"})
    if st != 200 or not isinstance(data, dict) or not data.get("federation_license_key"):
        detail = data.get("detail") if isinstance(data, dict) else data
        if st == 404 and "predates" not in str(detail):
            raise StepFailed(f"no licence key to apply: {str(detail)[:300]}")
        raise StepFailed(f"the licence-key route answered {st}: {str(detail)[:300]} (an image that predates it: roll the frame's registry)")
    key = str(data["federation_license_key"])
    env_path = os.path.join(facts.stack_dir, ".env.frame-test")
    try:
        text = open(env_path, encoding="utf-8").read()
    except OSError as e:
        raise StepFailed(f"the frame's env file could not be read: {e}")
    mode = os.stat(env_path).st_mode & 0o777
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write(upsert_env_line(text, "FEDERATION_LICENSE_KEY", key))
    os.chmod(env_path, mode or 0o600)
    rc, out = run_fn(["docker", "compose", "-f", os.path.join(facts.stack_dir, "docker-compose.frame-test.yml"), "--env-file", env_path,
                      "up", "-d", "--no-deps", "--no-build", "--force-recreate", f"{facts.name}-registry"], timeout=600)
    if rc != 0:
        raise StepFailed(f"the registry recreate after the licence write failed (rc={rc}): {out.strip()[-300:]}")
    deadline = clock() + 300
    health = "none"
    while clock() < deadline:
        rc, out = run_fn(["docker", "inspect", f"{facts.name}-registry", "--format", "{{.State.Health.Status}}"], timeout=30)
        health = out.strip() if rc == 0 else "none"
        if health == "healthy":
            break
        sleep(5)
    if health != "healthy":
        raise StepFailed(f"the registry did not come back healthy within 5 minutes after the licence write (last: {health}); "
                         f"`docker logs {facts.name}-registry` says why. The key IS in the env file; a later recreate applies it.")
    rc, out = exec_in(f"{facts.name}-registry", ["sh", "-c", 'test -n "$FEDERATION_LICENSE_KEY" && echo present || echo absent'])
    present = rc == 0 and "present" in out
    log(f"[7/7] licence {data.get('prefix', key[:12])}... applied: FEDERATION_LICENSE_KEY written to .env.frame-test, the registry "
        f"recreated alone and healthy, the variable {'present' if present else 'ABSENT'} in its environment")
    if not present:
        raise StepFailed("the recreated registry does not carry FEDERATION_LICENSE_KEY: the compose does not hand the env file to the registry.")
    return {"prefix": data.get("prefix", key[:12]), "health": health, "present": present}


def peer_row(facts: Facts, peer_registry_id: Optional[int], get=http_json) -> Optional[dict]:
    if not peer_registry_id:
        return None
    st, rows = get("GET", f"http://127.0.0.1:{facts.registry_port}{API}/federation/registries")
    if st == 200 and isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and r.get("registry_id") == peer_registry_id:
                return r
    return None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Federate this frame with a peer, from the frame's own host.")
    ap.add_argument("--stack-dir", required=True, help="the frame's stack directory (.env.frame-test + docker-compose.frame-test.yml)")
    ap.add_argument("--with", dest="with_url", required=True, help="the peer's https console URL")
    ap.add_argument("--peer-bundle-endpoint", default=None, help="override the bundle endpoint the peer's card advertises")
    ap.add_argument("--contact-email", default=None, help="the contact the peer's admin sees (default: the frame admin's email)")
    ap.add_argument("--description", default=None, help="one line for the peer's admin")
    ap.add_argument("--admin-secret-file", default=os.environ.get("FRAME_ADMIN_SECRET_FILE"),
                    help="the .<frame>_frame_admin.secret.json the standup wrote (or FRAME_ADMIN_SECRET_FILE)")
    ap.add_argument("--timeout-min", type=float, default=20.0, help="how long to wait for the peer's approval")
    ap.add_argument("--dry-run", action="store_true", help="stop after reading the frame and the peer; touch nothing")
    ap.add_argument("--no-licence", action="store_true", help="do not take and apply the delivered licence key (step 7)")
    ap.add_argument("--fresh", action="store_true",
                    help="send a NEW invitation even when an earlier one of this frame is still pending or approved (the peer's admin "
                         "rejected or lost it; a re-run without this flag resumes the earlier row)")
    a = ap.parse_args(argv)
    try:
        facts = step1_facts(a.stack_dir)
        peer_td, endpoint = step2_peer(a.with_url, a.peer_bundle_endpoint, facts.trust_domain)
        if a.dry_run:
            _, argv_create, _ = plan_relationship({}, peer_td, endpoint)
            print("[dry-run] would run, in this order (the bundle's format, spiffe or pem, is decided at the fetch):")
            print(f"    docker cp <bundle> {facts.spire_container}:{bundle_stage_path(peer_td, 'spiffe')}")
            print("    docker exec " + facts.spire_container + " " + " ".join(bundle_set_argv(peer_td, bundle_stage_path(peer_td, 'spiffe'), 'spiffe')))
            print("    docker exec " + facts.spire_container + " " + " ".join(argv_create or []))
            print(f"    docker exec {facts.spire_container} {SPIRE_BIN} entry show / entry update -federatesWith spiffe://{peer_td} ...")
            print(f"    wait for {', '.join(facts.terminators)} to gain the root ({facts.cert_dir}/{BUNDLE_FILE}, up to "
                  f"{2 * facts.refresh_sec + ROOT_WAIT_MARGIN_SEC} s)")
            print(f"    POST http://127.0.0.1:{facts.registry_port}{API}/admin/federation/frame-invitations/outbound "
                  f"target_registry_url={a.with_url.rstrip('/')} spire_bundle_imported=true")
            return 0
        if not a.admin_secret_file:
            raise Refused("pass --admin-secret-file <the .<frame>_frame_admin.secret.json the standup wrote> "
                          "(or set FRAME_ADMIN_SECRET_FILE); the outbound invitation is an admin action on this frame.")
        email, password = read_admin_secret(a.admin_secret_file)
        before = root_counts(docker_exec, facts.terminators, facts.cert_dir)
        imported = step3_import(facts, peer_td, endpoint)
        step4_roots(facts, before, imported["already_held"])
        target = a.with_url.strip().rstrip("/")
        token = admin_login(facts, email, password)
        prior = None if a.fresh else existing_outbound(facts, target, token)
        if prior:
            inv_id = prior["id"]
            print(f"[5/7] resuming the outbound invitation {inv_id} this frame recorded earlier for {target} "
                  f"(status {prior.get('status')}); no new invitation is sent")
        else:
            inv_id = step5_outbound(facts, target, token, a.contact_email or email,
                                    a.description or f"outbound invitation to {target}")
        inv = step6_wait(facts, inv_id, token, a.timeout_min)
        row = peer_row(facts, inv.get("peer_registry_id"))
        prefix = licence_prefix(inv.get("review_notes"))
        print(f"[6/7] completed at {inv.get('completed_at')}: peer row id={inv.get('peer_registry_id')}"
              + (f" name={row.get('registry_name')} url={row.get('registry_url')}" if row else " (not in this frame's registry list yet)")
              + (f"; licence prefix {prefix}" if prefix else "; no licence prefix recorded (the peer issued none, or its image predates §FRAMELIC)"))
        if prefix and not a.no_licence:
            step7_licence(facts, inv_id, token)
        elif not prefix:
            print("[7/7] no licence to apply")
        return 0
    except Refused as e:
        sys.stdout.flush()
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except StepFailed as e:
        sys.stdout.flush()
        print(f"failed: {e}", file=sys.stderr)
        return 3
    except TimedOut as e:
        sys.stdout.flush()
        print(f"timed out: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
