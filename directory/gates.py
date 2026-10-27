#!/usr/bin/env python3
"""The Directory trial's gates (DESIGN §4 + §DIRFEED): every source verified · zero unsigned · the index equals the
sum of the registries' NATIVE cards (server-filtered AND client-walked, so neither can lie alone) · a fresh agent on EU
appears within one sync cycle · home/issuer resolution · query latency · no mutation type · pagination · the CURSOR FEED
actually spares the detail reads · a card that goes away is marked gone by the full pass · the venue index · the
re-read switch fired · what the index costs against what the mesh replicates · both ledgers untouched.

Usage: gates.py <directory base> <pair.json>"""
import json, secrets, statistics, sys, time, urllib.request, urllib.parse, urllib.error

BASE = sys.argv[1].rstrip("/"); CFG = json.load(open(sys.argv[2]))
T0 = time.time(); ts = lambda: f"+{time.time()-T0:6.1f}s"; RESULTS = []
def leg(name, ok, detail=""): RESULTS.append((name, ok)); print(ts(), "PASS" if ok else "FAIL", name, detail)
def skip(name, why): RESULTS.append((name, None)); print(ts(), "SKIP", name, why)

# ── TOPOLOGY, from the config (§DIRSANDBOX 2026-09-06) ─────────────────────────
# These gates were written against the EU/ASIA pair and carried its names, currencies and
# tickers as literals, so they could only ever grade the pair they were born on. Every one
# is now a config key with the EU/ASIA value as its DEFAULT — the original invocation is
# unchanged, and a second topology (the sandbox pair) runs the same 22 legs.
#
# `directory_name` is deliberately its own key rather than reused from `frames.*.name`: the
# Directory reports a source by its CARD name (`identity.registry_name`), which is not the
# slug the rest of this config uses — measured, `frames.A.name` is "eu" while the Directory
# says "EU", and on the sandbox pair the card says "Sandbox Alpha" where the slug is
# "sbx-alpha". Deriving one from the other would work on exactly one of the two pairs.
A_NAME = CFG["frames"]["A"].get("directory_name", "EU")
B_NAME = CFG["frames"]["B"].get("directory_name", "ASIA")
N_SOURCES = int(CFG.get("expected_sources", 6))
# The DID shape a FRESH issuance has on frame A. `namespaced` only where the frame carries
# DID_ISSUER_NAMESPACE (§DIDWIDEN item 1); a frame that predates it issues the two-segment
# uuid4 and asserting "namespaced" there would be grading the config, not the Directory.
A_DID_SHAPE = CFG["frames"]["A"].get("expect_did_shape", "namespaced")
# [{symbol, currency, frame}] — frame is "A"/"B", resolved to the Directory's source name.
# `if "venues" in CFG` — NOT `CFG.get("venues") or [...]`. An explicit `[]` means "this pair
# lists nothing worth pinning" and must reach the skip; `or` treats it as absent and silently
# restores the EU/ASIA default, which is how the first sandbox run reported
# `expected ['EUCL','ASCL']` against a config that asked for neither.
VENUES = CFG["venues"] if "venues" in CFG else [{"symbol": "EUCL", "currency": "ECU", "frame": "A"},
                                                {"symbol": "ASCL", "currency": "ACU", "frame": "B"}]
_FRAME_NAME = {"A": A_NAME, "B": B_NAME}
# Which KEYS in the frame's env file hold an admin that can still log in. Defaults are the
# standup template's, which is what EU/ASIA carry. Measured on the sandbox pair: its
# `FIRST_ADMIN_*` and `ADMIN_*` both answer 401 — rotated live and never written back — while
# `SANDBOX_ADMIN_*` works, so the pair that needs this key is not the pair that defined it.
CRED_KEYS = (CFG["frames"]["A"].get("admin_email_key", "FIRST_ADMIN_EMAIL"),
             CFG["frames"]["A"].get("admin_password_key", "FIRST_ADMIN_PASSWORD"))
