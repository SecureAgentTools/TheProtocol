#!/usr/bin/env python3
"""TheProtocol EigenTrust Simulation — transfers only, A2A payment on every transfer."""
import asyncio, argparse, collections, hashlib, json, math, os, random, sys, time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "theprotocol-sdk" / "src"))
from theprotocol.payment import PaymentClient

TRANSFER_MIN, TRANSFER_MAX = 1.0, 50.0
A2A_TTL = 300
# No auto-funding — fund agents once before running. Transfers are circular,
# fees drain ~1 AVT/s. 10K per agent × 139 agents lasts ~16 days at 8 TX/s.
REGISTRIES = {
    "Registry-A":    {"port": 8000,  "frame": "A"},
    "Op-Washington": {"port": 27200, "frame": "A"},
    "Op-London":     {"port": 27300, "frame": "A"},
    "Op-Paris":      {"port": 27400, "frame": "A"},
    "Op-Berlin":     {"port": 27500, "frame": "A"},
    "Frame-B":       {"port": 8100,  "frame": "B"},
    "Op-Tokyo":      {"port": 27000, "frame": "B"},
    "Op-Singapore":  {"port": 27100, "frame": "B"},
    "Op-Sydney":     {"port": 27600, "frame": "B"},
    "Op-Seoul":      {"port": 27700, "frame": "B"},
    # Frame C (BVT, 2nd currency) — §framec-sim 2026-06-06. Cross-frame legs to/from C
    # are CROSS-CURRENCY FX (BVT<->AVT and, since §2026-06-14, BVT<->JDAY), routed over
    # the async FX rail (see _do_tx).
    "Frame-C":       {"port": 8101,  "frame": "C"},
    "Op-Telaviv":    {"port": 28000, "frame": "C"},
    "Op-Riyadh":     {"port": 28100, "frame": "C"},
    "Op-Abudhabi":   {"port": 28200, "frame": "C"},
    "Op-Doha":       {"port": 28300, "frame": "C"},
}
# Frame -> settlement currency. §2026-06-14 (JDAY/V0079): Frame-B converted AVT->JDAY
# and the FULL FX TRIANGLE went live (A<->B<->C<->A, every pair a direct AMM pool;
# Frame-B seeded @fx_reserve 5M JDAY). All 3 frames now hold DISTINCT currencies, so
# EVERY cross-frame leg is now cross-CURRENCY FX (credited != sent) — there is no longer
# a same-currency 1:1 cross-frame pair. B's AGORA venue ($EAST/$BSEA) was relabeled to
# JDAY too, so FRAME_CURRENCY also = the AGORA venue currency (no divergence).
FRAME_CURRENCY = {"A": "AVT", "B": "JDAY", "C": "BVT"}
ES_PORTS = {"A": 8200, "B": 8201, "C": 8202}
# Frames whose registries settle FX. §2026-06-14: Frame-B is now FX-ENABLED (was OFF in
# the old NON-FX topology) — the A<->B and B<->C pools are live + Frame-B has a JDAY
# reserve. NOTE: B's OP-level FX (op<->op via Frame-B's gateway reserve) was proven at
# MAINFRAME level in the JDAY rollout but not yet at op level — smoke-test the first
# `fx`/dynamic run; if a B-op FX leg dead-letters, revert to {"A","C"} (host-mounted, no rebuild).
FX_ENABLED_FRAMES = {"A", "B", "C"}
# Mainframe (gateway) registries. A mainframe SENDER -> leaf-op RECEIVER currently 503s
# on the FX pool's counterparty reserve-read (leaf ops have no reserve booth), so `fx`
# mode routes op<->op only — the proven gateway-delegated corridor. §framec-sim.
MAINFRAMES = {"Registry-A", "Frame-B", "Frame-C"}

# ══════════ §BATCH8 (2026-09-06) — a SELF-CONTAINED network under test ══════════
# The tables above are prod's. A fresh network (the JUICE↔BRRR pair) runs the same sim against its own
# venues by OVERRIDING them from the environment — prod's tables and prod's credentials file are never
# touched (the hard rule at the top of the file stands). Shapes are the tables' own:
#   SIM_REGISTRIES_JSON      {"JUICE": {"port": 8350, "frame": "J"}, "juiceop-a": {...}, ...}
#   SIM_FRAME_CURRENCY_JSON  {"J": "JUICE", "R": "BRRR"}
#   SIM_ES_PORTS_JSON        {"J": 8461, "R": 8471}
#   SIM_FX_ENABLED_FRAMES    "J,R"          SIM_MAINFRAMES  "JUICE,BRRR"
# and the roster comes from --credentials (default: scripts/sim_credentials.json, prod's).
def _sim_env_json(name, default):
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception as e:  # a wrong override is loud, never silent
        raise SystemExit(f"{name} is not valid JSON: {e}")
if os.getenv("SIM_REGISTRIES_JSON"):
    REGISTRIES = _sim_env_json("SIM_REGISTRIES_JSON", REGISTRIES)
    FRAME_CURRENCY = _sim_env_json("SIM_FRAME_CURRENCY_JSON", FRAME_CURRENCY)
    ES_PORTS = {k: int(v) for k, v in _sim_env_json("SIM_ES_PORTS_JSON", ES_PORTS).items()}
    FX_ENABLED_FRAMES = set(x.strip() for x in os.getenv("SIM_FX_ENABLED_FRAMES", ",".join(FX_ENABLED_FRAMES)).split(",") if x.strip())
    MAINFRAMES = set(x.strip() for x in os.getenv("SIM_MAINFRAMES", ",".join(MAINFRAMES)).split(",") if x.strip())
    print(f"SIM | venue override: registries={sorted(REGISTRIES)} currencies={FRAME_CURRENCY} es_ports={ES_PORTS} "
          f"fx_frames={sorted(FX_ENABLED_FRAMES)} mainframes={sorted(MAINFRAMES)}", flush=True)

# ══════════ §SIMFEDTICKER (2026-08-27) — trade the WHOLE federation's book ══════════
# The sim used to learn its universe from ONE /exchange/listings call per registry it
# already had agents on, so a venue where it holds no agent was invisible and its
# symbols were never traded. `/exchange/federation-tickers` answers for ALL 16 venues
# in a single call (30 listings today) and carries best_ask/best_bid, which the buy
# path needs — a price read from `last` will not cross a real book.
#
# ⚠ THE VENUE SLUG IS NOT THE SIM'S REGISTRY KEY FOR FOUR OPS. A renamed operator
# keeps its ORIGINAL slug in federation data while the sim knows it by its new name,
# so a naive lowercase match silently drops op-tokyo/singapore/sydney/seoul and the
# five symbols they list. Same class as the peer-name trap on the money rails.
_PASSPORT_ALL_VENUES = os.getenv("SIM_PASSPORT_ALL_VENUES", "1").strip().lower() not in ("0", "false", "off")
# §AGORASIM (2026-09-22): SIM_SYMBOLS (comma list) restricts the traded universe to the listings a test seeded. The
# sandbox pair's market also holds dozens of the API tester's fixture listings; unfiltered, most of the flow bought other
# fixtures' launch allocations instead of exercising the seeded books. Unset = the whole book, as before.
_SIM_SYMBOLS = {x.strip().upper() for x in os.getenv("SIM_SYMBOLS", "").split(",") if x.strip()}
_passport_only_venues: set = set()   # venues in the book but with no sim agent

_VENUE_ALIAS = {           # federation slug -> sim registry key
    "op-newyork": "Op-Tokyo", "op-losangeles": "Op-Singapore",
    "op-chicago": "Op-Sydney", "op-houston": "Op-Seoul",
}

_REG_TO_SLUG = {v: k for k, v in _VENUE_ALIAS.items()}   # sim key -> federation slug
# §AGORASIM (2026-09-22): a self-contained network names its venues its own way. The federation ticker feed names a
# frame by its SLUG when the frame describes itself ("sandbox-alpha") and by its DISPLAY NAME when a peer describes it
# ("Sandbox Beta"), and neither is the sim's key (sbx-alpha): unmatched, the sim treated its own two venues as
# foreign, gave local flow to one of them only and aimed passport orders at names no peer table holds (measured).
#   SIM_VENUE_ALIAS_JSON  {feed name (any case): sim key}   SIM_VENUE_WIRE_JSON  {sim key: the name peer tables hold}
if os.getenv("SIM_VENUE_ALIAS_JSON"):
    _VENUE_ALIAS.update({str(k).strip().lower(): v for k, v in _sim_env_json("SIM_VENUE_ALIAS_JSON", {}).items()})
if os.getenv("SIM_VENUE_WIRE_JSON"):
    _REG_TO_SLUG.update(_sim_env_json("SIM_VENUE_WIRE_JSON", {}))

def _venue_wire_name(regkey: str) -> str:
    """The venue name to put ON THE WIRE for a passport order.

    ⚠ `venue_registry` is resolved by the receiving registry against
    `peer_registries.name`, and a RENAMED operator keeps its ORIGINAL slug there —
    the peer tables know op-newyork, not op-tokyo. Sending the sim's own key would
    resolve to nothing for four ops (or, worse, to a stale row), so translate back
    to the slug the federation actually addresses them by.
    """
    return _REG_TO_SLUG.get(regkey, regkey)

def _venue_to_regkey(venue: str, known: set) -> Optional[str]:
    """Map a federation venue slug onto the sim's registry key, or None."""
    v = (venue or "").strip().lower()
    if not v:
        return None
    if v in _VENUE_ALIAS and _VENUE_ALIAS[v] in known:
        return _VENUE_ALIAS[v]
    for k in known:                      # Registry-A -> registry-a, Op-Berlin -> op-berlin
        if k.lower() == v:
            return k
    return None

def _ticker_row_to_listing(row: dict, currency: str) -> dict:
    """Adapt a federation-ticker row to the shape the trading loop already reads.

    The endpoint returns only approved+trading listings, so `approved` is synthesized
    rather than guessed; `last` is flat here and nested under `stats` there.
    """
    return {
        "symbol": row.get("symbol"), "display_name": row.get("display_name"),
        "organization_id": row.get("organization_id"),
        "status": row.get("status") or "trading", "approved": True,
        "ipo_price": row.get("ipo_price"), "currency": row.get("currency") or currency,
        "stats": {"last": row.get("last"),
                  "best_ask": row.get("best_ask"), "best_bid": row.get("best_bid"),
                  "volume_24h_notional": row.get("volume_24h_notional")},
        "best_ask": row.get("best_ask"), "best_bid": row.get("best_bid"),
        "_via": "federation-ticker",
    }

# §V0064 P2 passport-at-scale: HOME registries whose agents can relay orders to
# the frame-c venue via the DevCard Passport (EXCHANGE_PASSPORT_ENABLED on the op).
PASSPORT_HOMES = {"Op-Washington", "Op-Paris", "Op-Berlin", "Op-London", "Op-Doha", "Op-Telaviv",
                  # §2026-06-19 — frame-B ops added so JDAY-homed agents passport-trade and become
                  # dev_card participants → their AGORA dividends REPATRIATE (instead of paying
                  # frame-local and stranding on the wrong frame). Keys are the old container/host
                  # slugs (renamed in-place → op-newyork/losangeles/chicago/houston); ports unchanged.
                  "Op-Tokyo", "Op-Singapore", "Op-Sydney", "Op-Seoul"}
# §AGORASIM-2 (2026-09-22): a self-contained network names its OWN passport homes — the registry keys of
# SIM_REGISTRIES_JSON, comma-separated (the sandbox: its two frames and two operators) — so plain market mode relays
# --passport-share of its orders to a foreign venue instead of only the production homes above. Unset: unchanged.
_SIM_PASSPORT_HOMES = [x.strip() for x in os.getenv("SIM_PASSPORT_HOMES", "").split(",") if x.strip()]
if _SIM_PASSPORT_HOMES:
    PASSPORT_HOMES = set(_SIM_PASSPORT_HOMES)
# §AGORASIM-2 (2026-09-22): homes that cannot exchange currency (their registry's /api/v1/teg/fx/rates answers
# available=false, e.g. a cloud operator with FX off) relay passport orders only to venues of THEIR OWN currency.
# Filled at startup by asking each registry; a home the sim could not ask stays unrestricted. Measured before: 237 of
# 247 live-run failures were operator traders' cross-currency orders answering 502 "FX rate unavailable".
_NO_FX_HOMES: set = set()
# §AGORAWORDS Phase 5 (2026-09-22): the AGORA market's prefix. Every registry since V0419 serves /api/v1/agora (the
# documented name; /api/v1/exchange stays live until a later release drops it). A network of older registries sets
# SIM_AGORA_PREFIX=/api/v1/exchange (frame-sim.py derives it from the frame's own answer); the launch purchase follows.
AGORA = (os.getenv("SIM_AGORA_PREFIX", "/api/v1/agora") or "/api/v1/agora").rstrip("/")
LAUNCH_BUY = "launch/buy" if AGORA.endswith("/agora") else "ipo/buy"


def _passport_reachable(home: str, venue: str) -> bool:
    """A passport order from `home` can settle on `venue`: same currency, or the home can exchange currency."""
    if home not in _NO_FX_HOMES:
        return True
    return FRAME_CURRENCY.get(REGISTRIES.get(home, {}).get("frame")) == FRAME_CURRENCY.get(REGISTRIES.get(venue, {}).get("frame"))
# §SIMTRUTH (2026-09-30): the home registry answers 502 for ANY foreign refusal of a passport order
# ("the foreign AGORA market rejected the order relay (HTTP <code>): <body>"), and the failure message kept only
# resp.text[:70], so the foreign venue's own guardrails (the 20-open-orders cap = 429, the price band = 422) read as
# hard failures: 1 of ~2,800 fires in an hour on the V0497 sandbox, sbx-beta's cap refusing a relay from sbx-alpha.
# Read the foreign code out of the relay's own sentence; 429 and 422 are the venue working as designed ("rej", as
# on the local path). Every other foreign code, and every status but 502, stays a failure.
_RELAY_REFUSED = "rejected the order relay (HTTP "


def _passport_failure(resp, s, el):
    """The result tuple for a passport order its home registry did not accept (see §SIMTRUTH above)."""
    text = resp.text or ""
    i = text.find(_RELAY_REFUSED) if resp.status_code == 502 else -1
    at = i + len(_RELAY_REFUSED)
    if i >= 0 and text[at:at + 3] in ("429", "422"):
        return ("rej", s, s, 0.0, "passport", f"foreign venue {text[at:at + 3]}: {text[at + 6:at + 76]}", el)
    return ("fail", s, s, 0.0, "passport", f"HTTP {resp.status_code}: {text[:70]}", el)


PASSPORT_VENUE = "frame-c"
# §2026-06-14 — passport settlement currency DERIVED from PASSPORT_VENUE's frame letter
# ("frame-c"→C→BVT today), NOT hardcoded. Auto-corrects if the passport venue ever moves.
PASSPORT_CCY = FRAME_CURRENCY.get(PASSPORT_VENUE.split("-")[-1].upper(), "BVT")
# §2026-06-15 DIVERSIFY (Commander): spread passport relays across ALL mainframe venues
# (Registry-A / Frame-B / Frame-C) instead of only Frame-C, so foreign DevCards land on
# EVERY venue, not just C. Set False to restore the Frame-C-only corridor. Host-script
# change → no rebuild (sim copies the script on (re)start).
PASSPORT_DIVERSIFY = True

def _is_fx(a, b) -> bool:
    """True iff a transfer between agents a and b crosses a currency boundary."""
    return FRAME_CURRENCY.get(a.frame, "AVT") != FRAME_CURRENCY.get(b.frame, "AVT")

def _load_fx_targets():
    """§2026-06-17 FX managed-float driver config (scripts/fx_targets.json, RE-READ each cycle
    so it is LIVE-tunable without a sim restart). Returns (targets, band, bias):
      targets: {CCY: target_rate_in_AVT}  e.g. {"JDAY":1.20,"BVT":0.85}; AVT=1.0 implied (anchor)
      band:    soft free-float half-width (fraction) — inside it the driver is ~neutral noise
      bias:    0..1 push strength toward target outside the band
    Missing file / enabled=false / empty ⇒ driver OFF (legacy 50/50 flip)."""
    # /scripts is the read-only bind mount (host scripts/); the container only COPIES
    # sim_eigentrust.py + sim_credentials.json into /tmp/simwork/scripts, so the config
    # must be read from the bind mount. cwd-relative is the fallback for local runs.
    for _p in ("/scripts/fx_targets.json", "scripts/fx_targets.json"):
        try:
            d = json.loads(Path(_p).read_text())
        except Exception:
            continue
        if not d.get("enabled", True):
            return {}, 0.0, 0.0
        targets = {str(k).upper(): float(v) for k, v in (d.get("targets") or {}).items() if float(v) > 0}
        return targets, float(d.get("band", 0.08)), float(d.get("bias_strength", 0.7))
    return {}, 0.0, 0.0

def _load_director():
    """§2026-06-17 AGORA per-stock DEMAND DIRECTOR (scripts/agora_director.json, RE-READ each
    cycle → live-tunable, no restart). Returns {SYMBOL: {"dir": +1|0|-1, "strength": 0..1}}.
    dir>0 pushes the stock UP (buy-side bias + higher limit prices); dir<0 DOWN; 0/absent =
    legacy mean-revert. Missing file / enabled=false ⇒ {}. Reads the read-only bind mount
    /scripts first (the container copies only the .py + creds, not extra config files)."""
    for _p in ("/scripts/agora_director.json", "scripts/agora_director.json"):
        try:
            d = json.loads(Path(_p).read_text())
        except Exception:
            continue
        if not d.get("enabled", True):
            return {}
        out = {}
        for _sym, _cfg in (d.get("tickers") or {}).items():
            try:
                out[str(_sym).upper()] = {"dir": float(_cfg.get("dir", 0)),
                                          "strength": max(0.0, min(1.0, float(_cfg.get("strength", 0.7)))),
                                                   "intensity": max(0.0, min(1.0, float(_cfg.get("intensity", 0.0)))),
                                                   "volatility": max(0.0, min(1.0, float(_cfg.get("volatility", 0.0)))),
                                                   "regime": str(_cfg.get("regime", "calm"))}
            except (TypeError, ValueError):
                pass
        return out
    return {}

# ── §2026-06-28 AWARD-SIM CHUNK 1 — T1 archetypes + T2 telemetry ──────────────────
# All of the below is Δ-IRRELEVANT: it only shapes which orders are emitted (side/price/
# qty) and what the sim LOGS. Settlement still flows exclusively through the server-side
# exref/fxref escrow mover (Δ=0 by construction). No money path, no clamp removed.
#
# Per-symbol rolling recent-price history (one `last` sample per cycle, maxlen ~30),
# appended in _refresh_venues from prices the sim ALREADY reads. Feeds the momentum
# archetype's SMA/trend (T1) and the realized-vol telemetry (T2). Module-level so it
# persists across cycles within a process.
_price_hist = collections.defaultdict(lambda: collections.deque(maxlen=30))
MICRO_OB_EVERY = 5   # §T2 throttle: read top-of-book DEPTH every N cycles (mainframe venues only)

# Default trader-archetype mix (§2026-06-28 CHUNK 4 added `arbitrageur`; CHUNK 2 added
# `market_maker`): noise 32 / momentum 16 / mean_reversion 14 / fundamental 13 /
# market_maker 17 / arbitrageur 8 (sum=1.00). `noise` reproduces the pre-archetype decision
# policy byte-for-byte — the safe superset/default. Order matters: deterministic DID-hash
# bucketing walks this in order (adding an archetype reshuffles assignments vs the prior
# chunk — expected, still deterministic & reproducible).
# §2026-06-28 CHUNK 4 — T7 master switch. ARB_ENABLED=False removes `arbitrageur` from the
# mix (no agent is assigned it) AND makes the _do_market/_do_passport arb branches dead →
# byte-identical to chunk-3 behavior. Independently toggleable from T8 (HAWKES_ENABLED).
ARB_ENABLED = True
_ARCHETYPE_DEFAULT_MIX = [("noise", 0.32), ("momentum", 0.16), ("mean_reversion", 0.14),
                          ("fundamental", 0.13), ("market_maker", 0.17), ("arbitrageur", 0.08)]
if not ARB_ENABLED:
    # strip arbitrageur + renormalise the remaining five to sum=1.0 (the chunk-3 mix)
    _ARCHETYPE_DEFAULT_MIX = [(n, w) for n, w in _ARCHETYPE_DEFAULT_MIX if n != "arbitrageur"]
    _arb_tot = sum(w for _, w in _ARCHETYPE_DEFAULT_MIX) or 1.0
    _ARCHETYPE_DEFAULT_MIX = [(n, w / _arb_tot) for n, w in _ARCHETYPE_DEFAULT_MIX]
_ARCHETYPE_NAMES = {n for n, _ in _ARCHETYPE_DEFAULT_MIX}

def _load_archetypes():
    """§T1 trader-archetype mix (scripts/sim_archetypes.json, read at load — tunable without
    an image rebuild, mirrors _load_director). Returns an ordered, sum-normalised
    [(name, weight), ...]. Missing file / enabled=false / empty / unknown-only ⇒ the default
    mix. Only the four known archetypes are honoured."""
    for _p in ("/scripts/sim_archetypes.json", "scripts/sim_archetypes.json"):
        try:
            d = json.loads(Path(_p).read_text())
        except Exception:
            continue
        if not d.get("enabled", True):
            return list(_ARCHETYPE_DEFAULT_MIX)
        pairs = []
        for k, v in (d.get("mix") or {}).items():
            try:
                if str(k) in _ARCHETYPE_NAMES and float(v) > 0:
                    pairs.append((str(k), float(v)))
            except (TypeError, ValueError):
                pass
        tot = sum(w for _, w in pairs)
        if pairs and tot > 0:
            return [(k, w / tot) for k, w in pairs]
        return list(_ARCHETYPE_DEFAULT_MIX)
    return list(_ARCHETYPE_DEFAULT_MIX)

def _assign_archetype(did: str, mix):
    """Deterministic per-agent archetype from sha1(did) → an agent keeps the SAME archetype
    across restarts (reproducible). Buckets a stable [0,1) fraction of the DID hash against
    the normalised mix."""
    h = int(hashlib.sha1(did.encode()).hexdigest(), 16)
    frac = (h % 1_000_000) / 1_000_000.0
    cum = 0.0
    for name, w in mix:
        cum += w
        if frac < cum:
            return name
    return mix[-1][0] if mix else "noise"

def _fair_mult(did: str):
    """Deterministic per-agent private-belief multiplier for the `fundamental` archetype:
    lognormal(0, 0.15) seeded from the DID hash (reproducible across restarts)."""
    return random.Random(int(hashlib.sha1((did + ":fair").encode()).hexdigest(), 16)).lognormvariate(0.0, 0.15)

def _rvol(seq):
    """§T2 realized volatility = sample stdev of consecutive log-returns over the price deque.
    Returns 0.0 with <3 valid prices (too few for a return series)."""
    vals = [v for v in seq if v and v > 0]
    if len(vals) < 3:
        return 0.0
    rets = [math.log(vals[i] / vals[i - 1]) for i in range(1, len(vals))]
    if len(rets) < 2:
        return 0.0
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) if var > 0 else 0.0

# ── §2026-06-28 AWARD-SIM CHUNK 2 — T3 heavy-tailed sizes + T4 market-maker ────────
# Both Δ-IRRELEVANT (order-gen only; settlement still flows through the server-side
# exref/fxref escrow mover → Δ=0 by construction). T3 reshapes only the SIZE draw; T4
# adds a two-sided-quote decision branch. No money path, no clamp/cap removed, no rate
# raised (per-fire request count rises slightly for the MM minority — canaried).
#
# T3 — heavy-tailed order sizes: replace the old uniform int(amount/4)∈[1,12] with a
# LOGNORMAL draw (many small, few large — a core market stylized fact). median = e^MU,
# clipped to [1, QTY_CAP] where QTY_CAP is the SAME pre-existing cap (the heavy tail must
# NOT exceed it). Server MAX_ORDER_NOTIONAL + the abs price clamp stay the backstop.
QTY_LOGN_MU = 1.30      # e^1.30 ≈ 3.7 share median
QTY_LOGN_SIGMA = 0.70   # right-skew; ~p95 ≈ 11-12 → the [1,12] cap is hit only rarely
QTY_CAP = 12            # unchanged pre-existing size cap (heavy tail clipped here, never exceeded)
#
# T4 — designated MARKET-MAKER archetype (Avellaneda–Stoikov-lite). An MM posts a
# TWO-SIDED quote each fire (bid below mid + ask above mid) at a tight half-spread,
# shifted by an INVENTORY skew: long (free > target) → reservation price DOWN (lean
# sell / offload); short (free < target) → UP (lean buy / accumulate). Tightens spreads
# and DEEPENS the book (visible in the T2 MICRO `sprd=`/`dpth=` fields). Fenced exactly
# like every other order path: ≤2 clamped LIMIT orders/fire via the SAME /exchange/orders
# endpoint, MAX_RESTING-bounded footprint, ask leg never exceeds real holdings
# (sell-from-holdings), both legs band + absolute-breaker (ipo×[0.5,80]) clamped.
MM_HALF_SPREAD_MIN = 0.001   # tightest half-spread = 0.10% of mid (→ 0.20% full spread)
MM_HALF_SPREAD_MAX = 0.005   # widest  half-spread = 0.50% of mid (→ 1.00% full spread)
MM_INV_SKEW = 0.004          # max reservation-price shift = 0.40% of mid at full inventory deviation
MM_TARGET_INV = 20           # target book inventory (free qty); long>this leans sell, short<this leans buy
MM_QTY_MU = 0.85             # MM clip-size lognormal: e^0.85 ≈ 2.3 median (small / frequent)
MM_QTY_SIGMA = 0.5
MM_QTY_CAP = 5               # MM stays small (≤5); the ask leg further clamps to real holdings

