#!/usr/bin/env python3
"""§SHOWCASEOWN (2026-09-07) — give a fresh frame its OWN showcase agents.

His word: *"showcase shows its own agents. we reonboard all the agents via a script."*

MEASURED on EU 2026-09-07, before this script existed: `/api/v1/public/showcase/agents` on the EU
frame returned **registry-a's eleven agents** — DIDs issued on Frame A, endpoints under
api.theprotocol.cloud, prices in **AVT** on an ECU frame (with `fx_unavailable: true`, because
there is no AVT pool to convert from), and internal dials like `http://weather-agent:8055` naming a
container that only resolves on Frame A's docker network. Every one of those is a claim about
another frame published as if it were this frame's.

What this does, per agent:
  1. creates an agent on THIS frame through the normal onboard rail, owned by a SERVICE ACCOUNT
     (so the card is `unlisted` by construction and never litters discovery),
  2. prices it in THIS frame's currency on its own card,
  3. runs a SECOND CONTAINER from the SAME already-built image, pointed at this frame, on this
     frame's network, under a frame-prefixed name — the original Frame A instance is untouched,
     which matters because registry-a still serves the apex while it is being retired,
  4. writes the catalog JSON the registry reads as SHOWCASE_CATALOG_JSON,
  5. (D6-831, 2026-10-25) where the frame enforces the reputation bond, bonds each agent through its
     owner's roads (the treasury backstop where allowed, else the agent's own balance) or says loudly
     that it could not, and gives a reused agent's card the address this run publishes:
     <base>/agents/<slug>/a2a, which the registry serves itself (no vhost of its own).

It is idempotent: an agent that already exists on this frame is reused, and a container that is
already running is left alone unless --recreate.

    python3 scripts/hetzner_demo/reonboard_showcase.py \
        --frame eu --registry-url http://127.0.0.1:8350 \
        --network eu_default --currency ECU \
        --creds sessionlogs2026/.eu_service_accounts.secret.json \
        --out /opt/theprotocol/stack/eu-<ts>/showcase_catalog.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# The eleven, with the port each serves inside its own container and the price it has always
# charged. The PRICE is a number in THIS frame's currency now — 0.5 ECU, not "0.5 AVT relabelled":
# the agent bills what its card says, and its card is created here.
SHOWCASE = [
    ("weather",   "weather-agent",         8055, "0.5", "WeatherAgent",       "Current weather and forecasts for any location."),
    ("currency",  "currency-agent",        8056, "0.5", "CurrencyAgent",      "Foreign-exchange rates between world currencies."),
    ("news",      "news-agent",            8057, "0.5", "NewsAgent",          "Headlines and news search."),
    ("ip",        "ip-info-agent",         8058, "0.1", "IPInfoAgent",        "Geolocation and network facts for an IP address."),
    ("dns",       "dns-ssl-agent",         8059, "1.0", "DnsSSLAgent",        "DNS records and TLS certificate inspection for a domain."),
    ("timezone",  "timezone-agent",        8065, "0.1", "TimezoneAgent",      "Time-zone conversion and local time anywhere."),
    ("units",     "unit-converter-agent",  8066, "0.1", "UnitConverterAgent", "Unit conversion across measurement systems."),
    ("text",      "text-utility-agent",    8067, "0.1", "TextUtilityAgent",   "Text transforms: hashing, encoding, case, diff."),
    ("cron",      "cron-agent",            8068, "0.1", "CronAgent",          "Cron expression parsing and next-run calculation."),
    ("password",  "password-gen-agent",    8069, "0.1", "PasswordGenAgent",   "Cryptographically strong password generation."),
    ("converter", "converter-hub",         8070, "0.1", "ConverterHub",       "Format conversion between common data formats."),
]


def log(m: str) -> None:
    print(f"[showcase {time.strftime('%H:%M:%SZ', time.gmtime())}] {m}", flush=True)


def http(method: str, url: str, body: Any = None, headers: Optional[Dict[str, str]] = None,
         form: bool = False, timeout: int = 30) -> Tuple[int, Any]:
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
            raw = r.read().decode() or "{}"
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode() or "{}"
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:  # noqa: BLE001
        return 0, {"err": f"{type(e).__name__}: {e}"}


def public_address(public_base: str, frame: str, slug: str) -> str:
    """The address the card advertises: <base>/agents/<slug>/a2a, the shape the registry serves itself for a catalogue
    entry (§CARDLINK, main.py showcase_agent_address), so the card's address needs no vhost of its own.

    D6-831 (agentvault2-66, 2026-10-25): with --public-base this built <base>/<slug>/a2a, an address nothing routes
    (sbx-alpha's WeatherAgent answered 404 at https://sandbox-a.theprotocol.cloud/weather-agent/a2a and a member's buy
    failed at the call). A base that already ends in /agents is taken as it is."""
    base = (public_base or f"https://{frame}.theprotocol.cloud").rstrip("/")
    if not base.endswith("/agents"):
        base += "/agents"
    return f"{base}/{slug}/a2a"


def bond_config(registry_url: str) -> Optional[Dict[str, Any]]:
    """The bond this frame asks of a provider (public): its mode, amount, currency and whether the treasury backstops."""
    st, c = http("GET", f"{registry_url}/api/v1/reputation-bond/config")
    return c if st == 200 and isinstance(c, dict) else None


def ensure_bond(registry_url: str, H: Dict[str, str], key: str, did: str, cfg: Optional[Dict[str, Any]]) -> bool:
    """D6-831 (agentvault2-66, 2026-10-25): a paid showcase agent on a frame that enforces the bond holds its bond, or
    the run says so. Unbonded, a member's authorize refuses it ("holds no reputation bond"), its paid card cannot be
    edited, and the showcase lists it without a run. The owner's own roads, in order: the treasury backstop where the
    frame allows it, then the agent's own balance through the owner's session (this script keeps no client secret).
    True when the agent is bonded, or the frame does not enforce the bond."""
    if not cfg or str(cfg.get("mode") or "") != "enforce":
        return True
    q = urllib.parse.quote(did, safe=":")
    st, b = http("GET", f"{registry_url}/api/v1/developers/me/agents/{q}/reputation-bond", headers=H)
    if st == 200 and isinstance(b, dict) and b.get("is_bonded"):
        log(f"{key}: bonded ({(b.get('bond') or {}).get('status')})")
        return True
    need = f"{cfg.get('amount')} {cfg.get('currency')}"
    if cfg.get("treasury_backstop"):
        st, r = http("POST", f"{registry_url}/api/v1/developers/me/agents/{q}/reputation-bond/backstop", headers=H)
        if st == 200 and isinstance(r, dict) and r.get("status") in ("locked", "matured"):
            log(f"{key}: bonded from the treasury backstop ({r.get('amount')} {cfg.get('currency')})")
            return True
        log(f"!! {key}: the treasury backstop answered {st}: {str((r or {}).get('detail') if isinstance(r, dict) else r)[:200]}")
    st, t = http("POST", f"{registry_url}/api/v1/developers/me/agents/{q}/session-token", headers=H)
    tok = (t or {}).get("access_token") if isinstance(t, dict) else None
    if tok:
        st, r = http("POST", f"{registry_url}/api/v1/agents/reputation-bond/deposit", {},
                     headers={"Authorization": f"Bearer {tok}"})
        if st == 200 and isinstance(r, dict) and r.get("status") in ("locked", "matured"):
            log(f"{key}: bonded from its own balance ({r.get('amount')} {r.get('currency')})")
            return True
        why = (r or {}).get("detail") if isinstance(r, dict) else r
        log(f"!! {key}: its own balance could not bond it ({st}): {str(why)[:200]}")
    else:
        log(f"!! {key}: no session token for it ({st})")
    log(f"!! {key}: holds no bond on a frame that enforces it (needs {need}): a member's buy is refused and the "
        f"showcase lists it without a run. Fund the agent and run this again, or bond it with the admin backstop "
        f"(POST /api/v1/admin/reputation-bond/backstop).")
    return False


def repoint_card(registry_url: str, H: Dict[str, str], key: str, did: str, url: str) -> None:
    """A reused agent's card advertises the address this run publishes (D6-831: sbx-alpha's WeatherAgent was created
    with the address nothing routes, and a re-run reused it as it was). The card's other fields are left as they are."""
    q = urllib.parse.quote(did, safe=":")
    st, c = http("GET", f"{registry_url}/api/v1/agent-cards/{q}", headers=H)
    cd = (c or {}).get("card_data") if isinstance(c, dict) else None
    if st != 200 or not isinstance(cd, dict):
        log(f"!! {key}: could not read its card ({st}); its address is left as it is")
        return
    ifaces = [i for i in (cd.get("supportedInterfaces") or []) if isinstance(i, dict) and i.get("url")]
    if cd.get("url") == url and all(i["url"] == url for i in ifaces):
        return
    cd = json.loads(json.dumps(cd))
    if cd.get("url"):
        cd["url"] = url
    for i in cd.get("supportedInterfaces") or []:
        if isinstance(i, dict) and i.get("url"):
            i["url"] = url
    st, r = http("PUT", f"{registry_url}/api/v1/agent-cards/{q}", {"card_data": cd}, headers=H)
    if st == 200:
        log(f"{key}: its card now advertises {url}")
    else:
        why = (r or {}).get("detail") if isinstance(r, dict) else r
        log(f"!! {key}: the card's address could not be changed ({st}): {str(why)[:200]}")


