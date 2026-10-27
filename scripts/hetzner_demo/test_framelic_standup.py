#!/usr/bin/env python3
"""§FRAMELIC (2026-09-07) — gates for the production-standup changes.

Each row of FINDINGS_2026-09-06_REPROVISIONING.md this batch closes gets a gate that would have
FAILED on the pre-fix shape. Run: python3 scripts/hetzner_demo/test_framelic_standup.py
"""
import ast
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "hetzner_demo"))

import standup_extras as extras  # noqa: E402

FAILED = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILED.append(label)


# ── row 64 / W4: the DEMO jurisdiction profile is COMPLETE and named for this frame ───────────
prof = extras.demo_jurisdiction_profile(
    frame_label="EU", profile_name="eu-provider-no-fiat",
    jurisdiction_label="EU (demo)", authority="EU Demo Authority")
check("jurisdiction: four regulated actions, all shadow",
      set(prof["requires_authorization"]) == set(extras.REGULATED_ACTIONS)
      and all(v["mode"] == "shadow" for v in prof["requires_authorization"].values()),
      json.dumps(prof.get("requires_authorization", {}))[:200])
check("jurisdiction: a DEMO authority must never claim ENFORCE",
      all(v["mode"] != "enforce" for v in prof["requires_authorization"].values()))
check("jurisdiction: the authority is named for THIS frame, not Frame-A",
      all(v["authority"] == "EU Demo Authority" for v in prof["requires_authorization"].values()))

# The shape the VALIDATOR accepts is not the shape the CARD publishes — this cost a 422 on the
# first EU run. `services/jurisdiction.validate_profile` allows exactly these top-level keys, and
# `declared_at` is stamped server-side. (The authoritative check is running the real validator in
# the image; this is the cheap one that catches a drift before a standup does.)
ALLOWED_TOP = {"name", "version", "features", "limits", "declared_at", "note", "requires_authorization"}
check("jurisdiction: no key the validator would refuse as unknown",
      set(prof) <= ALLOWED_TOP, str(sorted(set(prof) - ALLOWED_TOP)))
check("jurisdiction CONTROL: the card's OUTPUT keys are NOT sent as input",
      not ({"features_denied", "declared_by", "regulated_actions"} & set(prof)))
check("jurisdiction: the four actions live under requires_authorization",
      set(prof.get("requires_authorization", {})) == set(extras.REGULATED_ACTIONS))
check("jurisdiction: scopes match services/regulatory_auth._DEFAULT_SCOPE "
      "(a per-subject act declared at registry scope is a different claim)",
      {a: e["scope"] for a, e in prof["requires_authorization"].items()} ==
      {"exchange.listing": "per_subject", "exchange.ipo": "per_subject",
       "fiat.lane": "registry", "registry.operation": "registry"})
check("jurisdiction: fiat is denied on a demo frame",
      prof["features"].get("fiat") is False)

auths = extras.demo_authorizations(
    frame_label="EU", jurisdiction_label="EU (demo)", authority="EU Demo Authority")
check("authorizations: one per regulated action",
      {a["action"] for a in auths} == set(extras.REGULATED_ACTIONS))
check("authorizations: reference ids carry the frame",
      all(a["reference_id"].startswith("DEMO-2026/EU-") for a in auths),
      str([a["reference_id"] for a in auths]))
check("authorizations: every record carries validity and evidence",
      all(a.get("valid_from") and a.get("valid_until") and a.get("evidence_hash", "").startswith("sha256:")
          for a in auths))
asia = extras.demo_authorizations(
    frame_label="ASIA", jurisdiction_label="ASIA (demo)", authority="ASIA Demo Authority")
check("authorizations: two frames NEVER publish the same evidence hash for the same action "
      "(registry-a reuses one constant across all four)",
      {a["evidence_hash"] for a in auths}.isdisjoint({a["evidence_hash"] for a in asia}))
check("authorizations: the four actions of ONE frame differ from each other too",
      len({a["evidence_hash"] for a in auths}) == 4)

# ── W2: the service accounts, and what each may do ───────────────────────────────────────────
check("service accounts: the four he named exist",
      set(extras.SERVICE_ACCOUNTS) == {"svc-provisioning", "svc-sim", "svc-canary", "svc-market"})
check("service accounts: only provisioning holds admin_federation "
      "(a leaked sim credential must not be able to provision an operator)",
      [n for n, v in extras.SERVICE_ACCOUNTS.items() if v["flags"].get("admin_federation")]
      == ["svc-provisioning"])