# ── §2026-06-28 AWARD-SIM CHUNK 3 — T5 endogenous vol-clustering + T6 regime response ──
# Both Δ-IRRELEVANT (order-gen only; settlement still flows through the server-side exref/
# fxref escrow mover → Δ=0 by construction). T5 reshapes only the JITTER WIDTH; T6 (in
# _do_market) reshapes only per-archetype side/drift GAINS. No money path, no clamp/cap
# removed, no rate raised.
#
# T5 — endogenous volatility clustering (GARCH/EWMA-ish). Per symbol keep TWO EWMAs of
# squared log-returns: a FAST one (recent turbulence) + a SLOW one (the long-run baseline),
# both folded in _refresh_venues from the SAME `last` the sim already reads. The jitter band
# is scaled by sqrt(fast/slow) → >1 inside turbulent clusters, <1 in calm → quiet and
# turbulent periods CLUSTER (a real stylized fact) instead of constant jitter. The ratio's
# long-run (geometric) mean ≈ 1 and the clamp is symmetric in log ([0.5,2]=½..2), so MEAN
# volatility stays ≈ today's baseline — the state only REDISTRIBUTES amplitude over time, it
# does NOT make the market systematically wilder. Module-level → persists across cycles in a
# process. Cold start / no returns ⇒ multiplier EXACTLY 1.0 → byte-identical to pre-T5. The
# venue ±band + absolute breaker (ipo×[0.5,80]) stay the hard backstop regardless.
_vol_state: Dict[str, float] = {}   # SYMBOL -> fast EWMA of r^2 (recent realized variance)
_vol_base:  Dict[str, float] = {}   # SYMBOL -> slow EWMA of r^2 (long-run baseline variance)
VOL_FAST_DECAY = 0.94    # RiskMetrics-style fast memory (~16 cycles) — reacts to bursts
VOL_SLOW_DECAY = 0.985   # slow baseline memory (~66 cycles) — the reference level
VOL_MULT_MIN = 0.5       # jitter-band multiplier clamp (symmetric in log around 1.0)
VOL_MULT_MAX = 2.0

def _vol_update(sym, prev, cur):
    """§T5 fold one new prev→cur return into the per-symbol fast+slow EWMAs of squared
    log-returns. Seeds BOTH EWMAs with the first observed r^2 so the ratio starts at ~1
    (no cold-start spike). No-op on a missing / non-positive sample."""
    if not (prev and cur and prev > 0 and cur > 0):
        return
    r2 = math.log(cur / prev) ** 2
    vs = _vol_state.get(sym); vb = _vol_base.get(sym)
    _vol_state[sym] = r2 if vs is None else (VOL_FAST_DECAY * vs + (1.0 - VOL_FAST_DECAY) * r2)
    _vol_base[sym]  = r2 if vb is None else (VOL_SLOW_DECAY * vb + (1.0 - VOL_SLOW_DECAY) * r2)

def _vol_mult(sym):
    """§T5 jitter-band multiplier = sqrt(fast/slow EWMA of r^2): >1 in turbulent clusters,
    <1 in calm, long-run mean ≈ 1 (clamped [VOL_MULT_MIN, VOL_MULT_MAX]). Returns EXACTLY
    1.0 until a baseline exists (cold start) ⇒ byte-identical to pre-T5 when vol-state ==
    baseline."""
    vb = _vol_base.get(sym, 0.0)
    vs = _vol_state.get(sym, 0.0)
    if vb <= 1e-12 or vs <= 0.0:
        return 1.0
    return max(VOL_MULT_MIN, min(VOL_MULT_MAX, math.sqrt(vs / vb)))

# ── §2026-06-28 AWARD-SIM CHUNK 4 — T7 cross-venue arbitrageur + T8 stochastic arrivals ──
# Both Δ-IRRELEVANT (order-gen + LAUNCH-TIMING only; settlement still flows through the
# server-side exref/fxref escrow mover → Δ=0 by construction). No money path, no clamp/cap
# removed, no per-cycle order COUNT raised. Each is independently toggleable (ARB_ENABLED,
# defined above with the mix, for T7; HAWKES_ENABLED below for T8) so a canary can bisect them.
#
# T7 — ARBITRAGEUR archetype. Trades a symbol ONLY toward its cross-venue / fundamental
# parity, and ONLY when the deviation clears round-trip fees + ε (so it never adds noise
# flow). Reference = cross-venue mean `last` when the symbol trades on 2+ venues, else the
# fundamental anchor (ipo×EQ_ANCHOR_MULT). The home-venue leg goes through _do_market's normal
# /exchange/orders path; the cross-FRAME leg through _do_passport's existing /exchange/passport/
# orders path (buy a CHEAP foreign venue, sell a HELD position gone RICH). Every band + abs
# breaker + sell-from-holdings + MAX_RESTING clamp is retained → Δ=0 by construction.
ARB_GAP_MIN = 0.015          # min |ln(last/parity)| to act on the HOME venue (~1% round-trip fee + ε)
ARB_GAP_MIN_XFRAME = 0.030   # min gap for the cross-FRAME (passport) leg — larger, to clear the FX spread + ε
#
# T8 — STOCHASTIC INTER-ARRIVAL (Poisson + Hawkes). Instead of launching all of a cycle's
# pairs at once, stagger the task LAUNCHES across a bounded budget with exponential (Poisson)
# inter-arrival gaps, self-excited Hawkes-style (each arrival transiently shortens the next
# gap → realistic bursts then quiet). The gaps are NORMALISED to sum to the budget, so the
# per-cycle order COUNT and the mean rate are UNCHANGED — it only REDISTRIBUTES timing and
# LOWERS peak instantaneous concurrency (the AIMD sem + all caps still bind). Default OFF
# (timing interacts with the AIMD controller — opt in for a dedicated canary).
HAWKES_ENABLED = True       # §T8 master switch (default OFF — flip True to canary stochastic arrivals)
ARRIVAL_SPREAD_FRAC = 0.5    # spread launches over this fraction of the cycle budget (daemon: cycle_interval)
ARRIVAL_SPREAD_MAX_S = 8.0   # hard cap on the launch-spread window (s) — never overruns the cycle
HAWKES_EXCITE = 0.6          # per-arrival self-excitation kick (raises near-term intensity → clustering)
HAWKES_DECAY = 0.85          # excitation memory decay per arrival (→ excitation fades between bursts)

def _build_xref(venue_cache):
    """§T7 cross-venue parity map: SYMBOL -> {"ref": mean(last across venues), "n": venue_count}.
    Pure (no I/O) — built from the listings the sim already fetched in _refresh_venues. The
    arbitrageur trades toward `ref` when n>=2 (true cross-venue), else falls back to the
    fundamental anchor. Empty when there are no venues."""
    agg: Dict[str, list] = {}
    for _ls in (venue_cache or {}).values():
        for _x in _ls:
            _sym = (_x.get("symbol") or "").upper()
            if not _sym:
                continue
            _lp = (_x.get("stats") or {}).get("last") or _x.get("ipo_price")
            try:
                _lpf = float(_lp)
            except (TypeError, ValueError):
                continue
            if _lpf > 0:
                agg.setdefault(_sym, []).append(_lpf)
    return {s: {"ref": sum(ps) / len(ps), "n": len(ps)} for s, ps in agg.items()}

def _pick_xframe(by_frame, fx_only: bool = False):
    """Pick (sender, receiver) from two DISTINCT frames. fx_only -> currencies must
    differ (an FX leg). Cross-CURRENCY pairs are ONLY formed between FX_ENABLED_FRAMES
    (all 3 frames since §2026-06-14 JDAY triangle). N-frame generalisation of the old A/B pick."""
    frames = [f for f, pool in by_frame.items() if pool]
    random.shuffle(frames)
    for fa in frames:
        for fb in frames:
            if fa == fb:
                continue
            diff_ccy = FRAME_CURRENCY.get(fa) != FRAME_CURRENCY.get(fb)
            if fx_only and not diff_ccy:
                continue
            if diff_ccy and not ({fa, fb} <= FX_ENABLED_FRAMES):
                continue  # never route FX through a non-FX-enabled frame (e.g. B)
            if by_frame.get(fa) and by_frame.get(fb):
                s, r = random.choice(by_frame[fa]), random.choice(by_frame[fb])
                if random.random() < 0.5:
                    s, r = r, s
                return s, r
    return None, None

def _pick_fx(by_frame):
    """FX leg for `fx` mode: two LEAF-OP agents on different-currency FX_ENABLED_FRAMES
    (op<->op corridor — A-op<->C-op proven; §2026-06-14 B-ops (JDAY) now FX-eligible too,
    routing via Frame-B's gateway reserve — smoke-test). Avoids the mainframe->leaf-op
    reserve-read 503 by picking ops only (excludes MAINFRAMES). §framec-sim."""
    pools = {}
    for f in FX_ENABLED_FRAMES:
        ops = [a for a in by_frame.get(f, []) if a.registry not in MAINFRAMES]
        if ops:
            pools[f] = ops
    frames = list(pools.keys())
    random.shuffle(frames)
    for fa in frames:
        for fb in frames:
            if fa == fb or FRAME_CURRENCY.get(fa) == FRAME_CURRENCY.get(fb):
                continue
            s, r = random.choice(pools[fa]), random.choice(pools[fb])
            if random.random() < 0.5:
                s, r = r, s
            return s, r
    return None, None

def _weighted_choice(items, weights):
    """Pick from `items` with relative `weights` (dict item->float). Uniform if weights empty/zero."""
    ws = [max(0.0, float(weights.get(it, 0.0))) for it in items]
    tot = sum(ws)
    if tot <= 0:
        return random.choice(items)
    x = random.random() * tot
    acc = 0.0
    for it, w in zip(items, ws):
        acc += w
        if x <= acc:
            return it
    return items[-1]

def _compute_local_weights(venues, mode, passport_share):
    """Relative weights for the LOCAL-market venue pick (sum→1), by currency.
    'venue': uniform per venue. 'currency': each CURRENCY gets equal TOTAL flow incl. passport.
    §2026-06-14 (JDAY) — adapted for the FULL TRIPLE-AGORA triangle: one venue per currency
    (A=AVT, B=JDAY, C=BVT), all distinct + symmetric. 'currency' splits flow EQUALLY across the
    N currencies present (each 1/N, derived dynamically), then folds the passport surplus out of
    the PASSPORT venue's currency (PASSPORT_CCY) so its LOCAL share stays balanced when
    passport_share>0. With 1 venue/currency, 'venue' and 'currency' converge unless passport is
    active. (The retired §V0073 2-AVT-venue anti-skew this once corrected no longer applies —
    that asymmetry is gone now that Frame-B is its own currency.)
    `venues` = registry names present in the venue cache (auto-discovers all 3 currencies)."""
    if not venues:
        return {}
    if mode != "currency":
        w = 1.0 / len(venues)
        return {v: w for v in venues}
    ccy_of = {v: FRAME_CURRENCY.get(REGISTRIES.get(v, {}).get("frame"), "AVT") for v in venues}
    currencies = sorted(set(ccy_of.values()))
    target = 1.0 / len(currencies)            # equal share per currency (of ALL fires)
    P = max(0.0, min(0.95, passport_share))   # passport fires (→ PASSPORT_CCY) are not local flow
    local_total = max(1e-9, 1.0 - P)
    weights = {}
    for v in venues:
        ccy = ccy_of[v]
        n_in_ccy = sum(1 for x in venues if ccy_of[x] == ccy)
        passport_to_ccy = P if ccy == PASSPORT_CCY else 0.0
        ccy_local = max(0.0, target - passport_to_ccy) / local_total   # this ccy's share of LOCAL flow
        weights[v] = ccy_local / n_in_ccy
    s = sum(weights.values()) or 1.0
    return {v: w / s for v, w in weights.items()}                      # normalize → sum 1

# §framec-sim — batch balance fast-path. Replaces the 2-calls-per-agent startup
# balance check (agent-token + /teg/balance × N) with ONE batch call per registry
# via the OWNER developer's JWT → POST /developers/me/agents/balances (<=50 DIDs/call).
# The batch endpoint filters by creator_developer_id, so we need the owning dev's JWT;
# minted in-container (no passwords). Graceful per-agent fallback if a registry's mint
# fails (e.g. no docker socket in the endpoint-launched container).
REG_OWNER = {  # registry -> (container, owner_dev_sub)
    "Registry-A":    ("agentvault_registry_a", "10"),
    "Frame-B":       ("frame-b-registry", "2"),
    "Frame-C":       ("frame-c-registry", "3"),
    "Op-Washington": ("cloud-op-op-washington-registry", "1"),
    "Op-London":     ("cloud-op-op-london-registry", "1"),
    "Op-Paris":      ("cloud-op-op-paris-registry", "1"),
    "Op-Berlin":     ("cloud-op-op-berlin-registry", "1"),
    "Op-Tokyo":      ("cloud-op-op-tokyo-registry", "1"),
    "Op-Singapore":  ("cloud-op-op-singapore-registry", "1"),
    "Op-Sydney":     ("cloud-op-op-sydney-registry", "1"),
    "Op-Seoul":      ("cloud-op-op-seoul-registry", "1"),
    "Op-Telaviv":    ("cloud-op-op-telaviv-registry", "1"),
    "Op-Riyadh":     ("cloud-op-op-riyadh-registry", "1"),
    "Op-Abudhabi":   ("cloud-op-op-abudhabi-registry", "1"),
    "Op-Doha":       ("cloud-op-op-doha-registry", "1"),
}

# §BALCHECKFIX (2026-07-28): this used to return a bare None on ANY failure, and the caller
# turned that into a silent per-agent fallback (2 calls per agent instead of 1 per registry).
# The dominant failure is a `docker exec` that overruns the timeout while the box is busy — the
# same class that made the Command Center checks flap. So: ONE retry, a longer ceiling, and the
# reason is returned to the caller instead of being swallowed.
_MINT_FAIL_REASON: Dict[str, str] = {}
# True once we learn the docker socket is not reachable (endpoint-launched container mode).
_DOCKER_UNAVAILABLE = False


def _note_docker_state(msg: str) -> None:
    """Flip the container-mode flag when the docker socket is demonstrably unreachable, so the
    caller can report 12 identical cloud-op fallbacks as ONE expected line instead of 12 alarms."""
    m = (msg or "").lower()
    if "docker.sock" in m or "docker daemon" in m or "docker api" in m:
        globals()["_DOCKER_UNAVAILABLE"] = True


def _mint_owner_jwt(container: str, sub: str, _retry: bool = True):
    """Mint the owning developer's JWT inside the registry container (no password)."""
    import subprocess
    try:
        code = ("from agentvault_registry.security import create_access_token;"
                "from datetime import timedelta;"
                f"print(create_access_token({{'sub':'{sub}'}}, expires_delta=timedelta(minutes=120)))")
        r = subprocess.run(["docker", "exec", container, "sh", "-c", f'PYTHONPATH=/app/src python3 -c "{code}"'],
                           capture_output=True, text=True, timeout=45)
        jwt = (r.stdout or "").strip()
        if jwt and "." in jwt:
            _MINT_FAIL_REASON.pop(container, None)
            return jwt
        _MINT_FAIL_REASON[container] = (r.stderr or "empty output")[:120]
        _note_docker_state(r.stderr or "")
    except Exception as e:
        _MINT_FAIL_REASON[container] = f"{type(e).__name__}: {str(e)[:100]}"
        _note_docker_state(str(e))
    if _retry:
        time.sleep(0.5)
        return _mint_owner_jwt(container, sub, _retry=False)
    return None

# ══════════════════════ §2026-07-19 IRONKEY DESK MODEL + DELEGATION MODE ══════════════════════
# Award-sim frontier: exercise the LIVE IRONKEY spawn/delegation/capability/AUDIT machinery on
# frame-c (:8101 — rbac=enforce deleg=enforce spawn=true xreg=true) with the existing sim fleet.
#   • --spawn-subagents  "the desk model" — CLUSTER-WIDE since §2026-07-19b: EVERY funded parent on
#       ALL 16 registries spawns ONE execution-clerk on its OWN registry (birth token:
#       exchange.trade+ipo+teg.transfer, no_redelegate, 24h; frame-bound by construction).
#       The parent keeps the archetype brain; the clerk EXECUTES its market+passport orders presenting
#       X-Capability-Token — base-only on its own JWT, so /exchange/orders (require_agent_permission
#       "exchange.trade") only clears via caveat ∩ ISSUER authority. Suspend the parent → the clerk
#       goes dark the same request. Every spawn fires the AgentSpawned reactor. Δ-neutral.
#   • --mode delegation (or a periodic tick inside market): a continuously-running IRONKEY
#       CONFORMANCE BATTERY + AUDIT SELF-CHECK. Each tick choreographs issue→consume→attenuate, an
#       over-budget consume DENY (expected PASS), an act-token over-cap spend DENY (403 caveat), an
#       L3 grant→act-token→revoke, a revoked-token reuse DENY (feeds the misuse stream), a periodic
#       circuit-breaker trip, and (optional) a cross-registry leg; THEN queries security_audit_logs
#       (/admin/audit-logs?action=ironkey.) and asserts every action it just fired left its durable
#       row — logging an audit-trail-completeness %. Expected-denies are first-class successes.
# Hard rules: NEVER writes scripts/sim_credentials.json; clerks persist to a SEPARATE
# scripts/sim_spawned_credentials.json, reused across restarts (spawn-once). Auto-degrades to direct
# trading / no-op wherever the IRONKEY flags are dark. The sim container has NO docker → admin ops
# use the commander form-login (_overview_login), never the owner-mint path.

SPAWN_SUBAGENTS = False          # set from --spawn-subagents in run()
XREG_DELEGATION = False          # set from --xreg-delegation in run()
_SPAWN_POOL_SIZE = int(os.getenv("SIM_SPAWN_POOL", "0"))    # clerk-parent cap; 0 = ALL funded parents (cluster-wide)
_CLERK_SEED_AMT = "3000"         # one-time clerk wallet seed, native ccy (admin fund-agent; parent transfer on ops)
# §XREGMODE-under-enforce (2026-08-13): teg.transfer_xreg is REQUIRED for the cross-frame
# (SIM_XREG_ONLY / SIM_CLERK_ANCHORED) legs — /teg/cross-registry-transfer + smart_send's fx/2pc
# fan-out gate on it (require_agent_permission("teg.transfer_xreg")). Without it, RBAC enforce 403s
# EVERY foreign transfer a walletless clerk attempts. The clerk's cap resolves as caveat ∩ ISSUER
# authority, and the parent archetype (trader role) already holds teg.transfer_xreg, so this grants
# cleanly; the v3 purse-redirect still debits the PRINCIPAL, so the money story is unchanged.
_CLERK_PERMS = ["exchange.trade", "exchange.ipo", "teg.transfer", "teg.transfer_xreg"]
# §2026-07-20 CLERK SOLVENCY + AUTHORITY — a clerk converts working ccy → shares as it BUYS; seeded
# once it drained and every buy fired a doomed 'order deposit failed: exchange mover 400'. And its
# birth-token per-tx cap (250) blocked single shares of the pricey tickers (CHONK 509, SLG…) that a
# rich parent traded freely → the un-inherited market-mode capability. Fix: keep float topped up
# (parent→clerk /teg/transfer, existing rail, parent holds millions same-ccy → Δ=0), raise the per-tx
# cap (still bounded vs the parent → desk model intact), and read the CLERK wallet/cap (not the
# parent's s.balance) for affordability. Guards key off each clerk's CONFIRMED tx_cap so there is no
# capability-deny while existing clerks re-issue their token at the new cap.
_SIM_CLERK_MIN_FLOAT = float(os.getenv("SIM_CLERK_MIN_FLOAT", "1000"))     # refill trigger (free ccy)
_SIM_CLERK_TARGET_FLOAT = float(os.getenv("SIM_CLERK_TARGET_FLOAT", "3000"))  # working float restored to
_SIM_CLERK_BAL_TTL = float(os.getenv("SIM_CLERK_BAL_TTL", "75"))           # balance-refresh cadence (s)
_CLERK_TX_CAP = int(os.getenv("SIM_CLERK_TX_CAP", "5000"))                 # birth/renewal token per-tx cap (bounded, but funds real tickers)
def _clerk_cap(ck) -> float:      # per-buy notional ceiling from the clerk's CONFIRMED token cap (250 until re-issued)
    return float((ck or {}).get("tx_cap", 250)) * 0.96
_CLERK_TOKEN_TTL = int(os.getenv("SIM_CLERK_TOKEN_TTL", "86400"))      # birth/renewal capability-token TTL (s)
_CLERK_RENEW_MARGIN = int(os.getenv("SIM_CLERK_RENEW_MARGIN", "7200")) # re-issue when < this many s of life left
# Clerk persistence path. In the endpoint-launched container the host sessionlogs2026 is bind-mounted
# rw at /sessionlogs, while the relative sessionlogs2026/ under /tmp/simwork is an EPHEMERAL real dir
# (the startup `ln -sf` no-ops because mkdir already created it) — so prefer /sessionlogs when present
# so clerks actually persist across restarts (bounds orphan-agent growth). NEVER the ro scripts/ dir.
_SPAWNED_CREDS = Path(os.getenv("SIM_SPAWNED_CREDS")
                      or ("/sessionlogs/sim_spawned_credentials.json" if os.path.isdir("/sessionlogs")
                          else "sessionlogs2026/sim_spawned_credentials.json"))
_DELEG_MGR_POOL = int(os.getenv("SIM_DELEG_MANAGERS", "6"))  # frame-c managers granted legacy-full
_CB_EVERY = int(os.getenv("SIM_DELEG_CB_EVERY", "20"))       # trip the breaker every Nth delegation tick
_DELEG_TICK_EVERY = int(os.getenv("SIM_DELEG_TICK_EVERY", "12"))  # market mode: run a full deleg battery every N cycles

