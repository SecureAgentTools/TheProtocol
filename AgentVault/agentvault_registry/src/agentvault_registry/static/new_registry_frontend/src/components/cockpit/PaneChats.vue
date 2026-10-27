<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
/**
 * §COCKPITCHATS — the conversations you or your agents can see, newest first.
 *
 * His ask: *"a modul which shows the latest active chats to have an overview over new
 * messages"*, scoped *"by dev. all chats he has access to from his org or agents"*.
 *
 * 🔴 NO NEW RAIL, AND THAT IS THE POINT. `GET /chat/conversations` already answers exactly
 * that question — its own docstring says "a developer's inbox spans their own rows plus
 * their local agents' rows; unread sums both" — so this pane is a mount, not a second
 * implementation of "which conversations are mine". A second inbox query is how two
 * surfaces come to disagree about what you have read (§ORGLEAK's lesson one table over).
 *
 * ⚠ THE PREVIEW IS A CARD KIND, NOT PROSE. Every preview on this account is a typed card
 * token — `[service.result]`, `[support.closed]`, `[share.certificate]` — because OurChat's
 * money-adjacent rows are a CLOSED vocabulary rather than free text (§OURSTATE). Rendering
 * `[service.result]` at a human is rendering our enum at them, so the known tokens become
 * sentences. ⚠ An UNKNOWN token is shown verbatim and marked as a card: inventing a
 * sentence for a vocabulary word this build does not know would be worse than the enum.
 *
 * ⚠ Previews are masked by the desk's hide switch. They are message CONTENT, which is the
 * "crucial data" the switch was asked for — the counts and the structure stay, so the pane
 * still tells you there is something to read.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { PANES } from './paneRegistry'
import { apiClient } from '@/services/api/client'

const { t, tp } = useI18n()
const { hidden, MASK } = usePrivacy()
const router = useRouter()
const def = PANES.chats

const FILTER_KEY = 'ckd_chats_filter'
type Filter = 'unread' | 'all'
const filter = ref<Filter>('unread')
try { const v = localStorage.getItem(FILTER_KEY); if (v === 'all' || v === 'unread') filter.value = v } catch { /* private window */ }
function setFilter(f: Filter) { filter.value = f; try { localStorage.setItem(FILTER_KEY, f) } catch { /* ignore */ } }

const rows = ref<any[]>([])
const totals = ref<{ messages: number; threads: number } | null>(null)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
const now = ref(Date.now())
let poll: ReturnType<typeof setInterval> | null = null
let tick: ReturnType<typeof setInterval> | null = null

// §COCKPITTILES T1 — rows now follow the tile, not a constant.
const ROW_FLOOR = 4
const rowsEl = ref<HTMLElement | null>(null)
const { count: fitRows } = useFillCount(rowsEl, { rowPx: 34, min: ROW_FLOOR, max: 40, reservePx: 92 })

