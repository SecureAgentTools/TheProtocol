"""The Auditor — Configuration."""
import os
from pathlib import Path

EVENT_STORE_URL = os.getenv("EVENT_STORE_URL", "http://agentvault_event_store:8200")
EVENT_STORE_KEY = os.getenv(
    "EVENT_STORE_INTERNAL_KEY",
    ""  # §KEYROT 2026-09-05: env-only (EVENT_STORE_INTERNAL_KEY); a live key sat here as the default,
)
# §MTLSHOPS T2 (S4, 2026-09-15): the client certificate and trust bundle of an https store read (tls_client.py). A solo
# auditor presents its own SVID to the store's mTLS sidecar. Unset, an https read verifies against the system roots and
# presents nothing; http reads are unchanged.
AUDITOR_TLS_CERT = os.getenv("AUDITOR_TLS_CERT", "")
AUDITOR_TLS_KEY = os.getenv("AUDITOR_TLS_KEY", "")
AUDITOR_TLS_CA = os.getenv("AUDITOR_TLS_CA", "")
REGISTRY_A_URL = os.getenv("REGISTRY_URL", "http://agentvault_registry_a:8000")
AGENT_DID = os.getenv("AGENT_DID", "pending")
AGENT_NAME = os.getenv("AGENT_NAME", "The Auditor")
AUDIT_INTERVAL = int(os.getenv("AUDIT_INTERVAL", "60"))
AUDITOR_API_PORT = int(os.getenv("AUDITOR_API_PORT", "8045"))
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", "/app/frontend"))
# §SOVKIT K0 (2026-09-14): env-only, no defaults. A live login sat here as a code default (the retired
# Commander password, rotated §CMDROTATE 2026-08-21) and shipped in every image; nothing in src/ reads them
# beyond this line. Unset means unset.
COMMANDER_EMAIL = os.getenv("COMMANDER_EMAIL", "")
COMMANDER_PASSWORD = os.getenv("COMMANDER_PASSWORD", "")

# Auditor version (surfaced in /health + footer)
AUDITOR_VERSION = os.getenv("AUDITOR_VERSION", "2.1.0")

# ── Multi-frame, DUAL-MODE configuration (2026-06-02) ──────────────────────
# The Auditor is a SINGLE app that audits BOTH the production frames AND the
# sandbox frames. Each frame carries a `mode` ('prod'|'sandbox'); the frontend
# shows one mode at a time via a toggle whose default is derived from the
# subdomain (auditor.* → prod, sandbox-auditor.* → sandbox). A frame appears
# ONLY when it has a URL or a DSN configured, so unconfigured slots (e.g. a
# not-yet-live prod Frame C) are simply absent rather than broken.
#
# Direct-DB atomic invariant (v2.1): the auditor reads each frame's EventStore
# Postgres directly and computes the supply invariant in ONE SQL statement
# (single MVCC snapshot) — immune to the read-skew that makes the HTTP
# /supply-audit endpoint report transient phantom deltas while CQRS batch
# updates are in flight. DSNs are optional; without one the auditor falls back
# to the HTTP live-read delta.
#
# Env convention: prod uses the bare FRAME_*; sandbox uses SBX_FRAME_*. Frame C
# is prepared in BOTH modes — sandbox C is live (eventstore_test_c); prod C is a
# ready placeholder (unset → absent until the 3rd prod frame ships).
ATOMIC_TOLERANCE = float(os.getenv("ATOMIC_TOLERANCE", "0.000001"))
# I3 per-user conservation: an agent is "negative" only below this floor, so
# sub-cent projection dust never raises a breach (the real cases are whole AVT).
PER_USER_TOLERANCE = float(os.getenv("PER_USER_TOLERANCE", "0.01"))

# ── Native-supply per-currency reconciliation (V6, 2026-06-19) ─────────────
# The ledger is currency-blind, so an FX-active frame reads circulating > issued
# (circulating sums ALL currencies on the books; issued is native mints). V6 proves
# native conservation: native_circulating = circulating − transit_net must reconcile
# with typed mints (true_minted − true_burned) within this band (fee/rounding/in-flight
# skew). Beyond it → native_supply_ok=false = a real finding (e.g. a mis-stamped mint).
NATIVE_SUPPLY_TOL = float(os.getenv("NATIVE_SUPPLY_TOL", "50") or 50)

