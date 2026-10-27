<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
/**
 * §RAT (P8b) — YOUR AGENTS, on the cockpit board.
 *
 * His ask: the Incident layout shows registry/fleet health; it should also show the
 * agents YOU own, selectable, with live metrics and deployment state.
 *
 * Three design facts that are not decoration:
 *
 *  1. 🔴 THREE DIFFERENT STATES, NEVER MERGED INTO ONE "STATUS" LIGHT.
 *     Enforcement (active|suspended|revoked, written by the enforcement rail — an owner
 *     cannot set it), DEPLOYMENT (the CI/CD record), and TRAFFIC (has anyone called it).
 *     A single green dot that means "fine" would be exactly the §AGENTCOCKPIT failure:
 *     a control or a label asserting something the underlying column does not say.
 *
 *  2. 🔴 A PINNED WATCHLIST, NOT A FIREHOSE. `/developers/me/agents` is page-capped at
 *     200 (max 500) — §AGENTCOCKPIT lost 10 seconds and still could not find the
 *     account's own agent inside that page. So the board shows what you PIN, and finding
 *     something to pin goes through the SERVER's search (`q`), which is not page-bound.
 *     It also bounds the work: detail is fetched per pinned row, not for 200 agents.
 *
 *  3. 🔴 "NO DATA" IS RENDERED AS NO DATA. The metrics rail returns all-zeros for an
 *     agent it has never seen, which is byte-identical to one failing every request.
 *     `neverObserved()` splits them, because "0% success" on an agent nobody has called
 *     is a false accusation.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import Icon from '@/components/Icon.vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { PANES } from './paneRegistry'
import { openDeployment } from '@/services/cockpit/agentDoor'
import { useI18n } from '@/composables/useI18n'
// ⚠ `agentApi`, singular. I imported `agentsApi` by convention rather than reading the
// module — services/api/agents.ts exports `agentApi` (line 399). A guessed import name
// is a build failure, which is the cheap version of this mistake; the expensive version
// is a guessed COLUMN name, which answers 200 and returns nothing (see `status='active'`).
import { agentApi } from '@/services/api/agents'
import { agentOpsApi, neverObserved, type AgentMetrics, type DeploymentRow } from '@/services/api/agentOps'

const props = withDefaults(defineProps<{ pollSeconds?: number; maxPinned?: number }>(), {
  pollSeconds: 30, maxPinned: 8,
})

const { t, tp } = useI18n()
const def = PANES.agentops

const PIN_KEY = 'ckd_agent_pins'
function loadPins(): string[] {
  // ⚠ Read the READER before writing the key (the §BUYSERVICE `gt_dismissed` lesson: a
  // valid-JSON value of the WRONG TYPE sails past a try/catch and throws downstream).
  try {
    const raw = JSON.parse(localStorage.getItem(PIN_KEY) || '[]')
    return Array.isArray(raw) ? raw.filter(x => typeof x === 'string') : []
  } catch { return [] }
}
const pins = ref<string[]>(loadPins())
/** §COCKPITDESK — whether this browser holds a choice at all. An absent key is "never chose" (the board shows the agents
 *  this account owns); a stored [] is "chose an empty board", and stays empty. */
function pinsWereChosen(): boolean { try { return localStorage.getItem(PIN_KEY) !== null } catch { return false } }
const pinsChosen = ref<boolean>(pinsWereChosen())
function persist() { try { localStorage.setItem(PIN_KEY, JSON.stringify(pins.value)) } catch { /* private window */ } }