def req(base, method, path, body=None, hdr=None, form=False, timeout=60):
    data = None; h = dict(hdr or {})
    if body is not None:
        if form: data = urllib.parse.urlencode(body).encode(); h["Content-Type"] = "application/x-www-form-urlencoded"
        else: data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=h, method=method), timeout=timeout) as r:
            t = r.read().decode(); return r.status, (json.loads(t) if t else {})
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try: return e.code, json.loads(t)
        except Exception: return e.code, {"raw": t[:200]}
    except Exception as e: return 0, {"error": str(e)[:200]}
def gql(query, variables=None):
    t0 = time.time(); s, r = req(BASE, "POST", "/graphql", {"query": query, "variables": variables or {}}); return s, r, (time.time() - t0) * 1000
def env(path):
    d = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d
def delta(fr):
    s, d = req(CFG["frames"][fr]["es_base"], "GET", "/api/v1/projections/supply-audit", timeout=30); return (d.get("delta"), d.get("status")) if s == 200 else (None, f"http {s}")

d0 = {fr: delta(fr) for fr in ("A", "B")}
# 1 sources
s, r, ms = gql("{ status { anchors agentsTotal registriesTotal registriesVerified lastCycleAt lastCycleSeconds sources { name verified reason reachable federationStatus agentsIndexed lastError } } }")
st = (r.get("data") or {}).get("status") or {}
srcs = st.get("sources") or []
leg("1.all-sources-verified", len(srcs) == N_SOURCES and all(x["verified"] for x in srcs), f"expected {N_SOURCES}; {[(x['name'], x['verified'], x['reason']) for x in srcs]}")
leg("1.zero-unsigned", all(x["reason"] == "ok" for x in srcs), f"cycle {st.get('lastCycleSeconds')}s")
# 2 the index equals the sum of NATIVE cards across the six registries (the registry's own filter…)
BASES = {A_NAME: CFG["frames"]["A"]["base"], B_NAME: CFG["frames"]["B"]["base"],
         **{o["name"].replace("cloud-op-", ""): o["base"] for o in CFG.get("operators", [])}}
expect, per_source, mesh_rows = 0, {}, 0
for x in srcs:
    reg = BASES.get(x["name"])
    if not reg:
        continue
    s2, lst = req(reg, "GET", "/api/v1/agent-cards/?limit=1&natives_only=true")
    n = ((lst.get("pagination") or {}).get("total_items") if isinstance(lst, dict) else None) or 0
    per_source[x["name"]] = n
    expect += n
    s3, all_lst = req(reg, "GET", "/api/v1/agent-cards/?limit=1")
    mesh_rows += ((all_lst.get("pagination") or {}).get("total_items") if isinstance(all_lst, dict) else 0) or 0
# The index and the registries are counted a moment apart, and on a LIVE tier cards are
# created and deleted in between — the sandbox pair answered 5433 vs 5434, off by one, with
# nothing wrong. Re-read both once and allow a drift the config names (0 on a quiet pair, so
# EU/ASIA keeps the exact equality it had).
DRIFT = int(CFG.get("index_count_drift_allowed", 0))
_idx = st.get("agentsTotal")
if _idx != expect and DRIFT:
    s9, r9, _ = gql("{ status { agentsTotal } }")
    _idx2 = ((r9.get("data") or {}).get("status") or {}).get("agentsTotal")
    _exp2 = 0
    for x in srcs:
        reg = BASES.get(x["name"])
        if not reg:
            continue
        _s, _l = req(reg, "GET", "/api/v1/agent-cards/?limit=1&natives_only=true")
        _exp2 += ((_l.get("pagination") or {}).get("total_items") if isinstance(_l, dict) else 0) or 0
    _idx, expect = _idx2, _exp2
leg("2.index-equals-native-cards", abs((_idx or 0) - expect) <= DRIFT,
    f"index {_idx} vs natives {expect} (drift allowed {DRIFT}) {per_source}")