# ── True mint/burn (A2, 2026-05-30) ────────────────────────────────────────
# supply_summary.tokens_issued / tokens_destroyed are per-event net ACCUMULATORS
# that keep the CQRS projection's atomic invariant Δ=0. Post-cutover they fold in
# transfer / cross-frame LEGS (a split-txid transfer arrives as two single-sided
# events) so they are NOT real mint/burn. The TRUE figures are the typed supply
# events on the immutable log since the balance-integrity baseline, bounded at
# the baseline date to exclude pre-cutover guard-era inflation.
TRUE_SUPPLY_SINCE = os.getenv("TRUE_SUPPLY_SINCE", "2026-05-29T00:00:00+00:00")

# Back-compat: a legacy prod env relied on FRAME_A_EVENT_STORE_URL defaulting to
# EVENT_STORE_URL. Preserve that so an un-migrated prod deployment still shows A.
if not os.getenv("FRAME_A_EVENT_STORE_URL"):
    os.environ["FRAME_A_EVENT_STORE_URL"] = EVENT_STORE_URL

# (mode, frame-id, display-name, url-env, dsn-env, currency) — id is GLOBALLY
# unique so the audit loop / latest_results / metrics key cleanly across modes.
# currency is the per-frame token ticker surfaced in the UI: three sovereign
# currencies — Frame A = AVT, Frame B = JDAY (relabeled from AVT 2026-06-14),
# Frame C = BVT. Each is env-overridable (FRAME_<X>_CURRENCY / SBX_FRAME_<X>_CURRENCY)
# so any re-denominated frame needs no code change.
_FRAME_SLOTS = [
    # §LEGACYTIER 2026-09-09 (his word "i want a third where you move the legacy stack in"): registry-a /
    # frame-b / frame-c are the RETIRING stack, reachable at a|frame-b|frame-c.theprotocol.cloud with their
    # operators off. They are still real ledgers with real history, so they keep their attestation chain
    # (ATTEST_MODES) and only leave the 'prod' tier, which now means the live EU/ASIA cluster.
    ("legacy",  "frame-a",     "Frame A", "FRAME_A_EVENT_STORE_URL",     "FRAME_A_ES_DSN",     "AVT"),
    ("legacy",  "frame-b",     "Frame B", "FRAME_B_EVENT_STORE_URL",     "FRAME_B_ES_DSN",     "JDAY"),
    ("legacy",  "frame-c",     "Frame C", "FRAME_C_EVENT_STORE_URL",     "FRAME_C_ES_DSN",     "BVT"),
    ("sandbox", "sbx-frame-a", "Frame A", "SBX_FRAME_A_EVENT_STORE_URL", "SBX_FRAME_A_ES_DSN", "AVT"),
    ("sandbox", "sbx-frame-b", "Frame B", "SBX_FRAME_B_EVENT_STORE_URL", "SBX_FRAME_B_ES_DSN", "AVT"),
    ("sandbox", "sbx-frame-c", "Frame C", "SBX_FRAME_C_EVENT_STORE_URL", "SBX_FRAME_C_ES_DSN", "BVT"),
    # §BATCH9 (2026-09-06, his word "list them under sandbox and wire the new sandboxes also"): the fresh pair
    # (NOT promoted — a sandbox dry run) and the live sandbox tier (sbx-alpha / sbx-beta, 2026-09-03). The
    # retired sandbox A/B/C slots above stay declared; their env is unset in the compose, so the loop skips them.
    ("sandbox", "juice",     "JUICE",         "SBX_JUICE_EVENT_STORE_URL", "SBX_JUICE_ES_DSN", "JUICE"),
    ("sandbox", "brrr",      "BRRR",          "SBX_BRRR_EVENT_STORE_URL",  "SBX_BRRR_ES_DSN",  "BRRR"),
    ("sandbox", "sbx-alpha", "Sandbox Alpha", "SBX_ALPHA_EVENT_STORE_URL", "SBX_ALPHA_ES_DSN", "SBXA"),
    ("sandbox", "sbx-beta",  "Sandbox Beta",  "SBX_BETA_EVENT_STORE_URL",  "SBX_BETA_ES_DSN",  "SBXB"),
]