const mine = ref<any[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
const truncated = ref(false)
const q = ref('')
const searching = ref(false)
const results = ref<any[]>([])
/** §FESUITE (V0577): mFailed / dFailed = that read got no answer this cycle, kept apart from the answer itself. A failed
 *  metrics read was neverObserved(null) = "no traffic recorded", a failed deployments read "no deployment record". */
const detail = ref<Record<string, {
  m: AgentMetrics | null; d: DeploymentRow[] | null; failed: boolean; mFailed: boolean; dFailed: boolean
}>>({})
const selected = ref<string | null>(null)
/** null = nothing selected or not fetched yet; [] = fetched and this registry has none. */
const selectedDeploys = computed<DeploymentRow[] | null>(() => {
  const did = selected.value
  if (!did) return null
  const det = detail.value[did]
  return det ? (det.d || []) : null
})
/** the selected agent's deployments read failed this cycle: not "none recorded" */
const selectedDeploysFailed = computed(() => !!(selected.value && detail.value[selected.value]?.dFailed))

const PAGE = 100

/* 🔴 §COCKPITSHOW A1 — HIS REPORT: *"i hadded hagrid and others to the agents. but the
 * names and status disappear from most. just hagrid stays."*
 *
 * Exactly right, and the cause is the capped-list class one more time. A pinned row was
 * resolved by looking the DID up in `mine` ∪ `results` — a 100-row page of a 4,130-agent
 * account, plus whatever happened to be in the search box. So a pin kept its name only
 * while its agent stayed inside one of those two windows: pin four agents, reload, and
 * three of them fall out and render as `did:theprotocol:…` with status UNKNOWN. Hagrid
 * survived because it happened to sit in the page; SYBIL survived in his first shot only
 * because "Sybil" was still typed in the search box, and lost its name in the second.
 *
 * ⚠ And UNKNOWN was the WORST possible rendering of it: the pane's whole argument is that
 * enforcement, deployment, runtime and traffic are four separate answers, and here three
 * of them read "unknown" for agents whose metrics were on screen in the same row. Not
 * fetched and genuinely unknown must never look the same (§RAT).
 *
 * The cure is the rail that exists for precisely this — `include_dids`, which hydrates
 * named DIDs REGARDLESS of the recency window (§agentfinder). Pins are hydrated by
 * identity, so they no longer depend on where they happen to sort. */
const pinned = ref<Record<string, any>>({})
const pinsFailed = ref(false)
/**
 * 🔴 §COCKPITFRAME F3 — DIDs we have ASKED about and got an answer for.
 *
 * With paging the pin list can hold 200 agents while only a page of them is on screen, so
 * hydration follows the PAGE. That makes "we have not looked yet" a real state for the
 * first time — and the row must not print "could not resolve" about an identity nobody has
 * asked about. That is the §RAT law (not fetched ≠ genuinely unknown) and the §COCKPITFIT
 * `namesReady` rule, arriving here through the pager.
 *
 * ⚠ It is also why hydration is no longer whole-list: §DIDCHUNK refused a 13.8 KB query
 * string outright and it read as "no agents". 200 pins × ~44 chars is ~9 KB of `include_dids`
 * — close enough to that wall to be a real risk, and there is no reason to pay it: a name is
 * only needed for a row on screen.
 */
const askedDids = ref<Set<string>>(new Set())

async function hydratePins() {
  const want = visiblePins.value.filter(Boolean)
  if (!boardPins.value.length) { pinned.value = {}; askedDids.value = new Set(); pinsFailed.value = false; return }
  if (!want.length) return
  try {
    const r: any = await agentApi.getMyAgents({ includeDids: want, limit: 1 })
    const list = Array.isArray(r) ? r : (r?.items || r?.results || [])
    const map: Record<string, any> = { ...pinned.value }
    for (const a of list) { const d = didOf(a); if (d && want.includes(d)) map[d] = a }
    pinned.value = map
    // ⚠ MERGED, not replaced: paging back to page 1 must not make its names disappear and
    // reappear. A stale entry for an unpinned DID is never read — only pins in view are.
    const asked = new Set(askedDids.value); for (const d of want) asked.add(d)
    askedDids.value = asked
    // A pin we asked for and did NOT get back is a different fact from one we never asked
    // about — the row says "could not resolve", never "unknown".
    pinsFailed.value = false
  } catch {
    // ⚠ NOT marked asked: a failed round trip must not turn every row into "could not
    // resolve", which would be a claim about the registry made from a claim about our own
    // request.
    pinsFailed.value = true
  }
}

async function loadMine() {
  try {
    const r: any = await agentApi.getMyAgents({ limit: PAGE, topLevelOnly: true })
    const list = Array.isArray(r) ? r : (r?.items || r?.results || [])
    mine.value = list
    // Say so when the page is full: the list is CAPPED, and a name you cannot see is not
    // a name that does not exist.
    truncated.value = list.length >= PAGE
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
  void hydratePins()
}

async function search() {
  const term = q.value.trim()
  if (term.length < 2) { results.value = []; return }
  searching.value = true
  try {
    const r: any = await agentApi.getMyAgents({ q: term, limit: 20, topLevelOnly: false })
    results.value = Array.isArray(r) ? r : (r?.items || r?.results || [])
  } catch { results.value = [] } finally { searching.value = false }
}

function didOf(a: any): string { return a?.did || a?.agent_did || '' }
function nameOf(a: any): string { return a?.name || a?.agent_name || didOf(a).slice(0, 22) || '—' }

/** One resolved view-model per pinned row.
 *
 *  The template used to reach `detail[didOf(a) || a.did]!.m!.total_requests` in five
 *  places: the same lookup repeated, each with TS non-null assertions inside a template
 *  expression. Deep optional chains in markup are where a rename becomes a blank cell
 *  nobody notices, so the resolution happens ONCE, here, in typed script.
 */
const pinnedAgents = computed(() => {
  const byDid = new Map<string, any>()
  for (const a of [...mine.value, ...results.value]) { const d = didOf(a); if (d) byDid.set(d, a) }
  // Hydrated-by-DID wins over whatever the page or the search box happens to hold.
  for (const [d, a] of Object.entries(pinned.value)) byDid.set(d, a)
  return visiblePins.value.map(did => {
    // 🔴 §COCKPITFIT — `_unresolved` USED TO LIVE ON THIS INNER OBJECT while the template
    // read `r._unresolved` at the TOP level, so it was `undefined` at runtime ALWAYS: the
    // "could not resolve" chip could never render and an unresolvable pin fell to the
    // `v-else` branch, which prints UNKNOWN — the exact half of his report this was written
    // to fix. Caught by the TYPE RATCHET (`Property '_unresolved' does not exist`), not by
    // any battery: the leg asserted `unresolved === 0`, which is true of a chip that cannot
    // exist. A type error on a property a template reads is a dead branch until proven
    // otherwise.
    // Three states, not two: RESOLVED · asked-and-refused · NOT ASKED YET (a page we have
    // not hydrated). Collapsing the last two is how "could not resolve" gets said about an
    // agent nobody looked up.
    const unresolved = !byDid.has(did) && askedDids.value.has(did)
    const identityPending = !byDid.has(did) && !askedDids.value.has(did)
    const a = byDid.get(did) || { did, name: null }
    const det = detail.value[did] || null
    const deploys = det?.d || null
    const latest = deploys && deploys.length ? deploys[0] : null
    const m = det?.m || null
    return {
      did,
      agent: a,
      // On the ROW, where the template reads it, and therefore typed.
      _unresolved: unresolved,
      _identityPending: identityPending,
      name: nameOf(a),
      enforcement: a.status || null,
      // Three separate answers, never folded into one light.
      latest,
      hasDeployRecord: !!latest,
      metrics: m,
      // `pending` = we have not fetched yet; `none` = fetched and there is nothing to show.
      trafficState: !det ? 'pending' : det.mFailed ? 'unread' : (neverObserved(m) ? 'none' : 'known'),
      // §FESUITE (V0577): the deployments read failed, so no claim either way about a record
      deployUnread: !!det?.dFailed,
      // §COCKPITA R2 — RUNTIME, the fourth answer. Two independent directions, and their
      // DISAGREEMENT is itself informative: an agent that calls us but does not answer has
      // a working outbound and a broken inbound, which no single light can say.
      runtime: runtimeOf(a),
    }
  })
})

/** How old is a timestamp, in seconds? `null` when there is none to age. */
function ageSec(iso?: string | null): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.round((Date.now() - t) / 1000))
}

