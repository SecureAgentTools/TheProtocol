<!-- IRONKEY L4 — Sub-agent lineage tree (§SUBAGENT-LIABILITY "hands, not persons").
     Read-only oversight: who spawned this agent (born_from) + every HAND it has
     spawned, nested client-side from parent_did→hand_did with `generation` as the
     indent depth. The tree can be very large (real data: 3179 gen-1 hands), so each
     parent renders at most PER_PARENT_CAP children with a "+N more" reveal — we never
     mount thousands of DOM nodes at once.
     Props: agentDid, mode (owner|admin|readonly). Sibling of AgentAccessPanel; shares
     its visual language. -->
<template>
  <div class="alt">
    <!-- header: counts + refresh -->
    <div class="alt-head">
      <div class="alt-head-l">
        <span class="alt-title">{{ t('agentLineage.title', 'Sub-agent lineage') }}</span>
        <span v-if="lineage" class="alt-mode" :class="'alt-mode--' + modeClass"
              :title="t('agentLineage.modeTip', 'Authorization mode') + ': ' + lineage.mode">{{ lineage.mode }}</span>
      </div>
      <div class="alt-head-r">
        <span v-if="lineage" class="alt-counts">
          <span class="alt-c"><b>{{ counts.total }}</b> {{ t('agentLineage.hands', 'hands') }}</span>
          <span class="alt-c alt-c--ok"><b>{{ counts.alive }}</b> {{ t('agentLineage.alive', 'alive') }}</span>
          <span class="alt-c alt-c--anchor"><b>{{ counts.anchored }}</b> {{ t('agentLineage.anchored', 'anchored') }}</span>
          <span class="alt-c"><b>{{ counts.generations }}</b> {{ t('agentLineage.generations', 'gen') }}</span>
          <span v-if="counts.foreign" class="alt-c alt-c--xf"><b>{{ counts.foreign }}</b> {{ t('agentLineage.crossFrameShort', 'cross-frame') }}</span>
        </span>
        <button class="alt-refresh" :disabled="loading"
                :aria-label="t('agentLineage.refresh', 'Refresh lineage')" @click="load">
          <Icon name="mdi:refresh" :class="loading ? 'alt-spin' : ''" />
        </button>
      </div>
    </div>

    <!-- states -->
    <div v-if="loading && !lineage" class="alt-skel">{{ t('agentLineage.loading', 'Loading lineage…') }}</div>
    <div v-else-if="forbidden" class="alt-forbidden">
      <Icon name="mdi:lock" class="alt-forbidden-ic" />
      <span>{{ t('agentLineage.forbidden', 'You do not have access to this agent’s lineage.') }}</span>
    </div>
    <div v-else-if="error" class="alt-error" role="alert">
      <span>{{ error }}</span>
      <button class="alt-btn" @click="load">{{ t('agentLineage.retry', 'Retry') }}</button>
    </div>

    <template v-else-if="lineage">
      <!-- born_from -->
      <div v-if="lineage.born_from" class="alt-born">
        <span class="alt-born-lab">{{ t('agentLineage.spawnedBy', 'Spawned by') }}</span>
        <button class="alt-did" :title="lineage.born_from.parent_did"
                :aria-label="t('agentLineage.copyDid', 'Copy DID') + ': ' + lineage.born_from.parent_did"
                @click="copy(lineage.born_from.parent_did)">
          <Icon name="mdi:content-copy" class="alt-copyico" />
          <span>{{ shortDid(lineage.born_from.parent_did) }}</span>
          <span v-if="copiedDid === lineage.born_from.parent_did" class="alt-copied" role="status" aria-live="polite">{{ t('agentLineage.copied', 'copied') }}</span>
        </button>
        <button class="alt-open" :title="t('agentLineage.viewAgent', 'View agent page')"
                :aria-label="t('agentLineage.viewAgent', 'View agent page') + ': ' + lineage.born_from.parent_did"
                @click="viewAgent(lineage.born_from.parent_did)">
          <Icon name="mdi:open-in-new" />
        </button>
        <span v-if="lineage.born_from.anchored" class="alt-badge alt-badge--anchor">
          <Icon name="mdi:shield-account" /> {{ t('agentLineage.anchoredTag', 'anchored') }}
        </span>
        <span class="alt-status" :class="'alt-status--' + toneOf(lineage.born_from.status)">{{ lineage.born_from.status }}</span>
        <span v-if="lineage.born_from.expires_at" class="alt-decay"
              :class="{ 'alt-decay--past': isPast(lineage.born_from.expires_at), 'alt-decay--soon': isSoon(lineage.born_from.expires_at) }">
          {{ expiryLabel(lineage.born_from.expires_at) }}
        </span>
      </div>

      <!-- empty -->
      <div v-if="!lineage.hands.length && !foreignHands.length" class="alt-empty">{{ t('agentLineage.empty', 'No sub-agents spawned') }}</div>

      <!-- tree (flattened for capping; `gen` drives the indent). role=group (NOT tree:
           the capped/flattened rows don't honour treeitem semantics) + a scroll region. -->
      <div v-else class="alt-tree" role="group" :aria-label="t('agentLineage.treeLabel', 'Spawned sub-agents')">
        <template v-for="row in visibleRows" :key="row.key">
          <!-- hand node -->
          <div v-if="row.hand" class="alt-node"
               :class="[row.hand.anchored ? 'alt-node--anchor' : 'alt-node--sub',
                        { 'alt-node--dim': !row.hand.alive, 'alt-node--orphan': row.orphan }]"
               :style="indentStyle(row.gen)">
            <div class="alt-node-main">
              <span v-if="row.gen > 1" class="alt-branch" aria-hidden="true">↳</span>
              <button class="alt-did" :title="row.hand.hand_did"
                      :aria-label="t('agentLineage.copyDid', 'Copy DID') + ': ' + row.hand.hand_did"
                      @click="copy(row.hand.hand_did)">
                <Icon name="mdi:content-copy" class="alt-copyico" />
                <span>{{ shortDid(row.hand.hand_did) }}</span>
                <span v-if="copiedDid === row.hand.hand_did" class="alt-copied" role="status" aria-live="polite">{{ t('agentLineage.copied', 'copied') }}</span>
              </button>
              <button class="alt-open" :title="t('agentLineage.viewAgent', 'View agent page')"
                      :aria-label="t('agentLineage.viewAgent', 'View agent page') + ': ' + row.hand.hand_did"
                      @click="viewAgent(row.hand.hand_did)">
                <Icon name="mdi:open-in-new" />
              </button>
              <span class="alt-badge" :class="row.hand.anchored ? 'alt-badge--anchor' : 'alt-badge--sub'">
                <Icon :name="row.hand.anchored ? 'mdi:shield-account' : 'mdi:robot-outline'" />
                {{ row.hand.anchored ? t('agentLineage.anchoredHand', 'anchored hand') : t('agentLineage.subAgent', 'sub-agent') }}
              </span>
              <span class="alt-status" :class="'alt-status--' + toneOf(row.hand.status, row.hand.alive)">{{ row.hand.status }}</span>
              <span v-if="row.hand.no_redelegate" class="alt-tag"
                    :title="t('agentLineage.noRedelegateHint', 'This hand may not delegate any further')">
                {{ t('agentLineage.noRedelegate', 'no re-delegate') }}
              </span>
            </div>
            <div class="alt-node-sub">
              <span class="alt-meta">{{ usesLabel(row.hand) }}</span>
              <span v-if="row.hand.budget_remaining != null" class="alt-meta">
                {{ row.hand.budget_remaining }}<template v-if="row.hand.currency"> {{ row.hand.currency }}</template> {{ t('agentLineage.left', 'left') }}
              </span>
              <span class="alt-decay" :class="{ 'alt-decay--past': isPast(row.hand.expires_at), 'alt-decay--soon': isSoon(row.hand.expires_at) }">{{ expiryLabel(row.hand.expires_at) }}</span>
              <span class="alt-caps-lab">{{ t('agentLineage.canPrefix', 'can:') }}</span>
              <template v-if="row.hand.permissions && row.hand.permissions.length">
                <span v-for="p in row.hand.permissions" :key="p" class="alt-perm">{{ p }}</span>
              </template>
              <span v-else class="alt-meta alt-caps-none">{{ t('agentLineage.noCaps', 'none') }}</span>
            </div>
          </div>

          <!-- "+N more" reveal for a capped parent -->
          <button v-else-if="row.more" class="alt-more" :style="indentStyle(row.gen)"
                  :aria-label="t('agentLineage.showMore', 'Show more sub-agents')"
                  @click="expand(row.more.parentDid)">
            + {{ row.more.hidden }} {{ t('agentLineage.more', 'more') }}
          </button>
        </template>
      </div>

      <!-- cross-frame delegations (foreign hands) — a bounded slice of this agent's
           authority extended to an agent on a PEER frame; opened cross-origin. -->
      <div v-if="foreignHands.length" class="alt-xf">
        <div class="alt-xf-head">
          <Icon name="mdi:transit-connection-variant" class="alt-xf-ic" />
          <span class="alt-xf-title">{{ t('agentLineage.crossFrame', 'Cross-frame delegations') }}</span>
          <span class="alt-xf-count">{{ foreignHands.length }}</span>
        </div>
        <div class="alt-xf-list">
          <div v-for="f in foreignHands" :key="f.credential_id" class="alt-node alt-node--xf"
               :class="{ 'alt-node--dim': ['revoked','expired','ship_failed'].includes(f.status) }">
            <div class="alt-node-main">
              <span class="alt-badge alt-badge--xf" :title="f.home_registry || ''">
                <Icon name="mdi:earth" /> {{ f.home_frame || t('agentLineage.foreignFrame', 'peer frame') }}
              </span>
              <button class="alt-did" :title="f.delegate_did"
                      :aria-label="t('agentLineage.copyDid', 'Copy DID') + ': ' + f.delegate_did"
                      @click="copy(f.delegate_did)">
                <Icon name="mdi:content-copy" class="alt-copyico" />
                <span>{{ shortDid(f.delegate_did) }}</span>
                <span v-if="copiedDid === f.delegate_did" class="alt-copied" role="status" aria-live="polite">{{ t('agentLineage.copied', 'copied') }}</span>
              </button>
              <button v-if="f.home_ui_url" class="alt-open" :title="t('agentLineage.openPeer', 'Open on its home frame (new tab)')"
                      :aria-label="t('agentLineage.openPeer', 'Open on its home frame') + ': ' + f.delegate_did"
                      @click="openForeign(f.home_ui_url)">
                <Icon name="mdi:open-in-new" />
              </button>
              <span class="alt-status" :class="'alt-status--' + xfTone(f.status)">{{ f.status }}</span>
              <span v-if="!f.live" class="alt-tag"
                    :title="t('agentLineage.declaredHint', 'Declared from this frame’s audit trail; the peer’s live status was not reachable')">
                {{ t('agentLineage.declared', 'declared') }}
              </span>
            </div>
            <div class="alt-node-sub">
              <span class="alt-decay" :class="{ 'alt-decay--past': isPast(f.expires_at), 'alt-decay--soon': isSoon(f.expires_at) }">{{ expiryLabel(f.expires_at) }}</span>
              <span v-if="f.caveats && f.caveats.max_per_tx" class="alt-meta">
                ≤ {{ f.caveats.max_per_tx }}<template v-if="f.caveats.allowed_currencies"> {{ (f.caveats.allowed_currencies || []).join('/') }}</template> {{ t('agentLineage.perTx', '/ tx') }}
              </span>
              <span class="alt-caps-lab">{{ t('agentLineage.canPrefix', 'can:') }}</span>
              <template v-if="f.permissions && f.permissions.length">
                <span v-for="p in f.permissions" :key="p" class="alt-perm">{{ p }}</span>
              </template>
              <span v-else class="alt-meta alt-caps-none">{{ t('agentLineage.noCaps', 'none') }}</span>
            </div>
          </div>
        </div>
        <p class="alt-xf-note">{{ t('agentLineage.crossFrameNote', 'These agents live on another frame and act with a bounded slice of this agent’s authority. Opening one leaves this registry.') }}</p>
      </div>

      <p v-if="lineage.note" class="alt-note">{{ lineage.note }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import { agentDelegationApi, type AgentLineage, type LineageHand, type ForeignHand } from '@/services/api/agentDelegation'

const { t } = useI18n()
const router = useRouter()

const props = withDefaults(defineProps<{
  agentDid: string
  mode?: 'owner' | 'admin' | 'readonly'
}>(), { mode: 'owner' })

// A flattened, capped view row: either a hand node or a "+N more" affordance.
interface LineageRow {
  key: string
  gen: number
  hand: LineageHand | null
  orphan: boolean
  more: { parentDid: string; hidden: number } | null
}

const PER_PARENT_CAP = 200

const loading = ref(false)
const error = ref<string | null>(null)
const forbidden = ref(false)   // 403 → a friendly restricted state (no pointless Retry)
const lineage = ref<AgentLineage | null>(null)
const copiedDid = ref<string | null>(null)
// parents the user has chosen to fully expand past the per-parent cap
const expanded = ref<Set<string>>(new Set())

const counts = computed(() => lineage.value?.counts ?? { total: 0, alive: 0, anchored: 0, generations: 0, foreign: 0 })
// Cross-frame delegations ("foreign hands") — agents on peer frames that act with a
// bounded slice of this agent's authority. Rendered as their own section (not the
// local spawn tree) because they live on another registry.
const foreignHands = computed<ForeignHand[]>(() => lineage.value?.foreign_hands ?? [])

// Opening a foreign hand LEAVES this registry — it is homed on a peer frame, so we
// open its own UI cross-origin in a new tab (never router.push, which would 404 here).
function openForeign(url: string | null) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}
function xfTone(status: string): 'ok' | 'bad' | 'warn' | 'muted' {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'ok'
  if (s === 'revoked' || s === 'ship_failed') return 'bad'
  if (s === 'expired') return 'warn'
  return 'muted'   // 'delegated' = declared from local audit, not peer-confirmed
}
const modeClass = computed(() => {
  const m = (lineage.value?.mode || 'off').toLowerCase()
  return m === 'enforce' ? 'enforce' : m === 'shadow' ? 'shadow' : 'off'
})

