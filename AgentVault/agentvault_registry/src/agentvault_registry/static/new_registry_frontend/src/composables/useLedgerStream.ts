/**
 * composables/useLedgerStream.ts — §BRIDGE #B2
 *
 * ONE ledger stream for the whole app. A module-level singleton that opens at
 * most one WebSocket per frame and fans the traffic out to every consumer.
 *
 * WHY A SINGLETON. Before §BRIDGE the app opened the SAME EventStore sockets
 * from four different places (MissionControl x3, useFederationEvents,
 * command/EventTicker, landing/EventLedgerLive). Adding a fifth for the stage
 * would have been the §FANOUTFIX mistake again: N copies of one question, free
 * to disagree. There is now one asker.
 *
 * WHAT IT GUARANTEES
 *  - Exact counts. EVERY event increments the per-frame counter, including the
 *    ones the stage never draws. The ledger COUNTS, the stage SAMPLES
 *    (strategy honesty rule 2) — so the two numbers are allowed to differ, and
 *    the difference is published as `droppedForRender`, not hidden.
 *  - Coalescing. Descriptors are buffered and flushed once per animation frame,
 *    so a 900-events-per-second sim burst costs one callback per frame, not 900.
 *  - Overflow is stated, never silently swallowed.
 *  - Reconnect uses FULL JITTER, never lockstep (§JITTER). Every tab reconnects
 *    at a different moment after an EventStore restart.
 *  - Honest liveness: `lastEventAt` per frame drives the "STREAM RECONNECTING,
 *    last real event ..." banner. A dead stream must LOOK dead.
 */
import { ref, computed, onUnmounted, effectScope, type Ref, type ComputedRef } from 'vue'
import { FRAMES, esSocketUrl, type FrameDescriptor } from '@/config/frames'
import { currentFrameManifest, onFrameManifest } from '@/composables/useFrameManifest'
import { frameOf } from '@/services/frameManifest'
import { toVerb, type VerbDescriptor, type GrammarContext } from '@/services/bridge/grammar'

// ─── Tunables (strategy §8: pool cap 128; coalesce per frame) ────────────────
/** Max descriptors handed to the renderer per flush. Excess is COUNTED, not drawn. */
export const RENDER_BATCH_CAP = 48
/** §MCFOLD — the ceiling of the un-flushed queue. rAF does not run in a hidden tab, so a
 *  burst arriving while the tab is in the background used to grow `pending` without
 *  bound; now the OLDEST are dropped and COUNTED, and the freshest 4 batches survive. */
export const PENDING_CAP = RENDER_BATCH_CAP * 4
/** Reconnect backoff ceiling. */
const RECONNECT_CAP_MS = 15_000
const RECONNECT_BASE_MS = 300
/**
 * Stop retrying a socket that has NEVER opened after this many attempts. A
 * socket that DID open resets the counter, so genuine blips still recover
 * forever; only a structurally unreachable endpoint (an origin with no
 * /ws/events-c map) goes quiet instead of storming the console.
 */
const NEVER_OPENED_GIVEUP = 40

/**
 * §AGORASIM-2 (2026-09-22, his words: "add the sandbox live event ledgers as collapsed thing like the live ledger has
 * on the frontpage. so if a sim or mcp tester is running. people can watch it live") — WHICH folded strip a frame
 * belongs to. `main` is every frame the app always streamed; `sandbox` is a frame the serving registry marks
 * `"strip": "sandbox"` in FRESH_NETWORK_JSON (the test frames, where the sim and the MCP tester run). A strip's
 * sockets open only while something that shows that strip is mounted, so a folded sandbox strip costs nothing and
 * the main ledger, Mission Control and the stage never open a sandbox socket at all.
 */
export type LedgerStrip = 'main' | 'sandbox'

export interface FrameStreamState {
  key: string
  /** The strip this frame's row belongs to (§AGORASIM-2). */
  strip: LedgerStrip
  label: string
  currency: string
  accent: string
  connected: boolean
  /** Epoch ms of the last event actually received on this frame's socket. */
  lastEventAt: number | null
  /** Exact count of events seen on this socket this session. Never sampled. */
  eventCount: number
  /** True once we have stopped retrying (endpoint structurally unreachable). */
  gaveUp: boolean
}