/** RUNTIME: is this agent up, and how do we know?
 *
 * 🔴 A VERDICT WITH NO AGE IS A FOSSIL. `agents.last_health` has carried a word since
 * migration 0055 with nothing recording when it was written, and on registry-a six of the
 * eleven running agents read `unreachable`/`unhealthy` while answering 200 on their public
 * subdomains — because the checker selected on a card field the A2A cards do not have and
 * so could never rewrite them. Mig 0168 adds `last_health_at`; anything older than
 * STALE_AFTER is reported as STALE, never as current.
 *
 * The push direction (`last_active_at`, written when the agent calls US with its own JWT)
 * needs no probe and is the stronger signal when it is fresh, so it wins.
 */
const STALE_AFTER = 30 * 60      // 30 min: six missed 5-minute cycles
const ACTIVE_WITHIN = 15 * 60    // an agent that called us this recently is up, whatever a probe says
function runtimeOf(a: any): { state: 'up' | 'down' | 'stale' | 'unknown'; how: string; ageSec: number | null } {
  const actAge = ageSec(a?.last_active_at)
  if (actAge !== null && actAge <= ACTIVE_WITHIN) {
    return { state: 'up', how: 'called the registry', ageSec: actAge }
  }
  const probeAge = ageSec(a?.last_health_at)
  const verdict = a?.last_health || null
  if (verdict && probeAge !== null && probeAge <= STALE_AFTER) {
    return { state: verdict === 'healthy' ? 'up' : 'down', how: 'probed', ageSec: probeAge }
  }
  if (verdict && probeAge === null) {
    // A word with no timestamp at all: pre-0168 data. Say STALE, never repeat the word.
    return { state: 'stale', how: 'probe result predates timestamping', ageSec: null }
  }
  if (verdict) return { state: 'stale', how: 'probed', ageSec: probeAge }
  return { state: 'unknown', how: 'never probed and no recent call', ageSec: actAge }
}

function runtimeTone(st: string): string {
  if (st === 'up') return 'is-ok'
  if (st === 'down') return 'is-bad'
  if (st === 'stale') return 'is-warn'
  return 'is-dim'
}

/**
 * 🔴 §COCKPITTILES T1 — HIS REPORT: *"the agent pipeline/activity thing caps out so i cant
 * fill up to the maximum row tile height."* `maxPinned` was a constant 8, so a three-unit
 * tile showed eight rows and then whitespace. The cap now follows the tile.
 *
 * ⚠ It stays a CAP, and a hard one (24): every pinned agent costs TWO reads per poll cycle
 * (metrics + deployments), so this number is a request budget, not only a layout number.
 * The fan-out that §TROPHYALIAS turned into 89,576 requests is exactly what the bound is
 * for — filling a tile must not quietly become a fleet sweep.
 */
