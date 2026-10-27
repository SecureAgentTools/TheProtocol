#!/usr/bin/env python3
"""§FRAMEPROV P2 (2026-09-13): the frame runner, a small root service on a local socket that runs the frame standup
driver for the admin UI, and nothing else.

His decision 2026-09-13 (the host-runner recommendation): the registry never holds host root for frame provisioning.
It holds this socket, and the socket accepts a CLOSED set of jobs with validated arguments:

    ping · plan · standup · resume · teardown · cancel · status · events · reveal · dns_status · dns_ensure · dns_remove

A leaked admin token can plan or stand up a SANDBOX frame, or tear down a frame this runner built; nothing else.
Milestone 1 never federates, never grants host reach, never provisions operators, never stands up a production posture.

Protocol: one JSON object on one line in; one line out, {"ok": true, "result": ...} or {"ok": false, "refused": "..."};
then the connection closes. Callers are admitted by the socket's mode (0660 root:deploy) and by SO_PEERCRED (uid 0, or
the registry's uid 1000). State (0700): jobs/<id>/{job.json, stdout.log, progress.jsonl, secrets/}, frames/<name>.json
(which job built it) and audit.jsonl. The frame admin credential is handed over ONCE (`reveal`, his word "show once");
the frame's own .env.frame-test keeps it on the host.

Plan: sessionlogs2026/PLAN_2026-09-13_FRAME_PROVISIONING.md. Unit: theprotocol-frame-runner.service beside this file.

§FRAMEPROV P5 (his "go for p5", 2026-09-13): with a `dns` block in the policy file the runner also owns the four DNS names
of the frames it builds (frame_dns.py). A standup creates them, marked with its job, and runs the driver behind
`await-dns` with `--acme`; a teardown deletes only the records it wrote down that still carry its mark, and the
certificate. A host that already has a record, or resolves without one, is refused and never adopted.
"""
import argparse
import base64
import datetime
import glob
import grp
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from decimal import Decimal, InvalidOperation
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_dns  # noqa: E402  (beside this file, stdlib only)

VERSION = "4"   # 4: the sandbox ops (§TESTBED), unadopt, the calling frame identified by its container   # 2: ping names the images, the domain, the resumable steps and the spec fields · 3: the dns ops (P5)
# §LANTERNT3 (2026-09-16, his decision "route it through the frame runner"; the scoping is agentvault2-b5's).
# TWO OP SETS AND TWO SOCKETS, because a unix socket already carries scope in its PATH.
#   OPS           — frame management. Served on the full socket, which is where the admin console lives.
#   OPERATOR_OPS  — what a FRAME's own registry may ask for on its own behalf. Served on a SECOND socket.
# A frame's registry needs host reach to provision its cloud operator (the bundle is built through the host
# Docker API), and a docker socket is unrestricted root on the host. Routing it through the runner replaces an
# UNBOUNDED grant with a BOUNDED one — but bounded at the SOCKET is not bounded at the OP: admission here is
# `uid not in allowed_uids`, every op is a method on one dispatcher, and both the console and a frame present
# uid 1000. So a frame admitted at all would be admitted to standup, resume and TEARDOWN.
# The second listener is the bound: same mode, same SO_PEERCRED gate, serving ONLY these ops and refusing the
# rest in the runner's own words. The frame template mounts THAT socket; the full one stays with the console.
# ⚠ OPERATOR_OPS IS DELIBERATELY NOT ADDED TO OPS. One flag would let the full-socket callers gain them too;
# two sets cannot be confused, which is the same argument as teardown being its own op rather than a flag.
# §F6 WP6.1 (2026-09-26, his words "approved ... do it fully autonomously"): the IDENTITY ops, what a frame's registry
# did against its OWN SPIRE server through the Docker socket (the frame-invitation rail's bundle and federation steps,
# the workload entries' -federatesWith, IRONHAND's entries, SVID issuance and node list), done here as closed ops on the
# operator socket, each bound to the calling frame (see Runner._identity_ctx and the spec_* rules below).
IDENTITY_OPS = ("spire_bundle_set", "spire_bundle_show", "spire_bundle_list", "spire_bundle_delete",
                "spire_federation_create", "spire_federation_update", "spire_federation_list", "spire_federation_delete",
                "spire_entry_create", "spire_entry_show", "spire_entry_update_federates", "spire_entry_delete",
                "spire_entry_count", "spire_x509_mint", "spire_agent_list", "spire_agent_ban", "spire_agent_evict")
# §F6 WP6.2 (2026-09-26, agentvault2-a1's go on his "do it fully autonomously"): the operator lifecycle the registry ran
# through a docker:cli sidecar holding the Docker socket (restart_cloud_service, fetch_cloud_logs), done here on the
# operator's own compose stack. Bound by the OPERATOR's containers (Runner._caller_operator), so they serve frames this
# runner did not build as well as the ones it did.
# Slice 2 (2026-09-26, his words "continue with wp6.2 slice 2 on the sandbox pair"): the SPIRE half of an operator's revoke
# and purge (only /operator/<op>/ of the caller's frame, never its own node or another operator's), and the host half of
# a purge (the stack, the edge, the stack dir, and the genesis drain run inside the operator's own TEG).
OPERATOR_LIFECYCLE_OPS = ("operator_restart", "operator_logs", "operator_revoke_spire", "operator_purge")
# Read-only observation of the caller's OWN compose project, or of one of its operators': what a frame's registry read
# host-wide through the socket (the docker-stats socket and route, the operator health route) narrowed to what it owns.
OBSERVATION_OPS = ("containers_census", "container_stats")
OPERATOR_OPS = (("operator_ping", "operator_provision", "operator_teardown", "operator_status")
                + IDENTITY_OPS + OPERATOR_LIFECYCLE_OPS + OBSERVATION_OPS)
# §TESTBED (2026-09-19, his words "the sandbox provisioning should be also in the frontend mcp-tester view ... all
# provisioned thru the proper lanes"): a kit frame's console provisions its SANDBOX through these, on the operator socket
# it already mounts, and only where the policy says `"sandboxes": true` (the kit installer writes it; this network's own
# runner has no such key, so they are refused here). Each one acts for the CALLING frame only, identified by its container.
SANDBOX_OPS = ("sandbox_status", "sandbox_up", "sandbox_down", "sandbox_events", "sandbox_reveal")
# (spec field, the frame registry's env key it must equal). The bundle phase's four since V0386 (agentvault2-b5).
SPEC_SPIRE_FIELDS = (("spire_container", "SPIRE_CONTAINER"), ("spire_trust_domain", "SPIRE_TRUST_DOMAIN"),
                     ("spire_server_address", "SPIRE_SERVER_ADDRESS"), ("spire_server_port", "SPIRE_SERVER_PORT"))

OPS = ("ping", "plan", "standup", "resume", "teardown", "cancel", "status", "events", "reveal", "dns_status", "dns_ensure",
       "dns_remove", "dns_push_ensure", "relink_auditor", "adopt", "unadopt")
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}[a-z0-9]")
INSTANCE_RE = NAME_RE
# §NIGHTPROV (2026-09-27, his words "1 yes 2 approved 3 00:30z. go ahead.": the frame runner may build SANDBOX-posture
# frames at night, DNS names and a certificate per frame, created and removed automatically). The nightly provisioning
# job's pair is nt<yymmdd> (nt<yymmdd>x<n> for a second pair the same day: a proof, a re-run), its two frames
# <pair>a and <pair>b. The whole nt<6 digits> namespace is the job's: any other name in it is refused, so nothing but
# the job's own frames can ever carry a name the job's teardown and leftover check look for.
NIGHTLY_CHILD_RE = re.compile(r"(nt[0-9]{6}(?:x[0-9]{1,2})?)([ab])")
NIGHTLY_RESERVED_RE = re.compile(r"nt[0-9]{6}.*")
# the host sidecar pieces a nightly frame is wired into: the stream SNI map (its federation address) and the bundle
# refresh (its ES vhost verifies the pair's roots). Never Prometheus, the public auditor, the apex or the prod compose.
NIGHTLY_WIRE = "sni,bundle"


_CGROUP_CONTAINER_RE = re.compile(r"(?:docker-|/docker/)([0-9a-f]{64})")


def container_of_pid(pid):
    """The docker container id a host pid runs in (its cgroup path names it), or None (not in a container, or gone)."""
    try:
        with open(f"/proc/{int(pid)}/cgroup") as f:
            text = f.read()
    except (OSError, ValueError, TypeError):
        return None
    m = _CGROUP_CONTAINER_RE.search(text)
    return m.group(1) if m else None


def frame_of_project(project):
    """The frame a compose project label names (<frame>-<digits> or <frame>-edge), or None. The same rule as
    scripts/hetzner_demo/frame_names.py (this runner stays stdlib-only and loads nothing from the export)."""
    m = re.fullmatch(r"(.+)-(?:\d+|edge)", project or "")
    return m.group(1) if m else None


# ── §F6 WP6.1: the identity ops' argument rules. Pure and stdlib-only, so each rule is tested without a SPIRE server ──
# A runner op with a too-wide argument is the docker socket by another name (DESIGN_2026-09-26_F5_F6.md §4.2): every
# argument below is refused unless it has the one shape a frame's own identity work needs, and the SPIRE CLI is always
# called with an argument LIST, so no value ever reaches a shell.
SPIRE_BIN = "/opt/spire/bin/spire-server"
IDENTITY_KINDS = ("agent", "operator", "service")                          # the SPIFFE paths a frame's registry may name
SELECTOR_KEYS = ("com.agentvault.service", "com.theprotocol.agent-did")    # the two label keys a frame's entries use
DNS_NAME_RE = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
TRUST_DOMAIN_RE = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]{1,200}")
ENTRY_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")
SVID_TTL_BOUNDS = (60, 86400)
MAX_DNS_NAMES = 16
MAX_FEDERATES = 32
MAX_SELECTORS = 4
MAX_BUNDLE_BYTES = 48 * 1024          # under MAX_REQUEST_BYTES with room for the rest of the request
MAX_SPIRE_OUTPUT = 2 * 1024 * 1024
BUNDLE_FORMATS = ("pem", "spiffe")
FEDERATION_PROFILES = ("https_spiffe", "https_web")
BUNDLE_DELETE_MODES = ("dissociate", "restrict", "delete")
# §F6 WP6.2: the operator lifecycle's rules. The services are the operator compose's own (the registry's allowlist,
# CLOUD_OP_RESTARTABLE_SERVICES, is the same set); a name is a compose project suffix; a log tail is bounded.
OPERATOR_SERVICES = ("registry", "teg-layer", "nginx-federation", "redis", "db", "teg-db", "pgbouncer", "spire-agent",
                     "cert-writer", "all")
OPERATOR_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}[a-z0-9]")
LOG_TAIL_BOUNDS = (10, 2000)
MAX_LOG_BYTES = 1024 * 1024
FINGERPRINT_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")      # an x509pop node's fingerprint (SHA-1 or SHA-256 hex)
TEG_ID_RE = re.compile(r"[a-z][a-z0-9-]{0,62}")                  # a TEG id as PARTNER_TEGS names it
AMOUNT_RE = re.compile(r"\d{1,15}(\.\d{1,18})?")                 # a treasury amount as the drain sends it


def treasury_amount(raw):
    """A treasury balance as the TEG prints it ('0E-18' and '12.5' alike) as a Decimal, or None when it is not a finite,
    non-negative number. Measured 2026-09-27: an empty operator treasury reads '0E-18', which the old pattern refused."""
    try:
        d = Decimal(str(raw if raw is not None else "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() and d >= 0 else None
MAX_CENSUS_CONTAINERS = 64
_PEM_CERT_RE = re.compile(r"-----BEGIN CERTIFICATE-----([A-Za-z0-9+/=\s]+?)-----END CERTIFICATE-----")


def spec_trust_domain(value, what="trust_domain"):
    """A trust domain: a DNS name with at least one dot, lowercase; a spiffe:// prefix and a trailing slash dropped."""
    td = str(value or "").strip().lower()
    if td.startswith("spiffe://"):
        td = td[len("spiffe://"):]
    td = td.rstrip("/")
    if not TRUST_DOMAIN_RE.fullmatch(td):
        raise Refused(f"{what}: {str(value)[:80]!r} is not a DNS name")
    return td


def spec_peer_trust_domain(value, own):
    td = spec_trust_domain(value)
    if td == own:
        raise Refused(f"trust_domain: {td} is this frame's own, and the op is about a PEER's")
    return td


def _spiffe_path(value, td_rule):
    s = str(value or "").strip()
    if not s.startswith("spiffe://"):
        raise Refused(f"{s[:80]!r} is not a SPIFFE ID")
    td, _, path = s[len("spiffe://"):].partition("/")
    td_rule(td, s)
    segs = path.split("/") if path else []
    if not segs or not all(PATH_SEGMENT_RE.fullmatch(x) and x not in (".", "..") for x in segs):
        raise Refused(f"{s[:80]!r} has an empty or unusual path segment")
    return s, segs


def spec_spiffe_id(value, own, kinds=IDENTITY_KINDS):
    """spiffe://<this frame's trust domain>/<kind>/<name>..., each segment a plain name; an operator identity is
    /operator/<op>/<name>. A frame names its own identities and nothing else."""
    def own_td(td, s):
        if td != own:
            raise Refused(f"spiffe_id: {s[:80]!r} is not under this frame's trust domain ({own})")
    s, segs = _spiffe_path(value, own_td)
    if segs[0] not in kinds:
        raise Refused(f"spiffe_id: {s[:80]!r} is not under {' or '.join('/' + k + '/' for k in kinds)}")
    if len(segs) < (3 if segs[0] == "operator" else 2):
        raise Refused(f"spiffe_id: {s[:80]!r} names no workload under /{segs[0]}/")
    return s


def spec_node_id(value, own):
    """A SPIRE agent NODE of this frame: spiffe://<own>/spire/agent/<attestor>/<id>."""
    prefix = f"spiffe://{own}/spire/agent/"
    s = str(value or "").strip()
    rest = s[len(prefix):] if s.startswith(prefix) else ""
    segs = rest.split("/") if rest else []
    if len(segs) < 2 or not all(PATH_SEGMENT_RE.fullmatch(x) and x not in (".", "..") for x in segs):
        raise Refused(f"{s[:80]!r} is not a SPIRE agent node of this frame ({prefix}<attestor>/<id>)")
    return s


def spec_endpoint_spiffe_id(value, peer):
    """The SPIFFE ID a peer's bundle endpoint presents: under the PEER's trust domain."""
    def peer_td(td, s):
        if td != peer:
            raise Refused(f"endpoint_spiffe_id: {s[:80]!r} is not under the peer's trust domain ({peer})")
    return _spiffe_path(value, peer_td)[0]


def spec_selectors(values, kind):
    """docker:label:<key>:<name> with the ONE key its identity kind uses: an agent carries the agent label, a service or
    an operator the service label, so no entry can claim the other kind's workloads."""
    key = "com.theprotocol.agent-did" if kind == "agent" else "com.agentvault.service"
    vals = values if isinstance(values, list) else []
    if not 1 <= len(vals) <= MAX_SELECTORS:
        raise Refused(f"selectors: a list of 1 to {MAX_SELECTORS}")
    out = []
    for v in vals:
        parts = str(v).split(":")
        if len(parts) != 4 or parts[:2] != ["docker", "label"] or parts[2] != key or not PATH_SEGMENT_RE.fullmatch(parts[3]):
            raise Refused(f"selectors: {str(v)[:80]!r} is not docker:label:{key}:<name>")
        if v not in out:
            out.append(v)
    return out


def spec_dns_names(values):
    vals = [] if values in (None, "") else values
    if not isinstance(vals, list) or len(vals) > MAX_DNS_NAMES:
        raise Refused(f"dns: a list of at most {MAX_DNS_NAMES} names")
    out = []
    for v in vals:
        d = str(v).strip().lower()
        if not DNS_NAME_RE.fullmatch(d):
            raise Refused(f"dns: {str(v)[:80]!r} is not a DNS name")
        if d not in out:
            out.append(d)
    return out


def spec_ttl(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise Refused(f"ttl: {str(value)[:40]!r} is not a number of seconds") from None
    if not SVID_TTL_BOUNDS[0] <= n <= SVID_TTL_BOUNDS[1]:
        raise Refused(f"ttl: {n}s is outside {SVID_TTL_BOUNDS[0]}..{SVID_TTL_BOUNDS[1]}")
    return n


def spec_federates(values, own):
    vals = [] if values in (None, "") else values
    if not isinstance(vals, list) or len(vals) > MAX_FEDERATES:
        raise Refused(f"federates_with: a list of at most {MAX_FEDERATES} trust domains")
    out = []
    for v in vals:
        td = spec_peer_trust_domain(v, own)
        if td not in out:
            out.append(td)
    return out


def spec_entry_id(value):
    s = str(value or "").strip()
    if not ENTRY_ID_RE.fullmatch(s):
        raise Refused(f"entry_id: {s[:80]!r} is not a SPIRE entry ID")
    return s


def spec_bundle_url(value):
    """https://<host>[:port] and nothing else: a bundle endpoint, never a page, a login or a query."""
    raw = str(value or "").strip()
    try:
        u = urllib.parse.urlsplit(raw)
        port = u.port
    except ValueError:
        raise Refused(f"bundle_endpoint_url: {raw[:100]!r} is not a URL") from None
    host = (u.hostname or "").lower()
    if (u.scheme != "https" or not host or u.username or u.password or u.query or u.fragment
            or u.path not in ("", "/") or "@" in u.netloc):
        raise Refused(f"bundle_endpoint_url: {raw[:100]!r} is not https://<host>[:port]")
    if not (DNS_NAME_RE.fullmatch(host) or re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host)):
        raise Refused(f"bundle_endpoint_url: {host[:80]!r} is not a host name")
    return f"https://{host}" + (f":{port}" if port else "")


def _der_ok(b64):
    try:
        der = base64.b64decode("".join(str(b64).split()), validate=True)
    except (ValueError, TypeError):
        return False
    return len(der) > 16 and der[0] == 0x30


def spec_bundle(body, fmt):
    """A trust bundle: PEM certificates and nothing else, or a SPIFFE JWK set (the /.well-known/spiffe/bundle shape)
    whose keys hold no private part. Parsed as far as the stdlib can: every certificate's body is DER."""
    if fmt not in BUNDLE_FORMATS:
        raise Refused(f"format: {str(fmt)[:20]!r} is not {' or '.join(BUNDLE_FORMATS)}")
    raw = str(body or "")
    if not raw.strip() or len(raw.encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise Refused(f"bundle: empty, or over {MAX_BUNDLE_BYTES} bytes")
    if fmt == "pem":
        blocks = _PEM_CERT_RE.findall(raw)
        if not blocks or _PEM_CERT_RE.sub("", raw).strip() or not all(_der_ok(b) for b in blocks):
            raise Refused("bundle: not PEM certificates alone (another block, text outside them, or a body that is not DER)")
        return raw
    try:
        doc = json.loads(raw)
    except ValueError:
        raise Refused("bundle: a spiffe bundle is a JSON JWK set") from None
    keys = doc.get("keys") if isinstance(doc, dict) else None
    if not isinstance(keys, list) or not keys:
        raise Refused("bundle: a JWK set with at least one key")
    for k in keys:
        if not isinstance(k, dict) or k.get("use") not in ("x509-svid", "jwt-svid") or k.get("kty") not in ("EC", "RSA", "OKP"):
            raise Refused("bundle: every key has use x509-svid or jwt-svid and kty EC, RSA or OKP")
        if any(p in k for p in ("d", "p", "q", "dp", "dq", "qi", "k")):
            raise Refused("bundle: a key carries a private part; a bundle is public keys only")
        if k.get("use") == "x509-svid" and not (isinstance(k.get("x5c"), list) and k["x5c"] and all(_der_ok(c) for c in k["x5c"])):
            raise Refused("bundle: an x509-svid key carries its certificate as DER in x5c")
    return raw


def parse_spire_entries(text):
    """`spire-server entry show` text -> one dict per entry (the registry's parse_entry_show, kept here stdlib-only)."""
    out, cur = [], {}
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
            td = (val[len("spiffe://"):] if val.startswith("spiffe://") else val).strip("/")
            if td and td not in cur.setdefault("federates_with", []):
                cur["federates_with"].append(td)
        elif key == "X509-SVID TTL":
            cur["ttl"] = val if val and val != "default" else None
    return out


def spec_operator_name(value):
    name = str(value or "").strip()
    if not OPERATOR_NAME_RE.fullmatch(name):
        raise Refused(f"operator: {name[:40]!r} is not an operator name")
    return name


def spec_operator_service(value):
    # no default: a request that names no service must not restart every one of them
    svc = str(value or "").strip()
    if svc not in OPERATOR_SERVICES:
        raise Refused(f"service: {svc[:30]!r} is not one of {', '.join(OPERATOR_SERVICES)}")
    return svc


def spec_log_tail(value):
    if value is None:
        return 200
    if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and value.isascii() and value.isdigit())):
        raise Refused("tail: a whole number of lines")
    tail = int(value)
    if not (LOG_TAIL_BOUNDS[0] <= tail <= LOG_TAIL_BOUNDS[1]):
        raise Refused(f"tail: {LOG_TAIL_BOUNDS[0]} to {LOG_TAIL_BOUNDS[1]} lines")
    return tail


def spec_fingerprint(value):
    fp = str(value or "").strip().lower()
    if not FINGERPRINT_RE.fullmatch(fp):
        raise Refused("fingerprint: an operator node's x509pop fingerprint is 40 or 64 hex characters")
    return fp


def mem_available_gib():
    try:
        with open("/proc/meminfo") as f:
            return next(int(line.split()[1]) for line in f if line.startswith("MemAvailable")) / 1024 ** 2
    except (OSError, ValueError, StopIteration):
        return None


def instance_paths(instance=""):
    """The paths a runner INSTANCE owns (§HELLOFRAME lane 6, 2026-09-18). Empty = the single runner of a host, every
    path byte-identical to what P2 fixed; a name = a second runner beside it (the network's own host runs the
    production runner and frame-up is proven there too): its own sockets under /run/theprotocol/<name>/, its own
    state (and so its own jobs and audit), its own policy and unit. ONE definition, read by the runner's Config and
    by frame-runner-install.py, so the two cannot name different places."""
    if not instance:
        return {"unit": "theprotocol-frame-runner", "config": "/etc/theprotocol/frame-runner.json",
                "socket": "/run/theprotocol/frame-runner.sock",
                "operator_socket": "/run/theprotocol/operator/frame-runner.sock",
                "state": "/var/lib/theprotocol/frame-runner",
                "runtime_dir": "theprotocol", "state_dir": "theprotocol/frame-runner"}
    if not INSTANCE_RE.fullmatch(str(instance)):
        raise ValueError(f"a runner instance is named like a frame ({INSTANCE_RE.pattern}), not {instance!r}")
    return {"unit": f"theprotocol-frame-runner-{instance}", "config": f"/etc/theprotocol/frame-runner-{instance}.json",
            "socket": f"/run/theprotocol/{instance}/frame-runner.sock",
            "operator_socket": f"/run/theprotocol/{instance}/operator/frame-runner.sock",
            "state": f"/var/lib/theprotocol/frame-runner-{instance}",
            "runtime_dir": f"theprotocol/{instance}", "state_dir": f"theprotocol/frame-runner-{instance}"}
TICKER_RE = re.compile(r"[A-Z]{2,6}")
JOB_ID_RE = re.compile(r"[0-9a-f]{16}")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
RESUMABLE_STEPS = ("compose", "spire", "seed", "login", "emission", "vhosts", "admin", "jurisdiction", "canary", "wire", "mtls")
SPEC_FIELDS = ("name", "frame_label", "ticker", "currency_name", "mint", "theme", "description", "operator_label",
               "location_label", "lat", "lng", "website", "registry_image", "teg_image", "es_image")
MAX_REQUEST_BYTES = 64 * 1024
EVENTS_PAGE = 500


class Refused(Exception):
    """A sentence for the caller. Nothing was started."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path, data, mode=0o600):
    tmp = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# A credential may be NAMED in a string crossing this seam. It may never be RESOLVED in one.
#
# §OPDIST (2026-09-16). Both key hunts on this seam walk dicts and lists and cannot see inside a STRING, and the
# stack phase REQUIRES `compose`, which is a large string — so a DSN inside it walked through every check either
# side had. `_check_operator_vhost` already said so in its own docstring and fixed it for the vhost alone; this is
# that rule, once, for every string.
#
# WHAT THE SHAPE HAD TO BE, AND WHY IT IS NOT "REFUSE THE NAME". Measured on the compose the distribution actually
# ships (scripts/distribution/docker-compose.operator.yml, retired since: its control test reads the bundle's
# nginx-templates copy): it carries DATABASE_URL six times and five DSNs, and
# EVERY password is a `${PG_PASS_*}` placeholder, with zero of the four names carrying a value. Refusing the NAME
# would therefore have refused every legitimate stack spec there has ever been — a gate that only ever fails,
# which is worse than the hole it closes. Refusing the RESOLVED FORM passes that compose with margin and still
# catches the thing worth catching. That is D12 read as a guard: a compose is topology, values live in env.
_PLACEHOLDER_RE = re.compile(r"\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\{\{[^}]*\}\}")
_DSN_RE = re.compile(r"\b([a-z][a-z0-9+.\-]*)://([^/\s@\"']+)@", re.I)
_CRED_NAMES = ("DATABASE_URL", "API_KEY_SECRET", "SECRET_KEY", "JWT_SECRET_KEY")
_CRED_ASSIGN_RE = re.compile(r"\b(" + "|".join(_CRED_NAMES) + r")\s*[:=]\s*([^\s\"',]+)")
_DB_SCHEMES = ("postgres://", "postgresql://", "postgresql+", "mysql://", "redis://", "amqp://")


def _is_placeholder(value):
    """True when the value is ENTIRELY interpolation — `${X}`, `$X`, `{{X}}`, or several of them. Stripping the
    placeholders and asking whether anything is left handles `${A}${B}` without a second rule."""
    return value != "" and _PLACEHOLDER_RE.sub("", value).strip() == ""


def scan_for_resolved_credentials(text, where, allow_placeholders=True):
    """Refuse a string that carries a resolved credential. Returns None; raises Refused.

    allow_placeholders=True  — for spec strings (the compose): a value may NAME a key and interpolate it, because
                               that is what a topology-only compose is supposed to look like.
    allow_placeholders=False — for the host vhost: an nginx config has no legitimate reason to mention a database
                               at all, so the name alone is refused there. That is a surface-specific tightening
                               of one rule, not a second rule, and the parameter says which surface asked.
    """
    if not isinstance(text, str) or not text:
        return
    for scheme, userinfo in ((m.group(1), m.group(2)) for m in _DSN_RE.finditer(text)):
        _, sep, password = userinfo.partition(":")
        if not sep or not password:
            continue  # a userinfo with no password is an address, not a credential
        if allow_placeholders and _is_placeholder(password):
            continue
        raise Refused(f"{where} carries a {scheme}:// address whose password is a resolved value, not a "
                      f"${{PLACEHOLDER}}: a credential inside a STRING passes every key hunt on both sides of "
                      f"this seam, so it is refused here. Nothing was done.")
    for name, value in _CRED_ASSIGN_RE.findall(text):
        if allow_placeholders and _PLACEHOLDER_RE.search(value):
            continue
        raise Refused(f"{where} assigns {name} the resolved value {value[:8]!r}...: the one-shot holds neither "
                      f"the frame's database nor a token, and a string is not an exemption from that. "
                      f"Nothing was done.")
    if not allow_placeholders:
        for name in _CRED_NAMES:
            if name in text:
                raise Refused(f"{where} mentions {name}, which an nginx config never needs; refused whether or "
                              f"not it is interpolated.")
        for scheme in _DB_SCHEMES:
            if scheme in text:
                raise Refused(f"{where} mentions {scheme}, which an nginx config never needs; refused whether or "
                              f"not it is interpolated.")


def pid_alive(pid, needle=None):
    """Alive AND (when a needle is given) still the process we started: a recycled pid is not our job."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if needle:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return needle.encode() in f.read()
        except OSError:
            return False
    return True


# ---- the caddy edge (§HELLOFRAME lane 6, 2026-09-18) ------------------------------------------------------------
# A frame stood up by frame-up on its own host has no host nginx: its public door is its own `<name>-edge` Caddy
# container, reading <stack>/edge/Caddyfile, whose template imports operators/*.caddy. Under the "caddy" posture the
# runner writes ONE site file per operator into that directory and asks the edge to validate and reload. The block
# names only what it needs: the operator's public name, the host address its registry port is bound to (the docker
# bridge gateway, so the port is not public) and the frame's TLS choice. The helpers are pure so a test can pin the
# text without a host; the runner methods below do the writing and the two docker execs.
EDGE_MODES = ("nginx", "caddy")
CADDY_CONFIG = "/etc/caddy/Caddyfile"
CADDY_ADAPTER = "caddyfile"


def caddy_tls_line(edge_tls, acme_email=""):
    """The `tls` directive of an operator block: `tls internal` when the frame's edge issues its own certificates,
    `tls <email>` when an ACME account is named, and NO line otherwise (Caddy then uses the Caddyfile's global
    `email`, which the frame's own block relies on the same way)."""
    if str(edge_tls or "").strip().lower() == "internal":
        return "tls internal"
    email = str(acme_email or "").strip()
    if email and "@" in email and not re.search(r"[\s{}\"']", email):
        return f"tls {email}"
    return ""


def caddy_operator_block(*, domain, bind_address, reg_port, tls_line=""):
    """The whole site file for one operator. The upstream is the HOST address the operator's registry port is bound
    to, never a container name: the edge runs in host network mode and shares no compose network with the operator."""
    domain = str(domain or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", domain) or ".." in domain:
        raise ValueError(f"operator edge: not a host name: {domain!r}")
    try:
        port = int(reg_port)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError(f"operator edge: not a port: {reg_port!r}")
    bind = str(bind_address or "127.0.0.1").strip()
    if not re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}|\[[0-9A-Fa-f:.]+\]", bind):
        raise ValueError(f"operator edge: not a bind address: {bind_address!r}")
    lines = [
        f"# operator {domain}: written by the frame runner; a teardown removes this file. Do not edit by hand.",
        f"{domain} {{",
    ]
    if tls_line:
        lines.append(f"\t{tls_line}")
    lines += [
        "\tencode gzip zstd",
        "\theader {",
        '\t\tStrict-Transport-Security "max-age=31536000; includeSubDomains"',
        '\t\tX-Content-Type-Options "nosniff"',
        '\t\tX-Frame-Options "SAMEORIGIN"',
        '\t\tReferrer-Policy "strict-origin-when-cross-origin"',
        "\t\t-Server",
        "\t}",
        f"\treverse_proxy {bind}:{port} {{",
        "\t\theader_up X-Forwarded-Proto https",
        "\t\theader_up X-Real-IP {remote_host}",
        "\t}",
        "}",
        "",
    ]
    return "\n".join(lines)


def caddy_site_path(operators_dir, slug):
    """<operators_dir>/<slug>.caddy — the ONLY names the edge's `import operators/*.caddy` reads; the backups this
    runner keeps beside them end in .bak or .torn-down and are never imported."""
    if not re.fullmatch(r"[a-z0-9-]{1,40}", str(slug or "")):
        raise ValueError(f"operator edge: not an operator slug: {slug!r}")
    return os.path.join(operators_dir, f"{slug}.caddy")


def read_caddy_global_email(text):
    """The `email` of a Caddyfile's global options block, or "" (an internal-CA frame carries a comment there)."""
    m = re.search(r"^\s*email\s+(\S+)\s*$", text or "", re.M)
    return m.group(1) if m else ""


def frame_up_facts(stack_dir, name):
    """What the caddy posture needs from the frame, read from <stack>/frame-up.json (frame-up writes it; nothing else
    stands such a frame up). ok=False with a `why` when the file is missing or unreadable, so the caller records a
    SKIP instead of guessing at an edge that may not exist. Keys frame-up may not have written yet fall back to the
    layout its template fixes: the container `<name>-edge`, the directory <stack>/edge/operators, the ACME address
    from the Caddyfile's global block."""
    stack_dir = str(stack_dir or "")
    path = os.path.join(stack_dir, "frame-up.json")
    try:
        with open(path) as f:
            data = json.load(f) or {}
    except FileNotFoundError:
        return {"ok": False, "why": f"{path} is missing: this frame was not stood up by frame-up, so it has no "
                                    f"Caddy edge the runner could write a site into"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "why": f"{path} could not be read: {exc}"}
    edge = data.get("edge") if isinstance(data.get("edge"), dict) else {}
    acme_email = str(edge.get("acme_email") or "")
    if not acme_email:
        try:
            with open(os.path.join(stack_dir, "edge", "Caddyfile")) as f:
                acme_email = read_caddy_global_email(f.read())
        except OSError:
            acme_email = ""
    return {"ok": True, "public_name": str(data.get("public_name") or ""),
            "container": str(edge.get("container") or f"{name}-edge"),
            "operators_dir": str(edge.get("operators_dir") or os.path.join(stack_dir, "edge", "operators")),
            "tls": str(edge.get("tls") or ""), "acme_email": acme_email, "https_port": edge.get("https_port")}


class Config:
    """Every path and limit: paths from the environment (and keyword overrides in tests), policy from
    /etc/theprotocol/frame-runner.json on the host."""

    def __init__(self, conf=None, **paths):
        env = os.environ
        # §HELLOFRAME lane 6: FRAME_RUNNER_INSTANCE scopes the socket, the operator socket, the state and the policy
        # (instance_paths); unset = the single runner, byte-identical. FRAME_RUNNER_SOCKET / _OPERATOR_SOCKET /
        # _STATE / _CONFIG set explicitly still win, as they always have.
        self.instance = str(paths.get("instance") or env.get("FRAME_RUNNER_INSTANCE") or "")
        try:
            _own = instance_paths(self.instance)
        except ValueError as exc:
            raise SystemExit(str(exc))
        self.socket = paths.get("socket") or env.get("FRAME_RUNNER_SOCKET") or _own["socket"]
        self.state = paths.get("state") or env.get("FRAME_RUNNER_STATE") or _own["state"]
        self.driver = paths.get("driver") or env.get(
            "FRAME_RUNNER_DRIVER", "/opt/theprotocol/stack/Agentvault2/scripts/hetzner_demo/standup_driver.py")
        # §MTLSHOPS T2 (2026-09-15): the compose template that driver renders from; a resume compares a frame's stack with it
        self.template = paths.get("template") or env.get("FRAME_RUNNER_TEMPLATE") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(self.driver)))),
            "templates", "frame-test", "docker-compose.frame-test.yml.tmpl")
        # §TESTBED: the sandbox engine, in the export this runner serves (beside the driver's scripts/)
        self.frame_sandbox = paths.get("frame_sandbox") or env.get("FRAME_RUNNER_FRAME_SANDBOX") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(self.driver)))),
            "scripts", "distribution", "frame-sandbox.py")
        self.teardown = paths.get("teardown") or env.get(
            "FRAME_RUNNER_TEARDOWN", "/opt/theprotocol/stack/Agentvault2/scripts/hetzner_demo/teardown_hetzner_frame.sh")
        self.python = paths.get("python") or env.get("FRAME_RUNNER_PYTHON", "/usr/bin/python3")
        self.stack_root = (paths.get("stack_root") or env.get("FRAME_RUNNER_STACK_ROOT", "/opt/theprotocol/stack")).rstrip("/")
        self.protected_list = paths.get("protected_list") or env.get(
            "FRAME_RUNNER_PROTECTED_LIST", "/etc/theprotocol/protected-frames.list")
        self.dig = paths.get("dig") or env.get("FRAME_RUNNER_DIG", "dig")
        self.certbot = paths.get("certbot") or env.get("FRAME_RUNNER_CERTBOT", "certbot")
        self.letsencrypt = (paths.get("letsencrypt") or env.get("FRAME_RUNNER_LETSENCRYPT", "/etc/letsencrypt")).rstrip("/")
        self.config_path = paths.get("config") or env.get("FRAME_RUNNER_CONFIG") or _own["config"]
        if conf is None:
            conf = read_json(self.config_path, {})
        images = conf.get("images") or {}
        self.images = {"registry": list(images.get("registry") or []), "teg": list(images.get("teg") or []),
                       # §SOVKIT: the store's allowlist; empty = the driver's own default (a hand-run posture)
                       "event_store": list(images.get("event_store") or [])}
        # §SOVKIT (2026-09-14): the kit's two built images; optional lists, their FIRST entry is what the driver
        # builds the frame with (the provisioner reads FRAME_TEST_AUDITOR_IMAGE / FRAME_TEST_DIRECTORY_IMAGE)
        self.kit_images = {"auditor": list(images.get("auditor") or []), "directory": list(images.get("directory") or [])}
        # whether a frame this runner builds is also wired into THIS host's sidecars (Prometheus targets, the
        # host auditor slot, the SNI map, the apex ws lane). True on the host that runs the fleet; a stranger's
        # host that has no sidecars.json sets it false and the frame relies on its own kit.
        self.wire_prod = bool(conf.get("wire_prod", True))
        # §LANTERNT3 (2026-09-16, his word "lantern shouldnt be sandbox"): the posture a frame this runner builds is
        # BORN with. It was the literal "sandbox" in driver_argv, and standup_driver.py:695 turns the rate limiter OFF
        # for any posture that is not "production" — so every frame the runner has ever built (hansa, orchard, both
        # lanterns) went live on a public DNS name with a real certificate and NO rate limiting. Measured 2026-09-16:
        # https://lantern.theprotocol.cloud answered /health with no x-ratelimit-limit at all while EU returned 1200.
        # Row 66 of the DIDWIDEN residues and residue 5 of FRAMESHOWCASE are this, twice reported and never closed.
        # Default production, because a runner-built frame is internet-facing by construction; a host that really wants
        # a sandbox frame says so in its own policy. The driver's own gate (:2137) refuses a standup whose measured
        # limiter disagrees with the posture it claims, so this cannot go live lying in either direction.
        self.posture = str(conf.get("posture", "production"))
        if self.posture not in ("production", "sandbox"):
            raise SystemExit(f'the runner policy\'s posture must be "production" or "sandbox", not {self.posture!r}')
        self.domain = conf.get("domain", "theprotocol.cloud")
        self.allowed_uids = {int(u) for u in conf.get("allowed_uids", [0, 1000])}
        self.socket_group = conf.get("socket_group", "deploy")
        # §HELLOFRAME lane 6 (2026-09-18): the EDGE posture. Absent or "nginx" = this host's nginx carries the
        # operator's vhost and SNI line, byte for byte as before this key existed. "caddy" = a frame stood up by
        # frame-up on its own host: its public door is its own <name>-edge Caddy container, the operator gets one site
        # file under <stack>/edge/operators/ and a reload of that container, and host nginx is never touched.
        self.edge = str(conf.get("edge") or "nginx")
        # §TESTBED: whether a frame on this host may provision its own sandbox through the operator socket. Absent = no.
        self.sandboxes = bool(conf.get("sandboxes", False))
        # §NIGHTPROV: whether the host's nightly job may stand up its sandbox pair here, and where the job keeps each
        # pair's shared tester fixtures (<dir>/<pair>/fixtures.secret.json, 600, written by the job). Absent = no.
        nightly = conf.get("nightly")
        self.nightly = bool(nightly)
        self.nightly_dir = ((nightly.get("dir") if isinstance(nightly, dict) else None) or paths.get("nightly_dir")
                            or env.get("FRAME_RUNNER_NIGHTLY_DIR") or "/var/lib/theprotocol/nightly").rstrip("/")
        # the pair's registry workers: its tester host's count (sbx-alpha runs 8), so the suites run against the posture
        # they are tuned on. 0 or absent = the provisioner's default.
        workers = nightly.get("registry_workers", 0) if isinstance(nightly, dict) else 0
        if isinstance(workers, bool) or not isinstance(workers, int) or not (workers == 0 or 1 <= workers <= 16):
            raise SystemExit(f"the runner policy's nightly.registry_workers must be 0 or 1-16, not {workers!r}")
        self.nightly_registry_workers = workers
        if self.edge not in EDGE_MODES:
            raise SystemExit(f"the runner policy's edge must be one of {sorted(EDGE_MODES)}, not {self.edge!r}")
        # §LANTERNT3: the operator socket. A frame's registry mounts THIS one and never the full socket, so the
        # ops it may ask for are bounded by the file it can see. Default beside the first, same dir, same mode.
        # ⚠ IN ITS OWN DIRECTORY, and that is load-bearing twice over. A frame's registry bind-mounts the
        # DIRECTORY, never the socket file: make_server removes and re-binds the socket on every restart, so a
        # file bind-mount would leave the container pointing at a deleted inode until someone recreated it (which
        # is why the console mounts /run/theprotocol rather than the file). And a directory of its own is what
        # keeps the full socket out of the frame's sight — mounting the shared directory would hand it both.
        self.operator_socket = paths.get("operator_socket") or env.get("FRAME_RUNNER_OPERATOR_SOCKET") or \
            os.path.join(os.path.dirname(self.socket), "operator", "frame-runner.sock")
        self.max_load = float(conf.get("max_load", 40))
        self.min_mem_gib = float(conf.get("min_mem_gib", 15))
        self.min_free_gb = float(conf.get("min_free_gb", 60))
        self.plan_timeout = int(conf.get("plan_timeout_s", 300))
        # §LANTERNT3 (2026-09-16): the outbound relay a PRODUCTION-posture frame needs. standup_driver.py:2048
        # refuses that posture without one, and it is right to (findings row 181): verification ON with no relay is
        # the §OPGUIDE-2 lockout, and a production frame that silently comes up mail-dead can send no verification,
        # no password reset, no frame invitation and no operator application. The token is a FILE reference, never a
        # value in this policy, exactly as the dns block's token_file is.
        mail = conf.get("mail")
        self.mail = None
        if mail:
            try:
                self.mail = {"server": str(mail["server"]), "address": str(mail["address"]),
                             "token_file": str(mail.get("token_file", "/root/.noreply_smtp_token")),
                             "port": int(mail.get("port", 587))}
            except KeyError as exc:
                raise SystemExit(f"the mail block of the runner's policy lacks {exc}")
        dns = conf.get("dns")
        self.dns = None
        if dns:   # P5: present means the runner owns the DNS names of the frames it builds
            try:
                self.dns = {"zone_id": str(dns["zone_id"]), "ipv4": str(dns["ipv4"]),
                            "token_file": dns.get("token_file", "/etc/theprotocol/frame-runner/cloudflare.token"),
                            "api": dns.get("api", frame_dns.API), "resolver": dns.get("resolver", "1.1.1.1"),
                            "propagation_timeout_s": float(dns.get("propagation_timeout_s", 300)),
                            "poll_interval_s": float(dns.get("poll_interval_s", 5))}
            except KeyError as exc:
                raise SystemExit(f"the dns block of the runner's policy lacks {exc}")