export interface LedgerStreamApi {
  /** Per-frame liveness + exact counts, THIS handle's strip only. Reactive, read-only. */
  frames: Readonly<Ref<FrameStreamState[]>>
  /** True when at least one frame socket is open. */
  anyConnected: ComputedRef<boolean>
  /** True when every enabled frame socket is open. */
  allConnected: ComputedRef<boolean>
  /** Exact total across this strip's frames. The ledger's number. */
  totalEvents: Readonly<Ref<number>>
  /** Descriptors the renderer was NOT given because the batch was capped. */
  droppedForRender: Ref<number>
  /** Rolling events-per-second, for the "+n/s not drawn" caption. */
  eventsPerSecond: ComputedRef<number>
  /** Epoch ms of the newest event on any frame, or null if nothing ever arrived. */
  lastEventAt: ComputedRef<number | null>
  /** Subscribe to coalesced descriptor batches. Returns an unsubscribe fn. */
  onVerbs: (cb: (batch: VerbDescriptor[]) => void) => () => void
  /** Subscribe to every raw event (unsampled) for consoles that must count. */
  onRaw: (cb: (frameKey: string, inner: any) => void) => () => void
  /** Tell the grammar which DIDs are the viewer's, so `mine` is correct. */
  setMineDids: (dids: Iterable<string>) => void
  /** Registry slug that local (frame-scoped) events originate from. */
  setLocalRegistry: (frameKey: string, slug: string | null) => void
  /**
   * #B17 REPLAY — the descriptors THIS SESSION has seen, oldest first.
   *
   * Session-scoped on purpose, and that is a design answer rather than a
   * limitation I am apologising for. A websocket has no history: you receive
   * what arrives after you connect, which is exactly why the pulse bar draws
   * the minutes before you arrived as ABSENCE. Replaying a window the session
   * never observed would mean querying the ledger's past, and the only public
   * event endpoint (`/public/eventstore-recent`) is a FIFTEEN-event Redis seed
   * — enough to prime a feed, not to reconstruct an hour.
   *
   * So replay replays what was witnessed, and says so. Same rule as the pulse.
   */
  replayBuffer: () => VerbDescriptor[]
  replayWindow: () => {
    from: number | null; to: number | null; count: number; capped: boolean
    seeded: number; witnessed: number
    /** Repeat deliveries refused by identity. Counted so it can be GATED —
     *  a defect nothing counts is a defect nothing catches. */
    duplicatesDropped: number
  }
}

// ─── Singleton state ────────────────────────────────────────────────────────
interface Conn {
  key: string
  url: string
  ws: WebSocket | null
  timer: ReturnType<typeof setTimeout> | null
  attempt: number
  everOpened: boolean
  neverOpenedTries: number
  /** Set when a strip folds: the socket is closed on purpose and must never reconnect. */
  closed: boolean
}

const frames = ref<FrameStreamState[]>([])
const totalEvents = ref(0)
const droppedForRender = ref(0)
const _rateWindow: number[] = []          // epoch ms of recent events (trimmed to 5s)
const _rateTick = ref(0)                  // bumped on flush so the computed re-runs

const conns = new Map<string, Conn>()
const verbSubs = new Set<(b: VerbDescriptor[]) => void>()
const rawSubs = new Set<(f: string, e: any) => void>()
const localRegistryByFrame = new Map<string, string>()
let mineDids: Set<string> = new Set()
/* §AGORASIM-2 — per-strip consumers, each frame's strip, and a rate window per strip (the global window stays). */
const refByStrip: Record<LedgerStrip, number> = { main: 0, sandbox: 0 }
const stripOfKey = new Map<string, LedgerStrip>()
const _rateByStrip: Record<LedgerStrip, number[]> = { main: [], sandbox: [] }
/** Bumped when the runtime frame list arrives, so a view can ask "does this strip have frames?" reactively. */
const runtimeTick = ref(0)
function stripOf(f: { strip?: string } | null | undefined): LedgerStrip {
  return f?.strip === 'sandbox' ? 'sandbox' : 'main'
}

let pending: VerbDescriptor[] = []
let flushHandle: number | null = null
/* §MCFOLD — counters are EXACT per event but PUBLISHED once per flush. A reactive write per
 * event made every consumer that shows a count (the ledger's per-frame chips, the pulse
 * bar) re-render per event — 900 renders a second under a sim burst. The shadow counters
 * take the per-event cost; the reactive refs take one write per animation frame. */
const _frameCounts = new Map<string, { n: number; last: number }>()
let _total = 0
let _dropped = 0
let _countsDirty = false
function publishCounts(): void {
  if (!_countsDirty) return
  _countsDirty = false
  for (const st of frames.value) {
    const c = _frameCounts.get(st.key)
    if (!c) continue
    if (st.eventCount !== c.n) st.eventCount = c.n
    if (st.lastEventAt !== c.last) st.lastEventAt = c.last
  }
  if (totalEvents.value !== _total) totalEvents.value = _total
  if (droppedForRender.value !== _dropped) droppedForRender.value = _dropped
  _rateTick.value++
}
let started = false

/** Frames worth streaming: prod mainframes that own an EventStore.
 *
 * §COCKPITA R3 — EXPORTED, because the cockpit's pane registry needs to answer "can this
 * deployment show a live ledger at all?" and the §FANOUTFIX law says the two places must
 * ask ONE predicate, not two that agree today. The first draft of the pane asked
 * `ctx.config.caps.hasOwnEventStore`, a path that does not exist on RegistryConfig (the
 * flag lives on the FRAME SEED) — it read `undefined !== false` and was therefore a
 * predicate that could never return false. */