/**
 * 🔴 §COCKPITFRAME F3 (2026-09-01) — HIS REPORT: *"the limit should be lifted on it and make
 * have pages. and also its height change shoudl also allow more agents to be shown on one
 * page."*
 *
 * The height half was already true (§COCKPITTILES wired `useFillCount` here); 24 was the
 * wall he was hitting, and there was no paging at all.
 *
 * 🔴 THE OLD NUMBER WAS NOT A LAYOUT NUMBER, WHICH IS WHY LIFTING IT NAIVELY IS THE WRONG
 * FIX. `refreshDetail()` issues TWO reads per row per 30-second cycle (metrics +
 * deployments), so a cap on rows was a cap on requests. Raising it to "unbounded" is
 * §TROPHYALIAS again — one page that became 89,576 requests.
 *
 * So the two things are DECOUPLED:
 *   • PINS are a stored list. Cheap. Bounded only against a hand-edited localStorage.
 *   • A PAGE is what is FETCHED. `refreshDetail` iterates the visible page ONLY, so the
 *     per-cycle budget is `2 × pageSize` and never grows with the pin list.
 *   • PAGE SIZE IS `fitRows`, so his second sentence holds by construction: a taller tile
 *     is a bigger page — more agents on one page AND more fetched, still bounded.
 *
 * ⚠ The pager states what is on screen against what is pinned (`13–24 of 57`). A list that
 * silently stops is the trap `useFillCount`'s own docstring warns about.
 */
const MAX_PINS = 200
/**
 * §COCKPITDESK (2026-10-14) — NOTHING PINNED IS NOT "NO AGENTS". Pins live in this browser, so a new device, a new account
 * or a cleared site store opened this pane on "No agents on the board yet" while Agents alive, one tile away, listed the
 * very agent (lifecycle 98's photograph: a member with one agent, and the door test found no agent to open). With no pins,
 * the board shows the agents this account owns (the page `loadMine` already reads, newest first) and NEVER stores them;
 * the first add or removal copies what is shown into the person's own list and changes that. The request budget is the
 * same page-bounded one: detail is fetched for the visible page only.
 */
const implicit = computed(() => !pinsChosen.value && pins.value.length === 0 && mine.value.length > 0)
const boardPins = computed<string[]>(() => implicit.value
  ? mine.value.map(didOf).filter(Boolean).slice(0, MAX_PINS)
  : pins.value)
/** The per-cycle request budget, in rows. A page can never exceed it however tall the tile. */
const HARD_PAGE_CAP = 24
const ratEl = ref<HTMLElement | null>(null)
/** ⚠ `reservePx` re-measured for the SHELL. Since F1 this pane lives inside
 *  `.ckd-pane-body`, which `useFillCount` resolves to — a box that already excludes the
 *  pane header and its padding. The old 156 was calibrated against the whole slot and would
 *  now subtract that chrome twice. What is left to reserve is what shares the BODY with the
 *  list: the find row, the capped note, and the pager. */
const { count: fitRows } = useFillCount(ratEl, { rowPx: 56, min: 4, max: HARD_PAGE_CAP, reservePx: 118 })
const pageSize = computed(() => Math.min(HARD_PAGE_CAP, Math.max(props.maxPinned, fitRows.value)))
const page = ref(0)
const pageCount = computed(() => Math.max(1, Math.ceil(boardPins.value.length / pageSize.value)))
const pageStart = computed(() => page.value * pageSize.value)
/** The rows this render fetches for and shows. Everything downstream reads THIS, not `pins`. */
const visiblePins = computed(() => boardPins.value.slice(pageStart.value, pageStart.value + pageSize.value))
/** Human 1-based bounds for the pager sentence. */
const pageFrom = computed(() => (boardPins.value.length ? pageStart.value + 1 : 0))
const pageTo = computed(() => Math.min(boardPins.value.length, pageStart.value + pageSize.value))

/** ⚠ A page that stops existing must not leave the board on it. Shrinking the tile or
 *  unpinning the last row of the last page both do that, and the symptom is an empty pane
 *  that still says it has pins. */
watch(pageCount, n => { if (page.value >= n) page.value = Math.max(0, n - 1) })
/** A NEW page is a different set of rows: both their DETAIL and their NAMES have to follow
 *  it, and neither may wait for the 30-second cycle to catch up. */
watch([page, pageSize], () => { void refreshDetail(); void hydratePins() })

function goPage(d: -1 | 1) {
  page.value = Math.min(pageCount.value - 1, Math.max(0, page.value + d))
}

