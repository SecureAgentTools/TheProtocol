<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgeFleetLog.vue — §BRIDGE #B9
 *
 * "What are MY agents doing", in sentences.
 *
 * Every line here is one real ledger event that involved one of the viewer's
 * agents, rendered through `describeVerb()` — the same descriptor the stage drew
 * as a comet. Click a line and it opens the thing it is about; this view adds no
 * detail surface of its own, it is a set of doors into what already exists.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import AgentDetailModal from '@/components/AgentDetailModal.vue'
import BridgePayloadModal from '@/components/bridge/BridgePayloadModal.vue'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { describeVerb, type VerbDescriptor } from '@/services/bridge/grammar'
import { usePrivacy } from '@/composables/usePrivacy'
import { classifyIdentity, firstOpenable } from '@/services/bridge/identity'
import { createHistoryRing } from '@/services/bridge/historyRing'

const { t } = useI18n()
const { hidden: privacyHidden } = usePrivacy()
/* R16.3 — re-render the sentence from the DESCRIPTOR while hiding, instead of
 * trusting `l.text`, which was built when the row arrived. The rows are capped
 * at a dozen, so recomputing the visible ones costs nothing and the switch
 * takes effect on rows that are already on screen. */
function lineText(l: any): string {
  return privacyHidden.value ? describeVerb(l.d, nameFor, { hideAmounts: true }) : l.text
}
const stream = useLedgerStream()

const props = withDefaults(defineProps<{
  /** The DID currently followed, so the row can show it. */
  following?: string | null
  /** did -> human name, so the log says "Caspian Manifest Services", not hex. */
  agentNames?: Record<string, string>
  /** When the viewer owns nothing yet, the log explains itself instead of sitting blank. */
  hasFleet?: boolean
  /** The SELECTED agent — what the quick actions act on. §BRIDGE R9. */
  selected?: string | null
}>(), { agentNames: () => ({}), hasFleet: true, selected: null })

/** Rows rendered at rest. Anything past this is HISTORY, one click away. */
const MAX_LINES = 14
/** How many older rows one STEP reveals. */
const STEP = 40
/** Hard DOM ceiling. §BRIDGE P2 measured 866 nodes against a cap of 14 when a
 *  transition leaked; history must never be able to recreate that. */
const RENDER_CAP = 300

interface Line {
  key: string
  time: string
  text: string
  verb: string
  /** Openable DID, or null. Only this may become a door or a money target. */
  did: string | null
  /** What the row is ABOUT when there is no openable DID (a UUID, a system
   *  account) — shown as text so the row still names its party honestly. */
  refLabel: string | null
  fresh: boolean
  /** The descriptor this row was rendered from, so the raw wire is one click
   *  away (§BRIDGE R11 #7). A reference, not a copy. */
  d: VerbDescriptor
}

/**
 * §BRIDGE R11 #4/#8 — HISTORY + PAUSE, sharing the ledger's mechanism.
 *
 * The ring keeps up to 2,000 rows in MEMORY; the list renders a WINDOW. PAUSE
 * freezes the window, never the ring — a paused log that dropped events would
 * be destroying the very history it was asked to keep.
 */
const ring = createHistoryRing<Line>()
/** Bumped on every ring write so the counters above can be reactive. */
const ringVersion = ref(0)
const lines = ref<Line[]>([])
const paused = ref(false)
/** Rows that landed in the ring while the view was frozen. */
const heldBack = ref(0)
const shown = ref(MAX_LINES)
let off: (() => void) | null = null
let pendingBatch: Line[] = []
let flushTimer: ReturnType<typeof setInterval> | null = null
const FLUSH_MS = 400

function nameFor(did: string | null): string | null {
  if (!did) return null
  return props.agentNames[did] || props.agentNames[did.toLowerCase()] || null
}