export function streamableFrames(strip?: LedgerStrip): FrameDescriptor[] {
  // §FEFRAME W2 (2026-10-01): the frames come from the FRAME MANIFEST (registry-config self + peers): each frame's
  // own ledger at wss://<its public host>/ws/events, own frame first (an operator console: its parent). Before W2 a
  // "cluster host" (the apex, api., registry., and any seed trust domain, so the sandbox consoles too) streamed the
  // retired A/B/C seed on /ws/events, -b and -c: the apex showed the legacy store as "Frame A" and dialled two dead
  // lanes, and EU, ASIA and every operator console streamed a nameless local socket.
  // With no manifest (a config that could not be read) the console streams its own /ws/events only.
  // The runtime frames of `/api/v1/public/fresh-network` (FRESH_NETWORK_JSON: the folded sandbox strip on EU) join,
  // deduplicated by key, by trust domain and by socket (one asker per stream, the §FANOUTFIX law).
  // §AGORASIM-2: `strip` narrows the answer to one folded strip; no argument is every frame.
  const fromManifest = manifestFrames().filter(f => f.caps?.hasOwnEventStore && (f.es?.absoluteWsUrl || f.es?.sameOriginPath))
  const base = fromManifest.length ? fromManifest : [localFrameDescriptor()]
  const out = base.slice()
  const keys = new Set(out.map(f => f.key))
  const tds = new Set(out.map(f => (f.trustDomain || '').toLowerCase()).filter(Boolean))
  const urls = new Set(out.map(f => wsUrlFor(f)))
  for (const f of runtimeFrames) {
    const u = wsUrlFor(f)
    const td = (f.trustDomain || '').toLowerCase()
    if (!f.es?.sameOriginPath || keys.has(f.key) || (td && tds.has(td)) || urls.has(u)) continue
    out.push(f); keys.add(f.key); urls.add(u); if (td) tds.add(td)
  }
  return strip ? out.filter(f => stripOf(f) === strip) : out
}

/** §AGORASIM-2 — true once the runtime list names at least one frame of this strip. Reactive (reads the tick). */
export function stripHasFrames(strip: LedgerStrip): boolean {
  void runtimeTick.value
  return streamableFrames(strip).length > 0
}

// The ES socket URL is built in ONE place (`config/frames.ts`), because it used
// to be hand-written in a dozen and three of those still named a dead port.
function wsUrlFor(f: FrameDescriptor): string {
  // The descriptor is the frame list here: a runtime frame is not in FRAMES, and a key lookup there would silently
  // fall back to `/ws/events` (the LOCAL socket) for every fresh frame.
  return esSocketUrl(f.key, [f])
}

function stateFor(key: string): FrameStreamState | undefined {
  return frames.value.find(s => s.key === key)
}

// ─── Coalescing flush ───────────────────────────────────────────────────────
function scheduleFlush(): void {
  if (flushHandle !== null) return
  const raf = (typeof requestAnimationFrame === 'function')
    ? requestAnimationFrame
    : (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 16) as unknown as number
  flushHandle = raf(flush) as unknown as number
}

function flush(): void {
  flushHandle = null
  if (!pending.length) { publishCounts(); return }
  let batch = pending
  pending = []
  if (batch.length > RENDER_BATCH_CAP) {
    // Keep the NEWEST. Under a burst the freshest truth is the useful truth,
    // and the count of what we skipped is published rather than buried.
    _dropped += batch.length - RENDER_BATCH_CAP
    _countsDirty = true
    batch = batch.slice(-RENDER_BATCH_CAP)
  }
  publishCounts()
  rememberForReplay(batch)
  for (const cb of verbSubs) {
    try { cb(batch) } catch { /* one bad consumer must not kill the stream */ }
  }
}

// ─── Socket lifecycle ───────────────────────────────────────────────────────
/**
 * #B17 — a ring of recent descriptors, so the stage can be re-played without
 * asking the server for a past it does not publish. Bounded by BOTH count and
 * age: this is a visual convenience, not a second ledger.
 */
const REPLAY_CAP = 600
const REPLAY_MAX_AGE_MS = 15 * 60_000
/**
 * Which frame is serving this app? The seed comes from THIS registry, so its
 * events belong to the local frame. Derived from the origin against the same
 * FRAME_SEED trust domains the rest of the app uses; an origin we do not
 * recognise falls back to the first frame, which is where such an origin is.
 */
let _hostOverride: string | null = null
/** §FEFRAME W2 test seam: the manifest frames (null = the live FRAMES the manifest filled). */
let _framesOverride: FrameDescriptor[] | null = null
/** The frame manifest's frames, own frame first (empty until the manifest lands). */
function manifestFrames(): FrameDescriptor[] { return _framesOverride ?? FRAMES }
function currentHost(): string {
  if (_hostOverride !== null) return _hostOverride
  try { return (window.location.hostname || '').toLowerCase() } catch { return '' }
}
/** The console's own socket when no manifest could be read: `/ws/events` on this origin, labelled by the host. */
export function localFrameDescriptor(host: string = currentHost()): FrameDescriptor {
  const name = (host.split('.')[0] || 'local')
  return {
    key: 'local', label: name.toUpperCase(), shortLabel: name.slice(0, 2).toUpperCase(),
    trustDomain: host, currency: '', tier: 'unknown', env: 'prod', isSandbox: false,
    accent: 'var(--nc-primary, #00e0c6)',
    es: { sameOriginPath: '/ws/events' },
    caps: { hasOwnEventStore: true },
    source: 'topology', status: 'live',
  }
}
/** The key of the frame serving this app (its events are the local ones): the manifest's own frame, else 'local'. */
function localFrameHint(): string {
  const m = currentFrameManifest()
  return (m && frameOf(m, m.self)?.key) || 'local'
}