const childrenByParent = computed(() => {
  const map = new Map<string, LineageHand[]>()
  for (const h of lineage.value?.hands ?? []) {
    const arr = map.get(h.parent_did)
    if (arr) arr.push(h)
    else map.set(h.parent_did, [h])
  }
  for (const arr of map.values()) {
    arr.sort((a, b) => (a.generation - b.generation) || (a.token_id - b.token_id))
  }
  return map
})
const handDids = computed(() => new Set((lineage.value?.hands ?? []).map(h => h.hand_did)))

// DFS pre-order flatten, capping each parent's children and (never silently
// dropping a hand) surfacing detached subtrees whose parent is not in view.
const visibleRows = computed<LineageRow[]>(() => {
  const l = lineage.value
  if (!l) return []
  const byParent = childrenByParent.value
  const known = handDids.value
  const rows: LineageRow[] = []
  const seen = new Set<number>()

  const walk = (parentDid: string) => {
    const kids = byParent.get(parentDid)
    if (!kids || !kids.length) return
    const limit = expanded.value.has(parentDid) ? kids.length : Math.min(kids.length, PER_PARENT_CAP)
    for (let i = 0; i < limit; i++) {
      const h = kids[i]
      if (seen.has(h.token_id)) continue // cycle / duplicate guard
      seen.add(h.token_id)
      rows.push({ key: 'h' + h.token_id, gen: h.generation, hand: h, orphan: false, more: null })
      walk(h.hand_did)
    }
    if (limit < kids.length) {
      rows.push({
        key: 'm' + parentDid,
        gen: kids[limit]?.generation ?? 1,
        hand: null,
        orphan: false,
        more: { parentDid, hidden: kids.length - limit },
      })
    }
  }

  walk(l.agent_did)

  // detached hands (parent not in the returned set) — kept as extra roots so
  // the rendered rows always reconcile with counts.total
  for (const h of l.hands) {
    if (seen.has(h.token_id)) continue
    if (h.parent_did === l.agent_did) continue
    if (known.has(h.parent_did)) continue // hidden behind a "+N more", not detached
    seen.add(h.token_id)
    rows.push({ key: 'h' + h.token_id, gen: h.generation, hand: h, orphan: true, more: null })
    walk(h.hand_did)
  }
  return rows
})

