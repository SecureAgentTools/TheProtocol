<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgeLedger.vue — §BRIDGE #B5
 *
 * ONE live ledger, replacing the three side-by-side raw consoles that used to be
 * the centrepiece of Mission Control. Same truth, one place, per-frame chips
 * instead of per-frame panels.
 *
 * This is the ACCESSIBLE rendering of the stage: the stage draws a capped
 * sample, this counts everything, and both numbers are on screen at once.
 * It reads from the shared `useLedgerStream` singleton — it opens no socket.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { unwrapEnvelope, involvesDids, VERB_TABLE, SILENT_BY_DESIGN } from '@/services/bridge/grammar'
import { createHistoryRing } from '@/services/bridge/historyRing'
import BridgePayloadModal from '@/components/bridge/BridgePayloadModal.vue'
import { ledgerEventLabel } from '@/services/ledgerEventLabel'

const { t } = useI18n()
const router = useRouter()

/** Ledger Forensics lives behind the admin gate, so the door only appears for
 *  someone who can actually walk through it. A dead-end button is worse than no
 *  button. */
const props = withDefaults(defineProps<{
  canOpenForensics?: boolean
  /** The viewer's own agent DIDs. Drives the default MINE scope. */
  mineDids?: string[]
  /**
   * Honest note about the DID set itself: null when it is complete, otherwise
   * what is missing. An empty MINE means "nothing matched", and that is only
   * true if we actually know the whole fleet — while the DID list is still
   * loading, or truncated, the panel must say so instead of implying idleness.
   */
  scopeNote?: string | null
  /** §LPSTRIPS — false for a visitor with no account: ALL scope only, the MINE control hidden. */
  mineAvailable?: boolean
  /** §AGORASIM-2 — which folded strip this ledger shows: `main` (every frame the app always streamed) or
   *  `sandbox` (the test frames). The strip's sockets open while this ledger is mounted and close with it. */
  strip?: 'main' | 'sandbox'
}>(), { canOpenForensics: false, mineDids: () => [], scopeNote: null, mineAvailable: true, strip: 'main' })
// Declared below the props on purpose: the strip is a prop, and the handle is this ledger's view of one strip.
const stream = useLedgerStream({ strip: props.strip })

const MAX_ROWS = 14
/** One STEP of history. */
const STEP = 40
/** Hard DOM ceiling — the 866-node lesson, made structural. */
const RENDER_CAP = 300

/**
 * SCOPE — the ledger opens on YOUR traffic, not the whole federation
 * (Commander 2026-08-18: "the live ledger should start filtered with only your
 * and your orgs agents ... because the ledger makes this lag even at moderate
 * ledger events speed").
 *
 * This is a display scope, never a claim about the network: the per-frame chips
 * and the SESSION total above keep counting EVERY event either way, so nothing
 * is hidden by narrowing what the list draws.
 */
const scope = ref<'mine' | 'all'>(props.mineAvailable ? 'mine' : 'all')
const mineSet = computed(() => {
  const s = new Set<string>()
  for (const d of props.mineDids || []) if (d) s.add(String(d).toLowerCase())
  return s
})
/**
 * The accounting-shadow toggle. Persisted: it is a working preference, like the
 * rails, not a boot condition like the AGORA strip.
 */
const showShadow = ref((() => {
  try { return localStorage.getItem('brg.ledger.shadow') === '1' } catch { return false }
})())
const hiddenShadow = ref(0)
function toggleShadow(): void {
  showShadow.value = !showShadow.value
  try { localStorage.setItem('brg.ledger.shadow', showShadow.value ? '1' : '0') } catch { /* private mode */ }
  hiddenShadow.value = 0
  ring.clear()
  ringVersion.value++
  shown.value = MAX_ROWS
  rows.value = []
}

/** Events that matched MINE but are not drawn because the scope is narrow. */
const hiddenByScope = ref(0)

interface Row {
  key: string
  frame: string
  time: string
  type: string
  subject: string
  drawn: boolean
  mine: boolean
  /** The envelope, BY REFERENCE, so left-click can show the raw wire. */
  raw: unknown
}

/**
 * §BRIDGE R11 #4/#8 — the SAME ring the fleet log uses.
 *
 * Before this, `paused` returned at the top of the subscriber: a paused ledger
 * threw its events away, so pausing to read something destroyed the very
 * history you paused to look at. Now intake never stops; only the view freezes.
 */
