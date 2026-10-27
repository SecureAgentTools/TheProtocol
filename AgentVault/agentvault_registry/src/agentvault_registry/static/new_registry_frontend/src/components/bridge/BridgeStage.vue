<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgeStage.vue — §BRIDGE #B3/#B4/#B6
 *
 * THE STAGE. The full-bleed living starmap behind Mission Control, where every
 * light is a real ledger event.
 *
 * It composes rather than builds:
 *   - the map            = `GalacticMap.vue` in `mission-mode` (one canvas, one
 *                          extra render profile, no fork — the §GalacticCommand
 *                          embed precedent)
 *   - the meaning        = `services/bridge/grammar.ts` (pure, unit-tested)
 *   - the traffic        = `composables/useLedgerStream.ts` (one shared socket set)
 *
 * This component only wires those three together and renders the honesty layer:
 * the caption, the stream-truth banner and the sampling notice.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import GalacticMap from '@/views/GalacticMap.vue'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { useI18n } from '@/composables/useI18n'
import { describeVerb, humaneAmount, type VerbDescriptor, classifyEnvelope } from '@/services/bridge/grammar'
import { usePrivacy } from '@/composables/usePrivacy'
import { useRouter } from 'vue-router'

const { t } = useI18n()
const router = useRouter()

const props = withDefaults(defineProps<{
  /**
   * EVERY DID the viewer owns. Identity only — it answers "is this event mine?"
   * and must be complete, or the fleet lens and the ledger under-report.
   */
  mineDids?: string[]
  /**
   * The BOUNDED subset drawn as individual stars.
   *
   * Deliberately a different list from `mineDids`, because they are different
   * questions: identity is free, geometry is not. P1 cut the stage down to the
   * viewer's own agents after it built one sprite per agent (~2,100 on frame-c)
   * and blocked the renderer for minutes; R1 then made `mineDids` complete
   * (200 -> 4,098) and, because the two were the same prop, walked that cost
   * straight back up. One prop, two jobs, is how a fixed defect returns.
   */
  starDids?: string[]
  /**
   * §OWNEDHOMES — where each drawn star LIVES, for the ones the map's own
   * source cannot place.
   *
   * `/agents/locations/` is a 6,000-row SAMPLE of ~13,800: measured on frame-c
   * 2026-08-21, only 1,689 of his 4,440 owned agents were in it, and not one
   * foreign agent he owns was. `starDids` is a FILTER over that sample, so an
   * agent he owns on op-berlin could never become a star no matter how the
   * budget was spread. This says where it belongs so the map can place it by
   * the same deterministic DID-seeded orbit every other star uses.
   */
  ownedHomes?: Array<{ did: string; name?: string | null; local?: boolean; names?: string[]; trustDomain?: string | null }>
  /** Deferred mount: the HUD must paint before WebGL starts (strategy §8.1). */
  deferMs?: number
  /** Forensics is admin-only; a dead-end door is worse than no door. */
  canOpenForensics?: boolean
  /** §BRIDGE R10 — the HUD's agent search. Dims non-matches, beacons matches. */
  search?: string
  /** §BRIDGE R14.4 — the wash dial: 'off' | 'subtle' | 'full'. */
  atmosphere?: string
}>(), { mineDids: () => [], starDids: () => [], ownedHomes: () => [], deferMs: 300, canOpenForensics: false, search: '', atmosphere: 'subtle' })

const emit = defineEmits<{
  (e: 'verbs', batch: VerbDescriptor[]): void
  /** §BRIDGE R13 #2 — the stage can name a target now. */
  (e: 'select-agent', did: string): void
}>()

/**
 * WHO WE ARE ACTUALLY TALKING TO (§BRIDGE R5).
 *
 * The other end of the viewer's own traffic, kept as a small most-recent set so
 * those parties can be drawn as dim stars and an arc can land on a body instead
 * of on the glyph of a whole registry. Bounded hard: this feeds geometry, and
 * geometry is the one thing on this stage that must never grow with the network
 * (the R1.6 lesson — identity is free, stars are not).
 *
 * Only counterparties of MINE. A busy network's full party list would be the
 * whole population again, which is precisely what mission mode exists to avoid.
 */