# Per-mode EventStore HTTP key (the live-read fallback). Prod + sandbox ES use
# different internal keys; the atomic DSN path is key-agnostic, but the HTTP
# supply-summary needs the right one per mode so both modes' live deltas read.
_MODE_KEYS = {
    "prod": EVENT_STORE_KEY,
    # The legacy frames never carried FRAME_<X>_EVENT_STORE_KEY: frame-a IS this key's ES, and frame-b/c
    # are read over their DSN (the atomic path). Named here so the fallback is a decision, not an accident.
    "legacy": EVENT_STORE_KEY,
    # §SOVKIT K0 (2026-09-14): env-only; the retired sandbox tier's key was a code default here (stale since 09-03).
    "sandbox": os.getenv("SBX_EVENT_STORE_KEY", ""),
}

# ── FX reserve solvency (independent I2 invariant, 2026-06-04) ──────────────
# The auditor reads each frame's @fx_reserve from materialized_balances (the SAME
# single-statement DB snapshot as the supply invariant) and compares it to its OWN
# configured floor — it NEVER trusts the registry's /fx/pool or /cross-frame-audit
# (those belong to the audited system). A frame is a "reserve frame" iff the
# @fx_reserve row exists; non-FX frames (e.g. Frame B) simply report no solvency.
# This closes the structural blind spot of the supply invariant (I1): @fx_reserve
# and @fx_router are ordinary balances counted in Σ(liquid+staked), so a draining
# reserve or stranded router residue keeps Δ=0 — I1 alone cannot see it.
FX_RESERVE_DID = os.getenv("FX_RESERVE_DID", "did:theprotocol:teg_system_fx_reserve")


def _fx_floor(ccy: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(f"FX_RESERVE_FLOOR_{ccy.upper()}", "") or default))
    except (TypeError, ValueError):
        return default


# Per-currency reserve floors (env-overridable). Defaults = the locked sandbox values.
FX_RESERVE_FLOORS: dict[str, float] = {
    "AVT": _fx_floor("AVT", 100000.0),
    "BVT": _fx_floor("BVT", 50000.0),
}
# Reserve fuel-gauge reads "full" at ≥ this multiple of the floor.
FX_SOLVENCY_COMFORT_MULT = float(os.getenv("FX_SOLVENCY_COMFORT_MULT", "10") or 10)
# Status: BREACH below floor · LOW below floor × WARN_FACTOR · else SOLVENT.
FX_SOLVENCY_WARN_FACTOR = float(os.getenv("FX_SOLVENCY_WARN_FACTOR", "1.5") or 1.5)
# op→op @fx_router residue: the router DID is a dynamically-onboarded system agent,
# so configure it per frame via FRAME_<X>_FX_ROUTER_DID / SBX_FRAME_<X>_FX_ROUTER_DID.
# Residue above this threshold (in the frame's currency) flags a stranded route.
FX_ROUTER_RESIDUE_THRESHOLD = float(os.getenv("FX_ROUTER_RESIDUE_THRESHOLD", "1000") or 1000)