const ring = createHistoryRing<Row>()
/** Bumped on every ring write so the counters above can be reactive. */
const ringVersion = ref(0)
const rows = ref<Row[]>([])
const paused = ref(false)
const heldBack = ref(0)
const shown = ref(MAX_ROWS)
let seq = 0
let off: (() => void) | null = null

/**
 * Incoming rows are BUFFERED and flushed on a timer, never applied per event.
 * Per-event `unshift` re-rendered the whole list on every delivery — at the
 * sim's rate that is dozens of list re-renders a second, which is the lag the
 * Commander felt. One flush every 400ms costs the same at 2/s and at 900/s.
 */
const FLUSH_MS = 400
let pending: Row[] = []
let flushTimer: ReturnType<typeof setInterval> | null = null

/** Frame chip tint. Gold / silver / emerald — the same territory palette the stage uses. */
const FRAME_CLASS: Record<string, string> = { A: 'blg-fa', B: 'blg-fb', C: 'blg-fc' }
/** §COCKPITDESK (2026-10-14) — a row's frame, short. The legacy keys are one letter (A, B, C) and the row's first column
 *  was sized for one; the frames stood up since carry names ("sandbox-alpha", "eu"), and in a desk tile the name wrapped
 *  over the time beside it (lifecycle 98's photograph of the Incident board). A key of three letters or fewer stays; a
 *  longer one shows its frame's currency (SBXA, ECU), which the chips above already pair with it; the full name rides the
 *  title. */
const frameShort = computed<Record<string, string>>(() => {
  const m: Record<string, string> = {}
  for (const f of stream.frames.value) m[f.key] = f.key.length <= 3 ? f.key : (f.currency || f.key)
  return m
})

function shortDid(v: string): string {
  if (!v) return '-'
  return v.length > 24 ? `${v.slice(0, 12)}...${v.slice(-4)}` : v
}