const CP_CAP = 48
/** did -> { last seen, the frame we saw it transacting on }. */
const counterpartySeen = new Map<string, { t: number; frame: string | null }>()
const counterparties = ref<Array<{ did: string; frame: string | null }>>([])
let cpDirty = false
function noteCounterparties(batch: VerbDescriptor[]): void {
  const mine = new Set((props.mineDids || []).map(d => String(d).toLowerCase()))
  if (!mine.size) return
  const now = Date.now()
  for (const d of batch) {
    if (!d?.mine) continue
    // WHICH FRAME each side is on. Carrying this is what makes the feature work
    // at all: `/agents/locations/` is a 6,000-row SAMPLE and the busiest
    // counterparties are not in it, so without a frame there is no home we can
    // name and the guard (correctly) refuses to draw them. The frame is not a
    // guess — it is where the event was settled.
    const sideFrame = (side: 'from' | 'to') =>
      (side === 'from' ? d.fromFrame : d.toFrame) || d.frame || null
    for (const [party, side] of [[d.fromDid, 'from'], [d.toDid, 'to'], [d.actorDid, 'from']] as const) {
      if (!party) continue
      const k = String(party).toLowerCase()
      if (mine.has(k)) continue          // that one is ours; it already has a star
      counterpartySeen.set(k, { t: now, frame: sideFrame(side) })
      cpDirty = true
    }
  }
  if (!cpDirty) return
  // Trim to the most recent CP_CAP, then republish. Rebuilding the array is
  // what makes the map rebuild its instanced mesh, so it happens on the tick,
  // never per event.
  if (counterpartySeen.size > CP_CAP) {
    const oldestFirst = Array.from(counterpartySeen.entries()).sort((a, b) => a[1].t - b[1].t)
    for (const [k] of oldestFirst.slice(0, counterpartySeen.size - CP_CAP)) counterpartySeen.delete(k)
  }
}

const mapRef = ref<any>(null)
const stageReady = ref(false)
const captionShown = ref(false)

const stream = useLedgerStream()

/** Honest liveness: how long since ANY frame delivered a real event. */
const nowTick = ref(Date.now())
let tickTimer: ReturnType<typeof setInterval> | null = null

const lastEventAgo = computed<number | null>(() => {
  const last = stream.lastEventAt.value
  return last === null ? null : Math.max(0, Math.round((nowTick.value - last) / 1000))
})

const lastEventClock = computed<string>(() => {
  const last = stream.lastEventAt.value
  if (last === null) return '--:--:--'
  return new Date(last).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
})

/**
 * Four honest states, and no fifth. A quiet network says it is quiet; it never
 * gets fake particles to look busy (strategy honesty rule 1).
 */
const streamState = computed<'connecting' | 'reconnecting' | 'quiet' | 'live'>(() => {
  if (!stream.anyConnected.value) {
    return stream.lastEventAt.value === null ? 'connecting' : 'reconnecting'
  }
  const ago = lastEventAgo.value
  if (ago === null || ago > 45) return 'quiet'
  return 'live'
})

const sampledPerSecond = computed(() => Math.round(stream.eventsPerSecond.value))

/**
 * #B12 — PHOTONS ARE RECEIPTS. Click a moving light and it stops being decoration:
 * the descriptor that drew it opens as a card, and the card is a DOOR into the
 * record it came from. No new detail surface is invented here; Forensics already
 * exists, and the card is only allowed to say what the event actually carried.
 */
const receipt = ref<VerbDescriptor | null>(null)
const { money: privacyMoney } = usePrivacy()
// R16.3 — the photon receipt names an amount; the switch reaches it too.
const receiptAmount = computed(() => {
  if (!receipt.value) return null
  const a = humaneAmount(receipt.value.amount)
  return a === null ? null : privacyMoney(a)
})
const receiptLine = computed(() => (receipt.value ? describeVerb(receipt.value) : ''))
const receiptClock = computed(() =>
  receipt.value ? new Date(receipt.value.tsMs).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '')

/**
 * A star was picked on the stage. Selecting is all this does — the camera is a
 * separate question (§BRIDGE R9: `onFollow` used to null the target whenever the
 * stage could not place an agent, which silently broke selection for thousands).
 */
function onStageAgent(agent: any): void {
  const did = agent?.did
  if (typeof did === 'string' && did) emit('select-agent', did)
}

function onVerbClick(d: VerbDescriptor | null): void {
  receipt.value = d || null
}
function closeReceipt(): void { receipt.value = null }
function openForensics(): void {
  const ref0 = receipt.value?.receiptRef?.eventId || receipt.value?.receiptRef?.aggregateId
  router.push(ref0 ? { path: '/admin/forensics', query: { q: String(ref0) } } : '/admin/forensics')
    .catch(() => { /* the route guard owns the outcome */ })
}