# ── AGORA share registry (read-only, 2026-06-17) ───────────────────────────
# The AGORA org-stock cap table (who holds which shares) lives in each frame's
# REGISTRY Postgres (tables org_share_positions + exchange_listings), NOT the
# EventStore — shares are the registry ledger. To surface stock holders the same
# way it surfaces currency holders, the auditor opens a SECOND read-only pool per
# frame to the registry DB via FRAME_<X>_REG_DSN (sandbox: SBX_FRAME_<X>_REG_DSN).
# Optional + graceful: unset → the Share Registry panel is simply absent for that
# frame (mirrors how FRAME_C_ES_DSN was introduced — deploy order is not load-bearing).
# §SOVKIT K2 (2026-09-14) — SOLO MODE: a frame ships its own auditor. `AUDITOR_SOLO=true` audits ONLY the frames
# named in AUDITOR_EXTRA_FRAMES_FILE / _JSON (one entry: the frame itself) and consults none of the slot table
# above, whose env names describe THIS host's fleet; without it the forced Frame A slot (EVENT_STORE_URL's
# default) would make a solo auditor show a phantom "Frame A" beside the one frame it can reach.
AUDITOR_SOLO = (os.getenv("AUDITOR_SOLO", "") or "").strip().lower() in ("1", "true", "yes", "on")
FRAMES: list[dict] = []
for _mode, _fid, _name, _url_env, _dsn_env, _ccy in ([] if AUDITOR_SOLO else _FRAME_SLOTS):
    _url = (os.getenv(_url_env, "") or "").strip()
    _dsn = (os.getenv(_dsn_env, "") or "").strip()
    if _url or _dsn:
        # Per-frame currency, env-overridable: FRAME_A_EVENT_STORE_URL → FRAME_A_CURRENCY
        _ccy_env = _url_env.replace("_EVENT_STORE_URL", "_CURRENCY")
        _currency = (os.getenv(_ccy_env, "") or "").strip().upper() or _ccy
        _router_did = (os.getenv(_url_env.replace("_EVENT_STORE_URL", "_FX_ROUTER_DID"), "") or "").strip()
        # Registry DB DSN (share cap table). Derived: FRAME_A_EVENT_STORE_URL → FRAME_A_REG_DSN.
        _reg_dsn = (os.getenv(_url_env.replace("_EVENT_STORE_URL", "_REG_DSN"), "") or "").strip()
        # TEG DB DSN (V6 currency attribution). cross_teg_transfers is the only
        # currency-aware money table; the auditor opens a THIRD read-only pool to it
        # per frame via FRAME_<X>_TEG_DSN. Optional — unset → currency attribution omitted.
        _teg_dsn = (os.getenv(_url_env.replace("_EVENT_STORE_URL", "_TEG_DSN"), "") or "").strip()
        FRAMES.append({
            "id": _fid, "name": _name, "url": _url, "dsn": _dsn,
            # §BATCH9: a per-frame EventStore key (FRAME_<X>_EVENT_STORE_KEY) beats the per-mode one — every
            # provisioned frame has its own INTERNAL_API_KEY, so one key per mode stopped being true.
            "mode": _mode, "key": (os.getenv(_url_env.replace("_EVENT_STORE_URL", "_EVENT_STORE_KEY"), "") or "").strip()
                                 or _MODE_KEYS.get(_mode, EVENT_STORE_KEY),
            "currency": _currency,
            "fx_reserve_floor": FX_RESERVE_FLOORS.get(_currency, 0.0),
            "fx_router_did": _router_did,
            "reg_dsn": _reg_dsn,
            "teg_dsn": _teg_dsn,
            # §MTLSHOPS (a): a built-in slot's URL and key come from this host's own env, so it keeps the mode-key fallback
            "builtin": True, "public_only": False, "public_read": False,
        })

# ── AGORA venues beyond the frames (2026-08-27) ────────────────────────────
# A FRAME is the unit of money and of the Δ invariant. A VENUE is the unit of a
# share register — and since the cloud operators started listing their own orgs,
# most venues are NOT frames: 13 of the federation's 16 venues are cloud-ops with
# their own registry Postgres. The auditor read only the three frame registries,
# so every share on an op venue was outside its sight, and NOTHING said so.
#
# Listings inside a registry are already discovered by querying exchange_listings,
# so a NEW STOCK on a wired venue appears with no config change at all. Wiring a
# NEW VENUE is one entry here:
#   VENUE_REG_DSNS_JSON={"op-berlin":{"dsn":"postgresql://...","currency":"AVT","frame":"frame-a"}}
# A bare string value is accepted as shorthand for {"dsn": ...}.
#
# Read-only and graceful: an unreachable venue is reported as an ERROR row rather
# than dropped, because a venue that silently vanishes from an audit is the exact
# blindspot this block exists to close.
#
# §OPDIST (2026-09-16): the list is FILLED below, after the extra-frames carrier is defined, by read_venues() and
# apply_venues() — the carrier and the in-place reload FRAMES got at §FRAMEKIT P3.1. Built at import from env, a venue
# change cost the recreate that re-audits every tier, so nobody made one: the fleet list held 13 venues, all stopped
# operators, 0 reachable, and none of the 6 that run.
VENUES: list[dict] = []