/**
 * RUNTIME FRAMES — the frames this registry names in `/api/v1/public/fresh-network` (`FRESH_NETWORK_JSON`
 * on the serving registry). Each entry with a `ws_path` becomes a streamable descriptor; the seed no
 * longer needs an entry per fresh frame, and a frame added to the JSON streams with no FE change.
 */
let runtimeFrames: FrameDescriptor[] = []
let runtimeLoad: Promise<void> | null = null
export function runtimeFrameFromNetworkEntry(e: any): FrameDescriptor | null {
  const ws = String(e?.ws_path || '').trim()
  const slug = String(e?.slug || '').trim()
  if (!slug || !ws.startsWith('/')) return null
  const group = String(e?.group || 'sandbox').toLowerCase()
  const sandbox = group === 'sandbox'
  let host = slug
  try { host = new URL(String(e?.registry_url || e?.console || '')).hostname || slug } catch { /* no url in the entry */ }
  return {
    key: slug, label: String(e?.name || slug), shortLabel: slug.slice(0, 2).toUpperCase(),
    trustDomain: host, currency: String(e?.currency || ''),
    tier: sandbox ? 'sandbox' : 'sovereign-mainframe', env: sandbox ? 'sandbox' : 'prod', isSandbox: sandbox,
    accent: `var(--frame-${slug.replace(/[^a-z0-9-]/gi, '')}, #7dd3fc)`,
    es: { sameOriginPath: ws, statsPath: '/api/v1/public/fresh-network' },
    caps: { hasOwnEventStore: true, mintable: false, fxEnabled: true },
    source: 'topology', status: e?.reachable === false ? 'unreachable' : 'live',
    // §AGORASIM-2: the registry files a frame under a folded strip; anything but "sandbox" is the main ledger.
    strip: String(e?.strip || '').toLowerCase() === 'sandbox' ? 'sandbox' : 'main',
  }
}
async function fetchRuntimeFrames(): Promise<FrameDescriptor[]> {
  try {
    const res = await fetch(`${window.location.origin}/api/v1/public/fresh-network`, { cache: 'no-store' })
    if (!res.ok) return []
    const body = await res.json()
    const rows: any[] = Array.isArray(body?.frames) ? body.frames : (Array.isArray(body) ? body : [])
    return rows.map(runtimeFrameFromNetworkEntry).filter((f): f is FrameDescriptor => f !== null)
  } catch {
    return []
  }
}
function ensureRuntimeFrames(): Promise<void> {
  if (!runtimeLoad) runtimeLoad = fetchRuntimeFrames().then(list => { runtimeFrames = list; runtimeTick.value++ })
  return runtimeLoad
}

let replayRing: VerbDescriptor[] = []
let replayCapped = false
let replaySeeded = 0
let duplicatesDropped = 0
let seedDone = false

/**
 * At-least-once delivery is a property of this wire, so identity is the client's job.
 *
 * MEASURED 2026-08-19 on the PUBLIC socket (`/ws/events-c`, 45s): 64 messages
 * carrying 42 unique event ids — 22 events delivered TWICE. The cause is upstream
 * and known: the EventStore broadcasts once at accept time (`routers/events.py`
 * 202-branch) and again after its Kafka consumer stores the same event
 * (`services/kafka_consumer.py`), so every event ingested over its HTTP route
 * while KAFKA_ENABLED=true arrives twice.
 *
 * A client that counts the same event id twice is simply wrong, whatever the
 * reason — so this is not a workaround for the upstream duplicate, it is the
 * correct reading of an at-least-once stream. Fixing the double PUBLISH is a
 * separate decision (it changes what every websocket client on the fleet
 * receives) and is deliberately not made here.
 *
 * ONE gate for BOTH paths — live and seed — because the seed of one frame and
 * the live socket of that same frame overlap by design, and replay must not show
 * the same event twice from the two of them. Bounded: ids only, FIFO, capped.
 */
const SEEN_CAP = 4000
const _seenIds = new Set<string>()
const _seenOrder: string[] = []

function eventIdOf(envelope: any): string | null {
  const ev = envelope?.event ?? envelope
  const id = ev?.id ?? ev?.event_id
  return typeof id === 'string' && id ? id : null
}

/** True the FIRST time this event id is seen; false on every repeat. */
function firstSightOfEvent(envelope: any): boolean {
  const id = eventIdOf(envelope)
  if (!id) return true          // no id to judge by: never silently drop it
  if (_seenIds.has(id)) return false
  _seenIds.add(id)
  _seenOrder.push(id)
  if (_seenOrder.length > SEEN_CAP) {
    const gone = _seenOrder.splice(0, _seenOrder.length - SEEN_CAP)
    for (const g of gone) _seenIds.delete(g)
  }
  return true
}