# ── §XREGMODE 2026-08-12 (Commander) — "100% FOREIGN-FEDERATED" overlay ─────────────────────────
# Exercise the delegation + subagent-spawn CROSS-REGISTRY path at saturation, so every clerk-routed
# interaction crosses to a FOREIGN federated registry. Three env knobs (byte-inert defaults):
#   SIM_SPAWN_FRAMES  (default "C") — the MAINFRAME frames whose parents receive the authz.delegate
#                     grant so they may /agents/spawn under enforce. "A,B,C" spawns an execution
#                     clerk on ALL THREE mainframes (legacy = frame-c only). The commander login is
#                     admin on all three, so the grant works per-port. Cloud-ops stay ungranted
#                     (no admin account there) → they degrade to direct trading, unchanged.
#   SIM_XREG_ONLY     (default off) — market mode: FORCE every fire to a FOREIGN passport order
#                     placed BY a spawned clerk whose home ≠ the target venue (venue registry !=
#                     sender registry) → 100% cross-registry order-flow. Needs --mode market
#                     --spawn-subagents. Pairs with --xreg-delegation (the battery's cross-registry
#                     delegation leg) to cover BOTH mechanisms the Commander named.
#   SIM_CLERK_ANCHORED(default off) — spawn the clerk WALLETLESS (skip the seed + solvency top-up)
#                     and let the §SPAWN-ANCHOR purse-redirect fund its spend from the PARENT.
#                     ⚠ Only the anchor-wired legs honor it today: local /teg/transfer and
#                     /exchange/orders. The PASSPORT funding leg is NOT yet anchor-aware (its nested
#                     /teg/send does not forward X-Capability-Token), so under SIM_XREG_ONLY leave
#                     this OFF — a mainframe clerk is Δ-clean seeded (projected locally, no census
#                     blindspot; that is a cloud-op-only phenomenon). See the v3 follow-up note.
def _env_true(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes")
_SPAWN_FRAMES = {f.strip().upper() for f in os.getenv("SIM_SPAWN_FRAMES", "C").split(",") if f.strip()}
# §BATCH10 finding 23: on a self-contained network (SIM_FRAME_CURRENCY_JSON set) the grant frames are THAT network's letters
# unless SIM_SPAWN_FRAMES says otherwise — the "C" default is production's Frame-C, which such a network does not have.
if os.getenv("SIM_FRAME_CURRENCY_JSON") and not os.getenv("SIM_SPAWN_FRAMES"):
    try:
        _SPAWN_FRAMES = {str(k).strip().upper() for k in json.loads(os.environ["SIM_FRAME_CURRENCY_JSON"]).keys()}
    except Exception:
        pass
_MF_NAME = {"A": "Registry-A", "B": "Frame-B", "C": "Frame-C"}
# §AGORASIM (2026-09-22): with SIM_REGISTRIES_JSON the mainframes are SIM_MAINFRAMES under their own frame letters. The
# prod map above named none of them, so no parent was spawn-eligible and SIM_XREG_ONLY found "0 eligible senders"
# and quietly fell back to local orders (measured on the sandbox pair).
if os.getenv("SIM_REGISTRIES_JSON"):
    _MF_NAME = {str(v.get("frame")): k for k, v in REGISTRIES.items()
                if k in MAINFRAMES and isinstance(v, dict) and v.get("frame")} or _MF_NAME
_DELEG_MF = os.getenv("SIM_DELEG_MAINFRAME", "Frame-C")   # §BATCH8: the delegation battery's mainframe (prod: Frame-C)
_XREG_ONLY = _env_true(os.getenv("SIM_XREG_ONLY", "0"))
_CLERK_ANCHORED = _env_true(os.getenv("SIM_CLERK_ANCHORED", "0"))

_admin_jwt_cache: Dict[int, tuple] = {}   # port -> (jwt, ts)
_spawned_creds: Dict[str, dict] = {}      # parent_did -> {did, client_id, client_secret, token}
_CLERK_DIDS: set = set()                   # clerk-routed parent DIDs, CLUSTER-WIDE (populated at startup)
_deleg_state: Dict[str, Any] = {"ready": False, "managers": [], "workers": [], "admin_id": None, "tick": 0}

async def _admin_jwt(c, port, login) -> Optional[str]:
    """Commander dev-JWT for a registry port (form login; cached ~50 min). The endpoint-launched
    sim container has no docker exec, so the owner-mint path is unavailable — this is the only way."""
    ent = _admin_jwt_cache.get(port)
    if ent and (time.time() - ent[1]) < 3000:
        return ent[0]
    if not login:
        return None
    # §AGORASIM (2026-09-22): the prod frames share one admin (the Commander); a self-contained network's mainframes each
    # have their OWN, so one login granted nothing on the other frame and every clerk spawn there answered 403 (measured).
    # An optional `by_port` map in the roster's _overview_login names the admin per registry port; absent = as before.
    if isinstance(login.get("by_port"), dict) and str(port) in login["by_port"]:
        login = login["by_port"][str(port)]
    try:
        r = await c.post(f"http://localhost:{port}/api/v1/auth/login",
                         data={"username": login["username"], "password": login["password"]},
                         headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        if r.status_code == 200:
            jwt = r.json().get("access_token")
            if jwt:
                _admin_jwt_cache[port] = (jwt, time.time())
                return jwt
    except Exception:
        pass
    return None

async def _agent_token(c, port, cid, secret) -> Optional[str]:
    try:
        r = await c.post(f"http://localhost:{port}/api/v1/auth/agent/token",
                         data={"username": cid, "password": secret},
                         headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception:
        pass
    return None

async def _grant_legacy_full(c, port, admin_jwt, did) -> bool:
    """Give a frame-c sim agent authz.delegate (via legacy-full) so it may spawn/issue. Idempotent."""
    try:
        r = await c.put(f"http://localhost:{port}/api/v1/agents/{did}/authz",
                        json={"roles": ["legacy-full"]},
                        headers={"Authorization": f"Bearer {admin_jwt}"}, timeout=15)
        return r.status_code in (200, 204)
    except Exception:
        return False

def _load_spawned_creds():
    global _spawned_creds
    if _SPAWNED_CREDS.exists():
        try:
            _spawned_creds = json.loads(_SPAWNED_CREDS.read_text())
        except Exception:
            _spawned_creds = {}

def _save_spawned_creds():
    try:
        _SPAWNED_CREDS.write_text(json.dumps(_spawned_creds))
        # §AGORASIM (2026-09-22): clerk client secrets; the container's umask left the file 644 (measured). Keep it 600.
        try:
            os.chmod(_SPAWNED_CREDS, 0o600)
        except Exception:
            pass
    except Exception:
        pass

async def _renew_clerk_token(c, parent: "Agent", ck: dict, fh) -> None:
    """§2026-07-19b BIRTH-TOKEN AUTO-RENEW — identity is permanent, authority is ephemeral: the
    clerk's att_ capability token expires (TTL ~24h). Near/at/past expiry — or when no expiry is
    recorded (pre-renew-era persisted clerks) — the PARENT re-issues a fresh token for the SAME
    clerk via the normal issue rail (POST /agents/capabilities, same perms/caveats as birth). No
    re-spawn, no identity churn. Throttled per clerk (10 min; 1 h back-off on failure) so a dark
    or failing node can't get hammered. Where deleg is off the token stays audit-only anyway."""
    now = time.time()
    exp = float(ck.get("token_exp") or 0)
    # Re-issue when near/at/past expiry OR when the recorded cap is stale (existing clerks were born at
    # 250 → force one re-issue at _CLERK_TX_CAP so they can trade the pricey tickers). Throttle unchanged.
    if ck.get("token") and exp and (exp - now) > _CLERK_RENEW_MARGIN and ck.get("tx_cap") == _CLERK_TX_CAP:
        return
    if (now - float(ck.get("renew_ts") or 0)) < 600:
        return
    ck["renew_ts"] = now
    try:
        pj = await get_jwt(c, parent)
        r = await c.post(f"http://localhost:{parent.port}/api/v1/agents/capabilities",
                         json={"holder_agent_did": ck["did"],
                               "caveats": {"permissions": _CLERK_PERMS, "max_per_tx": _CLERK_TX_CAP, "no_redelegate": True},
                               "ttl_seconds": _CLERK_TOKEN_TTL},
                         headers={"Authorization": f"Bearer {pj}"}, timeout=20)
        if r.status_code == 200 and (r.json() or {}).get("token"):
            ck["token"] = r.json()["token"]; ck["token_exp"] = now + _CLERK_TOKEN_TTL; ck["tx_cap"] = _CLERK_TX_CAP
            _spawned_creds[parent.did] = {k: ck.get(k) for k in ("did", "client_id", "client_secret", "token", "token_exp")}
            _save_spawned_creds()
            log(f"RENEW | {parent.name} re-issued clerk token …{str(ck['did'])[-10:]} (+{_CLERK_TOKEN_TTL // 3600}h)", fh)
        else:
            ck["renew_ts"] = now + 3000   # issue denied/unavailable here — back off ~1 h total
    except Exception:
        ck["renew_ts"] = now + 3000


async def _ensure_clerk_solvent(c, parent: "Agent", ck: dict, fh) -> None:
    """§2026-07-20 Keep an execution-clerk's WORKING CURRENCY afloat so its buys clear instead of
    firing doomed 'order deposit failed: exchange mover 400' round-trips. TTL-gated
    (SIM_CLERK_BAL_TTL) → ~one balance GET per clerk per interval, NOT per fire. Refill = a
    parent→clerk /teg/transfer (existing rail; the parent holds millions of the same-registry ccy,
    seed capital never minted) → Δ-neutral. Cached ck['bal'] is debited per buy / credited per sell
    between refreshes so the affordability guard stays live without an HTTP hit each fire."""
    now = time.time()
    if ck.get("bal_ts", 0) and (now - ck["bal_ts"]) < _SIM_CLERK_BAL_TTL:
        return
    j = ck.get("jwt")
    if not j:
        return
    try:
        r = await c.get(f"http://localhost:{parent.port}/api/v1/teg/balance",
                        headers={"Authorization": f"Bearer {j}"}, timeout=15)
        ck["bal"] = float(Decimal(str(r.json().get("balance", "0")))) if r.status_code == 200 else ck.get("bal", 0.0)
    except Exception:
        ck["bal"] = ck.get("bal", 0.0)
    ck["bal_ts"] = now
    if ck["bal"] < _SIM_CLERK_MIN_FLOAT:
        _need = round(_SIM_CLERK_TARGET_FLOAT - ck["bal"], 2)
        try:
            pj = await get_jwt(c, parent)
            rt = await c.post(f"http://localhost:{parent.port}/api/v1/teg/transfer",
                              json={"receiver_agent_id": ck["did"], "amount": f"{_need:.2f}",
                                    "message": "clerk-float top-up"},
                              headers={"Authorization": f"Bearer {pj}"}, timeout=20)
            if rt.status_code == 200:
                ck["bal"] = _SIM_CLERK_TARGET_FLOAT
                log(f"TOPUP | {parent.name} → clerk …{str(ck.get('did'))[-8:]} +{_need:.0f} (float→{_SIM_CLERK_TARGET_FLOAT:.0f})", fh)
        except Exception:
            pass


# §AGORASIM-2 (2026-09-22): a refused spawn is remembered per parent for SIM_SPAWN_RETRY_S (600 s). Before, every order
# attempt of a parent on a spawn-dark registry sent another /agents/spawn and logged another 403 line (2,484 in two hours
# on the sandbox operators), and the line guessed its cause; it now carries the registry's own detail, once a window.
_SPAWN_RETRY_S = float(os.getenv("SIM_SPAWN_RETRY_S", "600"))
_SPAWN_REFUSED_UNTIL: Dict[str, float] = {}


async def _get_or_spawn_clerk(c, parent: "Agent", login, fh) -> Optional[dict]:
    """Spawn-once, cache on the parent, persist. Returns the clerk dict
    {did, jwt, jwt_ts, token, token_exp, client_id, client_secret} or None (→ parent trades directly)."""
    ck = getattr(parent, "clerk", None)
    if ck and ck.get("jwt") and (time.time() - ck.get("jwt_ts", 0)) < 840:
        await _renew_clerk_token(c, parent, ck, fh)   # no-op unless the att_ token nears expiry
        return ck
    if ck and ck.get("client_id"):  # refresh a stale child JWT
        j = await _agent_token(c, parent.port, ck["client_id"], ck["client_secret"])
        if j:
            ck["jwt"] = j; ck["jwt_ts"] = time.time()
            await _renew_clerk_token(c, parent, ck, fh)
            return ck
        return ck if ck.get("jwt") else None
    saved = _spawned_creds.get(parent.did)   # reuse across restarts (NEVER re-spawn)
    if saved and saved.get("client_id"):
        j = await _agent_token(c, parent.port, saved["client_id"], saved["client_secret"])
        if j:
            parent.clerk = {**saved, "jwt": j, "jwt_ts": time.time()}
            await _renew_clerk_token(c, parent, parent.clerk, fh)   # pre-renew clerks: no token_exp → renew once now
            return parent.clerk
    if _SPAWN_REFUSED_UNTIL.get(parent.did, 0.0) > time.monotonic():
        return None                 # refused recently: trade directly without asking again inside the window
    pj = await get_jwt(c, parent)   # fresh spawn — parent must hold authz.delegate (granted at startup)
    body = {"name": f"clerk-of-{parent.name[:36]}", "permissions": _CLERK_PERMS,
            "ttl_seconds": _CLERK_TOKEN_TTL, "max_per_tx": _CLERK_TX_CAP, "no_redelegate": True}
    try:
        r = await c.post(f"http://localhost:{parent.port}/api/v1/agents/spawn", json=body,
                         headers={"Authorization": f"Bearer {pj}"}, timeout=25)
    except Exception:
        return None
    if r.status_code != 200:
        if r.status_code == 403:
            try:
                _det = str((r.json() or {}).get("detail") or "")[:120]
            except Exception:
                _det = (r.text or "")[:120]
            _SPAWN_REFUSED_UNTIL[parent.did] = time.monotonic() + _SPAWN_RETRY_S
            log(f"SPAWN | {parent.name}@{parent.registry} 403: {_det or 'no detail'} — direct-trade fallback, "
                f"next try in {_SPAWN_RETRY_S:.0f}s", fh)
        return None
    d = r.json()
    clerk = {"did": d.get("child_did"), "client_id": d.get("client_id"),
             "client_secret": d.get("client_secret"), "token": d.get("birth_token"),
             "token_exp": time.time() + _CLERK_TOKEN_TTL, "jwt": None, "jwt_ts": 0.0,
             "bal": float(_CLERK_SEED_AMT), "bal_ts": 0.0, "tx_cap": _CLERK_TX_CAP}
    if not clerk["did"] or not clerk["token"]:
        return None
    clerk["jwt"] = await _agent_token(c, parent.port, clerk["client_id"], clerk["client_secret"])
    clerk["jwt_ts"] = time.time()
    if not _CLERK_ANCHORED:
        # §XREGMODE: SKIP the seed when anchored — the clerk is spawned WALLETLESS (anchor on) and
        # its spend is funded from the PARENT's purse by the §SPAWN-ANCHOR redirect on the anchor-
        # wired legs. Seeding a walletless anchored clerk would re-create the very wallet the anchor
        # eliminates. When NOT anchored, seed as before (Δ-neutral working capital).
        aj = await _admin_jwt(c, parent.port, login)   # one-time wallet seed so the clerk can BUY (Δ-neutral)
        seeded = False
        if aj:   # mainframes: commander treasury fund (parent capital untouched)
            try:
                r2 = await c.post(f"http://localhost:{parent.port}/api/v1/teg/treasury/fund-agent",
                                  json={"target_agent_did": clerk["did"], "amount": _CLERK_SEED_AMT, "reason": "clerk-seed"},
                                  headers={"Authorization": f"Bearer {aj}"}, timeout=20)
                seeded = r2.status_code == 200
            except Exception:
                pass
        if not seeded:
            # cloud-ops (no commander account → no admin JWT): the DESK funds its own clerk via the
            # normal transfer rail — parent allowance, same registry, ordinary fee. Δ-neutral by rail.
            try:
                await c.post(f"http://localhost:{parent.port}/api/v1/teg/transfer",
                             json={"receiver_agent_id": clerk["did"], "amount": _CLERK_SEED_AMT, "message": "clerk-seed allowance"},
                             headers={"Authorization": f"Bearer {pj}"}, timeout=20)
            except Exception:
                pass
    parent.clerk = clerk
    _spawned_creds[parent.did] = {k: clerk.get(k) for k in ("did", "client_id", "client_secret", "token", "token_exp")}
    _save_spawned_creds()
    log(f"SPAWN | {parent.name} → clerk …{str(clerk['did'])[-10:]} (birth token: exchange.trade)", fh)
    return clerk

async def _ensure_spawn_pool(c, mfs: List["Agent"], login, fh):
    """Grant authz.delegate (legacy-full) ONCE to the MAINFRAME parents on the configured spawn
    frames (SIM_SPAWN_FRAMES; default frame-c only). §28/§29 rolled AGENT_RBAC_MODE=enforce
    FLEET-WIDE, so the grant is now a precondition for /agents/spawn on Registry-A and Frame-B too —
    not only Frame-C (the old docstring predated that roll). The commander login (_admin_jwt) is
    admin on all three mainframes, so each parent is granted on ITS OWN port. Cloud-ops are excluded
    (no commander account there) → they degrade to direct trading, unchanged. Idempotent."""
    if not mfs:
        return
    pool = sorted(mfs, key=lambda a: a.did)
    if _SPAWN_POOL_SIZE > 0:
        pool = pool[:_SPAWN_POOL_SIZE]
    # one admin JWT per distinct mainframe port (A=8000 / B=8100 / C=8101)
    _aj: Dict[int, Optional[str]] = {}
    ok = 0; skipped_ports = set()
    for a in pool:
        if a.port not in _aj:
            _aj[a.port] = await _admin_jwt(c, a.port, login)
        aj = _aj[a.port]
        if not aj:
            skipped_ports.add(a.port)
            continue
        if await _grant_legacy_full(c, a.port, aj, a.did):
            ok += 1
    _frames = "+".join(sorted({a.frame for a in pool}))
    log(f"SPAWN | granted authz.delegate to {ok}/{len(pool)} mainframe parents on frame(s) {_frames} "
        f"(enforce side){' — no admin JWT on ports ' + str(sorted(skipped_ports)) if skipped_ports else ''}", fh)


def _clerk_pool_dids(parents: List["Agent"]) -> set:
    p = sorted(parents, key=lambda x: x.did)
    return {a.did for a in (p[:_SPAWN_POOL_SIZE] if _SPAWN_POOL_SIZE > 0 else p)}


# ── §FG-7 GÖDEL FORGE generation battery (frame-c) ────────────────────────────────────────────
# One GENERATION per tick: battery parent spawns a variant (bounded birth token carrying
# cicd.version+bundle.write) → variant solves the arena suite's PUBLIC problems (embedded solver;
# every 3rd generation ships a DELIBERATE flaw to exercise the fail path) → commits its answers as
# its own version → self-triggers the eval (code_patch → 3-of-5 verifier quorum, never
# self-scored) → adopts (activates) on pass. Degrades silently where the arena is dark/unseeded.
_FORGE_TICK_EVERY = int(os.getenv("SIM_FORGE_TICK_EVERY", "50"))
# Batch 8: one generation per LIVE arena per tick. Arenas are discovered by filename —
# the per-frame credential files the seeder writes — mapped to their registry ports.
# SIM_FORGE_ARENA (single path, frame-c) still wins for backward compatibility.
_FORGE_ARENA_DIR = "/sessionlogs" if os.path.isdir("/sessionlogs") else "sessionlogs2026"
# SIM_FORGE_ARENAS=off (2026-09-30): no arena at all. The arenas below are the LEGACY frames' (8000/8100/8101), so a run on
# another network (the sandbox) must switch the battery off, or it builds generations on Registry-A.
_FORGE_ARENAS = [] if os.getenv("SIM_FORGE_ARENAS", "").strip().lower() in ("off", "none", "0") else (
    [(os.getenv("SIM_FORGE_ARENA"), 8101, "c")] if os.getenv("SIM_FORGE_ARENA") else [
    (f"{_FORGE_ARENA_DIR}/forge_arena_credentials_a.json", 8000, "a"),
    (f"{_FORGE_ARENA_DIR}/forge_arena_credentials_b.json", 8100, "b"),
    (f"{_FORGE_ARENA_DIR}/forge_arena_credentials.json", 8101, "c"),
])
_forge_states: Dict[str, Dict[str, Any]] = {
    fr: {"gen": 0, "arena": None, "disabled": False, "path": p, "port": port}
    for p, port, fr in _FORGE_ARENAS}


def _forge_solve(problem: dict):
    kind = problem.get("kind"); inputs = problem.get("inputs") or []
    if kind == "sum_list": return [sum(x) for x in inputs]
    if kind == "sort_desc": return [sorted(x, reverse=True) for x in inputs]
    if kind == "reverse_string": return [str(x)[::-1] for x in inputs]
    if kind == "max_minus_min": return [(max(x) - min(x)) if x else 0 for x in inputs]
    return []


async def _forge_tick(c, fh) -> None:
    """One battery generation per LIVE arena (batch 8: frames a/b/c; a missing or dark
    arena disables only ITSELF — the others keep evolving)."""
    for fr, st in _forge_states.items():
        if st["disabled"]:
            continue
        if st["arena"] is None:
            try:
                st["arena"] = json.loads(Path(st["path"]).read_text())
            except Exception:
                if fr == "c":  # a/b arenas are optional — only frame-c absence is worth a log line
                    log("FORGE | arena creds not found — battery disabled this run (run forge_seed_arena first)", fh)
                st["disabled"] = True
                continue
        a = st["arena"]; parent = (a.get("agents") or {}).get("battery-parent") or {}
        suite_id = a.get("suite_id"); problems = a.get("problems") or []
        if not parent.get("client_id") or not suite_id or not problems:
            log(f"FORGE | arena {fr} incomplete (parent/suite/problems) — battery disabled", fh)
            st["disabled"] = True
            continue
        port = st["port"]
        st["gen"] += 1; gen = st["gen"]
        try:
            pj = await _agent_token(c, port, parent["client_id"], parent["client_secret"])
            if not pj:
                log(f"FORGE | frame={fr} parent token mint failed — skipping generation", fh); continue
            r = await c.post(f"http://localhost:{port}/api/v1/agents/spawn", json={
                "name": f"forge-gen-{gen}" if fr == "c" else f"forge-{fr}-gen-{gen}",
                "permissions": ["cicd.version", "bundle.write", "exchange.trade", "teg.transfer"],
                "ttl_seconds": 86400, "max_per_tx": 100, "no_redelegate": True,
            }, headers={"Authorization": f"Bearer {pj}"}, timeout=25)
            if r.status_code != 200:
                log(f"FORGE | frame={fr} gen {gen}: spawn {r.status_code} — arena dark here?", fh); continue
            d = r.json()
            vjwt = await _agent_token(c, port, d["client_id"], d["client_secret"])
            cap = {"X-Capability-Token": d.get("birth_token", "")}
            flawed = (gen % 3 == 0)
            sols = [_forge_solve(p) for p in problems]
            if flawed and sols and sols[0]:
                sols[0] = list(sols[0]); sols[0][0] = "WRONG"
            rv = await c.post(f"http://localhost:{port}/api/v1/agents/self/version",
                              json={"version": f"0.{gen}.0", "release_notes": f"forge battery gen {gen}",
                                    "artifacts": {"answers": {"solutions": sols}}},
                              headers={"Authorization": f"Bearer {vjwt}", **cap}, timeout=25)
            _rvj = (rv.json() or {}) if rv.status_code == 200 else {}
            vid = _rvj.get("version_id") or _rvj.get("id")
            re_ = await c.post(f"http://localhost:{port}/api/v1/forge/evals/run",
                               json={"suite_id": suite_id},
                               headers={"Authorization": f"Bearer {vjwt}", **cap}, timeout=180)
            score = None; passed = False; adopted = None
            if re_.status_code == 200:
                rr = await c.get(f"http://localhost:{port}/api/v1/evals/agents/{d['child_did']}/results",
                                 params={"limit": 1}, timeout=20)
                results = (rr.json() or {}).get("results") if rr.status_code == 200 else None
                if results:
                    score = results[0].get("score"); passed = bool(results[0].get("passed"))
                    if passed and vid:
                        ra = await c.post(f"http://localhost:{port}/api/v1/agents/self/versions/{vid}/activate",
                                          headers={"Authorization": f"Bearer {vjwt}", **cap}, timeout=25)
                        adopted = ra.status_code == 200
            ok = (rv.status_code == 200) and (re_.status_code == 200) and (score is not None)
            expected = (not passed) if flawed else True   # a flawed gen SHOULD fail — that's a pass for the battery
            log(f"FORGE-GEN | frame={fr} gen {gen} | flawed={flawed} score={score} passed={passed} adopted={adopted} "
                f"| version={rv.status_code} eval={re_.status_code} "
                f"| SELF-CHECK={'100%' if (ok and expected) else 'INCOMPLETE'}", fh)
        except Exception as e:  # noqa: BLE001
            log(f"FORGE | frame={fr} gen {gen} error (non-fatal): {e}", fh)


# ── the IRONKEY conformance battery + audit self-check (one tick) ─────────────────────────────
async def _deleg_setup(c, framec: List["Agent"], login, fh):
    """One-time: grant a manager pool legacy-full (so they can issue/attenuate/spawn) + record the
    admin developer id (for L3 grants). Workers are plain trader-role frame-c agents."""
    if _deleg_state["ready"] or not framec:
        return
    port = framec[0].port
    aj = await _admin_jwt(c, port, login)
    if not aj:
        log("DELEG | no admin JWT on frame-c — delegation battery disabled this run", fh)
        _deleg_state["ready"] = True  # don't retry every cycle
        return
    try:
        prof = await c.get(f"http://localhost:{port}/api/v1/auth/profile", headers={"Authorization": f"Bearer {aj}"}, timeout=15)
        _deleg_state["admin_id"] = str((prof.json() or {}).get("id")) if prof.status_code == 200 else None
    except Exception:
        _deleg_state["admin_id"] = None
    pool = sorted(framec, key=lambda a: a.did)
    cand = pool[:_DELEG_MGR_POOL]
    granted = []
    for m in cand:
        if await _grant_legacy_full(c, m.port, aj, m.did):
            granted.append(m)          # keep ONLY managers that actually hold authz.delegate now
    _deleg_state["managers"] = granted
    _deleg_state["workers"] = pool[_DELEG_MGR_POOL:_DELEG_MGR_POOL + 12] or pool[:12]
    _deleg_state["ready"] = True
    log(f"DELEG | setup: {len(granted)}/{len(cand)} managers hold authz.delegate, "
        f"{len(_deleg_state['workers'])} workers, admin_id={_deleg_state['admin_id']}", fh)


async def _delegation_tick(c, framec: List["Agent"], login, cycle, fh) -> Optional[dict]:
    """Run ONE IRONKEY lifecycle instance on frame-c + an audit self-check. Returns a stats dict
    {fired, passed, denies_ok, audit_pct} or None if disabled. Every leg is guarded — a failed leg
    is counted, never crashes the tick. Δ-safe: deny paths are pre-escrow, budgets are bookkeeping."""
    await _deleg_setup(c, framec, login, fh)
    mgrs = _deleg_state.get("managers") or []
    wrks = _deleg_state.get("workers") or []
    if not mgrs or not wrks:
        return None
    _deleg_state["tick"] += 1
    tick = _deleg_state["tick"]
    M = mgrs[tick % len(mgrs)]
    W = wrks[tick % len(wrks)]
    X = wrks[(tick + 1) % len(wrks)]   # a DIFFERENT worker = the wrong-holder for misuse/breaker
    port = M.port
    fired: List[str] = []          # ironkey.<action> we expect to have produced an audit row
    passed = 0; denies_ok = 0; fail = 0
    _dbg: List[str] = []           # per-leg (name:status) telemetry — surfaced on the tick line
    async def hdr(a: "Agent"):
        return {"Authorization": f"Bearer {await get_jwt(c, a)}"}

    # 1) ISSUE att_ token M→W (budget 40, max_per_tx 5)
    tok = None; tid = None
    try:
        mh = await hdr(M)
        r = await c.post(f"http://localhost:{port}/api/v1/agents/capabilities",
                         json={"holder_agent_did": W.did,
                               "caveats": {"permissions": ["exchange.trade", "teg.transfer"], "max_per_tx": 5},
                               "budget_total": 40, "currency": "BVT", "ttl_seconds": 900}, headers=mh, timeout=20)
        _dbg.append(f"issue:{r.status_code}")
        if r.status_code == 200:
            tok = r.json().get("token"); tid = r.json().get("id"); fired.append("capability_issue"); passed += 1
        else: fail += 1
    except Exception as _e: _dbg.append(f"issue:x"); fail += 1

    wh = await hdr(W)
    # 2) CONSUME ok (amount 2 < budget)
    if tok:
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/agents/capabilities/consume",
                             json={"token": tok, "amount": 2, "currency": "BVT"}, headers=wh, timeout=20)
            _dbg.append(f"consume:{r.status_code}")
            if r.status_code == 200: fired.append("capability_consume"); passed += 1
            else: fail += 1
        except Exception: _dbg.append("consume:x"); fail += 1
    # 3) ATTENUATE (strictly ≤ parent — MUST carry max_per_tx ≤ parent's 5)
    if tid:
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/agents/capabilities/{tid}/attenuate",
                             json={"caveats": {"permissions": ["exchange.trade"], "max_per_tx": 3}, "ttl_seconds": 600},
                             headers=wh, timeout=20)
            _dbg.append(f"atten:{r.status_code}")
            if r.status_code == 200: fired.append("capability_attenuate"); passed += 1
            else: fail += 1
        except Exception: _dbg.append("atten:x"); fail += 1
    # 4) OVER-BUDGET consume DENY (amount 999 > remaining) — expected 422 = PASS
    if tok:
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/agents/capabilities/consume",
                             json={"token": tok, "amount": 999, "currency": "BVT"}, headers=wh, timeout=20)
            if r.status_code in (422, 403): denies_ok += 1
            else: fail += 1
        except Exception: fail += 1
    # 5) REVOKE the token (M) → cap_revoked
    if tid:
        try:
            r = await c.request("DELETE", f"http://localhost:{port}/api/v1/agents/capabilities/{tid}", headers=await hdr(M), timeout=20)
            if r.status_code == 200: fired.append("capability_revoke"); passed += 1
            else: fail += 1
        except Exception: fail += 1
    # 6) REVOKED-token REUSE DENY (W consumes it) — expected 403 + feeds ironkey.capability_misuse
    if tok:
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/agents/capabilities/consume",
                             json={"token": tok, "amount": 1, "currency": "BVT"}, headers=wh, timeout=20)
            if r.status_code == 403: denies_ok += 1; fired.append("capability_misuse")
            else: fail += 1
        except Exception: fail += 1
    # 7) L3 grant (dev→W) → act-token → over-cap act SPEND deny → revoke grant
    admin_id = _deleg_state.get("admin_id")
    if admin_id:
        aj = await _admin_jwt(c, port, login)
        gid = None
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/agents/{W.did}/delegations",
                             json={"principal_type": "dev", "principal_ref": f"dev:{admin_id}",
                                   "permissions": ["teg.transfer", "gov.propose"], "ttl_hours": 1},
                             headers={"Authorization": f"Bearer {aj}"}, timeout=20)
            _dbg.append(f"grant:{r.status_code}")
            if r.status_code == 200: fired.append("delegation_grant"); passed += 1
        except Exception: _dbg.append("grant:x"); fail += 1
        try:  # act-token mint (W acts as dev)
            r = await c.post(f"http://localhost:{port}/api/v1/agents/act-token",
                             json={"act_as": f"dev:{admin_id}"}, headers=wh, timeout=20)
            _dbg.append(f"act:{r.status_code}")
            if r.status_code == 200: fired.append("act_token_mint"); passed += 1
        except Exception: _dbg.append("act:x"); fail += 1
        try:  # revoke the grant → deleg_revoked
            lr = await c.get(f"http://localhost:{port}/api/v1/agents/{W.did}/delegations",
                             headers={"Authorization": f"Bearer {aj}"}, timeout=15)
            gs = (lr.json() or {}).get("grants", []) if lr.status_code == 200 else []
            gid = gs[0]["id"] if gs else None
            if gid:
                r = await c.request("DELETE", f"http://localhost:{port}/api/v1/delegations/{gid}",
                                    headers={"Authorization": f"Bearer {aj}"}, timeout=15)
                if r.status_code == 200: fired.append("delegation_revoke"); passed += 1
        except Exception: fail += 1
    # 8) CIRCUIT BREAKER trip (every _CB_EVERY ticks): sacrificial token, wrong-holder ×5
    if (tick % _CB_EVERY) == 0:
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/agents/capabilities",
                             json={"holder_agent_did": W.did, "caveats": {"permissions": ["exchange.trade"]},
                                   "ttl_seconds": 600}, headers=await hdr(M), timeout=20)
            if r.status_code == 200:
                stok = r.json().get("token"); stid = r.json().get("id")
                xh = await hdr(X)   # WRONG holder
                for _ in range(6):
                    await c.post(f"http://localhost:{port}/api/v1/agents/capabilities/consume",
                                 json={"token": stok, "amount": 0}, headers=xh, timeout=15)
                fired.append("capability_circuit_breaker_trip"); denies_ok += 1
                log(f"DELEG | tick {tick}: circuit-breaker trip fired (token {stid}, 6× wrong-holder)", fh)
        except Exception: fail += 1
    # 9) CROSS-REGISTRY leg (optional; frame-c → doha peer over federation)
    if XREG_DELEGATION:
        try:
            aj = await _admin_jwt(c, port, login)
            # discover a doha-homed agent + its registry url via federation agent-cards
            fr = await c.get(f"http://localhost:{port}/api/v1/federation/agent-cards?limit=50",
                             headers={"Authorization": f"Bearer {aj}"}, timeout=15)
            _remote = None
            if fr.status_code == 200:
                for _card in (fr.json() if isinstance(fr.json(), list) else (fr.json() or {}).get("cards", [])):
                    _rd = _card.get("agent_did") or _card.get("did")
                    if _rd and ":" in str(_rd):
                        _remote = _rd; break
            if _remote:
                r = await c.post(f"http://localhost:{port}/api/v1/agents/delegate-cross-registry",
                                 json={"delegate_did": _remote,
                                       "delegate_registry_url": "https://op-doha.op.theprotocol.cloud",
                                       "permissions": ["teg.transfer"], "ttl_hours": 1, "max_per_tx": 3},
                                 headers=await hdr(M), timeout=25)
                if r.status_code == 200: fired.append("xreg_delegation_issue"); passed += 1
        except Exception: fail += 1

    # ── AUDIT SELF-CHECK: assert each fired action left a durable security_audit_logs row ──────
    audit_pct = None; found = set()
    try:
        aj = await _admin_jwt(c, port, login)
        ar = await c.get(f"http://localhost:{port}/api/v1/admin/audit-logs",
                         params={"action": "ironkey.", "since_hours": 1, "limit": 500},
                         headers={"Authorization": f"Bearer {aj}"}, timeout=20)
        if ar.status_code == 200:
            body = ar.json()
            rows = body.get("items") or body.get("logs") or (body if isinstance(body, list) else [])
            for row in rows:
                act = (row.get("action") or "").replace("ironkey.", "")
                found.add(act)
        want = set(fired)
        hit = len(want & found)
        audit_pct = round(100.0 * hit / max(1, len(want)), 1)
    except Exception:
        audit_pct = None
    miss = sorted(set(fired) - found)
    log(f"DELEG | tick {tick} M=…{M.did[-8:]} W=…{W.did[-8:]} | fired={len(fired)} pass={passed} "
        f"denies_ok={denies_ok} fail={fail} | legs=[{' '.join(_dbg)}] | AUDIT-SELF-CHECK={audit_pct}%"
        + (f" MISSING={miss}" if miss else " (every fired action left its row)"), fh)
    return {"fired": len(fired), "passed": passed, "denies_ok": denies_ok, "fail": fail, "audit_pct": audit_pct}