# id → mode, and the ordered list of modes that actually have ≥1 frame.
# §BATCH10 finding 7: frames the standup driver wires arrive as ONE JSON list in AUDITOR_EXTRA_FRAMES_JSON
# ([{mode,id,name,currency,url,dsn,key}]) — no slot table edit, no rebuild per frame. A bad entry is skipped and named.
# §FRAMEKIT P3.1 (2026-09-12): that list now lives in a FILE the host rewrites (AUDITOR_EXTRA_FRAMES_FILE, a
# directory mount so a replaced inode is seen) and is re-applied IN PLACE by POST /api/auditor/admin/reload-frames —
# wiring or unwiring a frame no longer recreates the auditor, which re-audited every tier (load 120 on the host).
# The env carrier is the fallback an older checkout still boots from; when the file exists it is the ONE source.
import json as _json_extra

EXTRA_FRAMES_FILE: str = (os.getenv("AUDITOR_EXTRA_FRAMES_FILE", "") or "").strip()
BUILTIN_FRAME_IDS: frozenset[str] = frozenset(f["id"] for f in FRAMES)

# §MTLSHOPS (a) (2026-09-15, his decision; agentvault2-85's calls). The slot shapes this auditor reads, listed on
# /api/auditor/modes so a slot writer asks before it writes one. A public-only frame is one whose databases take TLS
# clients with a frame certificate only: this host reads its public supply audit and nothing else; a public reading never
# feeds the atomic status, CONSERVED, the uptime or the streak, and opens an incident only after
# PUBLIC_BREACH_READINGS consecutive BREACH readings.
SLOT_SHAPES: tuple = ("public_only", "public_read")
PUBLIC_BREACH_READINGS: int = int(os.getenv("AUDITOR_PUBLIC_BREACH_READINGS", "5") or 5)
PUBLIC_ONLY_REASON: str = ("this frame's databases take TLS clients with a frame certificate only, and this host holds none; "
                           "the frame's own auditor makes this check and holds its attestation")


def _extra_frame(x: dict) -> dict:
    """One extra-frame entry → the FRAMES shape (raises on a malformed entry; the caller skips and names it).

    §MTLSHOPS (a) (2026-09-15): an extra slot never inherits a mode key; it carries its own or none (agentvault2-85: a
    slot's URL is written by whoever wrote the slot, so the host's key must not follow it). `public_read` marks a live read
    of the frame's public supply audit (no key); `public_only` is a public read and nothing else (no DSN at all)."""
    fid = str(x["id"]); mode = str(x.get("mode") or "sandbox"); ccy = str(x.get("currency") or "").upper()
    public_only = bool(x.get("public_only"))
    public_read = public_only or bool(x.get("public_read"))
    return {
        "id": fid, "name": str(x.get("name") or fid), "url": str(x.get("url") or ""),
        "dsn": "" if public_only else str(x.get("dsn") or ""),
        "mode": mode, "key": "" if public_read else str(x.get("key") or ""),
        "currency": ccy, "fx_reserve_floor": FX_RESERVE_FLOORS.get(ccy, 0.0),
        "fx_router_did": "" if public_only else str(x.get("fx_router_did") or ""),
        "reg_dsn": "" if public_only else str(x.get("reg_dsn") or ""),
        "teg_dsn": "" if public_only else str(x.get("teg_dsn") or ""),
        "builtin": False, "public_only": public_only, "public_read": public_read,
    }


