<!-- THE REGISTRY BOARD (§MEMBERSHIP phase C, 2026-10-02; design § 12 S5) — every registry the federated index reads,
     with its members and its commons. Registries compete for members the way cities compete for residents: with their
     rules and with what their commons pays for. The board shows members and their 30-day flow where a market would
     show a price, and it has no price, no chart and no buy button by design.
     The figures come from the Directory (stack directory/board.py) through this registry's own proxy; each says what
     was observed and no more: not checked yet, not published, could not be read, or the last good read with its time.
     Shown where this registry runs governance by membership or a commons (the sandbox, until phase E). Anywhere else the
     router's requiresRegistryAny guard sends a typed URL where the console starts before this page loads, and the page
     itself renders nothing while closed: production names no unreleased feature, not even by URL. -->
<template>
  <div class="rb-view" data-testid="registry-board" :data-state="state">
    <p v-if="!loaded" class="rb-muted" aria-busy="true">…</p>
    <template v-else-if="open">
    <header class="rb-head">
      <h1 class="rb-title"><Icon name="mdi:account-group" /> {{ t('registryBoard.title', 'Registries') }}</h1>
      <p class="rb-lead">{{ t('registryBoard.lead', 'Every registry the federated index reads, with its members and its commons. Registries compete for members with their rules and with what their commons pays for; there is no price on this page.') }}</p>
      <div v-if="state === 'ready'" class="rb-bar">
        <span class="rb-muted" data-testid="board-index">{{ indexLine }}</span>
        <label class="rb-sort">
          <span class="rb-muted">{{ t('registryBoard.sort', 'Order') }}</span>
          <select v-model="sortBy" class="tp-input rb-sort__select" data-testid="board-sort">
            <option value="members">{{ t('registryBoard.sortMembers', 'Most members') }}</option>
            <option value="flow">{{ t('registryBoard.sortFlow', 'Most joined in 30 days, net') }}</option>
            <option value="name">{{ t('registryBoard.sortName', 'Name') }}</option>
          </select>
        </label>
      </div>
    </header>

    <p v-if="state === 'ready' && figuresUnsupported" class="rb-note" data-testid="board-unsupported">
      {{ t('registryBoard.unsupported', 'This federated index does not read membership or commons figures yet; the registries are listed without them.') }}
    </p>

    <p v-if="state === 'loading'" class="rb-muted" aria-busy="true">…</p>
    <p v-else-if="state === 'no-index'" class="rb-note" data-testid="board-no-index">{{ t('registryBoard.noIndex', 'This registry is not connected to a federated index, so it cannot list other registries.') }}</p>
    <p v-else-if="state === 'failed'" class="rb-note" role="status" data-testid="board-failed">{{ t('registryBoard.failed', 'The federated index could not be read right now.') }}</p>
    <p v-else-if="state === 'ready' && !rows.length" class="rb-note" data-testid="board-empty">{{ t('registryBoard.empty', 'The federated index reads no registry yet.') }}</p>

    <ul v-else-if="state === 'ready'" class="rb-list">
      <li v-for="r in rows" :key="r.name" class="rb-card" data-testid="board-row" :data-name="r.name">
        <!-- §REPATLANE-7 (journal 51's figure): the place has a line of its own on every card; inline it wrapped to the
             second line on some cards and stayed beside the name on others, depending on how long the name was -->
        <div class="rb-card__top">
          <span class="rb-name">{{ r.name }}</span>
          <span v-if="r.tier" class="rb-tag">{{ tierWord(r.tier) }}</span>
          <a v-if="safeExternalUrl(r.publicUrl)" :href="safeExternalUrl(r.publicUrl)" target="_blank" rel="noopener noreferrer" class="rb-link">{{ t('registryBoard.visit', 'Visit') }}</a>
        </div>
        <div v-if="r.location || r.currency" class="rb-muted rb-card__where" data-testid="board-where">{{ [r.location, r.currency].filter(Boolean).join(' · ') }}</div>

        <div class="rb-cols">
          <!-- members: the figure a market would show as a price -->
          <div class="rb-col" data-testid="board-members" :data-kind="mv(r).kind">
            <div class="rb-col__label">{{ t('registryBoard.members', 'Members') }}</div>
            <template v-if="mv(r).kind === 'ok' || mv(r).kind === 'stale'">
              <div class="rb-big">{{ fmtCount(m(r).members) }}</div>
              <div class="rb-line">
                {{ tp('registryBoard.flow', '{joined} joined, {left} left in 30 days', { joined: fmtCount(m(r).joined), left: fmtCount(m(r).left) }) }}
                <span class="rb-net" :class="m(r).net > 0 ? 'is-up' : m(r).net < 0 ? 'is-down' : ''" data-testid="board-net">{{ netWord(m(r).net) }}</span>
              </div>
              <div class="rb-muted">{{ modeWord(m(r).mode) }}</div>
              <div v-if="mv(r).kind === 'stale'" class="rb-stale" data-testid="board-members-stale">
                {{ tp('registryBoard.stale', 'The last read failed; these figures are from {when}.', { when: when(m(r).readAt) }) }}
              </div>
            </template>
            <div v-else class="rb-muted">{{ notShown(mv(r).kind) }}</div>
          </div>

          <!-- the commons: the newest season, or why there is none to show -->
          <div class="rb-col" data-testid="board-commons" :data-kind="cv(r).kind">
            <div class="rb-col__label">{{ t('registryBoard.commons', 'Commons') }}</div>
            <template v-if="cv(r).kind === 'season'">
              <div class="rb-line rb-season">#{{ season(r).id }} {{ season(r).title || '' }} · <span>{{ seasonStatus(season(r).status) }}</span></div>
              <div class="rb-line">{{ tp('registryBoard.budget', 'Budget {budget} {cur}, paid {paid}', { budget: amount(season(r).budget), paid: amount(season(r).paidTotal), cur: cur(r) }) }}</div>
              <div class="rb-muted">{{ tp('registryBoard.work', 'Submissions: {subs} · Ballots: {ballots}', { subs: fmtCount(season(r).submissions ?? 0), ballots: fmtCount(season(r).ballots ?? 0) }) }}</div>
              <div v-if="cancelledOf(r) > 0" class="rb-muted" data-testid="board-commons-cancelled">{{ tp('registryBoard.cancelled', 'Cancelled recently: {n}', { n: fmtCount(cancelledOf(r)) }) }}</div>
              <div v-if="commonsStale(r)" class="rb-stale" data-testid="board-commons-stale">{{ tp('registryBoard.stale', 'The last read failed; these figures are from {when}.', { when: when(commonsReadAt(r)) }) }}</div>
            </template>
            <template v-else-if="cv(r).kind === 'none'">
              <div class="rb-muted">{{ cancelledOf(r) > 0 ? t('registryBoard.noLiveSeason', 'No season apart from cancelled ones.') : t('registryBoard.noSeason', 'No season yet.') }}</div>
              <div v-if="cancelledOf(r) > 0" class="rb-muted" data-testid="board-commons-cancelled">{{ tp('registryBoard.cancelled', 'Cancelled recently: {n}', { n: fmtCount(cancelledOf(r)) }) }}</div>
            </template>
            <div v-else-if="cv(r).kind === 'off'" class="rb-muted">{{ t('registryBoard.commonsOff', 'Switched off on this registry.') }}</div>
            <div v-else class="rb-muted">{{ notShown(cv(r).kind) }}</div>
          </div>
        </div>
      </li>
    </ul>
    </template>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { directoryService } from '@/services/api/directory'
import { fmt, fmtCount, fmtDateTime } from '@/services/cockpit/num'
import { commonsEnabled, governanceMode } from '@/services/membership/membership'
import {
  commonsView, membershipView, sortBoard,
  type BoardRegistry, type BoardSeason, type BoardSort, type CommonsView, type MembershipView,
} from '@/services/membership/board'

const { t, tp } = useI18n()
const { config, loaded, directoryUrl } = useRegistryConfig()

type State = 'loading' | 'off' | 'no-index' | 'failed' | 'ready'
const state = ref<State>('loading')
const all = ref<BoardRegistry[]>([])
const total = ref(0)
const lastCycleAt = ref<number | null>(null)
const sortBy = ref<BoardSort>('members')
/** the index answered, but it is older than the board's figures (it rejected the membership/commons fields) */
const figuresUnsupported = ref(false)

const open = computed(() => governanceMode(config.value) === 'member' || commonsEnabled(config.value))
const rows = computed(() => sortBoard(all.value, sortBy.value))

async function load() {
  if (!loaded.value) return
  if (!open.value) { state.value = 'off'; return }      // the router's guard closed the route; nothing shows here
  if (!directoryUrl.value) { state.value = 'no-index'; return }
  state.value = 'loading'
  try {
    const out = await directoryService.board(directoryUrl.value)
    all.value = out.registries
    total.value = out.registriesTotal
    lastCycleAt.value = out.lastCycleAt
    figuresUnsupported.value = out.figures === 'unsupported'
    state.value = 'ready'
  } catch {
    state.value = 'failed'
  }
}
watch(loaded, (v) => { if (v) void load() })
onMounted(() => { if (loaded.value) void load() })

// ── words ─────────────────────────────────────────────────────────────────
function mv(r: BoardRegistry): MembershipView { return membershipView(r.membership) }
function m(r: BoardRegistry) { return mv(r) as Extract<MembershipView, { kind: 'ok' | 'stale' }> }
function cv(r: BoardRegistry): CommonsView { return commonsView(r.commons) }
function season(r: BoardRegistry): BoardSeason { return (cv(r) as Extract<CommonsView, { kind: 'season' }>).season }
function cancelledOf(r: BoardRegistry) { const v = cv(r); return v.kind === 'season' || v.kind === 'none' ? v.cancelled : 0 }
function commonsStale(r: BoardRegistry) { const v = cv(r); return v.kind === 'season' && v.stale }
function commonsReadAt(r: BoardRegistry) { const v = cv(r); return v.kind === 'season' ? v.readAt : null }
function cur(r: BoardRegistry) { return (cv(r) as Extract<CommonsView, { kind: 'season' }>).currency || r.currency || '' }
function amount(v: string | null) { return v == null ? '—' : fmt(v, 6) }
function when(epochSeconds: number | null | undefined) { return epochSeconds ? fmtDateTime(epochSeconds * 1000) : '—' }
function netWord(n: number) { return n > 0 ? `+${fmtCount(n)}` : n < 0 ? `−${fmtCount(-n)}` : '±0' }

const indexLine = computed(() => tp('registryBoard.index', 'The federated index reads {n} registries; its last cycle ran {when}.',
  { n: fmtCount(total.value), when: when(lastCycleAt.value) }))

function tierWord(tier: string) {
  return ({ frame: t('registryBoard.tier.frame', 'Frame'), 'cloud-operator': t('registryBoard.tier.operator', 'Operator') } as Record<string, string>)[tier] || tier
}
function modeWord(mode: string | null) {
  if (mode === 'member') return t('registryBoard.modeMember', 'Votes: one per member, weighted by membership')
  if (mode === 'lock') return t('registryBoard.modeLock', 'Votes: weighted by locked units')
  return ''
}
function seasonStatus(s: string | null) {
  return ({ open: t('commons.status.open', 'open'), closed: t('commons.status.closed', 'closed'),
    paid: t('commons.status.paid', 'paid'), cancelled: t('commons.status.cancelled', 'cancelled') } as Record<string, string>)[s || ''] || (s || '')
}
function notShown(kind: string) {
  // an index older than the figures never checks them: "not checked yet" would promise a check that is not coming
  if (kind === 'unchecked' && figuresUnsupported.value) return t('registryBoard.notRead', 'Not read by this index.')
  return ({
    unchecked: t('registryBoard.unchecked', 'Not checked yet.'),
    absent: t('registryBoard.absent', 'Not published by this registry.'),
    failed: t('registryBoard.unreadable', 'Could not be read yet.'),
  } as Record<string, string>)[kind] || ''
}
</script>

<style scoped>
.rb-view { padding: 1.25rem; max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 1rem; }
.rb-head { display: flex; flex-direction: column; gap: 0.4rem; }
.rb-title { display: inline-flex; align-items: center; gap: 0.5rem; margin: 0; font-size: 1.35rem; font-weight: 800; }
.rb-title :deep(svg) { width: 1.3rem; height: 1.3rem; }
.rb-lead { margin: 0; max-width: 70ch; font-size: 0.86rem; line-height: 1.5; opacity: 0.85; }
.rb-bar { display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.rb-sort { display: inline-flex; align-items: center; gap: 0.4rem; }
.rb-sort__select { font-size: 16px; }
.rb-muted { font-size: 0.78rem; opacity: 0.8; line-height: 1.45; }
.rb-note { margin: 0; font-size: 0.86rem; }
.rb-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr)); gap: 0.75rem; }
.rb-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb, 0,212,255), 0.14); border-radius: 10px; padding: 0.85rem 1rem; display: flex; flex-direction: column; gap: 0.6rem; min-width: 0; }
.rb-card__top { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.rb-card__where { margin-top: -0.35rem; overflow-wrap: anywhere; }
.rb-name { font-weight: 800; font-size: 0.95rem; overflow-wrap: anywhere; }
.rb-tag { font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.1rem 0.4rem; border-radius: 4px; background: rgba(255,255,255,0.06); }
.rb-link { margin-left: auto; font-size: 0.78rem; color: inherit; text-decoration: underline; text-underline-offset: 2px; }
.rb-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }
.rb-col { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.rb-col__label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.7; }
.rb-big { font-size: 1.6rem; font-weight: 800; font-variant-numeric: tabular-nums; color: var(--nc-primary, #00d4ff); }
.rb-line { font-size: 0.8rem; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.rb-season { font-weight: 700; }
.rb-net { margin-left: 0.35rem; font-weight: 700; }
.rb-net.is-up { color: rgb(74,222,128); }
.rb-net.is-down { color: rgb(251,191,36); }
.rb-stale { font-size: 0.72rem; color: rgb(251,191,36); }
@media (max-width: 480px) {
  .rb-view { padding: 0.9rem; }
  .rb-cols { grid-template-columns: 1fr; }
}
</style>
