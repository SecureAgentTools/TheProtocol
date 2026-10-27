#!/usr/bin/env python3
"""Run the market simulation on your frame: a trading roster born through the frame's own rails, the AGORA market
modes (a bounded run or a live one), and a verdict that counts what actually happened.

  ./frame-sim.py onboard --name <frame> [--name <peer> ...]          the roster, two listings per frame, launch positions,
                                                                      a market maker per listing, the cards listed
  ./frame-sim.py run <mode> --name <frame> [--name <peer> ...]       one bounded run and its verdict
        modes: market | dynamic | clerks | xreg | director | all   (xreg needs two frames: 100 % foreign orders)
  ./frame-sim.py live start|stop|status --name <frame> [...]         the continuous run, with a watchdog that stops it
  ./frame-sim.py verdict --name <frame> [...]                        the last run's verdict again (exit 0 only if real)

A frame is named in one of two ways:
  --name <frame>        a frame stood up with this kit (frame-up.py): its frame-up.json and its admin login under
                        --stack-root (default /opt/theprotocol/stack, or FRAME_STACK_ROOT)
  --frame registry=http://127.0.0.1:<port>,es=http://127.0.0.1:<port>,admin=<admin.secret.json>[,key=<slug>][,container=<registry container>]
                        any other frame; the admin file holds {"admin_email", "admin_password"}
Everything the simulation engine (scripts/sim_eigentrust.py) needs is derived from each frame's OWN answers: its name and
currency (/api/v1/public/registry-config), its ports, its admin. Nothing in here names another network.

Onboarding runs under the frame's purpose-named service accounts, never the admin: svc-sim owns the roster and its
funding, svc-market owns the listings and their market makers. A kit frame's standup already created them
(<secrets>/.<frame>_service_accounts.secret.json) and they are reused; elsewhere they are created here (with a single-use
invite code when the frame requires one). The admin only funds from the treasury and approves the listings.

What a run is judged by (a clean log over zero trades is not a pass): the engine's own cycle lines succeeded more than
they failed, the frames' listings printed NEW trades on their public tape during the run, an xreg run's trades carry a
party homed on another frame (a DID names its home: did:theprotocol:<issuer>:<id>), and every frame's supply delta read
0.0 before and after. Exit 0 only when all of them hold.

State (logins, the roster, logs, verdicts) goes to --state-dir (default <stack-root>/frame-sim-<frames>), mode 600 for
every secret file. The engine runs inside the frame's own registry image on the host network; nothing is installed.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
ENGINE = os.path.join(EXPORT_ROOT, "scripts", "sim_eigentrust.py")
SDK_SRC = os.path.join(EXPORT_ROOT, "theprotocol-sdk", "src")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(EXPORT_ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


frame_names = _load("frame_names", os.path.join("scripts", "hetzner_demo", "frame_names.py"))

N_DEFAULT = 8
POSITION_QTY = 100
FUND_AMOUNT = 1000.0
FUNDER_AMOUNT = 2000.0
LETTERS = "LTUVWXYZPQRS"   # the engine's frame letters; A, B and C are its production defaults, never reused here
NAMES = ["Alder", "Birch", "Cedar", "Dune", "Elm", "Fern", "Gale", "Heath", "Isle", "Juniper", "Kestrel", "Lark",
         "Moss", "Nettle", "Oak", "Pine", "Quartz", "Rowan", "Sage", "Thistle", "Umber", "Vale", "Willow", "Yarrow"]
T0 = time.time()


def log(msg):
    print(f"[frame-sim +{time.time() - T0:6.1f}s] {msg}", flush=True)


def die(msg, code=2):
    log(msg)
    sys.exit(code)


def http(method, url, body=None, headers=None, form=False, timeout=90):
    data, h = None, dict(headers or {})
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else {})
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try:
            return e.code, json.loads(t)
        except ValueError:
            return e.code, {"raw": t[:200]}
    except Exception as e:  # noqa: BLE001
        return 0, {"raw": f"{type(e).__name__}: {e}"[:200]}


def save(path, obj):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def dev_login(base, email, pw):
    st, r = http("POST", base + "/api/v1/auth/login", {"username": email, "password": pw}, form=True)
    return (r.get("access_token") if st == 200 and isinstance(r, dict) else None), st


def agent_login(base, cid, secret):
    st, r = http("POST", base + "/api/v1/auth/agent/token", {"username": cid, "password": secret}, form=True)
    return (r.get("access_token") if st == 200 and isinstance(r, dict) else None), st


# ── the network: every frame's facts, derived ─────────────────────────────────────────────────────────────────────
def parse_frame_spec(spec):
    out = {}
    for part in spec.split(","):
        k, _, v = part.partition("=")
        if not v:
            die(f"--frame: '{part}' is not key=value")
        out[k.strip()] = v.strip()
    for k in ("registry", "es", "admin"):
        if k not in out:
            die(f"--frame needs {k}=")
    return out


def port_of(url):
    p = urllib.parse.urlparse(url)
    return p.port or (443 if p.scheme == "https" else 80)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def resolve_frames(a):
    frames = []
    for name in a.name or []:
        dirs = frame_names.stack_dirs(a.stack_root, name, need_file="frame-up.json")
        if not dirs:
            die(f"no frame named {name} under {a.stack_root} (frame-up.json); name another one with --frame")
        rec = json.load(open(os.path.join(a.stack_root, dirs[-1], "frame-up.json")))
        ports = rec.get("ports") or {}
        sec_dir = rec.get("secrets_dir") or os.path.join(a.stack_root, f"{name}-secrets")
        frames.append({"key": name, "registry": f"http://127.0.0.1:{ports.get('registry')}",
                       "es": f"http://127.0.0.1:{ports.get('es')}",
                       "admin_file": os.path.join(sec_dir, f".{name}_frame_admin.secret.json"),
                       "services_file": os.path.join(sec_dir, f".{name}_service_accounts.secret.json"),
                       "container": f"{name}-registry"})
    for spec in a.frame or []:
        f = parse_frame_spec(spec)
        frames.append({"key": f.get("key"), "registry": f["registry"].rstrip("/"), "es": f["es"].rstrip("/"),
                       "admin_file": f["admin"], "services_file": f.get("services"), "container": f.get("container")})
    if not frames:
        die("name at least one frame: --name <frame> or --frame registry=...,es=...,admin=...")
    for i, f in enumerate(frames):
        st, cfg = http("GET", f["registry"] + "/api/v1/public/registry-config", timeout=30)
        if st != 200 or not isinstance(cfg, dict):
            die(f"{f['registry']}: /api/v1/public/registry-config answered {st}")
        f["name"] = cfg.get("registry_name") or f["key"] or f"frame-{i + 1}"
        f["currency"] = cfg.get("local_currency") or ""
        f["key"] = f["key"] or slugify(f["name"])
        f["port"] = port_of(f["registry"])
        f["es_port"] = port_of(f["es"])
        f["letter"] = LETTERS[i]
        adm = load(f["admin_file"], None)
        if not adm or not adm.get("admin_email") or not adm.get("admin_password"):
            die(f"{f['key']}: the admin login is not readable at {f['admin_file']} (admin_email, admin_password)")
        if not f["currency"]:
            die(f"{f['key']}: the frame names no currency (local_currency)")
        f["agora"] = agora_prefix(f)
    keys = [f["key"] for f in frames]
    if len(set(keys)) != len(keys):
        die(f"two frames share a key: {keys}")
    return frames


AGORA_PREFIX, LEGACY_PREFIX = "/api/v1/agora", "/api/v1/exchange"


def agora_prefix(f):
    """The AGORA market's prefix on this frame: /api/v1/agora (every registry since V0419), else the older /api/v1/exchange
    when this frame's router does not know the new route at all (a bare 404 "Not Found"; an unknown listing is not that)."""
    st, r = http("GET", f["registry"] + AGORA_PREFIX + "/listings", timeout=30)
    if st == 404 and isinstance(r, dict) and (r.get("detail") in (None, "Not Found")):
        return LEGACY_PREFIX
    return AGORA_PREFIX