function clock(ts: string | undefined): string {
  const d = ts ? new Date(ts) : new Date()
  return Number.isNaN(d.getTime())
    ? new Date().toLocaleTimeString('en-GB', { hour12: false })
    : d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

onMounted(() => {
  off = stream.onRaw((frameKey, envelope) => {
    const inner = unwrapEnvelope(envelope)
    const type = inner?.event_type
    if (!type || typeof type !== 'string') return

    const mine = involvesDids(envelope, mineSet.value)
    if (scope.value === 'mine' && !mine) { hiddenByScope.value++; return }

    // THE ACCOUNTING SHADOW.
    //
    // `LedgerBalanceChanged` is the double-entry record of movements that are
    // ALREADY in this list under their own name (TokensTransferred,
    // FxSwapSettled, ...). The stage refuses to draw it for exactly that reason
    // — drawing it would double-count the same money on screen — but the
    // console listed it, and it is the highest-volume type on the network. Once
    // MINE actually worked, the result was a panel where ~70% of the rows were
    // the shadow of the other 30%: technically the whole truth, practically
    // unreadable, and not an answer to "what are my agents doing".
    //
    // So it is a CONTROL, not a silent decision: off by default because the
    // information is already on screen, one click away when you want the raw
    // wire, and counted either way.
    if (!showShadow.value && type === 'LedgerBalanceChanged') { hiddenShadow.value++; return }

    pending.push({
      key: `${frameKey}-${inner.id ?? seq++}-${seq++}`,
      frame: frameKey,
      time: clock(inner.timestamp),
      type,
      subject: shortDid(String(inner.aggregate_id ?? '')),
      // Whether the STAGE draws this one. Silent-by-design rows still appear
      // here: the console is where the whole truth lives.
      drawn: type in VERB_TABLE,
      mine,
      raw: envelope,
    })
    // The buffer only has to survive one flush interval, but it must never grow
    // without bound if a flush is starved (a backgrounded tab does exactly that).
    if (pending.length > RENDER_CAP) pending = pending.slice(-RENDER_CAP)
  })

  flushTimer = setInterval(() => {
    if (pending.length) {
      ring.push(pending)                       // history always fills
      ringVersion.value++                      // ...and the counters can SEE it
      if (paused.value) heldBack.value += pending.length
      pending = []
    }
    if (!paused.value) refreshView()           // only the VIEW freezes
  }, FLUSH_MS)
})

function refreshView(): void {
  rows.value = ring.window(Math.min(shown.value, RENDER_CAP))
}
function togglePause(): void {
  paused.value = !paused.value
  if (!paused.value) { heldBack.value = 0; refreshView() }
}
function older(): void {
  shown.value = Math.min(shown.value + STEP, RENDER_CAP, ring.size())
  refreshView()
}
function backToLive(): void {
  shown.value = MAX_ROWS; paused.value = false; heldBack.value = 0; refreshView()
}
const hasMore = computed(() => ring.size() > rows.value.length && rows.value.length < RENDER_CAP)
const atRenderCap = computed(() => rows.value.length >= RENDER_CAP)
/**
 * ⚠ The ring is a PLAIN OBJECT, so `ring.size()` is invisible to Vue.
 *
 * The R11 battery caught this the moment it existed: with the panel paused,
 * the history counter read `14/0` and never moved, because a computed whose
 * only dependency is a non-reactive call is evaluated once and cached
 * forever. `hasMore` happened to work purely because it ALSO reads `rows`,
 * which is reactive — i.e. it was right by accident, which is the same bug
 * wearing a passing test.
 *
 * One explicit version counter, bumped where the ring is written, is the
 * honest dependency.
 */
const kept = computed(() => (ringVersion.value, ring.size()))
const forgotten = computed(() => (ringVersion.value, ring.dropped()))
const expanded = computed(() => shown.value > MAX_ROWS)

/** §BRIDGE R11 #7/#11 — left-click a row, see the wire it came off. */
const payloadRow = ref<Row | null>(null)
const showPayload = ref(false)
function inspectRow(r: Row): void { payloadRow.value = r; showPayload.value = true }

/** Switching scope re-baselines rather than mixing two populations in one list. */
function setScope(next: 'mine' | 'all'): void {
  if (scope.value === next) return
  scope.value = next
  hiddenShadow.value = 0
  pending = []
  ring.clear()
  ringVersion.value++
  shown.value = MAX_ROWS
  rows.value = []
  hiddenByScope.value = 0
}

onBeforeUnmount(() => {
  off?.()
  if (flushTimer) clearInterval(flushTimer)
})

const silentCount = computed(() => SILENT_BY_DESIGN.size)
const drawnTypeCount = computed(() => Object.keys(VERB_TABLE).length)

function openForensics(): void {
  router.push('/admin/forensics').catch(() => { /* route guard owns the outcome */ })
}
</script>

<template>
  <!-- `data-mine` is the ONE fact that broke when the stage stopped owning
       `setMineDids` (§LITEBRIDGE): with no stage, nothing would have told the
       stream whose events these are, and the MINE filter would have read empty
       on a machine whose only problem was having no GPU. A gate can only catch
       that if the number is on the element; waiting for traffic to prove it is
       the "fails on a quiet network" trap. -->
  <section class="blg" data-tour="bridge-ledger" :data-mine="(mineDids || []).length">
    <BridgePayloadModal :show="showPayload" :envelope="payloadRow?.raw"
                        :title="payloadRow ? `${payloadRow.type} — ${payloadRow.subject}` : null"
                        @close="showPayload = false" />
    <header class="blg-hdr">
      <span class="blg-title">{{ t('bridge.ledger.title', 'LIVE LEDGER') }}</span>
      <div class="blg-hdr-right">
        <button
          type="button" class="blg-btn"
          :aria-pressed="paused"
          data-testid="ledger-pause"
          :title="paused
            ? t('bridge.ledger.resume', 'Resume. Nothing was dropped while paused.')
            : t('bridge.ledger.pause', 'Freeze this list. New events keep landing in the history behind it.')"
          @click="togglePause"
        >
          <Icon :name="paused ? 'mdi:play' : 'mdi:pause'" :size="11" />
        </button>
        <span v-if="paused && heldBack > 0" class="blg-held"
              :title="t('bridge.ledger.heldHelp', 'Arrived while paused. They are in the history, not lost.')">
          +{{ heldBack.toLocaleString(appLocale()) }}
        </span>
        <button v-if="props.canOpenForensics" type="button" class="blg-btn blg-btn-door"
                :title="t('bridge.ledger.forensicsHelp', 'Open Ledger Forensics')"
                @click="openForensics">
          {{ t('bridge.ledger.forensics', 'FORENSICS') }}
          <Icon name="mdi:arrow-top-right" :size="10" />
        </button>
      </div>
    </header>

    <!-- Per-frame chips: exact counts, honest liveness, one row. -->
    <div class="blg-chips">
      <div
        v-for="f in stream.frames.value" :key="f.key"
        class="blg-chip" :class="[FRAME_CLASS[f.key] || '', f.connected ? 'is-live' : f.gaveUp ? 'is-gone' : 'is-down']"
        :title="f.gaveUp
          ? t('bridge.ledger.unreachable', 'Not reachable from this origin')
          : f.connected ? t('bridge.ledger.streaming', 'Streaming') : t('bridge.ledger.reconnecting', 'Reconnecting')"
      >
        <span class="blg-chip-dot"></span>
        <span class="blg-chip-key">{{ f.key }}</span>
        <span class="blg-chip-cur">{{ f.currency }}</span>
        <span class="blg-chip-n">{{ f.eventCount.toLocaleString(appLocale()) }}</span>
      </div>
      <div class="blg-chip blg-chip-total" :title="t('bridge.ledger.totalHelp', 'Exact count of every event received this session, including the ones the stage does not draw')">
        <span class="blg-chip-key">{{ t('bridge.ledger.session', 'SESSION') }}</span>
        <span class="blg-chip-n">{{ stream.totalEvents.value.toLocaleString(appLocale()) }}</span>
      </div>
    </div>

    <!-- Scope. MINE by default; ALL is one click away and says what it costs. -->
    <div v-if="props.mineAvailable" class="blg-scope" role="group" :aria-label="t('bridge.ledger.scopeLabel', 'Ledger scope')">
      <button
        type="button" class="blg-scope-btn" :class="{ 'is-on': scope === 'mine' }"
        :aria-pressed="scope === 'mine'"
        :title="t('bridge.ledger.scopeMineHelp', 'Only events involving your agents. The counts above still include everything.')"
        @click="setScope('mine')"
      >{{ t('bridge.ledger.scopeMine', 'MINE') }}</button>
      <button
        type="button" class="blg-scope-btn" :class="{ 'is-on': scope === 'all' }"
        :aria-pressed="scope === 'all'"
        :title="t('bridge.ledger.scopeAllHelp', 'Every event on every frame. Busy on a live network.')"
        @click="setScope('all')"
      >{{ t('bridge.ledger.scopeAll', 'ALL') }}</button>
      <span v-if="scope === 'mine' && hiddenByScope > 0" class="blg-scope-n"
            :title="t('bridge.ledger.hiddenHelp', 'Counted, not listed, because the scope is MINE')">
        +{{ hiddenByScope.toLocaleString(appLocale()) }}
      </span>
      <button
        type="button" class="blg-scope-btn blg-shadow-btn" :class="{ 'is-on': showShadow }"
        data-testid="ledger-shadow"
        :aria-pressed="showShadow"
        :title="t('bridge.ledger.shadowHelp', 'LedgerBalanceChanged is the double-entry shadow of movements already listed here. Off by default; the counters include it either way.')"
        @click="toggleShadow"
      >{{ t('bridge.ledger.shadow', 'SHADOW') }}</button>
      <span v-if="!showShadow && hiddenShadow > 0" class="blg-scope-n"
            :title="t('bridge.ledger.shadowHidden', 'Accounting-shadow rows counted but not listed')">
        &#8776;{{ hiddenShadow.toLocaleString(appLocale()) }}
      </span>
      <span v-if="scope === 'mine' && scopeNote" class="blg-scope-note"
            :title="t('bridge.ledger.scopeNoteHelp', 'MINE can only be as complete as the list of your agents')">
        {{ scopeNote }}
      </span>
    </div>

    <div class="blg-feed">
      <p v-if="rows.length === 0" class="blg-empty">
        {{ !stream.anyConnected.value
          ? t('bridge.ledger.connecting', 'Connecting')
          : scope === 'mine'
            ? (scopeNote || t('bridge.ledger.awaitingMine', 'Awaiting events involving your agents'))
            : t('bridge.ledger.awaiting', 'Awaiting events') }}
      </p>
      <!-- No TransitionGroup. Each row is keyed and enters with a CSS animation,
           which needs no leave bookkeeping: a leave transition that never fires
           its `transitionend` (a throttled or backgrounded tab does exactly that)
           leaves the element in the DOM forever. Measured before this change:
           866 `.blg-row` nodes alive against a MAX_ROWS of 14, still climbing. -->
      <div v-else>
        <!-- §BRIDGE R11 #7 — a row is a door onto its own payload. -->
        <button v-for="r in rows" :key="r.key" type="button" class="blg-row"
                data-testid="ledger-row"
                :class="{ 'is-silent': !r.drawn, 'is-mine': r.mine }"
                :title="t('bridge.ledger.inspectHelp', 'Show the raw event payload')"
                @click="inspectRow(r)">
          <span class="blg-row-frame" :class="FRAME_CLASS[r.frame] || ''" :title="r.frame">{{ frameShort[r.frame] || r.frame }}</span>
          <span class="blg-row-time">{{ r.time }}</span>
          <span class="blg-row-type" :title="r.type">{{ ledgerEventLabel(r.type) }}</span>
          <span class="blg-row-subject">{{ r.subject }}</span>
        </button>
      </div>
    </div>

    <footer class="blg-foot">
      <button v-if="hasMore" type="button" class="blg-more" data-testid="ledger-older" @click="older">
        {{ t('bridge.ledger.older', 'OLDER') }} +{{ Math.min(40, kept - rows.length) }}
      </button>
      <button v-if="expanded" type="button" class="blg-more" data-testid="ledger-live" @click="backToLive">
        {{ t('bridge.ledger.live', 'BACK TO LIVE') }}
      </button>
      <span class="blg-keep" data-testid="ledger-keep"
            :title="t('bridge.ledger.keepHelp', 'This session only. The ring holds the most recent 2,000 rows in this scope; older ones are discarded, never hidden.')">
        {{ rows.length }}/{{ kept.toLocaleString(appLocale()) }}<template v-if="forgotten > 0"> · {{ forgotten.toLocaleString(appLocale()) }} {{ t('bridge.ledger.aged', 'aged out') }}</template><template v-if="atRenderCap"> · {{ t('bridge.ledger.renderCap', 'render cap') }}</template>
      </span>
      <span class="blg-foot-types"
            :title="t('bridge.ledger.footHelp', 'The stage draws the event types that mean value or work moved. The rest are counted here and never drawn as motion — since R14 they show only as faint background density on the frame that produced them, because drawing the accounting shadow as traffic would count the same money twice.')">
        {{ drawnTypeCount }} {{ t('bridge.ledger.drawn', 'drawn') }} · {{ silentCount }} {{ t('bridge.ledger.counted', 'counted only') }}
      </span>
    </footer>
  </section>
</template>

<style scoped>
.blg {
  /* §COCKPITDESK (2026-10-14, lifecycle 98's axe on the desk's Trading, Analytics, Incident and Build boards): the quiet
     texts read the theme's dim-text token, which NO stylesheet defines, so each fell back to its own grey: #6b7f9e
     (4.35:1 on this panel's #131825), #5f708a (3.52:1), #7c8797, and #8fa3c0 dimmed again by opacity (4.01 and 3.23).
     Two named greys, both above AA's 4.5:1: --blg-dim #8fa3c0 (6.89:1) for controls, --blg-quiet #7d91b0 (5.53:1)
     for what sits beside the data. */
  --blg-dim: #8fa3c0;
  --blg-quiet: #7d91b0;
  /* min-height floor: this panel is a scroll container, and at 0 height it
     clips every row while its header overflows and stays visible. */
  display: flex; flex-direction: column; min-height: 9rem;
  background: rgba(8, 12, 22, 0.72);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 4px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
}
.blg-hdr {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14));
}
.blg-title { font-size: 0.66rem; letter-spacing: 0.18em; color: var(--nc-text, #d6e2f2); }
.blg-hdr-right { display: flex; align-items: center; gap: 0.3rem; }
.blg-btn {
  display: inline-flex; align-items: center; gap: 0.25rem;
  background: transparent; color: var(--blg-dim);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.2));
  border-radius: 3px; padding: 0.15rem 0.35rem; cursor: pointer;
  font-family: inherit; font-size: 0.58rem; letter-spacing: 0.1em;
}
.blg-btn:hover { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.blg-btn:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 1px; }