check("service accounts: none holds admin_platform (nothing here needs the whole platform)",
      not any(v["flags"].get("admin_platform") for v in extras.SERVICE_ACCOUNTS.values()))
src_extras = (REPO / "scripts/hetzner_demo/standup_extras.py").read_text()
check("service accounts: every one is created with agents hidden from discovery",
      'flags["agents_unlisted_by_default"] = True' in src_extras)

# ── the driver rows ──────────────────────────────────────────────────────────────────────────
drv = (REPO / "scripts/hetzner_demo/standup_driver.py").read_text()
ast.parse(drv)
check("row 34: a fresh frame gets its OWN (empty) canary mTLS map, never production's",
      '("CANARY_MTLS_MAP_FILE", "/app/config/canary_mtls_map.frame-local.json")' in drv)
check("row 52: the image is written to the env as ONE carrier",
      '("FT_REG_IMAGE", args.registry_image)' in drv and '("FT_TEG_IMAGE", args.teg_image)' in drv)
check("row 62: the theme rides the card at birth", 'visual["theme"] = args.theme' in drv)
check("row 66: a production posture turns the limiter bypass OFF",
      '("SANDBOX_BYPASS_RATE_LIMIT", "false" if args.posture == "production" else "true")' in drv)
check("row 66: a production posture + tester fixtures is REFUSED, not silently downgraded "
      "(two declarations disagreeing)",
      'if args.posture == "production" and args.tester_fixtures:' in drv and "die(" in drv)
check("§FRAMELIC: the frame's own licence can be seeded before its first boot",
      '("FEDERATION_LICENSE_KEY", args.federation_license_key)' in drv)
check("row 125: --es-public-url actually reaches the provisioner context "
      "(the operator EVENT_STORE_URL a frame hands out)",
      'ctx.event_store_public_url = (args.es_public_url or "").strip().rstrip("/")' in drv)
check("showcase: the catalog is a driver input, and unset does not fall back to Frame A's",
      "SHOWCASE_CATALOG_JSON" in drv)

# ── row 52 control: the compose must NOT pin the image any more ──────────────────────────────
tmpl = (REPO / "templates/frame-test/docker-compose.frame-test.yml.tmpl").read_text()
check("row 52 CONTROL: the compose no longer PINS the registry image",
      "image: agentvault2-registry-test:latest" not in tmpl)
check("row 52: the compose interpolates it, with a default so `docker compose config` still works",
      "image: ${FT_REG_IMAGE:-agentvault2-registry-test:latest}" in tmpl)
check("row 52: same for the TEG",
      "image: ${FT_TEG_IMAGE:-agentvault2-teg-layer-test:latest}" in tmpl
      and "image: agentvault2-teg-layer-test:latest" not in tmpl)

# ── the four defects the first EU run surfaced (findings 125-128) ────────────────────────────
ext = (REPO / "scripts/hetzner_demo/standup_extras.py").read_text()
check("row 126: the version constant is read from the image the frame WILL RUN, not from a "
      "hardcoded :latest (IMAGE_TAG env beats BUNDLED_IMAGE_TAG, so this one lies for life)",
      "_bundled_tag_of_image(args.registry_image)" in drv)
check("row 126 CONTROL: :latest survives only as the fallback for a caller that named no image",
      drv.index("_bundled_tag_of_image(args.registry_image)")
      < drv.index('_bundled_tag_of_image("agentvault2-registry-a:latest")'))
check("row 127: the authorizations POST names the router's real prefix (/admin/jurisdiction-profile)",
      "/api/v1/admin/jurisdiction-profile/authorizations" in ext
      and "/api/v1/admin/jurisdiction/authorizations" not in ext)
check("row 128: a service-account password meets every class by construction, not by luck",
      "_service_account_password()" in ext and "secrets.token_urlsafe(24)" not in ext)
pw = [extras._service_account_password() for _ in range(200)]
sp = "!@%^&*()_+-=?"
check("row 128: 200/200 generated passwords carry upper+lower+digit+special",
      all(any(c.isupper() for c in p) and any(c.islower() for c in p)
          and any(c.isdigit() for c in p) and any(c in sp for c in p) for p in pw))
check("row 128: none carries a character that .env parsing or compose ${} interpolation eats",
      not any(set(p) & set("$#'\"`\\|;{}[]<>,.:") for p in pw))

print(f"\n{len([1])and''}{'FAILED: ' + ', '.join(FAILED) if FAILED else 'ALL GATES PASS'}")
sys.exit(1 if FAILED else 0)
