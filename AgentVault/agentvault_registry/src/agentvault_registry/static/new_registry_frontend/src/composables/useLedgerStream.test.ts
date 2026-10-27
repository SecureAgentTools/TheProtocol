// @vitest-environment node
/**
 * useLedgerStream.test.ts — §BRIDGE #B2 unit suite.
 *
 * Runs in `node` with no WebSocket and no rAF: the parts that matter (counting,
 * coalescing, honest overflow, endpoint derivation, subscriber fan-out) are all
 * provable without either. Mutation-verified 2026-08-18.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useLedgerStream, __ledgerStreamInternals as I, RENDER_BATCH_CAP, PENDING_CAP } from './useLedgerStream'
import type { VerbDescriptor } from '@/services/bridge/grammar'
import { framesFromManifest } from '@/config/frames'
import { manifestFrom } from '@/services/frameManifest'

// Distinct events get DISTINCT ids. The default used to be the constant 'e1',
// which made three "different" events share one identity — harmless while
// nothing read the id, and quietly wrong the moment something did.
let _eid = 0
function esEvent(eventType: string, data: Record<string, any> = {}, id?: string): string {
  return JSON.stringify({
    type: 'event',
    event: {
      id: id ?? `e${++_eid}`,
      event_type: eventType, aggregate_id: 'did:agg',
      timestamp: '2026-08-18T16:34:12Z', data,
    },
  })
}

beforeEach(() => {
  I.reset()
  I.seedFrames(['A', 'B', 'C'])
})

// §FEFRAME W2 — EU's frame manifest as core/federation_view.build_manifest assembles it on the live cluster
// (2026-10-01): EU and ASIA frames, each streaming its own ledger on its PUBLIC host; amsterdam an operator of EU.
const EU_MANIFEST = manifestFrom({
  manifest_version: 1, multi_frame: true,
  self: { key: 'eu', name: 'EU', display_name: 'EU', trust_domain: 'eu.theprotocol.cloud', role: 'frame', parent: null,
    public_url: 'https://eu.theprotocol.cloud', console_url: 'https://theprotocol.cloud', currency: 'ECU',
    currency_name: 'European Compute Unit', theme: 'neural', ledger_ws: 'wss://eu.theprotocol.cloud/ws/events' },
  peers: [
    { key: 'asia', name: 'ASIA', display_name: 'ASIA', trust_domain: 'asia.theprotocol.cloud', role: 'frame',
      public_url: 'https://asia.theprotocol.cloud', console_url: 'https://asia.theprotocol.cloud', currency: 'ACU',
      theme: 'sovereign', ledger_ws: 'wss://asia.theprotocol.cloud/ws/events' },
    { key: 'amsterdam', name: 'amsterdam', display_name: 'Amsterdam', trust_domain: 'eu.theprotocol.cloud',
      role: 'operator', parent: 'eu', public_url: 'https://amsterdam.op.theprotocol.cloud', currency: 'ECU',
      ledger_ws: 'wss://eu.theprotocol.cloud/ws/events' },
  ],
})!
const useEuManifest = (): void => I.setManifestFrames(framesFromManifest(EU_MANIFEST))

describe('endpoint derivation (§FEFRAME W2: the frame manifest + the runtime network, no seed)', () => {
  it('streams the manifest frames, own frame first, each on its own absolute ledger socket', () => {
    useEuManifest()
    const fr = I.streamableFrames()
    expect(fr.map(f => f.key)).toEqual(['eu', 'asia'])                     // never the operator: it has no store
    expect(fr.map(f => I.wsUrlFor(f))).toEqual(['wss://eu.theprotocol.cloud/ws/events', 'wss://asia.theprotocol.cloud/ws/events'])
    expect(fr.map(f => f.label)).toEqual(['EU', 'ASIA'])
    expect(fr.map(f => f.currency)).toEqual(['ECU', 'ACU'])
  })

  it('with no manifest (an unreadable config) streams this console\'s own socket only, never a seed', () => {
    I.setHostOverride('eu.theprotocol.cloud')
    const own = I.streamableFrames()
    expect(own.map(f => f.key)).toEqual(['local'])
    expect(own[0].es?.sameOriginPath).toBe('/ws/events')
    expect(own[0].label).toBe('EU')
    expect(own[0].currency).toBe('')                                       // no guessed unit
  })

  it('appends every runtime frame the manifest does not name (the folded sandbox strip on EU)', () => {
    useEuManifest()
    const sbx = I.runtimeFrameFromNetworkEntry({ name: 'Sandbox Alpha', slug: 'sbx-alpha', group: 'sandbox', strip: 'sandbox',
      currency: 'SBXA', ws_path: '/ws/events-sbxalpha', reachable: false })
    expect(sbx).not.toBeNull()
    I.setRuntimeFrames([sbx!])
    expect(I.streamableFrames().map(f => f.key)).toEqual(['eu', 'asia', 'sbx-alpha'])
    expect(I.wsUrlFor(sbx!)).toBe('ws://localhost/ws/events-sbxalpha')
    expect(sbx!.isSandbox).toBe(true); expect(sbx!.status).toBe('unreachable')
  })

  it('refuses a runtime entry with no socket path or no slug — a frame with no stream is not a stream', () => {
    expect(I.runtimeFrameFromNetworkEntry({ name: 'X', slug: 'x', ws_path: '' })).toBeNull()
    expect(I.runtimeFrameFromNetworkEntry({ name: 'X', slug: 'x', ws_path: 'events-x' })).toBeNull()
    expect(I.runtimeFrameFromNetworkEntry({ name: 'X', ws_path: '/ws/events-x' })).toBeNull()
    expect(I.runtimeFrameFromNetworkEntry(null)).toBeNull()
  })

  it('never opens the same socket twice: a runtime entry naming a manifest frame (by key or trust domain) is ONE stream', () => {
    useEuManifest()
    // EU's hand-set FRESH_NETWORK_JSON names EU on `/ws/events` (on the apex that lane was the retired Frame A store)
    // and ASIA on its peer lane; both are the manifest's frames already, streamed on their own hosts.
    const euAgain = I.runtimeFrameFromNetworkEntry({ name: 'EU', slug: 'eu', ws_path: '/ws/events', group: 'candidate' })
    const asiaByTd = I.runtimeFrameFromNetworkEntry({ name: 'ASIA again', slug: 'asia-2', ws_path: '/ws/events-asia',
      registry_url: 'https://asia.theprotocol.cloud', group: 'candidate' })
    I.setRuntimeFrames([euAgain!, asiaByTd!])
    expect(I.streamableFrames().map(f => f.key)).toEqual(['eu', 'asia'])
  })
})

describe('at-least-once wire (identity decides, not arrival)', () => {
  // MEASURED on the public socket 2026-08-19: 64 messages, 42 unique ids — the
  // EventStore broadcasts once at accept time and again after its Kafka consumer
  // stores the event. A console that counted both would overstate the ledger.
  it('counts a repeated event id ONCE, on every counter it feeds', () => {
    const api = useLedgerStream({ autoStart: false })
    const dup = esEvent('TokensTransferred', { amount: 5 }, 'dup-1')
    I.handleMessage('C', dup)
    I.handleMessage('C', dup)
    I.handleMessage('C', dup)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.totalEvents.value).toBe(1)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.frames.value.find(f => f.key === 'C')!.eventCount).toBe(1)
    expect(api.replayWindow().duplicatesDropped).toBe(2)
  })

  it('does not hand a repeat to raw subscribers or the stage', () => {
    const api = useLedgerStream({ autoStart: false })
    const seen: any[] = []
    api.onRaw((_k, env) => seen.push(env))
    const dup = esEvent('TokensTransferred', { amount: 5 }, 'dup-2')
    I.handleMessage('C', dup)
    I.handleMessage('C', dup)
    expect(seen.length).toBe(1)
  })

  it('NEVER drops an envelope with no id — absence of identity is not a repeat', () => {
    const api = useLedgerStream({ autoStart: false })
    const noId = JSON.stringify({ type: 'event', event: { event_type: 'TokensTransferred', data: {} } })
    I.handleMessage('C', noId)
    I.handleMessage('C', noId)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.totalEvents.value).toBe(2)
  })

  it('forgets what it has seen on reset, so a replacement feed is not refused', () => {
    const api1 = useLedgerStream({ autoStart: false })
    I.handleMessage('C', esEvent('TokensTransferred', {}, 'shared-id'))
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api1.totalEvents.value).toBe(1)
    I.reset()
    I.seedFrames(['A', 'B', 'C'])
    const api2 = useLedgerStream({ autoStart: false })
    I.handleMessage('C', esEvent('TokensTransferred', {}, 'shared-id'))
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api2.totalEvents.value).toBe(1)
  })
})

describe('exact counting (the ledger COUNTS)', () => {
  it('counts every event, including ones the stage will never draw', () => {
    const api = useLedgerStream({ autoStart: false })
    // LedgerBalanceChanged is silent by design on the stage, but it is still a
    // real event and the console must count it.
    I.handleMessage('C', esEvent('LedgerBalanceChanged', { amount: 5 }))
    I.handleMessage('C', esEvent('TokensTransferred', { amount: 5 }, 'e2'))
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.totalEvents.value).toBe(2)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.frames.value.find(f => f.key === 'C')!.eventCount).toBe(2)
  })

  it('counts per frame independently', () => {
    const api = useLedgerStream({ autoStart: false })
    I.handleMessage('A', esEvent('TokensTransferred'))
    I.handleMessage('C', esEvent('TokensTransferred'))
    I.handleMessage('C', esEvent('TokensTransferred'))
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.frames.value.find(f => f.key === 'A')!.eventCount).toBe(1)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.frames.value.find(f => f.key === 'C')!.eventCount).toBe(2)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.totalEvents.value).toBe(3)
  })

  it('stamps liveness per frame so a dead stream can look dead', () => {
    const api = useLedgerStream({ autoStart: false })
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.lastEventAt.value).toBeNull()
    I.handleMessage('B', esEvent('TokensTransferred'))
    const b = api.frames.value.find(f => f.key === 'B')!
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(b.lastEventAt).toBeGreaterThan(0)
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.lastEventAt.value).toBe(b.lastEventAt)
  })

  it('ignores non-event frames and unparseable payloads without counting them', () => {
    const api = useLedgerStream({ autoStart: false })
    I.handleMessage('C', JSON.stringify({ type: 'pong' }))
    I.handleMessage('C', '{ not json')
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.totalEvents.value).toBe(0)
  })
})

describe('coalescing (one callback per frame, not one per event)', () => {
  it('buffers descriptors and delivers them as ONE batch on flush', () => {
    const api = useLedgerStream({ autoStart: false })
    const batches: VerbDescriptor[][] = []
    api.onVerbs(b => batches.push(b))

    for (let i = 0; i < 10; i++) I.handleMessage('C', esEvent('TokensTransferred', { amount: i + 1 }, `e${i}`))
    expect(batches.length).toBe(0)      // nothing delivered before the flush
    expect(I.pendingCount).toBe(10)

    I.flush()
    expect(batches.length).toBe(1)
    expect(batches[0].length).toBe(10)
  })

  it('a flush with an empty buffer notifies nobody', () => {
    const api = useLedgerStream({ autoStart: false })
    const seen: any[] = []
    api.onVerbs(b => seen.push(b))
    I.flush()
    expect(seen.length).toBe(0)
  })

  it('only drawable events reach the buffer; silent ones are counted and dropped', () => {
    const api = useLedgerStream({ autoStart: false })
    const batches: VerbDescriptor[][] = []
    api.onVerbs(b => batches.push(b))
    I.handleMessage('C', esEvent('LedgerBalanceChanged'))
    I.handleMessage('C', esEvent('ReputationChanged', {}, 'e2'))
    I.handleMessage('C', esEvent('TokensTransferred', {}, 'e3'))
    I.flush()
    expect(api.totalEvents.value).toBe(3)
    expect(batches[0].map(d => d.eventType)).toEqual(['TokensTransferred'])
  })
})

describe('honest overflow (the stage SAMPLES and says so)', () => {
  it('caps the render batch and PUBLISHES how many it skipped', () => {
    const api = useLedgerStream({ autoStart: false })
    const batches: VerbDescriptor[][] = []
    api.onVerbs(b => batches.push(b))

    const burst = RENDER_BATCH_CAP + 25
    for (let i = 0; i < burst; i++) I.handleMessage('C', esEvent('TokensTransferred', {}, `e${i}`))
    I.flush()

    expect(batches[0].length).toBe(RENDER_BATCH_CAP)
    expect(api.droppedForRender.value).toBe(25)
    // The COUNT is still exact — sampling never lies about how much happened.
    I.publishCounts()   // §MCFOLD — counters publish at the flush cadence
    expect(api.totalEvents.value).toBe(burst)
  })

  it('keeps the NEWEST events when it caps, not the stalest', () => {
    const api = useLedgerStream({ autoStart: false })
    let last: VerbDescriptor[] = []
    api.onVerbs(b => { last = b })
    const burst = RENDER_BATCH_CAP + 5
    for (let i = 0; i < burst; i++) I.handleMessage('C', esEvent('TokensTransferred', { amount: i + 1 }, `e${i}`))
    I.flush()
    expect(last[last.length - 1].amount).toBe(burst)   // the freshest survived
    expect(last[0].amount).toBe(6)                     // the five stalest were skipped
  })

  it('does not report drops when the batch fits', () => {
    const api = useLedgerStream({ autoStart: false })
    api.onVerbs(() => {})
    for (let i = 0; i < RENDER_BATCH_CAP; i++) I.handleMessage('C', esEvent('TokensTransferred', {}, `e${i}`))
    I.flush()
    expect(api.droppedForRender.value).toBe(0)
  })
})

describe('subscriber fan-out', () => {
  it('delivers to every verb subscriber', () => {
    const api = useLedgerStream({ autoStart: false })
    const a: any[] = []; const b: any[] = []
    api.onVerbs(x => a.push(x)); api.onVerbs(x => b.push(x))
    I.handleMessage('C', esEvent('TokensTransferred'))
    I.flush()
    expect(a.length).toBe(1); expect(b.length).toBe(1)
  })

  it('unsubscribe actually detaches', () => {
    const api = useLedgerStream({ autoStart: false })
    const got: any[] = []
    const off = api.onVerbs(x => got.push(x))
    I.handleMessage('C', esEvent('TokensTransferred')); I.flush()
    off()
    I.handleMessage('C', esEvent('TokensTransferred', {}, 'e2')); I.flush()
    expect(got.length).toBe(1)
  })

  it('a throwing subscriber cannot take the stream down with it', () => {
    const api = useLedgerStream({ autoStart: false })
    const good: any[] = []
    api.onVerbs(() => { throw new Error('bad consumer') })
    api.onVerbs(x => good.push(x))
    I.handleMessage('C', esEvent('TokensTransferred'))
    expect(() => I.flush()).not.toThrow()
    expect(good.length).toBe(1)
  })

  it('raw subscribers see EVERY event, sampled or not', () => {
    const api = useLedgerStream({ autoStart: false })
    const raw: string[] = []
    api.onRaw((frame) => raw.push(frame))
    I.handleMessage('C', esEvent('LedgerBalanceChanged'))
    I.handleMessage('A', esEvent('TokensTransferred', {}, 'e2'))
    expect(raw).toEqual(['C', 'A'])
  })
})

describe('grammar context wiring', () => {
  it('tags descriptors with the delivering frame and its currency', () => {
    useEuManifest()
    const api = useLedgerStream({ autoStart: false })
    let batch: VerbDescriptor[] = []
    api.onVerbs(b => { batch = b })
    I.handleMessage('asia', esEvent('TokensTransferred'))
    I.flush()
    expect(batch[0].frame).toBe('asia')
    expect(batch[0].currency).toBe('ACU')      // ASIA settles in ACU, from the frame manifest
  })

  it('setMineDids makes the fleet lens predicate true, case-insensitively', () => {
    const api = useLedgerStream({ autoStart: false })
    let batch: VerbDescriptor[] = []
    api.onVerbs(b => { batch = b })
    api.setMineDids(['DID:Mine'])
    I.handleMessage('C', esEvent('TokensTransferred', { sender_did: 'did:mine' }))
    I.flush()
    expect(batch[0].mine).toBe(true)
  })

  it('clearing the did set turns the lens off again', () => {
    const api = useLedgerStream({ autoStart: false })
    let batch: VerbDescriptor[] = []
    api.onVerbs(b => { batch = b })
    api.setMineDids(['did:mine'])
    api.setMineDids([])
    I.handleMessage('C', esEvent('TokensTransferred', { sender_did: 'did:mine' }))
    I.flush()
    expect(batch[0].mine).toBe(false)
  })

  it('setLocalRegistry supplies the origin system for frame-local events', () => {
    const api = useLedgerStream({ autoStart: false })
    let batch: VerbDescriptor[] = []
    api.onVerbs(b => { batch = b })
    api.setLocalRegistry('C', 'frame-c')
    I.handleMessage('C', esEvent('TokensTransferred'))
    I.flush()
    expect(batch[0].from).toBe('frame-c')
  })
})

describe('connection state', () => {
  it('reports not-connected before any socket opens', () => {
    const api = useLedgerStream({ autoStart: false })
    expect(api.anyConnected.value).toBe(false)
    expect(api.allConnected.value).toBe(false)
  })

  it('anyConnected and allConnected disagree during a partial outage', () => {
    const api = useLedgerStream({ autoStart: false })
    api.frames.value[0].connected = true
    expect(api.anyConnected.value).toBe(true)
    expect(api.allConnected.value).toBe(false)
    api.frames.value.forEach(f => { f.connected = true })
    expect(api.allConnected.value).toBe(true)
  })

  it('start() is a no-op without a WebSocket implementation instead of throwing', () => {
    // The environment's WebSocket is removed explicitly: Node 22+ ships a global WebSocket client, so the test's
    // precondition no longer holds by itself when the suite runs on Node 24 (it did on Node 20).
    vi.stubGlobal('WebSocket', undefined)
    try {
      expect(typeof WebSocket).toBe('undefined')
      expect(() => I.start()).not.toThrow()
      I.stop()
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

describe('reconnect backoff uses FULL JITTER (never lockstep)', () => {
  it('two clients backing off at the same attempt pick different delays', () => {
    // The composable derives its delay as random() * ceiling. Assert the shape
    // directly: a deterministic (non-jittered) backoff would collapse to one value.
    const ceiling = (attempt: number) => Math.min(15_000, 300 * Math.pow(2, attempt))
    const draws = new Set<number>()
    const seq = [0.1, 0.4, 0.9, 0.25, 0.63]
    const spy = vi.spyOn(Math, 'random')
    seq.forEach(v => spy.mockReturnValueOnce(v))
    for (const v of seq) draws.add(Math.random() * ceiling(3))
    spy.mockRestore()
    expect(draws.size).toBe(seq.length)
    expect(Math.max(...draws)).toBeLessThanOrEqual(ceiling(3))
  })

  it('the ceiling grows exponentially and then clamps', () => {
    const ceiling = (a: number) => Math.min(15_000, 300 * Math.pow(2, a))
    expect(ceiling(0)).toBe(300)
    expect(ceiling(1)).toBe(600)
    expect(ceiling(5)).toBe(9600)
    expect(ceiling(20)).toBe(15_000)
  })
})

describe('§MCFOLD — the un-flushed queue has a ceiling, and counters publish once per flush', () => {
  it('a burst that never flushes (hidden tab) keeps the freshest PENDING_CAP and counts the rest', () => {
    const api = useLedgerStream({ autoStart: false })
    const n = PENDING_CAP * 5
    for (let i = 0; i < n; i++) I.handleMessage('C', esEvent('TokensTransferred', { amount: i }))
    expect(I.pendingCount).toBe(PENDING_CAP)
    I.flush()
    expect(api.droppedForRender.value).toBe(n - RENDER_BATCH_CAP)
    expect(api.totalEvents.value).toBe(n)
  })
  it('a thousand messages are ONE reactive write per counter, not a thousand', () => {
    const api = useLedgerStream({ autoStart: false })
    for (let i = 0; i < 1000; i++) I.handleMessage('A', esEvent('TokensTransferred'))
    expect(api.totalEvents.value).toBe(0)                 // nothing published yet
    expect(api.frames.value.find(f => f.key === 'A')!.eventCount).toBe(0)
    I.flush()
    expect(api.totalEvents.value).toBe(1000)
    expect(api.frames.value.find(f => f.key === 'A')!.eventCount).toBe(1000)
  })
})

// §AGORASIM-2 (2026-09-22) — the entries below are EU's live `/api/v1/public/fresh-network` rows as served on
// theprotocol.cloud that morning (EU names itself on `/ws/events`, the standup's console-relative rule), plus the
// two sandbox-strip rows the V0420 roll adds to EU's FRESH_NETWORK_JSON.
const LIVE_EU = { name: 'EU', slug: 'eu', group: 'sandbox', currency: 'ECU', ws_path: '/ws/events',
  registry_url: 'http://eu-registry:8000', console: 'https://eu.theprotocol.cloud', reachable: true }
const LIVE_ASIA = { name: 'ASIA', slug: 'asia', group: 'sandbox', currency: 'ACU', ws_path: '/ws/events-asia',
  registry_url: 'http://asia-registry:8000', console: 'https://asia.theprotocol.cloud', reachable: true }
const SBX_A = { name: 'Sandbox Alpha', slug: 'sbx-alpha', group: 'sandbox', strip: 'sandbox', currency: 'SBXA',
  ws_path: '/ws/events-sbxalpha', console: 'https://sandbox-a.theprotocol.cloud', reachable: true }
const SBX_B = { name: 'Sandbox Beta', slug: 'sbx-beta', group: 'sandbox', strip: 'sandbox', currency: 'SBXB',
  ws_path: '/ws/events-sbxbeta', console: 'https://sandbox-b.theprotocol.cloud', reachable: true }
const rt = (...rows: any[]) => rows.map(r => I.runtimeFrameFromNetworkEntry(r)!)

describe('§AGORASIM-2 — the flagship streams itself, and the sandbox has a strip of its own', () => {
  it('on the apex the manifest streams EU on its own host: never the retired Frame A store behind /ws/events', () => {
    I.setHostOverride('theprotocol.cloud')
    useEuManifest()
    I.setRuntimeFrames(rt(LIVE_EU, LIVE_ASIA))
    const fr = I.streamableFrames()
    // Before W2: ['A', 'B', 'C', 'eu', 'asia'], seed A on the apex's /ws/events (Frame A's store) and B/C dead lanes.
    expect(fr.map(f => f.key)).toEqual(['eu', 'asia'])
    expect(I.wsUrlFor(fr[0])).toBe('wss://eu.theprotocol.cloud/ws/events')
  })

  it('files a sandbox-strip entry under the sandbox strip only, and everything else under main', () => {
    I.setHostOverride('theprotocol.cloud')
    useEuManifest()
    I.setRuntimeFrames(rt(LIVE_EU, LIVE_ASIA, SBX_A, SBX_B))
    expect(I.streamableFrames('main').map(f => f.key)).toEqual(['eu', 'asia'])
    expect(I.streamableFrames('sandbox').map(f => f.key)).toEqual(['sbx-alpha', 'sbx-beta'])
    expect(I.streamableFrames('sandbox').map(f => f.es?.sameOriginPath)).toEqual(['/ws/events-sbxalpha', '/ws/events-sbxbeta'])
    // No argument is every frame: the cockpit's "can this deployment show a ledger at all?"
    expect(I.streamableFrames().length).toBe(4)
    // The control: a row that names no strip, or another word, is the main ledger.
    const odd = I.runtimeFrameFromNetworkEntry({ ...SBX_A, slug: 'odd', ws_path: '/ws/events-odd', strip: 'Sandbox ' })!
    const plain = I.runtimeFrameFromNetworkEntry({ ...SBX_A, slug: 'plain', ws_path: '/ws/events-plain', strip: undefined })!
    expect(odd.strip).toBe('main'); expect(plain.strip).toBe('main')
  })

  it('says whether a strip has frames, so the landing page shows the sandbox section only where it exists', () => {
    I.setHostOverride('asia.theprotocol.cloud')
    I.setRuntimeFrames(rt(LIVE_EU))
    expect(I.stripHasFrames('sandbox')).toBe(false)
    I.setRuntimeFrames(rt(LIVE_EU, SBX_A))
    expect(I.stripHasFrames('sandbox')).toBe(true)
    expect(I.stripHasFrames('main')).toBe(true)
  })

  it('a folded sandbox strip opens no socket; unfolding opens only its sockets; folding closes only those', () => {
    const opened: string[] = []
    const closed: string[] = []
    class FakeWS {
      url: string; onopen: any = null; onclose: any = null; onmessage: any = null; onerror: any = null
      constructor(url: string) { this.url = url; opened.push(url) }
      send(): void { /* subscribe frame */ }
      close(): void { closed.push(this.url) }
    }
    vi.stubGlobal('WebSocket', FakeWS as any)
    try {
      I.setHostOverride('theprotocol.cloud')
      useEuManifest()
      I.setRuntimeFrames(rt(LIVE_EU, LIVE_ASIA, SBX_A, SBX_B))
      I.acquire('main')                       // the landing page's globe feed / the main LIVE LEDGER
      expect(I.openKeys()).toEqual(['eu', 'asia'])
      expect(opened.some(u => u.includes('sbx'))).toBe(false)
      I.acquire('sandbox')                    // the visitor unfolds SANDBOX · LIVE LEDGER
      expect(I.openKeys()).toEqual(['eu', 'asia', 'sbx-alpha', 'sbx-beta'])
      I.release('sandbox')                    // ...and folds it again
      expect(I.openKeys()).toEqual(['eu', 'asia'])
      expect(closed.filter(u => u.includes('sbx')).length).toBe(2)
      expect(closed.some(u => !u.includes('sbx'))).toBe(false)
      I.release('main')
      expect(I.openKeys()).toEqual([])
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('each handle sees only its strip: raw events, verbs, frames and totals', () => {
    const opened: string[] = []
    class FakeWS { url: string; onopen: any; onclose: any; onmessage: any; onerror: any
      constructor(url: string) { this.url = url; opened.push(url) } send(): void {} close(): void {} }
    vi.stubGlobal('WebSocket', FakeWS as any)
    try {
      I.reset()
      I.setHostOverride('theprotocol.cloud')
      useEuManifest()
      I.setRuntimeFrames(rt(LIVE_EU, SBX_A))
      I.acquire('main'); I.acquire('sandbox')
      const main = useLedgerStream({ autoStart: false })
      const sbx = useLedgerStream({ autoStart: false, strip: 'sandbox' })
      const seenMain: string[] = []; const seenSbx: string[] = []
      main.onRaw(k => seenMain.push(k)); sbx.onRaw(k => seenSbx.push(k))
      const vMain: string[] = []; const vSbx: string[] = []
      main.onVerbs(b => b.forEach(d => vMain.push(d.frame))); sbx.onVerbs(b => b.forEach(d => vSbx.push(d.frame)))
      I.handleMessage('eu', esEvent('TokensTransferred', { amount: 1 }))
      I.handleMessage('sbx-alpha', esEvent('TokensTransferred', { amount: 2 }))
      I.handleMessage('sbx-alpha', esEvent('TokensTransferred', { amount: 3 }))
      I.flush()
      expect(seenMain).toEqual(['eu']); expect(seenSbx).toEqual(['sbx-alpha', 'sbx-alpha'])
      expect(vMain.every(k => k === 'eu')).toBe(true); expect(vSbx.every(k => k === 'sbx-alpha')).toBe(true)
      expect(main.frames.value.map(f => f.key)).toEqual(['eu', 'asia'])
      expect(sbx.frames.value.map(f => f.key)).toEqual(['sbx-alpha'])
      expect(sbx.totalEvents.value).toBe(2)
      expect(main.totalEvents.value).toBe(1)
      I.release('sandbox'); I.release('main')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