.blg-chips { display: flex; flex-wrap: wrap; gap: 0.3rem; padding: 0.4rem 0.6rem; }
.blg-chip {
  display: inline-flex; align-items: center; gap: 0.3rem;
  padding: 0.12rem 0.35rem; border-radius: 2px;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  font-size: 0.58rem; letter-spacing: 0.08em; color: var(--blg-dim);
}
.blg-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--blg-quiet); }
.blg-chip.is-live .blg-chip-dot { background: var(--nc-success, #22c55e); box-shadow: 0 0 6px var(--nc-success, #22c55e); }
.blg-chip.is-down .blg-chip-dot { background: var(--nc-warning, #f59e0b); }
.blg-chip.is-gone { opacity: 0.45; }
.blg-chip-key { color: var(--nc-text, #d6e2f2); }
.blg-chip-cur { color: var(--blg-quiet); }
.blg-chip-n { color: var(--nc-primary, #22d3ee); }
.blg-fa .blg-chip-key { color: #ffc14d; }
.blg-fb .blg-chip-key { color: #c9d4e2; }
.blg-fc .blg-chip-key { color: #36d399; }
.blg-chip-total { margin-left: auto; }

/* R15 — a floor in ROWS, not only on the panel. `.blg` already carried a 9rem
   min-height, but the header and footer eat into it: measured 33px of FEED at
   1280x720 once the vitals card grew by two doors and three quick actions,
   which is one row and reads as broken. `min-height: 0` is the flex idiom that
   lets a scroll body shrink — and shrink to nothing is exactly what it did.
   The rail is a scroll container by design, so a squeeze must push the RAIL
   into scrolling rather than boil the feed down to a single line. */
.blg-feed { flex: 1 1 auto; min-height: 6.5rem; overflow-y: auto; padding: 0 0.35rem 0.35rem; }
.blg-empty { padding: 0.9rem 0.3rem; text-align: center; font-size: 0.6rem; letter-spacing: 0.12em; color: var(--blg-quiet); }
.blg-row {
  display: grid; grid-template-columns: 2.4rem 4.4rem 1fr auto;
  gap: 0.35rem; align-items: baseline;
  padding: 0.16rem 0.25rem; border-radius: 2px;
  font-size: 0.6rem; line-height: 1.5;
  /* A row is a button now (R11 #7) — strip the chrome, keep the grid. */
  width: 100%; text-align: left; background: transparent; border: 0;
  font-family: inherit; color: inherit; cursor: pointer;
}
.blg-row:hover { background: rgba(34, 211, 238, 0.08); }
.blg-row:focus-visible { outline: 1px solid var(--nc-primary, #22d3ee); outline-offset: -1px; }
.blg-held { font-size: 0.55rem; letter-spacing: 0.08em; color: var(--nc-primary, #22d3ee); }
.blg-more {
  background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 3px; padding: 0.1rem 0.4rem; margin-right: 0.35rem; cursor: pointer;
  font-family: inherit; font-size: 0.52rem; letter-spacing: 0.1em; color: var(--blg-dim);
}
.blg-more:hover { color: var(--nc-primary, #22d3ee); }
.blg-keep { font-size: 0.5rem; letter-spacing: 0.06em; color: var(--blg-quiet); margin-right: 0.5rem; }
.blg-foot-types { margin-left: auto; }
/* Your own traffic reads first; everything else is present but quiet. */
.blg-row.is-mine { background: rgba(34, 211, 238, 0.07); }
.blg-row.is-silent { opacity: 0.5; }
.blg-row-frame { font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.blg-row-time { color: var(--blg-quiet); }
.blg-row-type { color: var(--nc-text, #d6e2f2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.blg-row-subject { color: var(--blg-quiet); }

.blg-foot {
  padding: 0.3rem 0.6rem; border-top: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14));
  font-size: 0.55rem; letter-spacing: 0.1em; color: var(--blg-quiet);
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.2rem 0;
}
.blg-foot-types { cursor: help; }

/* Enter as an ANIMATION, not a transition: an animation is fire-and-forget, so
   nothing has to observe its end to remove the element. */
.blg-row { animation: blg-in 220ms ease both; }
@keyframes blg-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

.blg-scope {
  display: flex; align-items: center; gap: 0.25rem;
  padding: 0.2rem 0.5rem 0.3rem;
}
.blg-scope-btn {
  padding: 0.08rem 0.34rem; border-radius: 2px; cursor: pointer;
  background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  color: var(--blg-dim);
  font-family: inherit; font-size: 0.52rem; letter-spacing: 0.12em;
}
.blg-scope-btn.is-on { color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee); }
.blg-scope-btn:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 1px; }
.blg-shadow-btn { margin-left: 0.35rem; }
.blg-scope-note {
  margin-left: auto;
  font-size: 0.58rem;
  letter-spacing: 0.04em;
  color: var(--blg-quiet);
  opacity: 0.85;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.blg-scope-n { margin-left: auto; font-size: 0.52rem; color: var(--blg-quiet); cursor: help; }

@media (prefers-reduced-motion: reduce) {
  .blg-row { animation: none; }
}
</style>