/**
 * §BRIDGE R7 — prime the replay ring from the registry's own recent-events seed.
 *
 * `/public/eventstore-recent` is a bounded ring the REGISTRY maintains centrally
 * (one Redis list, written once per emitted event, read by every client), so
 * this costs the EventStore nothing no matter how many browsers are open. It is
 * this registry's own events only — no foreign EventStore is touched.
 *
 * It feeds the REPLAY buffer and NOTHING ELSE. Deliberately:
 *  - `totalEvents` keeps meaning "events this session saw on the wire". A seed
 *    is not something we saw arrive.
 *  - the PULSE BAR never sees it. Its entire rule is that minutes before you
 *    arrived are drawn as ABSENCE, and a seed does not turn absence into
 *    observation.
 *  - the LIVE LEDGER stays live. A console that mixes seeded rows with witnessed
 *    ones, without saying which is which, is exactly the kind of quiet lie this
 *    build refuses.
 * The replay caption states the split, so what is seeded is always visible AS
 * seeded.
 */
/**
 * WHERE THE FOREIGN SEEDS LIVE — DISCOVERED, NEVER HARDCODED.
 *
 * 🔴 NOTE FOR WHOEVER MOVES THIS OFF THIS MACHINE (Commander's instruction,
 * 2026-08-19): the addresses below are resolved AT RUNTIME from
 * `/api/v1/public/topology`, which returns `publicUrl` + `trust_domain` per
 * registry. Nothing here assumes `api.theprotocol.cloud` or any other host. If
 * a frame moves, is renamed, or a fourth appears, this picks it up with no code
 * change — and if topology is unreachable we seed the LOCAL frame only rather
 * than guessing an address.
 *
 * The longer-term shape he asked me to record: this should ultimately follow the
 * frames a viewer is actually TRANSACTING with rather than every mainframe on
 * the map, discovered the same way. That is a policy decision he has reserved;
 * the discovery mechanism it needs is already the one used here.
 */
async function discoverSeedSources(): Promise<Array<{ frame: string; base: string }>> {
  // §FEFRAME W2: the manifest names every frame and its public origin; a peer frame answers only once its derived
  // CORS admits this console (a frame that does not simply contributes nothing).
  const local = { frame: localFrameHint(), base: window.location.origin }
  const m = currentFrameManifest()
  const out: Array<{ frame: string; base: string }> = [local]
  if (!m) return out
  const seen = new Set([local.frame])
  for (const e of [m.self, ...m.peers]) {
    if (e.role !== 'frame' || seen.has(e.key) || !e.public_url) continue
    seen.add(e.key)
    out.push({ frame: e.key, base: e.public_url.replace(/\/+$/, '') })
  }
  return out
}

/**
 * Seed replay from EVERY frame the app already streams live from.
 *
 * This is not a new exposure and it is worth being explicit about why: the app
 * ALREADY opens the three EventStore websockets (`/ws/events`, `-b`, `-c`)
 * unauthenticated, from any frame's origin, and the landing page has done so
 * for a long time. Serving the same stream's recent PAST to a client that can
 * already watch its PRESENT is the same data shifted in time. Each frame serves
 * its own ring from its own Redis, so no registry ever reads a foreign
 * EventStore — the "registries only subscribe to their own eventstore" boundary
 * is kept exactly as it is.
 */
async function seedReplayOnce(): Promise<void> {
  if (seedDone) return
  seedDone = true
  try {
    const sources = await discoverSeedSources()
    const seed: VerbDescriptor[] = []
    const results = await Promise.allSettled(sources.map(async (src) => {
      const res = await fetch(`${src.base}/api/v1/public/eventstore-recent?limit=200`, { cache: 'no-store' })
      if (!res.ok) return { frame: src.frame, events: [] as any[] }
      const body = await res.json()
      return { frame: src.frame, events: (Array.isArray(body) ? body : (body?.events || [])) as any[] }
    }))
    for (const r of results) {
      if (r.status !== 'fulfilled') continue          // a dark frame simply contributes nothing
      const { frame, events } = r.value
      if (!events.length) continue
      // Oldest first, so the ring stays chronological.
      for (const env of events.slice().reverse()) {
        const ctx: GrammarContext = {
          frame,
          frameCurrency: manifestFrames().find(f => f.key === frame)?.currency || null,
          mineDids,
          localRegistry: localRegistryByFrame.get(frame) ?? null,
          now: Date.now(),
        }
        if (!firstSightOfEvent(env)) { duplicatesDropped++; continue }
        const d = toVerb(env, ctx)
        if (d) seed.push(d)
      }
    }
    if (!seed.length) return
    // One timeline across frames: a replay of three ledgers interleaved by when
    // things actually happened, not grouped by who reported them.
    seed.sort((a, b) => a.tsMs - b.tsMs)
    replaySeeded = seed.length
    replayRing = seed.concat(replayRing).slice(-REPLAY_CAP)
  } catch { /* a seed that does not arrive simply leaves replay to live events */ }
}