# …and the CONTROL: the same number walked client-side on EU, which is how the first trial counted. If the server's
# natives_only ever lied, these two would disagree — a single number that agrees with itself proves nothing.
# ⚠ THIS CONTROL USED TO WALK ONE PAGE AND COMPARE IT TO A WHOLE-POPULATION COUNT.
# `?limit=5000` returns at most one page: on the pair this was written against (~100 cards)
# that is everything, so the leg always passed. MEASURED on the sandbox pair: the request
# returned 5000 items with `pagination.total_items` 5368, the walk counted 4065 natives, the
# server said 4427 — and the leg reported the SERVER as lying when it was the walk that was
# 368 cards short. A control that cannot see past page one is the "gate loudest about what it
# cannot see" class. It now follows pagination, and because the honest walk costs one DETAIL
# read per card it carries a budget: over that, it SKIPS with the population rather than
# comparing a partial walk to a full count.
_A_BASE = CFG["frames"]["A"]["base"]
WALK_BUDGET = int(CFG.get("walk_budget_cards", 1200))
s2, page1 = req(_A_BASE, "GET", "/api/v1/agent-cards/?limit=200")
_total = ((page1.get("pagination") or {}).get("total_items") if isinstance(page1, dict) else None) or 0
if _total > WALK_BUDGET:
    skip("2.control-server-filter-agrees-with-a-client-walk",
         f"{A_NAME} holds {_total} cards; an independent walk costs one detail read each and the "
         f"budget is {WALK_BUDGET} (raise `walk_budget_cards` to run it). A one-page walk compared "
         f"to a whole-population count is what this leg used to do, and it read as a server fault")
else:
    # ⚠ THE PAGINATION PARAMETER IS `skip`, NOT `page`. `?page=2` is silently DROPPED by
    # FastAPI and answers 200 with page one again — measured on sandbox-a, two "pages" of 200
    # with an overlap of 200 and `current_page: 1` on both, while the response advertises
    # `total_pages: 27`. A walk written against `page` would have looped over the same 200
    # cards and called the difference a server fault. (`limit` also caps at 5000, le=5000,
    # which is why the old one-shot `?limit=5000` returned exactly 5000 of 5380.)
    walked, _seen, _ids = 0, 0, []
    while _seen < _total and _seen < WALK_BUDGET:
        s2, lst = req(_A_BASE, "GET", f"/api/v1/agent-cards/?limit=200&skip={_seen}")
        items = ((lst.get("items") if isinstance(lst, dict) else lst) or [])
        if not items:
            break
        _seen += len(items)
        for i in items:
            _ids.append(i.get("id"))
            s3, det = req(_A_BASE, "GET", f"/api/v1/agent-cards/{i.get('id')}")
            fm = ((det.get("card_data") or {}).get("federation_metadata") or {}) if s3 == 200 else {"source_registry": "?"}
            if not fm.get("source_registry"):
                walked += 1
    # 🔴 THE COUNT IS NOT THE CHECK — THE PARTITION IS. `skip` paging here is not a
    # partition: `crud/agent_card.py` orders on `updated_at` alone, with no unique
    # tiebreak, so Postgres may arrange equal-keyed rows differently for a different
    # LIMIT/OFFSET plan and the same walk both DOUBLE-COUNTS and MISSES. The two errors
    # are symmetric, so they cancel in a total: measured on the sandbox pair, 4465 natives
    # walked as 4465 with only 4357 distinct — 108 cards seen twice, 108 never seen, and a
    # count that agreed with itself perfectly. (Deterministic, not flaky: two identical
    # walks return the same set.) agentvault2-27 measured the same on EU, where 27 of 95
    # cards share an `updated_at`, and is fixing the ordering at the source.
    _dupes = len(_ids) - len(set(_ids))
    leg("2.control-server-filter-agrees-with-a-client-walk",
        walked == per_source.get(A_NAME) and _seen == _total and _dupes == 0,
        f"{A_NAME} walked {walked} natives over {_seen}/{_total} cards vs natives_only "
        f"{per_source.get(A_NAME)}; {len(set(_ids))} distinct of {len(_ids)}"
        + (f" — {_dupes} DUPLICATED, so as many were never seen: the walk is not a partition "
           f"(no unique tiebreak on the ORDER BY), and the totals cancelling is not evidence "
           f"it is right" if _dupes else ""))