function timeOf(d: VerbDescriptor): string {
  return new Date(d.tsMs).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function refreshView(): void {
  lines.value = ring.window(Math.min(shown.value, RENDER_CAP))
}

onMounted(() => {
  off = stream.onVerbs((batch) => {
    for (const d of batch) {
      if (!d.mine) continue
      const line: Line = {
        key: d.id,
        time: timeOf(d),
        text: describeVerb(d, nameFor),
        verb: d.verb,
        // A DID, or nothing. Several event payloads identify the actor by UUID
        // (`agent_id`, and `from`/`principal` on some types) — perfectly good for
        // deciding whether a row is MINE, useless as a DID. Handing one onward as
        // if it were a DID is what put "Agent card not found: 8a3d57d7-…" on the
        // screen, and would have pointed a treasury payment at an identifier the
        // treasury cannot resolve.
        did: firstOpenable(d.actorDid, d.fromDid, d.toDid),
        refLabel: (() => {
          // §BRIDGE R9 — a row with no openable DID is not anonymous: it usually
          // has a system account or an internal id behind it. Name it as TEXT.
          if (firstOpenable(d.actorDid, d.fromDid, d.toDid)) return null
          for (const raw of [d.actorRef, d.fromDid, d.toDid]) {
            const id = classifyIdentity(raw)
            if (id.kind === 'system' || id.kind === 'uuid') return id.label
          }
          return null
        })(),
        fresh: true,
        d,
      }
      pendingBatch.push(line)
      setTimeout(() => { line.fresh = false }, 1600)
    }
  })

  // ONE render per flush, never one per event — the same buffering the ledger
  // learned to need at the sim's rate.
  flushTimer = setInterval(() => {
    if (pendingBatch.length) {
      ring.push(pendingBatch)
      ringVersion.value++
      if (paused.value) heldBack.value += pendingBatch.length
      pendingBatch = []
    }
    if (!paused.value) refreshView()
  }, FLUSH_MS)
})

onBeforeUnmount(() => {
  off?.()
  if (flushTimer) clearInterval(flushTimer)
})

function togglePause(): void {
  paused.value = !paused.value
  if (!paused.value) { heldBack.value = 0; refreshView() }
}

/** Reveal older rows. Bounded by RENDER_CAP so the DOM cannot run away. */
function older(): void {
  shown.value = Math.min(shown.value + STEP, RENDER_CAP, ring.size())
  refreshView()
}
function backToLive(): void {
  shown.value = MAX_LINES
  paused.value = false
  heldBack.value = 0
  refreshView()
}
const hasMore = computed(() => ring.size() > lines.value.length && lines.value.length < RENDER_CAP)
const atRenderCap = computed(() => lines.value.length >= RENDER_CAP)
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
const expanded = computed(() => shown.value > MAX_LINES)

const empty = computed(() => lines.value.length === 0)

const emit = defineEmits<{
  /** LEFT-CLICK a row = SELECT that agent. §BRIDGE R9: this is the primary
   *  gesture. It used to open a card, and targeting was hidden behind a 10px
   *  glyph — so the Commander clicked rows, nothing was targeted, and FUND/SEND
   *  stayed disabled saying "follow an agent to target it". Measured, twice:
   *  the target line did not change on click. */
  (e: 'select', did: string): void
  (e: 'follow', did: string): void
}>()

function isSelected(did: string | null): boolean {
  return !!did && !!props.selected && props.selected.toLowerCase() === did.toLowerCase()
}

/**
 * §BRIDGE R8 — this used to `router.push('/my-agents')`, which is the one thing
 * the Commander said the bridge should stop doing: *"instead of routing to the
 * pages, make the most important actions quick actionable from this view."*
 * Leaving the bridge to look at a row you are already looking at also costs the
 * live stream — you come back to a stage that has to warm up again.
 *
 * BridgeTerminal already opens AgentDetailModal for exactly this, so this does
 * too: one behaviour asked in both places (§FANOUTFIX), no second surface.
 */
const openDid = ref('')
const showAgent = ref(false)
function openAgent(did: string | null): void {
  if (!did) return
  openDid.value = did
  showAgent.value = true
}

/**
 * §BRIDGE R11 #7 — THE GESTURES SWAP, on his instruction:
 *   *"right clicking an agent should select him for the quick actions"* and
 *   *"left clicking it should pop up the json payload to inspect"*.
 *
 * A right-click is not reachable on a trackpad tap or a touchscreen, so SELECT
 * also keeps an explicit control (the ⊕ button). A gesture the hardware cannot
 * perform is not an interface.
 */
const payloadLine = ref<Line | null>(null)
const showPayload = ref(false)
function inspect(l: Line): void {
  payloadLine.value = l
  showPayload.value = true
}
function selectFromRow(l: Line): void {
  if (l.did) emit('select', l.did)
}
</script>

<template>
  <section class="bfl" data-tour="bridge-fleet-log">
    <AgentDetailModal v-if="showAgent" v-model:show="showAgent" :agent-did="openDid" />
    <BridgePayloadModal :show="showPayload" :descriptor="payloadLine?.d || null"
                        :title="payloadLine?.text || null" @close="showPayload = false" />
    <header class="bfl-hdr">
      <span class="bfl-title">{{ t('bridge.fleetLog.title', 'FLEET LOG') }}</span>
      <div class="bfl-hdr-r">
        <span v-if="paused && heldBack > 0" class="bfl-held"
              :title="t('bridge.fleetLog.heldHelp', 'Arrived while paused. They are in the history, not lost.')">
          +{{ heldBack.toLocaleString(appLocale()) }}
        </span>
        <span v-else class="bfl-sub">{{ t('bridge.fleetLog.sub', 'your agents, live') }}</span>
        <!-- PAUSE freezes the VIEW. The ring keeps filling behind it. -->
        <button type="button" class="bfl-btn" data-testid="fleetlog-pause"
                :aria-pressed="paused"
                :title="paused
                  ? t('bridge.fleetLog.resume', 'Resume. Nothing was dropped while paused.')
                  : t('bridge.fleetLog.pause', 'Freeze this list. New events keep landing in the history behind it.')"
                @click="togglePause">
          <Icon :name="paused ? 'mdi:play' : 'mdi:pause'" :size="11" />
        </button>
      </div>
    </header>

    <div class="bfl-body">
      <p v-if="empty && !props.hasFleet" class="bfl-empty">
        {{ t('bridge.fleetLog.noFleet', 'No agents yet. Create one and this log fills with its real activity.') }}
      </p>
      <p v-else-if="empty" class="bfl-empty">
        {{ t('bridge.fleetLog.quiet', 'Your agents have not moved yet. Nothing is invented here, so this stays empty until they do.') }}
      </p>
      <TransitionGroup v-else name="bfl-line" tag="ul" class="bfl-list">
        <li v-for="l in lines" :key="l.key" class="bfl-line"
            :class="[`bfl-v-${l.verb}`, { 'is-fresh': l.fresh, 'is-selected': isSelected(l.did) }]">
          <!-- LEFT-CLICK = SELECT (§BRIDGE R9). The obvious gesture now does the
               obvious thing: it targets the quick actions and asks the stage to
               follow. Rows with no openable DID (a frame crossing has no single
               actor; a system account is not an agent) stay TEXT — a door onto a
               wall is worse than no door — but they still name their party. -->
          <button type="button" class="bfl-line-btn"
                  :aria-pressed="isSelected(l.did)"
                  data-testid="fleet-inspect"
                  :title="t('bridge.fleetLog.inspectHelp', 'Open the raw event payload. Right-click (or the target button) selects this agent instead.')"
                  @click="inspect(l)"
                  @contextmenu.prevent="selectFromRow(l)">
            <span class="bfl-line-mark"></span>
            <span class="bfl-line-text">{{ lineText(l) }}</span>
            <span v-if="!l.did && l.refLabel" class="bfl-line-ref">{{ l.refLabel }}</span>
            <span class="bfl-line-time">{{ l.time }}</span>
          </button>
          <!-- SELECT gets an explicit control as well as the right-click: a
               trackpad tap and a touchscreen have no right button, and a gesture
               the hardware cannot perform is not an interface. -->
          <button v-if="l.did" type="button" class="bfl-target"
                  :class="{ 'is-on': isSelected(l.did) }"
                  :aria-pressed="isSelected(l.did)"
                  data-testid="fleet-select"
                  :title="t('bridge.fleetLog.selectHelp', 'Select this agent — the quick actions will act on it')"
                  @click.stop="emit('select', l.did)">&#8853;</button>
          <!-- The agent CARD keeps its own control, so both are reachable and
               neither is a surprise. It moved off the row body because the row
               body is now selection. -->
          <button
            v-if="l.did" type="button" class="bfl-card"
            data-testid="fleet-card"
            :title="t('bridge.fleetLog.cardHelp', 'Open this agent\'s card')"
            @click.stop="openAgent(l.did)"
          >&#9432;</button>
          <!-- #B13 FOLLOW: pin the camera. Selecting already asks for this; the
               control stays so the camera can be released without dropping the
               selection (they are different questions — R9). -->
          <button
            v-if="l.did" type="button" class="bfl-follow"
            :class="{ 'is-on': following && l.did && following.toLowerCase() === l.did.toLowerCase() }"
            data-testid="fleet-follow"
            :title="t('bridge.fleetLog.followHelp', 'Pin the camera to this agent. Move the view, or press Esc, to release it.')"
            @click.stop="emit('follow', l.did)"
          >&#9678;</button>
        </li>
      </TransitionGroup>
    </div>

    <footer class="bfl-foot">
      <!-- HISTORY. The ring is memory, the list is a window, and the footer says
           what is kept and what has aged out — a capped history presented as a
           complete one is the lie this project keeps refusing to tell. -->
      <button v-if="hasMore" type="button" class="bfl-more" data-testid="fleetlog-older" @click="older">
        {{ t('bridge.fleetLog.older', 'OLDER') }} +{{ Math.min(40, kept - lines.length) }}
      </button>
      <button v-if="expanded" type="button" class="bfl-more" data-testid="fleetlog-live" @click="backToLive">
        {{ t('bridge.fleetLog.live', 'BACK TO LIVE') }}
      </button>
      <span class="bfl-keep" data-testid="fleetlog-keep"
            :title="t('bridge.fleetLog.keepHelp', 'This session only. The ring holds the most recent 2,000 of your agents\' events; older ones are discarded, never hidden.')">
        {{ lines.length }}/{{ kept.toLocaleString(appLocale()) }}<template v-if="forgotten > 0"> · {{ forgotten.toLocaleString(appLocale()) }} {{ t('bridge.fleetLog.aged', 'aged out') }}</template><template v-if="atRenderCap"> · {{ t('bridge.fleetLog.renderCap', 'render cap') }}</template>
      </span>
      <router-link to="/my-agents" class="bfl-door">
        {{ t('bridge.fleetLog.allAgents', 'ALL AGENTS') }}
        <Icon name="mdi:arrow-right" :size="10" />
      </router-link>
    </footer>
  </section>
</template>

<style scoped>
.bfl-line-btn--flat { cursor: default; }
.bfl {
  /* min-height floor - see BridgeLedger: a 0-height scroll body clips its
     content and leaves a floating header. */
  display: flex; flex-direction: column; min-height: 9rem;
  background: rgba(8, 12, 22, 0.72);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 4px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
}
.bfl-hdr {
  display: flex; align-items: baseline; justify-content: space-between;
  padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14));
}
.bfl-title { font-size: 0.66rem; letter-spacing: 0.18em; color: var(--nc-text, #d6e2f2); }
.bfl-sub { font-size: 0.55rem; letter-spacing: 0.1em; color: var(--nc-text-dim, #6b7f9e); }
.bfl-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 0.35rem; }
.bfl-empty { padding: 0.8rem 0.4rem; font-size: 0.6rem; line-height: 1.6; color: var(--nc-text-dim, #6b7f9e); }
.bfl-list { list-style: none; margin: 0; padding: 0; }
.bfl-line { margin: 0 0 0.1rem; }
.bfl-line-btn {
  display: grid; grid-template-columns: 4px 1fr auto; gap: 0.4rem; align-items: baseline;
  width: 100%; text-align: left; background: transparent; border: 0; cursor: pointer;
  padding: 0.22rem 0.3rem; border-radius: 2px;
  font-family: inherit; font-size: 0.62rem; line-height: 1.45; color: var(--nc-text, #d6e2f2);
}
.bfl-line-btn:hover { background: rgba(34, 211, 238, 0.08); }
.bfl-line-btn:focus-visible { outline: 2px solid var(--nc-primary, #22d3ee); outline-offset: 1px; }
.bfl-line.is-fresh .bfl-line-btn { background: rgba(34, 211, 238, 0.12); }
.bfl-line-mark { width: 3px; align-self: stretch; border-radius: 2px; background: var(--nc-primary, #22d3ee); }
.bfl-v-guild .bfl-line-mark { background: #64ffda; }
.bfl-v-fx .bfl-line-mark { background: #ffc14d; }
.bfl-v-trade .bfl-line-mark { background: #b388ff; }
.bfl-v-birth .bfl-line-mark { background: #ffffff; }
.bfl-v-treasury .bfl-line-mark { background: #82b1ff; }
.bfl-v-alarm .bfl-line-mark { background: var(--nc-danger, #ff5252); }
.bfl-line-text { overflow: hidden; text-overflow: ellipsis; }
.bfl-line-time { color: var(--nc-text-dim, #6b7f9e); font-size: 0.55rem; }
.bfl-line.is-selected { background: color-mix(in srgb, var(--brand-primary, #4dd8e6) 14%, transparent); }
.bfl-line.is-selected .bfl-line-mark { background: var(--brand-primary, #4dd8e6); box-shadow: 0 0 6px var(--brand-primary, #4dd8e6); }
.bfl-line-ref { opacity: .55; font-size: 9px; letter-spacing: .04em; margin-left: .35rem; white-space: nowrap; }
.bfl-card {
  flex: 0 0 auto; background: none; border: 0; cursor: pointer; padding: 0 2px;
  color: var(--text-tertiary, #7a8a9a); font-size: 11px; line-height: 1; opacity: .45;
  transition: opacity .15s ease, color .15s ease;
}
.bfl-card:hover, .bfl-card:focus-visible { opacity: 1; color: var(--brand-primary, #4dd8e6); }
.bfl-follow {
  flex: 0 0 auto; margin-left: 0.2rem; padding: 0 0.25rem;
  background: transparent; border: 0; cursor: pointer;
  color: var(--nc-text-dim, #5f708a); font-size: 0.7rem; line-height: 1;
  opacity: 0.45;
}
.bfl-follow:hover { opacity: 1; color: var(--nc-primary, #22d3ee); }
.bfl-follow.is-on { opacity: 1; color: var(--nc-primary, #22d3ee); }
.bfl-line { display: flex; align-items: center; }

.bfl-hdr-r { display: inline-flex; align-items: center; gap: 0.4rem; }
.bfl-btn { background: transparent; border: 0; cursor: pointer; padding: 0 0.15rem; line-height: 1;
  color: var(--nc-text-dim, #6b7f9e); opacity: 0.7; }
.bfl-btn:hover, .bfl-btn[aria-pressed="true"] { opacity: 1; color: var(--nc-primary, #22d3ee); }
.bfl-held { font-size: 0.55rem; letter-spacing: 0.08em; color: var(--nc-primary, #22d3ee); }
/**
 * ⊕ SELECT — the control that exists BECAUSE a trackpad has no right button.
 *
 * Polish pass 3 measured its hit target at 11x11. An 11px target is a pixel
 * hunt on a mouse and unusable on a touchscreen, which makes it a poor
 * substitute for the gesture it was added to replace. The GLYPH stays small
 * (this is quiet chrome on a dense row); the HIT AREA is what grows.
 */
.bfl-target, .bfl-card, .bfl-follow {
  min-width: 20px; min-height: 20px;
  display: inline-flex; align-items: center; justify-content: center;
}
.bfl-target {
  flex: 0 0 auto; background: none; border: 0; cursor: pointer; padding: 0 2px;
  color: var(--text-tertiary, #7a8a9a); font-size: 11px; line-height: 1; opacity: .45;
  transition: opacity .15s ease, color .15s ease;
}
.bfl-target:hover, .bfl-target:focus-visible { opacity: 1; color: var(--brand-primary, #4dd8e6); }
.bfl-target.is-on { opacity: 1; color: var(--brand-primary, #4dd8e6); }
.bfl-more {
  background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 3px; padding: 0.1rem 0.4rem; margin-right: 0.35rem; cursor: pointer;
  font-family: inherit; font-size: 0.52rem; letter-spacing: 0.1em; color: var(--nc-text-dim, #8fa3c0);
}
.bfl-more:hover { color: var(--nc-primary, #22d3ee); }
.bfl-keep { font-size: 0.5rem; letter-spacing: 0.06em; color: var(--nc-text-dim, #5f708a); margin-right: 0.5rem; }
.bfl-foot { padding: 0.3rem 0.6rem; border-top: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14));
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.2rem 0; }
.bfl-door {
  display: inline-flex; align-items: center; gap: 0.25rem;
  font-size: 0.56rem; letter-spacing: 0.12em; color: var(--nc-text-dim, #8fa3c0); text-decoration: none;
}
.bfl-door:hover { color: var(--nc-primary, #22d3ee); }

.bfl-line-enter-active { transition: opacity 260ms ease, transform 260ms ease; }
.bfl-line-enter-from { opacity: 0; transform: translateX(-6px); }
@media (prefers-reduced-motion: reduce) { .bfl-line-enter-active { transition: none; } }
</style>