function isPinned(did: string) { return boardPins.value.includes(did) }
function togglePin(did: string) {
  if (!did) return
  // The first gesture on the implicit board makes it the person's own list, starting from what they see.
  if (implicit.value) pins.value = [...boardPins.value]
  pinsChosen.value = true
  if (isPinned(did)) pins.value = pins.value.filter(x => x !== did)
  else if (pins.value.length < MAX_PINS) {
    pins.value = [...pins.value, did]
    // Show what was just added. Pinning a 57th agent while looking at page 1 would
    // otherwise appear to do nothing at all — the honest feedback IS landing on its page.
    page.value = Math.max(0, Math.ceil(pins.value.length / pageSize.value) - 1)
  }
  persist()
  void refreshDetail()
  // ⚠ Hydrate on PIN, not only on load: an agent added from a search result would
  // otherwise keep its name only until the search box was cleared — which is precisely
  // the bug this fixes, arriving one interaction later.
  void hydratePins()
}

async function refreshDetail() {
  // Bounded BY CONSTRUCTION: only the rows ON SCREEN. §COCKPITFRAME F3 — this is the whole
  // reason paging is the right answer to "lift the limit": the pin list may now be 200
  // long and the work per cycle is still `2 × pageSize`. A pane that fanned out over the
  // whole fleet is how §TROPHYALIAS turned one page into 89,576 requests.
  for (const did of visiblePins.value) {
    try {
      let mFailed = false
      let dFailed = false
      const [m, d] = await Promise.all([
        agentOpsApi.metrics(did).catch(() => { mFailed = true; return null }),
        agentOpsApi.deployments(did, 5).catch(() => { dFailed = true; return null }),
      ])
      detail.value = { ...detail.value, [did]: { m, d, failed: mFailed && dFailed, mFailed, dFailed } }
    } catch {
      detail.value = { ...detail.value, [did]: { m: null, d: null, failed: true, mFailed: true, dFailed: true } }
    }
  }
}