function expand(parentDid: string) {
  const next = new Set(expanded.value)
  next.add(parentDid)
  expanded.value = next
}

function shortDid(did: string): string {
  if (!did) return ''
  if (did.length <= 28) return did
  return did.slice(0, 16) + '…' + did.slice(-6)
}

async function copy(did: string) {
  try {
    await navigator.clipboard?.writeText(did)
    copiedDid.value = did
    window.setTimeout(() => { if (copiedDid.value === did) copiedDid.value = null }, 1200)
  } catch { /* clipboard unavailable (insecure context) — silent no-op */ }
}

// Open a DID's own agent page — the parent that spawned this agent (born_from)
// or one of the spawned hands. Copy stays untouched; this is a second affordance.
function viewAgent(did: string) {
  if (!did) return
  router.push({ name: 'agent-details', params: { agentId: did } })
}

function toneOf(status: string, alive?: boolean): 'ok' | 'bad' | 'warn' | 'muted' {
  if (alive) return 'ok'
  const s = (status || '').toLowerCase()
  if (s === 'active' || s === 'issued' || s === 'alive') return 'ok'
  if (s === 'revoked') return 'bad'
  if (s === 'exhausted') return 'warn'
  return 'muted'
}

function usesLabel(h: LineageHand): string {
  const left = h.uses_left == null ? '∞' : String(h.uses_left)
  const max = h.max_uses == null ? '∞' : String(h.max_uses)
  return `${left}/${max} ${t('agentLineage.uses', 'uses')}`
}