def launch_path(f):
    return "launch/buy" if f["agora"] == AGORA_PREFIX else "ipo/buy"


def state_dir(a, frames):
    d = a.state_dir or os.path.join(a.stack_root, "frame-sim-" + "-".join(f["key"] for f in frames))
    os.makedirs(os.path.join(d, "runs"), exist_ok=True)
    os.chmod(d, 0o700)
    return d


def admin_login(f):
    adm = load(f["admin_file"], {})
    tok, st = dev_login(f["registry"], adm["admin_email"], adm["admin_password"])
    if not tok:
        die(f"{f['key']}: the admin login answered {st}")
    return bearer(tok)


def delta(f):
    st, d = http("GET", f["es"] + "/api/v1/projections/supply-audit", timeout=30)
    if st != 200 or not isinstance(d, dict):
        return f"unreadable ({st})"
    return f"{d.get('delta')} {d.get('status')}"


def delta_ok(s):
    return s.split(" ")[:2] in (["0.0", "OK"], ["0", "OK"])


# ── onboarding ──────────────────────────────────────────────────────────────────────────────────────────────────
def symbols_for(f):
    """Two listing symbols from the frame's own name: its initials (2 to 3 letters) + W and L."""
    words = re.findall(r"[A-Za-z0-9]+", f["name"]) or [f["key"]]
    base = "".join(w[0] for w in words).upper()[:3]
    if len(base) < 2:
        base = (re.sub(r"[^A-Z0-9]", "", f["name"].upper()) + "XX")[:3]
    return [base + "W", base + "L"]


def listings(f):
    st, r = http("GET", f["registry"] + f["agora"] + "/listings", timeout=30)
    return r if isinstance(r, list) else ((r or {}).get("listings") or [])