function deployTone(s?: string | null): string {
  if (s === 'running' || s === 'pending') return 'is-live'
  if (s === 'success') return 'is-ok'
  if (s === 'failed') return 'is-bad'
  if (s === 'cancelled') return 'is-dim'
  return 'is-dim'
}
function enforcementTone(s?: string | null): string {
  if (s === 'active') return 'is-ok'
  if (s === 'suspended') return 'is-warn'
  if (s === 'revoked') return 'is-bad'
  return 'is-dim'
}
function ago(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

let poll: ReturnType<typeof setInterval> | null = null
onMounted(async () => {
  await loadMine()
  await refreshDetail()
  poll = setJitteredInterval(refreshDetail, Math.max(10, props.pollSeconds) * 1000)
})
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

defineExpose({ reload: async () => { await loadMine(); await refreshDetail() } })
</script>

<template>
  <!-- §COCKPITPOLISH P6 — `data-empty` so the enclosing GRID SLOT can stop spending two
       columns on a pane holding one sentence. This is the pane in his screenshot: the
       large void at the top of the board. ⚠ It does NOT use `PaneShell`, so the rule
       added there could never match it — a fix aimed at the wrong pane looks identical to
       a fix that did not work, right up until you read the screenshot. -->
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :read-at="readAt" :reload="loadMine">
  <div class="rat" data-testid="rat-root" data-tour="cockpit-agents" ref="ratEl"
       :data-fit="fitRows" :data-page-size="pageSize" :data-page="page"
       :data-pins="boardPins.length" :data-pages="pageCount" :data-implicit="implicit ? '1' : '0'"
       :data-empty="(!loading && boardPins.length === 0) ? '1' : '0'">
    <p v-if="loading" class="rat-note">{{ t('cockpit.rat.loading', 'Reading your agents…') }}</p>
    <p v-else-if="err" class="rat-note rat-err" data-testid="rat-error">{{ err }}</p>

    <template v-else>
      <!-- PINNED BOARD — the "editable list" -->
      <ul v-if="pinnedAgents.length" class="rat-list" data-testid="rat-pinned">
        <li v-for="r in pinnedAgents" :key="r.did"
            class="rat-row" :class="{ 'is-sel': selected === r.did }"
            data-testid="rat-row"
            @click="selected = selected === r.did ? null : r.did">
          <!-- §COCKPITFRAME F5 — the identity opens `AgentDetailModal`, which already
               existed and which nothing on this desk reached. ⚠ The ROW keeps its own
               click (it reveals this agent's deployments below), so the link stops the
               event; an UNRESOLVED name renders as plain text and lets the row through,
               because a door to a card the registry would not return is a dead end. -->
          <AgentLink class="rat-name" data-testid="rat-name"
                     :class="{ 'is-unresolved': r._unresolved }"
                     :did="r.did" :label="r.name" :unresolved="r._unresolved || r._identityPending" />

          <!-- 1. ENFORCEMENT — labelled, and named as not-yours-to-set.
               ⚠ A row we could not RESOLVE says so, instead of claiming the agent's
               enforcement state is "unknown". Those are different facts: one is about our
               lookup, the other would be about the registry, and rendering them the same
               is what put UNKNOWN beside a live request count in his screenshot. -->
          <span v-if="r._identityPending" class="rat-chip is-none" data-testid="rat-identity-pending"
                :title="t('cockpit.rat.pendingHint', 'This row is on a page we have not looked up yet. It is not a claim about the agent.')">
            {{ t('cockpit.rat.resolving', 'resolving…') }}
          </span>
          <span v-else-if="r._unresolved" class="rat-chip is-none" data-testid="rat-unresolved"
                :title="t('cockpit.rat.unresolvedHint', 'This registry did not return this agent when we asked for it by DID. Its metrics below are still real — only the identity lookup failed.')">
            {{ t('cockpit.rat.unresolved', 'could not resolve') }}
          </span>
          <span v-else class="rat-chip" :class="enforcementTone(r.enforcement)" data-testid="rat-enforcement"
                :title="t('cockpit.rat.enforcementHint', 'Enforcement state, set by the registry. Not a deployment state and not something you set here.')">
            {{ r.enforcement || t('cockpit.rat.unknown', 'unknown') }}
          </span>

          <!-- 2. DEPLOYMENT — or the honest absence of any record -->
          <span v-if="r.latest" class="rat-chip" :class="deployTone(r.latest.status)" data-testid="rat-deploy">
            <span v-if="r.latest.status === 'running' || r.latest.status === 'pending'"
                  class="rat-pulse" data-testid="rat-pulse" />
            {{ r.latest.status }}<template v-if="r.latest.version"> · {{ r.latest.version }}</template>
          </span>
          <span v-else-if="r.deployUnread" class="rat-chip is-none" data-testid="rat-deploy-unread"
                :title="t('cockpit.rat.deployUnreadHint', 'This agent’s deployment record could not be read just now. It is not a claim that there is none.')">
            {{ t('cockpit.rat.deployUnread', 'deployments unread') }}
          </span>
          <span v-else class="rat-chip is-none" data-testid="rat-deploy-none"
                :title="t('cockpit.rat.noDeployHint', 'This registry holds no CI/CD deployment record for this agent. That is not the same as the agent not running.')">
            {{ t('cockpit.rat.noDeploy', 'no deployment record') }}
          </span>

          <!-- 3. RUNTIME — "is it up right now", which neither of the two above answers -->
          <span class="rat-chip" :class="runtimeTone(r.runtime.state)" data-testid="rat-runtime"
                :title="t('cockpit.rat.runtimeHint', 'Is the agent up right now. Two directions: it called us, or we probed it. An old probe is reported as stale, never as current.') + ' — ' + r.runtime.how">
            {{ r.runtime.state }}<template v-if="r.runtime.ageSec !== null"> · {{ ago(new Date(Date.now() - r.runtime.ageSec * 1000).toISOString()) }}</template>
          </span>

          <!-- 4. TRAFFIC — never-observed is NOT zero-percent -->
          <span v-if="r.trafficState === 'none'" class="rat-traffic is-none" data-testid="rat-no-traffic"
                :title="t('cockpit.rat.noTrafficHint', 'No request has ever been recorded for this agent. Showing 0% success would accuse a healthy agent of failing.')">
            {{ t('cockpit.rat.noTraffic', 'no traffic recorded') }}
          </span>
          <span v-else-if="r.trafficState === 'unread'" class="rat-traffic is-none" data-testid="rat-traffic-unread"
                :title="t('cockpit.rat.trafficUnreadHint', 'This agent’s traffic could not be read just now. It is not a claim that nothing called it.')">
            {{ t('cockpit.rat.trafficUnread', 'traffic unread') }}
          </span>
          <span v-else-if="r.trafficState === 'known' && r.metrics" class="rat-traffic" data-testid="rat-traffic">
            <b>{{ r.metrics.total_requests }}</b> {{ t('cockpit.rat.reqs', 'reqs') }}
            · {{ r.metrics.success_rate }}%
            · {{ ago(r.metrics.last_active) }}
          </span>
          <span v-else class="rat-traffic is-none" data-testid="rat-traffic-pending">…</span>

          <button class="rat-pin" data-testid="rat-unpin"
                  :aria-label="t('cockpit.rat.unpin', 'Remove from board')"
                  @click.stop="togglePin(r.did)">
            <Icon name="mdi:close" class="rat-pin-icon" />
          </button>
        </li>
      </ul>
      <p v-else class="rat-note" data-testid="rat-empty">
        {{ t('cockpit.rat.empty', 'No agents on the board yet. Search below and add the ones you want to watch.') }}
      </p>
      <p v-if="implicit" class="rat-note" data-testid="rat-implicit">
        {{ t('cockpit.rat.implicit', 'Showing the agents you own, newest first. Add or remove one to make this board your own.') }}
      </p>

      <!-- §COCKPITFRAME F3 — the pager appears only when there is something to page, and it
           states what is ON SCREEN against what is PINNED. A list that quietly stops at the
           bottom of a tile is the failure this replaces. -->
      <div v-if="boardPins.length > pageSize" class="rat-pager" data-testid="rat-pager">
        <button class="rat-btn" data-testid="rat-page-prev" :disabled="page <= 0"
                :aria-label="t('cockpit.rat.prevPage', 'Previous page')"
                @click="goPage(-1)"><Icon name="mdi:chevron-left" /></button>
        <span class="rat-page-of" data-testid="rat-page-label"
              :title="t('cockpit.rat.pageHint', 'A page is what this pane fetches — two reads per row, every cycle — so the page is the budget. Make the tile taller for a bigger page.')">
          {{ tp('cockpit.rat.pageOf', '{a}–{b} of {n}', { a: pageFrom, b: pageTo, n: boardPins.length }) }}
        </span>
        <button class="rat-btn" data-testid="rat-page-next" :disabled="page >= pageCount - 1"
                :aria-label="t('cockpit.rat.nextPage', 'Next page')"
                @click="goPage(1)"><Icon name="mdi:chevron-right" /></button>
      </div>

      <!-- SELECTED DETAIL — recent deployments for the chosen agent -->
      <!-- Renders the moment a row is selected, with THREE states inside: still reading,
           nothing recorded, or the list. Keying the whole panel on data-arrived meant a
           click landing before the fetch resolved rendered nothing at all — a race that
           reads as "selection is broken" rather than "the answer has not come back". -->
      <div v-if="selected" class="rat-detail" data-testid="rat-detail">
        <span class="rat-detail-h">{{ t('cockpit.rat.recent', 'Recent deployments') }}</span>
        <p v-if="selectedDeploys === null" class="rat-note" data-testid="rat-detail-pending">
          {{ t('cockpit.rat.loading', 'Reading your agents…') }}
        </p>
        <ReadFailedNotice v-else-if="selectedDeploysFailed" dense :retry="refreshDetail" data-testid="rat-detail-failed" />
        <ul v-else-if="selectedDeploys.length" class="rat-deploys">
          <!-- §COCKPITFRAME F5 — these rows rendered a deployment and led nowhere, while
               `cicd/DeploymentLogsModal` has taken exactly `{ deployment, agentDid }`
               since it shipped. The whole row is the target here (it holds no other
               control), and the desk owns the dialog. -->
          <li v-for="d in selectedDeploys" :key="String(d.id)" class="rat-deploy-row">
            <button class="rat-deploy-open" type="button" data-testid="rat-deploy-row"
                    :title="t('cockpit.rat.logs', 'Open this deployment’s log')"
                    @click="openDeployment(selected, d)">
              <span class="rat-chip" :class="deployTone(d.status)">{{ d.status }}</span>
              <span class="rat-deploy-env">{{ d.environment || '—' }}</span>
              <span class="rat-deploy-ver">{{ d.version || '—' }}</span>
              <span class="rat-deploy-when">{{ ago(d.started_at) }}</span>
            </button>
          </li>
        </ul>
        <p v-else class="rat-note" data-testid="rat-detail-none">
          {{ t('cockpit.rat.noDeployRecords', 'No deployments have been recorded through this registry for this agent.') }}
        </p>
      </div>

      <!-- SEARCH — the SERVER's, because the list above is page-capped -->
      <div class="rat-find">
        <input v-model="q" class="rat-find-in" data-testid="rat-search"
               :placeholder="t('cockpit.rat.find', 'Find an agent by name or DID…')"
               @keyup.enter="search" />
        <button class="rat-btn" data-testid="rat-search-go" :disabled="searching" @click="search">
          {{ t('cockpit.rat.search', 'Search') }}
        </button>
      </div>
      <p v-if="truncated" class="rat-note rat-cap" data-testid="rat-capped">
        {{ t('cockpit.rat.capped', 'Your agent list is page-capped here. Use search to reach one that is not shown.') }}
      </p>
      <p v-if="pins.length >= MAX_PINS" class="rat-note rat-cap" data-testid="rat-pin-cap">
        {{ tp('cockpit.rat.pinCapped', 'The board holds {n} agents — the most it stores. Remove one to add another.', { n: MAX_PINS }) }}
      </p>
      <ul v-if="results.length" class="rat-results" data-testid="rat-results">
        <li v-for="r in results" :key="didOf(r)" class="rat-result">
          <span class="rat-name">{{ nameOf(r) }}</span>
          <span class="rat-did">{{ didOf(r).slice(0, 28) }}…</span>
          <button class="rat-btn" data-testid="rat-pin-add"
                  :disabled="isPinned(didOf(r)) || pins.length >= MAX_PINS"
                  @click="togglePin(didOf(r))">
            {{ isPinned(didOf(r)) ? t('cockpit.rat.pinned', 'On board') : t('cockpit.rat.pin', 'Add') }}
          </button>
        </li>
      </ul>
    </template>
  </div>
  </PaneShell>
</template>

<style scoped>
.rat { display: flex; flex-direction: column; gap: .4rem; }
.rat-note { margin: 0; font-size: .68rem; color: var(--nc-text-dim, #8b949e); }
.rat-err { color: var(--nc-danger, #f85149); }
.rat-cap { color: var(--nc-warning, #d29922); }
.rat-list, .rat-results, .rat-deploys { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .2rem; }
.rat-row { display: flex; align-items: center; gap: .4rem; padding: .25rem .3rem; border-radius: 5px; cursor: pointer; border: 1px solid transparent; }
.rat-row:hover { background: rgba(255,255,255,.03); }
.rat-row.is-sel { border-color: rgba(var(--nc-primary-rgb, 0,229,255), .35); background: rgba(var(--nc-primary-rgb, 0,229,255), .05); }
.rat-name.is-unresolved { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-muted, #6e7681); }
.rat-name { flex: 1; font-size: .72rem; font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rat-did { font-size: .62rem; color: var(--nc-text-dim, #8b949e); font-family: var(--nc-font-mono, ui-monospace, monospace); }
.rat-chip { display: inline-flex; align-items: center; gap: .22rem; font-size: .58rem; letter-spacing: .04em; text-transform: uppercase; padding: .05rem .3rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.14); color: var(--nc-text-dim, #8b949e); white-space: nowrap; }
.rat-chip.is-ok { color: var(--nc-success, #3fb950); border-color: rgba(63,185,80,.4); }
.rat-chip.is-bad { color: var(--nc-danger, #f85149); border-color: rgba(248,81,73,.4); }
.rat-chip.is-warn { color: var(--nc-warning, #d29922); border-color: rgba(210,153,34,.4); }
.rat-chip.is-live { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb, 0,229,255),.5); }
.rat-chip.is-dim, .rat-chip.is-none { border-style: dashed; }
/* The one moving thing on this pane, and only while a deployment is genuinely in flight. */
.rat-pulse { width: 5px; height: 5px; border-radius: 50%; background: currentColor; animation: rat-blink 1.1s ease-in-out infinite; }
@keyframes rat-blink { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .rat-pulse { animation: none; opacity: .85; } }
.rat-traffic { font-size: .64rem; color: var(--nc-text-secondary, #c9d1d9); font-family: var(--nc-font-mono, ui-monospace, monospace); white-space: nowrap; }
.rat-traffic.is-none { color: var(--nc-text-dim, #8b949e); font-style: italic; }
.rat-pin { background: none; border: 0; cursor: pointer; color: var(--nc-text-dim, #8b949e); padding: 0 .1rem; display: flex; }
.rat-pin:hover { color: var(--nc-danger, #f85149); }
.rat-pin-icon { font-size: .8rem; }
.rat-detail { border-top: 1px dashed rgba(255,255,255,.1); padding-top: .35rem; display: flex; flex-direction: column; gap: .2rem; }
.rat-detail-h { font-size: .6rem; letter-spacing: .05em; text-transform: uppercase; color: var(--nc-text-dim, #8b949e); }
.rat-deploy-row { display: flex; align-items: center; gap: .4rem; font-size: .64rem; color: var(--nc-text-secondary, #c9d1d9); }
.rat-deploy-env, .rat-deploy-ver, .rat-deploy-when { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-dim, #8b949e); }
.rat-deploy-env { flex: 1; }
.rat-find { display: flex; gap: .3rem; }
.rat-find-in { flex: 1; min-width: 0; background: rgba(0,0,0,.25); border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.12)); border-radius: 5px; color: var(--nc-text-primary, #e6edf3); font-size: .68rem; padding: .2rem .35rem; }
.rat-btn { background: rgba(255,255,255,.05); border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.14)); border-radius: 5px; color: var(--nc-text-secondary, #c9d1d9); font-size: .64rem; padding: .15rem .45rem; cursor: pointer; }
.rat-btn:disabled { opacity: .45; cursor: default; }
.rat-result { display: flex; align-items: center; gap: .4rem; font-size: .68rem; }
.rat-pager { display: flex; align-items: center; justify-content: center; gap: .4rem; padding-top: .1rem; }
.rat-page-of { font-size: .62rem; color: var(--nc-text-dim, #8b949e);
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums; }
.rat-pager .rat-btn { display: flex; align-items: center; padding: .1rem .3rem; }
.rat-pager .rat-btn :deep(svg) { width: 12px; height: 12px; }
/* The deployment row IS the button — a target inside a target is the §COCKPITPOLISH
   freshness-chip defect, so the row holds no other control. */
.rat-deploy-open { display: flex; align-items: center; gap: .4rem; width: 100%; text-align: left;
  background: none; border: 0; padding: .1rem .15rem; border-radius: 4px; cursor: pointer; color: inherit; }
.rat-deploy-open:hover, .rat-deploy-open:focus-visible { background: rgba(255,255,255,.05); }
</style>