async function load() {
  try {
    const { data } = await apiClient.get('/chat/conversations', { params: { state: 'active', limit: 30 } })
    rows.value = (data?.conversations || [])
    err.value = ''; readAt.value = Date.now()
    // Two independent reads: a failing counter must not blank the list.
    try {
      const u = await apiClient.get('/chat/unread-count')
      totals.value = { messages: Number(u.data?.messages ?? 0), threads: Number(u.data?.threads ?? 0) }
    } catch { totals.value = null }
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => {
  void load()
  poll = setJitteredInterval(load, (def.pollSeconds ?? 45) * 1000)
  tick = setJitteredInterval(() => { now.value = Date.now() }, 15000)
})
onUnmounted(() => {
  if (poll) clearInterval(poll); poll = null
  if (tick) clearInterval(tick); tick = null
})

/** The card vocabulary actually present on this deployment, turned into sentences.
 *  Anything not in this map renders as its own token — see the header note. */
const CARD_SAYS: Record<string, [string, string]> = {
  'service.result':     ['cockpit.chats.cardServiceResult', 'a paid service returned its result'],
  'service.request':    ['cockpit.chats.cardServiceRequest', 'a service was asked to do work'],
  'support.in_progress':['cockpit.chats.cardSupportProgress', 'the support desk started work'],
  'support.closed':     ['cockpit.chats.cardSupportClosed', 'the support ticket was closed'],
  'support.opened':     ['cockpit.chats.cardSupportOpened', 'a support ticket was opened'],
  'exchange.listing':   ['cockpit.chats.cardListing', 'an AGORA listing was shared'],
  'agent.card':         ['cockpit.chats.cardAgent', 'an agent card was shared'],
  'share.certificate':  ['cockpit.chats.cardCertificate', 'a signed holding certificate was shared'],
}

function previewOf(c: any): { text: string; isCard: boolean; unknown: boolean } {
  const raw = String(c?.last_preview ?? '').trim()
  if (!raw) return { text: t('cockpit.chats.noPreview', 'no messages yet'), isCard: false, unknown: false }
  const m = raw.match(/^\[([a-z_.]+)\]$/i)
  if (!m) return { text: hidden.value ? MASK : raw, isCard: false, unknown: false }
  const known = CARD_SAYS[m[1]]
  if (known) return { text: t(known[0], known[1]), isCard: true, unknown: false }
  return { text: m[1], isCard: true, unknown: true }
}

/** A thread's name: its title, else who it is with, else what it is — never a raw DID
 *  while a name exists, and never a blank line (§COCKPITPOLISH). */
function nameOf(c: any): string {
  if (c?.title) return String(c.title)
  const cp = c?.counterparty
  if (cp?.name) return String(cp.name)
  if (cp?.agent_did) return String(cp.agent_did).slice(0, 26)
  return t('cockpit.chats.untitled', 'untitled thread')
}
// a DID, or a peer registry principal's ADDRESS (§TWOAGENT G1, V0437): never an empty hover on a remote row
function subjectDid(c: any): string { return c?.counterparty?.agent_did || c?.counterparty?.remote_key || '' }

const KIND_LABEL: Record<string, [string, string]> = {
  support: ['cockpit.chats.kindSupport', 'support'],
  agent_service: ['cockpit.chats.kindService', 'service'],
  dm: ['cockpit.chats.kindDm', 'direct'],
  org_room: ['cockpit.chats.kindOrg', 'org room'],
  room: ['cockpit.chats.kindOrg', 'org room'],
}
function kindOf(c: any): string {
  const k = String(c?.kind || '')
  const l = KIND_LABEL[k]
  return l ? t(l[0], l[1]) : k
}

function ageOf(iso: string | null | undefined): string {
  if (!iso) return '—'
  const s = Math.max(0, Math.round((now.value - new Date(iso).getTime()) / 1000))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

const sorted = computed(() => [...rows.value].sort((a, b) =>
  new Date(b.last_message_at || 0).getTime() - new Date(a.last_message_at || 0).getTime()))
const filtered = computed(() => filter.value === 'unread'
  ? sorted.value.filter(c => Number(c.unread || 0) > 0)
  : sorted.value)
const shown = computed(() => filtered.value.slice(0, fitRows.value))
/** ⚠ Two independent hidings, reported apart (§HEARTBEAT): the FILTER and the row cap. */
const outsideFilter = computed(() => sorted.value.length - filtered.value.length)
const beyondCap = computed(() => Math.max(0, filtered.value.length - shown.value.length))
const empty = computed(() => !loading.value && sorted.value.length === 0)

function open(c: any) {
  // ⚠ `router.push` resolves on an ABORTED navigation, so nothing is asserted here —
  // the battery checks `currentRoute` after the click instead.
  void router.push({ name: 'desk-ourchat-thread', params: { id: String(c.id) } })
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.chats.empty', 'No conversations you or your agents take part in.')">
    <div class="ch" data-testid="ch-root" ref="rowsEl" :data-fit="fitRows">
      <p class="ch-lede" data-testid="ch-lede">
        <template v-if="totals">
          {{ tp('cockpit.chats.lede', '{m} unread across {t} threads — your own conversations and your agents’, together.',
                { m: totals.messages, t: totals.threads }) }}
        </template>
        <template v-else>
          {{ t('cockpit.chats.ledeNoCount', 'Your own conversations and your agents’, together. The unread counter could not be read just now.') }}
        </template>
      </p>

      <div class="ch-chips" data-testid="ch-chips">
        <button class="ch-chip" :class="{ 'is-on': filter === 'unread' }" data-testid="ch-chip-unread"
                @click="setFilter('unread')">
          {{ tp('cockpit.chats.chipUnread', 'Unread · {n}', { n: sorted.filter(c => Number(c.unread || 0) > 0).length }) }}
        </button>
        <button class="ch-chip" :class="{ 'is-on': filter === 'all' }" data-testid="ch-chip-all"
                @click="setFilter('all')">
          {{ tp('cockpit.chats.chipAll', 'All · {n}', { n: sorted.length }) }}
        </button>
      </div>

      <ul class="ch-list">
        <!-- ⚠ TWO LINES, because one line could not carry both. In a single-column pane
             the name, the kind chip, the badge and the age left the preview about four
             characters — the board rendered "a share…", "an agen…", "a paid…", which is
             an inbox that cannot tell you what arrived. The preview gets its own row and
             the whole pane width; everything that identifies the thread stays on the
             first. -->
        <li v-for="c in shown" :key="c.id" class="ch-row" data-testid="ch-row"
            :class="{ 'is-unread': Number(c.unread || 0) > 0, 'is-muted': c.muted }"
            @click="open(c)">
          <div class="ch-top">
            <span class="ch-dot" :class="Number(c.unread || 0) > 0 ? 'is-new' : 'is-read'" />
            <span class="ch-name" :title="subjectDid(c) || nameOf(c)" data-testid="ch-name">{{ nameOf(c) }}</span>
            <span class="ch-kind" data-testid="ch-kind">{{ kindOf(c) }}</span>
            <span class="ch-grow" />
            <span v-if="c.muted" class="ch-mutedmark"
                  :title="t('cockpit.chats.mutedHint', 'Muted: it still counts here, it just does not notify you.')">
              <Icon name="mdi:bell-off-outline" />
            </span>
            <span v-if="Number(c.unread || 0) > 0" class="ch-badge" data-testid="ch-unread">{{ c.unread }}</span>
            <span class="ch-age" data-testid="ch-age">{{ ageOf(c.last_message_at) }}</span>
          </div>
          <div class="ch-prev" :class="{ 'is-card': previewOf(c).isCard, 'is-unknown': previewOf(c).unknown }"
               data-testid="ch-preview">
            <Icon v-if="previewOf(c).isCard" name="mdi:card-account-details" class="ch-cardicon" />
            <span class="ch-prev-t">{{ previewOf(c).text }}</span>
          </div>
        </li>
      </ul>

      <p v-if="!shown.length && !empty" class="ch-none" data-testid="ch-none">
        {{ t('cockpit.chats.allRead', 'Nothing unread. Switch to All to see the rest.') }}
      </p>

      <p class="ch-foot" data-testid="ch-foot">
        {{ tp('cockpit.chats.foot', 'Showing {n} of {tot} · {out} outside this filter · {cap} beyond the row limit',
              { n: shown.length, tot: sorted.length, out: outsideFilter, cap: beyondCap }) }}
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ch { display: flex; flex-direction: column; gap: .35rem; }
.ch-lede { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #6e7681); line-height: 1.45; }
.ch-chips { display: flex; gap: .3rem; }
.ch-chip {
  border: 1px solid var(--nc-border, rgba(255,255,255,.12)); background: transparent;
  color: var(--nc-text-dim, #8b949e); border-radius: 5px; padding: .08rem .4rem;
  font-size: .6rem; letter-spacing: .05em; cursor: pointer;
}
.ch-chip.is-on { color: var(--nc-primary, #00e5ff); border-color: var(--nc-primary, #00e5ff); }
.ch-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .1rem; }
.ch-row {
  display: flex; flex-direction: column; gap: .05rem; font-size: .7rem;
  padding: .22rem .25rem; border-radius: 5px; cursor: pointer;
}
.ch-top { display: flex; align-items: center; gap: .35rem; }
.ch-grow { flex: 1; }
.ch-row:hover { background: rgba(255,255,255,.04); }
.ch-row.is-muted { opacity: .72; }
.ch-dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
.ch-dot.is-new { background: var(--nc-primary, #00e5ff); box-shadow: 0 0 5px rgba(var(--nc-primary-rgb,0,229,255),.8); }
.ch-dot.is-read { background: var(--nc-text-muted, #6e7681); opacity: .5; }
.ch-name {
  flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--nc-text-primary, #e6edf3);
}
.ch-row.is-unread .ch-name { font-weight: 600; }
.ch-kind {
  font-size: .55rem; letter-spacing: .06em; text-transform: uppercase;
  color: var(--nc-text-muted, #6e7681); border: 1px solid var(--nc-border, rgba(255,255,255,.1));
  border-radius: 3px; padding: 0 .22rem; flex: 0 0 auto;
}
.ch-prev {
  min-width: 0; color: var(--nc-text-dim, #8b949e); font-size: .64rem;
  display: flex; align-items: center; gap: .25rem; padding-left: .85rem;
}
.ch-prev-t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ch-prev.is-card { font-style: italic; }
/* A vocabulary word this build cannot translate is shown AS the word, and looks like one. */
.ch-prev.is-unknown { font-family: var(--nc-font-mono, ui-monospace, monospace); font-style: normal; }
.ch-cardicon { width: 11px; height: 11px; flex: 0 0 auto; opacity: .7; }
.ch-mutedmark { color: var(--nc-text-muted, #6e7681); display: inline-flex; }
.ch-badge {
  flex: 0 0 auto; min-width: 1.15rem; text-align: center; font-size: .58rem; font-weight: 700;
  background: var(--nc-primary, #00e5ff); color: var(--nc-bg, #05050a);
  border-radius: 999px; padding: 0 .25rem; font-variant-numeric: tabular-nums;
}
.ch-age {
  flex: 0 0 2.4rem; width: 2.4rem; text-align: right; font-size: .6rem;
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  color: var(--nc-text-muted, #6e7681);
}
.ch-none { margin: .2rem 0 0; font-size: .64rem; color: var(--nc-text-muted, #6e7681); }
.ch-foot { margin: .1rem 0 0; font-size: .6rem; color: var(--nc-text-muted, #6e7681); }
</style>