class Runner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.RLock()
        os.makedirs(cfg.state, mode=0o700, exist_ok=True)
        os.chmod(cfg.state, 0o700)
        for sub in ("jobs", "frames", "dns"):
            os.makedirs(os.path.join(cfg.state, sub), mode=0o700, exist_ok=True)
        self._recover()

    # ── records ──────────────────────────────────────────────────────────────────────────────────────────────────
    def job_dir(self, job_id):
        return os.path.join(self.cfg.state, "jobs", job_id)

    def job(self, job_id):
        if not isinstance(job_id, str) or not JOB_ID_RE.fullmatch(job_id):
            raise Refused("job_id: the 16 hex characters a start returned")
        rec = read_json(os.path.join(self.job_dir(job_id), "job.json"))
        if rec is None:
            raise Refused(f"no job {job_id}")
        return rec

    def save_job(self, rec):
        write_json(os.path.join(self.job_dir(rec["id"]), "job.json"), rec)

    def jobs(self):
        recs = [read_json(p) for p in glob.glob(os.path.join(self.cfg.state, "jobs", "*", "job.json"))]
        return sorted((r for r in recs if r), key=lambda r: r.get("created", ""), reverse=True)

    def frame(self, name):
        return read_json(os.path.join(self.cfg.state, "frames", f"{name}.json"))

    def save_frame(self, rec):
        write_json(os.path.join(self.cfg.state, "frames", f"{rec['name']}.json"), rec)

    def audit(self, uid, op, **fields):
        path = os.path.join(self.cfg.state, "audit.jsonl")
        with open(path, "a") as f:
            f.write(json.dumps({"ts": now(), "uid": uid, "op": op, **fields}) + "\n")
        os.chmod(path, 0o600)

    @staticmethod
    def summary(rec):
        return {k: rec.get(k) for k in ("id", "op", "name", "state", "created", "ended", "exit_code")}

    def protected_names(self):
        try:
            with open(self.cfg.protected_list) as f:
                return {line.split("#", 1)[0].strip() for line in f if line.split("#", 1)[0].strip()}
        except OSError:
            raise Refused(f"the protected-frames list {self.cfg.protected_list} is unreadable (fail closed)")

    def active(self):
        for rec in self.jobs():
            if rec.get("state") in ("running", "cancelling") and pid_alive(rec.get("pid"), rec.get("needle")):
                return rec
        return None

    def events(self, job_id, after=0):
        try:
            with open(os.path.join(self.job_dir(job_id), "progress.jsonl")) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        out = []
        for line in lines[after:after + EVENTS_PAGE]:
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"event": "unreadable", "raw": line[:200]})
        return out, min(len(lines), after + EVENTS_PAGE), lines

    def last_event(self, job_id):
        lines = self.events(job_id, 0)[2]
        for line in reversed(lines):
            try:
                return json.loads(line)
            except ValueError:
                continue
        return None

    # ── validation ───────────────────────────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _text(spec, key, max_len):
        value = spec.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Refused(f"{key}: required text")
        value = value.strip()
        if len(value) > max_len or CONTROL_RE.search(value) or value.startswith("-"):
            raise Refused(f"{key}: at most {max_len} characters, no control characters, not starting with '-'")
        return value

    def validate_spec(self, spec, check_new=True, uid=None):
        if not isinstance(spec, dict):
            raise Refused("spec: a JSON object")
        unknown = sorted(set(spec) - set(SPEC_FIELDS))
        if unknown:
            raise Refused(f"unknown field(s) {', '.join(unknown)}; the runner takes only {', '.join(SPEC_FIELDS)}")
        name = spec.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise Refused("name: 2 to 32 characters of a-z, 0-9 and '-', starting with a letter, not ending with '-'")
        if name in self.protected_names():
            raise Refused(f"name: {name} is a protected frame ({self.cfg.protected_list})")
        nightly = self.nightly_child(name, uid)
        if check_new:
            if self.frame(name):
                raise Refused(f"name: this runner already built {name}; tear it down first")
            existing = [d for d in glob.glob(os.path.join(self.cfg.stack_root, f"{name}-*"))
                        if re.fullmatch(rf"{re.escape(name)}-\d+", os.path.basename(d))]
            if existing:
                raise Refused(f"name: a stack dir for {name} already exists ({existing[0]})")
        clean = {"name": name, "frame_label": self._text(spec, "frame_label", 60)}
        ticker = spec.get("ticker")
        if not isinstance(ticker, str) or not TICKER_RE.fullmatch(ticker):
            raise Refused("ticker: 2 to 6 capital letters")
        clean["ticker"] = ticker
        clean["currency_name"] = self._text(spec, "currency_name", 40)
        mint = spec.get("mint", 1000000)
        if isinstance(mint, bool) or not isinstance(mint, int) or not 1 <= mint <= 10 ** 9:
            raise Refused("mint: a whole number from 1 to 1000000000")
        clean["mint"] = mint
        theme = spec.get("theme", "neural")
        if theme not in ("neural", "sovereign"):
            raise Refused("theme: neural or sovereign")
        clean["theme"] = theme
        clean["description"] = self._text(spec, "description", 400)
        clean["operator_label"] = self._text(spec, "operator_label", 80)
        clean["location_label"] = self._text(spec, "location_label", 80)
        for key, low, high in (("lat", -90, 90), ("lng", -180, 180)):
            value = spec.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise Refused(f"{key}: a number from {low} to {high} (a frame's location is declared, never invented)")
            clean[key] = float(value)
        website = spec.get("website", "")
        if not isinstance(website, str) or (website and (not website.startswith("https://") or len(website) > 200
                                                          or CONTROL_RE.search(website) or " " in website)):
            raise Refused("website: empty, or an https:// URL of at most 200 characters")
        clean["website"] = website
        for key, kind in (("registry_image", "registry"), ("teg_image", "teg")):
            value = spec.get(key)
            if value not in self.cfg.images[kind]:
                allowed = ", ".join(self.cfg.images[kind]) or "none (fill images in /etc/theprotocol/frame-runner.json)"
                raise Refused(f"{key}: {value or '(empty)'} is not an allowlisted {kind} image; allowed: {allowed}")
            clean[key] = value
        # §SOVKIT: the event store's image follows the same allowlist; a spec that omits it takes the FIRST allowlisted
        # entry (Frame Management has no field for it yet), and a policy without the list leaves the driver's default.
        es_allowed = self.cfg.images["event_store"]
        es = spec.get("es_image") or (es_allowed[0] if es_allowed else None)
        if es_allowed:
            if es not in es_allowed:
                raise Refused(f"es_image: {es or '(empty)'} is not an allowlisted event_store image; allowed: {', '.join(es_allowed)}")
            clean["es_image"] = es
        elif es:
            raise Refused("es_image: this host allowlists no event_store image (fill images.event_store in /etc/theprotocol/frame-runner.json)")
        if nightly:
            clean["nightly"] = nightly
        return clean

    def nightly_child(self, name, uid):
        """§NIGHTPROV: {"pair", "role"[, "federate_with"]} for a nightly pair's frame, None for any other name. Refused: a
        name in the job's namespace that is not a pair's frame, a policy that offers no nightly pairs, a caller that is
        not root (Frame Management's uid 1000 never stands one up), and the pair's b while its a is not a live frame this
        runner built (b federates with a at its own standup)."""
        m = NIGHTLY_CHILD_RE.fullmatch(name)
        if not m:
            if NIGHTLY_RESERVED_RE.fullmatch(name):
                raise Refused(f"name: {name} is in the nightly job's names (nt<yymmdd>[x<n>] and its frames a and b); "
                              f"a frame of its own takes another name")
            return None
        if not self.cfg.nightly:
            raise Refused(f"name: {name} is a frame of a nightly pair, and this runner's policy does not offer nightly pairs")
        if uid != 0:
            raise Refused(f"name: {name} is a frame of a nightly pair; only the host's nightly job (root, on the full socket) "
                          f"stands one up")
        pair, role = m.group(1), m.group(2)
        out = {"pair": pair, "role": role}
        if role == "b":
            a = self.frame(f"{pair}a")
            if not a or a.get("state") != "live" or not os.path.isdir(a.get("stack_dir") or ""):
                raise Refused(f"name: {name} federates with {pair}a at its standup, and {pair}a is not a live frame this "
                              f"runner built; stand {pair}a up first")
            out["federate_with"] = a["stack_dir"]
        return out

    def nightly_fixtures(self, pair):
        return os.path.join(self.cfg.nightly_dir, pair, "fixtures.secret.json")

    def built_frame(self, name):
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise Refused("name: not a frame name")
        if name in self.protected_names():
            raise Refused(f"{name} is a protected frame ({self.cfg.protected_list})")
        frame = self.frame(name)
        if not frame:
            raise Refused(f"{name} was not built by this runner; it only touches frames it built")
        if frame.get("adopted"):
            # §HELLOFRAME lane 6: adopted, not built. The runner does this frame's OPERATOR work only; its lifecycle
            # (resume, teardown, the admin secret) belongs to frame-up and frame-down, which stood it up.
            raise Refused(f"{name} was adopted by this runner, not built by it: the runner does its operator work only; "
                          f"resume, teardown and reveal are frame-up's and frame-down's")
        stack = frame.get("stack_dir") or ""
        if not stack or os.path.dirname(stack) != self.cfg.stack_root or not os.path.isdir(stack):
            raise Refused(f"{name}: no stack dir on record under {self.cfg.stack_root}")
        meta = read_json(os.path.join(stack, "hetzner-demo-run.json")) or {}
        if meta.get("name") != name:
            raise Refused(f"{name}: the stack dir's run meta names {meta.get('name')!r}, not {name}")
        return frame

    # ── the driver ───────────────────────────────────────────────────────────────────────────────────────────────
    def driver_argv(self, spec, allocate=True):
        domain, name = self.cfg.domain, spec["name"]
        # §LANTERNT3: the policy's posture; §NIGHTPROV: a nightly pair's frame is a sandbox, by its (reserved) name only
        nightly = spec.get("nightly")
        posture = "sandbox" if nightly else self.cfg.posture
        argv = [self.cfg.python, "-u", self.cfg.driver,
                "--name", name, "--frame-label", spec["frame_label"], "--trust-domain", f"{name}.{domain}",
                "--public-url", f"https://{name}.{domain}", "--es-public-url", f"https://{name}-es.{domain}",
                "--push-public-url", f"https://{name}-push.{domain}",
                "--ticker", spec["ticker"], "--currency-name", spec["currency_name"], "--mint", str(spec["mint"]),
                "--admin-email", f"admin@{name}.{domain}", "--admin-name", f"{spec['frame_label']} Admin",
                "--theme", spec["theme"], "--description", spec["description"],
                "--operator-label", spec["operator_label"], "--location-label", spec["location_label"],
                "--lat", str(spec["lat"]), "--lng", str(spec["lng"]), "--website", spec["website"],
                "--registry-image", spec["registry_image"], "--teg-image", spec["teg_image"],
                *(["--es-image", spec["es_image"]] if spec.get("es_image") else []),
                # §LANTERNT3: posture from the policy, never a literal. env_label follows it so the tier a frame is
                # GROUPED under on the status page cannot disagree with the posture it actually carries.
                "--posture", posture, "--env-label", posture, "--render-vhosts",
                "--max-load", str(self.cfg.max_load)]
        if self.cfg.wire_prod:   # §SOVKIT: optional; a host without sidecars runs the frame on its own kit
            # §NIGHTPROV: a nightly frame takes the two pieces it federates through, never the fleet's whole wiring
            argv += ["--wire-only", NIGHTLY_WIRE] if nightly else ["--wire-prod"]
        if nightly:
            # §NIGHTPROV: the pair's sandbox shape, derived here and never taken from a caller: the tester runs against
            # the frame itself (the docker socket, his "tester keeps socket"), both frames share the job's fixture set
            # and one identity net the job created, and b federates with a (FX pool and all, standup_federate.py)
            argv += ["--tester-self", "--tester-fixture-secrets", self.nightly_fixtures(nightly["pair"]),
                     "--identity-net", f"{nightly['pair']}-identity", "--identity-net-external",
                     # the bundle endpoint by its name on the pair's identity net. The driver's default since §F6 A4 is
                     # the public host and the published port, which a container on this host cannot reach when it
                     # shares a network with the SPIRE server behind that port (the hairpin falls to the docker proxy,
                     # and ufw drops it on INPUT): measured 2026-09-27 14:36Z, nt260927x1b's invitation probe to
                     # https://nt260927x1a.theprotocol.cloud:8515/ timed out while nt260927x1a-spire-server:8443 answered
                     "--bundle-public-url", f"https://{name}-spire-server:8443/"]
            if self.cfg.nightly_registry_workers:
                argv += ["--registry-workers", str(self.cfg.nightly_registry_workers)]
            if nightly.get("federate_with"):
                argv += ["--federate-with", nightly["federate_with"]]
        if self.cfg.dns:   # P5: the runner creates the names first, so the driver issues the certificate itself
            argv += ["--acme", "--dns-by-runner"]
        if allocate:
            argv.append("--allocate-ports")
        return argv

    def driver_env(self, secrets_dir=None, mail=True):
        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
               "HOME": os.environ.get("HOME", "/root"), "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1",
               "FRAME_PROTECTED_LIST": self.cfg.protected_list}
        if secrets_dir:
            env["FRAME_SECRETS_DIR"] = secrets_dir
        # §LANTERNT3: all three or none. The driver treats a half-supplied relay as an error, and a token file that
        # is missing or empty must read as "no relay" rather than as an empty password the relay would reject.
        if self.cfg.mail and mail:   # §NIGHTPROV: a nightly sandbox mails nobody (frame-sandbox.py's rule)
            try:
                token = open(self.cfg.mail["token_file"]).read().strip()
            except OSError:
                token = ""
            if token:
                env["FRAME_MAIL_SERVER"] = self.cfg.mail["server"]
                env["FRAME_MAIL_ADDRESS"] = self.cfg.mail["address"]
                env["FRAME_MAIL_TOKEN"] = token
                env["FRAME_MAIL_PORT"] = str(self.cfg.mail["port"])
        # §SOVKIT: the kit images the policy allowlists; the provisioner reads these (first entry = the build)
        if self.cfg.kit_images.get("auditor"):
            env["FRAME_TEST_AUDITOR_IMAGE"] = self.cfg.kit_images["auditor"][0]
        if self.cfg.kit_images.get("directory"):
            env["FRAME_TEST_DIRECTORY_IMAGE"] = self.cfg.kit_images["directory"][0]
        return env

    def load_gate(self):
        """The gate every job takes. An op that only gives resources back (an operator teardown) takes this one alone:
        the memory and disk floors in host_gates would refuse the act that raises them (2026-09-16 20:04Z, beacon: the
        teardown of jelgava was refused at 59 GB free under the 60 GB floor, so the one job that frees disk was shut)."""
        try:
            with open("/proc/loadavg") as f:
                load1 = float(f.read().split()[0])
            if load1 >= self.cfg.max_load:
                return [f"load1={load1} is at or above {self.cfg.max_load:g}"]
        except (OSError, ValueError):
            return ["/proc/loadavg is unreadable"]
        return []

    def host_gates(self):
        problems = self.load_gate()
        try:
            with open("/proc/meminfo") as f:
                kib = next(int(line.split()[1]) for line in f if line.startswith("MemAvailable"))
            if kib / 1024 ** 2 < self.cfg.min_mem_gib:
                problems.append(f"MemAvailable={kib // 1024 ** 2} GiB is under {self.cfg.min_mem_gib:g} GiB")
        except (OSError, ValueError, StopIteration):
            problems.append("/proc/meminfo is unreadable")
        free_gb = shutil.disk_usage(self.cfg.stack_root).free / 1024 ** 3
        if free_gb < self.cfg.min_free_gb:
            problems.append(f"{free_gb:.0f} GB free under {self.cfg.stack_root} is under {self.cfg.min_free_gb:g} GB")
        return problems

    def launch(self, op, uid, name, argv, request, secrets_dir=None, progress=True, job_id=None, needle=None, extra=None,
               mail=True):
        job_id = job_id or uuid.uuid4().hex[:16]
        jd = self.job_dir(job_id)
        # exist_ok because an op may STAGE INPUTS into the job dir before the process starts — operator_provision
        # writes its spec there, and the container reads it the instant it runs, so it cannot be written after.
        # (Found by the success path: the op created the dir, launch created it again, FileExistsError. Every
        # test I had written covered a refusal, and none covered the path where validation passes.)
        os.makedirs(jd, mode=0o700, exist_ok=True)
        if secrets_dir is None:
            secrets_dir = os.path.join(jd, "secrets")
            os.makedirs(secrets_dir, mode=0o700)
        if progress:
            argv = argv + ["--progress-file", os.path.join(jd, "progress.jsonl")]
        log_path = os.path.join(jd, "stdout.log")
        log_file = open(log_path, "ab", buffering=0)
        os.chmod(log_path, 0o600)
        rec = {"id": job_id, "op": op, "name": name, "state": "running", "uid": uid, "created": now(),
               "started_epoch": int(time.time()), "request": request, "argv": argv, "secrets_dir": secrets_dir,
               "needle": needle or os.path.basename(argv[2] if argv[1:2] == ["-u"] else argv[1]), **(extra or {})}
        proc = subprocess.Popen(argv, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=self.driver_env(secrets_dir, mail=mail), cwd=os.path.dirname(self.cfg.driver),
                                start_new_session=True)
        rec["pid"] = proc.pid
        self.save_job(rec)
        threading.Thread(target=self._watch, args=(job_id, proc, log_file), daemon=True).start()
        return rec

    # §LANTERNT3: a ceiling for operator jobs. This runner does ONE job at a time, and `proc.wait()` has no
    # timeout — so a one-shot that hangs holds the only slot forever and every later provision, teardown and
    # standup waits behind a container nobody is watching. Set ABOVE the caller's own deadline on purpose
    # (agentvault2-b5's is 2400 s): the caller should give up first, so the accurate message reaches the human,
    # and this exists only to stop a hung container becoming a stuck runner. Frame jobs keep their old behaviour,
    # because a standup legitimately runs long and nothing here has measured what long means for one.
    OPERATOR_JOB_CEILING_S = 3600

    def _watch(self, job_id, proc, log_file):
        rec0 = self.job(job_id) or {}
        if str(rec0.get("op") or "").startswith("operator_"):
            try:
                code = proc.wait(timeout=self.OPERATOR_JOB_CEILING_S)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                code = proc.wait()
                rec = self.job(job_id) or {}
                rec.setdefault("notes", []).append(
                    f"killed after {self.OPERATOR_JOB_CEILING_S}s: a one-shot that hangs holds this runner's only "
                    f"job slot, so it is stopped rather than left. Its caller will have given up before this.")
                self.save_job(rec)
            log_file.close()
            self._finish(job_id, code)
            return
        code = proc.wait()
        log_file.close()
        self._finish(job_id, code)

    def _finish(self, job_id, code):
        with self.lock:
            rec = self.job(job_id)
            last = self.last_event(job_id)
            if rec.get("state") == "cancelling":
                state = "cancelled"
            elif code is None:   # recovered after a runner restart: the exit code is gone, the progress file is not
                event = (last or {}).get("event")
                state = "succeeded" if event == "live" else ("failed" if event == "fail" else "lost")
            else:
                state = "succeeded" if code == 0 else "failed"
            rec.update({"state": state, "exit_code": code, "ended": now()})
            # §LANTERNT3: operator_host_work exits 3 for REFUSED (nothing was done) and 4 for a failure inside,
            # which is RunnerRefused vs RunnerError one level down. Carrying it back is what lets the rail tell
            # "cannot" from "failed" — the distinction whose absence spent a one-time activation code this
            # morning. Its result file is the op's answer, so it is read here while the job dir is still ours.
            if rec.get("op", "").startswith("operator_"):
                rec["refused"] = (code == 3)
                try:
                    result_path = os.path.join(self.job_dir(job_id), "result.json")
                    with open(result_path) as f:
                        rec["result"] = json.load(f)
                    # the one-shot writes it 0644 as uid 1000, and a provision's result carries the operator's
                    # first-boot admin password (measured on beacon/jelgava): the tree is root-only, the file is too
                    os.chmod(result_path, 0o600)
                except (OSError, ValueError):
                    rec["result"] = None
                if rec["op"] == "operator_provision" and state == "succeeded":
                    self._apply_operator_edge(rec)
                    if rec.get("state") == "succeeded":
                        self._apply_operator_redis_acl(rec)
                    # §OPDIST: provisioned is not connected. Marked BEFORE the save, so a poller that sees
                    # "succeeded" also sees that the frame links are still being made, and does not read one as
                    # the other.
                    if rec.get("state") == "succeeded":
                        rec["links_state"] = "pending"
                if rec["op"] == "operator_teardown" and state == "succeeded":
                    # inside the lock, so a poller sees "running" until the sweep, the edge and the stack dir are done:
                    # the registry writes its torn-down row on "succeeded", and must never write it early
                    self._finish_operator_teardown(rec)
                # AFTER the edge and the ACL: either can turn a job the one-shot finished into a failed one
                rec["reason"] = (self._operator_reason(job_id, rec)
                                 if rec.get("state") in ("failed", "cancelled", "lost") else None)
            self.save_job(rec)
            self._record_frame(rec)
        # OUTSIDE the lock: registration talks to docker and to the frame's auditor, which can take tens of
        # seconds, and this lock is every other op's too.
        if rec.get("links_state") == "pending":
            try:
                self._register_operator_with_frame(rec)
            except Exception as exc:  # noqa: BLE001 — a crash here must not leave the state at "pending" forever
                rec.setdefault("links", {})["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            rec["links_state"] = "done"
            with self.lock:
                self.save_job(rec)
        # A resume re-runs compose on the frame and can RECREATE its auditor, which drops every venue network the links
        # attached (see _relink_auditor). Outside the lock for the same reason as the links.
        if rec.get("op") == "resume" and rec.get("state") == "succeeded":
            try:
                rec["relink"] = self._relink_auditor(rec.get("name") or "")
            except Exception as exc:  # noqa: BLE001 — a relink failure is recorded, never raised out of _finish
                rec["relink"] = {"state": "NOT RELINKED", "why": f"{type(exc).__name__}: {str(exc)[:200]}"}
            with self.lock:
                self.save_job(rec)
        # LAST, after every reader of the spec (the edge check and the links above): nothing reads it again.
        if str(rec.get("op") or "").startswith("operator_"):
            self._scrub_operator_spec(job_id)

    # ⚠ FOUND BY THE COMMANDER ON FRAME MANAGEMENT (2026-09-16): "operator_provision · beacon · failed 9s · all steps not
    # run". The page drew the frame STANDUP step list for an operator job (which writes no step events) and the rail
    # carried no reason, so a job that had extracted, written env and markers, chowned the ACL and failed at compose up
    # was described as never having started. The reason is written HERE, redacted before it is stored, so no reader of
    # the record (the rail, the page, a human) can meet a credential in it.
    REASON_MAX = 600
    _REDACTIONS = (
        (re.compile(r"(://[^:/@\s]+):[^\s]*"), r"\1:<redacted>"),            # a DSN's password, complete or truncated
        (re.compile(r"dpt_[A-Za-z0-9]+"), "dpt_<redacted>"),                    # an image-registry pull token
        (re.compile(r"tp_fed_[A-Za-z0-9_-]+"), "tp_fed_<redacted>"),            # a federation licence key
        (re.compile(r"(?i)(password|secret|token)=\S+"), r"\1=<redacted>"),   # key=value forms
        (re.compile(r"[0-9a-fA-F]{32,}"), "<hex-redacted>"),                    # anything shaped like a generated secret
    )

    @classmethod
    def _redact_reason(cls, text):
        for pattern, repl in cls._REDACTIONS:
            text = pattern.sub(repl, text)
        return text

    def _operator_reason(self, job_id, rec):
        """One redacted line saying why an operator job did not succeed: the one-shot's last output line (its refusal or
        failure sentence, or an uncaught exception's last line) and the last note that names a FAILED step."""
        parts = []
        try:
            with open(os.path.join(self.job_dir(job_id), "stdout.log"), errors="replace") as f:
                lines = [l.strip() for l in f.read().splitlines() if l.strip()]
            if lines:
                parts.append(lines[-1])
        except OSError:
            pass
        notes = ((rec.get("result") or {}).get("notes") or []) if isinstance(rec.get("result"), dict) else []
        notes = list(notes) + list(rec.get("notes") or [])   # the runner's own post-steps (edge, ACL) note here
        failed = [str(n).strip() for n in notes if "FAILED" in str(n) or "refused" in str(n).lower()]
        if failed and failed[-1] not in parts:
            parts.append(failed[-1])
        if not parts:
            return f"no output: the one-shot exited {rec.get('exit_code')} before writing anything"
        reason = self._redact_reason(" · ".join(" · ".join(p.splitlines()) for p in parts))
        return reason if len(reason) <= self.REASON_MAX else reason[: self.REASON_MAX - 1] + "…"

    SPEC_SCRUB_MARK = "<scrubbed when the job ended: consumed by the one-shot, read by nothing since>"

    def _scrub_operator_spec(self, job_id):
        """§OPDIST (2026-09-16, the footprint census on beacon): a finished operator job kept its docker_pull_token, and a
        stack job keeps the operator's live secrets and every resolved env value, in a spec nothing reads again. The
        VALUES go; the KEYS stay, so the record still says what was passed. Written in place, mode unchanged."""
        path = os.path.join(self.job_dir(job_id), "spec.json")
        try:
            with open(path) as f:
                spec = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(spec, dict):
            return
        changed = False
        if spec.get("docker_pull_token"):
            spec["docker_pull_token"] = self.SPEC_SCRUB_MARK; changed = True
        for block in ("operator_secrets", "env"):
            if isinstance(spec.get(block), dict):
                for k, v in list(spec[block].items()):
                    if v not in (None, "", self.SPEC_SCRUB_MARK):
                        spec[block][k] = self.SPEC_SCRUB_MARK; changed = True
        if changed:
            mode = os.stat(path).st_mode & 0o777
            tmp = path + ".scrub"
            with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode), "w") as f:
                json.dump(spec, f)
            os.chmod(tmp, mode)
            os.replace(tmp, path)

    def find_stack_dir(self, name, since_epoch):
        best, best_ts = None, -1
        for d in glob.glob(os.path.join(self.cfg.stack_root, f"{name}-*")):
            m = re.fullmatch(rf"{re.escape(name)}-(\d+)", os.path.basename(d))
            if not m or int(m.group(1)) < since_epoch - 5:
                continue
            if (read_json(os.path.join(d, "hetzner-demo-run.json")) or {}).get("name") != name:
                continue
            if int(m.group(1)) > best_ts:
                best, best_ts = d, int(m.group(1))
        return best

    def _record_frame(self, rec):
        name = rec["name"]
        if rec["op"] == "standup":
            stack = self.find_stack_dir(name, rec.get("started_epoch", 0))
            if stack:
                self.save_frame({"name": name, "built_by_job": rec["id"], "stack_dir": stack, "spec": rec["request"],
                                 "secrets_dir": rec["secrets_dir"], "dns_managed": bool(rec.get("dns_managed")),
                                 "state": "live" if rec["state"] == "succeeded" else f"standup {rec['state']}",
                                 "created": rec["created"], "updated": now()})
        elif rec["op"] == "resume":
            frame = self.frame(name)
            if frame:
                frame.update({"state": "live" if rec["state"] == "succeeded" else f"resume {rec['state']}", "updated": now()})
                self.save_frame(frame)
        elif rec["op"] == "teardown" and rec["state"] == "succeeded":
            frame = self.frame(name)
            if frame:
                frame.update({"state": "torn down", "torn_down_by_job": rec["id"], "updated": now()})
                if frame.get("dns_managed"):
                    frame.update(self._teardown_names(name, rec.get("uid")))
                frame["secrets_cleanup"] = self._remove_frame_secrets(frame, rec.get("uid"))
                write_json(os.path.join(self.job_dir(rec["id"]), "frame.json"), frame)
                os.remove(os.path.join(self.cfg.state, "frames", f"{name}.json"))

    def _recover(self):
        for rec in self.jobs():
            if rec.get("state") not in ("running", "cancelling"):
                continue
            if pid_alive(rec.get("pid"), rec.get("needle")):
                threading.Thread(target=self._poll, args=(rec["id"], rec["pid"], rec.get("needle")), daemon=True).start()
            else:
                self._finish(rec["id"], None)

    def _poll(self, job_id, pid, needle):
        while pid_alive(pid, needle):
            time.sleep(5)
        self._finish(job_id, None)

    def _kill_if_alive(self, pid, needle):
        if pid_alive(pid, needle):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _refuse_if_busy(self):
        busy = self.active()
        if busy:
            raise Refused(f"job {busy['id']} ({busy['op']} {busy['name']}) is running: one job at a time")

    def running_jobs(self):
        return [r for r in self.jobs() if r.get("state") in ("running", "cancelling") and pid_alive(r.get("pid"), r.get("needle"))]

    def _refuse_if_busy_for(self, frame_name):
        """One job at a time, with ONE exception (§TESTBED): a sandbox job stands up its sandboxes and then provisions
        their cloud operators through the sandboxes' own consoles, which ask this runner for that operator work while
        the sandbox job holds the slot. A request for a frame the running sandbox job names as its child passes; while
        any other job runs, or a child's own job already runs, nothing does."""
        running = self.running_jobs()
        if not running:
            return
        only = running[0]
        if len(running) == 1 and only.get("op") in ("sandbox_up", "sandbox_down") and frame_name in (only.get("children") or []):
            return
        raise Refused(f"job {only['id']} ({only['op']} {only.get('name')}) is running: one job at a time")

    # ── ops ──────────────────────────────────────────────────────────────────────────────────────────────────────
    # ── DNS (P5) ─────────────────────────────────────────────────────────────────────────────────────────────────
    def dns_client(self):
        if not self.cfg.dns:
            raise Refused("DNS automation is not configured (no dns block in the runner's policy file)")
        d = self.cfg.dns
        return frame_dns.Cloudflare(d["token_file"], d["zone_id"], api=d["api"])

    def dns_path(self, name):
        return os.path.join(self.cfg.state, "dns", f"{name}.json")

    def dns_record(self, name):
        return read_json(self.dns_path(name)) or {"name": name, "records": []}

    def _save_dns(self, rec):
        if rec["records"]:
            write_json(self.dns_path(rec["name"]), rec)
        elif os.path.exists(self.dns_path(rec["name"])):
            os.remove(self.dns_path(rec["name"]))

    def _dns_name(self, name):
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise Refused("name: 2 to 32 characters of a-z, 0-9 and '-', starting with a letter, not ending with '-'")
        if name in self.protected_names():
            raise Refused(f"name: {name} is a protected frame ({self.cfg.protected_list})")
        return name

    def dns_state(self, name, client=None):
        """Read-only. Per host: the zone's records, each marked whether the runner created it (its id written down AND
        its comment still carrying the mark), and the resolver's answers. Overall: absent, propagating, ready, partial
        or refused, with the problems that refuse a standup."""
        client = client or self.dns_client()
        mine = {r.get("id") for r in self.dns_record(name)["records"]}
        hosts = []
        for host in frame_dns.names(name, self.cfg.domain):
            try:
                found = client.records(host)
            except frame_dns.DNSError as exc:
                raise Refused(str(exc))
            hosts.append({"host": host, "resolves": frame_dns.resolve(host, self.cfg.dns["resolver"], self.cfg.dig),
                          "records": [{"id": r.get("id"), "type": r.get("type"), "content": r.get("content"),
                                       "runner": r.get("id") in mine and frame_dns.carries_mark(r, name)}
                                      for r in found]})
        problems = []
        for h in hosts:
            foreign = [r for r in h["records"] if not r["runner"]]
            if foreign:
                what = ", ".join(str(r["type"]) + " " + str(r["content"]) for r in foreign)
                problems.append(f"{h['host']} already has a record the runner did not create ({what}): refused, never adopted")
            elif not h["records"] and h["resolves"]:
                problems.append(f"{h['host']} already resolves at {self.cfg.dns['resolver']} ({', '.join(h['resolves'])}) "
                                f"without a record in the zone: refused, never adopted")
        if problems:
            state = "refused"
        elif all(not h["records"] for h in hosts):
            state = "absent"
        elif all(h["records"] for h in hosts):
            state = "ready" if all(h["resolves"] for h in hosts) else "propagating"
        else:
            state = "partial"
        return {"name": name, "state": state, "problems": problems, "ipv4": self.cfg.dns["ipv4"], "hosts": hosts}

    def _plan_dns(self, name, doc):
        """The runner's half of a plan, read-only: what the zone and the resolver say about the four names."""
        try:
            state = self.dns_state(name)
        except Refused as exc:
            doc.setdefault("refusals", []).append(f"DNS automation: {exc}")
            doc["ok"] = False
            return
        doc.setdefault("derived", {})["dns_runner"] = state
        if state["problems"]:
            doc.setdefault("refusals", []).extend(state["problems"])
            doc["ok"] = False
            return
        missing = [h["host"] for h in state["hosts"] if not h["records"]]
        if missing:
            doc.setdefault("warnings", []).append(
                f"the frame runner creates {', '.join(missing)} (A {state['ipv4']}) at Start and waits until "
                f"{self.cfg.dns['resolver']} answers them")

    def _dns_ensure(self, name, uid, job):
        client = self.dns_client()
        state = self.dns_state(name, client)
        if state["problems"]:
            self.audit(uid, "dns_ensure", name=name, result="refused", problems=state["problems"])
            raise Refused("; ".join(state["problems"]))
        rec = self.dns_record(name)
        created = []
        for h in state["hosts"]:
            if h["records"]:
                continue
            try:
                made = client.create_a(h["host"], self.cfg.dns["ipv4"], frame_dns.mark(name, job))
            except frame_dns.DNSError as exc:
                self.audit(uid, "dns_ensure", name=name, result="failed", created=created, error=str(exc)[:300])
                raise Refused(f"{exc} (created before the failure: {', '.join(created) or 'none'}; dns_remove deletes them)")
            rec["records"].append({"id": made.get("id"), "host": h["host"], "content": made.get("content"), "job": job,
                                   "created": now()})
            self._save_dns(rec)   # each id is written down before the next change
            created.append(h["host"])
        self.audit(uid, "dns_ensure", name=name, job=job, created=created)
        return {"name": name, "created": created, "present": [h["host"] for h in state["hosts"] if h["records"]]}

    def _dns_remove(self, name, uid):
        rec = self.dns_record(name)
        if not rec["records"]:
            return {"name": name, "deleted": [], "kept": [], "note": "the runner holds no records for this name"}
        client = self.dns_client()
        deleted, kept = [], []
        for r in list(rec["records"]):
            try:
                live = [x for x in client.records(r["host"]) if x.get("id") == r.get("id")]
                if live and not frame_dns.carries_mark(live[0], name):
                    kept.append(f"{r['host']} (its comment no longer carries the runner's mark: left alone)")
                    continue
                if live:
                    client.delete(r["id"])
                deleted.append(r["host"] if live else f"{r['host']} (already gone)")
            except frame_dns.DNSError as exc:
                self.audit(uid, "dns_remove", name=name, result="failed", deleted=deleted, kept=kept, error=str(exc)[:300])
                raise Refused(f"{exc} (deleted before the failure: {', '.join(deleted) or 'none'})")
            rec["records"].remove(r)
            self._save_dns(rec)
        self.audit(uid, "dns_remove", name=name, deleted=deleted, kept=kept)
        return {"name": name, "deleted": deleted, "kept": kept}

    def _launch_driver(self, op, uid, name, argv, request, secrets_dir=None, manage_dns=False, mail=True):
        """Launch the driver. When the runner owns the frame's DNS, create the four names first (marked with this job)
        and run the driver behind `await-dns`, which waits for the resolver and then becomes the driver: the same pid and
        process group, and a needle (the driver's file name) that both command lines carry."""
        if not manage_dns:
            return self.launch(op, uid, name, argv, request=request, secrets_dir=secrets_dir, mail=mail)
        job_id = uuid.uuid4().hex[:16]
        self._dns_ensure(name, uid, job_id)
        d = self.cfg.dns
        wrapper = [self.cfg.python, "-u", os.path.abspath(__file__), "await-dns",
                   "--hosts", ",".join(frame_dns.names(name, self.cfg.domain)), "--resolver", d["resolver"],
                   "--timeout", str(d["propagation_timeout_s"]), "--interval", str(d["poll_interval_s"]),
                   "--dig", self.cfg.dig, "--"]
        return self.launch(op, uid, name, wrapper + argv, request=request, secrets_dir=secrets_dir, job_id=job_id,
                           needle=os.path.basename(self.cfg.driver), extra={"dns_managed": True}, mail=mail)

    def _remove_frame_secrets(self, frame, uid):
        """His word 2026-09-13 ("torn down secrets ... have no use anymore, you decide"): a torn-down frame's credential
        copies go with it. Only a `secrets` directory directly inside one of this runner's job directories is removed;
        any other path is named and left alone."""
        recorded = frame.get("secrets_dir") or ""
        path = os.path.realpath(recorded)
        jobs = os.path.realpath(os.path.join(self.cfg.state, "jobs"))
        if not recorded or os.path.basename(path) != "secrets" or os.path.dirname(os.path.dirname(path)) != jobs:
            result = f"left alone: {recorded!r} is not a runner job's secrets directory"
        elif not os.path.isdir(path):
            result = "none left"
        else:
            count = sum(len(files) for _, _, files in os.walk(path))
            try:
                shutil.rmtree(path)
                result = f"removed {count} file(s)"
            except OSError as exc:
                result = f"failed: {type(exc).__name__}"
        self.audit(uid, "teardown_secrets", name=frame.get("name"), result=result)
        return result

    def _teardown_names(self, name, uid):
        """After a successful teardown of a frame whose names the runner created: delete those records (only the ids it
        wrote down whose comment still carries its mark) and the certificate its --acme run issued for them. A standup that
        stopped before its certificate step issued none (§FRAMEPROV P4, plum at `emission`): certbot is not asked to delete
        a certificate that does not exist, and the answer says none was issued instead of reporting certbot's refusal."""
        out = {}
        try:
            out["dns_cleanup"] = self._dns_remove(name, uid)
        except Refused as exc:
            out["dns_cleanup"] = {"error": str(exc)[:300]}
        cert_name = f"{name}.{self.cfg.domain}"
        if not os.path.exists(os.path.join(self.cfg.letsencrypt, "renewal", f"{cert_name}.conf")):
            out["cert_cleanup"] = "none issued"
        else:
            try:
                p = subprocess.run([self.cfg.certbot, "delete", "--non-interactive", "--cert-name", cert_name],
                                   capture_output=True, text=True, timeout=120)
                out["cert_cleanup"] = ("deleted" if p.returncode == 0
                                       else f"certbot exit {p.returncode}: {(p.stderr or p.stdout or '')[-200:]}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                out["cert_cleanup"] = f"certbot failed: {type(exc).__name__}"
        self.audit(uid, "teardown_names", name=name, dns=out["dns_cleanup"], cert=out["cert_cleanup"])
        return out

    def handle(self, req, uid, allowed=None, pid=None):
        if uid not in self.cfg.allowed_uids:
            raise Refused(f"uid {uid} may not use the frame runner")
        allowed = tuple(allowed) if allowed is not None else OPS
        # §TESTBED: the caller's pid as the kernel reported it (SO_PEERCRED), never a field the caller wrote
        req = dict(req)
        req.pop("_peer_pid", None)
        if pid is not None:
            req["_peer_pid"] = pid
        op = req.get("op")
        if op not in allowed:
            # §LANTERNT3: "not on this socket" and "no such op" are different facts with different fixes —
            # mount the other socket, or fix the caller. A single "unknown op" would send a reader hunting
            # for a typo in a name that is spelled correctly.
            if op in SANDBOX_OPS and not self.cfg.sandboxes:
                raise Refused(f"op {op!r}: this runner's policy does not offer sandboxes (\"sandboxes\": true is a kit host's)")
            if op in OPS or op in OPERATOR_OPS or op in SANDBOX_OPS:
                raise Refused(f"op {op!r} is not served on this socket; this socket serves "
                              f"{', '.join(allowed)}")
            raise Refused(f"unknown op {op!r}; this socket serves {', '.join(allowed)}")
        return getattr(self, f"op_{op}")(req, uid)

    def image_drift(self):
        """Which frames this runner built are running a registry image the policy does not allowlist.

        ⚠ WHY THIS EXISTS: the allowlist is a CARRIER that no version roll touches, and it went stale three times
        in one day (2026-09-16) — at v0378 while the fleet was v0380, so a new frame would have been born with an
        SSRF hole that had just been closed everywhere else; at v0380 while lantern ran v0382, caught only
        because a ping's output happened to be read; and at v0382 with a v0383 roll pending, caught by the other
        session reading the file. Twice it was caught by luck and once by a person. Nothing gated it, because a
        fleet census answers "what is running" and an allowlist answers "what may exist", and no instrument we
        had asked the second question.

        It is reported rather than refused: drift is not always wrong (a frame may sit a version behind
        deliberately), and a runner that refused on it would refuse a standup for a reason that has nothing to do
        with the standup. Making it VISIBLE is the fix; making it fatal would be a different bug."""
        allowed = set()
        for tag in self.cfg.images.get("registry") or []:
            r = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                allowed.add(r.stdout.strip())
        out = []
        if not allowed:
            return out
        # enumerated the way line 1337 already does it; there is no frames() and I should not have assumed one
        for path in sorted(glob.glob(os.path.join(self.cfg.state, "frames", "*.json"))):
            f = read_json(path) or {}
            name = f.get("name")
            if not name:
                continue
            r = subprocess.run(["docker", "inspect", f"{name}-registry", "--format", "{{.Image}}"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0 or not r.stdout.strip():
                continue
            if r.stdout.strip() not in allowed:
                out.append({"frame": name, "running": r.stdout.strip()[:19],
                            "allowlisted": list(self.cfg.images.get("registry") or []),
                            "note": "this frame's registry image is not allowlisted; an operator_provision for "
                                    "it will be refused for an image that is correct"})
        return out

    def op_ping(self, req, uid):
        """What a caller may ask for: the allowlisted images, the domain every derived address uses, the steps a resume
        accepts and the spec's fields (the admin UI builds its form from this, so the two cannot drift)."""
        active = self.active()
        return {"version": VERSION, "uid": uid, "active": active["id"] if active else None, "domain": self.cfg.domain, "edge": self.cfg.edge,
                "images": self.cfg.images, "resumable_steps": list(RESUMABLE_STEPS), "spec_fields": list(SPEC_FIELDS),
                "dns_managed": bool(self.cfg.dns), "posture": self.cfg.posture, "sandboxes": self.cfg.sandboxes,
                "nightly": self.cfg.nightly,
                "mail_relay": bool(self.cfg.mail), "image_drift": self.image_drift()}

    # ── §LANTERNT3 operator ops — served ONLY on cfg.operator_socket ────────────────────────────────────
    # A frame's registry cannot provision its own cloud operator: the bundle is built through the host Docker
    # API (operator_provisioner._get_docker_client), and the frame template withholds that socket because a
    # docker socket is unrestricted root on the host. These ops move that work here, where the privilege is
    # already uid-gated, policy-bounded, host-gated and audited.

    def op_operator_ping(self, req, uid):
        """What a frame may ask for on this socket, and what it may NOT. A caller that can see this socket can
        read its own bound rather than discovering it by being refused."""
        return {"version": VERSION, "uid": uid, "socket": "operator", "image_drift": self.image_drift(),
                "ops": list(OPERATOR_OPS), "refused_here": list(OPS),
                "images": self.cfg.images, "domain": self.cfg.domain, "edge": self.cfg.edge,
                "max_load": self.cfg.max_load, "min_mem_gib": self.cfg.min_mem_gib,
                "min_free_gb": self.cfg.min_free_gb, "sandboxes": self.cfg.sandboxes}

    def caller_frame(self, pid):
        """(frame, None) for the frame whose container made this call, or (None, why). §TESTBED: every frame that mounts
        the operator socket presents uid 1000, so the name a request carries is a claim; the container the calling pid
        runs in (its cgroup) and that container's compose project are not."""
        cid = container_of_pid(pid)
        if not cid:
            return None, "the caller runs in no container this runner can name"
        r = subprocess.run(["docker", "inspect", cid, "--format", '{{index .Config.Labels "com.docker.compose.project"}}'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None, "the caller's container could not be inspected"
        project = r.stdout.strip()
        found = frame_of_project(project)
        return (found, None) if found else (None, f"the caller's container is compose project {project!r}, not a frame")

    def _claim_is_the_caller(self, req, uid, name):
        """Refuse a request that names a frame other than the one calling. Root (the host) may name any; a request with
        no peer pid (a direct call in a test) keeps the old behaviour."""
        pid = req.get("_peer_pid")
        if uid == 0 or pid is None:
            return
        who, why = self.caller_frame(pid)
        if who != name:
            raise Refused(f"frame {name!r} is not the calling frame ({who or why}): a frame asks this runner only for itself")

    def _operator_frame(self, req, uid=None):
        """The frame this request is about, refused unless THIS runner built it. agentvault2-b5: a registry
        asking for the wrong frame is a request the runner should decline rather than execute."""
        name = (req.get("frame") or "").strip()
        if not name:
            raise Refused("frame: the operator ops name the frame they are for")
        self._claim_is_the_caller(req, uid, name)
        frame = self.frame(name)
        if not frame:
            raise Refused(f"frame {name!r} was not built by this runner, so it is not this runner's to act on")
        return frame

    def op_operator_status(self, req, uid):
        """Two questions, one op, because a caller on this socket has exactly two.

        WITH a job_id: the state of THAT job — what the registry polls after provisioning. `status` and `events`
        are frame-management ops and are refused on this socket, so without this a caller could submit a job and
        never learn what became of it. (agentvault2-b5 caught that by ASKING which op to poll rather than
        assuming: his caller had OP_STATUS = "operator_status", and what I had built returned a frame summary
        that never changes, so his poll loop would have spun to its deadline against a job that had long
        finished. The seam invented twice, found before it cost anything.)

        WITHOUT one: what this runner knows about the frame's operators.

        ⚠ A KNOWN LIMIT, stated because the bound is only worth what is true of it: this socket cannot tell WHICH
        frame is calling. Every frame that mounts it presents uid 1000, so `frame` is a CLAIM, and a frame that
        can reach this socket can act on any frame this runner built. Today exactly one frame mounts it. The fix
        is a socket per frame — the same "the mount is the scope" idea one step further, where the listener that
        received the request IS the identity — and it is named rather than built because it is not free.
        """
        frame = self._operator_frame(req, uid)
        job_id = (req.get("job_id") or "").strip()
        if job_id:
            rec = self.job(job_id)
            if not rec or rec.get("name") != frame["name"] or not str(rec.get("op") or "").startswith("operator_"):
                raise Refused(f"job {job_id!r} is not an operator job of frame {frame['name']!r}")
            if rec.get("op") == "operator_teardown":
                rec = self._complete_teardown_result(rec)
            return {"job": {k: rec.get(k) for k in
                            ("id", "op", "name", "state", "created", "ended", "exit_code", "refused", "reason")},
                    "result": rec.get("result")}
        ops = list((frame.get("spec") or {}).get("operators") or [])
        return {"frame": frame["name"], "stack_dir": frame.get("stack_dir"), "state": frame.get("state"),
                "operators": ops, "host": {"problems": self.host_gates()}}

    # The spec a frame sends. agentvault2-b5 measured these against the host region rather than proposing them:
    # it READS seven fields of the application row and WRITES none, so nothing here is an ORM object and no
    # DATABASE_URL or API token crosses the seam. The one row that gets written (the federation licence) stays on
    # the registry side deliberately — a licence is issued ONCE, and a thing issued once must not sit on the far
    # side of a boundary that can fail after issuing it.
    # ⚠ THIS LIST IS THE SEAM AND IT NOW LIVES IN TWO PLACES. agentvault2-b5's operator_host_work checks the
    # same fields on its side, deliberately: two doors that both check disagree less often than one that assumes
    # the other did. These are the names HIS MODULE READS (measured, not proposed) plus image_id, which is the
    # runner's own — the module never sees it, because choosing the container is this side's job.
    # Neither of us changes a key here without telling the other.
    # ⚠ NOT UNDER `services`, AND THAT IS LOAD-BEARING (agentvault2-b5, measured in the image). Importing
    # agentvault_registry.services runs its package init, which imports webhook_service -> models -> database ->
    # config.Settings, and Settings REQUIRES DATABASE_URL and API_KEY_SECRET. The one-shot is given neither, on
    # purpose, because that is the entire reason this seam is worth having — so the container died at IMPORT,
    # before reading a spec, before touching a socket. Verified: `import agentvault_registry.services` with no
    # env raises a pydantic ValidationError naming both fields, while `import agentvault_registry` is clean.
    # Neither of us saw it because every proof we had lives on the NEAR side of the container start: the runner's
    # refusals fire before launch, and tests that import by path never run a package init.
    OPERATOR_ENTRY_MODULE = "agentvault_registry.host_work"

    OPERATOR_PHASES = ("bundle", "stack", "full")
    # Required in EVERY phase. `operator_secrets` is deliberately NOT here: a bundle job writes no env and no
    # markers, so requiring them would put four LIVE secrets in a spec file on disk for a job that never opens
    # them (agentvault2-b5). A secret written where nothing reads it is a secret with only downside.
    OPERATOR_SPEC_REQUIRED = ("frame", "operator_name", "safe_name", "operator_did", "docker_pull_token")
    OPERATOR_SPEC_REQUIRED_FULL = ("operator_secrets",)
    # "stack" is the SECOND half of an operator, run against the bundle activation already built — so it names
    # that bundle rather than making another, and it carries the secrets and the compose because it is the half
    # that writes env, markers and containers.
    OPERATOR_SPEC_REQUIRED_STACK = ("bundle_filename", "operator_secrets", "compose")
    # §OPDIST (agreed with agentvault2-b5): AUDITOR_RO_PASSWORD is the read-only credential his one-shot creates the
    # auditor_ro role with in the operator's own DB, and the one the frame auditor's venue entry uses. Required HERE
    # too, so a spec without it is refused before a job exists, not by the one-shot after one starts. It is not the
    # operator's to hold: his stack phase excludes it from .env.operator.
    OPERATOR_SECRET_KEYS = ("TEG_PROXY_TRUST_SECRET", "REGISTRY_PROXY_TRUST_SECRET",
                            "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG", "AUDITOR_RO_PASSWORD")

    def _operator_spec(self, req):
        """Validate what a frame sent. Refusals here cost nothing; a refusal AFTER the activation code is spent
        is the failure this whole route exists to remove."""
        spec = req.get("spec")
        if not isinstance(spec, dict):
            raise Refused("spec: one JSON object carrying the operator's fields")
        phase = spec.get("phase") or "full"
        if phase not in self.OPERATOR_PHASES:
            # refused, never defaulted to the biggest thing: b5's rule, and the right one — an unknown phase
            # defaulting to "full" would stand a stack up for a caller that asked for a bundle.
            raise Refused(f"spec.phase {phase!r} is not one of {', '.join(self.OPERATOR_PHASES)}")
        required = self.OPERATOR_SPEC_REQUIRED + {
            "full": self.OPERATOR_SPEC_REQUIRED_FULL,
            "stack": self.OPERATOR_SPEC_REQUIRED_STACK,
            "bundle": (),
        }[phase]
        if spec.get("images_local") is True:
            # §HELLOFRAME lane 6: the operator's images come from the export's LOCAL tag namespace, nothing is pulled,
            # and the frame's client sends no pull token on purpose (the one-shot reads the same flag); the first
            # stack-phase job from a frame-up frame was refused here for the key it must not carry.
            required = tuple(k for k in required if k != "docker_pull_token")
        missing = [k for k in required if not spec.get(k)]
        if missing:
            # all of them, not the first: one per round-trip is a conversation, and a caller fixing a spec should
            # need one round-trip and not seven.
            raise Refused(f"spec lacks {', '.join(missing)} (phase {phase})")
        # ⚠ THE CALLER DOES NOT NAME THE IMAGE. This side is the only one that can check the one-shot is the
        # image the frame is ACTUALLY RUNNING, and a value nobody is asked for is a value nobody can lie about.
        if spec.get("image_id"):
            raise Refused("spec.image_id: the runner takes the image from the frame's own registry container, "
                          "so that the one-shot is provably the image the frame runs. Do not send it.")
        if "env" in spec and not isinstance(spec["env"], dict):
            raise Refused("spec.env: the operator's env values, resolved by the caller, as an object")
        if phase in ("full", "stack"):
            secrets = spec.get("operator_secrets")
            if not isinstance(secrets, dict):
                raise Refused("spec.operator_secrets: the four per-operator secrets, as an object")
            missing_s = [k for k in self.OPERATOR_SECRET_KEYS if not secrets.get(k)]
            if missing_s:
                raise Refused(f"spec.operator_secrets lacks {', '.join(missing_s)}")
        elif spec.get("operator_secrets"):
            raise Refused("spec.operator_secrets in phase 'bundle': a bundle job opens none of them, so sending "
                          "them would write four live secrets to disk for nothing")
        # at ANY depth, matching his module's own check: a nested object is exactly where one would survive a
        # shallow scan, and "it is in env" was only ever one of the places it could hide.
        def _hunt(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("DATABASE_URL", "API_KEY_SECRET", "SECRET_KEY", "JWT_SECRET_KEY"):
                        raise Refused(f"spec carries {k!r} at {path or 'the top level'}: the one-shot holds "
                                      f"neither the frame's database nor a token, which is the only reason this "
                                      f"seam is worth having. Nothing was done.")
                    _hunt(v, f"{path}.{k}" if path else k)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    _hunt(v, f"{path}[{i}]")
            elif isinstance(node, str):
                # §OPDIST: the hunt above reads KEY NAMES, so it cannot see a credential that is inside a VALUE —
                # and `compose`, which the stack phase requires, is the largest string that crosses here. Measured
                # before choosing the rule: a live operator's 121 env keys carry no DSN with a password, and the
                # shipped compose's five DSNs are all placeholders, so this refuses the resolved form only.
                scan_for_resolved_credentials(node, f"spec.{path}" if path else "spec")
        _hunt(spec)
        return spec

    DOCKER_SOCKET = "/var/run/docker.sock"

    # ⚠ FOUND BY BEACON'S FIRST PROVISION (job d1de1776f2394128, 2026-09-16): `FileNotFoundError: CA key not found at
    # /opt/spire-ca/attestation-ca.key`. The bundle phase runs operator_provisioner.provision_operator, which reads its
    # SPIRE target from ENV and its attestation CA and nginx templates from DIRECTORIES. The frame's registry has all of
    # them (its env, and two bind mounts the image does not carry); the one-shot was given none. And the missing CA
    # was the LUCKY failure: SPIRE_CONTAINER and SPIRE_TRUST_DOMAIN default to Frame A's `agentvault-spire-server` and
    # `agentvault.com`, so the very next call would have registered this operator's entries in FRAME A's server.
    # Taken from the frame's running registry, exactly like the image: the one-shot sees what the in-registry path saw,
    # and a caller cannot name any of it. Names only cross; nothing credential-shaped is on the list.
    ONESHOT_ENV_FROM_FRAME = ("SPIRE_CONTAINER", "SPIRE_TRUST_DOMAIN", "SPIRE_FEDERATE_WITH", "SPIRE_SERVER_ADDRESS",
                              "SPIRE_SERVER_PORT", "OPERATOR_PROVISION_ALLOW_PARTIAL_SPIRE")
    ONESHOT_ENV_REQUIRED = ("SPIRE_CONTAINER", "SPIRE_TRUST_DOMAIN")
    # (env key the provisioner reads the directory from, its default = where the frame's registry mounts it)
    ONESHOT_DIRS_FROM_FRAME = (("OPERATOR_CA_DIR", "/opt/spire-ca"), ("NGINX_TEMPLATES_DIR", "/app/nginx-templates"))
    ONESHOT_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/,-]{0,252}")
    # ⚠ AND THE IMAGE CARRIES NO COMPOSE PLUGIN (V0385, as uid 1000: `docker: unknown command: docker compose`). The
    # Dockerfile copies only /usr/local/bin/docker out of docker:cli, because the in-registry path ran compose in a
    # docker:cli SIDECAR; host_work's stack phase calls `docker compose` itself, so every stack phase would fail after
    # the activation code is spent. The HOST's plugin (a static binary; this runner already drives the host's docker for
    # every frame) is bound read-only at a system plugin path, which the CLI searches whatever DOCKER_CONFIG says.
    COMPOSE_PLUGIN_CANDIDATES = ("/usr/libexec/docker/cli-plugins/docker-compose",
                                 "/usr/local/libexec/docker/cli-plugins/docker-compose",
                                 "/usr/lib/docker/cli-plugins/docker-compose",
                                 "/usr/local/lib/docker/cli-plugins/docker-compose")
    COMPOSE_PLUGIN_DEST = "/usr/libexec/docker/cli-plugins/docker-compose"

    def _host_compose_plugin(self):
        for path in self.COMPOSE_PLUGIN_CANDIDATES:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        raise Refused("this host has no docker compose plugin to hand the one-shot (the registry image carries none), "
                      "so its stack phase would fail after the activation code is spent; nothing was started")

    def _frame_provisioner_inputs(self, frame):
        """{"env": {...}, "binds": [(host source, container dest), ...]} for the one-shot, read from `<frame>-registry`.

        Refuses rather than defaulting: every default in the provisioner names Frame A. The SPIRE container the frame's
        registry names must belong to the frame's OWN compose project (the one-shot execs into it holding the docker
        socket), and each directory must be a bind mount on that container, which is where the provisioner reads it."""
        c = f"{frame['name']}-registry"
        r = subprocess.run(["docker", "inspect", c], capture_output=True, text=True, timeout=30)
        try:
            info = json.loads(r.stdout)[0] if r.returncode == 0 else None
        except (ValueError, IndexError):
            info = None
        if not info:
            raise Refused(f"{c} could not be inspected, so the one-shot's SPIRE target and CA cannot be read from the "
                          f"frame; this runner will not start it on the provisioner's defaults, which name Frame A")
        env = {}
        for kv in (info.get("Config") or {}).get("Env") or []:
            k, _, v = kv.partition("=")
            env[k] = v
        missing = [k for k in self.ONESHOT_ENV_REQUIRED if not env.get(k)]
        if missing:
            raise Refused(f"{c} carries no {', '.join(missing)}; the provisioner's defaults name Frame A's SPIRE "
                          f"(agentvault-spire-server, agentvault.com), so the one-shot is not started without them")
        out_env = {}
        for k in self.ONESHOT_ENV_FROM_FRAME:
            v = env.get(k)
            if not v:
                continue
            if not self.ONESHOT_VALUE_RE.fullmatch(v):
                # never echoed: the shape is the finding, and a value that fails it is not one to print
                raise Refused(f"{c}'s {k} is not the shape of a name, host or port, so it is not handed to a container "
                              f"that holds the docker socket")
            out_env[k] = v
        spire = out_env["SPIRE_CONTAINER"]
        p = subprocess.run(["docker", "inspect", spire], capture_output=True, text=True, timeout=30)
        try:
            labels = (json.loads(p.stdout)[0].get("Config") or {}).get("Labels") or {} if p.returncode == 0 else {}
        except (ValueError, IndexError, AttributeError):
            labels = {}
        wd = labels.get("com.docker.compose.project.working_dir") or ""
        own = frame.get("stack_dir") or ""
        if not (wd and own and os.path.realpath(wd) == os.path.realpath(own)):
            raise Refused(f"{c} names SPIRE container {spire!r}, which is not part of {frame['name']}'s own stack; the "
                          f"one-shot execs into it holding the docker socket, so it must be the frame's own server")
        binds = []
        mounts = info.get("Mounts") or []
        for key, default in self.ONESHOT_DIRS_FROM_FRAME:
            dest = env.get(key) or default
            m = next((m for m in mounts if m.get("Destination") == dest and m.get("Source")
                      and (m.get("Type") in (None, "bind"))), None)
            source = m["Source"] if m else None
            if not source and key == "OPERATOR_CA_DIR":
                # §F6 stage 4: a registry without the host holds no CA mount; the frame's OWN SPIRE server attests with the
                # same x509pop CA, and its server.conf names where (ca_bundle_path)
                source = self._spire_ca_dir(spire, labels_dir=own)
            if not source:
                raise Refused(f"{c} has no bind mount at {dest} ({key}), which is where the provisioner reads it; the "
                              f"one-shot would fail after the activation code is spent")
            binds.append((source, dest))
            if env.get(key):
                out_env[key] = dest
        return {"env": out_env, "binds": binds}

    CA_BUNDLE_RE = re.compile(r'ca_bundle_path\s*=\s*"([^"]+)"')

    def _spire_ca_dir(self, spire, labels_dir):
        """The host directory of the frame's x509pop CA, read from the frame's OWN SPIRE server (already checked to be in
        the frame's stack): its server.conf (a bind mount) names ca_bundle_path, and the server's bind at that file's
        directory is the source. None when any link is missing: the caller refuses, it never guesses a path."""
        r = subprocess.run(["docker", "inspect", spire], capture_output=True, text=True, timeout=30)
        try:
            mounts = (json.loads(r.stdout)[0].get("Mounts") or []) if r.returncode == 0 else []
        except (ValueError, IndexError, AttributeError):
            return None
        binds = {m.get("Destination"): m.get("Source") for m in mounts
                 if m.get("Source") and m.get("Type") in (None, "bind")}
        conf = binds.get("/opt/spire/conf/server.conf")
        if not conf or not os.path.realpath(conf).startswith(os.path.realpath(labels_dir) + os.sep):
            return None
        try:
            with open(conf) as f:
                found = self.CA_BUNDLE_RE.search(f.read())
        except OSError:
            return None
        if not found:
            return None
        src = binds.get(os.path.dirname(found.group(1)))
        if not src or not os.path.realpath(src).startswith(os.path.realpath(labels_dir) + os.sep):
            return None
        key = os.path.join(src, "attestation-ca.key")
        return src if os.path.isfile(key) else None

    def _stage_operator_work(self, jd, spec_doc):
        """The job dir the one-shot mounts at /work, and its spec.

        ⚠ FOUND BY THE FIRST LIVE RUN (tartu, job 22d4896c16ba4cf8, 2026-09-16): staged 0700 dir / 0600 spec, both root,
        while the registry image runs as its own user `agentvault` (uid 1000). The one-shot's entire output was
        `PermissionError: [Errno 13] Permission denied: '/work/spec.json'`. Every test faked the launch.
        The dir is 0770 and the spec 0640, root:root, reached through gid 0 (see _operator_oneshot_argv). On this host
        only root is in gid 0, so both stay root-only here. chmod is explicit: makedirs/open modes are cut by the umask."""
        os.makedirs(jd, mode=0o770, exist_ok=True)
        os.chmod(jd, 0o770)
        spec_path = os.path.join(jd, "spec.json")
        with open(os.open(spec_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o640), "w") as f:
            json.dump(spec_doc, f)
        os.chmod(spec_path, 0o640)
        return spec_path

    def _operator_oneshot_argv(self, job_id, jd, image_id, frame_inputs=None):
        """The one-shot: the registry image's own code, the docker socket it needs, the job dir for its answer, and the
        stack root it writes the operator's stack into. NOT --privileged and NOT --pid=host: the host nginx reload stays
        with THIS process, which is already root, rather than buying a container PID 1's namespace for one reload.

        It runs as the IMAGE'S OWN USER (uid 1000), deliberately not root: every existing operator stack is deploy:deploy
        (uid 1000), written by eu-registry running as 1000 with group_add of the socket's gid, and a root one-shot would
        make this the only root-owned operator. Two groups make that user able to do the job:
          · the docker socket's gid, READ from the socket (root:docker 0660), never a literal;
          · gid 0, because the one-shot writes the bundle under <frame stack dir>/operator-bundles, and a runner-built
            frame's stack dir is root:root 0750: uid 1000 cannot traverse it without the group bit. Inside, the container
            already holds the docker socket, so gid 0 grants nothing a docker call could not."""
        try:
            sock_gid = os.stat(self.DOCKER_SOCKET).st_gid
        except OSError as exc:
            raise Refused(f"{self.DOCKER_SOCKET} is not available to hand the one-shot ({exc})")
        return ["docker", "run", "--rm", "--name", f"operator-provision-{job_id}",
                "--group-add", str(sock_gid), "--group-add", "0",
                "-v", f"{self.DOCKER_SOCKET}:{self.DOCKER_SOCKET}",
                "-v", f"{jd}:/work",
                "-v", f"{self.cfg.stack_root}:{self.cfg.stack_root}",
                "-e", "OPERATOR_SPEC=/work/spec.json", "-e", "OPERATOR_RESULT=/work/result.json",
                # ⚠ THE IMAGE CARRIES NO PYTHONPATH. Its WorkingDir is /app and the package is at /app/src, so the
                # running registry gets this from its env file, not from the image. Without it the one-shot dies with
                # ModuleNotFoundError before any of the rest matters, invisible to every test that imports by path.
                "-e", "PYTHONPATH=/app/src",
                *[a for src, dest in (frame_inputs or {}).get("binds") or [] for a in ("-v", f"{src}:{dest}:ro")],
                *[a for k, v in sorted(((frame_inputs or {}).get("env") or {}).items()) for a in ("-e", f"{k}={v}")],
                "--entrypoint", "python3", image_id,
                "-m", self.OPERATOR_ENTRY_MODULE]

    def _operator_image(self, frame_name):
        """The image the one-shot runs: read from the FRAME'S OWN REGISTRY CONTAINER, never from the caller.

        By ID and never a tag (agentvault2-b5): a tag can move between a spec being written and a container
        starting, and then the thing that provisions an operator is not the thing anyone verified. An id cannot
        move. Taking it from the running container also makes the one-shot provably the same code the frame is
        running, which is the property that actually matters and which no caller can assert about itself."""
        c = f"{frame_name}-registry"
        r = subprocess.run(["docker", "inspect", c, "--format", "{{.Image}}"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0 or not r.stdout.strip():
            raise Refused(f"{c} is not running, so this runner cannot tell which image the frame is on and will "
                          f"not guess one")
        image_id = r.stdout.strip()
        if not re.fullmatch(r"(sha256:)?[0-9a-f]{12,64}", image_id):
            raise Refused(f"{c} reports {image_id!r}, which is not an image ID")
        allowed_ids = set()
        for tag in self.cfg.images.get("registry") or []:
            t = subprocess.run(["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
                               capture_output=True, text=True, timeout=30)
            if t.returncode == 0:
                allowed_ids.add(t.stdout.strip())
        if allowed_ids and image_id not in allowed_ids:
            raise Refused(f"{c} runs {image_id[:19]}, which is not an allowlisted registry image; the policy "
                          f"allows {', '.join(self.cfg.images.get('registry') or [])}. Roll the frame or update "
                          f"the policy, but this runner will not run an unallowlisted image.")
        return image_id

    def _frame_identity_network(self, frame):
        """The frame's identity network, READ FROM THE THING THAT NAMES IT: FT_REG_IDENTITY_NETWORK in the
        frame's own env file, which the standup driver wrote and the frame itself reads.

        Not derived from the slug, because no slug rule survives the population: lantern's is
        `lantern_network_identity` while EU's and ASIA's are both `fresh-identity`. A name that looks derivable
        on the node in front of you is the classic way to ship a rule that is wrong everywhere else.
        Stamped here rather than accepted from the caller, for the same reason as frame_stack_dir: the registry
        would be guessing, and a frame must not be able to name another frame's network by claiming it.

        §F6 B1 (2026-09-27): a frame born before the template carried that key (the sandbox pair, stood up 2026-09-03)
        names the network in one place only: IDENTITY_NETWORK in its registry's own environment, the value the
        registry's provisioner reads on its direct route. It is taken only when that registry is ATTACHED to the network
        it names; a name the frame is not on is not its identity network (measured on sbx-beta: the key absent from its
        env file, IDENTITY_NETWORK=sandbox-federation-identity, the registry on that network)."""
        env_path = os.path.join(frame.get("stack_dir") or "", ".env.frame-test")
        name = ""
        try:
            with open(env_path) as f:
                for line in f:
                    if line.startswith("FT_REG_IDENTITY_NETWORK="):
                        name = line.split("=", 1)[1].strip()
                        break
        except OSError as exc:
            raise Refused(f"cannot read {frame['name']}'s env to learn its identity network: {exc}")
        if not name:
            name = self._registry_identity_network(frame)
        if not name:
            raise Refused(f"{env_path} carries no FT_REG_IDENTITY_NETWORK and {frame['name']}-registry names no "
                          f"IDENTITY_NETWORK it is attached to, so this runner does not know which network the operator "
                          f"must join and will not guess one from the frame's name")
        r = subprocess.run(["docker", "network", "inspect", name, "--format", "{{.Name}}"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise Refused(f"{frame['name']} names identity network {name!r}, which does not exist on this host")
        return name

    NETWORK_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")

    def _registry_identity_network(self, frame):
        """IDENTITY_NETWORK from <frame>-registry's own environment when that registry is attached to it, else "".
        The runner (root) reads the container it inspects; nothing here is taken from a caller."""
        r = subprocess.run(["docker", "inspect", f"{frame['name']}-registry"], capture_output=True, text=True, timeout=30)
        try:
            info = json.loads(r.stdout)[0] if r.returncode == 0 else None
        except (ValueError, IndexError):
            info = None
        if not info:
            return ""
        value = ""
        for kv in (info.get("Config") or {}).get("Env") or []:
            k, _, v = kv.partition("=")
            if k == "IDENTITY_NETWORK":
                value = v.strip()
        attached = set(((info.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        return value if value and self.NETWORK_NAME_RE.fullmatch(value) and value in attached else ""

    def op_operator_provision(self, req, uid):
        """Do the host work a frame's own registry cannot: it has no docker socket, deliberately, because a
        docker socket is unrestricted root on the host. The privilege lives here for the seconds it is used, in a
        container this runner creates and destroys, under the same gates and audit every frame job gets."""
        frame = self._operator_frame(req, uid)
        spec = self._operator_spec(req)
        problems = self.host_gates()
        if problems:
            raise Refused("; ".join(problems))
        self._refuse_if_busy_for(frame["name"])

        image_id = self._operator_image(frame["name"])
        # ⚠ frame_stack_dir IS STAMPED HERE, never taken from the caller (agentvault2-b5's measurement): the
        # one-shot's own /app/operator-bundles dies with the container, so a bundle written there would put a
        # path in the row that nothing can open — "Bundle not found at None" one step later, which is exactly how
        # this morning failed. It writes into the FRAME's directory instead. And it comes from the frame record
        # this runner holds, so a frame cannot name another frame's directory by claiming it.
        frame_stack_dir = frame.get("stack_dir")
        if not frame_stack_dir or not os.path.isdir(frame_stack_dir):
            raise Refused(f"frame {frame['name']} has no readable stack dir on this host "
                          f"({frame_stack_dir or 'unset'}), so the one-shot has nowhere durable to write")

        identity_net = self._frame_identity_network(frame)
        inputs = self._frame_provisioner_inputs(frame)
        inputs["binds"] = list(inputs.get("binds") or []) + [(self._host_compose_plugin(), self.COMPOSE_PLUGIN_DEST)]
        # the one-shot execs into the SPIRE the spec names (the stack phase always did; since V0386 the bundle phase takes
        # all four from the spec too): a spec naming any other SPIRE is refused, never believed, and a value the frame's
        # registry does not carry cannot be verified, so it is refused as well. Compared as text: a port arrives as 8515.
        for field, key in SPEC_SPIRE_FIELDS:
            if spec.get(field) in (None, ""):
                continue
            own = inputs["env"].get(key)
            if own in (None, "") or str(spec[field]) != str(own):
                raise Refused(f"spec.{field} differs from {frame['name']}'s own ({key} on its registry"
                              f"{'' if own else ', which carries none'}); the one-shot acts on the frame's SPIRE only, "
                              f"so the spec is refused rather than believed")

        job_id = uuid.uuid4().hex[:16]
        jd = self.job_dir(job_id)
        self._stage_operator_work(jd, {**spec, "frame": frame["name"], "stack_root": self.cfg.stack_root,
                                       "frame_stack_dir": frame_stack_dir, "frame_identity_network": identity_net,
                                       "phase": spec.get("phase") or "full", "job_id": job_id})
        argv = self._operator_oneshot_argv(job_id, jd, image_id, inputs)
        rec = self.launch("operator_provision", uid, frame["name"], argv,
                          # application_id is not in the seam (b5's module never reads it) but the registry may
                          # pass it, and if it does it belongs in the audit row so a human can correlate a job
                          # with the application it was for. Optional, therefore .get.
                          request={"frame": frame["name"], "operator": spec["operator_name"],
                                   "application_id": spec.get("application_id"), "image_id": image_id,
                                   "phase": spec.get("phase") or "full"},
                          progress=False, job_id=job_id,
                          needle=f"operator-provision-{job_id}",
                          extra={"operator": spec["safe_name"]})
        self.audit(uid, "operator_provision", frame=frame["name"], operator=spec["safe_name"],
                   job_id=job_id, phase=spec.get("phase") or "full", image_id=image_id)
        # `job_id` at the top AND `job.id`: the registry's client reads the first (V0385 raised without it while the job it
        # had started went on to succeed), this runner's own drivers read the second. One id, both shapes.
        return {"started": True, "job_id": job_id,
                "job": self.public_job(rec) if hasattr(self, "public_job") else
                {k: rec[k] for k in ("id", "op", "name", "state", "created") if k in rec}}

    # ── the host edge, which is the runner's half and nobody else's ──────────────────────────────────────
    # The one-shot has no /etc/nginx and the frame's registry has no /host-nginx-sites (the T3 template withholds
    # it with the docker socket), so writing the operator's vhost and reloading nginx can only happen here. The
    # TEXT comes from the one-shot's result, not from a copy in this file: one definition of what a provisioned
    # operator looks like, rendered where the shared renderer lives, written where the privilege is. That is the
    # values-versus-structure line agentvault2-b5 drew, applied to the edge.
    NGINX_SITES = "/etc/nginx/sites-enabled"
    NGINX_BACKUPS = "/etc/nginx/vhost-backups"
    NGINX_SNI_MAP = "/etc/nginx/stream.d/federation-mtls.conf"

    def _check_operator_vhost(self, vhost, edge, slug):
        """What this vhost may make the host's nginx DO, checked against the values the spec declares.

        agentvault2-b5 named the escalation honestly rather than leaving it implied: a vhost the registry renders
        and the runner writes AS ROOT means the registry decides what this host serves. That is the same shape we
        decided the other way for the compose, so it does not get to pass here on the grounds that our own code
        rendered it. He offered spec["edge"] so this side can check rather than trust, and I am taking it.

        Not a re-render and not a diff: comparing text would couple this file to his template's whitespace and
        break provisioning on a legitimate change. It checks the three properties that decide what a vhost IS —
        whose name it answers to, where it sends traffic, and whose certificate it presents — plus a credential
        scan, because our key hunts walk dicts and lists and CANNOT see anything inside a string, and this is the
        first large string to cross the seam (his observation, and it applies to exactly this field)."""
        domain = str((edge or {}).get("domain") or "")
        if not domain:
            raise RuntimeError("spec.edge carries no domain, so nothing can be checked about the vhost and it "
                               "will not be written unchecked")
        ports = {str((edge or {}).get(k)) for k in ("reg_port", "fed_port") if (edge or {}).get(k)}
        ws_host = str((edge or {}).get("ws_events_host") or "")
        cert = str((edge or {}).get("ssl_cert_name") or "")

        # ⚠ nginx reads a directive WHEREVER it appears, not only at the start of a line, and these checks were
        # anchored with ^\s* — so the guard read a different config than nginx does, which is a parser
        # differential, which is the guard being absent. Measured 2026-09-16: ONE line,
        #   location /x { proxy_pass http://10.0.0.9:9999; server_name evil.example;
        #                 ssl_certificate /etc/letsencrypt/live/evil.example/fullchain.pem; }
        # was ACCEPTED with all three property checks finding nothing — a second hostname, an arbitrary
        # OFF-HOST upstream, and someone else's certificate, every one of them invisible. Found because I
        # asserted to agentvault2-b5 that a directory proxy WOULD be refused and then measured the claim.
        # Comments go first because nginx ignores them, so scanning them would refuse a legitimate commented
        # example; the credential scan below still reads the FULL text, since a secret in a comment is still a
        # secret this runner writes to disk as root.
        conf = re.sub(r"#[^\n]*", "", vhost)
        names = set(re.findall(r"\bserver_name\s+([^;]+);", conf))
        for n in names:
            if n.strip() != domain:
                raise RuntimeError(f"vhost answers to {n.strip()!r}, not this operator's {domain!r}")
        targets = re.findall(r"\bproxy_pass\s+(\S+?);", conf)
        for t in targets:
            host = re.sub(r"^https?://", "", t).split("/")[0]
            h, _, port = host.partition(":")
            if h in ("127.0.0.1", "localhost") and (not port or port in ports or host == ws_host):
                continue
            if ws_host and host == ws_host:
                continue
            raise RuntimeError(f"vhost proxies to {t!r}, which is neither this operator's loopback ports "
                               f"({', '.join(sorted(ports)) or 'none declared'}) nor the declared event-stream "
                               f"host {ws_host or '(none)'}")
        for certline in re.findall(r"\bssl_certificate(?:_key)?\s+(\S+?);", conf):
            if cert and f"/{cert}/" not in certline:
                raise RuntimeError(f"vhost presents {certline!r}, not the declared certificate {cert!r}")
        # §OPDIST: this list WAS the rule, and it lived only here while `compose` crossed the same seam
        # unscanned. It is now one shared rule called from both places; the vhost asks for the strict form,
        # because an nginx config never needs to name a database whether interpolated or not.
        try:
            scan_for_resolved_credentials(vhost, "vhost text", allow_placeholders=False)
        except Refused as e:
            raise RuntimeError(str(e))
        return sorted(names), targets

    # §PUSH (2026-10-06): an operator's push relay port is its block's fixed offset (AgentVault's
    # core/operator_compose.PUSH_PORT_OFFSET; the allocator reserves it). Pinned on both sides by their own tests.
    PUSH_PORT_OFFSET = 99
    _PUSH_PROXIED = ("= /v1/health", '~ "^/[-_A-Za-z0-9]{1,64}(,[-_A-Za-z0-9]{1,64})*/(json|sse|raw|ws|auth)$"')

    @staticmethod
    def _locations(conf):
        """(spec, body) for every `location <spec> { ... }`, braces matched (a body holds nested blocks)."""
        out = []
        for m in re.finditer(r"\blocation\s+([^{]+?)\s*\{", conf):
            depth, j = 1, m.end()
            while j < len(conf) and depth:
                depth += {"{": 1, "}": -1}.get(conf[j], 0)
                j += 1
            out.append((m.group(1).strip(), conf[m.end():j - 1]))
        return out

    def _check_operator_push(self, vhost, edge, slug):
        """§PUSH (2026-10-06, his words "fix the things you find on the way make it secure"): the operator's public push
        vhost, checked like its console vhost against what spec.edge declares, plus what the declaration itself must keep.
        The push name is ONE label under the operator's own suffix (`<label>-push.<suffix>` for `<label>.<suffix>`) and the
        port is its block's push offset, so a registry cannot name another host or reach another port through this
        field. And it must be SUBSCRIBE-ONLY by path: only the health check and the subscribe streams may reach the
        relay, and the catch-all must refuse (ntfy publishes on GET too, and since v2.16 deletes on GET)."""
        edge = edge or {}
        domain = str(edge.get("domain") or "")
        label, _, rest = domain.partition(".")
        push_host = str(edge.get("push_host") or "")
        if not (label and "." in rest and push_host == f"{label}-push.{rest}"):
            raise RuntimeError(f"spec.edge declares push host {push_host!r}, not {label}-push.{rest} for {domain!r}")
        try:
            push_port = int(edge.get("push_port"))
            fits = push_port == int(edge.get("reg_port")) + self.PUSH_PORT_OFFSET
        except (TypeError, ValueError):
            push_port, fits = None, False
        if not fits:
            raise RuntimeError(f"spec.edge declares push port {edge.get('push_port')!r}, not the block's "
                               f"+{self.PUSH_PORT_OFFSET} on {edge.get('reg_port')!r}")
        names, _ = self._check_operator_vhost(vhost, {"domain": push_host, "reg_port": push_port,
                                                      "ssl_cert_name": edge.get("ssl_cert_name")}, slug)
        conf = re.sub(r"#[^\n]*", "", vhost)
        locs = self._locations(conf)
        for spec, body in locs:
            if "proxy_pass" in body and spec not in self._PUSH_PROXIED:
                raise RuntimeError(f"the push vhost lets location {spec!r} reach the relay: only the health check and "
                                   f"the subscribe streams may (subscribe only)")
        if not any(spec == "/" and re.fullmatch(r"\s*return\s+403;\s*", body) for spec, body in locs):
            raise RuntimeError("the push vhost's catch-all does not refuse (`location / { return 403; }`)")
        return names

    def _apply_operator_edge(self, rec):
        """Write the operator's vhost and SNI entry, then TEST before reloading — a bad config here breaks the
        edge for every site on this host, not just the new operator. On a failed test everything written is
        reverted and nginx is left exactly as it was, which is checked rather than assumed."""
        if self.cfg.edge == "caddy":
            self._apply_operator_caddy(rec)
            return
        result = rec.get("result") or {}
        slug = rec.get("operator") or ""
        vhost, sni = result.get("host_vhost"), result.get("sni_entry")
        if not slug or not vhost:
            rec.setdefault("notes", []).append("edge: the result carried no host_vhost, so nothing was written")
            return
        os.makedirs(self.NGINX_BACKUPS, exist_ok=True)
        site = os.path.join(self.NGINX_SITES, f"cloud-op-{slug}")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        undo = []
        try:
            edge = {}
            try:
                with open(os.path.join(self.job_dir(rec["id"]), "spec.json")) as f:
                    edge = (json.load(f) or {}).get("edge") or {}
            except (OSError, ValueError, KeyError):
                edge = {}
            names, targets = self._check_operator_vhost(vhost, edge, slug)
            rec.setdefault("notes", []).append(
                f"edge: vhost checked against spec.edge — serves {', '.join(names)}, proxies to "
                f"{', '.join(targets) or 'nothing'}")
            # ⚠ a .bak in sites-enabled is LOADED by nginx.conf's include (22 conflicting-server-name warnings,
            # the day that was learned). Backups go to vhost-backups, never beside the live file.
            if os.path.exists(site):
                shutil.copy2(site, os.path.join(self.NGINX_BACKUPS, f"cloud-op-{slug}.{stamp}"))
                undo.append(("restore", site, os.path.join(self.NGINX_BACKUPS, f"cloud-op-{slug}.{stamp}")))
            else:
                undo.append(("remove", site, None))
            with open(os.open(site, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644), "w") as f:
                f.write(vhost if vhost.endswith("\n") else vhost + "\n")

            # §PUSH: the push relay's public door, its own file, checked against spec.edge like the console's
            push_vhost = result.get("push_vhost")
            if push_vhost:
                served = self._check_operator_push(push_vhost, edge, slug)
                psite = os.path.join(self.NGINX_SITES, f"cloud-op-{slug}-push")
                if os.path.exists(psite):
                    shutil.copy2(psite, os.path.join(self.NGINX_BACKUPS, f"cloud-op-{slug}-push.{stamp}"))
                    undo.append(("restore", psite, os.path.join(self.NGINX_BACKUPS, f"cloud-op-{slug}-push.{stamp}")))
                else:
                    undo.append(("remove", psite, None))
                with open(os.open(psite, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644), "w") as f:
                    f.write(push_vhost if push_vhost.endswith("\n") else push_vhost + "\n")
                rec.setdefault("notes", []).append(f"edge: push vhost checked against spec.edge — serves "
                                                   f"{', '.join(served)}, subscribe only")

            if sni:
                with open(self.NGINX_SNI_MAP) as f:
                    lines = f.read().splitlines(keepends=True)
                shutil.copy2(self.NGINX_SNI_MAP, os.path.join(self.NGINX_BACKUPS, f"federation-mtls.conf.{stamp}"))
                undo.append(("restore", self.NGINX_SNI_MAP,
                             os.path.join(self.NGINX_BACKUPS, f"federation-mtls.conf.{stamp}")))
                name = sni.split()[0]
                kept = [l for l in lines if l.strip().split()[:1] != [name]]   # idempotent: replace, never add twice
                at = next((i for i, l in enumerate(kept) if "--- Default:" in l), None)
                if at is None:
                    at = next(i for i, l in enumerate(kept) if l.rstrip() == "}")
                kept.insert(at, f"    {sni.strip()}\n")
                with open(self.NGINX_SNI_MAP, "w") as f:
                    f.write("".join(kept))

            t = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=60)
            if t.returncode != 0:
                raise RuntimeError(f"nginx -t refused the new config: {(t.stderr or '')[-300:]}")
            r = subprocess.run(["nginx", "-s", "reload"], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(f"nginx reload failed: {(r.stderr or '')[-300:]}")
            rec.setdefault("notes", []).append(f"edge: wrote {site}"
                                               + (f" and the SNI entry for {sni.split()[0]}" if sni else "")
                                               + ", nginx tested and reloaded")
        except Exception as exc:  # noqa: BLE001 — revert, then say what happened and that it was reverted
            for kind, path, src in reversed(undo):
                try:
                    if kind == "remove" and os.path.exists(path):
                        os.remove(path)
                    elif kind == "restore" and src and os.path.exists(src):
                        shutil.copy2(src, path)
                except OSError:
                    pass
            after = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=60)
            rec["state"] = "failed"
            rec.setdefault("notes", []).append(
                f"edge REFUSED and was reverted: {exc}. nginx -t after the revert: "
                f"{'clean' if after.returncode == 0 else 'STILL FAILING — look at this host now'}")

    # ── registering an operator with its frame's services (§OPDIST, his answer "Both links first") ────────────
    # An operator is CONNECTED to its frame only when the frame's own services can see it, and each of those needs
    # something written on the FRAME's side after the operator exists: an entry in the frame auditor's venue carrier
    # plus a network path to the operator's registry DB, and (agentvault2-b5's half, not built yet) the operator's
    # SPIFFE ID in the frame directory's readers. Every name below is READ from what names it — the auditor's mount,
    # its own command, the operator's compose labels, the DB's own network — and every outcome is recorded as
    # CONNECTED or NOT CONNECTED with the reason, because "provisioned" and "connected" are different claims.
    AUDITOR_FRAMES_MOUNT = "/app/frames"
    LINKS_TIMEOUT_S = 90
    _AUDITOR_CALL = r"""
import http.client, json, os, socket, sys
path, method, route = sys.argv[1], sys.argv[2], sys.argv[3]
class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, p):
        super().__init__("localhost", timeout=60); self._p = p
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); self.sock.settimeout(60); self.sock.connect(self._p)
headers = {}
if method == "POST":
    # the auditor's OWN token, read inside its own container: it never crosses to the runner
    headers["X-Auditor-Admin"] = os.environ.get("AUDITOR_ADMIN_TOKEN", "")
c = UnixHTTP(path); c.request(method, route, headers=headers); r = c.getresponse(); raw = r.read()
try:
    body = json.loads(raw or b"null")
except ValueError:
    body = {"unparsed": raw[:200].decode("utf-8", "replace")}
print(json.dumps({"status": r.status, "body": body}))
"""

    def _docker_inspect(self, name):
        r = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        try:
            return (json.loads(r.stdout) or [None])[0]
        except ValueError:
            return None

    def _auditor_call(self, container, sock, method, route):
        r = subprocess.run(["docker", "exec", "-i", container, "python3", "-", sock, method, route],
                           input=self._AUDITOR_CALL, capture_output=True, text=True, timeout=self.LINKS_TIMEOUT_S)
        if r.returncode != 0:
            return None, {"error": (r.stderr or "")[-200:]}
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1])
            return out.get("status"), out.get("body")
        except (ValueError, IndexError):
            return None, {"error": "the auditor call printed no answer"}

    def _operator_container(self, stack_dir, service):
        """The operator's container for a compose service, found by the labels compose stamped — never by a name
        spelled here. Exactly one, or None."""
        r = subprocess.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project.working_dir={stack_dir}",
                            "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.Names}}"],
                           capture_output=True, text=True, timeout=30)
        names = [n for n in (r.stdout or "").split() if n] if r.returncode == 0 else []
        return names[0] if len(names) == 1 else None

    def _frame_currency(self, frame_name):
        """The frame's currency as the frame itself publishes it (registry-config local_currency). Empty when it
        cannot be read — never a default, because the auditor keys an FX reserve floor on this."""
        script = ("import json,urllib.request;print(json.load(urllib.request.urlopen("
                  "'http://127.0.0.1:8000/api/v1/public/registry-config',timeout=20)).get('local_currency') or '')")
        r = subprocess.run(["docker", "exec", f"{frame_name}-registry", "python3", "-c", script],
                           capture_output=True, text=True, timeout=40)
        cur = (r.stdout or "").strip().upper() if r.returncode == 0 else ""
        return cur if re.fullmatch(r"[A-Z]{2,8}", cur) else ""

    def _register_operator_with_frame(self, rec):
        links = rec.setdefault("links", {})
        try:
            with open(os.path.join(self.job_dir(rec["id"]), "spec.json")) as f:
                spec = json.load(f) or {}
        except (OSError, ValueError, KeyError):
            spec = {}
        if (spec.get("phase") or "full") not in ("stack", "full"):
            return   # a bundle job leaves no running operator to register
        links["auditor_venue"] = self._link_auditor_venue(rec.get("name") or "", rec.get("operator") or "", spec,
                                                          rec.get("result") or {})
        # ⚠ NO DIRECTORY STEP, deliberately (agentvault2-b5's measurement, verified here 2026-09-16): an operator reads
        # its parent's index through the parent's PUBLIC directory proxy (<console>/api/v1/public/directory, the same
        # lane the frame's own console uses since §MTLSGAP). From inside amsterdam and against lantern: health and graphql
        # 200. So the operator's directory link is two env VALUES the provisioner writes (DIRECTORY_PUBLIC_URL,
        # DISCOVERY_VIA_DIRECTORY), and there is nothing for this runner to admit. A readers-writing step was built,
        # mutation-proven and withdrawn: a mechanism for a case that does not exist. Routing through the operator's
        # nginx-federation instead would make an inbound terminator an egress relay into the private index, checked
        # against the sidecar's identity rather than the caller's (a confused deputy).
        rec.setdefault("notes", []).append(
            "links: " + ", ".join(f"{k} {v.get('state')}" for k, v in links.items() if isinstance(v, dict)))

    def _frame_auditor(self, frame_name):
        """A frame's kit auditor as this runner calls it: ({container, inspect, frames_dir, sock}, None), or
        (None, why). Every name is read from the container itself: its mount and its own command."""
        auditor = f"{frame_name}-auditor"
        a = self._docker_inspect(auditor)
        if not a or not (a.get("State") or {}).get("Running"):
            return None, f"{auditor} is not running"
        frames_dir = next((m.get("Source") for m in a.get("Mounts") or []
                           if m.get("Destination") == self.AUDITOR_FRAMES_MOUNT), None)
        if not frames_dir:
            return None, f"{auditor} mounts nothing at {self.AUDITOR_FRAMES_MOUNT}, so it has no venue carrier"
        cmd = " ".join((a.get("Config") or {}).get("Cmd") or [])
        m = re.search(r"--uds\s+(\S+)", cmd)
        if not m:
            return None, f"{auditor}'s command names no --uds socket, so this runner has nothing to call"
        return {"container": auditor, "inspect": a, "frames_dir": frames_dir, "sock": m.group(1)}, None

    def _operator_db_network(self, stack_dir):
        """(db container, its inspect, its ONE operator network, None) for an operator stack, found by compose labels
        and the DB's own networks, or (None, None, None, why)."""
        db_name = self._operator_container(stack_dir, "db")
        if not db_name:
            return None, None, None, f"no single compose service 'db' is labelled with working dir {stack_dir}"
        db = self._docker_inspect(db_name) or {}
        nets = [n for n in ((db.get("NetworkSettings") or {}).get("Networks") or {}) if n.endswith("operator-net")]
        if len(nets) != 1:
            return None, None, None, f"{db_name} is on {len(nets)} operator networks, not exactly one: {nets}"
        return db_name, db, nets[0], None

    def _operators_decided(self, frame_name):
        """{slug: the job that decides it} per operator on a frame, the NEWEST of:
          · a succeeded operator_teardown (gone);
          · a stack/full operator_provision that SUCCEEDED (built) or FAILED AFTER STARTING WORK (partial): not refused,
            so the one-shot may have extracted a stack and brought containers up (beacon/jelgava 2026-09-16, job
            908a9513d677432c: compose up failed with seven containers running). A partial stack must be tear-down-able,
            or the next provision of the same application meets volumes initialised with the old passwords.
        A refused job did nothing and decides nothing; a failed teardown decides nothing (the operator stays
        tear-down-able); a bundle job builds no running operator."""
        decided = {}
        for rec in self.jobs():   # newest first
            slug, op, state = rec.get("operator"), rec.get("op"), rec.get("state")
            if rec.get("name") != frame_name or not slug or slug in decided:
                continue
            if op == "operator_teardown" and state == "succeeded":
                decided[slug] = rec
            elif (op == "operator_provision" and ((rec.get("request") or {}).get("phase") or "full") in ("stack", "full")
                  and (state == "succeeded" or (state in ("failed", "cancelled", "lost") and not rec.get("refused")))):
                decided[slug] = rec
        return decided

    def _operators_built(self, frame_name):
        """{slug: provision job} for every operator THIS runner built on a frame and has not torn down since."""
        return {s: r for s, r in self._operators_decided(frame_name).items()
                if r.get("op") == "operator_provision" and r.get("state") == "succeeded"}

    # compose's own report, one line per object: ` Container cloud-op-x-registry  Removed` (measured, job 7c609deb)
    _COMPOSE_REMOVED = re.compile(r"^\s*(Container|Volume|Network)\s+(\S+)\s+Removed\s*$")

    def _teardown_removal(self, job_id, sweep=None):
        """What a teardown removed, as the fields the registry's teardown reads (V0391: containers_removed or
        network_removed make its containers_stopped): compose down's own `... Removed` lines, plus what the label sweep
        removed after it. Counted from what was REPORTED removed, never inferred from what is absent afterwards: an
        operator that was never up leaves nothing behind either."""
        seen = {"Container": set(), "Volume": set(), "Network": set()}
        try:
            with open(os.path.join(self.job_dir(job_id), "stdout.log"), errors="replace") as f:
                for line in f.read().replace("\r", "\n").splitlines():
                    m = self._COMPOSE_REMOVED.match(line)
                    if m:
                        seen[m.group(1)].add(m.group(2))
        except OSError:
            pass
        sweep = sweep or {}
        swept = lambda k: int((sweep.get(k) or {}).get("swept") or 0)
        return {"containers_removed": len(seen["Container"]) + swept("containers"),
                "volumes_removed": len(seen["Volume"]) + swept("volumes"),
                "network_removed": bool(seen["Network"]) or swept("networks") > 0}

    # ⚠ WHY A RELINK EXISTS (measured 2026-09-16 on a throwaway compose project): the venue link attaches the frame's
    # auditor with `docker network connect`, which `docker restart` keeps and a compose --force-recreate DROPS. An
    # auditor roll or a frame resume therefore cut every venue link silently.
    def _relink_auditor(self, frame_name):
        """Re-attach a frame's kit auditor to the network of every operator THIS runner built there, have it re-read
        its venues, and record per operator what the auditor then says. The operator set comes from this runner's own
        job records and NEVER from venues.json: that file sits in a directory the frame's auditor mounts, and a name
        read from it could attach this frame's auditor to another frame's operator network. A venue with no runner job
        behind it is named, never attached."""
        ctx, why = self._frame_auditor(frame_name)
        if not ctx:
            return {"state": "NOT RELINKED", "why": why}
        attached = (ctx["inspect"].get("NetworkSettings") or {}).get("Networks") or {}
        built = self._operators_built(frame_name)
        operators = {}
        for slug, prov in sorted(built.items()):
            stack_dir = ((prov.get("result") or {}).get("stack_dir")
                         or os.path.join(self.cfg.stack_root, f"cloud-op-{slug}"))
            db_name, _, net, why = self._operator_db_network(stack_dir)
            if not db_name:
                operators[slug] = {"state": "NOT ATTACHED", "why": why}
            elif net in attached:
                operators[slug] = {"state": "ATTACHED", "network": net, "was": "already attached"}
            else:
                r = subprocess.run(["docker", "network", "connect", net, ctx["container"]],
                                   capture_output=True, text=True, timeout=60)
                operators[slug] = ({"state": "ATTACHED", "network": net, "was": "re-attached"} if r.returncode == 0
                                   else {"state": "NOT ATTACHED", "network": net,
                                         "why": f"docker network connect failed: {(r.stderr or '')[-160:]}"})
        try:
            with open(os.path.join(ctx["frames_dir"], "venues.json")) as f:
                venues = json.load(f)
        except (OSError, ValueError):
            venues = {}
        venues = venues if isinstance(venues, dict) else {}
        st, body = self._auditor_call(ctx["container"], ctx["sock"], "POST", "/api/auditor/admin/reload-venues")
        reloaded = st == 200 and isinstance((body or {}).get("venues"), list)
        st, body = self._auditor_call(ctx["container"], ctx["sock"], "GET", "/api/auditor/venue-shares")
        seen = ((body or {}).get("venues") or {}) if st == 200 else {}
        for slug, o in operators.items():
            v = seen.get(slug) or {}
            o["auditor"] = (self._redact_reason(f"{v.get('reach_status')} {v.get('note') or ''}".strip())[:300]
                            if v else "the auditor holds no venue by this name")
        ok = reloaded and all(o["state"] == "ATTACHED" for o in operators.values())
        return {"state": "RELINKED" if ok else "NOT RELINKED", "auditor": ctx["container"],
                "reload_venues": "applied" if reloaded else "not applied", "operators": operators,
                "venues_with_no_runner_job": sorted(set(venues) - set(built))}

    def op_relink_auditor(self, req, uid):
        """Frame op (full socket): re-attach a frame auditor after something recreated it. See _relink_auditor."""
        name = (req.get("frame") or "").strip()
        if not NAME_RE.fullmatch(name) or not self.frame(name):
            raise Refused(f"frame {name!r} was not built by this runner, so its auditor is not this runner's to relink")
        self._refuse_if_busy()
        out = self._relink_auditor(name)
        self.audit(uid, "relink_auditor", frame=name, state=out.get("state"),
                   operators={k: v.get("state") for k, v in (out.get("operators") or {}).items()})
        return out

    def _unwire_auditor_venue(self, frame_name, slug, stack_dir):
        """The venue link's undo, run BEFORE the operator's compose goes down: compose cannot remove a network that still
        has a foreign endpoint, so the frame auditor leaves the operator network first, then the venue entry goes and
        the auditor re-reads its venues. Refuses, with nothing changed, when the auditor cannot leave the network."""
        out = {"network_disconnected": False, "venue_removed": False, "reload_venues": None}
        ctx, why = self._frame_auditor(frame_name)
        if not ctx:
            out["why"] = why
            return out
        _, _, net, _ = self._operator_db_network(stack_dir)
        net = net or f"cloud-op-{slug}_operator-net"   # the compose project's own network name when the DB is gone
        if net in ((ctx["inspect"].get("NetworkSettings") or {}).get("Networks") or {}):
            r = subprocess.run(["docker", "network", "disconnect", net, ctx["container"]],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise Refused(f"{ctx['container']} could not leave {net} ({(r.stderr or '')[-160:]}); nothing was torn "
                              f"down, because compose cannot remove a network the auditor is still attached to")
            out["network_disconnected"] = True
        path = os.path.join(ctx["frames_dir"], "venues.json")
        try:
            with open(path) as f:
                current = json.load(f)
        except OSError:
            current = {}
        except ValueError:
            out["why"] = f"{path} is unparsable; the venue entry was left in it for a human"
            return out
        if isinstance(current, dict) and slug in current:
            tmp = path + ".tmp"
            with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
                json.dump({k: v for k, v in current.items() if k != slug}, f, indent=2)
                f.write("\n")
            os.replace(tmp, path)
            out["venue_removed"] = True
            st, body = self._auditor_call(ctx["container"], ctx["sock"], "POST", "/api/auditor/admin/reload-venues")
            # an EMPTY list is an answer (this was the auditor's only venue): `or [slug]` read it as "not applied"
            listed = (body or {}).get("venues")
            out["reload_venues"] = ("applied" if st == 200 and isinstance(listed, list) and slug not in listed
                                    else f"not applied ({st})")
        return out

    def _finish_operator_teardown(self, rec):
        """After compose down succeeded: sweep what the project left, then remove this runner's edge files, then the
        stack dir. Each later step runs only when the one before it held, because removing the edge of a stack that
        still runs would cut it off while it keeps its data."""
        slug, stack_dir = rec.get("operator") or "", rec.get("stack_dir") or ""
        notes = rec.setdefault("notes", [])
        sweep = self._sweep_operator_project(slug)
        unwire = rec.get("unwire") or {}
        res = {"phase": "teardown", "operator": slug, "stack_dir": stack_dir, "unwire": unwire, "sweep": sweep,
               "nginx_removed": False, "stack_removed": False, "notes": notes,
               "venue_unwired": bool(unwire.get("venue_removed") or unwire.get("network_disconnected"))}
        res.update(self._teardown_removal(rec["id"], sweep))
        rec["result"] = res
        left = {k: v["left"] for k, v in sweep.items() if isinstance(v, dict) and v.get("left")}
        if left or sweep.get("named_like_it"):
            rec["state"] = "failed"
            notes.append(f"teardown: the stack is NOT gone after compose down and a sweep (left: {left or 'none'}; "
                         f"unlabelled containers named like it: {sweep.get('named_like_it') or 'none'}); the edge and "
                         f"the stack dir were kept")
            return
        swept = ", ".join(f"{k} {v['swept']}" for k, v in sweep.items() if isinstance(v, dict))
        notes.append(f"teardown: compose project cloud-op-{slug} is gone (swept after down: {swept})")
        edge = self._remove_operator_edge(slug, rec.get("sni_name"), frame_name=rec.get("name"))
        res["nginx_removed"] = edge["nginx_removed"]
        notes.append(edge["note"])
        if edge.get("failed"):
            rec["state"] = "failed"
            return
        stack = self._remove_operator_stack(stack_dir, slug)
        res["stack_removed"] = stack["stack_removed"]
        notes.append(stack["note"])
        if stack.get("failed"):
            rec["state"] = "failed"
            return
        scrubbed = self._retire_provision_credentials((rec.get("request") or {}).get("provisioned_by_job"))
        if scrubbed:
            notes.append(f"teardown: the provision's {', '.join(scrubbed)} retired from its job record (the database that "
                         f"held that account is gone)")

    RESULT_CREDENTIAL_KEYS = ("admin_password",)

    def _retire_provision_credentials(self, provision_job_id):
        """After a teardown SUCCEEDED, the provision it undid keeps no credential: the first-boot admin password in its
        result (result.json and the copy in job.json) belonged to a database that no longer exists. Idempotent; returns
        the keys it scrubbed. Only a provision job, only these keys, only a value that is not already the mark."""
        if not (isinstance(provision_job_id, str) and JOB_ID_RE.fullmatch(provision_job_id)):
            return []
        scrubbed = set()
        with self.lock:
            try:
                prov = self.job(provision_job_id)
            except Refused:
                return []
            if prov.get("op") != "operator_provision":
                return []
            res = prov.get("result") if isinstance(prov.get("result"), dict) else None
            if res is not None:
                for k in self.RESULT_CREDENTIAL_KEYS:
                    if res.get(k) not in (None, "", self.SPEC_SCRUB_MARK):
                        res[k] = self.SPEC_SCRUB_MARK
                        scrubbed.add(k)
                if scrubbed:
                    self.save_job(prov)
            path = os.path.join(self.job_dir(provision_job_id), "result.json")
            try:
                with open(path) as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                doc = None
            if isinstance(doc, dict):
                changed = False
                for k in self.RESULT_CREDENTIAL_KEYS:
                    if doc.get(k) not in (None, "", self.SPEC_SCRUB_MARK):
                        doc[k] = self.SPEC_SCRUB_MARK
                        scrubbed.add(k)
                        changed = True
                if changed:
                    tmp = path + ".scrub"
                    with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
                        json.dump(doc, f, indent=2)
                    os.replace(tmp, path)
        return sorted(scrubbed)

    def _complete_teardown_result(self, rec):
        """A succeeded teardown job's result with the removal fields the registry reads. A record written before those
        fields existed (job 7c609debade44018 on beacon) gains them from its OWN output, once, and is saved: this runner
        owns the record, and a result that answers a question differently on every read is not a record."""
        res = rec.get("result") or {}
        if rec.get("state") == "succeeded":
            self._retire_provision_credentials((rec.get("request") or {}).get("provisioned_by_job"))
        if rec.get("state") != "succeeded" or "containers_removed" in res:
            return rec
        with self.lock:
            rec = self.job(rec["id"])
            res = dict(rec.get("result") or {})
            if "containers_removed" not in res:
                res.update(self._teardown_removal(rec["id"], res.get("sweep")))
                res.setdefault("notes", list(rec.get("notes") or []))
                unwire = res.get("unwire") or rec.get("unwire") or {}
                res.setdefault("venue_unwired", bool(unwire.get("venue_removed") or unwire.get("network_disconnected")))
                rec["result"] = res
                rec.setdefault("notes", []).append("teardown: removal counts derived from this job's own compose output "
                                                   "after the fact (the record predates those fields)")
                self.save_job(rec)
        return rec

    def _sweep_operator_project(self, slug):
        """What compose down left of the project, removed by the project LABEL compose stamped, then counted again.
        Containers NAMED like the operator but not labelled by its project are counted and never removed: they are not
        provably this operator's, and they would still collide with a re-provision's container names."""
        project = f"cloud-op-{slug}"
        label = f"label=com.docker.compose.project={project}"
        out = {}
        for kind, ls, rm in (("containers", ["docker", "ps", "-aq", "--filter", label], ["docker", "rm", "-f", "-v"]),
                             ("volumes", ["docker", "volume", "ls", "-q", "--filter", label], ["docker", "volume", "rm", "-f"]),
                             ("networks", ["docker", "network", "ls", "-q", "--filter", label], ["docker", "network", "rm"])):
            r = subprocess.run(ls, capture_output=True, text=True, timeout=60)
            ids = (r.stdout or "").split() if r.returncode == 0 else []
            if ids:
                subprocess.run(rm + ids, capture_output=True, text=True, timeout=180)
            r = subprocess.run(ls, capture_output=True, text=True, timeout=60)
            out[kind] = {"swept": len(ids), "left": len((r.stdout or "").split()) if r.returncode == 0 else -1}
        r = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=60)
        out["named_like_it"] = (sorted(n for n in (r.stdout or "").split() if n.startswith(project + "-"))
                                if r.returncode == 0 else ["(docker ps did not answer)"])
        return out

    def _remove_operator_edge(self, slug, sni_name, frame_name=None):
        """The edge step's undo: the vhost and the SNI line this runner wrote, each backed up to vhost-backups first,
        then nginx -t BEFORE the reload, and a refused test restores both and never reloads. Under the caddy posture
        the undo is the operator's site file and a reload of the frame's own edge (`_remove_operator_caddy`)."""
        if self.cfg.edge == "caddy":
            return self._remove_operator_caddy(slug, frame_name)
        site = os.path.join(self.NGINX_SITES, f"cloud-op-{slug}")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        undo, removed = [], []
        try:
            os.makedirs(self.NGINX_BACKUPS, exist_ok=True)
            for one, tag in ((site, f"cloud-op-{slug}"), (site + "-push", f"cloud-op-{slug}-push")):
                if os.path.exists(one):        # §PUSH: the push vhost goes with the console's
                    bak = os.path.join(self.NGINX_BACKUPS, f"{tag}.{stamp}.torn-down")
                    shutil.copy2(one, bak)
                    undo.append((one, bak))
                    os.remove(one)
                    removed.append(one)
            if sni_name and os.path.exists(self.NGINX_SNI_MAP):
                with open(self.NGINX_SNI_MAP) as f:
                    lines = f.read().splitlines(keepends=True)
                kept = [l for l in lines if l.strip().split()[:1] != [sni_name]]
                if len(kept) != len(lines):
                    bak = os.path.join(self.NGINX_BACKUPS, f"federation-mtls.conf.{stamp}.torn-down")
                    shutil.copy2(self.NGINX_SNI_MAP, bak)
                    undo.append((self.NGINX_SNI_MAP, bak))
                    with open(self.NGINX_SNI_MAP, "w") as f:
                        f.write("".join(kept))
                    removed.append(f"the SNI entry for {sni_name}")
            if not removed:
                return {"nginx_removed": False, "note": "edge: nothing of this operator's was in nginx"}
            t = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=60)
            if t.returncode != 0:
                raise RuntimeError(f"nginx -t refused the config without it: {(t.stderr or '')[-300:]}")
            r = subprocess.run(["nginx", "-s", "reload"], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(f"nginx reload failed: {(r.stderr or '')[-300:]}")
            return {"nginx_removed": True, "note": f"edge: removed {' and '.join(removed)}, nginx tested and reloaded"}
        except Exception as exc:  # noqa: BLE001 — restore, then say what happened and that it was restored
            for path, bak in reversed(undo):
                try:
                    shutil.copy2(bak, path)
                except OSError:
                    pass
            after = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=60)
            return {"nginx_removed": False, "failed": True,
                    "note": f"edge removal REFUSED and was restored: {exc}. nginx -t after the restore: "
                            f"{'clean' if after.returncode == 0 else 'STILL FAILING — look at this host now'}"}

    # ---- the caddy posture (§HELLOFRAME lane 6, 2026-09-18) --------------------------------------------------
    def _caddy(self, container, verb):
        """`caddy validate` or `caddy reload` inside the frame's edge container. Returns (rc, tail); rc None means
        the container is not running (the frame is down), which the callers record as a SKIP rather than a failure:
        the site file stays on disk and that edge's next start reads it."""
        cmd = ["docker", "exec", container, "caddy", verb, "--config", CADDY_CONFIG, "--adapter", CADDY_ADAPTER]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return -1, f"{exc}"[-300:]
        tail = ((p.stdout or "") + (p.stderr or "")).strip()[-300:]
        if p.returncode != 0 and re.search(r"No such container|is not running|not running", tail, re.I):
            return None, tail
        return p.returncode, tail

    def _frame_stack_dir(self, name):
        try:
            rec = self.frame(name) if name else None
        except Exception:  # noqa: BLE001 — an unreadable frame record reads as "no stack dir", the caller says so
            rec = None
        return str((rec or {}).get("stack_dir") or "")

    def _apply_operator_caddy(self, rec):
        """The caddy posture's `_apply_operator_edge`: one site file per operator under the frame's edge directory,
        validated and reloaded through the edge container. The operator is UP when this runs, so a door that could
        not be opened is a NOTE the provisioner surfaces, never a failed job (unlike the nginx path, where a refused
        `nginx -t` would have taken every site on this host down with it). A refused validate reverts the file."""
        slug = rec.get("operator") or ""
        notes = rec.setdefault("notes", [])
        edge = {}
        try:
            with open(os.path.join(self.job_dir(rec["id"]), "spec.json")) as f:
                edge = (json.load(f) or {}).get("edge") or {}
        except (OSError, ValueError, KeyError):
            edge = {}
        domain, reg_port = str(edge.get("domain") or ""), edge.get("reg_port")
        bind = str(edge.get("bind_address") or "127.0.0.1")
        if not slug or not domain or not reg_port:
            notes.append("edge (caddy): the spec carried no edge.domain / edge.reg_port, so no site file was written")
            return
        facts = frame_up_facts(self._frame_stack_dir(rec.get("name")), rec.get("name") or "")
        if not facts["ok"]:
            notes.append(f"edge (caddy): SKIPPED, {facts['why']}")
            return
        try:
            block = caddy_operator_block(domain=domain, bind_address=bind, reg_port=reg_port,
                                         tls_line=caddy_tls_line(facts["tls"], facts["acme_email"]))
            path = caddy_site_path(facts["operators_dir"], slug)
        except ValueError as exc:
            notes.append(f"edge (caddy): REFUSED, {exc}")
            return
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        prior = None
        try:
            os.makedirs(facts["operators_dir"], mode=0o755, exist_ok=True)
            os.chmod(facts["operators_dir"], 0o755)
            if os.path.exists(path):
                prior = f"{path}.{stamp}.bak"          # not *.caddy: the edge's import never reads it
                shutil.copy2(path, prior)
            with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644), "w") as f:
                f.write(block)
            # explicit, because the runner's unit runs under UMask=0027 and the edge container reads this file
            # (it holds a public host name and a gateway address, nothing a mode protects)
            os.chmod(path, 0o644)
        except OSError as exc:
            notes.append(f"edge (caddy): could not write {path}: {exc}")
            return
        container = facts["container"]
        rc, tail = self._caddy(container, "validate")
        if rc is None:
            notes.append(f"edge (caddy): wrote {path}; the edge container {container} is not running, so nothing was "
                         f"reloaded and {domain} opens at that edge's next start")
            rec["edge"] = {"mode": "caddy", "site": domain, "file": path, "reloaded": False}
            return
        if rc != 0:
            try:
                if prior:
                    shutil.copy2(prior, path)
                else:
                    os.remove(path)
            except OSError:
                pass
            notes.append(f"edge (caddy): REFUSED by caddy validate and reverted, so the operator is up without its "
                         f"public door: {tail}")
            return
        rc, tail = self._caddy(container, "reload")
        if rc != 0:
            notes.append(f"edge (caddy): wrote {path} and it validates, but the reload of {container} failed "
                         f"({tail}); {domain} opens at that edge's next reload")
            rec["edge"] = {"mode": "caddy", "site": domain, "file": path, "reloaded": False}
            return
        notes.append(f"edge (caddy): wrote {path}, validated and reloaded {container}; {domain} serves the "
                     f"operator's registry at {bind}:{reg_port}")
        rec["edge"] = {"mode": "caddy", "site": domain, "file": path, "reloaded": True}

    def _remove_operator_caddy(self, slug, frame_name=None):
        """The caddy posture's `_remove_operator_edge`: delete the operator's site file (a copy kept beside it under
        a name the edge never imports) and reload the edge. A missing file or a stopped edge is a note, never a
        failed teardown: the operator's stack is what the teardown is for."""
        result = {"nginx_removed": False, "caddy_removed": False}
        try:
            fname = os.path.basename(caddy_site_path("", slug))
        except ValueError as exc:
            result["note"] = f"edge (caddy): {exc}"
            return result
        candidates = []
        stack_dir = self._frame_stack_dir(frame_name)
        if stack_dir:
            candidates.append((frame_name, stack_dir))
        else:                   # an older record without the frame name: find the file under whichever frame has it
            for p in sorted(glob.glob(os.path.join(self.cfg.stack_root, "*", "frame-up.json"))):
                candidates.append((os.path.basename(os.path.dirname(p)), os.path.dirname(p)))
        for name, sdir in candidates:
            facts = frame_up_facts(sdir, name)
            if not facts["ok"]:
                continue
            path = os.path.join(facts["operators_dir"], fname)
            if not os.path.exists(path):
                continue
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            try:
                shutil.copy2(path, f"{path}.{stamp}.torn-down")
                os.remove(path)
            except OSError as exc:
                result["note"] = f"edge (caddy): could not remove {path}: {exc}"
                return result
            result["caddy_removed"] = True
            container = facts["container"]
            rc, tail = self._caddy(container, "reload")
            if rc is None:
                result["note"] = (f"edge (caddy): removed {path}; the edge container {container} is not running, "
                                  f"nothing to reload")
            elif rc != 0:
                result["note"] = f"edge (caddy): removed {path}, but the reload of {container} failed ({tail})"
            else:
                result["note"] = f"edge (caddy): removed {path} and reloaded {container}"
            return result
        result["note"] = f"edge (caddy): no site file {fname} under any frame's edge directory, nothing to remove"
        return result

    def _remove_operator_stack(self, stack_dir, slug):
        """Delete the operator's stack dir, only when it resolves to <stack root>/cloud-op-<slug> exactly. See
        op_operator_teardown for why it is deleted rather than archived. The file count is recorded, never contents."""
        root = os.path.realpath(self.cfg.stack_root)
        real = os.path.realpath(stack_dir) if stack_dir else ""
        if not real or os.path.dirname(real) != root or os.path.basename(real) != f"cloud-op-{slug}":
            return {"stack_removed": False, "failed": True,
                    "note": f"stack dir {stack_dir!r} is not {root}/cloud-op-{slug}; left in place"}
        if not os.path.isdir(real):
            return {"stack_removed": False, "note": f"stack dir {real} was already absent"}
        files = sum(len(fs) for _, _, fs in os.walk(real))
        try:
            shutil.rmtree(real)
        except OSError as exc:
            return {"stack_removed": False, "failed": True, "note": f"stack dir {real} could not be removed: {exc}"}
        return {"stack_removed": True,
                "note": f"stack dir {real} removed ({files} files: its attestation key and .env.operator are not kept "
                        f"anywhere nothing reads them)"}

    def _link_auditor_venue(self, frame_name, slug, spec, result):
        def no(why):
            return {"connected": False, "state": "NOT CONNECTED", "why": why}
        pw = str((spec.get("operator_secrets") or {}).get("AUDITOR_RO_PASSWORD") or "")
        if not pw:
            # ⚠ NEVER the operator's owner credential: an auditor that can rewrite the register it audits is an
            # integrity flaw (all 13 fleet venues were wired that way). No read-only credential, no venue.
            return no("the spec carried no AUDITOR_RO_PASSWORD, so no read-only credential exists for this "
                      "operator's share register; the owner credential is never used for an audit")
        ctx, why = self._frame_auditor(frame_name)
        if not ctx:
            return no(why)
        auditor, a, frames_dir, sock = ctx["container"], ctx["inspect"], ctx["frames_dir"], ctx["sock"]
        stack_dir = (result.get("stack_dir") or spec.get("cloud_stack_dir")
                     or os.path.join(self.cfg.stack_root, f"cloud-op-{slug}"))
        db_name, db, net, why = self._operator_db_network(stack_dir)
        if not db_name:
            return no(why)
        env = dict(e.split("=", 1) for e in (db.get("Config") or {}).get("Env") or [] if "=" in e)
        dbname = env.get("POSTGRES_DB") or env.get("POSTGRES_USER") or ""   # the postgres image's own default
        if not dbname:
            return no(f"{db_name} names neither POSTGRES_DB nor POSTGRES_USER, so its database is unknown")
        port = next((k.split("/")[0] for k in ((db.get("Config") or {}).get("ExposedPorts") or {}) if k.endswith("/tcp")),
                    "5432")

        # 1. reach: the auditor joins the operator's private network under its own unique name (no alias collision)
        if net not in ((a.get("NetworkSettings") or {}).get("Networks") or {}):
            r = subprocess.run(["docker", "network", "connect", net, auditor], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                return no(f"docker network connect {net} {auditor} failed: {(r.stderr or '')[-160:]}")

        # 2. the entry, beside frames.json in the carrier the auditor already mounts
        venues_path = os.path.join(frames_dir, "venues.json")
        current = {}
        if os.path.exists(venues_path):
            try:
                with open(venues_path) as f:
                    current = json.load(f)
                if not isinstance(current, dict):
                    raise ValueError("not an object")
            except (OSError, ValueError) as exc:
                return no(f"{venues_path} is unparsable ({exc}); it was left untouched")
        mode = "prod"
        try:
            with open(os.path.join(frames_dir, "frames.json")) as f:
                mode = next((x.get("mode") for x in json.load(f) if x.get("id") == frame_name), None) or "prod"
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        from urllib.parse import quote
        entry = {"dsn": f"postgresql://auditor_ro:{quote(pw, safe='')}@{db_name}:{port}/{dbname}",
                 "currency": self._frame_currency(frame_name), "frame": frame_name, "mode": mode}
        if current.get(slug) != entry:
            tmp = venues_path + ".tmp"
            with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
                json.dump({**current, slug: entry}, f, indent=2)
                f.write("\n")
            os.replace(tmp, venues_path)

        # 3. the auditor applies it, and says it did
        st, body = self._auditor_call(auditor, sock, "POST", "/api/auditor/admin/reload-venues")
        if st != 200 or slug not in ((body or {}).get("venues") or []):
            return no(f"reload-venues answered {st}: {str((body or {}).get('error') or body)[:160].replace(pw, '<redacted>')}")

        # 4. reach, as the auditor itself sees it — the only answer that makes this CONNECTED. "reachable" alone is not
        # enough: after a failed read the auditor serves an EARLIER reading as "stale" with reachable true, and a retry on
        # the same application keeps the same DSN, so an old reading could vouch for a database this entry cannot read.
        st, body = self._auditor_call(auditor, sock, "GET", "/api/auditor/venue-shares")
        v = ((body or {}).get("venues") or {}).get(slug) or {}
        if st == 200 and v.get("reachable") and v.get("reach_status") == "ok":
            return {"connected": True, "state": "CONNECTED", "venue": slug, "network": net, "db": db_name,
                    "currency": entry["currency"] or "(unread)", "listings": len(v.get("listings") or [])}
        seen = "cannot reach it" if not v.get("reachable") else "reached it, but its latest read is not ok"
        return no(f"the auditor took the entry but {seen}: {v.get('reach_status') or st} "
                  f"{str(v.get('note') or '')[:240].replace(pw, '<redacted>')}")

    def _apply_operator_redis_acl(self, rec):
        """A SAFETY NET for the one file the one-shot (uid 1000) cannot own by itself: the operator's Redis reads its ACL
        as uid 999. agentvault2-b5 measured that the change CANNOT wait for the job: an unreadable ACL makes Redis
        crash-loop, its healthcheck never passes, and `compose up -d` waits on `service_healthy` until the job fails.
        So the one-shot makes the change itself, mid-job, as ONE explicit root operation (a throwaway `alpine:3 -u 0`
        over the socket it already holds; AgentVault ddd69afe) and reports it in the result. A healthy provision
        therefore reports redis_acl_chown_needed FALSE, and this step does nothing; TRUE means the in-job change failed,
        and this runner, which is root, makes it and says so. It would have caught this class an hour earlier.

        Guarded so that a result can never become a root chown somewhere else: the path must resolve, symlinks followed,
        to a REGULAR file inside THIS operator's own stack dir; the uid must be an int in 1..65534; only the owner moves,
        and the group the one-shot gave the file is kept. A refusal fails the job: without it the Redis never starts."""
        result = rec.get("result") or {}
        if not result.get("redis_acl_chown_needed"):
            return
        slug = rec.get("operator") or ""
        root = os.path.realpath(self.cfg.stack_root)
        stack_dir = os.path.realpath(result.get("stack_dir") or os.path.join(root, f"cloud-op-{slug}"))
        path = os.path.realpath(str(result.get("redis_acl_path") or ""))
        uid = result.get("redis_acl_uid")

        def refuse(why):
            rec["state"] = "failed"
            rec.setdefault("notes", []).append(f"redis acl REFUSED: {why}; the operator's Redis cannot read its ACL")

        if not slug or not stack_dir.startswith(root + os.sep) or os.path.basename(stack_dir) != f"cloud-op-{slug}":
            return refuse(f"the operator stack dir {stack_dir!r} is not cloud-op-{slug} under {root}")
        if not path.startswith(stack_dir + os.sep):
            return refuse(f"{path!r} is not inside {stack_dir}")
        if not os.path.isfile(path):
            return refuse(f"{path!r} is not a regular file")
        if isinstance(uid, bool) or not isinstance(uid, int) or not 1 <= uid <= 65534:
            return refuse(f"redis_acl_uid {uid!r} is not a uid")
        try:
            os.chown(path, uid, -1)
        except OSError as exc:
            return refuse(f"chown failed: {exc}")
        rec.setdefault("notes", []).append(f"redis acl: the one-shot reported its own change FAILED; this runner set "
                                           f"{os.path.relpath(path, root)} owner -> {uid} (group kept)")

    def op_operator_teardown(self, req, uid):
        """The HOST half of tearing down an operator this runner built (§OPDIST 2026-09-16). The registry keeps its
        database half (peer INACTIVE, licence revoked, cloud_torn_down_at) and must write it only after this job
        SUCCEEDS: measured on beacon, the in-registry teardown's docker-SDK and nsenter steps both fail on a frame with
        no docker socket, and the route then marks the operator torn down anyway while it keeps running.

        Runner-native, no one-shot: every host thing an operator has was made by compose (from the stack's own files)
        or written by THIS runner (the edge, the venue entry, the auditor's network attachment), so this runner undoes
        exactly those. Nothing is taken from the caller but the operator's name: the stack dir and the SNI entry come
        from the provision record this runner holds, and an operator it has no such record of is refused.

        ⚠ THE STACK DIR IS DELETED, NOT ARCHIVED (the registry's non-purge path archives it). Measured in jelgava's: it
        holds spire/agent-attestation.key, which a non-purge teardown keeps LIVE (the SPIRE entries stay so the same
        application can be provisioned again), plus .env.operator and a .docker config. An archive keeps live
        credentials where nothing reads them; the frame's bundle tar keeps what a re-provision needs.
        ⚠ purge is REFUSED here: its SPIRE revocation, genesis drain and cross-frame row deletes have not been reviewed
        for this route."""
        frame = self._operator_frame(req, uid)
        spec = req.get("spec")
        if not isinstance(spec, dict):
            raise Refused("spec: one JSON object naming the operator (safe_name or operator_name)")
        slug = spec.get("safe_name") or spec.get("operator_name") or ""
        if not isinstance(slug, str) or not NAME_RE.fullmatch(slug):
            raise Refused(f"spec.safe_name {slug!r} is not an operator name")
        if spec.get("purge"):
            raise Refused("spec.purge: purge is not built on the runner route (its SPIRE revocation, genesis drain and "
                          "cross-frame row deletes are registry steps not yet reviewed for it); tear down without purge")
        # IDEMPOTENT: a teardown whose host half already SUCCEEDED answers with that job instead of refusing. The registry
        # writes its database half after this answer, so a route retried after its own failure (beacon, 2026-09-16: the
        # host half succeeded, the registry stamped nothing on a result missing containers_removed) must reach the same
        # succeeded job again; a refusal there would leave the host gone and the database saying live, for good.
        decisive = self._operators_decided(frame["name"]).get(slug)
        if decisive and decisive.get("op") == "operator_teardown":
            # the result is read through operator_status, which completes an older record there
            self.audit(uid, "operator_teardown", frame=frame["name"], operator=slug, job_id=decisive["id"],
                       already_torn_down=True)
            return {"started": False, "already_torn_down": True, "job_id": decisive["id"],
                    "job": {k: decisive.get(k) for k in ("id", "op", "name", "state", "created", "ended")}}
        problems = self.load_gate()   # not the memory and disk floors: a teardown only gives those back
        if problems:
            raise Refused("; ".join(problems))
        self._refuse_if_busy_for(frame["name"])
        prov = decisive
        if not prov:
            raise Refused(f"this runner holds no stack provision of {slug!r} on {frame['name']} (succeeded, or failed "
                          f"after starting work) that a later teardown has not undone, so there is nothing of this "
                          f"runner's to tear down")
        partial = prov.get("state") != "succeeded"
        root = os.path.realpath(self.cfg.stack_root)
        recorded = (prov.get("result") or {}).get("stack_dir") or os.path.join(root, f"cloud-op-{slug}")
        stack_dir = os.path.realpath(recorded)
        if os.path.dirname(stack_dir) != root or os.path.basename(stack_dir) != f"cloud-op-{slug}":
            raise Refused(f"the provision recorded stack dir {recorded}, which is not {root}/cloud-op-{slug}; refused "
                          f"rather than tearing down whatever it resolves to")
        compose = os.path.join(stack_dir, "docker-compose.operator.yml")
        env_file = os.path.join(stack_dir, ".env.operator")
        missing = [p for p in (compose, env_file) if not os.path.isfile(p)]
        if missing:
            raise Refused(f"{', '.join(missing)} missing, so compose cannot take the stack down; nothing was changed")
        sni = str((prov.get("result") or {}).get("sni_entry") or "").split()
        # FIRST, and able to refuse with nothing changed: compose cannot remove a network with a foreign endpoint
        unwire = self._unwire_auditor_venue(frame["name"], slug, stack_dir)
        job_id = uuid.uuid4().hex[:16]
        # THE SAME FILE SET THE `up` READ: an override the one-shot copied into the stack (V0391's db-TLS file) declares
        # its own services and volumes, and a `down -v` over the base alone left its data-certs volume for the sweep to
        # find (jelgava's partial stack, job 473b20a4d7b446fa). The one-shot copies an override in only when it applies it.
        overrides = sorted(glob.glob(os.path.join(stack_dir, "docker-compose.operator.*.yml")))
        argv = (["docker", "compose", "-p", f"cloud-op-{slug}", "-f", compose]
                + [arg for path in overrides for arg in ("-f", path)]
                + ["--env-file", env_file, "down", "-v", "--remove-orphans"])
        rec = self.launch("operator_teardown", uid, frame["name"], argv,
                          request={"frame": frame["name"], "operator": slug, "phase": "teardown",
                                   "application_id": spec.get("application_id"), "provisioned_by_job": prov["id"],
                                   "partial": partial},
                          progress=False, job_id=job_id, needle=f"cloud-op-{slug}",
                          extra={"operator": slug, "stack_dir": stack_dir, "unwire": unwire,
                                 "sni_name": sni[0] if sni else None})
        self.audit(uid, "operator_teardown", frame=frame["name"], operator=slug, job_id=job_id,
                   provisioned_by_job=prov["id"], partial=partial)
        return {"started": True, "job_id": job_id,
                "job": self.public_job(rec) if hasattr(self, "public_job") else
                {k: rec[k] for k in ("id", "op", "name", "state", "created") if k in rec}}

    # ── §F6 WP6.1: the identity ops (IDENTITY_OPS, served on the operator socket only) ────────────────────────────
    # Each acts on the CALLER's own frame: the compose project of the container the calling pid runs in, and that
    # project's one SPIRE server. Never a runner frame record (none of EU, ASIA or the sandbox pair was built by this
    # runner, §F6 WP6.0) and never a name the request carries: a `frame` field that names another frame is refused.
    # Root (the host itself, and this runner's tests) may name a compose `project` instead.

    def _identity_ctx(self, req, uid):
        pid = req.get("_peer_pid")
        cid = container_of_pid(pid) if pid is not None else None
        if cid:
            project = self._project_of_container(cid)
            if not project:
                raise Refused("the calling container's compose project could not be read, so it has no frame to act for")
        elif uid == 0:
            project = str(req.get("project") or "").strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,80}", project):
                raise Refused("project: the host names the compose project of the frame it acts for")
        else:
            raise Refused("the caller runs in no container this runner can name, so it has no frame to act for")
        frame = frame_of_project(project)
        if not frame:
            raise Refused(f"the caller's compose project {project!r} is not a frame")
        claimed = str(req.get("frame") or "").strip()
        if claimed and claimed != frame:
            raise Refused(f"frame {claimed!r} is not the calling frame ({frame}): a frame asks this runner only for itself")
        spire, own = self._frame_spire(project)
        return {"frame": frame, "project": project, "spire": spire, "trust_domain": own}

    @staticmethod
    def _project_of_container(cid):
        r = subprocess.run(["docker", "inspect", cid, "--format", '{{index .Config.Labels "com.docker.compose.project"}}'],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""

    def _frame_spire(self, project):
        """The ONE SPIRE server of a compose project and its trust domain, read from the server.conf it mounts. Cached
        per container id, so a recreated server is read again."""
        r = subprocess.run(["docker", "ps", "--filter", f"label=com.docker.compose.project={project}",
                            "--format", "{{.ID}} {{.Names}}"], capture_output=True, text=True, timeout=30)
        rows = [line.split(" ", 1) for line in r.stdout.splitlines() if " " in line]
        spires = [(i, n) for i, n in rows if n.endswith("spire-server")]
        if r.returncode != 0 or len(spires) != 1:
            raise Refused(f"compose project {project!r} runs {len(spires)} SPIRE server(s), not one")
        cid, name = spires[0]
        cache = self.__dict__.setdefault("_spire_td_cache", {})
        if cid in cache:
            return name, cache[cid]
        info = self._docker_inspect(name) or {}
        conf = next((m.get("Source") for m in (info.get("Mounts") or [])
                     if m.get("Destination") == "/opt/spire/conf/server.conf" and m.get("Source")), None)
        try:
            text = open(conf, encoding="utf-8").read() if conf else ""
        except OSError:
            text = ""
        m = re.search(r'^\s*trust_domain\s*=\s*"([^"]+)"', text, re.M)
        if not m:
            raise Refused(f"{name}'s trust domain could not be read from its server.conf")
        own = spec_trust_domain(m.group(1))
        cache[cid] = own
        return name, own

    def _spire_exec(self, spire, argv, stdin=None, timeout=30):
        """spire-server <argv> inside the frame's own SPIRE server: an argument list, never a shell; bounded output."""
        cmd = ["docker", "exec"] + (["-i"] if stdin is not None else []) + [spire, SPIRE_BIN] + list(argv)
        try:
            if stdin is None:
                r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
            else:
                r = subprocess.run(cmd, input=stdin.encode("utf-8"), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"rc": 124, "stdout": "", "stderr": f"spire-server {' '.join(argv[:2])} timed out after {timeout}s"}
        return {"rc": r.returncode, "stdout": r.stdout[:MAX_SPIRE_OUTPUT].decode("utf-8", "replace"),
                "stderr": r.stderr[:4096].decode("utf-8", "replace")}

    def _identity_result(self, uid, op, ctx, res, **fields):
        # the audit names what was asked and how it ended; never a bundle body, a certificate or a key
        self.audit(uid, op, frame=ctx["frame"], project=ctx["project"], rc=res["rc"], **fields)
        return {"frame": ctx["frame"], "trust_domain": ctx["trust_domain"], **res}

    def _live_nodes(self, ctx):
        res = self._spire_exec(ctx["spire"], ["agent", "list"])
        if res["rc"] != 0:
            raise Refused(f"agent list failed on {ctx['spire']}: {res['stderr'].strip()[:160]}")
        return set(re.findall(r"SPIFFE ID\s*:\s*(spiffe://\S+)", res["stdout"]))

    def _one_entry(self, ctx, entry_id, kinds):
        res = self._spire_exec(ctx["spire"], ["entry", "show", "-entryID", entry_id])
        found = [e for e in parse_spire_entries(res["stdout"]) if e.get("entry_id") == entry_id] if res["rc"] == 0 else []
        if len(found) != 1:
            raise Refused(f"entry_id: {entry_id} is not one entry of this frame's SPIRE server")
        spec_spiffe_id(found[0]["spiffe_id"], ctx["trust_domain"], kinds)
        return found[0]

    def op_spire_bundle_show(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        fmt = req.get("format") or "pem"
        if fmt not in BUNDLE_FORMATS:
            raise Refused(f"format: {str(fmt)[:20]!r} is not {' or '.join(BUNDLE_FORMATS)}")
        res = self._spire_exec(ctx["spire"], ["bundle", "show", "-format", fmt])
        return self._identity_result(uid, "spire_bundle_show", ctx, res, format=fmt)

    def op_spire_bundle_list(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        argv, peer = ["bundle", "list"], None
        if req.get("trust_domain"):
            peer = spec_peer_trust_domain(req["trust_domain"], ctx["trust_domain"])
            argv += ["-id", f"spiffe://{peer}"]
        if req.get("format"):
            if req["format"] not in BUNDLE_FORMATS:
                raise Refused(f"format: {str(req['format'])[:20]!r} is not {' or '.join(BUNDLE_FORMATS)}")
            argv += ["-format", req["format"]]
        res = self._spire_exec(ctx["spire"], argv)
        return self._identity_result(uid, "spire_bundle_list", ctx, res, peer=peer)

    def op_spire_bundle_set(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        peer = spec_peer_trust_domain(req.get("trust_domain"), ctx["trust_domain"])
        fmt = req.get("format") or "pem"
        body = spec_bundle(req.get("bundle"), fmt)
        res = self._spire_exec(ctx["spire"], ["bundle", "set", "-id", f"spiffe://{peer}", "-format", fmt], stdin=body)
        return self._identity_result(uid, "spire_bundle_set", ctx, res, peer=peer, format=fmt, bundle_bytes=len(body))

    def op_spire_bundle_delete(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        peer = spec_peer_trust_domain(req.get("trust_domain"), ctx["trust_domain"])
        mode = req.get("mode") or "dissociate"
        if mode not in BUNDLE_DELETE_MODES:
            raise Refused(f"mode: {str(mode)[:20]!r} is not {', '.join(BUNDLE_DELETE_MODES)}")
        res = self._spire_exec(ctx["spire"], ["bundle", "delete", "-mode", mode, "-id", f"spiffe://{peer}"])
        return self._identity_result(uid, "spire_bundle_delete", ctx, res, peer=peer, mode=mode)

    def op_spire_federation_list(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        return self._identity_result(uid, "spire_federation_list", ctx, self._spire_exec(ctx["spire"], ["federation", "list"]))

    def _federation(self, action, req, uid):
        ctx = self._identity_ctx(req, uid)
        peer = spec_peer_trust_domain(req.get("trust_domain"), ctx["trust_domain"])
        url = spec_bundle_url(req.get("bundle_endpoint_url"))
        profile = req.get("profile") or "https_spiffe"
        if profile not in FEDERATION_PROFILES:
            raise Refused(f"profile: {str(profile)[:20]!r} is not {' or '.join(FEDERATION_PROFILES)}")
        endpoint = spec_endpoint_spiffe_id(req.get("endpoint_spiffe_id") or f"spiffe://{peer}/spire/server", peer)
        res = self._spire_exec(ctx["spire"], ["federation", action, "-trustDomain", peer, "-bundleEndpointURL", url,
                                              "-bundleEndpointProfile", profile, "-endpointSpiffeID", endpoint])
        return self._identity_result(uid, f"spire_federation_{action}", ctx, res, peer=peer, url=url, profile=profile)

    def op_spire_federation_create(self, req, uid):
        return self._federation("create", req, uid)

    def op_spire_federation_update(self, req, uid):
        return self._federation("update", req, uid)

    def op_spire_entry_show(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        argv = ["entry", "show"]
        if req.get("entry_id"):
            argv += ["-entryID", spec_entry_id(req["entry_id"])]
        if req.get("spiffe_id"):
            argv += ["-spiffeID", spec_spiffe_id(req["spiffe_id"], ctx["trust_domain"])]
        if req.get("parent_id"):
            argv += ["-parentID", spec_node_id(req["parent_id"], ctx["trust_domain"])]
        return self._identity_result(uid, "spire_entry_show", ctx, self._spire_exec(ctx["spire"], argv),
                                     filters=[a for a in argv[2::2]])

    def op_spire_entry_create(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        own = ctx["trust_domain"]
        sid = spec_spiffe_id(req.get("spiffe_id"), own)
        kind = sid[len("spiffe://"):].split("/")[1]
        parent = spec_node_id(req.get("parent_id"), own)
        selectors = spec_selectors(req.get("selectors"), kind)
        dns = spec_dns_names(req.get("dns"))
        ttl = spec_ttl(req.get("ttl", 1800))
        federates = spec_federates(req.get("federates_with"), own)
        if parent not in self._live_nodes(ctx):
            raise Refused(f"parent_id: {parent} is not a live node of this frame's SPIRE server")
        argv = ["entry", "create", "-parentID", parent, "-spiffeID", sid]
        for sel in selectors:
            argv += ["-selector", sel]
        argv += ["-x509SVIDTTL", str(ttl)]
        for d in dns:
            argv += ["-dns", d]
        for td in federates:
            argv += ["-federatesWith", f"spiffe://{td}"]
        res = self._spire_exec(ctx["spire"], argv)
        return self._identity_result(uid, "spire_entry_create", ctx, res, spiffe_id=sid, ttl=ttl, dns=len(dns),
                                     federates=federates)

    def op_spire_entry_update_federates(self, req, uid):
        """ADD trust domains to one service or operator entry's FederatesWith. `entry update` is a full replace, so the
        entry is read first and every selector, DNS name and TTL it holds is passed back as it was."""
        ctx = self._identity_ctx(req, uid)
        own = ctx["trust_domain"]
        eid = spec_entry_id(req.get("entry_id"))
        add = spec_federates(req.get("add"), own)
        if not add:
            raise Refused("add: at least one trust domain to federate with")
        e = self._one_entry(ctx, eid, ("service", "operator"))
        have = list(e.get("federates_with") or [])
        want = have + [td for td in add if td not in have]
        if want == have:
            return self._identity_result(uid, "spire_entry_update_federates", ctx,
                                         {"rc": 0, "stdout": "", "stderr": "", "already": True}, entry_id=eid, add=add)
        argv = ["entry", "update", "-entryID", eid, "-spiffeID", e["spiffe_id"], "-parentID", e.get("parent_id", "")]
        for sel in e.get("selectors") or []:
            argv += ["-selector", sel]
        if e.get("ttl"):
            argv += ["-x509SVIDTTL", str(e["ttl"])]
        for d in e.get("dns") or []:
            argv += ["-dns", d]
        for td in want:
            argv += ["-federatesWith", f"spiffe://{td}"]
        res = self._spire_exec(ctx["spire"], argv)
        return self._identity_result(uid, "spire_entry_update_federates", ctx, {**res, "already": False},
                                     entry_id=eid, add=add)

    def op_spire_entry_delete(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        eid = spec_entry_id(req.get("entry_id"))
        e = self._one_entry(ctx, eid, IDENTITY_KINDS)
        res = self._spire_exec(ctx["spire"], ["entry", "delete", "-entryID", eid])
        return self._identity_result(uid, "spire_entry_delete", ctx, res, entry_id=eid, spiffe_id=e["spiffe_id"])

    def op_spire_entry_count(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        return self._identity_result(uid, "spire_entry_count", ctx, self._spire_exec(ctx["spire"], ["entry", "count"]))

    def op_spire_x509_mint(self, req, uid):
        """An X509-SVID for an AGENT of this frame (IRONHAND's external enrollment). The answer carries the private key
        to the caller alone: it is never written to the audit."""
        ctx = self._identity_ctx(req, uid)
        sid = spec_spiffe_id(req.get("spiffe_id"), ctx["trust_domain"], ("agent",))
        ttl = spec_ttl(req.get("ttl"))
        dns = spec_dns_names(req.get("dns"))
        argv = ["x509", "mint", "-spiffeID", sid, "-ttl", f"{ttl}s", "-output", "json"]
        for d in dns:
            argv += ["-dns", d]
        res = self._spire_exec(ctx["spire"], argv)
        return self._identity_result(uid, "spire_x509_mint", ctx, res, spiffe_id=sid, ttl=ttl, dns=len(dns))

    def op_spire_agent_list(self, req, uid):
        ctx = self._identity_ctx(req, uid)
        return self._identity_result(uid, "spire_agent_list", ctx, self._spire_exec(ctx["spire"], ["agent", "list"]))

    def _agent_action(self, action, req, uid):
        ctx = self._identity_ctx(req, uid)
        node = spec_node_id(req.get("spiffe_id"), ctx["trust_domain"])
        if node not in self._live_nodes(ctx):
            raise Refused(f"spiffe_id: {node} is not a live node of this frame's SPIRE server")
        res = self._spire_exec(ctx["spire"], ["agent", action, "-spiffeID", node])
        return self._identity_result(uid, f"spire_agent_{action}", ctx, res, node=node)

    def op_spire_agent_ban(self, req, uid):
        return self._agent_action("ban", req, uid)

    def op_spire_agent_evict(self, req, uid):
        return self._agent_action("evict", req, uid)

    def op_spire_federation_delete(self, req, uid):
        """§F6 WP6.2: a frame's revoke ends the SPIRE federation RELATIONSHIP with the peer, not only the peer's bundle.
        While the relationship stands, the server's bundle refresher keeps fetching the revoked peer's bundle from the
        endpoint it names, so a bundle the revoke dissociated can come back (the WP6.1 proof's named find). A relationship
        already gone answers SPIRE's own "not found", which the registry reads as done."""
        ctx = self._identity_ctx(req, uid)
        peer = spec_peer_trust_domain(req.get("trust_domain"), ctx["trust_domain"])
        res = self._spire_exec(ctx["spire"], ["federation", "delete", "-id", f"spiffe://{peer}"])
        return self._identity_result(uid, "spire_federation_delete", ctx, res, peer=peer)

    # ── §F6 WP6.2: the lifecycle of the calling frame's cloud operators ───────────────────────────────────────────
    # The registry restarted an operator's services and read its logs through a docker:cli sidecar it ran with the host
    # Docker socket (cloud_provisioner.restart_cloud_service / fetch_cloud_logs). Here the same two compose verbs run on
    # the operator's own stack, with the service and the tail from closed sets and the operator bound to the CALLER.
    OPERATOR_COMPOSE_FILE_RE = re.compile(r"docker-compose\.operator(?:\.[a-z0-9-]{1,40})?\.yml")
    OPERATOR_RESTART_TIMEOUT_S = 300
    OPERATOR_LOGS_TIMEOUT_S = 60

    def _caller_operator(self, ctx, value, for_write=True):
        """ONE cloud operator of the calling frame, read from the operator's own registry container rather than from
        anything the request says: compose project cloud-op-<name>, a working dir directly under the stack root with
        that name, the compose files `up` read (the stack's own docker-compose.operator.yml and its overrides) and its
        .env.operator, and the CALLING frame's trust domain in its SPIRE_TRUST_DOMAIN (an operator shares its parent's:
        measured on all 12 operator stacks of this host, 2026-09-26). Nothing is read from its env but those two names,
        and neither value is ever returned or audited."""
        name = spec_operator_name(value)
        project = f"cloud-op-{name}"
        r = subprocess.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}",
                            "--filter", "label=com.docker.compose.service=registry", "--format", "{{.ID}}"],
                           capture_output=True, text=True, timeout=30)
        ids = r.stdout.split() if r.returncode == 0 else []
        if len(ids) != 1:
            raise Refused(f"operator: {name!r} has {len(ids)} registry container(s) on this host, not one")
        info = self._docker_inspect(ids[0]) or {}
        config = info.get("Config") or {}
        labels = config.get("Labels") or {}
        root = os.path.realpath(self.cfg.stack_root)
        wd = labels.get("com.docker.compose.project.working_dir") or ""
        if not wd or os.path.realpath(wd) != os.path.join(root, project) or not os.path.isdir(wd):
            raise Refused(f"operator {name!r}: its compose working dir is not {root}/{project}")
        files = [p for p in (labels.get("com.docker.compose.project.config_files") or "").split(",") if p]
        if (not files or os.path.basename(files[0]) != "docker-compose.operator.yml"
                or any(os.path.dirname(p) != wd or not self.OPERATOR_COMPOSE_FILE_RE.fullmatch(os.path.basename(p))
                       or not os.path.isfile(p) for p in files)):
            raise Refused(f"operator {name!r}: the compose files its stack was brought up with are not its own "
                          f"docker-compose.operator.yml (and overrides) in {wd}")
        env_file = labels.get("com.docker.compose.project.environment_file") or os.path.join(wd, ".env.operator")
        if env_file != os.path.join(wd, ".env.operator") or not os.path.isfile(env_file):
            raise Refused(f"operator {name!r}: its stack's env file is not {wd}/.env.operator")
        declared = {}
        for item in config.get("Env") or []:
            key, _, val = item.partition("=")
            if key in ("SPIRE_TRUST_DOMAIN", "REGISTRY_SAFE_NAME"):
                declared[key] = val
        if declared.get("SPIRE_TRUST_DOMAIN") != ctx["trust_domain"]:
            raise Refused(f"operator {name!r} is not an operator of the calling frame {ctx['frame']}: "
                          f"a frame acts only on its own operators")
        if declared.get("REGISTRY_SAFE_NAME") not in (None, "", name):
            raise Refused(f"operator {name!r}: its registry names itself differently, so the stack is not that operator's")
        for job in (self.running_jobs() if for_write else []):
            if job.get("operator") == name:
                raise Refused(f"job {job['id']} ({job['op']} {name}) is running on this operator's stack; try again after it")
        return {"operator": name, "project": project, "stack_dir": wd, "files": files, "env_file": env_file,
                "registry_container": ids[0]}

    def _operator_compose(self, op, verb_args, timeout):
        argv = (["docker", "compose", "-p", op["project"]]
                + [arg for path in op["files"] for arg in ("-f", path)]
                + ["--env-file", op["env_file"]] + list(verb_args))
        env = dict(os.environ)
        docker_config = os.path.join(op["stack_dir"], ".docker")
        if os.path.isdir(docker_config):
            env["DOCKER_CONFIG"] = docker_config   # the stack's own registry login, as the sidecar used it
        t0 = time.time()
        try:
            r = subprocess.run(argv, cwd=op["stack_dir"], env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=timeout)
            rc, out = r.returncode, (r.stdout or b"") + (r.stderr or b"")
        except subprocess.TimeoutExpired as exc:
            rc, out = 124, (exc.stdout or b"") + (exc.stderr or b"") + f"\ncompose timed out after {timeout}s".encode()
        return rc, out, int((time.time() - t0) * 1000)

    def op_operator_restart(self, req, uid):
        """`docker compose restart [service]` on one of the calling frame's operators. The answer carries the tail of
        compose's own output; the audit carries the operator, the service, the exit code and the duration."""
        ctx = self._identity_ctx(req, uid)
        op = self._caller_operator(ctx, req.get("operator"))
        service = spec_operator_service(req.get("service"))
        rc, out, ms = self._operator_compose(op, ["restart"] + ([] if service == "all" else [service]),
                                             self.OPERATOR_RESTART_TIMEOUT_S)
        self.audit(uid, "operator_restart", frame=ctx["frame"], operator=op["operator"], service=service, rc=rc,
                   duration_ms=ms)
        return {"frame": ctx["frame"], "operator": op["operator"], "service": service, "rc": rc,
                "restarted": rc == 0, "output_tail": out[-400:].decode("utf-8", "replace"), "duration_ms": ms}

    def op_operator_logs(self, req, uid):
        """`docker compose logs --no-color --tail=N [service]` of one of the calling frame's operators, the last
        MAX_LOG_BYTES of it. The audit names the operator, the service, the tail and the size, never a line."""
        ctx = self._identity_ctx(req, uid)
        op = self._caller_operator(ctx, req.get("operator"))
        service = spec_operator_service(req.get("service"))
        tail = spec_log_tail(req.get("tail"))
        rc, out, ms = self._operator_compose(op, ["logs", "--no-color", f"--tail={tail}"]
                                             + ([] if service == "all" else [service]), self.OPERATOR_LOGS_TIMEOUT_S)
        truncated = len(out) > MAX_LOG_BYTES
        out = out[-MAX_LOG_BYTES:]
        self.audit(uid, "operator_logs", frame=ctx["frame"], operator=op["operator"], service=service, tail=tail, rc=rc,
                   bytes=len(out), truncated=truncated, duration_ms=ms)
        return {"frame": ctx["frame"], "operator": op["operator"], "service": service, "tail": tail, "rc": rc,
                "output": out.decode("utf-8", "replace"), "truncated": truncated, "duration_ms": ms}

    # ── slice 2: the SPIRE half of a revoke, the host half of a purge ─────────────────────────────────────────────
    def op_operator_revoke_spire(self, req, uid):
        """The SPIRE half of revoking or purging one of the calling frame's operators, on the frame's own SPIRE server.
        With the operator node's x509pop fingerprint: ban the node and delete every entry it parents. The node is NOT
        evicted: measured 2026-09-27 on sbx-beta (wp62opb), an evict after the ban erased the ban and the operator's agent
        re-attested within 30 s (x509pop, "Can re-attest: true"), so today's ban-delete-evict order revoked nothing at the
        node. A banned node stays listed as banned; that record is the revocation. Always: delete every entry under
        spiffe://<frame>/operator/<op>/ (the purge's sweep, cloud_provisioner._delete_op_spire_entries). The node may also
        parent IRONHAND agent entries (spiffe://<frame>/agent/<did>, registered with the operator's node as parent), which
        are the operator's and are deleted with it (agentvault2-a1's review: refusing them left an operator unrevokable).
        A node that parents ANY other entry is refused with nothing changed, so this op can ban neither the frame's own
        node (it parents /service/ entries) nor another operator's. The operator's containers are not required: a revoked
        operator may be gone already or run elsewhere; the binding is the caller's own SPIRE server and the operator's
        SPIFFE path."""
        ctx = self._identity_ctx(req, uid)
        name = spec_operator_name(req.get("operator"))
        raw_fp = req.get("fingerprint")
        fp = None if raw_fp in (None, "") else spec_fingerprint(raw_fp)
        # §OPPROV (2026-09-27): the caller may withhold the path sweep. A frame can hold two applications under one name
        # (names were never unique, and activation now refuses a second live one); revoking the one that never activated
        # must not sweep the path the live one's entries sit under. Without the sweep only the node's own children go.
        sweep_path = req.get("sweep_path", True)
        if not isinstance(sweep_path, bool):
            raise Refused("sweep_path is true or false")
        if not sweep_path and not fp:
            raise Refused("neither a node nor the path to revoke: nothing would be changed")
        prefix = f"spiffe://{ctx['trust_domain']}/operator/{name}/"
        node = f"spiffe://{ctx['trust_domain']}/spire/agent/x509pop/{fp}" if fp else None
        listing = self._spire_exec(ctx["spire"], ["entry", "show"])
        if listing["rc"] != 0:
            raise Refused(f"entry show failed on {ctx['spire']}: {listing['stderr'].strip()[:160]}; nothing was changed")
        entries = parse_spire_entries(listing["stdout"])
        agent_prefix = f"spiffe://{ctx['trust_domain']}/agent/"
        children = [e for e in entries if node and e.get("parent_id") == node]
        foreign = [e for e in children if not e["spiffe_id"].startswith((prefix, agent_prefix))]
        if foreign:
            raise Refused(f"node {node} parents {len(foreign)} identities outside {prefix} and {agent_prefix}: it is not "
                          f"operator {name}'s alone, so nothing was changed")
        agents = [e for e in children if e["spiffe_id"].startswith(agent_prefix)]
        # An agent entry is the operator's only on a node that is provably the operator's: one that also parents the
        # operator's own entries. Measured 2026-09-27 02:09Z: without this, a probe naming no real operator and the
        # fingerprint of a node that parented only a stale /agent/ entry deleted that entry on sbx-beta.
        if agents and not any(e["spiffe_id"].startswith(prefix) for e in children):
            raise Refused(f"node {node} parents {len(agents)} agent identities and none of operator {name}'s own, so they "
                          f"cannot be attributed to {name}; nothing was changed")
        targets = sorted({e["entry_id"] for e in (entries if sweep_path else children) if e["spiffe_id"].startswith(prefix)}
                         | {e["entry_id"] for e in agents})
        out = {"frame": ctx["frame"], "operator": name, "node": node, "node_listed": None, "banned": False,
               "entries_found": len(targets), "agent_entries": len(agents), "entries_deleted": 0, "evicted": False,
               "sweep_path": sweep_path, "errors": []}
        if node:
            out["node_listed"] = node in self._live_nodes(ctx)
            if out["node_listed"]:
                r = self._spire_exec(ctx["spire"], ["agent", "ban", "-spiffeID", node])
                out["banned"] = r["rc"] == 0
                if r["rc"] != 0:
                    out["errors"].append(f"agent ban rc={r['rc']}: {r['stderr'].strip()[:160]}")
        for eid in targets:
            r = self._spire_exec(ctx["spire"], ["entry", "delete", "-entryID", eid])
            if r["rc"] == 0:
                out["entries_deleted"] += 1
            else:
                out["errors"].append(f"entry delete {eid} rc={r['rc']}: {r['stderr'].strip()[:160]}")
        # no evict: it would erase the ban (see the docstring); `evicted` stays in the answer, always False, so a reader
        # of an older audit row and a newer one compares like with like
        self.audit(uid, "operator_revoke_spire", frame=ctx["frame"], project=ctx["project"], operator=name, node=node,
                   node_listed=out["node_listed"], banned=out["banned"], entries_found=out["entries_found"],
                   agent_entries=out["agent_entries"], entries_deleted=out["entries_deleted"], evicted=out["evicted"],
                   sweep_path=sweep_path, errors=len(out["errors"]))
        return out

    OPERATOR_PURGE_TIMEOUT_S = 300
    OPERATOR_DRAIN_TIMEOUT_S = 60
    # Measured 2026-09-27 on sbx-beta (the throwaway wp62opb, and sbxbetaop as the control): since §SECFIX an operator's
    # TEG answers its own admin key 403 "mTLS identity required", so a read with the key saw no treasury and every real
    # purge was refused (fail-closed, but nothing could be purged). The drain now runs where the operator's registry talks
    # to its TEG: in the operator's REGISTRY container, with the app's own SVID context (es_ssl_helper.get_httpx_verify),
    # through its nginx-teg sidecar (TEG_API_BASE_URL). One marked line comes back: the status and the balance, or the
    # status and the send's result. The body is built here from checked values; no key is read or sent.
    DRAIN_MARK = "DRAIN-JSON "
    _DRAIN_PY_READ = (
        "import os,json,httpx\n"
        "from agentvault_registry.es_ssl_helper import get_httpx_verify\n"
        "b=(os.environ.get('TEG_API_BASE_URL') or os.environ.get('TEG_LAYER_URL') or '').rstrip('/')\n"
        "r=httpx.get(b+'/api/v1/admin/treasury/info',verify=get_httpx_verify(),timeout=10)\n"
        "d=r.json() if 'json' in r.headers.get('content-type','') else {}\n"
        "print('DRAIN-JSON '+json.dumps({'status':r.status_code,'treasury_balance':str(d.get('treasury_balance',''))}))\n")
    # §OPPROV (2026-09-27): the parent's address is the one the operator's own registry dials it at, from its
    # MAINFRAME_PUBLIC_URL through the app's _teg_dial_url (V0457's rule for the operator -> parent hop), sent as the
    # fund-send's target_url, which the TEG prefers over its PARTNER_TEGS (resolve_partner_url's url_hint). Where the
    # app has no _teg_dial_url, the same rule by hand: the host, its port or 8443. The receiver accepts only a source in
    # its own trust domain, so an address that names anything else is refused there and the TEG re-credits (502).
    DRAIN_PARENT_LABEL = "teg-parent"
    _DRAIN_PY_SEND = (
        "import os,sys,json,httpx\n"
        "from urllib.parse import urlparse\n"
        "from agentvault_registry.es_ssl_helper import get_httpx_verify\n"
        "b=(os.environ.get('TEG_API_BASE_URL') or os.environ.get('TEG_LAYER_URL') or '').rstrip('/')\n"
        "body=json.load(sys.stdin)\n"
        "m=(os.environ.get('MAINFRAME_PUBLIC_URL') or '').strip()\n"
        "if m and not body.get('target_url'):\n"
        "    try:\n"
        "        from agentvault_registry.routers.teg_integration import _teg_dial_url\n"
        "        body['target_url']=_teg_dial_url(m)\n"
        "    except Exception:\n"
        "        u=urlparse(m)\n"
        "        body['target_url']=('https://%s:%s'%(u.hostname,u.port or 8443)) if u.hostname else ''\n"
        "r=httpx.post(b+'/api/v1/admin/treasury/cross-teg-fund-send',json=body,verify=get_httpx_verify(),timeout=30)\n"
        "d=r.json() if 'json' in r.headers.get('content-type','') else {}\n"
        "print('DRAIN-JSON '+json.dumps({'status':r.status_code,'result':str(d.get('status',''))[:40],"
        "'target_host':urlparse(body.get('target_url') or '').hostname}))\n")

    def _operator_incarnation(self, op):
        """A marker for THIS provisioning of the operator: its registry container's creation instant, hashed. The parent
        TEG treats a repeated correlation id as a replay and credits nothing while the sender still debits (agentvault2-
        a1's review), so a name purged, provisioned again and purged again must not reuse the first drain's id."""
        created = str((self._docker_inspect(op["registry_container"]) or {}).get("Created") or "")
        return hashlib.sha256(f"{op['operator']}|{created}".encode()).hexdigest()[:12]

    def _registry_python(self, container, code, stdin=None):
        """{parsed marked line} from `code` run by the app's python in the operator's registry container ({} on no answer)."""
        r = subprocess.run(["docker", "exec", "-i", "-w", "/app", "-e", "PYTHONPATH=/app/src", container,
                            "python", "-c", code], input=stdin, capture_output=True, text=True,
                           timeout=self.OPERATOR_DRAIN_TIMEOUT_S)
        line = next((ln[len(self.DRAIN_MARK):] for ln in reversed((r.stdout or "").splitlines())
                     if ln.startswith(self.DRAIN_MARK)), "")
        try:
            answer = json.loads(line) if r.returncode == 0 and line else {}
        except ValueError:
            answer = {}
        return answer if isinstance(answer, dict) else {}

    def _operator_vhost_names(self, slug):
        """The host names the operator's own vhost serves (its server_name lines): the only SNI lines a purge removes."""
        try:
            text = open(os.path.join(self.NGINX_SITES, f"cloud-op-{slug}")).read()
        except OSError:
            return []
        names = []
        for m in re.finditer(r"(?m)^\s*server_name\s+([^;]+);", text):
            for n in m.group(1).split():
                if DNS_NAME_RE.fullmatch(n) and n not in names:
                    names.append(n)
        return names

    def _operator_teg(self, slug):
        """(container, the ONE partner TEG id its PARTNER_TEGS names, None, 1) or (container or None, None, why, n), n the
        number of TEG containers the operator's project holds (-1: docker could not list them). Only the partner ids are
        read out of that variable, never a URL or a key."""
        r = subprocess.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project=cloud-op-{slug}",
                            "--filter", "label=com.docker.compose.service=teg-layer", "--format", "{{.Names}}"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None, None, "the operator's TEG containers could not be listed", -1
        names = r.stdout.split()
        if len(names) != 1:
            return None, None, f"the operator runs {len(names)} TEG container(s), not one", len(names)
        info = self._docker_inspect(names[0]) or {}
        raw = next((e.partition("=")[2] for e in ((info.get("Config") or {}).get("Env") or [])
                    if e.startswith("PARTNER_TEGS=")), "")
        try:
            doc = json.loads(raw) if raw else {}
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            ids = list(doc.keys())
        elif isinstance(doc, list):
            ids = [str(x.get("teg_id") or x.get("id") or "") for x in doc if isinstance(x, dict)]
        else:
            return names[0], None, "the operator TEG's PARTNER_TEGS is not a JSON object or list", 1
        ids = [i for i in ids if TEG_ID_RE.fullmatch(i or "")]
        # §OPPROV (2026-09-27): a partner id is only the drain's LABEL now; the address comes from the operator's own
        # registry (_DRAIN_PY_SEND). Measured on sbx-beta: every socket-route operator since §REDERIVE (09-12) ships
        # PARTNER_TEGS=[] and the older ones name teg-layer-test with an EMPTY url, so a funded operator's purge was
        # refused at "0 partner TEG(s)" (opprova) or, older, would have debited and then failed its send. No partner
        # is a label of its own; two are still ambiguous and refused.
        if not ids:
            return names[0], self.DRAIN_PARENT_LABEL, None, 1
        if len(ids) != 1:
            return names[0], None, f"the operator TEG names {len(ids)} partner TEG(s); the drain target is not unique", 1
        return names[0], ids[0], None, 1

    def _operator_ledger_volumes(self, slug):
        """The operator's TEG ledger volume(s) still on the host (compose volume 'teg-data', where its treasury lives), or
        None when docker could not list them."""
        r = subprocess.run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project=cloud-op-{slug}",
                            "--filter", "label=com.docker.compose.volume=teg-data"], capture_output=True, text=True, timeout=30)
        return r.stdout.split() if r.returncode == 0 else None

    DRAIN_RECORD = ".teardown-drain.json"
    DRAIN_DUST = Decimal("0.000001")
    DRAIN_ID_RE = re.compile(r"td-[a-z0-9-]{1,12}-[0-9a-f]{8}-[0-9]{1,4}")
    DRAIN_ID_MAX = 36   # teg_transactions.transaction_id is VARCHAR(36) on both sides of the send

    @classmethod
    def drain_id(cls, slug, incarnation, n):
        """The n-th drain of this incarnation of the operator, in at most 29 characters. Measured 2026-09-27 on opprova:
        the TEG stores the correlation id in teg_transactions.transaction_id, VARCHAR(36), and refused (400, "Local
        treasury debit commit failed", nothing debited) the 37-character teardown-drain-opprova-<12 hex>-1; the slice-2
        form teardown-drain-<op>-<12 hex> already overflowed for any operator name of nine characters or more."""
        return f"td-{slug[:12]}-{incarnation[:8]}-{n}"

    @staticmethod
    def _drain_outcome(answer):
        """What a fund-send answer means for the treasury (the TEG's own contract, endpoints_treasury.py):
        completed = the peer took it; reversed = the peer refused and the TEG re-credited the treasury (502); refused =
        the TEG refused before debiting (any other 4xx); uncertain = 503, a timeout or no answer at all, where the debit
        may stand as a PENDING row whose delivery nobody has confirmed."""
        status = answer.get("status")
        result = str(answer.get("result") or "").lower()
        if status in (200, 201) and result in ("completed", "success", "sent", "ok", "settled"):
            return "completed"
        if status == 502:
            return "reversed"
        if isinstance(status, int) and 400 <= status < 500:
            return "refused"
        return "uncertain"

    def _drain_record(self, op):
        """(path, record, None) of the drains a purge has SENT for this operator; (None, None, why) when there is no stack
        dir to keep one in; (path, None, why) when one exists and cannot be read. Kept in the operator's stack dir, so it lives exactly as long as the ledger it describes and is
        removed with it; the socket half of the purge (cloud_provisioner) reads and writes the same file. A record that
        exists and cannot be read is a refusal: it may be the only memory of a drain whose delivery was never confirmed."""
        d = op.get("stack_dir") or ""
        if not d or not os.path.isdir(d) or os.path.islink(d):
            return None, None, "the operator has no stack dir to keep its drain record in"
        path = os.path.join(d, self.DRAIN_RECORD)
        if not os.path.lexists(path):
            return path, {"drains": []}, None
        doc = read_json(path) if os.path.isfile(path) and not os.path.islink(path) else None
        if not isinstance(doc, dict) or not isinstance(doc.get("drains"), list):
            return path, None, (f"its drain record {path} cannot be read, and it may hold a drain whose delivery was "
                                f"never confirmed")
        return path, doc, None

    def _send_drain(self, op, correlation_id, amount, target):
        body = json.dumps({"amount": amount, "target_teg_id": target, "correlation_id": correlation_id,
                           "reason": "teardown_genesis_drain"})
        answer = self._registry_python(op["registry_container"], self._DRAIN_PY_SEND, stdin=body)
        return self._drain_outcome(answer), answer

    def _drain_operator_treasury(self, op):
        """Today's genesis drain (cloud_provisioner._drain_op_genesis), read and sent through the operator's own registry
        (its SVID, its TEG sidecar), to the one partner the operator's TEG knows (its parent). The old target was a Frame
        A-era id (teg-layer-a) no sandbox operator's TEG knows, so every purge there stranded the treasury. Returns
        {"ok": bool, ...}: ok False means the treasury holds value that did not move, and the purge must not go on.

        ⚠ A RETRY NEVER TRUSTS A ZERO (agentvault2-a1's review item 3, 2026-09-27). A send the peer did not confirm (503,
        a timeout) leaves the operator's TEG holding a PENDING row with the treasury already debited; the next purge read
        the treasury as empty, called it drained and destroyed that row with the ledger. Every send is now written to the
        operator's drain record BEFORE it goes out, each unconfirmed one is re-sent with its own correlation id and amount
        before the balance is read at all, and the purge stops while any stays unconfirmed. A completed drain's id is never
        reused either: the TEG answers a repeated id with the prior success and sends nothing, so a remainder that arrived
        after a first drain was reported drained and destroyed. Ids are td-<op[:12]>-<incarnation[:8]>-<n> (drain_id)."""
        slug = op["operator"]
        teg, partner, why, count = self._operator_teg(slug)
        if teg is None:
            # No TEG to read is "nothing to drain" only for an operator that holds no TEG ledger at all. Two TEG
            # containers, a listing that failed, or a TEG container gone while its ledger volume remains is a treasury
            # nobody can read, and `down -v` would destroy it undrained.
            ledger = self._operator_ledger_volumes(slug) if count == 0 else None
            if count == 0 and ledger == []:
                return {"ok": True, "drained": False, "note": f"nothing to drain: {why}, and no TEG ledger volume"}
            return {"ok": False, "drained": False,
                    "note": f"{why}{' while its TEG ledger volume remains' if ledger else ''}, so the treasury cannot be "
                            f"read and a purge would strand whatever it holds; start its TEG (or drain it by hand) first"}
        path, record, rec_why = self._drain_record(op)
        if path is not None and record is None:
            return {"ok": False, "drained": False, "note": rec_why}

        def save():
            write_json(path, record, mode=0o644)   # amounts, ids and a TEG id: nothing secret, readable by the frame

        completed_now = []
        for d in (record or {}).get("drains", []):
            if not isinstance(d, dict) or d.get("state") not in ("sending", "uncertain"):
                continue
            cid, amt, tgt = str(d.get("correlation_id") or ""), str(d.get("amount") or ""), str(d.get("target") or "")
            if (not self.DRAIN_ID_RE.fullmatch(cid) or len(cid) > self.DRAIN_ID_MAX
                    or not cid.startswith(f"td-{slug[:12]}-{self._operator_incarnation(op)[:8]}-")
                    or not AMOUNT_RE.fullmatch(amt) or tgt != (partner or "")):
                return {"ok": False, "drained": False, "amount": amt[:40], "correlation_id": cid[:100],
                        "note": f"an unconfirmed drain in {path} does not read as one this purge sent to "
                                f"{partner or 'the operator TEG partner'}, so it was not re-sent"}
            outcome, answer = self._send_drain(op, cid, amt, tgt)
            d.update(state=("uncertain" if outcome == "refused" else outcome), answered=answer.get("status"),
                     result=str(answer.get("result") or "")[:40] or None, at=now())
            try:
                save()
            except OSError as exc:
                return {"ok": False, "drained": False, "amount": amt, "correlation_id": cid,
                        "note": f"the drain record {path} could not be written ({type(exc).__name__}) after re-sending "
                                f"a drain; nothing was removed"}
            if d["state"] == "uncertain":
                return {"ok": False, "drained": False, "amount": amt, "target": tgt, "correlation_id": cid,
                        "status": d.get("result"),
                        "note": f"a drain of {amt} sent earlier (correlation id {cid}) is still unconfirmed: its "
                                f"re-delivery answered {answer.get('status') or 'nothing'}, and the operator's TEG may hold "
                                f"it pending, which a purge would destroy"}
            if d["state"] == "completed":
                completed_now.append(d)
        read = self._registry_python(op["registry_container"], self._DRAIN_PY_READ)
        dec = treasury_amount(read.get("treasury_balance")) if read.get("status") == 200 else None
        if dec is None:
            return {"ok": False, "drained": False, "note": f"the operator treasury could not be read (its TEG answered "
                                                          f"{read.get('status') or 'nothing'}), so a purge would strand "
                                                          f"whatever it holds"}
        bal = format(dec, "f")
        if dec <= self.DRAIN_DUST:
            out = {"ok": True, "drained": bool(completed_now), "amount": bal,
                   "note": "the operator treasury holds nothing to drain"}
            if completed_now:
                out["resumed"] = [d["correlation_id"] for d in completed_now]
            return out
        if partner is None:
            return {"ok": False, "drained": False, "amount": bal, "note": why}
        if not AMOUNT_RE.fullmatch(bal):
            return {"ok": False, "drained": False, "amount": bal[:40],
                    "note": "the treasury balance is not a shape the drain sends; nothing was sent"}
        if path is None:
            return {"ok": False, "drained": False, "amount": bal,
                    "note": f"{rec_why}, so a drain that stalled could not be resumed by a retry; nothing was sent"}
        cid = self.drain_id(slug, self._operator_incarnation(op), len(record["drains"]) + 1)
        d = {"correlation_id": cid, "amount": bal, "target": partner, "state": "sending", "at": now()}
        record["drains"].append(d)
        try:
            save()   # BEFORE the send: a purge that dies mid-send leaves "sending", which the next one re-sends first
        except OSError as exc:
            return {"ok": False, "drained": False, "amount": bal,
                    "note": f"the drain record {path} could not be written ({type(exc).__name__}); nothing was sent"}
        outcome, answer = self._send_drain(op, cid, bal, partner)
        d.update(state=outcome, answered=answer.get("status"), result=str(answer.get("result") or "")[:40] or None,
                 at=now())
        try:
            save()
        except OSError:
            pass   # the record still says "sending", so the next purge re-sends it first (a completed id is answered as done)
        ok = outcome == "completed"
        if ok:
            # §OPPROV (2026-09-27): "completed" is the TEG's word, and the TEG answers a correlation id it already
            # completed with that prior success while moving nothing (its idempotency). A drain whose record was lost
            # could reuse an id at the same amount and be told "completed" with the value still there, which the purge
            # would destroy. The drain is done only when the treasury READS empty after it; a remainder waits for a retry.
            after = self._registry_python(op["registry_container"], self._DRAIN_PY_READ)
            dec_after = treasury_amount(after.get("treasury_balance")) if after.get("status") == 200 else None
            if dec_after is None or dec_after > self.DRAIN_DUST:
                seen = "could not be re-read" if dec_after is None else f"still reads {format(dec_after, 'f')}"
                return {"ok": False, "drained": False, "amount": bal, "target": partner, "correlation_id": cid,
                        "outcome": outcome, "after": None if dec_after is None else format(dec_after, "f"),
                        "note": f"the drain {cid} was answered completed, but the operator treasury {seen}, so nothing "
                                f"was removed; a retried purge drains what remains"}
        return {"ok": ok, "drained": ok, "amount": bal, "target": partner, "status": d.get("result"),
                "correlation_id": cid, "outcome": outcome,
                "note": None if ok else {"reversed": "the parent refused the drain and the operator's TEG re-credited "
                                                     "its treasury, so it still holds the value",
                                         "refused": "the operator's TEG refused the drain before debiting anything",
                                         }.get(outcome, "the drain was not confirmed, so the operator's TEG may hold it "
                                                        "pending; a retried purge re-sends it first")}

    def _operator_host_traces(self, slug):
        """What of cloud-op-<slug> this host still holds: containers, volumes and networks by its compose project label,
        its stack dir, archived copies and vhost. A listing docker could not answer counts as a trace (it may hold one)."""
        project = f"cloud-op-{slug}"

        def listed(argv):
            r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            return r.stdout.split() if r.returncode == 0 else ["<listing failed>"]
        root = os.path.realpath(self.cfg.stack_root)
        rx = re.compile(re.escape(f"{project}-archived-") + r"\d{8}-\d{4}")
        return {
            "containers": listed(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}",
                                  "--format", "{{.ID}}"]),
            "volumes": listed(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"]),
            "networks": listed(["docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"]),
            "stack_dir": os.path.lexists(os.path.join(root, project)),
            "archives": [d for d in os.listdir(root) if rx.fullmatch(d)],
            "vhost": os.path.lexists(os.path.join(self.NGINX_SITES, project)),
        }

    def _remove_operator_archives(self, slug):
        """The archived copies a non-purge teardown left (<root>/cloud-op-<op>-archived-YYYYMMDD-HHMM), removed by a purge."""
        root = os.path.realpath(self.cfg.stack_root)
        rx = re.compile(re.escape(f"cloud-op-{slug}-archived-") + r"\d{8}-\d{4}")
        removed = []
        for d in sorted(os.listdir(root)):
            path = os.path.join(root, d)
            if rx.fullmatch(d) and os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
                removed.append(d)
        return removed

    def op_operator_purge(self, req, uid):
        """The host half of a PURGE teardown of one of the calling frame's operators, in the order the registry ran it:
        the genesis drain first (refused, with nothing removed, if the treasury holds value that did not move), then the
        compose project down with its volumes and a sweep by its project label, the edge (the vhost and the SNI lines of
        the names that vhost serves, nginx -t before the reload), the stack dir and its archived copies. The operator's
        SPIRE entries are operator_revoke_spire's, and its database rows each frame's own API's."""
        ctx = self._identity_ctx(req, uid)
        wanted = spec_operator_name(req.get("operator"))
        traces = self._operator_host_traces(wanted)
        if not any(traces.values()):
            # An operator whose provision failed before its stack came up (measured on sbx-beta 2026-09-26: activation's
            # bundle could not be packed, so nothing was ever written to the host) has no container to bind it to a frame
            # by, and refusing left it unpurgeable through the runner while its SPIRE entries and rows waited for the
            # purge. A purge of nothing removes nothing whoever asks, so it answers, and the purge's other halves go on.
            self.audit(uid, "operator_purge", frame=ctx["frame"], operator=wanted, nothing_on_host=True)
            return {"frame": ctx["frame"], "operator": wanted, "nothing_on_host": True,
                    "drain": {"ok": True, "drained": False, "note": "no stack of this operator on the host"},
                    "compose_rc": None, "sweep": {"containers": {"left": 0}}, "edge": [], "edge_names": [],
                    "stack": {"stack_removed": False}, "archives_removed": [], "duration_ms": 0}
        op = self._caller_operator(ctx, wanted)
        slug = op["operator"]
        names = self._operator_vhost_names(slug)
        drain = self._drain_operator_treasury(op)
        if not drain.get("ok"):
            self.audit(uid, "operator_purge", frame=ctx["frame"], operator=slug, refused="drain", drained=False)
            raise Refused(f"operator {slug}: {drain.get('note')}; nothing was removed")
        rc, out, ms = self._operator_compose(op, ["down", "-v", "--remove-orphans"], self.OPERATOR_PURGE_TIMEOUT_S)
        sweep = self._sweep_operator_project(slug)
        edge = [self._remove_operator_edge(slug, n, ctx["frame"]) for n in (names or [None])]
        stack = self._remove_operator_stack(op["stack_dir"], slug)
        archives = self._remove_operator_archives(slug)
        result = {"frame": ctx["frame"], "operator": slug, "drain": drain, "compose_rc": rc,
                  "compose_tail": out[-400:].decode("utf-8", "replace"), "sweep": sweep, "edge": edge, "edge_names": names,
                  "stack": stack, "archives_removed": archives, "duration_ms": ms}
        self.audit(uid, "operator_purge", frame=ctx["frame"], operator=slug, drained=bool(drain.get("drained")),
                   compose_rc=rc, containers_left=(sweep.get("containers") or {}).get("left"),
                   edge_removed=any(e.get("nginx_removed") for e in edge), stack_removed=bool(stack.get("stack_removed")),
                   archives_removed=len(archives), duration_ms=ms)
        return result

    # ── slice 2: read-only observation of what the caller owns ────────────────────────────────────────────────────
    DOCKER_SOCK = "/var/run/docker.sock"

    def _observed_project(self, ctx, req):
        """The caller's own compose project, or (with `operator`) one of its operators', bound like the lifecycle ops."""
        if req.get("operator") in (None, ""):
            return ctx["project"], None
        op = self._caller_operator(ctx, req.get("operator"), for_write=False)
        return op["project"], op["operator"]

    def _project_containers(self, project):
        fmt = "{{.ID}}\t{{.Names}}\t{{.Label \"com.docker.compose.service\"}}\t{{.State}}\t{{.Status}}\t{{.Image}}"
        r = subprocess.run(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={project}", "--format", fmt],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise Refused(f"docker ps did not answer for {project}")
        rows = []
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 6:
                rows.append(dict(zip(("id", "name", "service", "state", "status", "image"), parts)))
        rows.sort(key=lambda x: x["name"])
        return rows[:MAX_CENSUS_CONTAINERS], len(rows) > MAX_CENSUS_CONTAINERS

    def op_containers_census(self, req, uid):
        """The containers of the caller's own compose project (or one of its operators'): name, compose service, state,
        status and image. Nothing of any other project, and nothing from inside a container."""
        ctx = self._identity_ctx(req, uid)
        project, operator = self._observed_project(ctx, req)
        rows, truncated = self._project_containers(project)
        self.audit(uid, "containers_census", frame=ctx["frame"], project=project, operator=operator, count=len(rows))
        return {"frame": ctx["frame"], "project": project, "operator": operator, "containers": rows, "count": len(rows),
                "truncated": truncated}

    @classmethod
    def _docker_api_json(cls, route, timeout=30):
        """GET one Docker Engine API route over the host socket (stdlib only); the parsed JSON."""
        import http.client

        class _Unix(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(timeout)
                self.sock.connect(cls.DOCKER_SOCK)

        c = _Unix("localhost", timeout=timeout)
        try:
            c.request("GET", route)
            r = c.getresponse()
            raw = r.read()
            if r.status != 200:
                raise RuntimeError(f"{route} answered {r.status}")
            return json.loads(raw or b"null")
        finally:
            c.close()

    @staticmethod
    def _pruned_stats(doc):
        """The fields the registry's stats view computes from (cloud and websocket twins read the same keys)."""
        def cpu(block):
            b = block or {}
            u = b.get("cpu_usage") or {}
            return {"cpu_usage": {"total_usage": u.get("total_usage", 0), "percpu_usage": list(u.get("percpu_usage") or [])},
                    "system_cpu_usage": b.get("system_cpu_usage", 0), "online_cpus": b.get("online_cpus")}
        mem = doc.get("memory_stats") or {}
        blk = (doc.get("blkio_stats") or {}).get("io_service_bytes_recursive") or []
        return {"cpu_stats": cpu(doc.get("cpu_stats")), "precpu_stats": cpu(doc.get("precpu_stats")),
                "memory_stats": {"usage": mem.get("usage", 0), "limit": mem.get("limit", 1)},
                "networks": {k: {"rx_bytes": v.get("rx_bytes", 0), "tx_bytes": v.get("tx_bytes", 0)}
                             for k, v in (doc.get("networks") or {}).items()},
                "blkio_stats": {"io_service_bytes_recursive": [{"op": x.get("op"), "value": x.get("value", 0)}
                                                               for x in blk if isinstance(x, dict)]}}

    def op_container_stats(self, req, uid):
        """One stats sample (the Engine API's stream=false: two readings a second apart) for each RUNNING container of
        the caller's own compose project, or of one of its operators', pruned to the fields the stats views compute from."""
        ctx = self._identity_ctx(req, uid)
        project, operator = self._observed_project(ctx, req)
        rows, truncated = self._project_containers(project)
        running = [x for x in rows if x["state"] == "running"]
        from concurrent.futures import ThreadPoolExecutor

        def one(row):
            try:
                return dict(row, stats=self._pruned_stats(self._docker_api_json(f"/containers/{row['id']}/stats?stream=false")))
            except Exception as exc:  # noqa: BLE001 — one container's failure is reported, the rest still answer
                return dict(row, stats=None, error=f"{type(exc).__name__}: {str(exc)[:120]}")

        with ThreadPoolExecutor(max_workers=max(1, min(16, len(running)))) as pool:
            out = list(pool.map(one, running))
        self.audit(uid, "container_stats", frame=ctx["frame"], project=project, operator=operator, count=len(out),
                   errors=sum(1 for x in out if x.get("error")))
        return {"frame": ctx["frame"], "project": project, "operator": operator, "containers": out, "count": len(out),
                "truncated": truncated}

    def op_plan(self, req, uid, spec=None):
        spec = spec or self.validate_spec(req.get("spec"), uid=uid)
        argv = self.driver_argv(spec) + ["--plan"]
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=self.cfg.plan_timeout,
                               env=self.driver_env(mail=not spec.get("nightly")), cwd=os.path.dirname(self.cfg.driver))
        except subprocess.TimeoutExpired:
            raise Refused(f"the plan did not answer within {self.cfg.plan_timeout} s")
        try:
            doc = json.loads(p.stdout)
        except ValueError:
            doc = None
        self.audit(uid, "plan", name=spec["name"], exit_code=p.returncode)
        result = {"exit_code": p.returncode, "plan_ok": p.returncode == 0 and bool(doc) and doc.get("ok") is True,
                  "plan": doc}
        if doc is None:
            result["stderr_tail"] = (p.stderr or "")[-2000:]
        elif self.cfg.dns:
            self._plan_dns(spec["name"], doc)
            result["plan_ok"] = result["plan_ok"] and doc.get("ok") is True
        return result

    def op_standup(self, req, uid):
        spec = self.validate_spec(req.get("spec"), uid=uid)
        with self.lock:
            self._refuse_if_busy()
            gates = self.host_gates()
            if gates:
                raise Refused("host gates: " + "; ".join(gates))
            planned = self.op_plan(req, uid, spec=spec)
            if not planned["plan_ok"]:
                self.audit(uid, "standup", name=spec["name"], result="refused by its plan")
                return {"started": False, **planned}
            rec = self._launch_driver("standup", uid, spec["name"], self.driver_argv(spec), request=spec,
                                      manage_dns=bool(self.cfg.dns), mail=not spec.get("nightly"))
        self.audit(uid, "standup", name=spec["name"], job_id=rec["id"])
        return {"started": True, "job": self.summary(rec), "plan": planned["plan"]}

    def resume_shape_refusal(self, frame):
        """The sentence refusing a resume of `frame`, or None. The check is template_shape.py beside the driver this
        runner launches (one rule for the runner and a hand-run resume); a check that cannot load refuses, never passes."""
        name = frame["name"]
        path = os.path.join(os.path.dirname(os.path.abspath(self.cfg.driver)), "template_shape.py")
        try:
            spec = importlib.util.spec_from_file_location("frame_template_shape", path)
            shape = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(shape)
        except Exception as exc:
            return (f"{name} cannot be resumed: the template shape check beside the driver cannot be loaded "
                    f"({type(exc).__name__}); a resume stays refused until it can be")
        why = shape.stack_template_mismatch(frame["stack_dir"], self.cfg.template, name)
        if not why:
            return None
        try:
            with open(self.cfg.template, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        return shape.refusal_sentence(name, why, text)

    def op_resume(self, req, uid):
        step = req.get("from_step")
        if step not in RESUMABLE_STEPS:
            raise Refused(f"from_step: one of {', '.join(RESUMABLE_STEPS)}")
        frame = self.built_frame(req.get("name"))
        # §MTLSHOPS T2 (2026-09-15, with agentvault2-85): a resume launches TODAY's driver on this frame's stack. A stack
        # another template generation rendered (lantern predates T2) is refused here, before any job row exists (R31).
        refusal = self.resume_shape_refusal(frame)
        if refusal:
            self.audit(uid, "resume", name=frame["name"], result="refused: another template shape", from_step=step)
            raise Refused(refusal)
        with self.lock:
            self._refuse_if_busy()
            gates = self.host_gates()
            if gates:
                raise Refused("host gates: " + "; ".join(gates))
            argv = self.driver_argv(frame["spec"], allocate=False) + [
                "--resume-stack-dir", frame["stack_dir"], "--resume-from", step]
            rec = self._launch_driver("resume", uid, frame["name"], argv, request={"name": frame["name"], "from_step": step},
                                      secrets_dir=frame["secrets_dir"],
                                      manage_dns=bool(self.cfg.dns and frame.get("dns_managed")),
                                      mail=not (frame.get("spec") or {}).get("nightly"))
        self.audit(uid, "resume", name=frame["name"], job_id=rec["id"], from_step=step)
        return {"started": True, "job": self.summary(rec)}

    def op_teardown(self, req, uid):
        frame = self.built_frame(req.get("name"))
        with self.lock:
            self._refuse_if_busy()
            rec = self.launch("teardown", uid, frame["name"], ["/bin/bash", self.cfg.teardown, frame["stack_dir"]],
                              request={"name": frame["name"]}, secrets_dir=frame["secrets_dir"], progress=False)
        self.audit(uid, "teardown", name=frame["name"], job_id=rec["id"])
        return {"started": True, "job": self.summary(rec)}

    def op_adopt(self, req, uid):
        """§HELLOFRAME lane 6 (2026-09-18, agentvault2-8d's choice): RECORD a frame this runner did not build, so its
        registry may ask this runner for operator work. frame-up stands a frame up on a stranger's host with its own
        flow (doctor, driver, edge), and the runner may be installed before or after it; the operator ops read the
        frame record this runner holds (`_operator_frame`), so a frame without one is refused as not this runner's.
        Adoption is the narrow bridge: ROOT ONLY, on the full socket, and the same three facts `built_frame` demands
        of a frame the runner built — the stack dir sits directly under the runner's stack root, it carries the
        driver's hetzner-demo-run.json naming the frame, and <name>-registry is running. The record is marked
        adopted: operator ops accept it, the lifecycle ops (resume, teardown, reveal) refuse it, because frame-up owns
        that lifecycle (frame-down). Idempotent: the same frame at the same stack dir answers already=True; the same
        name at another stack dir is refused rather than moved."""
        if uid != 0:
            raise Refused("adopt: root only (a frame's own registry may not adopt frames)")
        name = req.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise Refused("name: not a frame name")
        # §F6 stage 3 (2026-09-27): one of OUR frames (the protected list) is recorded only as a REFERENCE, on the
        # caller's explicit word, so its registry can ask this runner for operator work once its socket is gone. Its
        # lifecycle stays refused twice over: built_frame refuses a protected name before it reads the record, and an
        # adopted record besides. A stranger's frame (frame-up's adopt) never carries the flag.
        reference = req.get("reference") is True
        protected = name in self.protected_names()
        if protected and not reference:
            raise Refused(f"{name} is a protected frame ({self.cfg.protected_list}); it is not adopted, it is ours "
                          f"(reference=true records one of ours for operator work only)")
        if reference and not protected:
            raise Refused(f"reference: {name} is not on the protected list; a reference record is for one of our frames")
        given = str(req.get("stack_dir") or "")
        stack = os.path.realpath(given) if given else ""
        if not stack or os.path.dirname(stack) != os.path.realpath(self.cfg.stack_root) or not os.path.isdir(stack):
            raise Refused(f"stack_dir: {given!r} is not a directory directly under {self.cfg.stack_root}")
        meta = read_json(os.path.join(stack, "hetzner-demo-run.json")) or {}
        if meta.get("name") != name:
            raise Refused(f"{stack}/hetzner-demo-run.json does not name {name} (it names {meta.get('name')!r}): "
                          f"refusing to adopt a directory the driver did not write for this frame")
        c = f"{name}-registry"
        r = subprocess.run(["docker", "inspect", c, "--format", "{{.State.Running}}"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0 or r.stdout.strip() != "true":
            raise Refused(f"{c} is not running ({(r.stderr or r.stdout).strip()[-160:] or 'no such container'}); "
                          f"a frame is adopted live, never from its directory alone")
        with self.lock:
            existing = self.frame(name)
            if existing:
                if os.path.realpath(existing.get("stack_dir") or "") == stack:
                    self.audit(uid, "adopt", name=name, stack_dir=stack, already=True)
                    return {"name": name, "stack_dir": stack, "recorded": False, "already": True,
                            "adopted": bool(existing.get("adopted")), "reference": bool(existing.get("reference"))}
                raise Refused(f"{name} is already recorded at {existing.get('stack_dir')}; refusing to move it to "
                              f"{stack}. Tear that frame down first, or adopt this one under another name")
            frame = {"name": name, "built_by_job": None, "adopted": True, "adopted_by_uid": uid, "stack_dir": stack,
                     "reference": reference,
                     # what the driver's run record says about the frame, for the status listing; never invented
                     "spec": {k: meta[k] for k in ("name", "frame_label", "ticker", "currency_name", "trust_domain",
                                                    "public_url", "env_label") if k in meta},
                     "secrets_dir": str(meta.get("secrets_dir") or ""), "dns_managed": False,
                     "state": "live (reference)" if reference else "live (adopted)", "created": now(), "updated": now()}
            self.save_frame(frame)
        self.audit(uid, "adopt", name=name, stack_dir=stack, already=False, reference=reference)
        return {"name": name, "stack_dir": stack, "recorded": True, "already": False, "adopted": True,
                "reference": reference}

    def op_unadopt(self, req, uid):
        """§TESTBED: forget a frame this runner ADOPTED, once it is gone (frame-down runs this after removing it), so the
        same name can be stood up and adopted again. ROOT ONLY, full socket; a frame the runner BUILT is refused (its
        lifecycle is `teardown`); a frame whose registry container still exists is refused (a frame is forgotten dead,
        never live). Idempotent: an unknown name answers forgotten=False."""
        if uid != 0:
            raise Refused("unadopt: root only")
        name = req.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise Refused("name: not a frame name")
        with self.lock:
            rec = self.frame(name)
            if not rec:
                self.audit(uid, "unadopt", name=name, forgotten=False)
                return {"name": name, "forgotten": False, "note": "not recorded"}
            if not rec.get("adopted"):
                raise Refused(f"{name} was built by this runner; its lifecycle is teardown, not unadopt")
            if rec.get("reference"):
                # §F6: a reference record is the only thing forgotten; the frame itself is ours and stays. Forgetting it
                # live is its rollback (the registry's operator rails then need their socket again): asked for by name.
                if req.get("reference") is not True:
                    raise Refused(f"{name} is a reference record of one of our frames; forgetting it while the frame runs "
                                  f"takes reference=true")
            else:
                r = subprocess.run(["docker", "inspect", f"{name}-registry", "--format", "{{.State.Status}}"],
                                   capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    raise Refused(f"{name}-registry still exists ({r.stdout.strip()}); remove the frame first (frame-down)")
            try:
                os.remove(os.path.join(self.cfg.state, "frames", f"{name}.json"))
            except FileNotFoundError:
                pass
        self.audit(uid, "unadopt", name=name, forgotten=True, stack_dir=rec.get("stack_dir"))
        return {"name": name, "forgotten": True, "stack_dir": rec.get("stack_dir")}

    # ── §TESTBED sandbox ops: served on the operator socket, only where the policy offers sandboxes ──────────────────
    # Estimates of what each topology adds to the host, measured 2026-09-19 (a kit frame ~2.4 GiB with 32 containers,
    # a cloud operator ~0.9 GiB with 10), rounded up; the host must keep its standing floor with the sandbox on top.
    SANDBOX_TOPOLOGIES = {(1, False): 2600, (1, True): 3600, (2, False): 5200, (2, True): 7200}

    def _sandbox_parent(self, req, uid):
        name = str(req.get("frame") or "").strip()
        if not NAME_RE.fullmatch(name):
            raise Refused("frame: the sandbox ops name the frame they are for")
        self._claim_is_the_caller(req, uid, name)
        rec = self.frame(name)
        if not rec:
            raise Refused(f"frame {name!r} is not one this runner knows (frame-up --with-runner adopts it)")
        fu = read_json(os.path.join(str(rec.get("stack_dir") or ""), "frame-up.json")) or {}
        if fu.get("sandbox_of"):
            raise Refused(f"{name} is itself the sandbox of {fu['sandbox_of']}; a sandbox does not provision sandboxes")
        return rec

    def _sandbox_set(self, parent):
        out = []
        root = self.cfg.stack_root
        for d in (sorted(os.listdir(root)) if os.path.isdir(root) else []):
            fu = read_json(os.path.join(root, d, "frame-up.json"))
            if isinstance(fu, dict) and fu.get("sandbox_of") == parent and fu.get("name"):
                out.append({"name": fu["name"], "public_name": fu.get("public_name"), "console": fu.get("console"),
                            "tester": (fu.get("console") or "") + "/#/admin/mcp-tester", "stack_dir": os.path.join(root, d),
                            "edge_health": fu.get("edge_health")})
        return out

    @staticmethod
    def _sandbox_job(rec):
        return None if not rec else {k: rec.get(k) for k in ("id", "op", "name", "state", "created", "ended", "exit_code", "request")}

    def _sandbox_jobs(self, parent):
        return [r for r in self.jobs() if r.get("op") in ("sandbox_up", "sandbox_down") and r.get("name") == parent]

    def op_sandbox_status(self, req, uid):
        parent = self._sandbox_parent(req, uid)
        jobs = self._sandbox_jobs(parent["name"])
        last = jobs[0] if jobs else None
        busy = self.active()
        return {"supported": True, "frame": parent["name"], "sandboxes": self._sandbox_set(parent["name"]),
                "job": self._sandbox_job(last), "last_event": self.last_event(last["id"]) if last else None,
                "topologies": [{"frames": f, "operators": o, "estimate_mib": m}
                               for (f, o), m in sorted(self.SANDBOX_TOPOLOGIES.items())],
                "host": {"problems": self.host_gates(), "mem_available_gib": mem_available_gib(),
                         "busy": {"id": busy["id"], "op": busy.get("op"), "name": busy.get("name")} if busy else None}}

    def _sandbox_launch(self, op, parent, uid, argv, request, children):
        if not os.path.isfile(self.cfg.frame_sandbox):
            raise Refused(f"the sandbox engine is not at {self.cfg.frame_sandbox} in this runner's export")
        with self.lock:
            self._refuse_if_busy()
            rec = self.launch(op, uid, parent, [self.cfg.python, "-u", self.cfg.frame_sandbox] + argv, request,
                              needle="frame-sandbox.py", extra={"children": children})
        self.audit(uid, op, frame=parent, job_id=rec["id"], **request)
        return {"started": True, "job": self._sandbox_job(rec)}

    def op_sandbox_up(self, req, uid):
        parent = self._sandbox_parent(req, uid)
        frames, operators = req.get("frames", 1), req.get("operators", False)
        if frames not in (1, 2) or not isinstance(operators, bool):
            raise Refused("frames is 1 or 2, operators is true or false")
        problems = self.host_gates()
        if problems:
            raise Refused("; ".join(problems))
        est = self.SANDBOX_TOPOLOGIES[(frames, operators)]
        avail = mem_available_gib()
        if avail is not None and avail - est / 1024 < self.cfg.min_mem_gib:
            raise Refused(f"{frames} frame(s){' with operators' if operators else ''} take about {est / 1024:.1f} GiB, and "
                          f"MemAvailable={avail:.1f} GiB would fall under this host's floor of {self.cfg.min_mem_gib:g} GiB")
        name = parent["name"]
        argv = ["up", "--for", name, "--frames", str(frames), "--stack-root", self.cfg.stack_root] + (["--operators"] if operators else [])
        return self._sandbox_launch("sandbox_up", name, uid, argv, {"frames": frames, "operators": operators},
                                    [f"{name}sbx", f"{name}sbxb"][:frames])

    def op_sandbox_down(self, req, uid):
        parent = self._sandbox_parent(req, uid)
        name = parent["name"]
        problems = self.load_gate()   # a teardown only gives memory and disk back
        if problems:
            raise Refused("; ".join(problems))
        return self._sandbox_launch("sandbox_down", name, uid, ["down", "--for", name, "--stack-root", self.cfg.stack_root],
                                    {}, [f"{name}sbx", f"{name}sbxb"])

    def op_sandbox_events(self, req, uid):
        parent = self._sandbox_parent(req, uid)
        job_id = str(req.get("job_id") or "")
        rec = self.job(job_id)
        if rec.get("op") not in ("sandbox_up", "sandbox_down") or rec.get("name") != parent["name"]:
            raise Refused(f"job {job_id} is not a sandbox job of {parent['name']}")
        after = req.get("after", 0)
        after = after if isinstance(after, int) and after >= 0 else 0
        events, nxt, _lines = self.events(job_id, after)
        return {"job": self._sandbox_job(rec), "events": events, "next": nxt}

    def op_sandbox_reveal(self, req, uid):
        """The admin login of one of the calling frame's sandboxes (its frame admin, the first password frame-up wrote),
        so the person who provisioned it can open its console and tester. Audited; never logged."""
        parent = self._sandbox_parent(req, uid)
        which = req.get("which", "a")
        if which not in ("a", "b"):
            raise Refused("which: a or b")
        name = parent["name"] + ("sbx" if which == "a" else "sbxb")
        found = next((s for s in self._sandbox_set(parent["name"]) if s["name"] == name), None)
        if not found:
            raise Refused(f"{parent['name']} has no sandbox {which} ({name})")
        fu = read_json(os.path.join(str(found.get("stack_dir") or ""), "frame-up.json")) or {}
        sec = read_json(os.path.join(str(fu.get("secrets_dir") or ""), f".{name}_frame_admin.secret.json")) or {}
        email, password = sec.get("admin_email"), sec.get("admin_password")
        if not email or not password:
            raise Refused(f"{name}'s admin secret file is missing or has no login")
        self.audit(uid, "sandbox_reveal", frame=parent["name"], sandbox=name)
        return {"sandbox": name, "console": found.get("console"), "email": email, "password": password}

    def op_cancel(self, req, uid):
        rec = self.job(req.get("job_id"))
        with self.lock:
            rec = self.job(rec["id"])
            if rec.get("state") != "running" or not pid_alive(rec.get("pid"), rec.get("needle")):
                raise Refused(f"job {rec['id']} is {rec.get('state')}, not running")
            rec["state"] = "cancelling"
            self.save_job(rec)
        try:
            os.killpg(rec["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        timer = threading.Timer(30, self._kill_if_alive, args=(rec["pid"], rec.get("needle")))
        timer.daemon = True
        timer.start()
        self.audit(uid, "cancel", name=rec["name"], job_id=rec["id"])
        return {"cancelling": rec["id"]}

    def op_status(self, req, uid):
        if req.get("job_id") is not None:
            rec = self.job(req.get("job_id"))
            return {"job": rec, "last_event": self.last_event(rec["id"])}
        frames = [read_json(p) for p in sorted(glob.glob(os.path.join(self.cfg.state, "frames", "*.json")))]
        active = self.active()
        return {"active": self.summary(active) if active else None,
                "jobs": [self.summary(r) for r in self.jobs()[:20]], "frames": [f for f in frames if f]}

    def op_events(self, req, uid):
        rec = self.job(req.get("job_id"))
        after = req.get("after", 0)
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise Refused("after: a line number, 0 or more")
        events, nxt, _ = self.events(rec["id"], after)
        return {"events": events, "next": nxt, "state": rec.get("state")}

    def op_reveal(self, req, uid):
        frame = self.built_frame(req.get("name"))
        name = frame["name"]
        path = os.path.join(frame.get("secrets_dir") or "", f".{name}_frame_admin.secret.json")
        with self.lock:
            doc = read_json(path)
            if not doc:
                if frame.get("revealed_at"):
                    raise Refused(f"{name}: the admin credential was handed over at {frame['revealed_at']}; the frame's "
                                  f"own .env.frame-test still holds it on the host")
                raise Refused(f"{name}: no admin credential on record yet (the standup writes it at its jurisdiction step)")
            os.remove(path)
            frame["revealed_at"] = now()
            self.save_frame(frame)
        self.audit(uid, "reveal", name=name)
        return {"admin_email": doc.get("admin_email"), "admin_password": doc.get("admin_password"),
                "console": f"https://{name}.{self.cfg.domain}"}

    def op_dns_status(self, req, uid):
        return self.dns_state(self._dns_name(req.get("name")))

    def op_dns_ensure(self, req, uid):
        name = self._dns_name(req.get("name"))
        with self.lock:
            stacks = [d for d in glob.glob(os.path.join(self.cfg.stack_root, f"{name}-*"))
                      if re.fullmatch(rf"{re.escape(name)}-\d+", os.path.basename(d))]
            if stacks and not self.frame(name):
                raise Refused(f"name: {name} has a stack dir this runner did not build ({stacks[0]})")
            return self._dns_ensure(name, uid, "manual")

    def op_dns_remove(self, req, uid):
        name = self._dns_name(req.get("name"))
        with self.lock:
            if self.frame(name):
                raise Refused(f"{name} is a frame this runner built: its teardown deletes its DNS")
            busy = self.active()
            if busy and busy.get("name") == name:
                raise Refused(f"job {busy['id']} ({busy['op']} {name}) is running")
            return self._dns_remove(name, uid)

    def op_dns_push_ensure(self, req, uid):
        """§PUSH (2026-10-06, his words "the key/token that the provisioner is using to issue subdomains. needs to do this
        in the provisioner. and you can do it for us too"): ONE name, `<name>-push.<domain>`, for a frame whose other
        names predate the runner (the sandbox pair: sandbox-a and sandbox-b were stood up before P5 and have no public
        push name). dns_ensure is all-or-nothing over the four names and refuses such a frame, rightly: it never adopts.
        This op adopts nothing either. It creates the push name alone, with the runner's own token and mark, and writes
        the record's id down so dns_remove deletes it like any other runner record. It refuses when the push name already
        has a record the runner did not create, or already resolves without one, and when the frame's console name does
        not resolve (there is no frame there to name). `dry_run` answers what it would create and creates nothing."""
        name = self._dns_name(req.get("name"))
        hosts = frame_dns.names(name, self.cfg.domain)
        console, host = hosts[0], hosts[3]
        with self.lock:
            client = self.dns_client()
            mine = {r.get("id") for r in self.dns_record(name)["records"]}
            try:
                found = client.records(host)
            except frame_dns.DNSError as exc:
                raise Refused(str(exc))
            foreign = [r for r in found if not (r.get("id") in mine and frame_dns.carries_mark(r, name))]
            if foreign:
                what = ", ".join(f"{r.get('type')} {r.get('content')}" for r in foreign)
                raise Refused(f"{host} already has a record the runner did not create ({what}): refused, never adopted")
            resolves = frame_dns.resolve(host, self.cfg.dns["resolver"], self.cfg.dig)
            if found:
                return {"name": name, "host": host, "created": [], "present": [host], "resolves": resolves}
            if resolves:
                raise Refused(f"{host} already resolves at {self.cfg.dns['resolver']} ({', '.join(resolves)}) "
                              f"without a record in the zone: refused, never adopted")
            if not frame_dns.resolve(console, self.cfg.dns["resolver"], self.cfg.dig):
                raise Refused(f"{console} does not resolve: there is no frame by that name to give a push name")
            if req.get("dry_run"):
                return {"name": name, "host": host, "would_create": host, "ipv4": self.cfg.dns["ipv4"], "created": []}
            job = "push-" + uuid.uuid4().hex[:12]
            rec = self.dns_record(name)
            try:
                made = client.create_a(host, self.cfg.dns["ipv4"], frame_dns.mark(name, job))
            except frame_dns.DNSError as exc:
                self.audit(uid, "dns_push_ensure", name=name, result="failed", error=str(exc)[:300])
                raise Refused(str(exc))
            rec["records"].append({"id": made.get("id"), "host": host, "content": made.get("content"), "job": job,
                                   "created": now()})
            self._save_dns(rec)
            self.audit(uid, "dns_push_ensure", name=name, job=job, created=[host])
            return {"name": name, "host": host, "created": [host], "ipv4": self.cfg.dns["ipv4"]}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        _pid, uid, _gid = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                                         struct.calcsize("3i")))
        try:
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(line) > MAX_REQUEST_BYTES:
                raise Refused(f"a request is at most {MAX_REQUEST_BYTES} bytes")
            try:
                req = json.loads(line.decode("utf-8") or "null")
            except (ValueError, UnicodeDecodeError):
                raise Refused("a request is one JSON object on one line")
            if not isinstance(req, dict):
                raise Refused("a request is one JSON object on one line")
            resp = {"ok": True, "result": self.server.runner.handle(req, uid, getattr(self.server, "allowed_ops", None), pid=_pid)}
        except Refused as exc:
            resp = {"ok": False, "refused": str(exc)}
        except Exception as exc:  # noqa: BLE001 — the caller gets the class of the failure, the service keeps serving
            resp = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def make_server(cfg, runner=None, socket_path=None, allowed=None):
    """One listener. §LANTERNT3: `allowed` is the op set THIS socket serves, so the grant is bounded by which
    file a caller can see rather than by a notion of caller identity we would have to invent."""
    runner = runner or Runner(cfg)
    path = socket_path or cfg.socket
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    # ⚠ THE DIRECTORY NEEDS THE GROUP TOO. The socket's own 0660 root:<group> is not enough: a caller must be
    # able to TRAVERSE the parent to reach it, and os.makedirs leaves 0750 root:root, which a frame's registry
    # (uid 1000) cannot enter. Measured on the first build of this: the socket was perfectly addressable and
    # perfectly unreachable. Same shape as a git checkout leaving templates 640 in a container that runs as 1000.
    if os.geteuid() == 0:
        try:
            os.chown(parent, 0, grp.getgrnam(cfg.socket_group).gr_gid)
            os.chmod(parent, 0o750)
        except KeyError:
            raise SystemExit(f"socket group {cfg.socket_group} does not exist")
    if os.path.lexists(path):
        if not stat.S_ISSOCK(os.lstat(path).st_mode):
            raise SystemExit(f"{path} exists and is not a socket; refusing to replace it")
        os.remove(path)
    srv = Server(path, _Handler)
    srv.runner = runner
    srv.allowed_ops = tuple(allowed) if allowed is not None else OPS
    os.chmod(path, 0o660)
    if os.geteuid() == 0:
        try:
            os.chown(path, 0, grp.getgrnam(cfg.socket_group).gr_gid)
        except KeyError:
            raise SystemExit(f"socket group {cfg.socket_group} does not exist")
    return srv


def call(socket_path, request, timeout=600):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(socket_path)
        s.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8"))


def await_dns(argv):
    """`frame_runner.py await-dns --hosts h1,h2 --resolver R --timeout S --interval S --dig PATH -- <driver argv>`.
    The first phase of a standup whose names the runner has just created: wait until the resolver answers every host,
    record that as the job's first progress step, then become the driver (exec keeps the pid, the process group and the
    needle the runner watches)."""
    if "--" not in argv:
        print("usage: frame_runner.py await-dns --hosts h1,h2 [--resolver R] [--timeout S] [--interval S] [--dig PATH] "
              "-- <driver argv>", file=sys.stderr)
        return 2
    i = argv.index("--")
    opts, driver = argv[:i], argv[i + 1:]
    if len(opts) % 2 or not driver:
        print("await-dns: options come in pairs, and a driver argv follows --", file=sys.stderr)
        return 2
    o = dict(zip(opts[0::2], opts[1::2]))
    hosts = [h for h in o.get("--hosts", "").split(",") if h]
    resolver, dig = o.get("--resolver", "1.1.1.1"), o.get("--dig", "dig")
    timeout, interval = float(o.get("--timeout", 300)), float(o.get("--interval", 5))
    progress = driver[driver.index("--progress-file") + 1] if "--progress-file" in driver[:-1] else None

    def emit(event, **fields):
        if progress:
            with open(progress, "a") as f:
                f.write(json.dumps({"ts": now(), "step": "dns", "event": event, **fields}) + "\n")

    emit("start")
    deadline = time.time() + timeout
    while True:
        pending = [h for h in hosts if not frame_dns.resolve(h, resolver, dig)]
        if not pending:
            break
        if time.time() >= deadline:
            sentence = (f"{', '.join(pending)} still do not resolve at {resolver} after {timeout:g} s; the records exist "
                        f"(dns_status names them), and the next standup of this name waits again")
            print(f"[await-dns] {sentence}", flush=True)
            emit("fail", verdict="refused", sentence=sentence)
            return 3
        time.sleep(interval)
    print(f"[await-dns] {len(hosts)} host(s) resolve at {resolver}", flush=True)
    emit("end", verdict="ok")
    os.execv(driver[0], driver)


def adopt_cli(argv):
    """`frame_runner.py adopt --name <name> --stack-dir <dir> [--socket <path>]` (§HELLOFRAME lane 6): record a frame
    this runner did not build, as root, over the full socket, without writing a socket client. frame-up runs it after
    its standup and before its edge. Exit 0 recorded or already recorded (the result JSON on stdout), 2 refused (the
    runner's sentence on stderr), 3 the runner did not answer (no socket, refused connection, timeout)."""
    ap = argparse.ArgumentParser(prog="frame_runner.py adopt", description=adopt_cli.__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--stack-dir", required=True)
    ap.add_argument("--reference", action="store_true", default=False,
                    help="§F6: one of OUR frames (the protected list), recorded for operator work only")
    ap.add_argument("--socket", default=None, help="the runner's FULL socket (default: FRAME_RUNNER_SOCKET or the runner's own)")
    ap.add_argument("--timeout", type=float, default=60.0)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    sock = a.socket or Config(conf={}).socket
    req = {"op": "adopt", "name": a.name, "stack_dir": os.path.abspath(a.stack_dir)}
    if a.reference:
        req["reference"] = True
    try:
        resp = call(sock, req, timeout=a.timeout)
    except (OSError, ValueError) as exc:
        print(f"[frame-runner adopt] the runner at {sock} did not answer: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        why = (resp.get("refused") or resp.get("error")) if isinstance(resp, dict) else None
        print(f"[frame-runner adopt] REFUSED: {why or 'no reason given'}", file=sys.stderr)
        return 2
    res = resp.get("result") or {}
    print(json.dumps(res))
    print(f"[frame-runner adopt] {a.name}: {'already recorded' if res.get('already') else 'recorded'} at "
          f"{res.get('stack_dir')}", file=sys.stderr)
    return 0


def unadopt_cli(argv):
    """`frame_runner.py unadopt --name <name> [--socket <path>]` (§TESTBED): forget an adopted frame once it is gone (frame-down
    runs it). Exit 0 forgotten or not recorded, 2 refused, 3 the runner did not answer."""
    ap = argparse.ArgumentParser(prog="frame_runner.py unadopt", description=unadopt_cli.__doc__)
    ap.add_argument("--name", required=True)
    ap.add_argument("--reference", action="store_true", default=False,
                    help="§F6: forget a reference record while its frame runs (the rollback of adopt --reference)")
    ap.add_argument("--socket", default=None, help="the runner's FULL socket (default: FRAME_RUNNER_SOCKET or the runner's own)")
    ap.add_argument("--timeout", type=float, default=60.0)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    sock = a.socket or Config(conf={}).socket
    req = {"op": "unadopt", "name": a.name}
    if a.reference:
        req["reference"] = True
    try:
        resp = call(sock, req, timeout=a.timeout)
    except (OSError, ValueError) as exc:
        print(f"[frame-runner unadopt] the runner at {sock} did not answer: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        why = (resp.get("refused") or resp.get("error")) if isinstance(resp, dict) else None
        print(f"[frame-runner unadopt] REFUSED: {why or 'no reason given'}", file=sys.stderr)
        return 2
    res = resp.get("result") or {}
    print(f"{a.name}: {'forgotten' if res.get('forgotten') else 'not recorded'}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["adopt"]:
        return adopt_cli(argv[1:])
    if argv[:1] == ["unadopt"]:
        return unadopt_cli(argv[1:])
    if argv[:1] == ["serve"] and len(argv) == 1:
        cfg = Config()
        runner = Runner(cfg)
        srv = make_server(cfg, runner)                                     # full socket: frame management
        opsrv = make_server(cfg, runner, cfg.operator_socket,                # second socket: a frame's own operator
                            OPERATOR_OPS + (SANDBOX_OPS if cfg.sandboxes else ()))  # work, and its sandbox (§TESTBED)

        def _stop(signum, frame):
            threading.Thread(target=srv.shutdown, daemon=True).start()
            threading.Thread(target=opsrv.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        print(f"[frame-runner] v{VERSION}{' instance ' + cfg.instance if cfg.instance else ''} serving {cfg.socket} "
              f"(state {cfg.state}, policy {cfg.config_path}, driver {cfg.driver}, "
              f"uids {sorted(cfg.allowed_uids)}, images {cfg.images})", flush=True)
        print(f"[frame-runner] v{VERSION} serving {cfg.operator_socket} — operator ops only "
              f"({', '.join(OPERATOR_OPS)}){'; the sandbox ops (' + ', '.join(SANDBOX_OPS) + ')' if cfg.sandboxes else ''}"
              f"; frame ops are REFUSED on it", flush=True)
        threading.Thread(target=opsrv.serve_forever, daemon=True).start()
        srv.serve_forever()
        return 0
    if argv[:1] == ["await-dns"]:
        return await_dns(argv[1:])
    if argv[:1] == ["call"] and len(argv) == 2:
        print(json.dumps(call(Config(conf={}).socket, json.loads(argv[1])), indent=1))
        return 0
    print("usage: frame_runner.py serve | frame_runner.py call '<one JSON request>' | "
          "frame_runner.py adopt --name <frame> --stack-dir <dir> | "
          "frame_runner.py await-dns ... -- <driver argv>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