def read_extra_frames() -> tuple[list, str]:
    """(entries, source). The file when it exists — the env is then ignored, one carrier — else the env."""
    if EXTRA_FRAMES_FILE and os.path.exists(EXTRA_FRAMES_FILE):
        try:
            with open(EXTRA_FRAMES_FILE) as fh:
                data = _json_extra.load(fh)
            return (list(data) if isinstance(data, list) else []), EXTRA_FRAMES_FILE
        except Exception as e:  # noqa: BLE001 — a malformed file must not stop the auditor; it is named
            print(f"[config] {EXTRA_FRAMES_FILE} unparsable: {e}")
            return [], f"{EXTRA_FRAMES_FILE} (unparsable)"
    try:
        data = _json_extra.loads(os.getenv("AUDITOR_EXTRA_FRAMES_JSON", "") or "[]")
        return (list(data) if isinstance(data, list) else []), "env:AUDITOR_EXTRA_FRAMES_JSON"
    except Exception as e:  # noqa: BLE001
        print(f"[config] AUDITOR_EXTRA_FRAMES_JSON unparsable: {e}")
        return [], "env:AUDITOR_EXTRA_FRAMES_JSON (unparsable)"


FRAME_MODE: dict[str, str] = {}
MODES: list[str] = []


def apply_extra_frames(extra: list) -> dict:
    """Mutate FRAMES / FRAME_MODE / MODES IN PLACE (main.py holds them by name). Built-in env slots never
    move; an extra id already present is replaced in place (its DSNs may have changed); ids gone from the
    list are removed. Returns what changed."""
    wanted: dict[str, dict] = {}
    for x in extra if isinstance(extra, list) else []:
        try:
            f = _extra_frame(x)
        except Exception as e:  # noqa: BLE001
            print(f"[config] extra frame entry skipped: {e}")
            continue
        if f["id"] in BUILTIN_FRAME_IDS:
            continue   # an env slot is the older carrier of the same frame; it wins, the entry is inert
        wanted[f["id"]] = f
    added, removed, replaced = [], [], []
    for f in list(FRAMES):
        if f["id"] not in BUILTIN_FRAME_IDS and f["id"] not in wanted:
            FRAMES.remove(f); removed.append(f["id"])
    for fid, f in wanted.items():
        idx = next((i for i, g in enumerate(FRAMES) if g["id"] == fid), None)
        if idx is None:
            FRAMES.append(f); added.append(fid)
        elif FRAMES[idx] != f:
            FRAMES[idx] = f; replaced.append(fid)
    FRAME_MODE.clear(); FRAME_MODE.update({f["id"]: f["mode"] for f in FRAMES})
    MODES[:] = [m for m in ("prod", "sandbox", "legacy") if any(f["mode"] == m for f in FRAMES)] or ["prod"]
    return {"added": added, "removed": removed, "replaced": replaced, "frames": [f["id"] for f in FRAMES]}


_EXTRA, EXTRA_FRAMES_SOURCE = read_extra_frames()
apply_extra_frames(_EXTRA)
DEFAULT_MODE: str = MODES[0]

# ── AGORA venues: the carrier and the reload (§OPDIST, 2026-09-16) ─────────
# `venues.json` BESIDE the extra-frames file, unless AUDITOR_VENUES_FILE names another. That file already lives in a
# DIRECTORY mount (so a replaced inode is seen), so a frame's kit auditor gains this carrier with no compose change and
# no new mount. Same shape as the env map and the same precedence as frames: the file when it exists, else the env.
VENUES_FILE: str = (os.getenv("AUDITOR_VENUES_FILE", "") or "").strip() or (
    os.path.join(os.path.dirname(EXTRA_FRAMES_FILE), "venues.json") if EXTRA_FRAMES_FILE else "")


def _venue_entry(name: str, cfg) -> dict:
    """One venue map entry → the VENUES shape. Raises on an entry with no dsn; the caller skips it and NAMES it."""
    if isinstance(cfg, str):
        cfg = {"dsn": cfg}
    dsn = str((cfg or {}).get("dsn") or "").strip()
    if not dsn:
        raise ValueError(f"venue {name!r} has no dsn")
    return {
        "id": f"venue:{name}",
        "name": name,
        "reg_dsn": dsn,
        "currency": str((cfg or {}).get("currency") or "").strip().upper(),
        "frame": str((cfg or {}).get("frame") or "").strip(),
        "mode": str((cfg or {}).get("mode") or "prod").strip(),
    }