function rememberForReplay(batch: VerbDescriptor[]): void {
  if (!batch.length) return
  replayRing.push(...batch)
  if (replayRing.length > REPLAY_CAP) {
    replayCapped = true
    replayRing = replayRing.slice(-REPLAY_CAP)
  }
  const cutoff = Date.now() - REPLAY_MAX_AGE_MS
  if (replayRing.length && replayRing[0].tsMs < cutoff) {
    const before = replayRing.length
    replayRing = replayRing.filter(d => d.tsMs >= cutoff)
    if (replayRing.length !== before) replayCapped = true
  }
}

function handleMessage(key: string, raw: string): void {
  let envelope: any
  try { envelope = JSON.parse(raw) } catch { return }
  if (envelope?.type && envelope.type !== 'event') return
  // Identity before counting: a repeat must not touch totalEvents, the per-frame
  // chips, the rate window, the raw subscribers or the stage.
  if (!firstSightOfEvent(envelope)) { duplicatesDropped++; return }

  const now = Date.now()
  const c = _frameCounts.get(key) ?? { n: 0, last: 0 }
  c.n++; c.last = now; _frameCounts.set(key, c)
  _total++
  _countsDirty = true
  scheduleFlush()
  _rateWindow.push(now)
  if (_rateWindow.length > 4000) _rateWindow.splice(0, _rateWindow.length - 4000)
  const rw = _rateByStrip[stripOfKey.get(key) ?? 'main']
  rw.push(now)
  if (rw.length > 4000) rw.splice(0, rw.length - 4000)

  for (const cb of rawSubs) {
    try { cb(key, envelope) } catch { /* swallow */ }
  }

  const known = manifestFrames().find(f => f.key === key) ?? runtimeFrames.find(f => f.key === key)
  const ctx: GrammarContext = {
    frame: key,
    frameCurrency: known?.currency || null,
    mineDids,
    localRegistry: localRegistryByFrame.get(key) ?? null,
    now,
  }
  const d = toVerb(envelope, ctx)
  if (d) {
    if (pending.length >= PENDING_CAP) { pending.shift(); _dropped++; _countsDirty = true }
    pending.push(d); scheduleFlush()
  }
}