function isPast(iso: string | null): boolean {
  if (!iso) return false
  const ts = new Date(iso).getTime()
  return !Number.isNaN(ts) && ts < Date.now()
}

// Expiring within 24h but not yet past → amber "decay" cue, so a hand about to
// lapse reads before it flips to the red expired state.
function isSoon(iso: string | null): boolean {
  if (!iso) return false
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return false
  const diff = ts - Date.now()
  return diff > 0 && diff < 86_400_000
}

function relTime(iso: string): string {
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return ''
  const diff = ts - Date.now()
  const abs = Math.abs(diff)
  const min = 60_000, hour = 3_600_000, day = 86_400_000
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (abs < hour) return rtf.format(Math.round(diff / min), 'minute')
  if (abs < day) return rtf.format(Math.round(diff / hour), 'hour')
  if (abs < 30 * day) return rtf.format(Math.round(diff / day), 'day')
  if (abs < 365 * day) return rtf.format(Math.round(diff / (30 * day)), 'month')
  return rtf.format(Math.round(diff / (365 * day)), 'year')
}

function expiryLabel(iso: string | null): string {
  if (!iso) return t('agentLineage.noExpiry', 'no expiry')
  const rel = relTime(iso)
  if (!rel) return t('agentLineage.noExpiry', 'no expiry')
  return isPast(iso)
    ? `${t('agentLineage.expired', 'expired')} ${rel}`
    : `${t('agentLineage.expires', 'expires')} ${rel}`
}

