"""§ONESHOT P2.1 (2026-09-12) — the `federate` step of the one-pass standup.

WHY THIS EXISTS. The driver federates nothing (the runbook's own sentence, §7.3): every fact that only
exists after the bilateral approve lived in two hand scripts (`scratchpad/batch6/federate_pair.py`,
`scratchpad/batch10/after_standups.sh`, EU/ASIA hardcoded) and in the hands of whoever ran them.
Appendix A of `PLAN_2026-09-12_AUTONOMOUS_PACKAGES.md` counted four mechanisms (#4 host half, #7, #9,
#12) that are all consequences of that approve and that the driver could not write because it runs
before the peer exists and never runs again. `--federate-with <peer stack dir>` on the SECOND frame's
run is the one actor that holds both frames' admins, so it does the whole post-approve state on BOTH
frames, idempotently, and verifies the three layers on both sides before it calls the pair federated.

WHAT IT DOES, in order, for each peer (a third peer APPENDS, never overwrites):
  0. preconditions, each a sentence naming the fix (nothing is written before all pass)
  1. the invitation dance: create-on-approver + approve, both directions (an already-completed
     invitation for the peer's trust domain is reused), then resync-eventstore on both
  2. the licence the dead finalize callback never delivers (row 44): the plain key an approve issued
     is seeded into the OTHER frame's env + `.<name>_frame_licence.secret.json` (600) — the anchor of
     a new network holds no licence otherwise (measured on EU, `PLAN_2026-09-12_ONESHOT.md` §2)
  3. the post-approve env on BOTH frames: replication on + `<td>|<es url>`, `<peer>-registry` into
     KNOWN_INTERNAL_SERVICES, the peer td into TRUSTED_SPIFFE_DOMAINS, the six FX keys (list append
     by registry_id, dict merge), EVENT_STORE_B_URL, the FRESH_NETWORK_JSON entry; baks first
  4. recreate `--no-deps` event-store, teg, registry on both (health each; the public rails after)
  5. two roots on the four proxies, else the parked `registry:federation:cardpull_*` keys are cleared
  6. the reserve-keeper PUT on both, then `/fx/rates` available on both
  7. verify: typed peer row, `federation list`, `bundle list`, `entry show FederatesWith`, the
     cached registry card, Δ=0 on both ledgers — refused if any layer is missing
  8. `<stack>/federation.json` on both, so teardown knows what to unwire and a third peer appends
Credentials are read from the stacks' 600 files BY NAME and never printed.
"""
import importlib.util as _ilu
import json
import os
import re
import secrets
import subprocess
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = _ilu.spec_from_file_location("standup_extras", os.path.join(_HERE, "standup_extras.py"))
extras = _ilu.module_from_spec(_spec); _spec.loader.exec_module(extras)   # type: ignore[union-attr]
http, log = extras.http, extras.log

SECRETS_DIR = extras.SECRETS_DIR
DOMAIN = extras.DOMAIN
PROXIES = ("nginx-federation", "nginx-teg")          # the two per-frame proxies that must carry both roots
RECREATE_ORDER = ("event-store", "teg", "registry")  # the registry proxies to the TEG; the ES first
KEEPER_FLOATS = {"target_float": "100000", "min_float": "50000", "max_float": "200000", "max_move_per_cycle": "100000"}


# ── pure helpers (unit-tested in tests/test_standup_federate.py) ──────────────────────────────────

def read_env(path: str) -> Dict[str, str]:
    d: Dict[str, str] = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def env_get(text: str, key: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(key)}=(.*)$", text, re.M)
    return None if m is None else m.group(1).strip().strip('"').strip("'")


def upsert_env_line(text: str, key: str, value: str) -> Tuple[str, bool]:
    """Replace `KEY=...` (any value) or append. Returns (text, changed)."""
    cur = env_get(text, key)
    if cur == str(value):
        return text, False
    pat = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    line = f"{key}={value}"
    if pat.search(text):
        return pat.sub(lambda _m: line, text, count=1), True
    return text.rstrip("\n") + f"\n{line}\n", True


def merge_csv(text: str, key: str, items: List[str]) -> Tuple[str, bool]:
    """Comma list, order kept, deduped; appends what is missing."""
    cur = [x.strip() for x in (env_get(text, key) or "").split(",") if x.strip()]
    out = list(cur)
    for it in items:
        if it and it not in out:
            out.append(it)
    return upsert_env_line(text, key, ",".join(out)) if out != cur else (text, False)


def merge_pipe_list(text: str, key: str, ident: str, entry: str) -> Tuple[str, bool]:
    """`a|x,b|y` entries keyed on the part before `|`: replace the entry with that key or append."""
    cur = [x.strip() for x in (env_get(text, key) or "").split(",") if x.strip()]
    out = [x for x in cur if x.split("|", 1)[0] != ident] + [entry]
    return upsert_env_line(text, key, ",".join(out)) if out != cur else (text, False)


def _json_load(raw: Optional[str], default):
    if raw is None or not raw.strip():
        return default
    try:
        v = json.loads(raw)
    except Exception:
        return default
    return v if isinstance(v, type(default)) else default


def merge_json_list(text: str, key: str, entry: Dict[str, Any], id_field: str) -> Tuple[str, bool]:
    """A JSON list env value: the entry with the same id is REPLACED, a new one is APPENDED."""
    cur = _json_load(env_get(text, key), [])
    out = [e for e in cur if not (isinstance(e, dict) and e.get(id_field) == entry.get(id_field))] + [entry]
    if out == cur:
        return text, False
    return upsert_env_line(text, key, json.dumps(out, separators=(",", ":")))


def merge_json_dict(text: str, key: str, mapping: Dict[str, Any]) -> Tuple[str, bool]:
    cur = _json_load(env_get(text, key), {})
    out = dict(cur); out.update(mapping)
    if out == cur:
        return text, False
    return upsert_env_line(text, key, json.dumps(out, separators=(",", ":")))