function connect(c: Conn): void {
  if (typeof WebSocket === 'undefined' || c.closed) return
  const st = stateFor(c.key)
  if (st?.gaveUp) return
  try {
    c.ws = new WebSocket(c.url)
  } catch {
    scheduleReconnect(c)
    return
  }
  c.ws.onopen = () => {
    c.everOpened = true
    c.attempt = 0
    c.neverOpenedTries = 0
    const s = stateFor(c.key); if (s) s.connected = true
    try { c.ws?.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' })) } catch { /* torn down */ }
  }
  c.ws.onmessage = (m: MessageEvent) => handleMessage(c.key, String(m.data))
  c.ws.onclose = () => {
    const s = stateFor(c.key); if (s) s.connected = false
    c.ws = null
    scheduleReconnect(c)
  }
  c.ws.onerror = () => { /* onclose always follows; reconnect is handled there */ }
}

function scheduleReconnect(c: Conn): void {
  if (!started || c.closed) return
  const st = stateFor(c.key)
  if (!c.everOpened) {
    c.neverOpenedTries++
    if (c.neverOpenedTries >= NEVER_OPENED_GIVEUP) {
      // Structurally unreachable from this origin. Go quiet and SAY so, rather
      // than storming the console with 403s forever.
      if (st) { st.gaveUp = true; st.connected = false }
      return
    }
  }
  if (c.timer) clearTimeout(c.timer)
  const ceiling = Math.min(RECONNECT_CAP_MS, RECONNECT_BASE_MS * Math.pow(2, c.attempt++))
  // FULL JITTER (§JITTER): pick uniformly in [0, ceiling]. Lockstep reconnects
  // after an EventStore restart are a self-inflicted thundering herd.
  const delay = Math.random() * ceiling
  c.timer = setTimeout(() => connect(c), delay)
}

function start(): void {
  if (started) return
  started = true
  // Prime REPLAY from the registry's central seed. Fire-and-forget: the live
  // sockets below must not wait on it, and a seed that never arrives costs
  // nothing but an emptier replay.
  void seedReplayOnce()
  frames.value = []
  syncStrips()
  // §BATCH10: the runtime frames arrive one fetch later; the seeds do not wait for them. A fetch that
  // fails costs nothing but the fresh frames' columns — the seeds are already streaming.
  void ensureRuntimeFrames().then(() => {
    if (!started) return
    syncStrips()
  })
}

// §FEFRAME W2: a manifest that lands after the stream started (the 4 s router bound passed) opens its frames then.
onFrameManifest(() => { if (started) syncStrips() })

/**
 * §AGORASIM-2 — open the frames of every strip somebody is showing, close the frames of every strip nobody is.
 * A direct `start()` with no consumer at all (a test, a service) keeps the old behaviour: the main strip.
 */
function syncStrips(): void {
  if (!started) return
  const anyone = refByStrip.main + refByStrip.sandbox > 0
  const want = streamableFrames().filter(f => (anyone ? refByStrip[stripOf(f)] > 0 : stripOf(f) === 'main'))
  const wantKeys = new Set(want.map(f => f.key))
  for (const key of Array.from(conns.keys())) if (!wantKeys.has(key)) closeFrame(key)
  for (const f of want) openFrame(f)
}

/** Close ONE frame's socket for good (its strip folded) and drop its row and counters. */
function closeFrame(key: string): void {
  const c = conns.get(key)
  if (c) {
    c.closed = true
    if (c.timer) { clearTimeout(c.timer); c.timer = null }
    try { c.ws?.close(1000, 'strip folded') } catch { /* ignore */ }
    c.ws = null
    conns.delete(key)
  }
  if (frames.value.some(s => s.key === key)) frames.value = frames.value.filter(s => s.key !== key)
  _frameCounts.delete(key)
}

function acquire(strip: LedgerStrip): void {
  refByStrip[strip]++
  if (!started) start()
  else syncStrips()
}

function release(strip: LedgerStrip): void {
  refByStrip[strip] = Math.max(0, refByStrip[strip] - 1)
  if (refByStrip.main + refByStrip.sandbox === 0) stop()
  else syncStrips()
}

/** Open ONE frame's socket and publish its state row — idempotent per key. */
function openFrame(f: FrameDescriptor): void {
  if (conns.has(f.key)) return
  stripOfKey.set(f.key, stripOf(f))
  if (!stateFor(f.key)) {
    frames.value.push({
      key: f.key,
      strip: stripOf(f),
      label: f.label,
      currency: f.currency,
      accent: f.accent,
      connected: false,
      lastEventAt: null,
      eventCount: 0,
      gaveUp: false,
    })
  }
  const c: Conn = { key: f.key, url: wsUrlFor(f), ws: null, timer: null, attempt: 0, everOpened: false, neverOpenedTries: 0, closed: false }
  conns.set(f.key, c)
  connect(c)
}

function stop(): void {
  started = false
  for (const c of conns.values()) {
    c.closed = true
    if (c.timer) { clearTimeout(c.timer); c.timer = null }
    try { c.ws?.close(1000, 'stream idle') } catch { /* ignore */ }
    c.ws = null
  }
  conns.clear()
  for (const s of frames.value) s.connected = false
  pending = []
  if (flushHandle !== null) {
    if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(flushHandle)
    else clearTimeout(flushHandle as unknown as ReturnType<typeof setTimeout>)
    flushHandle = null
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────
/**
 * §AGORASIM-2 — every handle sees ONE strip: its frames, its counters, its liveness, its events. The main strip's
 * total stays the exact session total minus whatever the sandbox strip counted, so a page that never shows the
 * sandbox reads exactly what it always read.
 */
interface StripView {
  frames: ComputedRef<FrameStreamState[]>
  anyConnected: ComputedRef<boolean>
  allConnected: ComputedRef<boolean>
  totalEvents: ComputedRef<number>
  lastEventAt: ComputedRef<number | null>
  eventsPerSecond: ComputedRef<number>
}
const _views = new Map<LedgerStrip, StripView>()
/* The views are shared by every handle of a strip, so they live in a DETACHED scope: created inside the first
 * component's setup, a computed would belong to that component and stop when it unmounts. */
const _viewScope = effectScope(true)
function viewFor(strip: LedgerStrip): StripView {
  const cached = _views.get(strip)
  if (cached) return cached
  const v = _viewScope.run(() => buildView(strip)) as StripView
  _views.set(strip, v)
  return v
}
function buildView(strip: LedgerStrip): StripView {
  const fr = computed(() => frames.value.filter(f => (f.strip ?? 'main') === strip))
  const other = computed(() => frames.value.filter(f => (f.strip ?? 'main') !== strip))
  const v: StripView = {
    frames: fr,
    anyConnected: computed(() => fr.value.some(f => f.connected)),
    allConnected: computed(() => fr.value.length > 0 && fr.value.every(f => f.connected)),
    totalEvents: computed(() => (strip === 'main'
      ? Math.max(0, totalEvents.value - other.value.reduce((n, f) => n + f.eventCount, 0))
      : fr.value.reduce((n, f) => n + f.eventCount, 0))),
    lastEventAt: computed<number | null>(() => {
      let m: number | null = null
      for (const f of fr.value) if (f.lastEventAt && (m === null || f.lastEventAt > m)) m = f.lastEventAt
      return m
    }),
    eventsPerSecond: computed(() => {
      void _rateTick.value           // re-evaluate on every flush
      const w = _rateByStrip[strip]
      const cutoff = Date.now() - 5_000
      let n = 0
      for (let i = w.length - 1; i >= 0; i--) {
        if (w[i] < cutoff) break
        n++
      }
      return n / 5
    }),
  }
  return v
}
function inStrip(strip: LedgerStrip, frameKey: string): boolean {
  return (stripOfKey.get(frameKey) ?? 'main') === strip
}

/**
 * Join the shared stream. The socket opens on the FIRST consumer and closes when
 * the LAST one unmounts, so a page that does not want the ledger costs nothing.
 *
 * `autoStart: false` lets a caller (or a test) hold the handle without opening
 * sockets.
 */
export function useLedgerStream(opts?: { autoStart?: boolean; strip?: LedgerStrip }): LedgerStreamApi {
  const autoStart = opts?.autoStart !== false
  const strip: LedgerStrip = opts?.strip === 'sandbox' ? 'sandbox' : 'main'
  if (autoStart) {
    acquire(strip)
    // Only inside a component instance; a bare call (tests, services) opts out.
    try {
      onUnmounted(() => release(strip))
    } catch { /* not in a component scope */ }
  }
  const view = viewFor(strip)

  return {
    frames: view.frames,
    anyConnected: view.anyConnected,
    allConnected: view.allConnected,
    totalEvents: view.totalEvents,
    droppedForRender,
    eventsPerSecond: view.eventsPerSecond,
    lastEventAt: view.lastEventAt,
    onVerbs(cb) {
      // A batch carries every open frame; a handle hands its subscriber only its own strip's descriptors. While no
      // other strip is open the main strip's batch passes through untouched.
      const wrapped = (batch: VerbDescriptor[]) => {
        const onlyMain = refByStrip.sandbox === 0 && !Array.from(stripOfKey.values()).includes('sandbox')
        const mine = strip === 'main' && onlyMain ? batch : batch.filter(d => inStrip(strip, d.frame))
        if (mine.length) cb(mine)
      }
      verbSubs.add(wrapped)
      return () => { verbSubs.delete(wrapped) }
    },
    onRaw(cb) {
      const wrapped = (frameKey: string, inner: any) => { if (inStrip(strip, frameKey)) cb(frameKey, inner) }
      rawSubs.add(wrapped)
      return () => { rawSubs.delete(wrapped) }
    },
    setMineDids(dids) {
      const s = new Set<string>()
      for (const d of dids) if (d) s.add(String(d).toLowerCase())
      mineDids = s
    },
    setLocalRegistry(frameKey, slug) {
      if (slug) localRegistryByFrame.set(frameKey, slug)
      else localRegistryByFrame.delete(frameKey)
    },
    replayBuffer() { return replayRing.slice() },
    replayWindow() {
      return {
        from: replayRing.length ? replayRing[0].tsMs : null,
        to: replayRing.length ? replayRing[replayRing.length - 1].tsMs : null,
        count: replayRing.length,
        capped: replayCapped,
        seeded: replaySeeded,
        witnessed: Math.max(0, replayRing.length - replaySeeded),
        duplicatesDropped,
      }
    },
  }
}

// ─── Test seam ──────────────────────────────────────────────────────────────
/** Internals exposed for the unit suite ONLY. Not part of the app surface. */
export const __ledgerStreamInternals = {
  handleMessage,
  flush,
  start,
  stop,
  reset(): void {
    stop()
    frames.value = []
    totalEvents.value = 0
    droppedForRender.value = 0
    duplicatesDropped = 0
    // The seen-set must reset WITH the counters: a reset stream that still
    // remembers every id would silently refuse the whole replacement feed.
    _seenIds.clear()
    _seenOrder.length = 0
    _rateWindow.length = 0
    _frameCounts.clear(); _total = 0; _dropped = 0; _countsDirty = false
    verbSubs.clear()
    rawSubs.clear()
    localRegistryByFrame.clear()
    mineDids = new Set()
    pending = []
    refByStrip.main = 0; refByStrip.sandbox = 0
    stripOfKey.clear()
    _rateByStrip.main.length = 0; _rateByStrip.sandbox.length = 0
    runtimeFrames = []
    runtimeLoad = null
    _hostOverride = null
    _framesOverride = null
  },
  /** §BATCH10 test seam: the frames `/api/v1/public/fresh-network` would have returned. */
  setRuntimeFrames(list: FrameDescriptor[]): void { runtimeFrames = list.slice(); runtimeLoad = Promise.resolve(); runtimeTick.value++ },
  /** §BATCH10 test seam: pretend the app is served from this host (null = the real window). */
  setHostOverride(host: string | null): void { _hostOverride = host },
  /** §FEFRAME W2 test seam: the manifest's frames (null = the live FRAMES). */
  setManifestFrames(list: FrameDescriptor[] | null): void { _framesOverride = list ? list.slice() : null },
  runtimeFrameFromNetworkEntry,
  /** §AGORASIM-2 test seams: a consumer of one strip arriving and leaving, and which sockets are open. */
  acquire,
  release,
  openKeys(): string[] { return Array.from(conns.keys()) },
  stripHasFrames,
  localFrameDescriptor,
  openFrame,
  seedFrames(keys: string[]): void {
    frames.value = keys.map(k => {
      const f = manifestFrames().find(x => x.key === k)
      return {
        key: k, strip: 'main' as LedgerStrip, label: f?.label ?? k, currency: f?.currency ?? '', accent: f?.accent ?? '',
        connected: false, lastEventAt: null, eventCount: 0, gaveUp: false,
      }
    })
  },
  get pendingCount(): number { return pending.length },
  publishCounts,
  PENDING_CAP,
  streamableFrames,
  wsUrlFor,
  RENDER_BATCH_CAP,
}