def services(f, sd):
    """svc-sim and svc-market for this frame: the standup's own, else ours (created once, kept in the state dir)."""
    base = f["registry"]
    std = load(f.get("services_file") or "", {}) if f.get("services_file") else {}
    have = {n: std[n] for n in ("svc-sim", "svc-market") if isinstance(std.get(n), dict)}
    ours_path = os.path.join(sd, ".service_accounts.secret.json")
    ours = load(ours_path, {})
    for n in ("svc-sim", "svc-market"):
        if n in have and dev_login(base, have[n]["email"], have[n]["password"])[0]:
            continue
        a = ours.get(f["key"], {}).get(n)
        if a and dev_login(base, a["email"], a["password"])[0]:
            have[n] = a
    missing = [n for n in ("svc-sim", "svc-market") if n not in have]
    if missing:
        extras = _load("standup_extras", os.path.join("scripts", "hetzner_demo", "standup_extras.py"))
        adm = admin_login(f)
        codes = None
        st, rc = http("GET", base + "/api/v1/auth/registration-config")
        if st == 200 and isinstance(rc, dict) and rc.get("beta_invite_required"):
            sg, rg = http("POST", base + "/api/v1/admin/invite-codes/generate",
                          {"count": len(missing), "max_uses": 1, "expires_days": 1, "note": "frame-sim service accounts"}, adm)
            got = [c.get("code") for c in ((rg or {}).get("codes") or []) if c.get("code")] if sg in (200, 201) else []
            if len(got) < len(missing):
                die(f"{f['key']}: the frame requires an invite code and issued {len(got)} of {len(missing)} (status {sg})")
            codes = dict(zip(missing, got))
        # a suffix of our own, so a frame that already has svc-sim from another tool keeps it untouched
        made = extras.create_service_accounts(base, adm, f"{f['key']}-fsim", only=missing, invite_codes=codes)
        ours.setdefault(f["key"], {}).update(made)
        save(ours_path, ours)
        for n in missing:
            a = made.get(n)
            if not (a and dev_login(base, a["email"], a["password"])[0]):
                die(f"{f['key']}: {n} was not created or cannot log in")
            have[n] = a
            log(f"[{f['key']}] {n}: created (developer {a.get('developer_id')})")
    return have


def svc_bearer(f, have, n):
    tok, st = dev_login(f["registry"], have[n]["email"], have[n]["password"])
    if not tok:
        die(f"{f['key']}: {n} login answered {st}")
    return bearer(tok)


def mint(f, svc_hdr, hri, name, desc, tags):
    base = f["registry"]
    st, r = http("POST", base + "/api/v1/onboard/bootstrap/request-token", {"agent_type_hint": "service"}, svc_hdr)
    bt = (r or {}).get("bootstrap_token") if isinstance(r, dict) else None
    if not bt:
        return None, f"bootstrap {st}"
    host = urllib.parse.urlparse(base).netloc
    card = {"schemaVersion": "1.0", "humanReadableId": hri, "agentVersion": "1.0.0", "name": name, "description": desc,
            "url": f"http://{host}/agents/{hri.split('/')[-1]}/a2a",
            "provider": {"name": "frame-sim", "url": f"http://{host}"},
            "capabilities": {"a2aVersion": "1.0"}, "authSchemes": [{"scheme": "none"}],
            "skills": [{"id": "sim-trader", "name": "Market simulation trader", "description": "Trades in the AGORA market simulation", "tags": ["sim"]}],
            "tags": tags}
    st, r = http("POST", base + "/api/v1/onboard/create_agent", {"agent_did_method": "theprotocol", "agent_card": card},
                 {"Bootstrap-Token": bt})
    if st not in (200, 201) or not isinstance(r, dict) or not r.get("agent_did"):
        return None, f"create_agent {st} {str(r)[:120]}"
    return {"did": r["agent_did"], "client_id": r["client_id"], "client_secret": r["client_secret"]}, None


