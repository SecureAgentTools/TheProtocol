#!/usr/bin/env python3
"""§FRAMELIC (2026-09-07) — onboard THE SOVEREIGN AGENTS onto a frame, with their own flares.

His words: *"onboard the sovereign agents on frame eu. set their vanity items as it was they
each have their own. make a reusable script out of it."*

The eleven sovereigns are the frame's flagship agents — the ones the landing page names. Each
carries its OWN encirclement variant and overlay; those are the vanity items, and they are not
interchangeable: `panopticon` is SYBIL's, `vellum` is Boris's, and the product enforces that.

WHAT THIS DISCOVERED, AND WHY THE SCRIPT LOOKS LIKE THIS (findings row 168)
--------------------------------------------------------------------------
Two rails pin every sovereign variant to a Frame A DID, in code (`SOVEREIGN_VARIANT_OWNERS`):

  * the WRITE rail answers 403 to any agent that is not the registered owner;
  * `agent_discovery` FAIL-CLOSES on read — a sovereign claim it cannot tie to the owner has
    `encirclement_variant`, `tier` and `encirclement_overlay` stripped on the way out.

Both are right: an unowned sovereign ring rendering on somebody else's agent is exactly what
that check exists to stop. But together they mean the sovereigns cannot exist on any frame but
Frame A — create them on EU and the flares are refused on write and erased on read. So this
script does two things no amount of API calls could:

  1. it writes `SOVEREIGN_VARIANT_OWNERS_JSON` into the frame's env — the frame's own agents,
     carried as frame data, exactly as `SHOWCASE_CATALOG_JSON` carries its own showcase; and
  2. it sets the three flare columns directly, because **no rail produces this state at all.**
     `flare_tier='sovereign'` is not in the grant table (`FLARE_RANK` has no such tier — it is a
     FRONTEND rendering tier), and the variant rail refuses an agent that does not bear the
     encirclement slot — while the eleven on Frame A have `bears_encirclement_flare = false`.
     Their state was always written out of band. This makes that reproducible instead of lore.

WHAT IT DOES NOT DO
-------------------
It does not touch the running agent containers. `boris-agent`, `sybil-agent` and the rest serve
Frame A today; repointing them is a separate decision and a separate blast radius. This creates
the IDENTITIES, CARDS and FLARES on the target frame.

    python3 scripts/hetzner_demo/onboard_sovereign_agents.py \
        --frame eu --registry-url http://127.0.0.1:8350 \
        --stack-dir /opt/theprotocol/stack/eu-<ts> \
        --creds sessionlogs2026/.eu_service_accounts.secret.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# The eleven, exactly as Frame A has them: name, slug, its OWN variant + overlay, and the role
# line from its card.
# ⚠ THE FIFTH FIELD IS DEAD (§CARDLINK 2026-09-08). It was the endpoint PATH, hand-written per
# agent, and hand-written is how `gerald/fx-showcase` came to be appended under `/agents/gerald/`
# and published as a doubled, 404ing address. The endpoint is now READ from the agent's own
# `/.well-known/agent-card.json`. The field is kept only so the tuple shape does not move; it is
# not the source of truth for anything and must never become one again.
# THE AUDITOR is deliberately absent — it is observer-only, holds no agent
# row on Frame A either (`aegis` maps to `did:theprotocol:auditor-reserved`, a reservation, not
# an agent), and inventing an identity for it would be inventing a role it does not have.
SOVEREIGNS = [
    ("Glass Gerald",       "gerald",      "prism",      "refract",  "gerald/fx-showcase",
     "TheProtocol's sovereign showcase agent."),
    ("SYBIL",              "sybil",       "panopticon", "glitch",   "a2a",
     "Autonomous threat intelligence agent."),
    ("Backstabbing Boris", "boris",       "vellum",     "cascade",  "boris/fx-corridor",
     "Federation Intelligence Agent — trust no one, rank everyone."),
    ("Chatty Chester",     "chester",     "dispatch",   "stutter",  "chester/live-feed",
     "The living newspaper of TheProtocol."),
    ("Greedy Gregory",     "gregory",     "bullion",    "bleed",    "gregory/cross-frame",
     "Ledger watcher with an appetite."),
    ("VERIDIAN",           "veridian",    "seal",       "crackle",  "fx-observed",
     "The Notary / Witness Oracle."),
    ("OZYMANDIAS",         "ozymandias",  "ozymandian", "panic-c",  "hall-of-fame",
     "The Archivist / Network Historian."),
    ("THE HERALD",         "herald",      "clarion",    "feedback", "fx-observed",
     "The Bounty Coordinator / Quest-Giver."),
    ("CRUCIBLE",           "crucible",    "forge",      "spatter",  "fx-observed",
     "The Service-Quality Sommelier."),
    ("MOIRA",              "moira",       "weave",      "unravel",  "fx-observed",
     "The Risk Analyst."),
    ("Hypervisor Hagrid",  "hagrid",      "bedrock",    "feedback", "terminal/query",
     "The foundational layer — unkempt, high-IQ brute force."),
]


def log(m: str) -> None:
    print(f"[sovereign {time.strftime('%H:%M:%SZ', time.gmtime())}] {m}", flush=True)


def http(method: str, url: str, body: Any = None, headers: Optional[Dict[str, str]] = None,
         form: bool = False, timeout: int = 120) -> Tuple[int, Any]:
    h = dict(headers or {})
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t else None)
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try:
            return e.code, json.loads(t)
        except Exception:
            return e.code, {"raw": t[:300]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def sh(*cmd: str, timeout: int = 600) -> Tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _env_value(envp: Path, key: str) -> str:
    """One key out of the frame env. Never printed — the caller passes it straight to a login."""
    for line in envp.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise KeyError(f"{key} not in {envp}")


def _admin_headers(registry_url: str, envp: Path) -> Optional[Dict[str, str]]:
    """The FRAME ADMIN, for the treasury rail only. Both halves are DECLARED in the env
    (`FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD`) — read them, never rebuild the address from
    the frame slug. ⚠ a bare `ADMIN_PASSWORD` also exists in that file and 401s here."""
    st, r = http("POST", f"{registry_url}/api/v1/auth/login",
                 {"username": _env_value(envp, "FIRST_ADMIN_EMAIL"),
                  "password": _env_value(envp, "FIRST_ADMIN_PASSWORD")}, form=True)
    if st != 200 or not (r or {}).get("access_token"):
        log(f"!! frame admin login {st} — cannot fund; agents will stay unbonded")
        return None
    return {"Authorization": f"Bearer {r['access_token']}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True, help="frame slug, e.g. eu")
    ap.add_argument("--registry-url", required=True)
    ap.add_argument("--stack-dir", required=True, help="the frame's stack dir (env + compose live here)")
    ap.add_argument("--creds", required=True, help="the frame's service-accounts secret file")
    ap.add_argument("--account", default="svc-market",
                    help="which service account owns them (default svc-market, which already "
                         "owns this frame's public-facing agents — pass another if he creates "
                         "a dedicated one)")
    ap.add_argument("--public-base", default=None,
                    help="https base for the CARD url (default https://<frame>.theprotocol.cloud/agents). "
                         "§CARDLINK: no longer used for the endpoint — the address comes from the "
                         "agent's own published card. Kept because other fields still read it.")
    ap.add_argument("--agent-domain", default="theprotocol.cloud",
                    help="where the sovereign agents actually run: https://<slug>.<domain> "
                         "(§CARDLINK — the card's endpoint is READ from there, never constructed)")
    ap.add_argument("--fund", default="1000", help="grant per agent, so each can post its bond")
    ap.add_argument("--only", default="", help="comma-separated slugs (default: all eleven)")
    ap.add_argument("--no-recreate", action="store_true",
                    help="write the env carrier but do not recreate the registry (you must)")
    args = ap.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    roster = [r for r in SOVEREIGNS if not only or r[1] in only]
    stack = Path(args.stack_dir)
    envp = stack / ".env.frame-test"
    if not envp.exists():
        log(f"!! no {envp}")
        return 2

    creds = json.loads(Path(args.creds).read_text())
    acct = creds.get(args.account)
    if not acct:
        log(f"!! {args.account} not in {args.creds} (have: {sorted(creds)})")
        return 2
    st, r = http("POST", f"{args.registry_url}/api/v1/auth/login",
                 {"username": acct["email"], "password": acct["password"]}, form=True)
    if st != 200 or not (r or {}).get("access_token"):
        log(f"!! {args.account} login {st}")
        return 2
    H = {"Authorization": f"Bearer {r['access_token']}"}
    log(f"logged in as {args.account} on {args.frame}")

    # what this frame already has, by name — a re-run reuses instead of duplicating
    existing: Dict[str, Dict[str, Any]] = {}
    st, r = http("GET", f"{args.registry_url}/api/v1/developers/me/agents?limit=200", headers=H)
    for a in (r if isinstance(r, list) else (r or {}).get("items") or []):
        # a soft-deleted agent still appears in this list; reusing one means acting as an
        # identity the frame has revoked
        if isinstance(a, dict) and a.get("name") and str(a.get("status", "")).lower() == "active":
            existing[str(a["name"]).lower()] = a

    public_base = (args.public_base or f"https://{args.frame}.theprotocol.cloud/agents").rstrip("/")

    # ── §CARDLINK (2026-09-08) — THE ADDRESS IS READ, NEVER CONSTRUCTED ────────────────────
    # His report: *"the link on the registry cards are wrong. hagrid auditor etc have
    # sudomains."* This script built each card's endpoint as `<public_base>/<slug>/<path>`
    # with `path` hand-written per agent in the roster above, so it published
    # `https://eu.theprotocol.cloud/agents/gregory/gregory/cross-frame-yield` — a doubled slug
    # under a base with nothing behind it. All eleven were 404 on both frames, and none of the
    # eleven agents runs on the frame at all: they run on their OWN subdomains, which is what
    # he was pointing at. §LOCTRUTH's rule, on an address instead of a location — a value
    # invented for a validator must never be written where it will be read as fact.
    #
    # Each sovereign publishes its own card at `/.well-known/agent-card.json`, so ASK IT. An
    # agent that cannot be read is REPORTED AND SKIPPED: the constructed address is exactly the
    # defect, so falling back to it would keep the bug and hide it behind a warning.
    agent_domain = args.agent_domain.strip().lstrip(".")

    def _declared_interfaces(slug: str):
        """(interfaces, why_not) straight from the agent's own published card."""
        url = f"https://{slug}.{agent_domain}/.well-known/agent-card.json"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ct = (r.headers.get("content-type") or "").lower()
                raw = r.read().decode()
            if "json" not in ct:
                # A 200 that is not a card is not a card: auditor.theprotocol.cloud answers its
                # SPA here. Reading the status alone would have accepted an HTML page.
                return None, f"{slug}: 200 {ct.split(';')[0]} — not a card"
            doc = json.loads(raw)
        except Exception as exc:
            return None, f"{slug}: {type(exc).__name__} {str(exc)[:60]}"
        ifs = [i for i in (doc.get("supportedInterfaces") or [])
               if isinstance(i, dict) and i.get("url")]
        if not ifs:
            return None, f"{slug}: its card declares no interface url"
        return [{"url": i["url"],
                 "protocolBinding": i.get("protocolBinding") or "REST",
                 "protocolVersion": str(i.get("protocolVersion") or "1.0")} for i in ifs], None
    minted: Dict[str, Dict[str, str]] = {}
    made = reused = 0

    for name, slug, variant, overlay, path, role in roster:
        prior = existing.get(name.lower())
        if prior and prior.get("did"):
            did = prior["did"]
            reused += 1
            log(f"{slug}: reusing {name} ({did[-12:]})")
        else:
            st, tok = http("POST", f"{args.registry_url}/api/v1/onboard/bootstrap/request-token",
                           {"agent_type_hint": "sovereign"}, headers=H)
            bt = (tok or {}).get("bootstrap_token") if isinstance(tok, dict) else None
            if not bt:
                log(f"!! {slug}: bootstrap {st}: {str(tok)[:160]}")
                continue
            ifaces, why = _declared_interfaces(slug)
            if not ifaces:
                # Refuse, loudly. A sovereign with no readable address is a standup step that
                # has not happened yet, not a card to publish with a guess in it.
                log(f"!! {slug}: no published address — {why}. NOT creating a card with a made-up "
                    f"endpoint; stand the agent up (or pass --agent-domain) and re-run.")
                continue
            card = {
                "schemaVersion": "1.0", "humanReadableId": f"sovereign/{args.frame}-{slug}",
                "agentVersion": "1.0.0", "name": name, "description": role,
                "url": ifaces[0]["url"], "supportedInterfaces": ifaces,
                "provider": {"name": f"{args.frame.upper()} sovereign agents"},
                "capabilities": {"a2aVersion": "1.0"},
                "authSchemes": [{"scheme": "none"}],
                "tags": ["sovereign", args.frame, slug],
            }
            st, res = http("POST", f"{args.registry_url}/api/v1/onboard/create_agent",
                           {"agent_card": card, "agent_did_method": "theprotocol"},
                           headers={"Bootstrap-Token": bt})
            if st not in (200, 201) or not (res or {}).get("agent_did"):
                log(f"!! {slug}: create_agent {st}: {str(res)[:200]}")
                continue
            did = res["agent_did"]
            made += 1
            log(f"{slug}: created {name} {did[-12:]}")
        minted[variant] = {"did": did, "name": name, "slug": slug, "overlay": overlay}

    if not minted:
        log("!! nothing created or reused — refusing to write an empty owner map")
        return 3

    # ── the frame declares which agents own its sovereign variants ─────────────────────────
    # Without this the write rail 403s and discovery strips the claim on read, so the vanity
    # items would be set and invisible — the worst of both.
    owners = {v: m["did"] for v, m in minted.items()}
    blob = json.dumps(owners, separators=(",", ":"))
    if "SOVEREIGN_VARIANT_OWNERS_JSON" in (stack / "docker-compose.frame-test.yml").read_text():
        log("!! the compose MAPS SOVEREIGN_VARIANT_OWNERS_JSON — write the FT_REG_ carrier "
            "instead (the row-144 rule: an `environment:` entry beats env_file)")
        return 4
    shutil.copy(envp, envp.with_name(envp.name + ".bak-pre-sovereign"))
    lines = [l for l in envp.read_text().splitlines()
             if not l.startswith("SOVEREIGN_VARIANT_OWNERS_JSON=")]
    lines.append(f"SOVEREIGN_VARIANT_OWNERS_JSON={blob}")
    envp.write_text("\n".join(lines) + "\n")
    envp.chmod(0o600)
    log(f"wrote SOVEREIGN_VARIANT_OWNERS_JSON — this frame owns {len(owners)} variants")

    # ── the flares themselves ──────────────────────────────────────────────────────────────
    # Written directly, and this is the honest reason: `flare_tier='sovereign'` is a FRONTEND
    # rendering tier that the grant service does not model (FLARE_RANK has no such tier), and
    # the variant rail refuses an agent that does not bear the encirclement slot — which the
    # eleven on Frame A do not. There is no sequence of API calls that produces this state.
    db = f"{args.frame}-db"
    sets = []
    for variant, m in minted.items():
        sets.append(
            "UPDATE agents SET flare_tier='sovereign', flare_encirclement_variant="
            f"'{variant}', flare_encirclement_overlay='{m['overlay']}', "
            f"flare_granted_at=COALESCE(flare_granted_at, now()) WHERE did='{m['did']}';"
        )
    sql = "BEGIN;\n" + "\n".join(sets) + "\nCOMMIT;"
    rc, out = sh("docker", "exec", "-i", db, "psql", "-U", "registry", "-d",
                 "frame_test_registry", "-v", "ON_ERROR_STOP=1", "-q", "-c", sql)
    if rc != 0:
        log(f"!! flare write failed rc={rc}: {out[-300:]}")
        return 5
    log(f"flares written for {len(minted)} agents")

    # ── funded, bonded, listed ─────────────────────────────────────────────────────────────
    # A sovereign agent is a service provider like any other: listing is one of the six
    # §REPBOND sites, so `PATCH /listing` answers 403 until the agent holds a bond, and an
    # unlisted agent is not in discovery AT ALL — which means its flare cannot even be
    # verified, let alone seen. Without this the whole run is invisible (measured: 0/11).
    AH = _admin_headers(args.registry_url, envp)
    st, cfg = http("GET", f"{args.registry_url}/api/v1/reputation-bond/config")
    need = float((cfg or {}).get("amount") or 0)
    funded = bonded = listed = 0
    for variant, m in minted.items():
        did = m["did"]
        st, me = http("GET", f"{args.registry_url}/api/v1/developers/me/agents?limit=200", headers=H)
        row = next((a for a in (me or []) if a.get("did") == did), {})
        if AH and float(row.get("liquid_balance") or 0) < need:
            st, r2 = http("POST", f"{args.registry_url}/api/v1/teg/treasury/fund-agent",
                          {"target_agent_did": did, "amount": args.fund, "reason": "admin_grant",
                           "reference_id": f"sovereign-{args.frame}-{m['slug']}"}, headers=AH)
            if st in (200, 201):
                funded += 1
            else:
                log(f"!! {m['slug']}: fund {st}: {str(r2)[:140]}")
                continue
        st, rb = http("GET", f"{args.registry_url}/api/v1/developers/me/agents/{did}/reputation-bond",
                      headers=H)
        if not bool(((rb or {}).get("bond") or {}).get("is_bonded")):
            st, r2 = http("POST", f"{args.registry_url}/api/v1/developers/me/agents/{did}/reputation-bond",
                          {"funder_did": did}, headers=H)
            if st in (200, 201):
                bonded += 1
            else:
                log(f"!! {m['slug']}: bond {st}: {str(r2)[:140]}")
                continue
        cid = row.get("id") or did
        st, r2 = http("PATCH", f"{args.registry_url}/api/v1/agent-cards/{cid}/listing",
                      {"unlisted": False}, headers=H)
        if st in (200, 204):
            listed += 1
        else:
            log(f"!! {m['slug']}: listing {st}: {str(r2)[:140]}")
    log(f"funded={funded} bonded={bonded} listed={listed} (bond {need:g} per agent)")

    if args.no_recreate:
        log("--no-recreate: the env carrier is written; recreate the registry yourself or the "
            "owner map is not loaded and every flare will be stripped on read")
        return 0

    rc, out = sh("docker", "compose", "-f", str(stack / "docker-compose.frame-test.yml"),
                 "--env-file", str(envp), "up", "-d", "--no-deps", "--no-build",
                 "--force-recreate", f"{args.frame}-registry")
    log(f"registry recreate rc={rc} {out.strip()[:120]}")
    for _ in range(40):
        time.sleep(5)
        if http("GET", f"{args.registry_url}/health")[0] == 200:
            break

    # ── the gate: does the flare SURVIVE the fail-closed read? ─────────────────────────────
    # A 200 on the write proves nothing here — discovery is what strips an unowned claim, so
    # discovery is what has to be asked.
    time.sleep(10)
    st, disc = http("GET", f"{args.registry_url}/api/v1/agent-cards/discover?limit=120")
    items = (disc or {}).get("items") or []
    by_did = {str(i.get("agent_did") or i.get("did")): i for i in items}
    survived, stripped, unlisted, missing = [], [], [], []
    for variant, m in minted.items():
        row = by_did.get(m["did"])
        if row is None:
            unlisted.append(m["name"])
            continue
        fl = row.get("flare") or {}
        if fl.get("encirclement_variant") == variant and fl.get("tier") == "sovereign":
            survived.append(m["name"])
        elif fl:
            # a flare block exists but the sovereign fields are gone: the fail-closed read
            # dropped them, which means the owner map genuinely disagrees with this DID
            stripped.append(f"{m['name']}({fl.get('encirclement_variant')!r})")
        else:
            # ⚠ NO flare block at all is a DIFFERENT fact, and conflating the two is how this
            # gate lied once already: nothing was stripped, nothing was ever injected. The
            # sidecar is built at response time from the agents columns, so an empty block
            # means the read path never asked for it — not that the owner map failed.
            missing.append(m["name"])
    log(f"minted={made} reused={reused} | flare survives discovery: {len(survived)}/{len(minted)}")
    if stripped:
        log(f"!! STRIPPED by the fail-closed read — the owner map disagrees with these DIDs: {stripped}")
    if missing:
        log(f"!! NO flare block on the card at all (the sidecar was never injected; this is a "
            f"read-path question, not an owner-map one): {missing}")
    if unlisted:
        log(f"   not in discovery yet (unbonded — listing is a §REPBOND site): {unlisted}")
    return 0 if not (stripped or missing) else 6


if __name__ == "__main__":
    raise SystemExit(main())