# §backlog-aware (2026-06-13): poll each venue's settlement backlog (admin overview
# `settlement.pending`) so dynamic mode never outruns the settlement worker. The endpoint-
# launched sim container has NO docker socket/binary, so the in-container owner-JWT mint
# (_mint_owner_jwt) can't be used here — instead we log in as commander (creds from
# sim_credentials.json `_overview_login`) on each venue's port, JWT cached ~100min. Venues =
# the 3 mainframe frames that host venues (A/B/C). Any venue that errors is skipped =
# fail-open (no hold) — the sim must never wedge on a backlog read it can't do.
_OVERVIEW_JWT_CACHE: Dict[str, tuple] = {}   # registry_name -> (jwt, ts)
_BACKLOG_VENUES = ["Registry-A", "Frame-B", "Frame-C"]

async def _venue_backlog(c: httpx.AsyncClient, name: str, login: Optional[dict]) -> Optional[int]:
    info = REGISTRIES.get(name)
    if not info or not login:
        return None
    port = info["port"]
    jwt, ts = _OVERVIEW_JWT_CACHE.get(name, (None, 0.0))
    if not jwt or time.time() - ts > 6000:
        try:
            lr = await c.post(f"http://localhost:{port}/api/v1/auth/login",
                              data={"username": login.get("username"), "password": login.get("password")},
                              headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
            if lr.status_code == 200:
                jwt = lr.json().get("access_token")
                if jwt:
                    _OVERVIEW_JWT_CACHE[name] = (jwt, time.time())
        except Exception:
            return None
    if not jwt:
        return None
    try:
        r = await c.get(f"http://localhost:{port}{AGORA}/admin/overview",
                        headers={"Authorization": f"Bearer {jwt}"}, timeout=8)
        if r.status_code == 200:
            # Gate ONLY on settlement.pending (trades awaiting payout). NOT on the
            # 'funding' queue: settle drains autonomously (the worker settles pending
            # trades whether the sim runs or not), but passport funding drains via
            # cross-frame deposits coupled to new buy-flow — so HOLDing the sim starves
            # the gateway and funding floors at its solvency limit, deadlocking the gate
            # (proven 2026-06-13). Funding is bounded by the SWEEP rate instead
            # (EXCHANGE_PASSPORT_SWEEP_BATCH), which keeps it low while the sim runs.
            return int((r.json().get("settlement") or {}).get("pending", 0) or 0)
    except Exception:
        return None
    return None

async def backlog_max(c: httpx.AsyncClient, login: Optional[dict]):
    """(max_pending across the 3 venues, {venue: pending}) — venues that error are skipped."""
    res = await asyncio.gather(*[_venue_backlog(c, n, login) for n in _BACKLOG_VENUES])
    per = {n: v for n, v in zip(_BACKLOG_VENUES, res) if v is not None}
    return (max(per.values()) if per else 0), per


_BATCH_FAIL_REASON: Dict[int, str] = {}


async def _batch_balances(c: httpx.AsyncClient, port: int, dev_jwt: str, dids: list) -> Dict[str, float]:
    """POST /developers/me/agents/balances in <=50-DID chunks. Returns {did: balance}."""
    out: Dict[str, float] = {}
    for i in range(0, len(dids), 50):
        chunk = dids[i:i + 50]
        try:
            r = await c.post(f"http://localhost:{port}/api/v1/developers/me/agents/balances",
                json={"agent_dids": chunk}, headers={"Authorization": f"Bearer {dev_jwt}"}, timeout=20)
            if r.status_code == 200:
                bals = (r.json() or {}).get("balances", {})
                for did, info in bals.items():
                    # §AGORASIM (2026-09-22): an agent the login does not OWN comes back as balance "0" WITH an error
                    # ("Agent not found or not authorized"); reading it as 0 made a whole frame's roster unfunded
                    # and idle while every log line read clean (measured on the sandbox pair). Skip it: the caller
                    # checks such an agent one by one with its own token.
                    if isinstance(info, dict) and info.get("error"):
                        continue
                    if isinstance(info, dict):
                        out[did] = float(info.get("balance", info.get("total", 0)) or 0)
                    else:
                        out[did] = float(info or 0)
            else:
                # §BALCHECKFIX: a bare `except: pass` here hid WHY the batch path was skipped.
                _BATCH_FAIL_REASON[port] = f"HTTP {r.status_code}: {(r.text or '')[:100]}"
        except Exception as e:
            _BATCH_FAIL_REASON[port] = f"{type(e).__name__}: {str(e)[:100]}"
    return out

@dataclass
class Agent:
    did: str; name: str; client_id: str; client_secret: str
    registry: str; frame: str; port: int
    currency: str = "AVT"
    balance: float = 0.0; jwt: Optional[str] = None; jwt_ts: float = 0.0
    # §2026-07-19 IRONKEY desk model (CLUSTER-WIDE since §2026-07-19b) — a spawned execution-clerk
    # sub-agent (dict) this parent routes its market+passport orders through, homed on the parent's
    # OWN registry; None = parent trades directly. See _get_or_spawn_clerk.
    clerk: Optional[dict] = None
    # §2026-06-28 T1 — persistent per-agent strategy (stable across restarts via DID hash).
    archetype: str = "noise"; fair_mult: float = 1.0

def log(msg, fh=None):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    if fh: fh.write(line + "\n"); fh.flush()

async def get_jwt(c: httpx.AsyncClient, a: Agent) -> str:
    if a.jwt and time.time() - a.jwt_ts < 840: return a.jwt
    r = await c.post(f"http://localhost:{a.port}/api/v1/auth/agent/token",
        data={"username": a.client_id, "password": a.client_secret},
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    r.raise_for_status()
    a.jwt = r.json()["access_token"]; a.jwt_ts = time.time()
    return a.jwt

async def check_supply(c: httpx.AsyncClient) -> str:
    parts = []
    for frame, port in ES_PORTS.items():
        try:
            r = await c.get(f"http://localhost:{port}/api/v1/projections/supply-audit", timeout=5)
            d = r.json(); parts.append(f"{frame}:delta={d.get('delta','?')}")
        except: parts.append(f"{frame}:ERR")
    return " | ".join(parts)

async def run(args):
    global SPAWN_SUBAGENTS, XREG_DELEGATION, _CLERK_DIDS
    SPAWN_SUBAGENTS = bool(getattr(args, "spawn_subagents", False))
    XREG_DELEGATION = bool(getattr(args, "xreg_delegation", False))
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    # §AGORASIM-2: the run log's directory is a knob (the kit's frame-sim.py points it into its own state directory,
    # the kit tree is mounted read-only); unset keeps sessionlogs2026 relative to the working directory.
    _log_dir = os.getenv("SIM_LOG_DIR", "sessionlogs2026")
    os.makedirs(_log_dir, exist_ok=True)
    fh = open(os.path.join(_log_dir, f"sim_eigentrust_{ts}.log"), "w")
    creds = json.loads(Path(getattr(args, "credentials", None) or "scripts/sim_credentials.json").read_text())  # §BATCH8: --credentials
    _overview_login = creds.get("_overview_login")   # commander login for venue backlog reads (--max-backlog)

    # Build agents
    agents: List[Agent] = []
    for reg, alist in creds.items():
        if reg not in REGISTRIES: continue
        info = REGISTRIES[reg]
        for a in alist:
            agents.append(Agent(a["did"], a["name"], a["client_id"], a["client_secret"],
                                reg, info["frame"], info["port"],
                                currency=FRAME_CURRENCY.get(info["frame"], "AVT")))
    log(f"LOADED | {len(agents)} agents across {len(creds)} registries", fh)

    # ── §2026-06-28 T1 — assign each agent a STABLE trader archetype (deterministic DID
    # hash → reproducible across restarts). `noise` == the pre-archetype behavior. Δ-safe:
    # this only diversifies decision policy; settlement still runs through the escrow mover. ──
    _arch_mix = _load_archetypes()
    _arch_counts = {}
    for a in agents:
        a.archetype = _assign_archetype(a.did, _arch_mix)
        if a.archetype == "fundamental":
            a.fair_mult = _fair_mult(a.did)
        _arch_counts[a.archetype] = _arch_counts.get(a.archetype, 0) + 1
    log("ARCHETYPES | mix=" + ", ".join(f"{n}:{w:.2f}" for n, w in _arch_mix)
        + " | assigned=" + ", ".join(f"{k}={_arch_counts.get(k, 0)}" for k, _ in _ARCHETYPE_DEFAULT_MIX), fh)

    # Payment clients per registry
    clients: Dict[int, PaymentClient] = {}
    for info in REGISTRIES.values():
        clients[info["port"]] = PaymentClient(f"http://localhost:{info['port']}")

    async with httpx.AsyncClient(timeout=45) as c:
        # Check all balances at startup — BATCH per registry (owner-dev JWT), ~15 calls
        # instead of ~2N; far gentler on the worker-sensitive frame-c/ME-op registries.
        log("BALCHECK | batch balances per registry (owner-dev)...", fh)
        by_registry: Dict[str, List[Agent]] = {}
        for a in agents:
            by_registry.setdefault(a.registry, []).append(a)

        # §BALCHECKFIX — record WHY a registry fell back, per stage. Before this, the log said
        # only "per-agent fallback for N registries" and the cause was unknowable after the fact.
        _fb_why: Dict[str, str] = {}
        _fb_unread: List["Agent"] = []   # §AGORASIM: agents a registry's batch login could not read

        async def _batch_reg(reg, alist) -> bool:
            # §BALCHECKFIX-2 (2026-07-28): the batch fast-path used ONLY `docker exec` to mint the
            # owner JWT, which cannot work when the sim runs as an endpoint-launched CONTAINER —
            # eigentrust-sim-* has no /var/run/docker.sock, so all 15 registries fell back to the
            # 2-calls-per-agent path. `_admin_jwt()` (HTTP form login) already existed for exactly
            # this reason and its docstring says so; it was simply never wired in here.
            # Order matters: HTTP login first (works in BOTH container and host mode), docker exec
            # second (host mode only, and the only way to reach a cloud-op's own admin account,
            # which has no password we hold). Verified: the commander login returns the sim's own
            # agent balances on all three mainframes, and 401s on cloud-ops by design.
            cont, sub = REG_OWNER.get(reg, (None, None))
            dev_jwt = await _admin_jwt(c, alist[0].port, _overview_login)
            if not dev_jwt and cont:
                dev_jwt = await asyncio.to_thread(_mint_owner_jwt, cont, sub)
            if not dev_jwt:
                if not cont:
                    _fb_why[reg] = "no REG_OWNER mapping and no usable login"
                elif _DOCKER_UNAVAILABLE:
                    _fb_why[reg] = "expected in container mode: no host login for this registry and no docker socket"
                else:
                    _fb_why[reg] = f"owner-JWT mint failed ({_MINT_FAIL_REASON.get(cont, 'unknown')})"
                return False
            bmap = await _batch_balances(c, alist[0].port, dev_jwt, [a.did for a in alist])
            if not bmap:
                _fb_why[reg] = f"batch call returned nothing ({_BATCH_FAIL_REASON.get(alist[0].port, 'empty response')})"
                return False
            for a in alist:
                if a.did in bmap:
                    a.balance = bmap[a.did]
                else:
                    _fb_unread.append(a)   # §AGORASIM: not readable by this login; checked with its own token below
            return True

        regs = list(by_registry.keys())
        batch_ok = await asyncio.gather(*[_batch_reg(reg, by_registry[reg]) for reg in regs],
                                        return_exceptions=True)

        # Per-agent fallback for any registry whose batch path was unavailable.
        sem = asyncio.Semaphore(20)
        async def _chk(a):
            async with sem:
                try:
                    jwt = await get_jwt(c, a)
                    r = await c.get(f"http://localhost:{a.port}/api/v1/teg/balance",
                        headers={"Authorization": f"Bearer {jwt}"})
                    a.balance = float(Decimal(r.json().get("balance", "0"))) if r.status_code == 200 else 0
                except: a.balance = 0
        failed_regs = [reg for reg, ok in zip(regs, batch_ok) if ok is not True]
        if failed_regs:
            # §BALCHECKFIX-2: collapse the EXPECTED container-mode fallbacks into one line.
            # 12 identical "no docker socket" lines read like an outage; they are a known mode.
            expected = [r for r in failed_regs if 'expected in container mode' in _fb_why.get(r, '')]
            unexpected = [r for r in failed_regs if r not in expected]
            if expected:
                log(f"BALCHECK | per-agent path for {len(expected)} cloud-op(s) "
                    f"(container mode: no host login, no docker socket) - normal, not an error", fh)
            if unexpected:
                log(f"BALCHECK | per-agent FALLBACK for {len(unexpected)} registr(ies): {unexpected}", fh)
                for _r in unexpected:
                    log(f"BALCHECK |   {_r}: {_fb_why.get(_r, 'unknown reason')}", fh)
            fb = [a for reg in failed_regs for a in by_registry[reg]]
            await asyncio.gather(*[_chk(a) for a in fb], return_exceptions=True)
        else:
            log(f"BALCHECK | batch OK for all {len(regs)} registries", fh)
        if _fb_unread:
            log(f"BALCHECK | {len(_fb_unread)} agent(s) the batch login does not own: checked one by one with their own token", fh)
            await asyncio.gather(*[_chk(a) for a in _fb_unread], return_exceptions=True)

        funded = [a for a in agents if a.balance >= TRANSFER_MAX + 10]
        by_frame = {f: [a for a in funded if a.frame == f] for f in sorted({a.frame for a in funded})}
        by_reg: Dict[str, List[Agent]] = {}
        for a in funded: by_reg.setdefault(a.registry, []).append(a)

        log("POOL | " + str(len(funded)) + " funded (" + ", ".join(f"{f}={len(by_frame.get(f,[]))}" for f in sorted(by_frame)) + ")", fh)

        # §AGORASIM-2 (2026-09-22): the balances above were read ONCE, then only ever debited locally (passport buys),
        # so a keeper's refill never reached the sim: traders refilled to 1,000,000 skipped with "insufficient local
        # balance" / "float low", and a trader dropped under the funded floor stayed out of the pools for the rest of the
        # run. Every SIM_BALANCE_REFRESH_S (120; 0 = off) the real balances are re-read (the batch only where it worked
        # at startup, else each agent with its own token; a failed read keeps the last known balance) and the pools are
        # rebuilt IN PLACE, so every closure holding them sees the change.
        _BAL_REFRESH_S = float(os.getenv("SIM_BALANCE_REFRESH_S", "120"))
        _bal_refresh = {"at": time.monotonic()}
        _batch_regs_ok = [reg for reg, ok in zip(regs, batch_ok) if ok is True]

        async def _chk_keep(a):
            async with sem:
                try:
                    _j = await get_jwt(c, a)
                    _r = await c.get(f"http://localhost:{a.port}/api/v1/teg/balance", headers={"Authorization": f"Bearer {_j}"})
                    if _r.status_code == 200:
                        a.balance = float(Decimal(_r.json().get("balance", "0")))
                except Exception:
                    pass

        async def _refresh_balances_and_pools():
            _fb_unread.clear()
            _okb = await asyncio.gather(*[_batch_reg(reg, by_registry[reg]) for reg in _batch_regs_ok], return_exceptions=True)
            _per = [a for reg in regs if reg not in _batch_regs_ok for a in by_registry[reg]]
            _per += [a for reg, ok in zip(_batch_regs_ok, _okb) if ok is not True for a in by_registry[reg]] + list(_fb_unread)
            if _per:
                await asyncio.gather(*[_chk_keep(a) for a in _per], return_exceptions=True)
            _n0 = len(funded)
            funded[:] = [a for a in agents if a.balance >= TRANSFER_MAX + 10]
            _bf: Dict[str, List[Agent]] = {}
            _br: Dict[str, List[Agent]] = {}
            for a in funded:
                _bf.setdefault(a.frame, []).append(a)
                _br.setdefault(a.registry, []).append(a)
            by_frame.clear(); by_frame.update({f: _bf[f] for f in sorted(_bf)})
            by_reg.clear(); by_reg.update(_br)
            return _n0, len(funded)
        # §AGORASIM-2: ask every home whether it can exchange currency before any passport order is placed
        for _rk, _ri in REGISTRIES.items():
            try:
                _fx = await c.get(f"http://localhost:{_ri['port']}/api/v1/teg/fx/rates", timeout=10)
                if _fx.status_code == 200 and (_fx.json() or {}).get("available") is False:
                    _NO_FX_HOMES.add(_rk)
            except Exception:
                pass
        if _NO_FX_HOMES:
            log(f"FXHOMES | no currency exchange on {sorted(_NO_FX_HOMES)}: their passport orders stay in their own currency", fh)

        # ── §2026-07-19 IRONKEY startup — desk-model + persisted-clerk reuse ─────────────────────
        # §2026-07-19b CLUSTER-WIDE: AGENT_SPAWN_ENABLED is now true on ALL 16 registries, so every
        # funded parent spawns its clerk on its OWN registry/port (one JWT domain each — no cross-
        # registry calls, frame-bound by construction). IRONKEY rbac/deleg stay enforce ONLY on the
        # Frame-C MAINFRAME (:8101) → the delegation BATTERY (needs real DENYs) still uses ONLY
        # registry=="Frame-C" agents; everywhere else the birth token rides audit-only.
        _framec_mf = [a for a in agents if a.registry == _DELEG_MF]   # §BATCH8: was by_frame["C"] + "Frame-C"
        # §XREGMODE — mainframe parents on the configured spawn frames get the authz.delegate grant
        # (SIM_SPAWN_FRAMES; default frame-c only; "A,B,C" spawns clerks on all three mainframes).
        # The delegation BATTERY stays frame-c-only (_framec_mf) — it needs the enforce DENYs there.
        _spawn_mf_names = {_MF_NAME[f] for f in _SPAWN_FRAMES if f in _MF_NAME}
        _spawn_mf = [a for a in funded if a.registry in _spawn_mf_names]
        if SPAWN_SUBAGENTS or args.mode == "delegation":
            _load_spawned_creds()
        _xreg_senders: List[Agent] = []
        if SPAWN_SUBAGENTS and funded:
            _CLERK_DIDS = _clerk_pool_dids(funded)
            await _ensure_spawn_pool(c, _spawn_mf, _overview_login, fh)   # grants: enforce side, configured frames
            log(f"DESK | spawn-subagents ON — CLUSTER-WIDE: {len(_CLERK_DIDS)} parents across "
                f"{len(by_reg)} registries route via execution clerks "
                f"(reusing {len(_spawned_creds)} persisted); spawn-grant frames={sorted(_SPAWN_FRAMES)}", fh)
            # §XREGMODE eligible senders: spawn-frame mainframe parents holding a clerk (so the
            # 100%-foreign flow truly rides a SUBAGENT SPAWN), else fall back to passport-home ops.
            _xreg_senders = [a for a in _spawn_mf if a.did in _CLERK_DIDS] \
                or [a for k in PASSPORT_HOMES for a in by_reg.get(k, [])]
            if _XREG_ONLY:
                log(f"XREGMODE | SIM_XREG_ONLY=on — 100% FOREIGN passport order-flow via clerks on "
                    f"{sorted(_SPAWN_FRAMES)} ({len(_xreg_senders)} eligible senders); "
                    f"anchored_clerk={_CLERK_ANCHORED}", fh)
        if args.mode == "delegation":
            log("DELEG | mode=delegation — IRONKEY conformance battery + audit self-check on frame-c mainframe", fh)

        # ── §V0064 AGORA `market` mode state ──────────────────────────────
        # Venue listings per registry (refreshed each cycle for live `last`)
        # + EigenTrust anchor per listing-treasury DID (fetched once, 0.5 on
        # any miss — trust-score 404s until the GTV epoch task has run).
        _venue_cache: Dict[str, list] = {}
        _lw_cache = {"key": None, "w": {}}   # §V0073 cached local-market venue weights (recomputed when the venue set changes)
        _trust_cache: Dict[str, float] = {}
        _ob_cache: Dict[str, dict] = {}      # §T2 throttled top-of-book depth: SYMBOL -> {bid_depth, ask_depth, top_bid_qty, top_ask_qty, ts}
        _xref: Dict[str, dict] = {}          # §T7 cross-venue parity map (SYMBOL -> {ref, n}); rebuilt each cycle from _venue_cache when ARB_ENABLED

        async def _refresh_federation_ticker():
            """§SIMFEDTICKER — ONE call, all 16 venues, every tradable symbol.

            Merged UNDER the per-registry local read below, never over it: the local
            call carries fields the ticker does not, so the ticker fills gaps (a venue
            with no sim agent, a symbol the local read missed) rather than replacing
            richer data. Never raises — a ticker outage degrades to today's behaviour.
            """
            try:
                _any = next(iter(by_reg.values()), None)
                if not _any:
                    return 0, 0
                _r = await c.get(f"http://localhost:{_any[0].port}{AGORA}/federation-tickers",
                                 timeout=45)
                if _r.status_code != 200:
                    return 0, 0
                _known = set(by_reg.keys())
                _added = _venues_seen = 0
                for _v in (_r.json() or {}).get("venues", []):
                    _key = _venue_to_regkey(_v.get("venue"), _known)
                    if not _key:
                        # No sim agent lives here, so it can never enter the LOCAL path
                        # (that list is filtered on by_reg). Admit it under its slug so
                        # the PASSPORT path can still reach its book — otherwise a whole
                        # venue's listings are simply never traded by anyone.
                        _key = (_v.get("venue") or "").strip()
                        if not _key:
                            continue
                        _passport_only_venues.add(_key)
                    _venues_seen += 1
                    _have = {(x.get("symbol") or "").upper() for x in _venue_cache.get(_key, [])}
                    _new = [_ticker_row_to_listing(_row, _v.get("currency") or "AVT")
                            for _row in (_v.get("listings") or [])
                            if (_row.get("symbol") or "").upper() not in _have
                            and (_row.get("status") or "trading") == "trading"
                            and (not _SIM_SYMBOLS or (_row.get("symbol") or "").upper() in _SIM_SYMBOLS)]
                    if _new:
                        _venue_cache.setdefault(_key, []).extend(_new)
                        _added += len(_new)
                return _venues_seen, _added
            except Exception:
                return 0, 0

        async def _refresh_venues():
            for _reg, _alist in by_reg.items():
                try:
                    _r = await c.get(f"http://localhost:{_alist[0].port}{AGORA}/listings", timeout=10)
                    _ls = [x for x in (_r.json().get("listings", []) if _r.status_code == 200 else [])
                           if x.get("status") == "trading" and x.get("approved")
                           and (not _SIM_SYMBOLS or (x.get("symbol") or "").upper() in _SIM_SYMBOLS)]
                    if _ls:
                        _venue_cache[_reg] = _ls
                        for _x in _ls:   # §T1/T2 roll per-symbol `last` (a price the sim already read) for SMA + realized-vol; §T5 fold into the vol-state EWMAs
                            _sym = (_x.get("symbol") or "").upper()
                            _lp = (_x.get("stats") or {}).get("last") or _x.get("ipo_price")
                            if _sym and _lp:
                                try:
                                    _lpf = float(_lp)
                                except (TypeError, ValueError):
                                    continue
                                _dq = _price_hist[_sym]
                                _vol_update(_sym, _dq[-1] if _dq else None, _lpf)   # §T5 EWMA(r^2) from prev→new last (before append)
                                _dq.append(_lpf)
                    else:
                        _venue_cache.pop(_reg, None)
                except Exception:
                    _venue_cache.pop(_reg, None)

        async def _refresh_orderbooks():
            """§T2 throttled top-of-book DEPTH read, mainframe-venue symbols only. best_bid/
            best_ask/last (→ spread/mid) already arrive free in the listings `stats`; only resting
            DEPTH needs the /book endpoint. Read-only + throttled (every MICRO_OB_EVERY cycles) +
            sequential (no burst) → negligible added load; emits NO orders → Δ untouched. Updates
            _ob_cache, which persists across cycles so MICRO/JSONL always carry the latest depth."""
            for _reg in MAINFRAMES:
                _ls = _venue_cache.get(_reg) or []
                if not _ls or _reg not in by_reg:
                    continue
                _port = by_reg[_reg][0].port
                for _x in _ls:
                    _sym = _x.get("symbol")
                    if not _sym:
                        continue
                    try:
                        _r = await c.get(
                            f"http://localhost:{_port}{AGORA}/listings/{_sym}/book",
                            params={"depth": 5}, timeout=8)
                        if _r.status_code != 200:
                            continue
                        _b = _r.json() or {}
                        _bids = _b.get("bids") or []
                        _asks = _b.get("asks") or []
                        _ob_cache[_sym.upper()] = {
                            "bid_depth": sum(int(x.get("qty", 0) or 0) for x in _bids),
                            "ask_depth": sum(int(x.get("qty", 0) or 0) for x in _asks),
                            "top_bid_qty": int(_bids[0].get("qty", 0) or 0) if _bids else 0,
                            "top_ask_qty": int(_asks[0].get("qty", 0) or 0) if _asks else 0,
                            "ts": time.time(),
                        }
                    except Exception:
                        continue

        # ── §2026-06-17 FX managed-float driver ───────────────────────────
        _fx_spot = {"AVT": 1.0}   # live FX spot per ccy (in AVT)
        _fx_absent_logged: set = set()   # §AGORASIM-2: target sets already reported as absent on this network

        async def _refresh_fx_rates():
            """Poll live cross-frame FX spot (1 ccy = X AVT) from /teg/fx/rates (registry-a)."""
            try:
                _r = await c.get("http://localhost:8000/api/v1/teg/fx/rates", timeout=8)
                if _r.status_code == 200:
                    for _p in _r.json().get("pairs", []):
                        _a, _b = _p.get("a"), _p.get("b")
                        try:
                            if _a == "AVT": _fx_spot[_b] = float(_p["a_per_b"])
                            elif _b == "AVT": _fx_spot[_a] = float(_p["b_per_a"])
                        except (TypeError, ValueError, KeyError):
                            pass
            except Exception:
                pass

        def _apply_fx_bias(s, r, targets, band, bias):
            """Managed-float direction bias. The RECEIVER's currency appreciates (its reserve
            drops on the swap). Bias the (sender,receiver) order so the currency furthest BELOW
            its target becomes the receiver (pushed UP) → mean-reverts toward target. Inside the
            band the bias→~0 (50/50 noise = a 'living' market); outside it strengthens. → (s, r)."""
            def _desire(ccy):
                t = targets.get(ccy); sp = _fx_spot.get(ccy)
                if not t or not sp or t <= 0:
                    return 0.0
                return (t - sp) / t   # >0 ⇒ below target ⇒ wants to appreciate (be receiver)
            cs = FRAME_CURRENCY.get(s.frame, "AVT")
            cr = FRAME_CURRENCY.get(r.frame, "AVT")
            diff = _desire(cr) - _desire(cs)   # >0 ⇒ keep order (r already receiver)
            scale = band if band > 0 else 0.08
            x = max(-1.0, min(1.0, diff / scale))
            p_keep = max(0.05, min(0.95, 0.5 + bias * 0.5 * x))
            return (s, r) if random.random() < p_keep else (r, s)

        async def _refresh_director_http(_c):
            """Poll the AGORA demand-director (DB-backed) from the registry each cycle.
            {SYMBOL:{dir,strength}} when enabled, {} when disabled, None on failure
            (→ caller falls back to the bind-mounted agora_director.json)."""
            # §AGORASIM (2026-09-22): the director is a per-registry DB flag. The URL was registry-a's alone, so a
            # self-contained network steered by ITS OWN directors read the prod frames' tickers instead (measured);
            # with SIM_REGISTRIES_JSON the sim asks every mainframe of that network and merges the enabled ones.
            _urls = ([f"http://localhost:{REGISTRIES[_k]['port']}{AGORA}/demand-director"
                      for _k in sorted(MAINFRAMES) if _k in REGISTRIES]
                     if os.getenv("SIM_REGISTRIES_JSON") else [f"http://localhost:8000{AGORA}/demand-director"])
            _tickers, _any_ok, _any_on = {}, False, False
            for _u in _urls:
                try:
                    _r = await _c.get(_u, timeout=6)
                except Exception:
                    continue
                if _r.status_code != 200:
                    continue
                try:
                    _d = _r.json()
                except Exception:
                    continue
                _any_ok = True
                if _d.get("enabled", False):
                    _any_on = True
                    _tickers.update(_d.get("tickers") or {})
            if not _any_ok:
                return None
            if not _any_on:
                return {}
            try:
                _out = {}
                for _sym, _cfg in _tickers.items():
                    try:
                        _out[str(_sym).upper()] = {"dir": float(_cfg.get("dir", 0)),
                                                   "strength": max(0.0, min(1.0, float(_cfg.get("strength", 0.7)))),
                                                   "intensity": max(0.0, min(1.0, float(_cfg.get("intensity", 0.0)))),
                                                   "volatility": max(0.0, min(1.0, float(_cfg.get("volatility", 0.0)))),
                                                   "regime": str(_cfg.get("regime", "calm"))}
                    except (TypeError, ValueError):
                        pass
                return _out
            except Exception:
                return None

        async def _trust_anchor(port: int, did: str) -> float:
            if did in _trust_cache: return _trust_cache[did]
            t = 0.5
            try:
                _r = await c.get(f"http://localhost:{port}/api/v1/reputation/{did}/trust-score", timeout=8)
                if _r.status_code == 200:
                    v = _r.json().get("trust_score")
                    if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0: t = float(v)
            except Exception:
                pass
            _trust_cache[did] = t
            return t
        supply = await check_supply(c)
        log(f"SUPPLY | {supply}", fh)

        # ── Dynamic auto-regulation state (AIMD controller, 2026-06-06) ───────
        # Closed loop: hold an avg settle-time SLO by adjusting in-flight
        # concurrency. Additive-increase when comfortably under target; fast
        # multiplicative-decrease + cooldown on breach/errors. Self-tunes to the
        # max error-free rate for sustained runs as the canary baseline shifts.
        import collections as _collections
        _dyn = bool(getattr(args, "dynamic", False))
        _dyn_n = args.min_concurrency if _dyn else 0          # start gentle, probe up
        _dyn_cooldown = 0
        _dyn_hist = _collections.deque(maxlen=max(1, args.control_window))
        # §2026-06-18 ZERO-CANCEL footprint cap: the sim NEVER cancels its own quotes
        # (the cancel-replace + 429 self-heal were removed — they were the only sim-side
        # cancellation source). Instead each agent caps its live quotes per listing at
        # MAX_RESTING and SKIPS a fire when already at the cap; resting orders clear only
        # by FILLING or ORDER_TTL expiry. Track (order_id, placed_monotonic) per
        # (agent, listing) for THIS process; entries older than the TTL window are pruned
        # locally (the server already expired them) so a filled/expired quote never wrongly
        # holds a slot. ≤3/agent/listing/process × ≤4 procs = ≤12 — far under the venue's
        # 20-open cap, so the 429 can't happen by construction.
        ORDER_TTL = 300                      # resting-limit TTL (s); server reaps, we prune locally past this
        _open_orders = {}                    # (agent_did, symbol) -> [(order_id, placed_monotonic), ...] (this process)
        MAX_RESTING = 3                      # ≤3 live quotes/agent/listing/process
        _FINISHED = ("filled", "cancelled", "canceled", "expired", "rejected", "failed")

        async def _prune_finished(_key, _port, _hdrs, _symbol):
            """§AGORASIM-2 (2026-09-22): a tracked order that has since filled, been cancelled or expired frees its slot.
            The tracker pruned only by age (ORDER_TTL + 60 s), so an order that rested and filled a minute later held
            its slot for six, and traders on a one-listing venue sat out ("at resting cap"). Asked only when a trader
            looks capped: one read of its own recent orders on that listing. An id the venue does not report stays
            until it ages out (it may have been placed under another routing of the same trader)."""
            held = _open_orders.get(_key, [])
            if not held:
                return held
            try:
                _r = await c.get(f"http://localhost:{_port}{AGORA}/orders/mine", params={"listing": _symbol},
                                 headers=_hdrs, timeout=10)
                if _r.status_code != 200:
                    return held
                _st = {str(o.get("id")): str(o.get("status") or "") for o in (_r.json() or {}).get("orders", [])}
            except Exception:
                return held
            keep = [(oid, ts) for (oid, ts) in held if _st.get(str(oid)) not in _FINISHED]
            _open_orders[_key] = keep
            return keep
        # §2026-06-20 PRICE ANCHOR (fixes the runaway). The old pricing was a driftless
        # multiplicative random walk on `last` with a band relative to `last` → no restoring
        # force → `last` wandered unboundedly (FLUX reached 87,000× IPO; also crashed to ~96×
        # and re-exploded — a walk, not a ratchet). Cure: mean-revert toward a STABLE
        # fundamental (ipo_price × EQ_ANCHOR_MULT) in log-space + an ABSOLUTE band clamp
        # [ipo×EQ_ABS_FLOOR_MULT, ipo×EQ_ABS_CEIL_MULT] as a hard circuit-breaker. Tunable via
        # env (no rebuild — bind-mounted). Matches Frame-C's healthy ~20–60× band.
        EQ_ANCHOR_MULT     = float(os.getenv("SIM_EQ_ANCHOR_MULT", "20"))    # fair = ipo × this
        EQ_REVERT_THETA    = float(os.getenv("SIM_EQ_REVERT_THETA", "0.01")) # log-reversion per fire (0=off) §2026-06-24 widened 0.18→0.05→0.01 — near-free walk so the displayed `last` wanders (high volume × any reversion pins the close); still hard-bounded by EQ_ABS_FLOOR/CEIL ipo×[0.5,80] (Commander req, testing)
        EQ_ABS_CEIL_MULT   = float(os.getenv("SIM_EQ_ABS_CEIL_MULT", "80"))  # hard ceiling = ipo × this
        EQ_ABS_FLOOR_MULT  = float(os.getenv("SIM_EQ_ABS_FLOOR_MULT", "0.5"))# hard floor   = ipo × this
        def _arb_gap(_sym, _li):
            """§T7 log-deviation of a listing's `last` from its cross-venue/anchor parity.
            >0 ⇒ RICH (the arb leans SELL toward parity); <0 ⇒ CHEAP (leans BUY); None if
            unpriceable. Reference = cross-venue mean `last` when the symbol trades on 2+
            venues (_xref n>=2), else the fundamental anchor (ipo×EQ_ANCHOR_MULT)."""
            try:
                _last = float((_li.get("stats") or {}).get("last") or _li.get("ipo_price") or 0)
                _ipo2 = float(_li.get("ipo_price") or 0)
            except (TypeError, ValueError):
                return None
            _xr = _xref.get((_sym or "").upper()) or {}
            _ref = _xr.get("ref") if _xr.get("n", 0) >= 2 else (_ipo2 * EQ_ANCHOR_MULT if _ipo2 > 0 else None)
            if not _ref or _ref <= 0 or _last <= 0:
                return None
            return math.log(_last / _ref)
        # §2026-06-20 BIDIRECTIONAL PASSPORT: probability a passport fire is a SELL of a
        # share the agent already holds (recoups cash → cash recirculates instead of the
        # one-way buys-only drain). Only fires when the agent has tracked holdings.
        PASSPORT_SELL_SHARE = float(os.getenv("SIM_PASSPORT_SELL_SHARE", "0.2"))  # §2026-06-20 0.4→0.2: 0.4 sold so hot into frame-c that repat creation≈drain (standing ~95 queue + /teg/send 503s); 0.2 lets drain outpace → queue clears, still amply demonstrates bidirectional.
        _passport_holdings = {}              # agent_did -> {(venue, symbol): approx_qty_held}

        # ══ §PASSPORTSELL (2026-08-22) — fill-tracking. Holdings credit on CONFIRMED
        # fills read back through the home passport status relay, never on the relay's
        # 200: acceptance is not a fill, and a 'funding' buy may never land (that
        # over-count is why sells 409'd and got clamped off under xreg-only).
        # SIM_PASSPORT_FILLTRACK=0 reverts to the legacy optimistic tracker INCLUDING
        # the xreg-only sell clamp. Parents rebuild holdings from the venue's own
        # portfolio (restart-proof); clerks are born fresh each run — nothing to rebuild.
        _FILLTRACK = os.getenv("SIM_PASSPORT_FILLTRACK", "1") == "1"
        # How long to keep tracking a NON-terminal order. MEASURED (2026-08-22,
        # frame-c, 5h window): venue fills average ~38 min and open orders live for
        # hours — a TTL-scale cap here silently dropped almost every future fill,
        # which re-creates the exact "holdings never grow" defect this tracker
        # exists to close. Bound is memory-safety only, so it is generous.
        _PP_TRACK_SEC = float(os.getenv("SIM_PASSPORT_TRACK_SEC", "10800"))
        # Don't poll entries younger than this — a passport buy spends its first
        # minute in 'funding' and cannot be terminal yet; skipping the young keeps
        # the poll volume proportional to orders that could actually have news.
        _PP_MIN_POLL_AGE = 60.0
        _pp_pending = {}      # did -> list[dict(s, venue, sym, oid, qty, side, ts, clerk)]
        _pp_rebuilt = set()   # (did, venue) already portfolio-seeded (parent identity only)
        _pp_stats = {"fills": 0, "stale": 0, "sell_recredit": 0, "polls": 0}
        _last_fillpoll = 0.0

        async def _poll_passport_fills(c, fh):
            """Batched status poll per (agent, venue, identity): terminal buys credit
            their FILLED qty; terminal sells re-credit the UNFILLED remainder that was
            decremented at accept; stale/never-landed refs are dropped and COUNTED."""
            _pp_stats["polls"] += 1
            for _did in list(_pp_pending.keys()):
                _plist = _pp_pending.get(_did) or []
                if not _plist:
                    _pp_pending.pop(_did, None)
                    continue
                _groups = {}
                _keep = []
                _now = time.time()
                for _e in _plist:
                    if (_now - _e["ts"]) < _PP_MIN_POLL_AGE:
                        _keep.append(_e)   # too young to be terminal — skip this round
                        continue
                    _groups.setdefault((_e["venue"], _e["clerk"]), []).append(_e)
                for (_venue, _is_clerk), _entries in _groups.items():
                    # The status endpoint takes ≤50 ids: ONLY the queried slice may be
                    # judged against the response — judging unqueried entries reads
                    # every one of them as "missing" and stales real orders. Oldest
                    # first, so long-lived orders are never starved by new flow.
                    _entries.sort(key=lambda x: x["ts"])
                    _entries, _overflow = _entries[:50], _entries[50:]
                    _keep.extend(_overflow)
                    try:
                        _s0 = _entries[0]["s"]
                        if _is_clerk:
                            _ck = await _get_or_spawn_clerk(c, _s0, _overview_login, fh)
                            _pj = (_ck or {}).get("jwt")
                        else:
                            _pj = await get_jwt(c, _s0)
                        if not _pj:
                            _keep.extend(_entries)
                            continue
                        _r = await c.post(
                            f"http://localhost:{_s0.port}{AGORA}/passport/order-status",
                            # §AGORASIM-2 (2026-09-22): the NAME the order was placed under, not the sim's key. The pending
                            # entry keeps the key; the relay resolves peer_registries.name, so on a network whose keys
                            # differ from its peer names (the sandbox's sbx-alpha vs its peer row) every status query
                            # answered 502 "no ACTIVE peer registry" and the pending list only grew (552 in two hours).
                            json={"venue_registry": _venue_wire_name(_venue), "order_ids": [x["oid"] for x in _entries]},
                            headers={"Authorization": f"Bearer {_pj}"}, timeout=30)
                        if _r.status_code != 200:
                            _keep.extend(_entries)
                            continue
                        _by = {o.get("order_id"): o for o in (_r.json() or {}).get("orders", [])}
                        _held2 = _passport_holdings.get(_did) or {}
                        for _e in _entries:
                            _o = _by.get(_e["oid"])
                            _age = time.time() - _e["ts"]
                            if _o is None:
                                if _age > ORDER_TTL + 120:
                                    _pp_stats["stale"] += 1
                                else:
                                    _keep.append(_e)
                                continue
                            _st = str(_o.get("status") or "")
                            _filled = int(_o.get("filled_qty") or 0)
                            if _st in ("filled", "cancelled", "expired", "rejected"):
                                _k2 = (_e["venue"], _e["sym"])
                                if _e["side"] == "buy":
                                    if _filled > 0:
                                        _held2[_k2] = int(_held2.get(_k2, 0)) + min(_filled, _e["qty"])
                                        _pp_stats["fills"] += 1
                                    else:
                                        _pp_stats["stale"] += 1
                                else:
                                    _un = max(0, _e["qty"] - _filled)
                                    if _un > 0:
                                        _held2[_k2] = int(_held2.get(_k2, 0)) + _un
                                        _pp_stats["sell_recredit"] += 1
                            elif _age > _PP_TRACK_SEC:
                                # memory cap only: the order may STILL fill later —
                                # the venue's own free/locked check stays the truth;
                                # we just stop watching (no re-credit for sells:
                                # that could double-count if the sell later fills).
                                _pp_stats["stale"] += 1
                            else:
                                _keep.append(_e)
                        _passport_holdings[_did] = _held2
                    except Exception:
                        _keep.extend(_entries)
                if _keep:
                    _pp_pending[_did] = _keep
                else:
                    _pp_pending.pop(_did, None)
            log(f"PASSPORTSELL | fills={_pp_stats['fills']} stale={_pp_stats['stale']} "
                f"sell_recredit={_pp_stats['sell_recredit']} "
                f"pending={sum(len(v) for v in _pp_pending.values())}", fh)

        # Registry-health backpressure state: watch the 3 mainframe registries directly
        # (registry-a is the FX origin + highest-load node) so the sim eases off BEFORE
        # it saturates one — a signal the settle-time SLO alone can miss.
        _health_ports = [(n, REGISTRIES[n]["port"]) for n in ("Registry-A", "Frame-B", "Frame-C") if n in REGISTRIES]
        _last_health = 0.0
        _health_bad_streak = 0
        # §backlog backpressure state (--max-backlog)
        _last_backlog_poll = 0.0
        _backlog_hold = False
        _backlog_pending = 0
        # §market-AIMD-fix (2026-06-13): market mode now feeds the AIMD a real venue-order
        # p50 (pct_market) so the target_settle_ms governor actually regulates venue
        # order-flow. HARD-CAP the target at 2500ms in market mode — a higher peg lets the
        # controller drive in-flight up until the escrow mover convoys, which lags the whole
        # frame badly (the 5000ms-peg crash class). Raise pressure via --max-concurrency, NOT
        # via a higher target; the 2500ms governor + circuit-breaker keep it safe.
        if _dyn and args.mode == "market" and args.target_settle_ms > 2500:
            log(f"DYN | market mode: clamping target_settle_ms {args.target_settle_ms}->2500 (server-safety)", fh)
            args.target_settle_ms = 2500
        if _dyn:
            log(f"DYN | auto-regulation ON: hold {args.target_metric} settle <= {args.target_settle_ms}ms "
                f"via concurrency [{args.min_concurrency}..{args.max_concurrency}] start {_dyn_n}; "
                f"AIMD up=+{args.aimd_up} down=x{args.aimd_down} cooldown={args.cooldown} window={args.control_window}", fh)

        # Run cycles
        for cycle in range(1, args.cycles + 1):
            t0 = time.time()
            if _BAL_REFRESH_S > 0 and time.monotonic() - _bal_refresh["at"] >= _BAL_REFRESH_S:
                _bal_refresh["at"] = time.monotonic()
                try:
                    _n0, _n1 = await _refresh_balances_and_pools()
                    log(f"BALREFRESH | real balances re-read; funded {_n0} -> {_n1}", fh)
                except Exception as _bre:
                    log(f"BALREFRESH | skipped this time: {type(_bre).__name__}: {str(_bre)[:120]}", fh)
            # ── §2026-07-19 DELEGATION MODE — the IRONKEY conformance battery IS the cycle. Runs
            # the full lifecycle + audit self-check on frame-c, then sleeps the interval. No market
            # machinery (skips the whole transfer/venue path below). Δ-safe (deny paths pre-escrow).
            if args.mode == "delegation":
                try:
                    await _delegation_tick(c, _framec_mf, _overview_login, cycle, fh)
                except Exception as _de:
                    log(f"DELEG | tick error (non-fatal): {_de}", fh)
                if (cycle % 10) == 0:
                    log("SUPPLY | " + await check_supply(c), fh)
                _si = max(0.0, args.cycle_interval - (time.time() - t0))
                if _si > 0:
                    await asyncio.sleep(_si)
                continue
            # ── §FG-7 dedicated GÖDEL FORGE mode: one generation per cycle, nothing else ──
            if args.mode == "forge":
                await _forge_tick(c, fh)
                if (cycle % 10) == 0:
                    log("SUPPLY | " + await check_supply(c), fh)
                _si = max(0.0, args.cycle_interval - (time.time() - t0))
                if _si > 0:
                    await asyncio.sleep(_si)
                continue
            # ── §2026-07-19 DESK MODEL — periodic delegation tick folded into a live MARKET run so
            # one continuous process exercises market + spawn + the full delegation lifecycle + audit.
            if SPAWN_SUBAGENTS and args.mode == "market" and (cycle % _DELEG_TICK_EVERY) == 0:
                try:
                    await _delegation_tick(c, _framec_mf, _overview_login, cycle, fh)
                except Exception as _de:
                    log(f"DELEG | market-tick error (non-fatal): {_de}", fh)
            # §FG-7 — a GÖDEL FORGE generation folds into the live market run periodically, so one
            # continuous process also proves spawn→commit→quorum-eval→adopt end to end.
            if args.mode == "market" and (cycle % _FORGE_TICK_EVERY) == 0:
                await _forge_tick(c, fh)
            # §PASSPORTSELL — promote confirmed fills into holdings (≥20s cadence).
            if _FILLTRACK and _pp_pending and (time.time() - _last_fillpoll) >= 20.0:
                _last_fillpoll = time.time()
                try:
                    await _poll_passport_fills(c, fh)
                except Exception as _ppe:
                    log(f"PASSPORTSELL | fill-poll error (non-fatal): {_ppe!r}", fh)

            # ── Registry-health backpressure (every health_ping_sec, not every cycle) ──
            # Slow BEFORE saturating a registry: if any of the 3 mainframes is
            # unresponsive (hard brake) or consistently slow >health_latency_ms (back
            # off), cut concurrency and hold via cooldown until it recovers.
            if _dyn and (time.time() - _last_health) >= args.health_ping_sec:
                _last_health = time.time()
                async def _ping(_port):
                    _p0 = time.time()
                    try:
                        _r = await c.get(f"http://localhost:{_port}/health",
                                         timeout=max(6.0, args.health_latency_ms / 1000.0 + 3.0))
                        return (_r.status_code == 200, (time.time() - _p0) * 1000.0)
                    except Exception:
                        return (False, (time.time() - _p0) * 1000.0)
                _hres = await asyncio.gather(*[_ping(p) for (_n, p) in _health_ports])
                _dead = [_health_ports[i][0] for i, (ok, ms) in enumerate(_hres) if not ok]
                _slow = [f"{_health_ports[i][0]}={ms:.0f}ms" for i, (ok, ms) in enumerate(_hres) if ok and ms > args.health_latency_ms]
                _hsum = " ".join(f"{_health_ports[i][0]}={'DEAD' if not ok else str(int(ms)) + 'ms'}" for i, (ok, ms) in enumerate(_hres))
                if _dead or _slow:
                    _health_bad_streak += 1
                    if _health_bad_streak >= args.health_consec:
                        if _dead:
                            _dyn_n = args.min_concurrency
                            _dyn_cooldown = max(args.cooldown * 3, int(args.health_ping_sec * 2))
                            log(f"HEALTH | BRAKE — unresponsive: {','.join(_dead)} | {_hsum} | conc->{_dyn_n}", fh)
                        else:
                            _dyn_n = max(args.min_concurrency, int(_dyn_n * args.aimd_down))
                            _dyn_cooldown = max(_dyn_cooldown, int(args.health_ping_sec))
                            log(f"HEALTH | DOWN — slow >{args.health_latency_ms}ms: {','.join(_slow)} | {_hsum} | conc->{_dyn_n}", fh)
                    else:
                        log(f"HEALTH | warn {_health_bad_streak}/{args.health_consec} | {_hsum}", fh)
                else:
                    _health_bad_streak = 0
                    log(f"HEALTH | ok | {_hsum}", fh)   # heartbeat: proves the 3-registry ping is live
            # ── Settlement-backlog backpressure (dynamic, --max-backlog) ──
            # Never outrun the settlement worker: poll each venue's pending_settlement and
            # HOLD all new order creation while any venue is over the cap; resume under 0.8x
            # (hysteresis). The worker keeps draining while we hold, so the backlog oscillates
            # around the cap instead of running away (the I-X4 over-SLO class). 0 = disabled.
            if _dyn and args.max_backlog > 0 and args.mode == "market" \
                    and (time.time() - _last_backlog_poll) >= args.backlog_poll_sec:
                _last_backlog_poll = time.time()
                _backlog_pending, _bk_per = await backlog_max(c, _overview_login)
                # If EVERY venue read errored, _bk_per is empty -> say so LOUDLY (never mask a
                # failed read as 0 pending; that silent-0 was the bug this gate had to fix).
                _bk_sum = " ".join(f"{n}={v}" for n, v in _bk_per.items()) or "(no venue reads — gate inert)"
                if _backlog_hold and _backlog_pending < int(args.max_backlog * 0.8):
                    _backlog_hold = False
                    log(f"BACKLOG | RESUME — max pending {_backlog_pending} < {int(args.max_backlog*0.8)} | {_bk_sum}", fh)
                elif not _backlog_hold and _backlog_pending > args.max_backlog:
                    _backlog_hold = True
                    log(f"BACKLOG | HOLD — max pending {_backlog_pending} > cap {args.max_backlog}; pausing new orders to let settlement drain | {_bk_sum}", fh)
                else:
                    log(f"BACKLOG | ok — max pending {_backlog_pending} (cap {args.max_backlog}) | {_bk_sum}", fh)   # heartbeat: proves the venue read is live
            if _dyn and _backlog_hold:
                await asyncio.sleep(max(1, args.backlog_poll_sec // 2))   # drain window; create nothing this cycle
                continue
            # Dynamic: per-cycle route count + in-flight cap come from the controller.
            _cycle_pairs = _dyn_n if _dyn else args.pairs
            _cycle_conc = _dyn_n if _dyn else args.concurrency
            # §2026-06-17 FX managed-float driver — load targets (live re-read) + refresh spot
            _fx_targets, _fx_band, _fx_bias = _load_fx_targets()
            # §AGORASIM-2 (2026-09-22): drive only currencies a frame of THIS network trades. scripts/fx_targets.json
            # names the legacy triangle's JDAY and BVT; on another network (the sandbox's SBXA/SBXB) the driver steered
            # nothing, logged a line every cycle and polled http://localhost:8000 (registry-a) for its rates.
            if _fx_targets:
                _fx_here = {str(v).upper() for v in FRAME_CURRENCY.values()}
                _fx_absent = tuple(sorted(k for k in _fx_targets if k not in _fx_here))
                if _fx_absent:
                    _fx_targets = {k: v for k, v in _fx_targets.items() if k in _fx_here}
                    if _fx_absent not in _fx_absent_logged:
                        _fx_absent_logged.add(_fx_absent)
                        log(f"FX-DRIVE | off for {', '.join(_fx_absent)}: no frame of this network trades them"
                            + ("" if _fx_targets else "; nothing left to drive"), fh)
            # §2026-06-18 DEMAND DIRECTOR — LIVE DB flag, controlled from the sim panel's
            # director card. Polled each cycle: the endpoint returns {} when the flag is OFF
            # (the default) → neutral two-sided market; the JSON fallback also respects
            # enabled:false. No CLI flag — toggle it live from the UI, no relaunch.
            _director = await _refresh_director_http(c)
            if _director is None:                              # endpoint unreachable
                _director = _load_director()                   # bind-mounted agora_director.json (OFF by default)
            if _director:
                log("DIRECTOR | " + " ".join(f"{k}:{'UP' if v['dir']>0 else 'DOWN' if v['dir']<0 else 'flat'}@{v['strength']:.2f}" for k, v in _director.items()), fh)
            if _fx_targets:
                await _refresh_fx_rates()
                log("FX-DRIVE | " + " ".join(f"{k} {_fx_spot.get(k,0):.4f}->{v}" for k, v in _fx_targets.items())
                    + f" | band=+/-{_fx_band:.0%} bias={_fx_bias:.2f}", fh)
            if args.mode == "market":
                await _refresh_venues()
                # §SIMFEDTICKER — fill in whatever the per-registry read could not see.
                # Logged the first time and then only when it changes, so a silent
                # zero cannot be mistaken for "there was nothing to add".
                _fv, _fa = await _refresh_federation_ticker()
                if _fa or cycle <= 1:
                    _tot = sum(len(v) for v in _venue_cache.values())
                    _po = sorted(_passport_only_venues)
                    log(f"FEDTICKER | {_fv} venues matched, +{_fa} listings merged — "
                        f"universe now {_tot} listings across {len(_venue_cache)} venues"
                        + (f" | passport-only (no sim agent): {','.join(_po)}" if _po else "")
                        + (" | passport targets: ALL venues" if _PASSPORT_ALL_VENUES
                           else " | passport targets: mainframes only"), fh)
                if ARB_ENABLED:                       # §T7 rebuild the cross-venue parity map (arbitrageur reference) from the prices just refreshed
                    _xref.clear(); _xref.update(_build_xref(_venue_cache))
                if not _venue_cache:
                    log("MKT | no venue with trading listings reachable — idle cycle", fh)
                elif (cycle % MICRO_OB_EVERY) == 1:   # §T2 throttled top-of-book DEPTH read (mainframe venues only)
                    await _refresh_orderbooks()
            settled = failed = 0
            rejected = 0  # benign VENUE GUARDRAIL rejections (HTTP 429 open-order cap + HTTP 422 price-band) — the venue working as designed, NOT a sim/system failure. Reported as "rej" (not "fail"), and excluded from the AIMD error rate so they can't false-trip the circuit-breaker. With cancel-replace below these should be ~0; this is honest accounting for any residual.
            local = cross_reg = cross_frame = 0
            fees = 0.0
            _micro = {}   # §T2 per-symbol order-flow THIS cycle: SYM -> {ord,buy,sell,fill,rej} (written by _do_market; read-only side-channel)

            # Collect pairs first — mode-aware (2026-05-03)
            # mixed: original 60/25/15 split (local/cross-reg/cross-frame)
            # local-only: 100% local, isolates the /teg/transfer fast path
            # cross-only: 50/50 cross-reg/cross-frame, exercises new async branch only
            # cross-frame-only: 100% cross-frame, validates async cross-frame path in isolation
            pairs = []
            for _ in range(_cycle_pairs):
                s = r = None; ttype = None

                if args.mode == "local-only":
                    regs = [k for k, v in by_reg.items() if len(v) >= 2]
                    if regs:
                        reg = random.choice(regs)
                        s, r = random.sample(by_reg[reg], 2); ttype = "local"

                elif args.mode == "cross-frame-only":
                    s, r = _pick_xframe(by_frame, fx_only=False)
                    if s and r: ttype = "cross_frame"

                elif args.mode == "fx":
                    # §framec-sim — 100% op<->op cross-CURRENCY over the FX rail. §2026-06-14:
                    # any distinct-currency pair across the A(AVT)/B(JDAY)/C(BVT) triangle.
                    s, r = _pick_fx(by_frame)
                    if s and r: ttype = "cross_frame"

                elif args.mode == "market" and _XREG_ONLY and _xreg_senders:
                    # §XREGMODE — 100% FOREIGN-FEDERATED: every fire is a cross-registry PASSPORT
                    # order placed BY a spawned execution-clerk (sender homed on a spawn-enabled
                    # mainframe). _do_passport forces the target venue foreign (tv != sender home),
                    # so the whole order-flow rides the delegation/subagent-spawn cross-registry path.
                    s = r = random.choice(_xreg_senders); ttype = "passport"

                elif args.mode == "market":
                    # §V0064 AGORA — venue order-flow: one agent per fire places a
                    # band-aware limit order around an EigenTrust-anchored fundamental
                    # (in-engine sibling of the market-pulse daemon).
                    # PASSPORT relays (--passport-share): a foreign-homed agent buys on
                    # the frame-c (BVT) venue via its HOME registry (DevCard + FX rail).
                    pp = [a for k in PASSPORT_HOMES for a in by_reg.get(k, [])]
                    if pp and any(v in _venue_cache for v in MAINFRAMES) and random.random() < args.passport_share:
                        s = r = random.choice(pp)
                        ttype = "passport"
                    else:
                        # §V0073 anti-skew: local-market venue pick is WEIGHTED (not uniform).
                        # §2026-06-14 (JDAY): venues are 1-per-currency (A=AVT/B=JDAY/C=BVT) so
                        # the old 2-AVT-venue skew is gone; 'currency' now mainly folds the
                        # passport→BVT surplus out of C's local share.
                        venues = [k for k in _venue_cache if by_reg.get(k)]
                        if venues:
                            _vk = tuple(sorted(venues))
                            if _lw_cache["key"] != _vk:
                                _lw_cache["key"] = _vk
                                _lw_cache["w"] = _compute_local_weights(venues, args.venue_balance, args.passport_share)
                                log("VENUE-BALANCE | mode=" + args.venue_balance + f" passport={args.passport_share:.2f} local_weights=" +
                                    ", ".join(f"{v}={_lw_cache['w'].get(v, 0):.2f}" for v in _vk), fh)
                            reg = _weighted_choice(venues, _lw_cache["w"])
                            s = r = random.choice(by_reg[reg])
                            ttype = "market"

                elif args.mode == "cross-only":
                    # Roll 50/50 cross-reg vs cross-frame; both exercise async branch
                    if random.random() < 0.5:
                        _frames = list(by_frame.keys())
                        for frame in random.sample(_frames, min(2, len(_frames))):
                            fa = by_frame.get(frame, [])
                            if len(fa) >= 2:
                                for _ in range(20):
                                    s, r = random.sample(fa, 2)
                                    if s.registry != r.registry: break
                                if s and s.registry != r.registry: ttype = "cross_reg"; break
                                else: s = r = None
                    if not s:
                        s, r = _pick_xframe(by_frame, fx_only=False)
                        if s and r: ttype = "cross_frame"

                else:  # mixed (legacy default)
                    roll = random.random()
                    if roll < 0.60:
                        regs = [k for k, v in by_reg.items() if len(v) >= 2]
                        if regs:
                            reg = random.choice(regs)
                            s, r = random.sample(by_reg[reg], 2); ttype = "local"
                    if not s and roll < 0.85:
                        _frames = list(by_frame.keys())
                        for frame in random.sample(_frames, min(2, len(_frames))):
                            fa = by_frame.get(frame, [])
                            if len(fa) >= 2:
                                for _ in range(20):
                                    s, r = random.sample(fa, 2)
                                    if s.registry != r.registry: break
                                if s and s.registry != r.registry: ttype = "cross_reg"; break
                                else: s = r = None
                    if not s:
                        s, r = _pick_xframe(by_frame, fx_only=False)
                        if s and r: ttype = "cross_frame"

                if not s or not r:
                    log(f"SKIP | mode={args.mode} no eligible pair (need 2+ funded agents)", fh); break
                # §2026-06-17 FX managed-float: bias the swap DIRECTION to mean-revert the rate
                # toward target (receiver's ccy appreciates). Only FX (cross-currency) legs.
                if ttype == "cross_frame" and _fx_targets and _is_fx(s, r):
                    s, r = _apply_fx_bias(s, r, _fx_targets, _fx_band, _fx_bias)
                pairs.append((s, r, round(random.uniform(TRANSFER_MIN, TRANSFER_MAX), 2), ttype))

            # Execute transfers in parallel with bounded concurrency (CLI-tunable;
            # dynamic mode drives this from the AIMD controller's current level).
            _tx_sem = asyncio.Semaphore(_cycle_conc)
            # 2026-05-03 AAA+ instrumentation: per-transfer sender latency captured
            # for each result so per-mode P50/P95/P99 are derivable from cycle data
            # (mixed-mode previously hid cross-frame async signal under local-tx noise).
            locked_count = 0
            settled_status_count = 0

            async def _do_market(s, amount):
                """§2026-06-18 ZERO-CANCEL two-sided market — LIMIT orders only.
                One limit order per fire, side ~50/50, priced with a small symmetric
                jitter around `last` and clamped inside the venue band: some land
                CROSSING the resting book (fill now) and some REST as standing liquidity.
                Limit orders never cancel (only market orders do — we send none), so the
                book stays two-sided and orders end filled/partial/open/expired, never
                `cancelled`. A seller with no shares IPO-seeds inventory (bootstraps the
                ask side). No cancel-replace, no 429 self-heal: at MAX_RESTING quotes we
                SKIP (place nothing) — resting orders clear by FILLING or TTL expiry."""
                async with _tx_sem:
                    t0 = time.monotonic()
                    try:
                        ls = _venue_cache.get(s.registry) or []
                        if not ls:
                            return ("fail", s, s, 0.0, "market", "no venue listings", 0.0)
                        li = random.choice(ls)
                        jwt = await get_jwt(c, s)
                        # §2026-07-19b DESK MODEL, CLUSTER-WIDE — route EVERY parent's orders through
                        # its execution-clerk sub-agent (spawned on the parent's OWN registry): under
                        # frame-c enforce the clerk's base-only JWT clears /exchange/orders
                        # (exchange.trade) ONLY by presenting X-Capability-Token (birth token ∩ parent
                        # authority) — suspend the parent → the clerk dies; where rbac is dark the
                        # token rides audit-only. Spawn-dark/failed path: _cap stays {}, s trades directly.
                        _cap = {}; _route_clk = None
                        if SPAWN_SUBAGENTS and s.did in _CLERK_DIDS:
                            _clk = await _get_or_spawn_clerk(c, s, _overview_login, fh)
                            if _clk and _clk.get("jwt") and _clk.get("token"):
                                jwt = _clk["jwt"]; _cap = {"X-Capability-Token": _clk["token"]}
                                if not _CLERK_ANCHORED:
                                    await _ensure_clerk_solvent(c, s, _clk, fh)   # top up working ccy (TTL-gated)
                                    _route_clk = _clk
                                # §XREGMODE anchored: walletless clerk → leave _route_clk None so
                                # affordability reads the PARENT's balance (the §SPAWN-ANCHOR purse);
                                # the anchor-wired /exchange/orders leg debits the parent.
                        # §2026-07-20 affordability reads the ACTUAL funding wallet: the CLERK when
                        # routed (thin, tracked here), else the parent's s.balance (millions → never
                        # the binding constraint). Doomed buys become clean skips, not mover-400s.
                        def _wallet():
                            return _route_clk.get("bal", float(_CLERK_SEED_AMT)) if _route_clk is not None else s.balance
                        def _debit(_n):
                            if _route_clk is not None:
                                _route_clk["bal"] = max(0.0, _route_clk.get("bal", float(_CLERK_SEED_AMT)) - _n)
                        def _credit(_n):
                            if _route_clk is not None:
                                _route_clk["bal"] = _route_clk.get("bal", 0.0) + _n
                        def _buy_qty(_px, _q):   # clamp buy size to what the wallet funds (+ the clerk's CONFIRMED token cap)
                            _budget = min(_wallet(), _clerk_cap(_route_clk)) if _route_clk is not None else _wallet()
                            if _budget < _px * 1.02:
                                return 0
                            return max(1, min(_q, int(_budget / (_px * 1.02))))
                        stats = li.get("stats") or {}
                        last = float(stats.get("last") or li.get("ipo_price") or 1.0)
                        band = float(li.get("band_pct") or 25) / 100.0
                        # Clamp to 80% of the band so a cycle-stale `last` doesn't push the
                        # price outside the venue's ±band re-check at order time (benign 422).
                        lo, hi = last * (1.0 - band * 0.8), last * (1.0 + band * 0.8)
                        # §2026-06-20 MEAN-REVERSION toward a stable fundamental `fair`
                        # (= ipo × EQ_ANCHOR_MULT). The old code was a driftless multiplicative
                        # random walk on `last` with a band relative to `last` → no restoring
                        # force → `last` wandered unboundedly (FLUX hit 87,000× IPO, also crashed
                        # to ~96× and re-exploded). `_rev` < 0 when last is ABOVE fair (push down),
                        # > 0 when below (push up); capped to [-1, 1].
                        _ipo = float(li.get("ipo_price") or 1.0)
                        # ── §2026-06-28 T4 MARKET-MAKER two-sided inventory-skewed quote ──────────
                        # Posts a tight bid+ask around the (inventory-shifted) mid. Δ-safe: ≤2
                        # band+abs-clamped LIMIT orders via the SAME /exchange/orders endpoint;
                        # MAX_RESTING bounds the footprint; the ask leg never exceeds real holdings;
                        # returns ONE aggregated result (per-leg counts still feed the _micro side-
                        # channel). noise/momentum/mean_reversion/fundamental skip this entirely.
                        if getattr(s, "archetype", "noise") == "market_maker":
                            _ok_key = (s.did, li["symbol"])
                            _held = [(oid, ts) for (oid, ts) in _open_orders.get(_ok_key, [])
                                     if (t0 - ts) < (ORDER_TTL + 60)]
                            _open_orders[_ok_key] = _held
                            if MAX_RESTING - len(_held) <= 0:   # §AGORASIM-2: a finished order's slot is free
                                _held = await _prune_finished(_ok_key, s.port, {"Authorization": f"Bearer {jwt}", **_cap}, li["symbol"])
                            _slots = MAX_RESTING - len(_held)
                            if _slots <= 0:
                                return ("rej", s, s, 0.0, "market",
                                        f"${li['symbol']} MM at resting cap ({MAX_RESTING}) — skip",
                                        (time.monotonic() - t0) * 1000.0)
                            # mid from top-of-book (free in the listings stats), else `last`
                            _bb = stats.get("best_bid"); _ba = stats.get("best_ask")
                            try: _bb = float(_bb) if _bb is not None else None
                            except (TypeError, ValueError): _bb = None
                            try: _ba = float(_ba) if _ba is not None else None
                            except (TypeError, ValueError): _ba = None
                            _mid = ((_bb + _ba) / 2.0) if (_bb and _ba and _bb > 0 and _ba > 0) else last
                            if not _mid or _mid <= 0:
                                _mid = last if last > 0 else _ipo
                            # real free inventory (skew signal + ask-clamp) — SAME source as the sell path
                            _free = 0
                            try:
                                _pf = await c.get(
                                    f"http://localhost:{s.port}{AGORA}/portfolio",
                                    headers={"Authorization": f"Bearer {jwt}"})
                                if _pf.status_code == 200:
                                    for _p in (_pf.json() or {}).get("positions", []):
                                        if _p.get("symbol") == li["symbol"]:
                                            _free = max(0, int(_p.get("qty", 0)) - int(_p.get("locked_qty", 0)))
                                            break
                            except Exception:
                                _free = 0
                            # inventory skew in [-1,1]: long(free>target)→+ → reservation price DOWN
                            # (lean sell); short(free<target)→- → UP (lean buy). Avellaneda-Stoikov-lite.
                            _inv = max(-1.0, min(1.0, (_free - MM_TARGET_INV) / float(MM_TARGET_INV)))
                            _hs = _mid * (MM_HALF_SPREAD_MIN + random.random() * (MM_HALF_SPREAD_MAX - MM_HALF_SPREAD_MIN))
                            _resv = _mid + (-_inv * MM_INV_SKEW * _mid)     # inventory-shifted reservation price
                            _plo = max(lo, _ipo * EQ_ABS_FLOOR_MULT)        # venue ±band ∩ absolute breaker
                            _phi = min(hi, _ipo * EQ_ABS_CEIL_MULT)
                            _bid_px = max(0.01, round(min(_phi, max(_plo, _resv - _hs)), 2))
                            _ask_px = max(0.01, round(min(_phi, max(_plo, _resv + _hs)), 2))
                            if _bid_px >= _ask_px:   # band window narrower than the spread at an extreme → never self-cross
                                return ("rej", s, s, 0.0, "market",
                                        f"${li['symbol']} MM band too tight — skip", (time.monotonic() - t0) * 1000.0)
                            _mmq = max(1, min(MM_QTY_CAP, int(round(random.lognormvariate(MM_QTY_MU, MM_QTY_SIGMA)))))
                            _legs = []   # (side, qty, price) — respect MAX_RESTING slots; ask only from real holdings
                            if _slots >= 2:
                                _legs.append(("buy", _mmq, _bid_px))
                                if _free >= 1:
                                    _legs.append(("sell", min(_mmq, _free), _ask_px))
                            else:        # exactly 1 free slot → post the inventory-reducing side
                                if _inv > 0 and _free >= 1:
                                    _legs.append(("sell", min(_mmq, _free), _ask_px))
                                else:
                                    _legs.append(("buy", _mmq, _bid_px))
                            _placed = 0; _notional = 0.0; _msgs = []
                            for _mside, _mqty, _mpx in _legs:
                                if _mqty < 1:
                                    continue
                                if _mside == "buy":          # §2026-07-20 fund the bid from the real wallet or skip (no doomed b!400)
                                    _mqty = _buy_qty(_mpx, _mqty)
                                    if _mqty < 1:
                                        _msgs.append("b~lowfloat"); continue
                                try:
                                    _body = {"listing": li["symbol"], "side": _mside, "order_type": "limit",
                                             "qty": _mqty, "price": f"{_mpx:.2f}", "ttl_seconds": ORDER_TTL,
                                             "client_order_id": f"sim-mm-{cycle}-{int(time.time()*1000) % 10**9}-{random.randrange(16**4):04x}"}
                                    _resp = await c.post(
                                        f"http://localhost:{s.port}{AGORA}/orders", json=_body,
                                        headers={"Authorization": f"Bearer {jwt}", **_cap})
                                    _mm = _micro.setdefault(li["symbol"].upper(), {"ord": 0, "buy": 0, "sell": 0, "fill": 0, "rej": 0})
                                    if _resp.status_code == 200:
                                        _rj = _resp.json() or {}
                                        _st = _rj.get("status", "open")
                                        if _st in ("open", "partially_filled") and _rj.get("order_id"):
                                            _open_orders.setdefault(_ok_key, []).append((_rj["order_id"], t0))
                                        _mm["ord"] += 1; _mm[_mside] = _mm.get(_mside, 0) + 1
                                        if _st in ("filled", "partial"):
                                            _mm["fill"] += 1
                                        if _mside == "buy": _debit(_mpx * _mqty)   # clerk float ↓ on buy, ↑ on sell (recirculate)
                                        else: _credit(_mpx * _mqty)
                                        _placed += 1; _notional += _mpx * _mqty
                                        _msgs.append(f"{_mside[0]}{_mqty}@{_mpx:.2f}/{_st}")
                                    else:
                                        _mm["rej"] += 1
                                        _msgs.append(f"{_mside[0]}!{_resp.status_code}")
                                except Exception:
                                    _msgs.append(f"{_mside[0]}!err")
                            _el = (time.monotonic() - t0) * 1000.0
                            if _placed:
                                return ("ok", s, s, _notional, "market",
                                        f"${li['symbol']} MM {' '.join(_msgs)} inv={_free}", _el)
                            return ("rej", s, s, 0.0, "market",
                                    f"${li['symbol']} MM all-rej {' '.join(_msgs)}", _el)
                        fair = _ipo * EQ_ANCHOR_MULT
                        _rev = 0.0
                        if EQ_REVERT_THETA > 0 and last > 0 and fair > 0:
                            _rev = max(-1.0, min(1.0, EQ_REVERT_THETA * math.log(fair / last)))
                        # Side: reversion tilts buy/sell toward closing the gap; the demand
                        # director (when ON) adds on top.
                        _dcfg = _director.get((li.get("symbol") or "").upper()) if _director else None
                        # §2026-06-25 v2 director enrichments (E1 volume / E2 volatility / E3 regime).
                        # Backward-compatible: absent fields → 0/0/"calm" → byte-identical to v1.
                        _dint = max(0.0, min(1.0, float(_dcfg.get("intensity", 0.0)))) if _dcfg else 0.0
                        _dvol = max(0.0, min(1.0, float(_dcfg.get("volatility", 0.0)))) if _dcfg else 0.0
                        _dreg = (_dcfg.get("regime", "calm") if _dcfg else "calm")
                        bias_buy = 0.5 + _rev * 0.35
                        if _dcfg and _dcfg["dir"] != 0:
                            bias_buy += _dcfg["dir"] * _dcfg["strength"] * 0.45
                        # ── §2026-06-28 T6 DIFFERENTIAL ARCHETYPE REGIME RESPONSE (bounded) ──
                        # The campaign-director regime no longer only widens the side clamp uniformly
                        # (E3, below): it AMPLIFIES specific archetypes so a campaign yields richer,
                        # archetype-differentiated dynamics. euphoria → MOMENTUM chases the trend
                        # HARDER; panic → MEAN_REVERSION dip-buys HARDER + NOISE CAPITULATES (herd-
                        # sells). Gains scale with the director's per-symbol strength and are BOUNDED
                        # (strength∈[0,1] → ≤1.6× / ≤0.15 tilt); the E3 side-clamp + venue band + abs
                        # breaker still bind below. calm ⇒ gains neutral (1.0 / 0.0) → byte-identical.
                        _rstr = _dcfg["strength"] if _dcfg else 0.0   # regime strength (set only when a director cfg exists → _dreg != "calm")
                        _mom_gain = _mr_gain = 1.0
                        _noise_panic = 0.0
                        if _dreg == "euphoria":
                            _mom_gain = 1.0 + 0.6 * _rstr             # momentum chases the trend harder
                        elif _dreg == "panic":
                            _mr_gain = 1.0 + 0.6 * _rstr              # mean-reversion dip-buys harder
                            _noise_panic = 0.15 * _rstr              # noise capitulation: herd sell-tilt
                        # ── §2026-06-28 T1 PER-AGENT ARCHETYPE nudge (heterogeneous policies) ──
                        # Shift bias_buy (side) + accrue a price drift addend (_arch_drift, folded
                        # into `drift` below) BEFORE the regime clamp + band + absolute breaker
                        # re-bound everything. `noise` is untouched in calm → byte-identical to the
                        # pre-archetype behavior. Pure side/price math: same endpoint, no new money
                        # path, every clamp/cap retained → Δ=0 by construction. §T6 scales the
                        # momentum/mean_reversion gains (×1.0 in calm = identity) and adds a noise
                        # panic sell-tilt (0.0 in calm = no change).
                        _arch = getattr(s, "archetype", "noise")
                        _arch_drift = 0.0
                        if _arch != "noise":
                            _hist = _price_hist.get((li.get("symbol") or "").upper())
                            if _arch == "momentum":            # chase the trend: buy when last > rolling mean (§T6 euphoria amplifies)
                                if _hist and len(_hist) >= 3:
                                    _sma = sum(_hist) / len(_hist)
                                    if _sma > 0:
                                        _mom = max(-1.0, min(1.0, (last - _sma) / _sma))
                                        bias_buy += 0.30 * _mom * _mom_gain
                                        _arch_drift += 0.25 * band * _mom * _mom_gain
                            elif _arch == "mean_reversion":    # fade the gap to fair (archetype-scoped; §T6 panic amplifies the dip-buy)
                                _sgn = 1.0 if fair > last else (-1.0 if fair < last else 0.0)
                                bias_buy += 0.40 * _sgn * _mr_gain
                                _arch_drift += 0.40 * band * _sgn * _mr_gain
                            elif _arch == "fundamental":       # private fair value (heterogeneous belief) → buy below / sell above
                                _pv = fair * getattr(s, "fair_mult", 1.0)
                                if _pv > 0 and last > 0:
                                    _gap = max(-1.0, min(1.0, math.log(_pv / last)))
                                    bias_buy = 0.5 + 0.45 * _gap
                                    _arch_drift += 0.45 * band * _gap
                            elif _arch == "arbitrageur" and ARB_ENABLED:   # §T7 trade toward cross-venue/anchor parity ONLY on a gap > round-trip fees+ε (else == noise: no spurious flow)
                                _ag = _arb_gap(li.get("symbol"), li)
                                if _ag is not None and abs(_ag) > ARB_GAP_MIN:
                                    _astr = min(1.0, 0.25 + (abs(_ag) - ARB_GAP_MIN) / (ARB_GAP_MIN * 3.0))  # ramp 0.25→1.0 as the gap widens past threshold
                                    if _ag > 0:                # RICH vs parity → lean SELL (sell-from-holdings clamp still binds downstream)
                                        bias_buy = 0.5 - 0.45 * _astr
                                        _arch_drift += -0.45 * band * _astr
                                    else:                      # CHEAP vs parity → lean BUY
                                        bias_buy = 0.5 + 0.45 * _astr
                                        _arch_drift += 0.45 * band * _astr
                        elif _noise_panic > 0.0:               # §T6 noise CAPITULATION in panic (herd-sell tilt; 0.0 in calm → byte-identical)
                            bias_buy -= _noise_panic
                        _bf, _bc = 0.05, 0.95     # E3 regime: panic floods asks (sells), euphoria floods bids
                        if _dreg == "panic":      _bf = 0.01
                        elif _dreg == "euphoria": _bc = 0.99
                        bias_buy = max(_bf, min(_bc, bias_buy))
                        side = "buy" if random.random() < bias_buy else "sell"
                        # Price: symmetric jitter (E2 widens it) + a reversion nudge toward fair (+ director
                        # when ON), inside the venue ±band. Δ-safe — still settles through the exref
                        # escrow mover (no new money). The abs clamp + breaker below stay the hard floor.
                        _vm = _vol_mult((li.get("symbol") or "").upper())   # §T5 endogenous vol-clustering multiplier (mean≈1, clamped [0.5,2]); EXACTLY 1.0 at cold start → byte-identical
                        _jw = band * (0.8 + _dvol * 1.5) * _vm   # E2 volatility (VOL_GAIN=1.5) × §T5 clustering state (redistributes amplitude; mean jitter ≈ baseline)
                        drift = random.uniform(-_jw, _jw) + _rev * band * 0.6 + _arch_drift   # §T1 + per-archetype price nudge (noise → +0.0, byte-identical)
                        if _dcfg and _dcfg["dir"] != 0:
                            drift += _dcfg["dir"] * band * 0.5 * _dcfg["strength"]
                        price = min(hi, max(lo, last * (1.0 + drift)))
                        # ABSOLUTE circuit-breaker around the fundamental — price can NEVER wander
                        # past [ipo×FLOOR, ipo×CEIL] (what the old last-relative band lacked). Stay
                        # venue-tradeable: if `last` is still far outside, pull to the nearest
                        # in-band edge so the order still fills and walks `last` toward fair.
                        _abs_lo, _abs_hi = _ipo * EQ_ABS_FLOOR_MULT, _ipo * EQ_ABS_CEIL_MULT
                        if price > _abs_hi:
                            price = max(lo, _abs_hi)
                        elif price < _abs_lo:
                            price = min(hi, _abs_lo)
                        price = max(0.01, round(price, 2))
                        # §2026-06-28 T3 heavy-tailed size: lognormal (many small, few large) replacing
                        # the old uniform int(amount/4). Clipped to the SAME [1, QTY_CAP=12] cap (never
                        # exceeded). Δ-irrelevant (size only); server MAX_ORDER_NOTIONAL + abs price clamp
                        # + sell-from-holdings below stay the backstop. `amount` is no longer the size driver.
                        qty = max(1, min(QTY_CAP, int(round(random.lognormvariate(QTY_LOGN_MU, QTY_LOGN_SIGMA)))))
                        if _dint > 0:   # E1 volume: scale order size with intensity (Q_GAIN=3, cap 40; sells still clamp to real holdings below)
                            qty = max(1, min(40, int(round(qty * (1.0 + _dint * 3.0)))))
                        _ok_key = (s.did, li["symbol"])
                        # Resting-footprint cap — SKIP (never cancel) when at the cap. Prune
                        # locally-tracked ids older than the TTL window first so a filled/expired
                        # quote doesn't wrongly hold a slot.
                        _held = [(oid, ts) for (oid, ts) in _open_orders.get(_ok_key, [])
                                 if (t0 - ts) < (ORDER_TTL + 60)]
                        _open_orders[_ok_key] = _held
                        if len(_held) >= MAX_RESTING:   # §AGORASIM-2: a finished order's slot is free
                            _held = await _prune_finished(_ok_key, s.port, {"Authorization": f"Bearer {jwt}", **_cap}, li["symbol"])
                        if len(_held) >= MAX_RESTING:
                            return ("rej", s, s, 0.0, "market",
                                    f"${li['symbol']} at resting cap ({MAX_RESTING}) — skip",
                                    (time.monotonic() - t0) * 1000.0)
                        # §#83 SELL FROM REAL HOLDINGS — a sell must come from the agent's ACTUAL
                        # on-chain position (free = qty − locked_qty); that is what supplies the ask
                        # side once IPO float is exhausted. The old path fired a doomed sell then
                        # IPO-seeded as a crutch — and that crutch SILENTLY failed when float ran
                        # out → no asks → buy-only freeze (BSEA/EAST/QCC). Now: hold shares → sell
                        # real inventory; hold none + float left → bootstrap ONE IPO-seed; hold none
                        # + float gone → skip (don't fire a doomed sell that masks the gap).
                        if side == "sell":
                            _free = 0
                            try:
                                _pf = await c.get(
                                    f"http://localhost:{s.port}{AGORA}/portfolio",
                                    headers={"Authorization": f"Bearer {jwt}"})
                                if _pf.status_code == 200:
                                    for _p in (_pf.json() or {}).get("positions", []):
                                        if _p.get("symbol") == li["symbol"]:
                                            _free = max(0, int(_p.get("qty", 0)) - int(_p.get("locked_qty", 0)))
                                            break
                            except Exception:
                                _free = 0
                            if _free > 0:
                                qty = min(qty, _free)          # sell REAL inventory
                            elif stats.get("ipo_remaining", 0) > 0:
                                try:
                                    ipo = await c.post(
                                        f"http://localhost:{s.port}{AGORA}/listings/{li['symbol']}/{LAUNCH_BUY}",
                                        json={"qty": max(qty, 5)}, headers={"Authorization": f"Bearer {jwt}", **_cap})
                                    el = (time.monotonic() - t0) * 1000.0
                                    if ipo.status_code == 200:
                                        return ("ok", s, s, float(li.get("ipo_price") or 0) * max(qty, 5),
                                                "market", f"${li['symbol']} ipo_seed×{max(qty, 5)}", el)
                                    return ("rej", s, s, 0.0, "market",
                                            f"sell-seed HTTP {ipo.status_code}", (time.monotonic() - t0) * 1000.0)
                                except Exception as e:
                                    return ("fail", s, s, 0.0, "market", e, (time.monotonic() - t0) * 1000.0)
                            else:
                                return ("rej", s, s, 0.0, "market",
                                        f"${li['symbol']} sell skip — no holdings, float exhausted",
                                        (time.monotonic() - t0) * 1000.0)
                        if side == "buy":   # §2026-07-20 size/skip the buy against the REAL funding wallet (clerk when routed)
                            qty = _buy_qty(price, qty)
                            if qty < 1:
                                return ("rej", s, s, 0.0, "market",
                                        f"${li['symbol']} buy skip — float low ({_wallet():.0f})",
                                        (time.monotonic() - t0) * 1000.0)
                        body = {"listing": li["symbol"], "side": side, "order_type": "limit",
                                "qty": qty, "price": f"{price:.2f}", "ttl_seconds": ORDER_TTL,
                                "client_order_id": f"sim-mkt-{cycle}-{int(time.time()*1000) % 10**9}-{random.randrange(16**4):04x}"}
                        resp = await c.post(
                            f"http://localhost:{s.port}{AGORA}/orders", json=body,
                            headers={"Authorization": f"Bearer {jwt}", **_cap})
                        el = (time.monotonic() - t0) * 1000.0
                        if resp.status_code == 200:
                            _rj = resp.json() or {}
                            st = _rj.get("status", "open")
                            if st in ("open", "partially_filled") and _rj.get("order_id"):
                                _open_orders.setdefault(_ok_key, []).append((_rj["order_id"], t0))  # now resting
                            _mm = _micro.setdefault(li["symbol"].upper(), {"ord": 0, "buy": 0, "sell": 0, "fill": 0, "rej": 0})  # §T2 read-only order-flow telemetry
                            _mm["ord"] += 1; _mm[side] = _mm.get(side, 0) + 1
                            if st in ("filled", "partial"): _mm["fill"] += 1   # API status: filled (full) / partial (partial fill)
                            if side == "buy": _debit(price * qty)   # clerk float recirculates: ↓ buy, ↑ sell
                            else: _credit(price * qty)
                            return ("ok", s, s, price * qty, "market", f"${li['symbol']} {side}×{qty}@{price:.2f}/{st}", el)
                        # Benign rejection (band 422 / cap 429) — NEVER cancel, never fail-loud.
                        _micro.setdefault(li["symbol"].upper(), {"ord": 0, "buy": 0, "sell": 0, "fill": 0, "rej": 0})["rej"] += 1  # §T2
                        return ("rej", s, s, 0.0, "market", f"HTTP {resp.status_code}: {resp.text[:60]}", el)
                    except Exception as e:
                        return ("fail", s, s, 0.0, "market", e, (time.monotonic() - t0) * 1000.0)

            async def _do_passport(s, amount):
                """§V0064 P2 — foreign agent trades on a mainframe venue via its HOME
                registry's passport relay (DevCard push). BUY funds the venue gateway
                (cross-frame FX). §2026-06-20 SELL (bidirectional) sells shares the agent
                already holds → proceeds repatriate home automatically (reverse FX via the
                gateway-credit rail) so cash RECIRCULATES instead of one-way draining."""
                async with _tx_sem:
                    t0 = time.monotonic()
                    try:
                        _held = _passport_holdings.get(s.did) or {}
                        # §PASSPORTSELL restart-proof seed (parent identity only): first fire
                        # after a (re)start seeds _held from the venue's ACTUAL free positions.
                        # Failure degrades silently to the empty-tracker behavior.
                        if _FILLTRACK and not (SPAWN_SUBAGENTS and s.did in _CLERK_DIDS):
                            for _sv in [v for v in MAINFRAMES if _venue_cache.get(v)]:
                                if (s.did, _sv) in _pp_rebuilt:
                                    continue
                                _pp_rebuilt.add((s.did, _sv))
                                try:
                                    _pj0 = await get_jwt(c, s)
                                    _pr0 = await c.get(
                                        f"http://localhost:{s.port}{AGORA}/passport/portfolio",
                                        params={"venue_registry": _venue_wire_name(_sv)},   # §AGORASIM-2: the wire name
                                        headers={"Authorization": f"Bearer {_pj0}"}, timeout=20)
                                    if _pr0.status_code == 200:
                                        for _pos in (_pr0.json() or {}).get("positions", []):
                                            _fq = int(_pos.get("free") or 0)
                                            if _fq > 0:
                                                _kk = (_sv, str(_pos.get("symbol")))
                                                _held[_kk] = max(int(_held.get(_kk, 0)), _fq)
                                        _passport_holdings[s.did] = _held
                                except Exception:
                                    pass
                        # ── §2026-06-28 T7 cross-FRAME arbitrage leg (passport) ──────────────
                        # An arbitrageur acts on a foreign venue ONLY on a real gap vs cross-
                        # venue/anchor parity: SELL a HELD position gone RICH, else BUY the
                        # CHEAPEST listing below parity; no opportunity → skip cleanly (adds NO
                        # random passport flow). Same /exchange/passport/orders path + clamps.
                        _arb_chose = False
                        if ARB_ENABLED and not _XREG_ONLY and getattr(s, "archetype", "noise") == "arbitrageur":
                            _pick = None   # (side, tv, sym, li, hqty)
                            for (_tv2, _sym2), _hq in list(_held.items()):   # 1) sell a HELD position gone RICH
                                _li2 = next((x for x in (_venue_cache.get(_tv2) or []) if x.get("symbol") == _sym2), None)
                                if _li2 is None or _hq < 1:
                                    continue
                                _g2 = _arb_gap(_sym2, _li2)
                                if _g2 is not None and _g2 > ARB_GAP_MIN_XFRAME:
                                    _pick = ("sell", _tv2, _sym2, _li2, int(_hq)); break
                            if _pick is None:                                # 2) else BUY the cheapest below-parity listing
                                # §SIMFEDTICKER — the target set was MAINFRAMES only, so every
                                # symbol listed on an op received zero foreign flow and a venue
                                # with no sim agent (qatest16) was never traded by anything.
                                # SIM_PASSPORT_ALL_VENUES=0 restores the mainframe-only shape.
                                _pool2 = (list(_venue_cache.keys()) if _PASSPORT_ALL_VENUES
                                          else list(MAINFRAMES))
                                # §AGORASIM-2: a passport order is foreign by definition, in every mode (see below)
                                _tvs2 = [v for v in _pool2 if _venue_cache.get(v)
                                         and v != s.registry and _passport_reachable(s.registry, v)] if PASSPORT_DIVERSIFY \
                                    else ([_DELEG_MF] if _venue_cache.get(_DELEG_MF) else [])
                                _best = None
                                for _tv2 in _tvs2:
                                    for _x in (_venue_cache.get(_tv2) or []):
                                        _g2 = _arb_gap((_x.get("symbol") or "").upper(), _x)
                                        if _g2 is not None and _g2 < -ARB_GAP_MIN_XFRAME and (_best is None or _g2 < _best[0]):
                                            _best = (_g2, _tv2, _x)
                                if _best is not None:
                                    _pick = ("buy", _best[1], _best[2].get("symbol"), _best[2], 0)
                            if _pick is None:
                                return ("rej", s, s, 0.0, "passport", "no arb gap — skip", (time.monotonic() - t0) * 1000.0)
                            _do_sell = (_pick[0] == "sell"); tv, sym, li, hqty = _pick[1], _pick[2], _pick[3], _pick[4]
                            _arb_chose = True
                        else:
                            # SELL a held position sometimes (recoup cash); else BUY. Sell only
                            # when we actually track a holding + its venue listing is cached.
                            # §XREGMODE: force BUY-only under xreg-only — a passport buy returns
                            # 'funding' (async limit order that may not fill), so local _held over-
                            # counts and a later sell 409s 'insufficient free shares'. Foreign buys
                            # are the clean 100%-foreign path; working foreign sells need real fill
                            # tracking (separate refinement).
                            # §PASSPORTSELL: with real fill-tracking the xreg-only sell clamp
                            # lifts — holdings are CONFIRMED fills now, so sells cannot 409
                            # from optimistic over-count. FILLTRACK=0 restores the clamp.
                            _do_sell = bool(_held) and (_FILLTRACK or not _XREG_ONLY) and random.random() < PASSPORT_SELL_SHARE
                            hqty = 0
                            if _do_sell:
                                (tv, sym), hqty = random.choice(list(_held.items()))
                                li = next((x for x in (_venue_cache.get(tv) or []) if x.get("symbol") == sym), None)
                                if li is None or hqty < 1:
                                    _do_sell = False
                        if not _do_sell and not _arb_chose:
                            # §2026-06-15 DIVERSIFY: pick a venue across A/B/C so foreign
                            # DevCards land on every venue.
                            # §SIMFEDTICKER — this is the GENERAL passport target (the arb
                            # branch above has its own list). MAINFRAMES-only here is why an
                            # op-listed symbol got no foreign flow and qatest16, where the sim
                            # holds no agent, was never traded by anything at all.
                            _pool = (list(_venue_cache.keys()) if _PASSPORT_ALL_VENUES
                                     else list(MAINFRAMES))
                            # §AGORASIM-2 (2026-09-22): the sender's OWN venue is excluded in every mode, not only
                            # under SIM_XREG_ONLY: a relay to its own registry answers 502 "no ACTIVE peer registry
                            # '<itself>'" (measured on the sandbox pair's first frame-sim market run, 3 of 16 fires).
                            _tvs = [v for v in _pool if _venue_cache.get(v)
                                    and v != s.registry and _passport_reachable(s.registry, v)] if PASSPORT_DIVERSIFY \
                                else ([_DELEG_MF] if _venue_cache.get(_DELEG_MF) else [])
                            if not _tvs:
                                return ("fail", s, s, 0.0, "passport", "no venue listings", 0.0)
                            tv = random.choice(_tvs)
                            ls = _venue_cache.get(tv) or []
                            li = random.choice(ls)
                        last = float((li.get("stats") or {}).get("last") or li.get("ipo_price") or 1.0)
                        jwt = await get_jwt(c, s)
                        # §2026-07-19b CLUSTER-WIDE DESK — op/foreign parents' PASSPORT trades also
                        # route through their execution clerk (spawned on the parent's OWN registry;
                        # the home relay sees the clerk + its X-Capability-Token, audit-only where dark).
                        _cap = {}; _clk = None
                        if SPAWN_SUBAGENTS and s.did in _CLERK_DIDS:
                            _clk = await _get_or_spawn_clerk(c, s, _overview_login, fh)
                            if _clk and _clk.get("jwt") and _clk.get("token"):
                                jwt = _clk["jwt"]; _cap = {"X-Capability-Token": _clk["token"]}
                                if not _CLERK_ANCHORED:
                                    await _ensure_clerk_solvent(c, s, _clk, fh)   # top up working ccy (TTL-gated)
                        if _do_sell:
                            sym = li["symbol"]
                            qty = max(1, min(int(hqty), random.randint(1, 4)))
                            # 2026-06-23 BALANCE FIX: clamp the passport ask to the same absolute band.
                            _ipo_p = float(li.get("ipo_price") or 1.0)
                            price = min(last * random.uniform(0.94, 1.01), _ipo_p * EQ_ABS_CEIL_MULT)
                            price = max(_ipo_p * EQ_ABS_FLOOR_MULT, price)
                            price = max(0.01, round(price, 2))  # crossable ask - band-clamped
                            resp = await c.post(
                                f"http://localhost:{s.port}{AGORA}/passport/orders",
                                json={"venue_registry": _venue_wire_name(tv), "listing": sym, "side": "sell",
                                      "qty": qty, "price": f"{price:.2f}", "fx_buffer_pct": 4},
                                headers={"Authorization": f"Bearer {jwt}", **_cap}, timeout=60)
                            el = (time.monotonic() - t0) * 1000.0
                            if resp.status_code == 200:
                                _nh = max(0, int(hqty) - qty)
                                if _nh:
                                    _held[(tv, sym)] = _nh
                                else:
                                    _held.pop((tv, sym), None)
                                _passport_holdings[s.did] = _held
                                if _FILLTRACK:
                                    # decremented at ACCEPT (prevents over-sell); the poller
                                    # re-credits whatever a terminal sell left UNFILLED.
                                    try:
                                        _soid = (resp.json() or {}).get("order_id")
                                    except Exception:
                                        _soid = None
                                    if _soid:
                                        _pp_pending.setdefault(s.did, []).append(
                                            {"s": s, "venue": tv, "sym": sym, "oid": str(_soid),
                                             "qty": qty, "side": "sell", "ts": time.time(),
                                             "clerk": bool(_cap)})
                                return ("ok", s, s, price * qty, "passport",
                                        f"${sym} relay SELL×{qty}@{price:.2f} (repat home)", el)
                            return _passport_failure(resp, s, el)
                        # BUY — §2026-06-20(B) size to what the agent can AFFORD in home ccy
                        # (qty*price *FX *(1+buffer) + fee; ~1.3x upper bound). Skip cleanly if broke.
                        # 2026-06-23 BALANCE FIX: passport buys now obey the SAME absolute ceiling +
                        # demand-director as _do_market. Previously neither, so each bid was priced off
                        # the rising last with no cap -> unbounded ratchet (the BSEA->2441 runaway).
                        # ipo*CEIL hard-caps the bid; a DOWN director (dir<0) shaves it, so the director
                        # can balance passport flow too instead of being bypassed entirely.
                        _ipo_p = float(li.get("ipo_price") or 1.0)
                        _dcfg = _director.get((li.get("symbol") or "").upper()) if _director else None
                        _dshave = (_dcfg["dir"] * _dcfg["strength"] * 0.08) if (_dcfg and _dcfg.get("dir")) else 0.0
                        price = last * random.uniform(0.99, 1.08) * max(0.80, 1.0 + _dshave)
                        price = min(price, _ipo_p * EQ_ABS_CEIL_MULT)
                        price = max(_ipo_p * EQ_ABS_FLOOR_MULT, price)
                        price = max(0.01, round(price, 2))  # crossable bid - director-aware, band-clamped
                        # §2026-07-20 affordability reads the CLERK's home-ccy wallet when routed
                        # (spawn mode funds the cross-frame buy from the clerk, not the parent) — was
                        # checking s.balance (parent, millions) → guard passed while the clerk was
                        # broke → mover 402 'passport funding: insufficient balance'. Now a clean skip.
                        _pw = (_clk.get("bal", float(_CLERK_SEED_AMT)) if (_cap and _clk and not _CLERK_ANCHORED) else s.balance)
                        _afford = int(_pw / (price * 1.3)) if price > 0 else 0
                        if _afford < 1:
                            return ("rej", s, s, 0.0, "passport",
                                    "insufficient clerk float — skip" if (_cap and _clk) else "insufficient local balance — skip",
                                    (time.monotonic() - t0) * 1000.0)
                        qty = max(1, min(5, int(amount / 10), _afford))
                        if _cap and _clk:
                            _mq = int(_clerk_cap(_clk) / (price * 1.3))   # keep notional under the clerk's CONFIRMED token cap
                            if _mq < 1:                                   # even 1 share exceeds the cap → skip clean (no cap-deny)
                                return ("rej", s, s, 0.0, "passport",
                                        f"${li['symbol']} px>clerk-cap — skip", (time.monotonic() - t0) * 1000.0)
                            qty = max(1, min(qty, _mq))
                        resp = await c.post(
                            f"http://localhost:{s.port}{AGORA}/passport/orders",
                            json={"venue_registry": _venue_wire_name(tv), "listing": li["symbol"], "side": "buy",
                                  "qty": qty, "price": f"{price:.2f}", "fx_buffer_pct": 4},
                            headers={"Authorization": f"Bearer {jwt}", **_cap}, timeout=60)
                        el = (time.monotonic() - t0) * 1000.0
                        if resp.status_code == 200:
                            _k = (tv, li["symbol"])
                            if _FILLTRACK:
                                # §PASSPORTSELL: acceptance is NOT a fill — record PENDING;
                                # the poller credits the CONFIRMED filled qty (or counts a
                                # stale never-landed funding deposit honestly).
                                try:
                                    _boid = (resp.json() or {}).get("order_id")
                                except Exception:
                                    _boid = None
                                if _boid:
                                    _pp_pending.setdefault(s.did, []).append(
                                        {"s": s, "venue": tv, "sym": li["symbol"], "oid": str(_boid),
                                         "qty": qty, "side": "buy", "ts": time.time(),
                                         "clerk": bool(_cap)})
                            else:
                                _held[_k] = int(_held.get(_k, 0)) + qty
                                _passport_holdings[s.did] = _held
                            if _cap and _clk:   # clerk home-ccy spent to fund the cross-frame buy
                                _clk["bal"] = max(0.0, _clk.get("bal", 0.0) - price * qty)
                            return ("ok", s, s, price * qty, "passport",
                                    f"${li['symbol']} relay buy×{qty}@{price:.2f} →{tv}", el)
                        return _passport_failure(resp, s, el)
                    except Exception as e:
                        return ("fail", s, s, 0.0, "passport", e, (time.monotonic() - t0) * 1000.0)

            async def _do_tx(s, r, amount, ttype):
                if ttype == "market":
                    return await _do_market(s, amount)
                if ttype == "passport":
                    return await _do_passport(s, amount)
                async with _tx_sem:
                    t_tx0 = time.monotonic()
                    try:
                        jwt = await get_jwt(c, s)
                        if args.raw:
                            # Direct transfer — skip A2A payment flow.
                            # Local (sender == receiver registry): /teg/transfer
                            # Cross (different registry): /cross-registry-transfer
                            if s.registry == r.registry:
                                resp = await c.post(f"http://localhost:{s.port}/api/v1/teg/transfer",
                                    json={"receiver_agent_id": r.did, "amount": str(amount), "message": "sim-raw"},
                                    headers={"Authorization": f"Bearer {jwt}"})
                            else:
                                # Phase 10 (2026-05-04): backend selection per-fire.
                                # mixed → random across {async, 2pc}; intra forced
                                # to local-only upstream so won't hit this branch.
                                if _is_fx(s, r):
                                    # Cross-CURRENCY leg → MUST use the async FX rail
                                    # (cross-registry-transfer?backend=async auto-detects
                                    # the currency mismatch and swaps via reserves). 2pc
                                    # has no FX path. §framec-sim.
                                    backend = "async"
                                elif args.backend_mode == "mixed":
                                    backend = random.choice(["async", "2pc"])
                                elif args.backend_mode in ("async", "2pc"):
                                    backend = args.backend_mode
                                else:
                                    backend = "async"  # safe default for unknown modes
                                resp = await c.post(
                                    f"http://localhost:{s.port}/api/v1/teg/cross-registry-transfer?backend={backend}",
                                    json={"receiver_did": r.did, "amount": str(amount), "message": f"sim-raw-{backend}"},
                                    headers={"Authorization": f"Bearer {jwt}"})
                            elapsed_ms = (time.monotonic() - t_tx0) * 1000.0
                            if resp.status_code == 200:
                                # Detect async backend's "locked" status — receiver
                                # credit is eventually-consistent via reactor; sim
                                # must NOT optimistically credit receiver's local
                                # balance under that branch.
                                try:
                                    body = resp.json()
                                except Exception:
                                    body = {}
                                tx_status = body.get("status", "completed")
                                return ("ok", s, r, amount, ttype, tx_status, elapsed_ms)
                            return ("fail", s, r, amount, ttype, f"HTTP {resp.status_code}", elapsed_ms)
                        else:
                            # A2A payment flow
                            token = await clients[s.port].get_token(jwt, r.did, str(amount), ttl_seconds=A2A_TTL)
                            result = await clients[s.port].settle(jwt, token, task_id=f"sim-{cycle}-{int(time.time())}")
                            elapsed_ms = (time.monotonic() - t_tx0) * 1000.0
                            if result.get("status") in ("settled", "SETTLED", "settling", "SETTLING"):
                                return ("ok", s, r, amount, ttype, result.get("status", "settled"), elapsed_ms)
                            return ("fail", s, r, amount, ttype, f"non-settled status: {result.get('status')}", elapsed_ms)
                    except Exception as e:
                        elapsed_ms = (time.monotonic() - t_tx0) * 1000.0
                        return ("fail", s, r, amount, ttype, e, elapsed_ms)

            # ── §2026-06-28 T8 STOCHASTIC INTER-ARRIVAL (Poisson + Hawkes), default OFF ──────
            # When HAWKES_ENABLED, stagger the task LAUNCHES across a bounded budget with
            # exponential inter-arrival gaps + Hawkes self-excitation (each arrival shortens the
            # next gap → bursts then quiet). The gaps are NORMALISED to sum to the budget, so the
            # per-cycle order COUNT and mean rate are UNCHANGED (timing-only) and the spread is
            # bounded ≤ budget; _tx_sem still caps concurrency and spreading LOWERS peak in-flight.
            # `_spread_used` is later deducted from the daemon sleep so the cadence (mean rate) is
            # preserved. Disabled ⇒ the original single-gather, byte-identical.
            _spread_used = 0.0
            if HAWKES_ENABLED and pairs:
                _budget = min(ARRIVAL_SPREAD_MAX_S,
                              max(0.0, ARRIVAL_SPREAD_FRAC * float(args.cycle_interval if args.daemon
                                                                   else ARRIVAL_SPREAD_MAX_S * 2)))
                _gaps = []; _exc = 0.0
                for _ in pairs:
                    _gaps.append(random.expovariate(1.0) / (1.0 + _exc))   # excited → shorter gap (cluster)
                    _exc = _exc * HAWKES_DECAY + HAWKES_EXCITE             # each arrival excites the next
                _gt = sum(_gaps) or 1.0
                _gaps = [g * _budget / _gt for g in _gaps]                 # normalise → total spread == budget (mean rate preserved)
                _t_launch = time.monotonic(); _tasks = []
                for _pr, _gap in zip(pairs, _gaps):
                    if _gap > 0:
                        await asyncio.sleep(_gap)
                    _tasks.append(asyncio.create_task(_do_tx(*_pr)))
                results = await asyncio.gather(*_tasks, return_exceptions=True)
                _spread_used = time.monotonic() - _t_launch
            else:
                results = await asyncio.gather(*[_do_tx(s, r, a, t) for s, r, a, t in pairs], return_exceptions=True)

            # 2026-05-03 AAA+ per-mode latency tracking
            # §market-AIMD-fix (2026-06-13): market/passport buckets added so the
            # AIMD controller gets a real settle signal for venue order-flow (was 0).
            lat_by_type = {"local": [], "cross_reg": [], "cross_frame": [], "market": [], "passport": []}
            lat_ok_all = []
            lat_fail_all = []

            for res in results:
                if isinstance(res, Exception):
                    failed += 1; continue
                # res tuple: ("ok"/"fail", s, r, amount, ttype, status_or_err, elapsed_ms)
                ttype = res[4] if len(res) > 4 else None
                elapsed_ms = res[6] if len(res) > 6 else 0.0
                if ttype in ("market", "passport"):
                    # §V0064 — venue orders are escrowed, NOT transfers: no
                    # receiver credit, no fee math; count + log + latency only.
                    if res[0] == "ok":
                        settled += 1
                        lat_ok_all.append(elapsed_ms)
                        lat_by_type[ttype].append(elapsed_ms)  # §market-AIMD-fix: bucket venue-order latency for the controller
                        if ttype == "passport":
                            # §2026-06-20(B): passport is buys-only → one-directional cash drain.
                            # Track it so the _do_passport affordability guard sees the agent deplete
                            # over the run (passport escrow doesn't otherwise touch s.balance).
                            try: res[1].balance = max(0.0, res[1].balance - float(res[3]))
                            except Exception: pass
                        log(f"MKT | {res[1].name}@{res[1].registry} | {res[5]} | notional≈{res[3]:.2f} | {elapsed_ms:.0f}ms", fh)
                    else:
                        failed += 1
                        _emsg = str(res[5]); _eml = _emsg.lower()
                        # benign = the venue/agent correctly declining (guardrails + can't-act),
                        # NOT a system failure: 429 open-order cap · 422 price-band · sell with no
                        # inventory when the IPO float is exhausted · transient empty venue cache ·
                        # §2026-06-20(A/B) INSUFFICIENT BALANCE (the agent legitimately can't afford
                        # the passport funding leg — now a clean 402, not a 5xx) · local affordability
                        # skip. Case-insensitive so "Insufficient balance" matches.
                        # §conc-fix (2026-07-20): an explicit "rej" first-element IS the
                        # placement path's own benign verdict — an MM whose quotes were all
                        # declined (price-band / venue state / order-cap), returned as
                        # ("rej", …) at line ~1791. Its SUMMARY message ("MM all-rej b!400")
                        # carries no benign keyword, so the string-match below missed it → the
                        # decline was miscounted as a hard failure and false-braked the AIMD
                        # controller EVEN WITH THE AGENT FLUSH (~2M balance). Honor the tuple's
                        # own signal first; keep the keyword match for paths that return "fail".
                        _benign = res[0] == "rej" or any(k in _eml for k in (
                            "429", "422", "band", "max 20 open", "sell+ipo", "no venue",
                            "no frame-c listings", "insufficient", "402", "skip",
                            # §2026-06-20: a market BUY the agent can't afford fails the escrow
                            # deposit ("order deposit failed: exchange mover 400: … Insufficient
                            # balance"). The sim truncates resp.text[:60] BEFORE "Insufficient
                            # balance", so match the visible prefix. Same benign can't-afford class.
                            "deposit failed", "mover 400"))
                        if _benign:                        # benign VENUE GUARDRAIL (429 open-order cap / 422 price-band): the venue working as designed, not a failure. With cancel-replace this is ~0; counted as "rej" + kept out of the breaker so it never false-brakes. A real failure (timeout/5xx/402/non-settled) is NOT benign and still counts.
                            rejected += 1
                        lat_fail_all.append(elapsed_ms)
                        _tag = "MKTREJ" if _benign else "MKTFAIL"
                        log(f"{_tag} | {res[1].name}@{res[1].registry} | {str(res[5])[:90]} | {elapsed_ms:.0f}ms", fh)
                    continue
                if res[0] == "ok":
                    s, r, amount = res[1], res[2], res[3]
                    tx_status = res[5] if len(res) > 5 else "completed"
                    settled += 1; fees += amount * 0.005
                    s.balance -= amount  # sender always deducted at lock/settle
                    if str(tx_status).lower() == "locked" or _is_fx(s, r):
                        # Async backend (receiver credited later via reactor) OR a
                        # cross-currency FX leg (receiver is credited amount*RATE in the
                        # OTHER currency — NOT 1:1). Either way, do NOT optimistically
                        # 1:1-credit the receiver's local sim balance. §framec-sim.
                        locked_count += 1
                    else:
                        # 2pc backend or local transfer: receiver credited synchronously.
                        r.balance += amount * 0.995
                        settled_status_count += 1
                    if ttype == "local": local += 1
                    elif ttype == "cross_reg": cross_reg += 1
                    else: cross_frame += 1
                    if ttype in lat_by_type:
                        lat_by_type[ttype].append(elapsed_ms)
                    lat_ok_all.append(elapsed_ms)
                    log(f"TX | {s.name}@{s.registry} → {r.name}@{r.registry} | {amount} {s.currency} | {ttype}/{tx_status} | {elapsed_ms:.0f}ms", fh)
                else:
                    s, r, amount = res[1], res[2], res[3]
                    if ttype == "local": local += 1
                    elif ttype == "cross_reg": cross_reg += 1
                    else: cross_frame += 1
                    failed += 1
                    err = res[5] if len(res) > 5 else "?"
                    lat_fail_all.append(elapsed_ms)
                    log(f"FAIL | {s.name} → {r.name} | {ttype} | {type(err).__name__}: {str(err)[:80]} | {elapsed_ms:.0f}ms", fh)

                # Remove depleted agents (on success or insufficient balance)
                _remove = False
                if res[0] == "ok":
                    s = res[1]
                    if s.balance < 100:
                        _remove = True
                elif res[0] == "fail" and len(res) > 5:
                    err_str = str(res[5])
                    if "402" in err_str or "Insufficient balance" in err_str:
                        s = res[1]
                        s.balance = 0
                        _remove = True
                if _remove:
                    for pool in [funded, by_frame.get(s.frame,[]), by_reg.get(s.registry,[])]:
                        if s in pool: pool.remove(s)

            supply = await check_supply(c)
            elapsed = time.time() - t0

            # 2026-05-03 AAA+ per-mode percentiles. Per-type latency from
            # lat_by_type lets us answer "what's cross-frame async P50 in
            # isolation" without local-tx noise polluting the number.
            def _pcts(lst):
                if not lst:
                    return None
                ls = sorted(lst)
                n = len(ls)
                p50 = ls[n // 2]
                p95 = ls[min(n - 1, int(n * 0.95))]
                p99 = ls[min(n - 1, int(n * 0.99))]
                return {"n": n, "min": ls[0], "p50": p50, "p95": p95, "p99": p99, "max": ls[-1]}

            pct_local = _pcts(lat_by_type["local"])
            pct_xreg = _pcts(lat_by_type["cross_reg"])
            pct_xframe = _pcts(lat_by_type["cross_frame"])
            pct_market = _pcts(lat_by_type["market"])  # §market-AIMD-fix: venue-order p50/p95 for the controller

            def _fmt(p, label):
                if not p:
                    return ""
                return f" {label}=p50/{p['p50']:.0f}|p95/{p['p95']:.0f}|p99/{p['p99']:.0f}ms(n={p['n']})"

            lat_tag = (_fmt(pct_local, "L") + _fmt(pct_xreg, "CR") + _fmt(pct_xframe, "CF") + _fmt(pct_market, "MKT")).strip()
            async_tag = ""
            if locked_count > 0 or settled_status_count > 0:
                async_tag = f" | locked={locked_count} sync={settled_status_count}"

            # ── Dynamic controller: measure this cycle's settle metric, embed it in
            # the CYCLE line (so /metrics can surface concurrency + settle live), then
            # AIMD-adjust _dyn_n for the next cycle. ──
            dyn_tag = ""
            _settle = 0.0
            _hardfail = max(0, failed - rejected)   # real failures = total minus benign venue-guardrail rejections (429/422)
            if _dyn:
                if args.target_metric == "avg":
                    _settle = (sum(lat_ok_all) / len(lat_ok_all)) if lat_ok_all else 0.0
                else:
                    # §market-AIMD-fix: in market mode the transfer buckets are empty,
                    # so prefer the venue-order bucket → the target_settle_ms governor
                    # finally works for market mode (was reading 0 → pinned to the cap).
                    _pf = pct_market or pct_xframe or pct_xreg or pct_local
                    _settle = float(_pf[args.target_metric]) if (_pf and args.target_metric in _pf) else 0.0
                _tot = settled + _hardfail
                _err = (_hardfail / _tot) if _tot else 0.0    # benign 429/422 excluded → breaker only reacts to REAL failures
                dyn_tag = (f" | DYN conc={_cycle_pairs} settle={int(_settle)} "
                           f"target={args.target_settle_ms} err={int(round(_err*100))} rej={rejected}")
            _rej_tag = f" {rejected}rej" if rejected else ""
            log(f"CYCLE {cycle} | {settled}ok {_hardfail}fail{_rej_tag} ({local}L {cross_reg}CR {cross_frame}CF) | fees≈{fees:.1f} | {supply} | {elapsed:.1f}s{async_tag} |{(' '+lat_tag) if lat_tag else ''}{dyn_tag}", fh)

            # ── §2026-06-28 T2 PER-SYMBOL MICROSTRUCTURE (market mode, read-only) ──────────
            # Built from prices/orderbook the sim already fetched: last, last/fair ratio,
            # realized-vol (_price_hist), spread/mid (free in the listings `stats`), throttled
            # top-of-book depth (_ob_cache), and this-cycle order-flow (_micro). Emits NO
            # orders → Δ untouched. Purely additive (a MICRO log line + a JSONL `market` block).
            _market_micro = {}
            if args.mode == "market" and _venue_cache:
                def _ff(v):
                    try: return float(v)
                    except (TypeError, ValueError): return None
                for _reg2, _ls2 in _venue_cache.items():
                    for _x in _ls2:
                        _sym = (_x.get("symbol") or "").upper()
                        if not _sym or _sym in _market_micro:
                            continue
                        _st2 = _x.get("stats") or {}
                        _last = _ff(_st2.get("last")) or _ff(_x.get("ipo_price"))
                        _ipo2 = _ff(_x.get("ipo_price")) or 0.0
                        _fairv = _ipo2 * EQ_ANCHOR_MULT if _ipo2 else 0.0
                        _bb = _ff(_st2.get("best_bid")); _ba = _ff(_st2.get("best_ask"))
                        _spread = (_ba - _bb) if (_bb is not None and _ba is not None) else None
                        _mid = ((_ba + _bb) / 2.0) if (_bb is not None and _ba is not None) else None
                        _ob = _ob_cache.get(_sym) or {}
                        _mk = _micro.get(_sym) or {}
                        _ordn = int(_mk.get("ord", 0)); _flln = int(_mk.get("fill", 0))
                        _market_micro[_sym] = {
                            "last": _last,
                            "ratio": (round(_last / _fairv, 3) if (_last and _fairv) else None),
                            "rvol": round(_rvol(_price_hist.get(_sym, ())), 4),
                            "volm": round(_vol_mult(_sym), 3),   # §T5 current vol-clustering multiplier (chartable: clusters >1 turbulent / <1 calm)
                            "mid": (round(_mid, 4) if _mid is not None else None),
                            "spread": (round(_spread, 4) if _spread is not None else None),
                            "bid_depth": _ob.get("bid_depth"), "ask_depth": _ob.get("ask_depth"),
                            "vol24": _st2.get("volume_24h_qty"),
                            "ord": _ordn, "buy": int(_mk.get("buy", 0)), "sell": int(_mk.get("sell", 0)),
                            "fill": _flln, "rej": int(_mk.get("rej", 0)),
                            "fill_ratio": (round(_flln / _ordn, 3) if _ordn else None),
                        }
                if _market_micro:
                    # "a few key symbols": busiest first (this cycle's order count), then by symbol.
                    _keys = sorted(_market_micro, key=lambda k: (-_market_micro[k]["ord"], k))[:8]
                    _segs = []
                    for k in _keys:
                        d = _market_micro[k]
                        _ls_s = f"{d['last']:.2f}" if d['last'] is not None else "-"
                        _r_s = f"{d['ratio']:.2f}x" if d['ratio'] is not None else "-"
                        _sp_s = f"{d['spread']:.2f}" if d['spread'] is not None else "-"
                        _bd_s = str(d['bid_depth']) if d['bid_depth'] is not None else "-"
                        _ad_s = str(d['ask_depth']) if d['ask_depth'] is not None else "-"
                        _fr_s = f"{d['fill_ratio']:.2f}" if d['fill_ratio'] is not None else "-"
                        _segs.append(f"{k} last={_ls_s} r={_r_s} rvol={d['rvol']*100:.1f}% vm={d['volm']:.2f} "
                                     f"sprd={_sp_s} dpth={_bd_s}/{_ad_s} "
                                     f"ord={d['ord']}({d['buy']}b/{d['sell']}s) fill={_fr_s}")
                    log("MICRO | " + " | ".join(_segs), fh)

            # ── AIMD: update concurrency for the NEXT cycle ──
            if _dyn:
                _dyn_hist.append(_settle)
                _avg = sum(_dyn_hist) / len(_dyn_hist)
                _tgt = float(args.target_settle_ms)
                _prev = _dyn_n
                # §conc-fix (2026-07-20): the AIMD error signal was NOISE-DOMINATED at low
                # concurrency. A single benign "can't-afford" market 400 in a 1-2 order cycle
                # reads as 25-50% err, tripping the breaker to the floor; and UP demanded
                # err==0 EXACTLY — so with any residual market-order rejection the loop could
                # never climb even with the box idle and settle far under target (the observed
                # "always on cooldown, conc stuck at min"). Fix: (a) a rate is only trusted
                # once the cycle did a real sample (_tot >= _err_min_n) — below that, tiny-n
                # noise can't brake; (b) a tolerance band absorbs the benign market sprinkle so
                # the loop probes up when latency has headroom. A SUSTAINED real failure
                # (> _err_tol over a real sample) still backs off; a storm (>0.40) still brakes;
                # a latency blowout (settle > 2×target) still brakes regardless of sample.
                _err_min_n = 5                                   # orders in-cycle before a rate is trustworthy
                _err_tol = 0.20                                  # benign can't-afford / transient sprinkle band
                _err_real = _err if _tot >= _err_min_n else 0.0  # tiny-sample rate = noise → ignore
                if _err_real > 0.40 or _settle > 2 * _tgt:      # circuit breaker → floor (anti-storm)
                    _dyn_n = args.min_concurrency; _dyn_cooldown = args.cooldown * 3; _act = "BRAKE"
                elif _err_real > _err_tol or _avg > _tgt:        # real breach → fast multiplicative back-off
                    _dyn_n = max(args.min_concurrency, int(_dyn_n * args.aimd_down)); _dyn_cooldown = args.cooldown; _act = "DOWN"
                elif _dyn_cooldown > 0:                          # hold a while after a back-off
                    _dyn_cooldown -= 1; _act = "COOL"
                elif _avg < 0.8 * _tgt and _err_real <= _err_tol:  # headroom + tolerable err → probe up
                    _dyn_n = min(args.max_concurrency, _dyn_n + args.aimd_up); _act = "UP"
                else:
                    _act = "HOLD"
                if _dyn_n != _prev or _act in ("COOL", "BRAKE"):
                    log(f"DYN | avg_settle={_avg:.0f}ms target={int(_tgt)}ms err={_err:.0%}(rej={rejected}) cooldown={_dyn_cooldown} "
                        f"| concurrency {_prev}->{_dyn_n} [{_act}]", fh)

            # Optional JSONL emission for downstream analysis
            if args.metrics_jsonl:
                try:
                    record = {
                        "ts": time.time(),
                        "cycle": cycle,
                        "mode": args.mode,
                        "ok": settled,
                        "fail": _hardfail,
                        "rejected": rejected,
                        "local": local,
                        "cross_reg": cross_reg,
                        "cross_frame": cross_frame,
                        "locked": locked_count,
                        "sync": settled_status_count,
                        "elapsed_s": elapsed,
                        "lat_ms": {
                            "local": pct_local,
                            "cross_reg": pct_xreg,
                            "cross_frame": pct_xframe,
                        },
                        "market": _market_micro,   # §T2 per-symbol microstructure ({} unless market mode)
                    }
                    with open(args.metrics_jsonl, "a") as mf:
                        mf.write(json.dumps(record) + "\n")
                except Exception as e:
                    log(f"metrics-jsonl write failed: {e}", fh)

            if args.daemon and cycle < args.cycles:
                # §T8 absorb the launch-stagger into the cadence → mean rate ≈ current (no-op when HAWKES off, _spread_used=0)
                _interval = max(1.0, args.cycle_interval - _spread_used) if (HAWKES_ENABLED and _spread_used > 0) else args.cycle_interval
                await asyncio.sleep(_interval)

        supply = await check_supply(c)
        log(f"SESSION END | {supply}", fh)
    fh.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--cycles", type=int, default=3)
    p.add_argument("--cycle-interval", type=int, default=60)
    p.add_argument("--pairs", type=int, default=10)
    p.add_argument("--raw", action="store_true", help="Skip A2A payment, do direct /teg/transfer")
    # 2026-05-03 AAA+ sim adaptation. Splits paths so per-mode latencies are
    # measurable in isolation (mixed-mode hides cross-frame async signal under
    # local-transfer noise).
    p.add_argument("--mode", choices=["mixed", "local-only", "cross-only", "cross-frame-only", "fx", "market", "delegation", "forge"],
                   default="mixed",
                   help="Pair-selection mode. mixed=60/25/15 local/cross-reg/cross-frame, "
                        "local-only=intra-registry only, cross-only=cross-registry+cross-frame, "
                        "cross-frame-only=cross-frame only (any 2 frames, validates async path), "
                        "fx=cross-CURRENCY only (FX legs across the A/B/C currency triangle over the async rail; §framec-sim), "
                        "market=AGORA venue order-flow (band-aware limit orders around an "
                        "EigenTrust-anchored fundamental; agents homed on a venue registry; §V0064), "
                        "delegation=IRONKEY conformance battery + audit self-check on frame-c (§2026-07-19).")
    # ── §2026-07-19 IRONKEY sim options ──────────────────────────────────────
    p.add_argument("--spawn-subagents", action="store_true",
                   help="Desk model, CLUSTER-WIDE: every funded parent (all 16 registries) spawns ONE "
                        "execution-clerk on its OWN registry that places its market+passport orders via "
                        "X-Capability-Token (birth token; load-bearing under frame-c enforce, audit-only "
                        "elsewhere). Also folds a delegation lifecycle+audit tick into market mode every "
                        "N cycles. Degrades to direct trading wherever spawn is dark. SIM_SPAWN_POOL>0 caps.")
    p.add_argument("--xreg-delegation", action="store_true",
                   help="Optional: add a cross-REGISTRY delegation leg (frame-c → doha peer) to the "
                        "delegation battery. Default OFF (does NOT require flipping any frame's flag).")
    p.add_argument("--concurrency", type=int, default=40,
                   help="Max parallel transfers per sim instance (was hardcoded 40)")
    p.add_argument("--metrics-jsonl", type=str, default=None,
                   help="If set, append one JSON line per cycle with full metrics to this path")
    # Phase 10 (2026-05-04): explicit cross-TEG backend selection. Cross-registry
    # calls get ?backend=<x> appended; intra calls (/teg/transfer) are unaffected
    # since intra/local has no cross-frame backend choice. mixed=randomize per
    # cross fire across {async, 2pc}; intra forces local-only path mode upstream.
    p.add_argument("--backend-mode", choices=["async", "2pc", "intra", "mixed"],
                   default="mixed",
                   help="Cross-TEG backend: async=SF-4 reactor, 2pc=synchronous 2-phase, "
                        "intra=local-only pairs (path mode forced upstream), "
                        "mixed=random per cross fire across {async, 2pc}.")
    # ── Dynamic auto-regulation (AIMD controller, 2026-06-06) ──────────────────
    # Hold a settle-time SLO by adjusting in-flight concurrency in a closed loop:
    # additive-increase under target, multiplicative-decrease + cooldown on breach
    # (and a circuit breaker on errors). Lets the sim self-tune to the max
    # error-free rate for sustained unattended runs as the baseline load shifts.
    p.add_argument("--dynamic", action="store_true",
                   help="Enable AIMD auto-regulation (adjust concurrency to hold --target-settle-ms)")
    p.add_argument("--target-settle-ms", type=int, default=5000,
                   help="Dynamic SLO: keep per-cycle settle (route) latency <= this (ms)")
    p.add_argument("--target-metric", choices=["p50", "p95", "avg"], default="p50",
                   help="Which per-cycle settle stat to regulate (default p50)")
    p.add_argument("--min-concurrency", type=int, default=2, help="Dynamic floor for in-flight concurrency")
    p.add_argument("--max-concurrency", type=int, default=64, help="Dynamic ceiling for in-flight concurrency")
    p.add_argument("--aimd-up", type=int, default=1, help="Additive concurrency step up when under target")
    p.add_argument("--aimd-down", type=float, default=0.7, help="Multiplicative factor on breach (e.g. 0.7)")
    p.add_argument("--cooldown", type=int, default=5, help="Ticks to hold after a back-off before probing up")
    p.add_argument("--control-window", type=int, default=4, help="Rolling window (cycles) for the settle average")
    # Registry-health backpressure (2026-06-07): in dynamic mode, ping the 3 mainframe
    # registries' /health and slow down if any is unresponsive or consistently slow.
    p.add_argument("--health-ping-sec", type=int, default=15, help="Dynamic: ping the 3 mainframe registries /health every N seconds (10-30 recommended)")
    p.add_argument("--health-latency-ms", type=int, default=3000, help="Dynamic: back off if a registry /health stays above this latency")
    p.add_argument("--health-consec", type=int, default=2, help="Dynamic: consecutive bad health pings before backing off")
    p.add_argument("--max-backlog", type=int, default=0, help="Dynamic: HOLD new order creation while any venue's settlement backlog (pending_settlement) exceeds this; resume under 0.8x (hysteresis). Keeps the sim from outrunning the settlement worker. 0=disabled (default).")
    p.add_argument("--backlog-poll-sec", type=int, default=8, help="Dynamic: poll venue settlement backlog every N seconds (only with --max-backlog)")
    # §V0073 anti-skew (market mode). §2026-06-14 (JDAY): the venue set is now SYMMETRIC —
    # 1 venue per currency (A=AVT, B=JDAY, C=BVT), so the old 2-AVT-venue skew is gone and
    # 'venue' vs 'currency' nearly converge. --venue-balance controls local-market flow split:
    #   currency = each CURRENCY gets equal aggregate flow; still folds the passport→BVT
    #              surplus out of C's local share (default) — harmless when symmetric
    #   venue    = each VENUE gets equal flow (legacy)
    p.add_argument("--venue-balance", choices=["currency", "venue"], default="currency",
                   help="market mode: balance order-flow by 'currency' (default, unskews A/B vs C) or by 'venue' (legacy uniform)")
    p.add_argument("--credentials", default=None,
                   help="§BATCH8: roster file (default scripts/sim_credentials.json — prod's; a fresh network passes its own, "
                        "together with SIM_REGISTRIES_JSON and friends)")
    p.add_argument("--passport-share", type=float, default=0.18,
                   help="market mode: fraction of fires that are PASSPORT relays (foreign-homed agent buys on the frame-c BVT venue). Folded into the currency balance. 0=off.")
    # §2026-06-18 demand-director is a LIVE DB flag toggled from the sim panel's director
    # card (polled each cycle, OFF by default) — no CLI flag; nothing in the launch path
    # passes one, so a flag here would be unreachable.
    asyncio.run(run(p.parse_args()))

if __name__ == "__main__": main()