def balance(f, hdr, did):
    st, b = http("POST", f["registry"] + "/api/v1/developers/me/agents/balances", {"agent_dids": [did]}, hdr)
    try:
        return float(((b or {}).get("balances", {}).get(did, {}) or {}).get("balance") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def fund_to(f, owner_hdr, adm_hdr, did, target, ref):
    need = target - balance(f, owner_hdr, did)
    if need <= 0.5:
        return "ok(already)"
    body = {"target_agent_did": did, "amount": f"{need:.6f}", "reason": "admin_grant", "reference_id": ref}
    st, r = http("POST", f["registry"] + "/api/v1/teg/treasury/fund-agent", body, {**adm_hdr, "Idempotency-Key": ref})
    return "ok" if st in (200, 201) else f"{st} {str((r or {}).get('detail') or r)[:100]}"


def bond(f, owner_hdr, did):
    base = f["registry"]
    st, r = http("GET", base + f"/api/v1/developers/me/agents/{did}/reputation-bond", headers=owner_hdr)
    b = (r or {}).get("bond") if isinstance(r, dict) else None
    status = (b.get("status") if isinstance(b, dict) else (r or {}).get("status")) if st == 200 else None
    if status in ("locked", "matured", "active"):
        return "ok(already)"
    st, r = http("POST", base + f"/api/v1/developers/me/agents/{did}/reputation-bond", {"funder_did": did}, owner_hdr, timeout=120)
    return "ok" if st in (200, 201) else f"{st} {str((r or {}).get('detail') or r)[:120]}"


def onboard(a, frames, sd):
    roster_path = os.path.join(sd, ".roster.secret.json")
    seed_path = os.path.join(sd, ".seed.secret.json")
    roster, seed = load(roster_path, {}), load(seed_path, {})
    rc = 0
    for fi, f in enumerate(frames):
        base, k = f["registry"], f["key"]
        have = services(f, sd)
        SIM, MKT, ADM = svc_bearer(f, have, "svc-sim"), svc_bearer(f, have, "svc-market"), admin_login(f)
        # the roster
        agents = roster.get(k, [])
        created = funded = bonded = 0
        for i in range(1, a.agents + 1):
            hri = f"{k}/fsim-{i:02d}"
            e = next((x for x in agents if x.get("hri") == hri), None)
            if not e:
                nm = f"{NAMES[(fi * a.agents + i - 1) % len(NAMES)]} {i:02d}"
                rec, err = mint(f, SIM, hri, nm, f"Market simulation trader on {f['name']} (frame-sim)", ["sim", k])
                if err:
                    log(f"[{k}] {hri}: {err}"); rc = 1; continue
                e = {**rec, "name": nm, "registry_url": base, "hri": hri}
                agents.append(e); roster[k] = agents; save(roster_path, roster); created += 1   # persisted before it is used
            # Funded ONCE: the bond takes a quarter of the grant straight after, and a trader that spent its money is the
            # market working. A second onboard used to "top up" the bond back under the first run's idempotency key and
            # got 422 for every trader (measured on the sandbox pair's re-run, 2026-09-22).
            if e.get("funded"):
                r1 = "ok(already)"
            else:
                r1 = fund_to(f, SIM, ADM, e["did"], FUND_AMOUNT, f"frame-sim-roster-{k}-{i:02d}")
            r2 = bond(f, SIM, e["did"])
            if r1.startswith("ok") and not e.get("funded"):
                e["funded"] = True; save(roster_path, roster)
            funded += r1.startswith("ok")
            bonded += r2.startswith("ok")
            if not (r1.startswith("ok") and r2.startswith("ok")):
                log(f"[{k}] {hri}: fund {r1} · bond {r2}"); rc = 1
        roster[k] = agents
        log(f"[{k}] roster {len(agents)} agents: created {created}, funded {funded}, bonded {bonded}")
        # two listings, owned by svc-market, approved by the admin
        syms = seed.get(f"{k}:symbols") or symbols_for(f)
        seed[f"{k}:symbols"] = syms
        for sym in syms:
            hit = next((x for x in listings(f) if (x.get("symbol") or "").upper() == sym), None)
            key = f"{k}:{sym}"
            fund = seed.get(key)
            if hit and not fund:
                die(f"[{k}] {sym} is already listed on this frame by someone else: pick other symbols (--symbols)")
            if hit and hit.get("status") in ("ipo", "trading"):
                log(f"[{k}] {sym} present ({hit.get('status')})"); continue
            orgname = f"{sym} market simulation ({f['name']})"
            if not fund:
                st, r = http("POST", base + "/api/v1/organizations", {"name": orgname, "description": "frame-sim listing", "settings": {}}, MKT)
                if st not in (200, 201):
                    die(f"[{k}] {sym}: organization {st} {str(r)[:160]}")
                rec, err = mint(f, MKT, f"{k}/{sym.lower()}-funder", f"{sym} listing funder", f"Pays the {sym} listing fee (frame-sim)", ["system", k])
                if err:
                    die(f"[{k}] {sym} funder: {err}")
                fund = {**rec, "org_id": str(r["id"])}
                seed[key] = fund; save(seed_path, seed)
            log(f"[{k}] {sym} funder: fund {fund_to(f, MKT, ADM, fund['did'], FUNDER_AMOUNT, f'frame-sim-seed-{k}-{sym}')} · bond {bond(f, MKT, fund['did'])}")
            if not hit:
                body = {"organization_id": fund["org_id"], "symbol": sym, "total_shares": 1_000_000, "ipo_float": 200_000,
                        "ipo_price": "1.000000", "funding_agent_did": fund["did"], "display_name": orgname}
                st, r = http("POST", base + f["agora"] + "/listings", body, {**MKT, "Idempotency-Key": f"frame-sim-list-{k}-{sym}"}, timeout=120)
                if st not in (200, 201):
                    die(f"[{k}] {sym}: listing {st} {str(r)[:200]}")
                ref = r.get("id") or r.get("listing_id") or sym
            else:
                ref = hit.get("id") or sym
            st, r = http("POST", base + f"{f['agora']}/admin/listings/{ref}/approve", {}, ADM, timeout=120)
            now = next((x for x in listings(f) if (x.get("symbol") or "").upper() == sym), None)
            log(f"[{k}] {sym}: approve {st} -> {now.get('status') if now else None}")
        save(seed_path, seed)
        # launch positions: every trader holds some of each home listing, or nothing ever fills
        bought = held = failed = 0
        for e in agents:
            if all(sym in (e.get("positions") or []) for sym in syms):
                held += len(syms); continue      # seeded once; what a trader sold since is the market, not a gap
            tok, st = agent_login(base, e["client_id"], e["client_secret"])
            if not tok:
                failed += 1; continue
            st, pf = http("GET", base + f["agora"] + "/portfolio", headers=bearer(tok))
            pos = {}
            for p in ((pf.get("positions") or pf.get("holdings") or []) if isinstance(pf, dict) else []):
                pos[(p.get("symbol") or "").upper()] = float(p.get("shares") or p.get("qty") or 0)
            for sym in syms:
                if pos.get(sym, 0) >= POSITION_QTY:
                    held += 1
                    if sym not in (e.get("positions") or []):
                        e.setdefault("positions", []).append(sym)
                    continue
                st, r = http("POST", base + f"{f['agora']}/listings/{sym}/{launch_path(f)}", {"qty": POSITION_QTY},
                             {**bearer(tok), "Idempotency-Key": f"frame-sim-pos-{e['did'][-12:]}-{sym}"})
                if st == 200:
                    bought += 1
                    e.setdefault("positions", []).append(sym)
                else:
                    failed += 1
                    log(f"[{k}] {e['hri']} launch buy {sym}: {st} {str((r or {}).get('detail') or r)[:140]}")
        save(roster_path, roster)
        log(f"[{k}] launch positions: bought {bought}, already held {held}, failed {failed}")
        rc = rc or (1 if failed else 0)
        # a market maker per listing (quotes only where the frame runs TREASURY_MM_ENABLED)
        for sym in syms:
            org = (seed.get(f"{k}:{sym}") or {}).get("org_id")
            body = {"enabled": True, "spread_bps": 300, "quote_qty": 40, "reserve_shares": 600000, "ref_mode": "last"}
            st, r = http("PUT", base + f"{f['agora']}/organizations/{org}/treasury/{sym}/mm", body, MKT)
            log(f"[{k}] {sym} market maker: {st}")
        # the cards must federate: a service account's agents are born unlisted, and unlisted also leaves the export
        listed = 0
        for e in agents:
            st, c = http("GET", base + f"/api/v1/agent-cards/{e['did']}", headers=SIM)
            if st == 200 and c.get("unlisted"):
                st, r = http("PATCH", base + f"/api/v1/agent-cards/{c.get('id') or e['did']}/listing", {"unlisted": False}, SIM)
                listed += st == 200
        log(f"[{k}] roster cards listed: {listed} (the rest already were)")
    # the engine's login for venue reads and clerk grants: each frame's admin, by port
    by_port = {}
    for f in frames:
        adm = load(f["admin_file"], {})
        by_port[str(f["port"])] = {"username": adm["admin_email"], "password": adm["admin_password"]}
    first = load(frames[0]["admin_file"], {})
    roster["_overview_login"] = {"email": first["admin_email"], "username": first["admin_email"],
                                 "password": first["admin_password"], "by_port": by_port}
    save(roster_path, roster)
    if len(frames) > 1:
        rc = rc or gate(frames, roster)
    log("onboard: " + ("done" if rc == 0 else "finished with refusals above"))
    return rc


def gate(frames, roster, max_s=1500):
    """Every roster card, with its bond, readable on every OTHER frame (a counterparty the peer cannot see is none)."""
    deadline = time.time() + max_s
    while True:
        missing, rows = 0, []
        for home in frames:
            for peer in frames:
                if peer is home:
                    continue
                ok = 0
                for e in roster.get(home["key"], []):
                    st, d = http("GET", peer["registry"] + f"/api/v1/agents/{e['did']}/reputation", timeout=15)
                    b = (d or {}).get("bond") or {} if st == 200 else {}
                    ok += (b.get("status") or (d or {}).get("bond_status")) in ("locked", "matured", "active")
                missing += len(roster.get(home["key"], [])) - ok
                rows.append(f"{home['key']}->{peer['key']} {ok}/{len(roster.get(home['key'], []))}")
        log("propagation: " + " | ".join(rows))
        if missing == 0:
            return 0
        if time.time() > deadline:
            log("the roster did not reach every peer within the deadline")
            return 1
        time.sleep(30)


# ── running the engine ──────────────────────────────────────────────────────────────────────────────────────────
MODES = {
    "market": [],
    "dynamic": ["--dynamic", "--min-concurrency", "1", "--max-concurrency", "4", "--target-settle-ms", "1500",
                "--target-metric", "p50", "--max-backlog", "10"],
    "clerks": ["--spawn-subagents"],
    "xreg": ["--spawn-subagents"],
    "director": [],
}


def engine_env(frames, sd, symbols, xreg=False):
    regs = {f["key"]: {"port": f["port"], "frame": f["letter"]} for f in frames}
    alias, wire = {}, {}
    for f in frames:
        for k in {f["key"], slugify(f["name"]), f["name"].lower()}:
            alias[k] = f["key"]
        wire[f["key"]] = f["name"]
    env = {
        "PYTHONUNBUFFERED": "1", "PYTHONPATH": "/kit/theprotocol-sdk/src",
        "SIM_REGISTRIES_JSON": json.dumps(regs),
        "SIM_FRAME_CURRENCY_JSON": json.dumps({f["letter"]: f["currency"] for f in frames}),
        "SIM_ES_PORTS_JSON": json.dumps({f["letter"]: f["es_port"] for f in frames}),
        "SIM_FX_ENABLED_FRAMES": ",".join(f["letter"] for f in frames),
        "SIM_MAINFRAMES": ",".join(f["key"] for f in frames),
        "SIM_DELEG_MAINFRAME": frames[0]["key"],
        "SIM_SPAWNED_CREDS": "/state/.spawned.secret.json",
        "SIM_VENUE_ALIAS_JSON": json.dumps(alias), "SIM_VENUE_WIRE_JSON": json.dumps(wire),
        "SIM_SYMBOLS": ",".join(symbols),
        "SIM_PASSPORT_HOMES": ",".join(f["key"] for f in frames) if len(frames) > 1 else "",
        "SIM_LOG_DIR": "/state/logs",
        # one prefix for the whole network: the new name where every frame serves it, else the old one (served by all)
        "SIM_AGORA_PREFIX": AGORA_PREFIX if all(f["agora"] == AGORA_PREFIX for f in frames) else LEGACY_PREFIX,
    }
    if xreg:
        env["SIM_XREG_ONLY"] = "1"
    return env


def engine_image(frames, a):
    if a.image:
        return a.image
    for f in frames:
        c = f.get("container")
        if c:
            r = subprocess.run(["docker", "inspect", c, "--format", "{{.Config.Image}}"], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
    die("no image to run the engine in: name the frame's registry container (container=) or pass --image")


def docker_cmd(frames, sd, a, env, args, name, detach=False):
    cmd = ["docker", "run", "--name", name, "--network", "host", "--user", f"{os.getuid()}:{os.getgid()}",
           "-v", f"{EXPORT_ROOT}:/kit:ro", "-v", f"{sd}:/state:rw", "-w", "/state"]
    cmd += ["-d", "--restart", "no", "--log-opt", "max-size=50m", "--log-opt", "max-file=3"] if detach else ["--rm"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["--entrypoint", "python3", engine_image(frames, a), "/kit/scripts/sim_eigentrust.py",
            "--credentials", "/state/.roster.secret.json"] + args
    return cmd


def issuer_of(did):
    """The home frame a DID names: did:theprotocol:<issuer>:<uuid> (an issuer-bound DID); None for any other shape."""
    parts = (did or "").split(":")
    return parts[2] if len(parts) >= 4 and parts[0] == "did" else None


TAPE_LIMIT = 200   # the trades route's own ceiling (le=200): a larger ask is a 422, which once read here as "no trades"


def tape(f, sym):
    st, r = http("GET", f["registry"] + f"{f['agora']}/listings/{sym}/trades?limit={TAPE_LIMIT}", timeout=30)
    return (r if isinstance(r, list) else ((r or {}).get("trades") or [])) if st == 200 else None


def tape_marks(frames, symbols):
    """The newest trade sequence number of every listing (the tape is newest first; seq only grows)."""
    out = {}
    for f in frames:
        for sym in symbols.get(f["key"], []):
            rows = tape(f, sym)
            out[f"{f['key']}:{sym}"] = max((int(t.get("seq") or 0) for t in rows), default=0) if rows is not None else None
    return out


def tape_since(frames, symbols, marks, issuers):
    """New trades per listing since the marks, and how many of their parties are homed on ANOTHER frame of the run."""
    new, foreign, unreadable = {}, 0, []
    for f in frames:
        own = issuers.get(f["key"], set())
        other = set().union(*[v for k, v in issuers.items() if k != f["key"]]) if len(issuers) > 1 else set()
        for sym in symbols.get(f["key"], []):
            key = f"{f['key']}:{sym}"
            got = tape(f, sym)
            if got is None or marks.get(key) is None:
                unreadable.append(key); new[key] = None; continue
            rows = [t for t in got if int(t.get("seq") or 0) > (marks.get(key) or 0)]
            new[key] = len(rows)
            for t in rows:
                for side in ("buyer_did", "seller_did"):
                    iss = issuer_of(t.get(side))
                    if iss and iss in other and iss not in own:
                        foreign += 1
    return new, foreign, unreadable


def director(frames, sd, on):
    seed = load(os.path.join(sd, ".seed.secret.json"), {})
    for f in frames:
        syms = seed.get(f"{f['key']}:symbols") or []
        body = ({"enabled": True, "tickers": {s: {"dir": d, "strength": 0.5} for s, d in zip(syms, (1, -1))}} if on
                else {"enabled": False, "tickers": {}})
        st, r = http("PUT", f["registry"] + f["agora"] + "/admin/demand-director", body, admin_login(f))
        log(f"[{f['key']}] demand director {'on' if on else 'off'}: {st}")


def run(a, frames, sd, mode):
    seed = load(os.path.join(sd, ".seed.secret.json"), {})
    symbols = {f["key"]: seed.get(f"{f['key']}:symbols") or [] for f in frames}
    if not all(symbols.values()) or not os.path.exists(os.path.join(sd, ".roster.secret.json")):
        die("onboard first: ./frame-sim.py onboard ...")
    if mode == "xreg" and len(frames) < 2:
        die("xreg sends every order to a foreign venue: it needs two frames")
    L = subprocess.run(["sh", "-c", "awk '{printf \"%d\",$1}' /proc/loadavg; echo; free -g | awk 'NR==2{print $7}'"], capture_output=True, text=True).stdout.split()
    if len(L) == 2 and (int(L[0]) >= 40 or int(L[1]) < 15):
        die(f"the host is busy (load {L[0]}, {L[1]}G available): not starting a run")
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_args = ["--mode", "market", "--backend-mode", "mixed", "--cycles", str(a.cycles), "--pairs", str(a.pairs),
                 "--concurrency", "2", "--cycle-interval", "4", "--metrics-jsonl", f"/state/runs/{ts}-{mode}.metrics.jsonl"]
    env = engine_env(frames, sd, [s for v in symbols.values() for s in v], xreg=(mode == "xreg"))
    roster = load(os.path.join(sd, ".roster.secret.json"), {})
    issuers = {f["key"]: {i for i in (issuer_of(e.get("did")) for e in roster.get(f["key"], [])) if i} for f in frames}
    before = {"marks": tape_marks(frames, symbols), "delta": {f["key"]: delta(f) for f in frames}}
    if mode == "director":
        director(frames, sd, True)
    logp = os.path.join(sd, "runs", f"{ts}-{mode}.log")
    log(f"run {mode}: {a.cycles} cycles x {a.pairs} pairs on {', '.join(f['key'] for f in frames)} (log {logp})")
    with open(logp, "w") as out:
        rc = subprocess.run(docker_cmd(frames, sd, a, env, base_args + MODES[mode], f"frame-sim-{mode}-{ts.lower()}"),
                            stdout=out, stderr=subprocess.STDOUT).returncode
    if mode == "director":
        director(frames, sd, False)
    time.sleep(3)
    new, foreign, unreadable = tape_since(frames, symbols, before["marks"], issuers)
    after = {"new_trades": new, "foreign_parties": foreign, "unreadable": unreadable, "delta": {f["key"]: delta(f) for f in frames}}
    v = verdict_of(open(logp, errors="replace").read(), before, after, len(frames), mode)
    v.update(mode=mode, at=ts, engine_rc=rc, log=logp)
    save(os.path.join(sd, "runs", f"{ts}-{mode}.verdict.json"), v)
    save(os.path.join(sd, "last_verdict.json"), v)
    print_verdict(v)
    return 0 if v["pass"] else 1


def verdict_of(text, before, after, nframes, mode):
    cyc = re.findall(r"CYCLE \d+ \| (\d+)ok (\d+)fail", text)
    ok, fail = sum(int(x) for x, _ in cyc), sum(int(y) for _, y in cyc)
    new_trades = after["new_trades"]
    foreign = after["foreign_parties"]
    counted = sum(v for v in new_trades.values() if v)
    checks = {
        # a tape that could not be read is said, never counted as zero
        "every listing's trade tape was readable" + (f" (not: {', '.join(after['unreadable'])})" if after["unreadable"] else ""): not after["unreadable"],
        f"the engine's cycles succeeded (ok {ok}, fail {fail})": ok > 0 and ok > fail,
        f"new trades on the frames' listings ({counted})": counted > 0,
        "every frame's supply delta read 0.0 before and after": all(delta_ok(v) for v in list(before["delta"].values()) + list(after["delta"].values())),
    }
    if nframes > 1 and mode == "xreg":
        # every xreg order is foreign by construction, so a fill must show a party from another frame on the tape
        checks[f"trades with a party homed on another frame ({foreign})"] = foreign > 0
    return {"pass": all(checks.values()), "checks": checks, "cycles_ok": ok, "cycles_fail": fail, "new_trades": new_trades,
            "foreign_parties": foreign, "delta_before": before["delta"], "delta_after": after["delta"]}


def print_verdict(v):
    for name, okk in v["checks"].items():
        print(("PASS " if okk else "FAIL ") + name)
    print("VERDICT: " + ("the run did something real" if v["pass"] else "NOT a pass"))


# ── live ─────────────────────────────────────────────────────────────────────────────────────────────────────
WATCHDOG = r"""#!/bin/sh
# frame-sim's live watchdog: stops the live run on a busy host, a non-zero delta (twice running) or a failing run.
NAME="$1"; STATE="$2"; ES_URLS="$3"; LOG="$STATE/live/watchdog.log"
say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }
halt() { say "STOP: $*"; docker stop -t 20 "$NAME" >/dev/null 2>&1; exit 0; }
say "watchdog up for $NAME"; dbad=0; fbad=0
while :; do
  [ "$(docker inspect "$NAME" --format '{{.State.Running}}' 2>/dev/null)" = true ] || { say "not running: watchdog exits"; exit 0; }
  LD=$(awk '{printf "%d",$1}' /proc/loadavg); AV=$(free -g | awk 'NR==2{print $7}')
  [ "$LD" -ge 60 ] && halt "load1=$LD"; [ "$AV" -lt 15 ] && halt "MemAvailable=${AV}G"
  bad=0; for u in $ES_URLS; do
    d=$(curl -s -m 20 "$u/api/v1/projections/supply-audit" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("delta"), d.get("status"))' 2>/dev/null)
    case "$d" in "0.0 OK"|"0 OK") : ;; *) bad=1; say "delta at $u: [$d]" ;; esac; done
  [ "$bad" = 1 ] && dbad=$((dbad+1)) || dbad=0; [ "$dbad" -ge 2 ] && halt "delta not 0.0 twice running"
  T=$(docker logs --tail 2000 "$NAME" 2>&1 | grep -oE "CYCLE [0-9]+ \| [0-9]+ok [0-9]+fail" | tail -20)
  OK=$(printf '%s\n' "$T" | awk '{sub("ok","",$4); s+=$4} END{print s+0}'); FL=$(printf '%s\n' "$T" | awk '{sub("fail","",$5); s+=$5} END{print s+0}')
  if [ $((OK + FL)) -ge 20 ] && [ "$FL" -gt "$OK" ]; then fbad=$((fbad+1)); else fbad=0; fi
  [ "$fbad" -ge 3 ] && halt "failing run: ok=$OK fail=$FL"
  sleep 60
done
"""


def live(a, frames, sd, verb):
    name = "frame-sim-live-" + "-".join(f["key"] for f in frames)
    os.makedirs(os.path.join(sd, "live"), exist_ok=True)
    if verb == "stop":
        subprocess.run(["docker", "stop", "-t", "20", name], capture_output=True)
        director(frames, sd, False)
        log(f"{name} stopped")
        return 0
    if verb == "status":
        st = subprocess.run(["docker", "inspect", name, "--format", "{{.State.Status}} since {{.State.StartedAt}}"], capture_output=True, text=True)
        log(f"{name}: {st.stdout.strip() or 'absent'}")
        tail = subprocess.run(["docker", "logs", "--tail", "400", name], capture_output=True, text=True)
        for line in [l for l in (tail.stdout + tail.stderr).splitlines() if re.search(r"CYCLE \d+ \|", l)][-3:]:
            print("  " + line[-160:])
        for f in frames:
            log(f"[{f['key']}] delta {delta(f)}")
        return 0
    seed = load(os.path.join(sd, ".seed.secret.json"), {})
    symbols = [s for f in frames for s in (seed.get(f"{f['key']}:symbols") or [])]
    if not symbols:
        die("onboard first")
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    director(frames, sd, True)
    args = ["--mode", "market", "--backend-mode", "mixed", "--cycles", "999999", "--pairs", "6", "--cycle-interval", "5",
            "--concurrency", "2", "--dynamic", "--min-concurrency", "2", "--max-concurrency", "6", "--target-settle-ms", "1500",
            "--target-metric", "p50", "--max-backlog", "10", "--spawn-subagents", "--passport-share", "0.18" if len(frames) > 1 else "0",
            "--metrics-jsonl", "/state/live/metrics.jsonl"]
    r = subprocess.run(docker_cmd(frames, sd, a, engine_env(frames, sd, symbols), args, name, detach=True), capture_output=True, text=True)
    if r.returncode != 0:
        die(f"the live run did not start: {r.stderr.strip()[:200]}")
    wd = os.path.join(sd, "live", "watchdog.sh")
    with open(wd, "w") as fh:
        fh.write(WATCHDOG)
    os.chmod(wd, 0o700)
    subprocess.Popen(["setsid", "sh", wd, name, sd, " ".join(f["es"] for f in frames)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"{name} started with its watchdog ({os.path.join(sd, 'live', 'watchdog.log')}); stop it with: ./frame-sim.py live stop ...")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Run the AGORA market simulation on your frame(s).",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=["onboard", "run", "live", "verdict"])
    ap.add_argument("what", nargs="?", help="run: market|dynamic|clerks|xreg|director|all · live: start|stop|status")
    ap.add_argument("--name", action="append", help="a frame stood up with this kit (repeatable)")
    ap.add_argument("--frame", action="append", help="registry=URL,es=URL,admin=FILE[,key=][,container=][,services=FILE] (repeatable)")
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    ap.add_argument("--state-dir")
    ap.add_argument("--agents", type=int, default=N_DEFAULT, help="traders per frame (onboard)")
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--pairs", type=int, default=4)
    ap.add_argument("--image", help="the image to run the engine in (default: the first frame's registry image)")
    a = ap.parse_args()
    if not os.path.isfile(ENGINE):
        die(f"the simulation engine is missing ({ENGINE}): this kit is incomplete")
    frames = resolve_frames(a)
    sd = state_dir(a, frames)
    save(os.path.join(sd, "network.json"), [{k: v for k, v in f.items() if k not in ("admin_file", "services_file")} for f in frames])
    if a.command == "onboard":
        return onboard(a, frames, sd)
    if a.command == "run":
        mode = a.what or "market"
        if mode == "all":
            rcs = [run(a, frames, sd, m) for m in (["market", "dynamic", "clerks", "director"] + (["xreg"] if len(frames) > 1 else []))]
            return 0 if all(r == 0 for r in rcs) else 1
        if mode not in MODES:
            die(f"unknown mode {mode}: " + ", ".join(list(MODES) + ["all"]))
        return run(a, frames, sd, mode)
    if a.command == "live":
        return live(a, frames, sd, a.what or "status")
    v = load(os.path.join(sd, "last_verdict.json"), None)
    if not v:
        die("no run yet")
    print_verdict(v)
    return 0 if v["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