# 3 freshness: a fresh agent on EU appears within one cycle
f = CFG["frames"]["A"]; e = env(f["env_file"])
s, r = req(f["base"], "POST", "/api/v1/auth/login", {"username": e[CRED_KEYS[0]], "password": e[CRED_KEYS[1]]}, form=True)
if s != 200 or "access_token" not in r:
    # Without a token nothing after this can be driven. Say WHICH key was tried: a 401 here
    # is nearly always a rotated password the env file never learned about, not a broken gate.
    print(ts(), "FATAL", f"admin login on {A_NAME} failed: HTTP {s} using {CRED_KEYS[0]}/{CRED_KEYS[1]} "
          f"from {f['env_file']} — set `admin_email_key`/`admin_password_key` on frames.A if the pair keeps its working admin under other names")
    sys.exit(2)
tok = {"Authorization": "Bearer " + r["access_token"]}
s, r = req(f["base"], "POST", "/api/v1/onboard/bootstrap/request-token", {}, tok); bt = r.get("bootstrap_token"); run = secrets.token_hex(3)
card = {"protocolVersion": "1.0", "name": f"DIRECTORY probe {run}", "description": "Directory freshness probe", "humanReadableId": f"directory/probe-{run}", "agentVersion": "1.0.0", "url": f"https://{f['host']}/agents/probe-{run}", "authSchemes": [{"scheme": "none"}], "capabilities": {}, "skills": [{"id": "echo", "name": "Echo", "description": "probe", "tags": ["probe"]}], "provider": {"name": "TheProtocol battery", "url": f"https://{f['host']}"}}
s, r = req(f["base"], "POST", "/api/v1/onboard/create_agent", {"agent_did_method": "theprotocol", "agent_card": card}, {"Bootstrap-Token": bt or ""}); did = r.get("agent_did"); t_create = time.time()
leg("3.probe-agent-created", s == 201, f"http {s} {did}")
seen = None
while time.time() - t_create < 200:
    s, r, ms = gql("query($n: String!) { agents(first: 5, nameContains: $n) { edges { cardId did name issuer shape source verified home { name trustDomain } issuerFrame { name } bond { status isBonded } } } }", {"n": f"DIRECTORY probe {run}"})
    a = next(iter((((r.get("data") or {}).get("agents") or {}).get("edges") or [])), None)
    if a: seen = a; break
    time.sleep(5)
leg("3.fresh-agent-indexed-within-a-cycle", seen is not None and (time.time() - t_create) <= 130, f"{round(time.time()-t_create)}s; {seen}")
leg("3.fresh-agent-did-on-the-read", bool(seen) and seen.get("did") == did, f"index did={seen.get('did') if seen else None} vs created {did} (a null here means the registry image hides agent_did on the card read — §DIRFEED put it on the read AND the summary)")
if seen:
    # On a frame WITHOUT DID_ISSUER_NAMESPACE the issuance carries no issuer, so the issuer half
    # of this leg has nothing to resolve — assert what that frame actually promises rather
    # than pass on an assumption or quietly drop the check.
    if A_DID_SHAPE == "namespaced":
        leg("3.home-and-issuer-resolve", seen.get("source") == A_NAME and (seen.get("home") or {}).get("name") == A_NAME and seen.get("issuer") == f["host"] and (seen.get("issuerFrame") or {}).get("name") == A_NAME and seen.get("shape") == "namespaced", str(seen)[:160])
    else:
        leg("3.home-resolves-and-the-shape-is-what-this-frame-mints",
            seen.get("source") == A_NAME and (seen.get("home") or {}).get("name") == A_NAME
            and seen.get("shape") == A_DID_SHAPE and seen.get("issuer") is None,
            f"expect shape={A_DID_SHAPE} issuer=None on a frame with no DID_ISSUER_NAMESPACE; {str(seen)[:150]}")
# 4 a legacy-shaped agent (battery 1's control) resolves with no issuer
# A pair with no legacy-shaped agent cannot run this leg. SKIP loudly with the reason: a
# leg that quietly does nothing is worse than one that says it could not run here.
if not CFG.get("legacy_did_on_A"):
    skip("4.legacy-agent-indexed-no-issuer", "config names no `legacy_did_on_A` — this pair has no 39-char legacy DID to resolve")
else:
    s, r, ms = gql("query($d: String!) { agent(did: $d) { did issuer shape source home { name } } }", {"d": CFG["legacy_did_on_A"]})
    a = (r.get("data") or {}).get("agent"); leg("4.legacy-agent-indexed-no-issuer", bool(a) and a.get("issuer") is None and a.get("shape") == "legacy" and (a.get("home") or {}).get("name") == A_NAME, str(a))