let offVerbs: (() => void) | null = null
let offRaw: null | (() => void) = null
/* R14.2 — raw/counted counters. weatherSeen=0 is ambiguous on its own: it could
 * be a quiet wire, a classifier that never says 'counted', or a setter that is
 * never reached. These three numbers separate all three. */
let rawSeen = 0
let countedSeen = 0
let weatherDelivered = 0
let mountTimer: ReturnType<typeof setTimeout> | null = null

/*
 * §LITEBRIDGE — the STAGE no longer owns "which DIDs are mine".
 *
 * It used to: `watch(props.mineDids, stream.setMineDids)` lived here. That was
 * fine while the stage was the only way to see the bridge, and it became a
 * silent defect the moment the stage could be absent — with the light bridge
 * mounted instead, nothing would ever have called it, and the fleet log and the
 * ledger's MINE filter would both have reported an empty fleet on a machine
 * whose only sin was having no GPU. MissionControl sets it now, in both modes,
 * once, and can narrow it when the board focuses a registry.
 */

onMounted(() => {
  installDebugHook()
  tickTimer = setInterval(() => { nowTick.value = Date.now(); republishCounterparties() }, 1000)

  // Defer the WebGL mount past first paint. The HUD is the promise the page
  // makes on load; the stage is the one it keeps a beat later.
  const boot = () => {
    stageReady.value = true
    setTimeout(() => { captionShown.value = true }, 900)
  }
  if (typeof requestIdleCallback === 'function') {
    const id = setTimeout(() => requestIdleCallback(boot, { timeout: 1200 }), props.deferMs)
    mountTimer = id
  } else {
    mountTimer = setTimeout(boot, props.deferMs)
  }

  // One coalesced batch per animation frame, straight into the pooled verb layer.
  offVerbs = stream.onVerbs((batch) => {
    mapRef.value?.pushVerbs?.(batch)
    noteCounterparties(batch)
    emit('verbs', batch)
  })

  /*
   * §BRIDGE R14.2 — the 81 counted-only types become weather.
   *
   * These never come through `onVerbs`: `toVerb()` returns null for them by
   * design, and that must not change — drawing `LedgerBalanceChanged` as motion
   * would double-count on screen every movement already drawn. So they are read
   * from the RAW hook and attributed to the frame that delivered them.
   *
   * `unknown` types are deliberately excluded. A type this build cannot name is
   * not evidence of activity we are entitled to render, in any form.
   */
  offRaw = stream.onRaw((frameKey, envelope) => {
    // classifyEnvelope UNWRAPS. Reading `envelope.event_type` here would find
    // undefined on every real message; see the note on classifyEnvelope.
    rawSeen++
    if (classifyEnvelope(envelope) === 'counted') {
      countedSeen++
      if (mapRef.value?.noteWeather) { mapRef.value.noteWeather(frameKey); weatherDelivered++ }
    }
  })
})

/** Republish on the slow tick: a mesh rebuild must never ride the event rate. */
function republishCounterparties(): void {
  if (!cpDirty) return
  cpDirty = false
  const next = Array.from(counterpartySeen.entries()).map(([did, v]) => ({ did, frame: v.frame }))
  if (next.length !== counterparties.value.length ||
      next.some((d, i) => d.did !== counterparties.value[i]?.did)) {
    counterparties.value = next
  }
}

onBeforeUnmount(() => {
  offVerbs?.()
  offRaw?.()
  if (tickTimer) clearInterval(tickTimer)
  if (mountTimer) clearTimeout(mountTimer)
  removeDebugHook()
})

/**
 * §7.7 — dev-only self-measurement hook. Behind `?bridgedebug=1` ONLY, so the
 * perf contract in §8 is something a battery can READ rather than something a
 * human has to believe. Nothing is attached to window without the flag.
 */