def read_venues() -> tuple[dict, str]:
    """(map, source). The file when it exists — the env is then ignored, one carrier — else the env. An unparsable
    carrier answers an empty map with the source marked "(unparsable)", so a caller can refuse to apply it."""
    if VENUES_FILE and os.path.exists(VENUES_FILE):
        try:
            with open(VENUES_FILE) as fh:
                data = _json_extra.load(fh)
            return (dict(data) if isinstance(data, dict) else {}), VENUES_FILE
        except Exception as e:  # noqa: BLE001 — a malformed file must not stop the auditor; it is named
            print(f"[config] {VENUES_FILE} unparsable: {e}")
            return {}, f"{VENUES_FILE} (unparsable)"
    try:
        data = _json_extra.loads(os.getenv("VENUE_REG_DSNS_JSON", "") or "{}")
        return (dict(data) if isinstance(data, dict) else {}), "env:VENUE_REG_DSNS_JSON"
    except Exception as e:  # noqa: BLE001
        print(f"[config] VENUE_REG_DSNS_JSON unparsable: {e}")
        return {}, "env:VENUE_REG_DSNS_JSON (unparsable)"


def apply_venues(mapping: dict) -> dict:
    """Mutate VENUES IN PLACE (main.py holds it by name): an id already present is replaced in place when its entry
    changed, ids gone from the map are removed. Returns what changed. Skipped entries are printed by name."""
    wanted: dict[str, dict] = {}
    for vname, vcfg in (mapping.items() if isinstance(mapping, dict) else []):
        try:
            v = _venue_entry(str(vname), vcfg)
        except Exception as e:  # noqa: BLE001
            print(f"[config] venue entry skipped: {e}")
            continue
        wanted[v["id"]] = v
    added, removed, replaced = [], [], []
    for v in list(VENUES):
        if v["id"] not in wanted:
            VENUES.remove(v); removed.append(v["id"])
    for vid, v in wanted.items():
        idx = next((i for i, g in enumerate(VENUES) if g["id"] == vid), None)
        if idx is None:
            VENUES.append(v); added.append(vid)
        elif VENUES[idx] != v:
            VENUES[idx] = v; replaced.append(vid)
    return {"added": added, "removed": removed, "replaced": replaced, "venues": [v["name"] for v in VENUES]}


_VENUE_MAP, VENUES_SOURCE = read_venues()
apply_venues(_VENUE_MAP)

# Which tiers carry a TPSA-1 attestation chain. A deliberately-dark sandbox would flood the chain with
# ERROR attestations, so it is excluded; the legacy frames are NOT — they hold an existing signed chain
# whose prev_hash links would simply stop if this were keyed on the literal "prod".
ATTEST_MODES: frozenset[str] = frozenset(
    (os.getenv("AUDITOR_ATTEST_MODES", "") or "prod,legacy").replace(" ", "").split(",")
) - {""}

# ── Maintenance mode (reusable; runtime-togglable) ─────────────────────────
# Authoritative state lives in the SQLite `meta` table so it can be flipped live
# via the API without a rebuild. These env vars only SEED the initial state the
# first time the auditor boots against a fresh DB.
MAINTENANCE_SEED_ACTIVE = os.getenv("MAINTENANCE_ACTIVE", "false").lower() in ("1", "true", "yes")
MAINTENANCE_SEED_TITLE = os.getenv("MAINTENANCE_TITLE", "Maintenance — Balance-Integrity Rollout")
MAINTENANCE_SEED_MESSAGE = os.getenv(
    "MAINTENANCE_MESSAGE",
    "CQRS balance-integrity cutover in progress across frames. Transient "
    "live-read deltas are expected and safe — the atomic invariant is the source "
    "of truth. Breaches in this window are deliberately caused and mitigated.",
)
MAINTENANCE_SEED_PATCH_REF = os.getenv("MAINTENANCE_PATCH_REF", "pass73.3.20 · auditor v2.1")

# Token gating writes to the maintenance/reset endpoints. Reads are public (the
# banner needs them). If unset, write endpoints are disabled (safe default).
AUDITOR_ADMIN_TOKEN = os.getenv("AUDITOR_ADMIN_TOKEN", "")