// Indent by generation, but CAP the depth so a deep chain (maxGen=8) can never
// squeeze the row content or push horizontal scroll onto the page on a narrow
// panel. Past the cap, rows share the deepest indent — the ↳ glyph + row order
// still convey descent. Step is gentle (.9rem) for the same reason.
const MAX_INDENT_LEVELS = 6
function indentStyle(gen: number) {
  const level = Math.min(Math.max(0, gen - 1), MAX_INDENT_LEVELS)
  return { paddingLeft: (0.55 + level * 0.9) + 'rem' }
}

async function load() {
  loading.value = true
  error.value = null
  forbidden.value = false
  try {
    lineage.value = await agentDelegationApi.getLineage(props.agentDid)
    expanded.value = new Set() // fresh data → reset per-parent caps
  } catch (e: any) {
    if (e?.response?.status === 403) forbidden.value = true
    else error.value = e?.response?.data?.detail || e?.message || t('agentLineage.loadFail', 'Failed to load lineage')
  } finally {
    loading.value = false
  }
}

watch(() => props.agentDid, load)
onMounted(load)
</script>

<style scoped>
.alt { display: flex; flex-direction: column; gap: .7rem; color: var(--text-primary, #cbd5e1); font-size: .82rem; }

.alt-head { display: flex; align-items: center; justify-content: space-between; gap: .6rem; flex-wrap: wrap; }
.alt-head-l { display: flex; align-items: center; gap: .5rem; }
.alt-title { font-weight: 600; color: var(--text-primary, #e2e8f0); }
.alt-mode { padding: .05rem .4rem; border-radius: 5px; font-size: .66rem; text-transform: uppercase; letter-spacing: .04em; border: 1px solid; }
.alt-mode--shadow { border-color: #b45309; background: rgba(180,83,9,.12); color: #fcd34d; }
.alt-mode--enforce { border-color: #15803d; background: rgba(21,128,61,.14); color: #86efac; }
.alt-mode--off { border-color: #334155; background: rgba(51,65,85,.2); color: #94a3b8; }
.alt-head-r { display: flex; align-items: center; gap: .6rem; }
.alt-counts { display: flex; flex-wrap: wrap; gap: .5rem; color: #64748b; font-size: .78rem; }
.alt-c b { color: #cbd5e1; font-weight: 600; }
.alt-c--ok b { color: #86efac; }
.alt-c--anchor b { color: #c4b5fd; }
.alt-refresh { display: inline-flex; align-items: center; justify-content: center; width: 1.7rem; height: 1.7rem; border-radius: 7px; background: transparent; border: 1px solid #334155; color: #94a3b8; cursor: pointer; }
.alt-refresh:disabled { opacity: .5; cursor: default; }
.alt-spin { animation: alt-spin .8s linear infinite; }
@keyframes alt-spin { to { transform: rotate(360deg); } }

.alt-skel, .alt-error, .alt-empty, .alt-forbidden { padding: .7rem .9rem; border: 1px solid var(--border-color, #1e293b); border-radius: 9px; background: rgba(15,23,42,.4); color: #94a3b8; }
.alt-error { color: #fca5a5; display: flex; gap: .6rem; align-items: center; justify-content: space-between; }
.alt-forbidden { display: flex; gap: .5rem; align-items: center; }
.alt-forbidden-ic { color: #64748b; flex-shrink: 0; }
.alt-btn { flex-shrink: 0; padding: .3rem .7rem; border-radius: 7px; background: transparent; border: 1px solid #334155; color: #cbd5e1; cursor: pointer; font-size: .78rem; }

.alt-born { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem; padding: .5rem .7rem; border-radius: 9px; background: rgba(139,92,246,.08); border: 1px solid rgba(139,92,246,.28); }
.alt-born-lab { color: #94a3b8; }

.alt-did { display: inline-flex; align-items: center; gap: .3rem; padding: .1rem .4rem; border-radius: 6px; background: rgba(2,6,23,.5); border: 1px solid #1e293b; color: #a5b4fc; font-family: ui-monospace, monospace; font-size: .74rem; cursor: pointer; }
.alt-did:hover { border-color: #334155; color: #c7d2fe; }
.alt-copyico { color: #64748b; font-size: .82em; }
.alt-copied { color: #86efac; font-size: .68rem; font-family: inherit; }
/* Open the DID's own agent page — cyan icon button matching the sub-agent surface. */
.alt-open { display: inline-flex; align-items: center; justify-content: center; width: 1.35rem; height: 1.35rem; border-radius: 6px; background: rgba(2,6,23,.5); border: 1px solid #1e293b; color: #67e8f9; cursor: pointer; flex-shrink: 0; }
.alt-open:hover { border-color: #06b6d4; color: #a5f3fc; }

/* Own scroll container: caps height AND absorbs any worst-case horizontal bleed
   so a deep/wide tree never pushes the page into horizontal scroll. */
.alt-tree { display: flex; flex-direction: column; gap: .3rem; max-height: 460px; overflow: auto; padding-right: .2rem; }
.alt-node { border-radius: 8px; background: rgba(2,6,23,.35); border: 1px solid #1e293b; padding: .4rem .55rem; }
/* Semantic left rail — reuses the surface palette (cyan = sub-agent, purple = anchored hand)
   so lineage type is scannable down the left edge before any badge is read. */
.alt-node--sub { box-shadow: inset 3px 0 0 rgba(6,182,212,.55); }
.alt-node--anchor { box-shadow: inset 3px 0 0 rgba(139,92,246,.6); }
.alt-node--dim { opacity: .5; }
/* A dead hand's rail goes neutral — alive/dead reads before the status badge. */
.alt-node--dim.alt-node--sub, .alt-node--dim.alt-node--anchor { box-shadow: inset 3px 0 0 rgba(100,116,139,.5); }
.alt-node--orphan { border-style: dashed; }
.alt-node-main { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; }
.alt-node-sub { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; margin-top: .3rem; }
.alt-branch { color: #475569; font-family: ui-monospace, monospace; }

.alt-badge { display: inline-flex; align-items: center; gap: .25rem; padding: .08rem .4rem; border-radius: 999px; font-size: .68rem; border: 1px solid; }
.alt-badge--anchor { background: rgba(139,92,246,.14); border-color: rgba(139,92,246,.4); color: #c4b5fd; }
.alt-badge--sub { background: rgba(6,182,212,.12); border-color: rgba(6,182,212,.35); color: #67e8f9; }

.alt-status { padding: .05rem .4rem; border-radius: 5px; font-size: .68rem; text-transform: uppercase; letter-spacing: .03em; border: 1px solid transparent; }
.alt-status--ok { color: #86efac; border-color: rgba(21,128,61,.4); background: rgba(21,128,61,.12); }
.alt-status--bad { color: #fca5a5; border-color: rgba(153,27,27,.4); background: rgba(153,27,27,.12); }
.alt-status--warn { color: #fcd34d; border-color: rgba(180,83,9,.4); background: rgba(180,83,9,.12); }
.alt-status--muted { color: #94a3b8; border-color: #334155; background: rgba(51,65,85,.18); }

.alt-tag { padding: .05rem .4rem; border-radius: 5px; font-size: .66rem; background: rgba(148,163,184,.12); border: 1px solid #334155; color: #94a3b8; }
.alt-meta { color: #64748b; font-size: .72rem; }
.alt-decay { color: #94a3b8; font-size: .72rem; }
.alt-decay--soon { color: #fcd34d; }   /* expiring within 24h */
.alt-decay--past { color: #fca5a5; }   /* already expired */
.alt-perm { padding: .05rem .4rem; border-radius: 5px; background: rgba(30,41,59,.6); border: 1px solid #334155; color: #cbd5e1; font-size: .68rem; font-family: ui-monospace, monospace; }
/* "can:" prefix that makes the permission chips read unmistakably as capabilities. */
.alt-caps-lab { color: #64748b; font-size: .68rem; text-transform: uppercase; letter-spacing: .04em; }
.alt-caps-none { font-style: italic; }

.alt-more { align-self: flex-start; padding: .25rem .6rem; border-radius: 7px; background: transparent; border: 1px dashed #334155; color: #67e8f9; cursor: pointer; font-size: .74rem; }
.alt-more:hover { border-color: #06b6d4; }

.alt-note { margin: .2rem 0 0; font-size: .74rem; color: #64748b; }

/* Cross-frame delegations — gold accent, distinct from cyan (sub-agent) / purple
   (anchored hand). These live on a PEER frame; opening one leaves this registry. */
.alt-c--xf b { color: #fcd34d; }
.alt-xf { margin-top: .4rem; padding-top: .6rem; border-top: 1px dashed #334155; display: flex; flex-direction: column; gap: .4rem; }
.alt-xf-head { display: flex; align-items: center; gap: .4rem; }
.alt-xf-ic { color: #fbbf24; }
.alt-xf-title { font-weight: 600; color: var(--text-primary, #e2e8f0); }
.alt-xf-count { padding: .02rem .42rem; border-radius: 999px; background: rgba(251,191,36,.14); border: 1px solid rgba(251,191,36,.4); color: #fcd34d; font-size: .68rem; }
.alt-xf-list { display: flex; flex-direction: column; gap: .3rem; }
.alt-node--xf { box-shadow: inset 3px 0 0 rgba(251,191,36,.6); }
.alt-node--xf.alt-node--dim { box-shadow: inset 3px 0 0 rgba(100,116,139,.5); }
.alt-badge--xf { background: rgba(251,191,36,.12); border-color: rgba(251,191,36,.4); color: #fcd34d; }
.alt-xf-note { margin: .1rem 0 0; font-size: .72rem; color: #64748b; }
</style>