function installDebugHook(): void {
  if (typeof window === 'undefined') return
  try {
    if (!new URLSearchParams(window.location.search).has('bridgedebug')) return
  } catch { return }
  ;(window as any).__bridge = {
    stats: () => mapRef.value?.bridgeStats?.() ?? null,
    raw: () => ({ rawSeen, countedSeen, weatherDelivered, hasNote: !!mapRef.value?.noteWeather }),
    stream: () => ({
      frames: stream.frames.value.map(f => ({ key: f.key, connected: f.connected, events: f.eventCount, gaveUp: f.gaveUp })),
      total: stream.totalEvents.value,
      dropped: stream.droppedForRender.value,
      perSecond: stream.eventsPerSecond.value,
      lastEventAt: stream.lastEventAt.value,
      state: streamState.value,
    }),
    ready: () => stageReady.value,
    verbs: () => mapRef.value?.verbScreenPositions?.() ?? [],
    stars: () => mapRef.value?.agentScreenPositions?.() ?? [],
    /** R13 #8 — the hover card's source data, for the battery. */
    hoverEntityFor: (did: string) => mapRef.value?.hoverEntityFor?.(did) ?? null,
    searchMatches: () => mapRef.value?.searchMatchCount?.() ?? 0,
    densityByRegistry: () => mapRef.value?.densityByRegistry?.() ?? null,
    registryIndex: () => mapRef.value?.registryIndex?.() ?? [],
    /** Deterministic framing for capture. Wheel events never reached
     *  OrbitControls from a driver, so a screenshot could not be aimed. */
    cameraState: () => mapRef.value?.cameraState?.() ?? null,
    setCamera: (x: number, y: number, z: number) => mapRef.value?.setCamera?.(x, y, z) ?? false,
    receipt: () => (receipt.value ? { eventType: receipt.value.eventType, verb: receipt.value.verb } : null),
    token: DEBUG_TOKEN,
  }
}

/**
 * Leaving `__bridge` behind on unmount would pin this component's closures and
 * make the mode-isolation gate pass for the WRONG reason (a stale hook whose
 * `stats()` happens to return null once `mapRef` clears). The gate has to fail
 * when isolation is actually broken, so the hook leaves when the stage does.
 */
const DEBUG_TOKEN = Symbol('bridgeDebug')
function removeDebugHook(): void {
  if (typeof window === 'undefined') return
  const cur = (window as any).__bridge
  if (cur && cur.token === DEBUG_TOKEN) delete (window as any).__bridge
}

/*
 * §BRIDGE R14.4 — apply the persisted atmosphere WHEN THE CANVAS EXISTS.
 * The stage mounts deferred so the HUD can paint first (§8.1), which means a
 * setter fired on this component's `mounted` reliably lands on a null ref. This
 * watches the REF as well as the value, so it applies on whichever happens last
 * and re-applies if the canvas is ever rebuilt. No timeout, nothing to tune.
 */
watch([() => props.atmosphere, mapRef], () => {
  mapRef.value?.setAtmosphere?.(props.atmosphere)
}, { immediate: true })

defineExpose({
  bridgeStats: () => mapRef.value?.bridgeStats?.() ?? null,
  cameraState: () => mapRef.value?.cameraState?.() ?? null,
  setCamera: (x: number, y: number, z: number) => mapRef.value?.setCamera?.(x, y, z) ?? false,
  setAtmosphere: (m: string) => mapRef.value?.setAtmosphere?.(m),
  missionBoost: (ms?: number) => mapRef.value?.missionBoost?.(ms),
  setFleetLens: (on: boolean) => mapRef.value?.setFleetLens?.(on),
  setFollowAgent: (did: string | null) => mapRef.value?.setFollowAgent?.(did) ?? false,
  searchMatchCount: () => mapRef.value?.searchMatchCount?.() ?? 0,
  searchMatchDids: () => mapRef.value?.searchMatchDids?.() ?? [],
  isFollowing: () => mapRef.value?.isFollowing?.() ?? null,
  /** #B17 — feed the stage a replayed batch. Same path live events take. */
  pushVerbs: (batch: VerbDescriptor[]) => mapRef.value?.pushVerbs?.(batch),
})
</script>