def sh(*cmd: str) -> Tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True, help="frame slug, e.g. eu")
    ap.add_argument("--registry-url", required=True, help="loopback registry base, e.g. http://127.0.0.1:8350")
    ap.add_argument("--public-base", default="", help="public https base for the agents (default: skip the public url)")
    ap.add_argument("--network", required=True, help="docker network the frame's registry is on")
    ap.add_argument("--agent-registry-url", default=None,
                    help="the registry as the AGENTS reach it on --network (default http://<frame>-registry:8000). "
                         "§SHOWCASEPAY: they verify every payment token there, and a host-side address does not "
                         "resolve inside their containers")
    ap.add_argument("--currency", required=True, help="this frame's currency code, e.g. ECU")
    ap.add_argument("--creds", required=True, help="the frame's service-accounts secret file")
    ap.add_argument("--account", default="svc-market", help="which service account owns the showcase agents")
    ap.add_argument("--out", required=True, help="where to write the catalog JSON")
    ap.add_argument("--only", default="", help="comma-separated keys (default: all eleven)")
    ap.add_argument("--recreate", action="store_true", help="recreate a container that is already running")
    # §FRAMELIC (2026-09-07, findings row 160) — WIRE IT, or the frame keeps serving Frame A's.
    # The catalog can only be written AFTER the frame is up (its agents are created on it), so
    # `--showcase-catalog-json` on the standup driver can never be used on a first pass, and the
    # wiring was therefore done by hand on the previous pair — and died with the teardown. The
    # frame then served the BUILT-IN showcase map: Frame A's DIDs, which 404 on this frame, while
    # the prices read ECU because only the price lookup falls back to the local currency. A card
    # advertising a DID that does not resolve is worse than no card.
    ap.add_argument("--wire", default=None, metavar="STACK_DIR",
                    help="write SHOWCASE_CATALOG_JSON into the frame's .env.frame-test and "
                         "recreate its registry, so the frame serves the catalog just written")
    ap.add_argument("--no-containers", action="store_true",
                    help="create the cards and write the catalog but do not run the agent containers")
    args = ap.parse_args()
    agent_registry = (args.agent_registry_url or f"http://{args.frame}-registry:8000").rstrip("/")

    keys = [k.strip() for k in args.only.split(",") if k.strip()] or [s[0] for s in SHOWCASE]
    creds = json.loads(Path(args.creds).read_text())
    if args.account not in creds:
        log(f"!! {args.account} not in {args.creds} (have: {', '.join(creds)})")
        return 2
    acct = creds[args.account]

    st, r = http("POST", f"{args.registry_url}/api/v1/auth/login",
                 {"username": acct["email"], "password": acct["password"]}, form=True)
    if st != 200 or not (r or {}).get("access_token"):
        log(f"!! {args.account} login {st}: {str(r)[:200]}")
        return 2
    H = {"Authorization": f"Bearer {r['access_token']}"}
    log(f"logged in as {args.account} on {args.frame}")
    bond_cfg = bond_config(args.registry_url)
    if bond_cfg:
        log(f"the frame's bond: mode {bond_cfg.get('mode')}, {bond_cfg.get('amount')} {bond_cfg.get('currency')}, "
            f"treasury backstop {'on' if bond_cfg.get('treasury_backstop') else 'off'}")
    else:
        log("!! the frame's bond config could not be read: the agents' bonds are not checked")
    unbonded = []

    # what this frame already has, by name — so a re-run reuses instead of duplicating
    existing: Dict[str, Dict[str, Any]] = {}
    st, r = http("GET", f"{args.registry_url}/api/v1/developers/me/agents?limit=200", headers=H)
    for a in (r if isinstance(r, list) else (r or {}).get("items") or []):
        if isinstance(a, dict) and a.get("name"):
            existing[str(a["name"]).lower()] = a

    catalog: Dict[str, Dict[str, str]] = {}
    made = reused = ran = 0
    for key, slug, port, price, name, description in SHOWCASE:
        if key not in keys:
            continue
        local_name = f"{args.frame}-{slug}"
        # TWO addresses, and the card carries the PUBLIC one. `AgentCard.url` is validated as
        # HTTPS-unless-localhost (correctly: a card is a published claim, and an internal container
        # name is not an address anyone off this host can dial). The internal name is the DIAL the
        # showcase rail uses from inside the frame's network, and it belongs in the catalog's
        # `url`, not on the card. Frame A has always done this — the hardcoded map carries both —
        # and building the card from the dial was my own conflation of the two.
        dial = f"http://{local_name}:{port}/a2a"
        url = public_address(args.public_base, args.frame, slug)

        res = None          # bound on the MINT branch only; the reuse path must not NameError
        prior = existing.get(name.lower())
        if prior and prior.get("did"):
            did = prior["did"]
            reused += 1
            log(f"{key}: reusing {name} ({did[-12:]})")
        else:
            st, tok = http("POST", f"{args.registry_url}/api/v1/onboard/bootstrap/request-token",
                           {"agent_type_hint": "showcase"}, headers=H)
            bt = (tok or {}).get("bootstrap_token") if isinstance(tok, dict) else None
            if st not in (200, 201) or not bt:
                log(f"!! {key}: bootstrap {st}: {str(tok)[:200]}")
                continue
            card = {
                "schemaVersion": "1.0", "humanReadableId": f"showcase/{args.frame}-{key}",
                "agentVersion": "1.0.0", "name": name, "description": description,
                "url": url, "provider": {"name": f"{args.frame.upper()} showcase"},
                "capabilities": {"a2aVersion": "1.0"},
                "authSchemes": [{"scheme": "none"}],
                # The price lives on the CARD, in THIS frame's currency, because the showcase
                # endpoint reads the card rather than trusting any local map (§SHOWCASE-FX).
                "pricing": {"payment_required": True, "base_rate": price,
                            "currency": args.currency, "pricing_model": "per_call"},
                "tags": ["showcase", args.frame, key],
            }
            st, res = http("POST", f"{args.registry_url}/api/v1/onboard/create_agent",
                           {"agent_card": card, "agent_did_method": "theprotocol"},
                           headers={"Bootstrap-Token": bt})
            if st not in (200, 201) or not (res or {}).get("agent_did"):
                log(f"!! {key}: create_agent {st}: {str(res)[:240]}")
                continue
            did = res["agent_did"]
            made += 1
            log(f"{key}: created {name} {did[-12:]} at {price} {args.currency}")

        # §FRAMELIC (2026-09-07, findings row 149) — A SHOWCASE AGENT IS THE ONE KIND THAT MUST BE
        # LISTED. Creating these under a SERVICE ACCOUNT is right (they are frame infrastructure,
        # and the account owns them), but `agents_unlisted_by_default` then hid them from
        # discovery: the showcase page still worked because it reads the catalog directly, while
        # `/agent-cards/discover` returned ZERO cards on a frame with eleven live agents. Two
        # correct rules meeting in one place, which is the §COCKPITFRAME shape. Un-hide them
        # explicitly — the flag is a DEFAULT, and this is exactly the case that overrides it.
        # the owner-only rail is PATCH /agent-cards/{card_id}/listing (routers/agent_cards.py)
        _cid = (prior or {}).get("id") or (res or {}).get("card_id") or (res or {}).get("id") or did
        st_u, r_u = http("PATCH", f"{args.registry_url}/api/v1/agent-cards/{_cid}/listing",
                         {"unlisted": False}, headers=H)
        if st_u in (200, 204):
            log(f"{key}: listed (a showcase agent is for showing)")
        else:
            log(f"!! {key}: could not un-hide ({st_u}) — it will not appear in discovery")

        # D6-831: the bond before the card edit (a paid card is edited only by a bonded agent where the bond is
        # enforced), then a reused agent's card gets this run's address
        if not ensure_bond(args.registry_url, H, key, did, bond_cfg):
            unbonded.append(key)
        if prior and prior.get("did"):
            repoint_card(args.registry_url, H, key, did, url)

        entry = {"did": did, "url": dial, "price": price, "name": name, "public": url}
        catalog[key] = entry

        if args.no_containers:
            continue
        # A SECOND instance of the SAME image: no new layers, no disk, and Frame A's original
        # container is untouched — it still serves the apex while registry-a is retired.
        rc, out = sh("docker", "ps", "-a", "--filter", f"name=^{local_name}$", "--format", "{{.Names}}")
        if out.strip() == local_name:
            if not args.recreate:
                log(f"{key}: container {local_name} already exists — left alone")
                ran += 1
                continue
            sh("docker", "rm", "-f", local_name)
        rc, img = sh("docker", "inspect", slug, "--format", "{{.Config.Image}}")
        if rc != 0 or not img.strip():
            log(f"!! {key}: no source container {slug} to take the image from — container skipped")
            continue
        rc, out = sh(
            "docker", "run", "-d", "--name", local_name, "--network", args.network,
            "--restart", "unless-stopped",
            # §SHOWCASEPAY (2026-09-26): the agent verifies each payment token at its registry, so it must dial the
            # registry on the network it runs on. This was the host-side address (host.docker.internal, which has no
            # entry inside the container, and 127.0.0.1, which is the agent itself): every paid call answered 402.
            "-e", f"REGISTRY_URL={agent_registry}",
            "-e", f"AGENT_DID={did}",
            "-e", "PAYMENT_REQUIRED=true",
            "-e", f"MIN_PAYMENT={price}",
            "-e", f"AGENT_CURRENCY={args.currency}",
            "-e", f"TRUSTED_REGISTRIES={agent_registry}",
            img.strip(),
        )
        if rc != 0:
            log(f"!! {key}: docker run failed: {out[:200]}")
            continue
        ran += 1
        log(f"{key}: container {local_name} up on {args.network}")

    Path(args.out).write_text(json.dumps(catalog, indent=1))
    os.chmod(args.out, 0o644)
    log(f"catalog: {len(catalog)} agents ({made} created, {reused} reused, {ran} containers) -> {args.out}")
    if unbonded:
        log(f"!! {len(unbonded)} agent(s) without a bond on a frame that enforces it: {', '.join(unbonded)}")

    if args.wire:
        # The key is NOT mapped in the compose `environment:` block, and the registry service does
        # carry `env_file:`, so the bare name is the carrier here — the opposite of row 144, which
        # is why the rule is "read the compose", not "always write FT_REG_".
        envp = Path(args.wire) / ".env.frame-test"
        compose = Path(args.wire) / "docker-compose.frame-test.yml"
        if "SHOWCASE_CATALOG_JSON" in compose.read_text():
            log("!! the compose MAPS SHOWCASE_CATALOG_JSON — write the FT_REG_ carrier instead (row 144)")
            return 3
        blob = json.dumps(catalog, separators=(",", ":"))
        lines = [l for l in envp.read_text().splitlines()
                 if not l.startswith("SHOWCASE_CATALOG_JSON=")]
        lines.append(f"SHOWCASE_CATALOG_JSON={blob}")
        shutil.copy(envp, envp.with_name(envp.name + ".bak-pre-showcase-wire"))
        envp.write_text("\n".join(lines) + "\n")
        envp.chmod(0o600)
        log(f"wired SHOWCASE_CATALOG_JSON ({len(blob)} bytes) into {envp}")
        rc, out = sh("docker", "compose", "-f", str(compose), "--env-file", str(envp),
                     "up", "-d", "--no-deps", "--no-build", "--force-recreate",
                     f"{args.frame}-registry")
        log(f"registry recreate rc={rc} {out.strip()[:120]}")
        # a 200 is not proof the catalog took — read the published DID back
        time.sleep(35)
        st, sc = http("GET", f"{args.registry_url}/api/v1/public/showcase/agents")
        pub = {a2.get("did") for a2 in (sc or {}).get("agents", [])}
        mine = {e["did"] for e in catalog.values()}
        if pub and pub <= mine:
            log(f"showcase now serves THIS frame's agents ({len(pub)} DIDs, all from the catalog)")
        else:
            log(f"!! showcase still not serving the catalog: published={list(pub)[:2]}")
            return 4
    if not catalog:
        log("!! EMPTY catalog — do NOT set SHOWCASE_CATALOG_JSON from this; the registry would "
            "refuse it and fall back to Frame A's eleven, which is the defect we are fixing.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