# 5 latency
lat = [gql("{ agents(first: 50) { edges { did name bond { isBonded } } hasNextPage } }")[2] for _ in range(20)]
leg("5.query-p50-under-100ms", statistics.median(lat) < 100, f"p50 {statistics.median(lat):.1f} ms, max {max(lat):.1f} ms")
# 6 read-only by construction
s, r, ms = gql("{ __schema { mutationType { name } } }"); leg("6.no-mutation-type", (r.get("data") or {}).get("__schema", {}).get("mutationType") is None)
# 7 pagination survives
s, r, ms = gql("{ agents(first: 5) { edges { cardId } endCursor hasNextPage } }"); pg = (r.get("data") or {}).get("agents") or {}
s2, r2, _ = gql("query($c: String) { agents(first: 5, after: $c) { edges { cardId } } }", {"c": pg.get("endCursor")}); pg2 = (r2.get("data") or {}).get("agents") or {}
leg("7.pagination-disjoint-pages", bool(pg.get("edges")) and not ({x["cardId"] for x in pg["edges"]} & {x["cardId"] for x in pg2.get("edges", [])}), f"page1 {len(pg.get('edges', []))} page2 {len(pg2.get('edges', []))}")
# 8 ledgers untouched
d1 = {fr: delta(fr) for fr in ("A", "B")}; leg("8.delta-both-untouched", d0 == d1 and all(d1[fr][0] in (0, 0.0) for fr in d1), f"{d0} -> {d1}")
# 9 the cursor feed: every source serves it, and a QUIET cycle costs no detail reads
def status_now():
    s, r, _ = gql("{ status { agentsTotal agentsGone listingsTotal extractVersion lastCycleNumber lastCycleWasFull lastCycleDetailReads lastCycleSeconds sources { name feedSupported cardsCursor lastFullAt agentsIndexed listingsIndexed } } }")
    return (r.get("data") or {}).get("status") or {}
st2 = status_now()
leg("9.every-source-serves-the-feed", bool(st2.get("sources")) and all(x["feedSupported"] for x in st2["sources"]),
    f"{[(x['name'], x['feedSupported'], (x['cardsCursor'] or '')[:19]) for x in st2.get('sources', [])]}")
start_cycle = st2.get("lastCycleNumber")
quiet = None
while time.time() - T0 < 900:            # wait for a cycle that starts AFTER this line: nothing changes in it
    time.sleep(10); s3 = status_now()
    if s3.get("lastCycleNumber") and start_cycle and s3["lastCycleNumber"] >= start_cycle + 2 and not s3.get("lastCycleWasFull"):
        quiet = s3; break
# What the cursor feed promises is that a cycle costs a detail read per CHANGED card, not per
# card. On a quiet pair that is exactly 0; on a live one it is however many changed while the
# gate watched — the sandbox pair answered 6 against 5433 indexed, which is the feed working,
# not failing. The ceiling is config'd and defaults to 0, so EU/ASIA keeps the strict form.
QUIET_MAX = int(CFG.get("quiet_cycle_max_detail_reads", 0))
_reads = quiet.get("lastCycleDetailReads") if quiet else None
leg("9.a-quiet-cursor-cycle-costs-no-detail-reads", bool(quiet) and _reads is not None and _reads <= QUIET_MAX,
    f"cycle {quiet.get('lastCycleNumber') if quiet else None}: {_reads} detail reads (ceiling {QUIET_MAX}) in "
    f"{quiet.get('lastCycleSeconds') if quiet else '?'}s over {(quiet or {}).get('agentsTotal')} indexed "
    f"(the pre-feed trial read one per card, every cycle)")