<template>
  <div class="bstage" :class="`bstage--${streamState}`" data-tour="bridge-stage">
    <!-- The map. aria-hidden: it is atmosphere over an accessible HUD, and the
         ledger console is the accessible rendering of the very same truth. -->
    <div class="bstage-canvas" aria-hidden="true">
      <GalacticMap
        v-if="stageReady"
        ref="mapRef"
        embedded
        mission-mode
        :only-agent-dids="starDids"
        :owned-homes="ownedHomes"
        :counterparties="counterparties"
        :mission-search="search"
        @verb-click="onVerbClick"
        @select-agent="onStageAgent"
      />
      <div v-else class="bstage-preboot"></div>
    </div>

    <!-- Honesty layer -->
    <div class="bstage-veil"></div>

    <!-- #B12 the receipt of one photon. Only fields the event really carried. -->
    <div v-if="receipt" class="bstage-receipt" role="dialog" aria-live="polite" data-testid="verb-receipt">
      <div class="bstage-receipt-hd">
        <span class="bstage-receipt-type">{{ receipt.eventType }}</span>
        <button type="button" class="bstage-receipt-x"
                :title="t('bridge.receipt.close', 'Close')" @click="closeReceipt">x</button>
      </div>
      <p class="bstage-receipt-line">{{ receiptLine }}</p>
      <dl class="bstage-receipt-facts">
        <div v-if="receiptAmount"><dt>{{ t('bridge.receipt.amount', 'AMOUNT') }}</dt>
          <dd>{{ receiptAmount }} {{ receipt.currency || '' }}</dd></div>
        <div><dt>{{ t('bridge.receipt.frame', 'FRAME') }}</dt><dd>{{ receipt.frame }}</dd></div>
        <div><dt>{{ t('bridge.receipt.at', 'AT') }}</dt><dd>{{ receiptClock }}</dd></div>
        <div v-if="receipt.correlationKey"><dt>{{ t('bridge.receipt.corr', 'STORY') }}</dt>
          <dd>{{ receipt.correlationKey }}</dd></div>
      </dl>
      <button v-if="canOpenForensics" type="button" class="bstage-receipt-door" @click="openForensics">
        {{ t('bridge.receipt.forensics', 'OPEN IN LEDGER FORENSICS') }}
      </button>
    </div>

    <div class="bstage-caption" :class="{ 'is-in': captionShown }">
      <span class="bstage-caption-dot"></span>
      <span class="bstage-caption-text">
        {{ t('bridge.caption', 'LIVE - every light on this map is a ledger event.') }}
      </span>
    </div>

    <div class="bstage-truth" role="status">
      <template v-if="streamState === 'connecting'">
        <span class="bstage-truth-dot bstage-dot-wait"></span>
        <span>{{ t('bridge.stream.connecting', 'CONNECTING TO THE LEDGER') }}</span>
      </template>
      <template v-else-if="streamState === 'reconnecting'">
        <span class="bstage-truth-dot bstage-dot-warn"></span>
        <span>{{ t('bridge.stream.reconnecting', 'STREAM RECONNECTING') }} - {{ t('bridge.stream.lastReal', 'last real event') }} {{ lastEventClock }}</span>
      </template>
      <template v-else-if="streamState === 'quiet'">
        <span class="bstage-truth-dot bstage-dot-quiet"></span>
        <span>{{ t('bridge.stream.quiet', 'LOW ACTIVITY') }} - {{ t('bridge.stream.lastReal', 'last real event') }} {{ lastEventClock }}</span>
      </template>
      <template v-else>
        <span class="bstage-truth-dot bstage-dot-live"></span>
        <span>{{ t('bridge.stream.live', 'LIVE') }}</span>
        <span class="bstage-truth-rate">{{ sampledPerSecond }}/s</span>
        <!-- The stage samples, the ledger counts. Said out loud, never hidden. -->
        <span v-if="stream.droppedForRender.value > 0" class="bstage-truth-sample"
              :title="t('bridge.stream.sampleHelp', 'Under load the stage draws a capped sample. The ledger console keeps the exact count.')">
          +{{ stream.droppedForRender.value.toLocaleString(appLocale()) }} {{ t('bridge.stream.notDrawn', 'not drawn') }}
        </span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.bstage {
  position: absolute;
  inset: 0;
  /* Explicit floor of the stacking order: the HUD declares z-index 2, so the
     stage never composites over its own instruments regardless of whether the
     browser promotes the WebGL canvas to its own layer. */
  z-index: 0;
  overflow: hidden;
  background: radial-gradient(ellipse at 50% 45%, rgba(18, 26, 48, 0.9) 0%, rgba(5, 7, 15, 1) 72%);
}
.bstage-canvas { position: absolute; inset: 0; transition: opacity 900ms ease, filter 400ms ease; }

/* The receipt sits over the stage but under the HUD rails, and only exists
   while a photon is selected. Quiet glass, same tokens as every other card. */