def fresh_network_entry(peer: Dict[str, Any]) -> Dict[str, Any]:
    """The peer's tile as `standup_driver._fresh_network_json` shapes it (the socket path is the lane this
    console serves for the peer; facts the driver cannot know are omitted, never guessed)."""
    e = {"name": str(peer.get("frame_label") or peer["name"]).upper(), "slug": peer["name"], "role": "frame",
         "group": peer.get("env_label") or "sandbox", "console": peer["public_url"].rstrip("/"),
         "status_url": peer["public_url"].rstrip("/") + "/#/status",
         "registry_url": peer["public_url"].rstrip("/"), "es_url": (peer.get("es_public_url") or "").rstrip("/"),
         "ws_path": f"/ws/events-{peer['name']}"}
    if peer.get("ticker"):
        e["currency"] = peer["ticker"]
    if peer.get("currency_name"):
        e["currency_name"] = peer["currency_name"]
    return e


def post_approve_env(text: str, peer: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Everything a frame's env must carry about a federated peer. Returns (text, changed keys).
    The six FX keys are written only when the peer has an `@fx_router` DID — a route to nobody is
    the §FXSTRAND shape, and the caller SAYS which peer stays FX-less."""
    changed: List[str] = []
    def apply(fn, *a):
        nonlocal text
        text, ch = fn(text, *a)
        if ch:
            changed.append(a[0])
    apply(upsert_env_line, "FT_ES_CROSS_FRAME_REPLICATION_ENABLED", "true")
    apply(merge_pipe_list, "FT_ES_CROSS_FRAME_PEERS", peer["td"], f"{peer['td']}|{peer['es_public_url']}")
    apply(merge_csv, "FT_ES_KNOWN_INTERNAL_SERVICES", [f"{peer['name']}-registry"])
    apply(merge_csv, "FT_TRUSTED_SPIFFE_DOMAINS", [peer["td"]])
    apply(merge_json_list, "FT_REG_FRESH_NETWORK_JSON", fresh_network_entry(peer), "slug")
    if peer.get("router_did", "").startswith("did:"):
        apply(upsert_env_line, "FT_REG_FX_ENABLED", "true")
        apply(upsert_env_line, "FT_REG_FX_RATE_MODE", "pool")
        apply(merge_json_list, "FT_REG_FX_ROUTE_PEERS",
              {"currency": peer["ticker"], "registry_id": peer["name"], "teg_id": f"teg-layer-{peer['name']}",
               "router_did": peer["router_did"]}, "registry_id")
        apply(merge_json_dict, "FT_REG_TEG_SIDECAR_MAP",
              {f"teg-layer-{peer['name']}": f"{peer['name']}-nginx-teg", f"registry-{peer['name']}": f"{peer['name']}-nginx-teg"})
        apply(upsert_env_line, "FT_REG_FX_RESERVE_KEEPER_ENABLED", "true")
        apply(upsert_env_line, "FT_REG_EVENT_STORE_B_URL", peer["es_public_url"])
    return text, changed


def keeper_body(own_ticker: str, anchor_ticker: str) -> Dict[str, Any]:
    body: Dict[str, Any] = {"enabled": True, "anchor_currency": anchor_ticker, "ratio_vs_anchor": "1"}
    body.update(KEEPER_FLOATS)
    if own_ticker != anchor_ticker:
        body.pop("target_float", None)   # the non-anchor pegs by ratio; the anchor holds the float
    return body


def classify_preconditions(me: Dict[str, Any], peer: Dict[str, Any], *, peer_health: int, my_svid_verifies: bool,
                           federated_pem_roots: int) -> List[str]:
    """Every reason NOT to start, as sentences naming the fix. Empty = go."""
    out: List[str] = []
    if peer_health != 200:
        out.append(f"the peer registry at 127.0.0.1:{peer.get('registry_port')} does not answer /health "
                   f"({peer_health}): stand the peer up first, or point --federate-with at its stack dir")
    if not peer.get("td") or not peer.get("es_public_url") or not peer.get("admin_email"):
        out.append(f"the peer stack {peer.get('stack_dir')} lacks a trust domain, EVENT_STORE_PUBLIC_URL or "
                   f"FIRST_ADMIN_EMAIL in .env.frame-test: it is not a frame this driver stood up")
    if me.get("identity_net") and peer.get("identity_net") and me["identity_net"] != peer["identity_net"]:
        out.append(f"identity networks differ ({me['identity_net']} vs {peer['identity_net']}): both frames must "
                   f"declare the same --identity-net so their SPIRE servers resolve each other by name")
    if me.get("td") == peer.get("td"):
        out.append("both frames carry the same trust domain: a frame cannot federate with itself")
    if federated_pem_roots < 2:
        out.append(f"the host federated bundle carries {federated_pem_roots} root(s), the peer's ES vhost cannot verify "
                   f"this frame's SVID: register both frames in /etc/theprotocol/frame-spire-bundles.list and run "
                   f"/usr/local/bin/frame-spire-bundle.sh (FORCE=1)")
    elif not my_svid_verifies:
        out.append("this frame's registry SVID does not verify against the host federated bundle: the bundle is "
                   "stale — run /usr/local/bin/frame-spire-bundle.sh and retry")
    return out


# ── facts about a frame, from its stack dir (by name; never printed) ─────────────────────────────

def frame_facts(stack_dir: str) -> Dict[str, Any]:
    sd = stack_dir.rstrip("/")
    meta = json.load(open(os.path.join(sd, "hetzner-demo-run.json")))
    env = read_env(os.path.join(sd, ".env.frame-test"))
    comp = open(os.path.join(sd, "docker-compose.frame-test.yml")).read()
    def port(inner: str) -> Optional[int]:
        m = re.search(rf'127\.0\.0\.1:(\d+):{inner}"?', comp)
        return int(m.group(1)) if m else None
    name = meta["name"]
    public_url = (meta.get("public_url") or env.get("PUBLIC_URL") or "").rstrip("/")
    host = urllib.parse.urlparse(public_url).hostname or f"{name}.{DOMAIN}"
    return {
        "name": name, "ts": meta.get("ts"), "stack_dir": sd,
        "frame_label": meta.get("frame_label") or name, "env_label": meta.get("env_label") or "sandbox",
        "td": env.get("SPIRE_TRUST_DOMAIN") or env.get("FT_SPIRE_TRUST_DOMAIN") or meta.get("trust_domain") or "",
        "ticker": meta.get("ticker") or env.get("FRAME_CURRENCY") or "", "currency_name": meta.get("currency_name") or "",
        "public_url": public_url, "host": host,
        "es_public_url": (env.get("FT_REG_EVENT_STORE_PUBLIC_URL") or env.get("EVENT_STORE_PUBLIC_URL")
                          or meta.get("es_public_url") or "").rstrip("/"),
        "fed_url": (meta.get("federation_public_url") or f"https://{host}:8443").rstrip("/"),
        # §F6 WP6.5/A4: the endpoint the frame ADVERTISES (its own env), not a compose-internal name no peer resolves
        "bundle_url": env.get("FRAME_LOCAL_BUNDLE_ENDPOINT_URL") or f"https://{name}-spire-server:8443/",
        "admin_email": env.get("FIRST_ADMIN_EMAIL", ""), "admin_password": env.get("FIRST_ADMIN_PASSWORD", ""),
        "router_did": env.get("FT_REG_FX_ROUTER_DID", ""),
        "identity_net": env.get("FT_REG_IDENTITY_NETWORK") or env.get("IDENTITY_NETWORK") or "",
        "registry_port": (meta.get("ports") or {}).get("registry") or port("8000"),
        "es_port": (meta.get("ports") or {}).get("es") or port("8200"),
        "has_license": bool(env.get("FEDERATION_LICENSE_KEY")),
    }


def base(f: Dict[str, Any]) -> str:
    return f"http://127.0.0.1:{f['registry_port']}"


def login(f: Dict[str, Any]) -> str:
    st, r = http("POST", f"{base(f)}/api/v1/auth/login",
                 {"username": f["admin_email"], "password": f["admin_password"]}, form=True)
    if st != 200 or not isinstance(r, dict) or "access_token" not in r:
        raise SystemExit(f"federate: admin login on {f['name']} failed HTTP {st}")
    return r["access_token"]


def hdr(tok: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# ── the licence the callback never delivers ──────────────────────────────────────────────────────

def pre_issue_license(peer_stack_dir: str, my_name: str, my_td: str) -> Optional[str]:
    """Before render: the PEER (the anchor) issues this frame's licence so the frame is licensed from
    its first boot (§12c's order, done by the driver instead of by hand). Returns the plain key ONCE."""
    peer = frame_facts(peer_stack_dir)
    tok = login(peer)
    key = extras.issue_frame_license(base(peer), hdr(tok), frame_name=my_name, frame_trust_domain=my_td)
    if key:
        rec = {"operator_name": my_name, "operator_did": f"spiffe://{my_td}", "licensee_type": "frame", "license_key": key,
               "issued_by": peer["name"], "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "active",
               "note": "issued by the anchor BEFORE this frame's first boot (--federate-with); the env carries it as FEDERATION_LICENSE_KEY"}
        rp = f"{SECRETS_DIR}/.{my_name}_frame_licence.secret.json"
        open(rp, "w").write(json.dumps(rec, indent=1)); os.chmod(rp, 0o600)
        log(f"federate: {peer['name']} issued {my_name}'s federation licence before its first boot ({rp} 600)")
    else:
        log(f"federate: {peer['name']} did not issue a licence for {my_name} (see the line above); "
            f"the approve will issue one and the step seeds it")
    return key


def seed_license(f: Dict[str, Any], key: str, issuer: str) -> bool:
    """Write the plain key into the frame's env (FEDERATION_LICENSE_KEY) and its 600 secret file."""
    envp = os.path.join(f["stack_dir"], ".env.frame-test")
    txt = open(envp).read()
    txt, ch = upsert_env_line(txt, "FEDERATION_LICENSE_KEY", key)
    if ch:
        open(envp, "w").write(txt)
    rec = {"operator_name": f["name"], "operator_did": f"spiffe://{f['td']}", "licensee_type": "frame",
           "license_key": key, "issued_by": issuer, "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "status": "active"}
    p = f"{SECRETS_DIR}/.{f['name']}_frame_licence.secret.json"
    open(p, "w").write(json.dumps(rec, indent=1)); os.chmod(p, 0o600)
    log(f"federate: {f['name']} now holds the licence {issuer} issued (env {'updated' if ch else 'unchanged'}, {p} 600)")
    return ch


# ── §FEDLICENCE (2026-09-28): the network licence rides the invitation ──────────────────────────
# Under FEDERATION_LICENCE_MODE=enforce an approve refuses an initiator that presents no licence it can verify, and only
# the network's genesis admits an unlicensed one, by issuing it a licence in the same approve (network_licence_plan).
# This step creates each invitation ON the approver, so it carries what the initiator's own outbound call would: its
# licence-signing key and the licence it holds. Measured by the kit dry run (agentvault2-a4, 2026-09-28): without these
# facts both approves answer 403 in enforce, so no new frame could join a network that enforces.

def licence_facts(f: Dict[str, Any]) -> Dict[str, Any]:
    """The frame's own licence block from its public route ({state, key, certificate, chain, ...}); {} from an image
    without licences (404) or on any failure, and then the frame federates exactly as before."""
    try:
        st, r = http("GET", f"{base(f)}/api/v1/federation/licence/own", timeout=20)
    except Exception:  # noqa: BLE001 - a frame that cannot say is a frame without licence facts
        return {}
    return r if st == 200 and isinstance(r, dict) else {}


def licence_invitation_fields(lic: Dict[str, Any]) -> Dict[str, Any]:
    """The optional invitation fields describing a frame's licence: its key (so a genesis can issue to it) and the
    licence it holds (so an approver that enforces can verify it)."""
    out: Dict[str, Any] = {}
    key = lic.get("key")
    if isinstance(key, dict) and key.get("kty") == "OKP" and key.get("x"):
        out["licence_key"] = {k: key.get(k) for k in ("kty", "crv", "x")}
    cert = lic.get("certificate")
    if isinstance(cert, str) and cert and lic.get("state") in ("genesis", "licensed"):
        out["licence_certificate"] = cert
        out["licence_chain"] = [c for c in (lic.get("chain") or []) if isinstance(c, str)][:2]
    return out


def approve_licence_fields(approver_lic: Dict[str, Any], described_lic: Dict[str, Any], plan: str) -> Dict[str, Any]:
    """On the network's genesis, admitting a frame that holds no licence: issue one under `plan`. Anywhere else, or for
    a frame that already holds one, nothing: the approve verifies what the invitation presents."""
    if not plan or approver_lic.get("state") != "genesis" or described_lic.get("state") in ("genesis", "licensed"):
        return {}
    return {"network_licence_plan": plan}


def genesis_first(my_lic: Dict[str, Any], peer_lic: Dict[str, Any]) -> bool:
    """A frame without a licence joining the genesis is admitted BY the genesis first: it then holds its licence (and,
    through FEDERATION_GENESIS_CERT_HASH, the root) before its own approve verifies the genesis."""
    return peer_lic.get("state") == "genesis" and my_lic.get("state") not in ("genesis", "licensed")


def install_issued_licence(issuer: Dict[str, Any], holder: Dict[str, Any], holder_tok: str,
                           netlic: Optional[Dict[str, Any]]) -> Optional[str]:
    """The licence an approve issued, installed on the frame it names when the finalize callback did not (a same-host
    pair's callback often cannot reach the initiator). Returns the verdict sentence, or None when there is nothing to do."""
    if not isinstance(netlic, dict) or not netlic.get("issued_hash"):
        return None
    done = netlic.get("installed_by_peer") or {}
    if isinstance(done, dict) and done.get("installed"):
        return f"installed by the callback ({done.get('state')})"
    h = netlic["issued_hash"]
    st, r = http("GET", f"{base(issuer)}/api/v1/public/federation/licences/{h}", timeout=20)
    root = (licence_facts(issuer) or {}).get("certificate")
    if st != 200 or not isinstance(r, dict) or not r.get("certificate") or not root:
        raise SystemExit(f"federate: {issuer['name']} issued {holder['name']} licence {h[:16]} but it could not be read "
                         f"back (HTTP {st}); install it with POST /api/v1/admin/federation/licence/install")
    st, r2 = http("POST", f"{base(holder)}/api/v1/admin/federation/licence/install",
                  {"certificate": r["certificate"], "chain": [root]}, headers=hdr(holder_tok), timeout=60)
    if st >= 300 or not isinstance(r2, dict):
        raise SystemExit(f"federate: [{holder['name']}] install of licence {h[:16]} refused HTTP {st}: {str(r2)[:200]}")
    v = r2.get("verdict") if isinstance(r2.get("verdict"), dict) else {}   # the route answers {installed, verdict}
    return f"installed {h[:16]}: {v.get('state')} ({str(v.get('reason') or '')[:120]})"


# ── the dance ────────────────────────────────────────────────────────────────────────────────────

def completed_invitation_for(approver: Dict[str, Any], tok: str, peer_td: str) -> Optional[Dict[str, Any]]:
    st, r = http("GET", f"{base(approver)}/api/v1/admin/federation/frame-invitations?status=completed", headers=hdr(tok))
    items = (r.get("invitations") or r.get("items") or []) if isinstance(r, dict) else []
    for it in items:
        if isinstance(it, dict) and it.get("initiator_trust_domain") == peer_td:
            return it
    return None


def ensure_approved(approver: Dict[str, Any], tok: str, peer: Dict[str, Any], notes: str, *,
                    described_lic: Optional[Dict[str, Any]] = None, approver_lic: Optional[Dict[str, Any]] = None,
                    plan: str = "") -> Tuple[Optional[int], Optional[str], bool, Optional[Dict[str, Any]]]:
    """On `approver`, an invitation DESCRIBING `peer`, approved as approver's admin.
    Returns (peer_registry_id, plain licence key the approve issued to the peer or None, reused, the approve's
    `network_licence` block or None). §FEDLICENCE: the invitation carries the peer's licence facts, and the genesis
    issues an unlicensed peer its licence under `plan`."""
    ex = completed_invitation_for(approver, tok, peer["td"])
    if ex:
        pid = ex.get("peer_registry_id")
        if not pid:
            pid = peer_row(approver, tok, peer["td"], want_active=False).get("id")
        log(f"federate: [{approver['name']}] invitation describing {peer['name']} already completed (id {ex.get('id')}, peer row {pid}) — reused")
        return pid, None, True, None
    body = {"trust_domain": peer["td"], "bundle_endpoint_url": peer["bundle_url"], "federation_endpoint_url": peer["fed_url"],
            "event_store_url": peer["es_public_url"], "name": peer["name"], "contact_email": peer["admin_email"],
            "initiator_nonce": secrets.token_hex(16), **licence_invitation_fields(described_lic or {})}
    # §FINDINGS-A4 3d (2026-09-27): the route lets only a FEDERATION ADMIN name an internal bundle host (it refuses an
    # anonymous caller any address that is not globally routable, on every redirect hop); a same-host pair's bundle URL
    # is compose-internal, so the invitation goes in as the approver's admin. An older registry ignores the header.
    st, r = http("POST", f"{base(approver)}/api/v1/federation/frame-invitations", body, headers=hdr(tok))
    if st >= 300 or not isinstance(r, dict) or not r.get("id"):
        raise SystemExit(f"federate: [{approver['name']}] invitation describing {peer['name']} refused HTTP {st}: {str(r)[:200]}")
    inv = r["id"]
    st, r = http("POST", f"{base(approver)}/api/v1/admin/federation/frame-invitations/{inv}/approve",
                 {"notes": notes, **approve_licence_fields(approver_lic or {}, described_lic or {}, plan)},
                 headers=hdr(tok), timeout=240)
    if st >= 300 or not isinstance(r, dict):
        raise SystemExit(f"federate: [{approver['name']}] approve of {peer['name']} refused HTTP {st}: {str(r)[:200]}")
    log(f"federate: [{approver['name']}] approved {peer['name']}: status={r.get('status')} peer_row={r.get('peer_registry_id')} "
        f"relationship={'yes' if r.get('federation_relationship') else 'no'} licence_issued={'yes' if r.get('federation_license_key') else 'no'}")
    netlic = r.get("network_licence") if isinstance(r.get("network_licence"), dict) else None
    if netlic and (netlic.get("issued_hash") or netlic.get("error")):
        log(f"federate: [{approver['name']}] network licence for {peer['name']}: plan={netlic.get('plan')} "
            f"issued={str(netlic.get('issued_hash') or '-')[:16]} error={netlic.get('error') or '-'}")
    return r.get("peer_registry_id"), r.get("federation_license_key") or None, False, netlic


def resync_es(f: Dict[str, Any], tok: str, peer_id: int) -> Dict[str, Any]:
    st, r = http("POST", f"{base(f)}/api/v1/admin/federation/frames/{peer_id}/resync-eventstore", {}, headers=hdr(tok), timeout=120)
    log(f"federate: [{f['name']}] resync-eventstore peer {peer_id}: HTTP {st} sf4={r.get('sf4_registered') if isinstance(r, dict) else '?'}")
    return r if isinstance(r, dict) else {}


def peer_row(f: Dict[str, Any], tok: str, td: str, want_active: bool = True) -> Dict[str, Any]:
    st, r = http("GET", f"{base(f)}/api/v1/admin/federation/peers/all", headers=hdr(tok), timeout=60)
    items = (r.get("items") or []) if isinstance(r, dict) else (r if isinstance(r, list) else [])
    rows = [p for p in items if isinstance(p, dict) and p.get("trust_domain") == td and p.get("peer_type") == "frame"]
    if want_active:
        rows = [p for p in rows if str(p.get("status", "")).upper() == "ACTIVE"] or rows
    rows.sort(key=lambda p: (0 if str(p.get("base_url", "")).endswith(":8443") else 1, -(p.get("id") or 0)))
    return rows[0] if rows else {}


# ── host actions ─────────────────────────────────────────────────────────────────────────────────

def sh(cmd: List[str], timeout: int = 120) -> Tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def compose_recreate(f: Dict[str, Any], service_suffix: str) -> None:
    svc = f"{f['name']}-{service_suffix}"
    rc, out = sh(["docker", "compose", "-f", os.path.join(f["stack_dir"], "docker-compose.frame-test.yml"),
                  "--env-file", os.path.join(f["stack_dir"], ".env.frame-test"),
                  "up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", svc], timeout=900)
    if rc != 0:
        raise SystemExit(f"federate: recreate of {svc} failed rc={rc}: {out[-300:]}")


def wait(desc: str, fn, tries: int, sleep: float) -> bool:
    for i in range(tries):
        ok, detail = fn()
        if ok:
            log(f"federate: {desc}: OK ({detail})"); return True
        if i % 10 == 0:
            log(f"federate: {desc}: waiting ({detail})")
        time.sleep(sleep)
    log(f"federate: {desc}: TIMEOUT"); return False


def _code(url: str, timeout: int = 8) -> int:
    st, _ = http("GET", url, timeout=timeout); return st


def teg_health_probe(healthcheck_test) -> str:
    """The python the step runs INSIDE a TEG container to ask its /health, read from the container's OWN compose
    healthcheck. §NIGHTPROV (2026-09-27): a socket-only TEG (§MTLSHOPS T2 S4, `uvicorn --uds /sock/teg/teg.sock`) names
    its socket there (`curl --unix-socket <path>`) and listens on no TCP port, so the old probe (TCP 8080) was refused
    after every recreate and the step failed a healthy frame (nt260927x1b, "did not come back healthy" while docker
    called it healthy). A TEG born before T2 has no socket in its healthcheck and listens on TCP 8080. Pure."""
    test = [str(x) for x in (healthcheck_test or [])]
    sock = test[test.index("--unix-socket") + 1] if "--unix-socket" in test[:-1] else None
    if sock:
        return ("import socket;s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect(%r);"
                "s.sendall(b'GET /health HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n');"
                "print(s.recv(64).split()[1].decode())") % sock
    return "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5).status)"


def health_after_recreate(f: Dict[str, Any], suffix: str) -> None:
    if suffix == "event-store":
        ok = wait(f"{f['name']}-event-store health", lambda: (_code(f"http://127.0.0.1:{f['es_port']}/health") == 200, f"es:{f['es_port']}"), 60, 3)
    elif suffix == "teg":
        rc, out = sh(["docker", "inspect", f"{f['name']}-teg", "--format", "{{json .Config.Healthcheck}}"], timeout=30)
        try:
            hc = (json.loads(out) or {}).get("Test") if rc == 0 else None
        except ValueError:
            hc = None
        probe = teg_health_probe(hc)
        where = "teg:socket" if "AF_UNIX" in probe else "teg:8080"

        def teg():
            rc, out = sh(["docker", "exec", f"{f['name']}-teg", "python", "-c", probe], timeout=30)
            return (rc == 0 and out.strip().endswith("200"), where)
        ok = wait(f"{f['name']}-teg health", teg, 60, 5)
    else:
        ok = wait(f"{f['name']}-registry health", lambda: (_code(f"{base(f)}/health") == 200, f"registry:{f['registry_port']}"), 100, 3)
        if ok:
            for rail in ("agent-cards/discover?limit=1", "agent-cards/?limit=1", "public/registry-config", "federation/registries", "reputation-bond/config"):
                c = _code(f"{base(f)}/api/v1/{rail}", timeout=25)
                if c != 200:
                    raise SystemExit(f"federate: {f['name']} public rail /{rail} answered {c} after the recreate — refusing to call it live")
            log(f"federate: {f['name']} five public rails 200")
    if not ok:
        raise SystemExit(f"federate: {f['name']}-{suffix} did not come back healthy")


def proxy_roots(f: Dict[str, Any]) -> Dict[str, int]:
    out = {}
    for p in PROXIES:
        rc, o = sh(["docker", "exec", f"{f['name']}-{p}", "sh", "-c", 'grep -c "BEGIN CERT" /certs/bundle.0.pem'], timeout=30)
        try:
            out[f"{f['name']}-{p}"] = int(o.strip().splitlines()[-1]) if o.strip() else 0
        except ValueError:
            out[f"{f['name']}-{p}"] = 0
    return out


def reload_proxies(f: Dict[str, Any]) -> Dict[str, int]:
    """`nginx -s reload` in each proxy of `f`, {container: rc}. A proxy reads its client CA (/certs/bundle.0.pem) at start
    and at each reload only, and its own loop reloads every RELOAD_SEC (300 s), so a file that just gained the peer's root
    is not yet what it serves. Measured 2026-09-27 (§F6 stage 5): nt260927x4b's /fx/rates stayed unavailable through the
    whole 5-minute wait below, because nt260927x4a's nginx-teg answered "400 The SSL certificate error" to b's registry
    until its next scheduled reload; nt260927x5 passed only because that reload fell 61 s inside the wait, and x3 the same
    way. A failed reload is reported, never fatal: the sidecar's own loop still takes the file."""
    out = {}
    for p in PROXIES:
        rc, _o = sh(["docker", "exec", f"{f['name']}-{p}", "nginx", "-s", "reload"], timeout=30)
        out[f"{f['name']}-{p}"] = rc
    return out


# §MTLSHOPS T3 (2026-09-15): a TLS-only Redis (--port 0) keeps a unix socket inside its container for local tooling; the
# socket takes the same ACL users.
REDIS_SOCKET = "/run/redis/redis.sock"


def registry_redis_password(f: Dict[str, Any]) -> str:
    """The registry's Redis ACL password from the frame's env file (§MTLSHOPS G3); empty for a frame from an older template."""
    url = urllib.parse.urlparse(read_env(os.path.join(f["stack_dir"], ".env.frame-test")).get("FT_REG_REDIS_URL", ""))
    return (url.password or "") if url.username == "registry" else ""


def clear_parked_pulls(f: Dict[str, Any]) -> int:
    """Deletes the registry's parked card-pull keys (db 0). On a frame whose Redis takes ACL users (§MTLSHOPS G3) redis-cli
    authenticates as the registry with the password on stdin, never on a command line. A refusal raises: an
    unauthenticated scan answers NOPERM, which would otherwise read as nothing parked."""
    pw = registry_redis_password(f)
    # §MTLSHOPS T3: a frame whose Redis serves TLS only is asked over its socket; an older frame has none and keeps its port
    script = (f'if [ -S {REDIS_SOCKET} ]; then set -- -s {REDIS_SOCKET} "$@"; fi; '
              + ('read -r REDISCLI_AUTH; export REDISCLI_AUTH; exec redis-cli --no-auth-warning --user registry "$@"' if pw
                 else 'exec redis-cli "$@"'))

    def cli(*args: str) -> Tuple[int, str]:
        r = subprocess.run(["docker", "exec", "-i", f"{f['name']}-redis", "sh", "-c", script, "redis-cli", *args],
                           input=(pw + "\n") if pw else "", capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    rc, o = cli("--scan", "--pattern", "registry:federation:cardpull_*")
    if rc != 0 or any(w in o for w in ("NOPERM", "NOAUTH", "WRONGPASS")):
        raise SystemExit(f"federate: {f['name']}-redis refused the parked-pull scan (rc {rc}): {o.strip()[:120]}")
    keys = [k for k in o.split() if k.startswith("registry:federation:")]
    for k in keys:
        cli("del", k)
    return len(keys)


def spire(f: Dict[str, Any], *args: str) -> str:
    rc, o = sh(["docker", "exec", f"{f['name']}-spire-server", "/opt/spire/bin/spire-server", *args], timeout=60)
    return o


def host_pem_roots(pem: str) -> int:
    try:
        return open(pem).read().count("BEGIN CERTIFICATE")
    except OSError:
        return 0


def svid_verifies(f: Dict[str, Any], pem: str) -> bool:
    rc, svid = sh(["docker", "exec", f"{f['name']}-registry", "cat", "/certs/svid.0.pem"], timeout=30)
    if rc != 0 or "BEGIN CERTIFICATE" not in svid:
        return False
    r = subprocess.run(["openssl", "verify", "-CAfile", pem], input=svid, capture_output=True, text=True)
    return r.returncode == 0 and "OK" in r.stdout


def add_peer_ledger_lane(name: str, peer_name: str, peer_es_port: int, *, log_fn=log) -> bool:
    """The console vhost must proxy `/ws/events-<peer>` to the peer's EventStore, or the ledger tile the
    FRESH_NETWORK_JSON entry promises renders EMPTY (a `ws_path` is same-origin; runbook §10.3b, §FRAMELIC's
    "always the allow same origin problem"). The SECOND frame renders the lane at birth (--peer-ledger is
    derived from --federate-with); the FIRST frame was rendered before the peer existed, so the lane is
    inserted into its rendered vhost here, before the last `location / {` of the file. Idempotent."""
    path = os.path.join(extras.NGINX_AVAIL, f"{name}-theprotocol")
    if not os.path.exists(path):
        log_fn(f"federate: {name} has no rendered console vhost (--render-vhosts unset) — no ledger lane to add")
        return False
    s = open(path).read()
    if f"location /ws/events-{peer_name} " in s:
        return False
    block = extras._peer_ledger_block({peer_name: int(peer_es_port)})
    idx = s.rfind("\n    location / {")
    if idx < 0:
        log_fn(f"federate: {path} has no `location / {{` anchor — ledger lane for {peer_name} NOT added"); return False
    extras._bak(path, f"lane-{peer_name}")
    open(path, "w").write(s[:idx + 1] + block + s[idx + 1:])
    rc = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if rc.returncode != 0:
        raise SystemExit(f"federate: nginx -t failed after adding /ws/events-{peer_name} to {path}: {rc.stderr[-300:]}")
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    log_fn(f"federate: console vhost {name}-theprotocol now proxies /ws/events-{peer_name} → 127.0.0.1:{peer_es_port}")
    return True


# ── the step ─────────────────────────────────────────────────────────────────────────────────────

def verify_layers(me: Dict[str, Any], tok: str, peer: Dict[str, Any]) -> Dict[str, Any]:
    row = peer_row(me, tok, peer["td"])
    fed = spire(me, "federation", "list"); bl = spire(me, "bundle", "list")
    ent = spire(me, "entry", "show", "-spiffeID", f"spiffe://{me['td']}/service/{me['name']}-registry")
    st, sa = http("GET", f"http://127.0.0.1:{me['es_port']}/api/v1/projections/supply-audit", timeout=30)
    delta = (sa.get("delta"), sa.get("status")) if isinstance(sa, dict) else (None, f"HTTP {st}")
    return {
        "peer_row": bool(row) and row.get("hop_distance") == 1 and str(row.get("base_url", "")).endswith(":8443"),
        "peer_row_detail": {k: row.get(k) for k in ("id", "name", "status", "base_url", "hop_distance")},
        "federation_list": peer["td"] in fed, "bundle_list": peer["td"] in bl,
        "entry_federates_with": ("FederatesWith" in ent and peer["td"] in ent),
        # the admin peers rail carries no card body; the card sync stamps `last_synced_at` on every OK
        # (measured: the row gained it the minute `[RegistryCardSync] peer=… OK` was logged)
        "cached_card": bool(row.get("last_synced_at") or row.get("cached_registry_card")) if row else False,
        "delta": delta,
    }


def run(args, ctx, meta, ports: Dict[str, int], log_fn=None) -> Dict[str, Any]:
    """Called by the driver at the `federate` step, on the frame the driver is standing up (`me`)."""
    _log = log_fn or log
    me = frame_facts(ctx.stack_dir_host)
    me["registry_port"] = ports.get("registry", me["registry_port"]); me["es_port"] = ports.get("es", me["es_port"])
    record: Dict[str, Any] = {"frame": me["name"], "peers": {}, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    anchor_ccy = (getattr(args, "fx_anchor", "") or "").upper()
    for peer_dir in args.federate_with:
        peer = frame_facts(peer_dir)
        _log(f"federate: {me['name']} ({me['td']}) with {peer['name']} ({peer['td']}) from {peer_dir}")
        # 0. preconditions — against the federated client-CA file OF THIS PAIR'S IDENTITY NET (one per net,
        # sidecars.federated_bundle_for_net), never the production pair's file
        pem = extras.FEDERATED_BUNDLE_PEM
        try:
            _sc_spec = _ilu.spec_from_file_location("sidecars", os.path.join(_HERE, "sidecars.py"))
            _sc = _ilu.module_from_spec(_sc_spec); _sc_spec.loader.exec_module(_sc)   # type: ignore[union-attr]
            if me.get("identity_net"):
                pem = _sc.federated_bundle_for_net(_sc.load(), me["identity_net"])[1]
        except SystemExit:
            _log("federate: no sidecar manifest — the precondition reads the default federated bundle")
        _log(f"federate: client-CA file for net {me.get('identity_net') or '(none)'}: {pem} ({host_pem_roots(pem)} root(s))")
        problems = classify_preconditions(me, peer, peer_health=_code(f"{base(peer)}/health"),
                                          my_svid_verifies=svid_verifies(me, pem), federated_pem_roots=host_pem_roots(pem))
        if problems:
            for p in problems:
                _log(f"federate: REFUSED — {p}")
            raise SystemExit(2)
        my_tok, peer_tok = login(me), login(peer)
        # 1. the dance, both directions, then resync both
        # §FEDLICENCE: each invitation carries the described frame's licence facts; the genesis issues an unlicensed
        # frame its licence (--federate-licence-plan), and admits it FIRST, so the frame holds its licence before it
        # approves the genesis; a licence the callback did not deliver is installed here.
        plan = (getattr(args, "federate_licence_plan", "") or "").strip().lower()
        my_lic, peer_lic = licence_facts(me), licence_facts(peer)
        if my_lic or peer_lic:
            _log(f"federate: licences: {me['name']} {my_lic.get('state') or '-'}, {peer['name']} {peer_lic.get('state') or '-'}"
                 f"{', plan ' + plan if plan else ''}")

        def _me_approves():
            out = ensure_approved(me, my_tok, peer, f"§ONESHOT federate {me['name']}<->{peer['name']}",
                                  described_lic=peer_lic, approver_lic=my_lic, plan=plan)
            done = install_issued_licence(me, peer, peer_tok, out[3])
            if done:
                _log(f"federate: [{peer['name']}] network licence {done}")
            return out

        def _peer_approves():
            out = ensure_approved(peer, peer_tok, me, f"§ONESHOT federate {peer['name']}<->{me['name']}",
                                  described_lic=my_lic, approver_lic=peer_lic, plan=plan)
            done = install_issued_licence(peer, me, my_tok, out[3])
            if done:
                _log(f"federate: [{me['name']}] network licence {done}")
            return out

        if genesis_first(my_lic, peer_lic):
            pid_on_peer, key_for_me, reused_b, _ = _peer_approves()
            pid_on_me, key_for_peer, reused_a, _ = _me_approves()
        else:
            pid_on_me, key_for_peer, reused_a, _ = _me_approves()
            pid_on_peer, key_for_me, reused_b, _ = _peer_approves()
        if pid_on_me: resync_es(me, my_tok, pid_on_me)
        if pid_on_peer: resync_es(peer, peer_tok, pid_on_peer)
        # 2. the licences the callback never delivers
        if key_for_peer and not peer["has_license"]:
            seed_license(peer, key_for_peer, issuer=me["name"]); peer["has_license"] = True
        if key_for_me and not me["has_license"]:
            seed_license(me, key_for_me, issuer=peer["name"]); me["has_license"] = True
        # 3. the post-approve env on both, baks first
        changed: Dict[str, List[str]] = {}
        for f, other in ((me, peer), (peer, me)):
            envp = os.path.join(f["stack_dir"], ".env.frame-test")
            bak = f"{envp}.bak-pre-federate-{other['name']}"
            if not os.path.exists(bak):
                subprocess.run(["cp", "-a", envp, bak], check=True)
            txt = open(envp).read()
            txt, keys = post_approve_env(txt, other)
            if keys:
                open(envp, "w").write(txt)
            changed[f["name"]] = keys
            if not other.get("router_did", "").startswith("did:"):
                _log(f"federate: {other['name']} has no @fx_router DID in its env — {f['name']} gets no FX keys for it (no route to nobody)")
            _log(f"federate: [{f['name']}] env keys changed for {other['name']}: {keys or 'none (already there)'}")
            # read-back: the merge that matched nothing is the class this driver keeps paying for
            back = open(envp).read()
            for k in ("FT_ES_CROSS_FRAME_PEERS", "FT_ES_KNOWN_INTERNAL_SERVICES", "FT_TRUSTED_SPIFFE_DOMAINS"):
                v = env_get(back, k) or ""
                needle = {"FT_ES_CROSS_FRAME_PEERS": other["td"] + "|", "FT_ES_KNOWN_INTERNAL_SERVICES": f"{other['name']}-registry",
                          "FT_TRUSTED_SPIFFE_DOMAINS": other["td"]}[k]
                if needle not in v:
                    raise SystemExit(f"federate: [{f['name']}] {k} does not carry {needle!r} after the merge — refusing")
        # 3b. the same-origin ledger lane on BOTH consoles (the first frame's vhost predates the peer)
        for f, other in ((me, peer), (peer, me)):
            if other.get("es_port"):
                add_peer_ledger_lane(f["name"], other["name"], other["es_port"], log_fn=_log)
        # 4. recreate --no-deps, both frames, ES then TEG then registry
        for f in (me, peer):
            for suffix in RECREATE_ORDER:
                compose_recreate(f, suffix); health_after_recreate(f, suffix)
        # 5. two roots on the four proxies (each frame's federation + teg proxies), else clear the parked keys
        want = 2
        deadline = time.time() + 420; cleared = False
        while True:
            roots = {}; roots.update(proxy_roots(me)); roots.update(proxy_roots(peer))
            if all(v >= want for v in roots.values()):
                _log(f"federate: proxies at {want}+ roots: {roots}")
                rel = {}; rel.update(reload_proxies(me)); rel.update(reload_proxies(peer))
                _log(f"federate: proxies reloaded, so they serve both roots now rather than at their next scheduled "
                     f"reload (rc per proxy): {rel}")
                break
            if time.time() > deadline:
                n = clear_parked_pulls(me) + clear_parked_pulls(peer)
                _log(f"federate: proxies still at {roots} after 420 s — cleared {n} parked pull key(s); continuing")
                cleared = True; break
            time.sleep(10)
        # 6. keepers on both, then the rates
        anchor = ""
        if peer.get("router_did", "").startswith("did:") and me.get("router_did", "").startswith("did:"):
            anchor = anchor_ccy or peer["ticker"]   # the peer stood first: it is the anchor unless --fx-anchor says otherwise
            for f, tok in ((me, my_tok), (peer, peer_tok)):
                st, r = http("PUT", f"{base(f)}/api/v1/teg/fx/reserve-keeper", keeper_body(f["ticker"], anchor), headers=hdr(tok), timeout=60)
                _log(f"federate: [{f['name']}] reserve keeper PUT (anchor {anchor}): HTTP {st}")
                if st >= 300:
                    raise SystemExit(f"federate: keeper PUT on {f['name']} refused HTTP {st}: {str(r)[:160]}")
            def rates(f):
                st, r = http("GET", f"{base(f)}/api/v1/teg/fx/rates", timeout=30)
                ok = isinstance(r, dict) and bool(r.get("available"))
                return ok, f"{f['name']} available={r.get('available') if isinstance(r, dict) else st} pairs={len(r.get('pairs') or []) if isinstance(r, dict) else 0}"
            for f in (me, peer):
                if not wait(f"{f['name']} /fx/rates", lambda f=f: rates(f), 30, 10):
                    raise SystemExit(f"federate: {f['name']} never answered /fx/rates available:true")
        else:
            _log("federate: FX pool not armed (a router DID is missing on one side) — the pair federates without FX")
        # 7. verify the three layers on both sides
        vm, vp = verify_layers(me, my_tok, peer), verify_layers(peer, peer_tok, me)
        for who, v in ((me["name"], vm), (peer["name"], vp)):
            _log(f"federate: [{who}] peer_row={v['peer_row']} {v['peer_row_detail']} federation_list={v['federation_list']} "
                 f"bundle_list={v['bundle_list']} entry_federates_with={v['entry_federates_with']} cached_card={v['cached_card']} delta={v['delta']}")
        missing = [f"{who}:{k}" for who, v in ((me["name"], vm), (peer["name"], vp))
                   for k in ("peer_row", "federation_list", "bundle_list", "entry_federates_with") if not v[k]]
        for who, v in ((me["name"], vm), (peer["name"], vp)):
            d = v["delta"]
            if not (d and str(d[1]).upper() == "OK" and float(d[0] or 0) == 0.0):
                missing.append(f"{who}:delta={d}")
        if missing:
            raise SystemExit(f"federate: the pair is NOT federated — missing: {missing}")
        # the cached card arrives with the next sync cycle; wait for it, it is what discovery renders from
        def cards():
            a = verify_layers(me, my_tok, peer)["cached_card"]; b = verify_layers(peer, peer_tok, me)["cached_card"]
            return (a and b, f"{me['name']}:{a} {peer['name']}:{b}")
        wait("cached registry cards both ways", cards, 24, 15)
        record["peers"][peer["name"]] = {"td": peer["td"], "stack_dir": peer["stack_dir"], "peer_row_on_me": pid_on_me,
                                         "peer_row_on_peer": pid_on_peer, "reused": [reused_a, reused_b],
                                         "env_changed": changed, "parked_keys_cleared": cleared,
                                         "fx_anchor": anchor or None, "verified": {me["name"]: vm, peer["name"]: vp}}
        # 8. the record, on both stacks
        for f in (me, peer):
            p = os.path.join(f["stack_dir"], "federation.json")
            cur = json.load(open(p)) if os.path.exists(p) else {"frame": f["name"], "peers": {}}
            other = peer if f is me else me
            cur["peers"][other["name"]] = {"td": other["td"], "stack_dir": other["stack_dir"], "at": record["at"],
                                           "fx_anchor": anchor or None}
            open(p, "w").write(json.dumps(cur, indent=1))
        _log(f"federate: {me['name']} <-> {peer['name']} FEDERATED (three layers both sides, Δ=0 both ledgers)")
    return record