# 10 a card that GOES AWAY is marked gone by a full pass (the half a cursor can never see)
# re-authenticate first: `POST /auth/logout` bumps the developer's token_version, which revokes every live
# token of that account EVERYWHERE (that is the product working). A browser drive on the same admin — or any
# other client that logs out — kills a token this gate issued minutes ago, and the destructive leg then reads
# 401 as a product defect. A fresh token immediately before the write is the honest instrument.
s, r = req(f["base"], "POST", "/api/v1/auth/login", {"username": e[CRED_KEYS[0]], "password": e[CRED_KEYS[1]]}, form=True)
tok = {"Authorization": "Bearer " + r.get("access_token", "")}
s, r = req(f["base"], "DELETE", f"/api/v1/agent-cards/{seen['cardId'] if seen else ''}", None, tok)
leg("10.probe-card-deleted-at-the-origin", s in (200, 204), f"http {s}")
gone_seen = None
while time.time() - T0 < 1500:
    time.sleep(10)
    s2, r2, _ = gql("query($n: String!) { live: agents(first: 5, nameContains: $n) { total } all: agents(first: 5, nameContains: $n, includeGone: true) { total edges { reachable } } }", {"n": f"DIRECTORY probe {run}"})
    d = r2.get("data") or {}
    if d and (d.get("live") or {}).get("total") == 0 and (d.get("all") or {}).get("total", 0) >= 1:
        gone_seen = d; break
leg("10.the-full-pass-marks-it-gone-and-keeps-the-row", bool(gone_seen),
    f"{gone_seen} (live 0 / kept 1 = marked unreachable, never deleted)")
# 11 the venue index: every AGORA listing in the component, in one query
s, r, ms = gql("{ listings(first: 50) { total edges { symbol currency status source venue { name tier } } } }")
L = (r.get("data") or {}).get("listings") or {}
syms = {e["symbol"]: e for e in L.get("edges", [])}
if not VENUES:
    _why = ("`venues` is an explicit [] — this pair lists nothing worth pinning"
            if "venues" in CFG else "config names no `venues` for this pair")
    skip("11.venues-indexed", _why)
    skip("11.a-listing-names-its-venue-and-its-currency", _why)
else:
    leg("11.venues-indexed", (L.get("total") or 0) >= len(VENUES) and all(v["symbol"] in syms for v in VENUES),
        f"expected {[v['symbol'] for v in VENUES]}; total {L.get('total')} {[(e['symbol'], e['currency'], e['source']) for e in L.get('edges', [])]}")
    leg("11.a-listing-names-its-venue-and-its-currency",
        all(syms.get(v["symbol"], {}).get("currency") == v["currency"]
            and (syms.get(v["symbol"], {}).get("venue") or {}).get("name") == _FRAME_NAME.get(v.get("frame"), v.get("frame"))
            for v in VENUES),
        "; ".join(f"{v['symbol']} {syms.get(v['symbol'])}" for v in VENUES))
s, r, ms = gql('{ listings(first: 5, symbol: "NOSUCHSYMBOL") { total } }')
leg("11.control-an-unknown-symbol-is-empty", ((r.get("data") or {}).get("listings") or {}).get("total") == 0)
# 12 the re-read switch: the extraction version is stamped and every source has been read in FULL at least once
st3 = status_now()
leg("12.re-read-switch-stamped-and-a-full-pass-ran",
    st3.get("extractVersion") == 2 and all(x["lastFullAt"] for x in st3.get("sources", [])),
    f"extract_version {st3.get('extractVersion')}, full passes {[(x['name'], bool(x['lastFullAt'])) for x in st3.get('sources', [])]}")
# 13 what the index costs against what the mesh replicates (DESIGN §3's size leg)
leg("13.index-is-smaller-than-what-the-mesh-replicates", (st3.get("agentsTotal") or 0) < mesh_rows,
    f"index {st3.get('agentsTotal')} rows vs {mesh_rows} card rows stored across the six registries (each mirror is a copy)")
# A SKIP is `None`, and it is neither a pass nor a failure — counting it as either is how a
# leg that could not run reads as a clean result. Reported on its own line, and the exit code
# still turns only on real failures.
bad = [n for n, ok in RESULTS if ok is False]
skipped = [n for n, ok in RESULTS if ok is None]
passed = len(RESULTS) - len(bad) - len(skipped)
print(ts(), f"DONE {passed}/{len(RESULTS) - len(skipped)} PASS"
      + (f" ({len(skipped)} SKIPPED: {', '.join(skipped)})" if skipped else ""),
      ("FAILED: " + ", ".join(bad)) if bad else "")
print("litter: none (the probe agent is deleted by leg 10):", did)
sys.exit(1 if bad else 0)