.bstage-receipt {
  position: absolute; left: 50%; bottom: 3.2rem; transform: translateX(-50%);
  z-index: 1; pointer-events: auto;
  min-width: 17rem; max-width: 26rem;
  padding: 0.55rem 0.7rem;
  background: rgba(8, 12, 22, 0.92);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.28));
  border-radius: 4px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  animation: bstage-receipt-in 180ms ease both;
}
@keyframes bstage-receipt-in { from { opacity: 0; transform: translate(-50%, 6px); } to { opacity: 1; transform: translate(-50%, 0); } }
.bstage-receipt-hd { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; }
.bstage-receipt-type { color: var(--nc-primary, #22d3ee); font-size: 0.62rem; letter-spacing: 0.1em; }
.bstage-receipt-x {
  background: none; border: 0; cursor: pointer; padding: 0 0.2rem;
  color: var(--nc-text-dim, #6b7f9e); font-family: inherit; font-size: 0.7rem;
}
.bstage-receipt-line { margin: 0.3rem 0 0.4rem; color: var(--nc-text, #d6e2f2); font-size: 0.66rem; line-height: 1.5; }
.bstage-receipt-facts { display: flex; flex-wrap: wrap; gap: 0.3rem 0.9rem; margin: 0; }
.bstage-receipt-facts div { display: flex; align-items: baseline; gap: 0.3rem; }
.bstage-receipt-facts dt { color: var(--nc-text-dim, #6b7f9e); font-size: 0.5rem; letter-spacing: 0.12em; }
.bstage-receipt-facts dd { margin: 0; color: var(--nc-text, #d6e2f2); font-size: 0.58rem; }
.bstage-receipt-door {
  margin-top: 0.5rem; width: 100%; cursor: pointer;
  padding: 0.28rem 0.4rem; border-radius: 3px;
  background: transparent; border: 1px solid var(--nc-primary, #22d3ee);
  color: var(--nc-primary, #22d3ee);
  font-family: inherit; font-size: 0.55rem; letter-spacing: 0.12em;
}
@media (prefers-reduced-motion: reduce) { .bstage-receipt { animation: none; } }
.bstage-preboot { position: absolute; inset: 0; }

/* A dropped stream dims the stage instead of freezing it silently. */
.bstage--reconnecting .bstage-canvas { opacity: 0.8; filter: saturate(0.6); }
.bstage--connecting .bstage-canvas { opacity: 0.9; }

/* Keeps HUD text legible over a bright galaxy without hiding the galaxy. */
.bstage-veil {
  position: absolute; inset: 0; pointer-events: none;
  background:
    radial-gradient(ellipse at 50% 50%, rgba(0, 0, 0, 0) 42%, rgba(3, 5, 12, 0.55) 100%),
    linear-gradient(to bottom, rgba(3, 5, 12, 0.45) 0%, rgba(3, 5, 12, 0) 18%, rgba(3, 5, 12, 0) 78%, rgba(3, 5, 12, 0.5) 100%);
}

.bstage-caption {
  /* Offset by the pulse strip (--brg-pulse-h, declared on .brg). */
  position: absolute; left: 50%; bottom: calc(var(--brg-pulse-h, 0px) + 4.5rem); transform: translate(-50%, 8px);
  display: flex; align-items: center; gap: 0.5rem;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-size: 0.72rem; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--nc-text-dim, #8fa3c0);
  opacity: 0; transition: opacity 1200ms ease, transform 1200ms ease;
  pointer-events: none; white-space: nowrap;
}
.bstage-caption.is-in { opacity: 1; transform: translate(-50%, 0); }
.bstage-caption-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--nc-primary, #22d3ee);
  box-shadow: 0 0 8px var(--nc-primary, #22d3ee);
}

.bstage-truth {
  position: absolute; right: 1rem; bottom: calc(var(--brg-pulse-h, 0px) + 0.75rem);
  display: flex; align-items: center; gap: 0.45rem;
  padding: 0.3rem 0.6rem; border-radius: 3px;
  background: rgba(6, 10, 20, 0.72);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-size: 0.63rem; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--nc-text-dim, #8fa3c0);
}
.bstage-truth-dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
.bstage-dot-live { background: var(--nc-success, #22c55e); box-shadow: 0 0 7px var(--nc-success, #22c55e); animation: bstage-pulse 2.4s ease-in-out infinite; }
.bstage-dot-quiet { background: var(--nc-text-dim, #8fa3c0); }
.bstage-dot-warn { background: var(--nc-warning, #f59e0b); animation: bstage-pulse 1.1s ease-in-out infinite; }
.bstage-dot-wait { background: var(--nc-border, #6b7f9e); }
.bstage-truth-rate { color: var(--nc-primary, #22d3ee); }
.bstage-truth-sample { color: var(--nc-warning, #f59e0b); cursor: help; }

@keyframes bstage-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

@media (prefers-reduced-motion: reduce) {
  .bstage-caption { transition: none; opacity: 1; transform: translate(-50%, 0); }
  .bstage-dot-live, .bstage-dot-warn { animation: none; }
}
</style>
