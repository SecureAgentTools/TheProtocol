<template>
  <!-- §FEDDIR (2026-09-09) — the federated index, as a Federation tab.
       His word: "would be good if you can also add the directory in a new tab. since its
       federation related." It is: the index is the only component that sees every frame's cards
       at once, and `DISCOVERY_VIA_DIRECTORY` means registries RENDER what it returns.

       Body-only, like FederationOperationsPanel — the hero and ambient belong to Federation.vue.
       No new backend: `directoryService.snapshot()` already returns status + sources + agents +
       listings in ONE round-trip through the registry's own mTLS proxy. -->
  <div class="fdir">

    <!-- ── THREE STATES, NEVER ONE EMPTY LIST ────────────────────────────────────────────────
         A filter that removes everything is indistinguishable from an outage unless it says so.
         "No index configured", "the index refused us" and "the index is genuinely empty" need
         three different sentences and three different actions. -->
    <div v-if="!directoryDiscoveryEnabled" class="fdir-state fdir-state--off">
      <Icon name="mdi:information-outline" :size="16" />
      <div>
        <p class="fdir-state-title">{{ t('federationView.directory.notConfigured') }}</p>
        <p class="fdir-state-sub">{{ t('federationView.directory.notConfiguredSub') }}</p>
      </div>
    </div>

    <div v-else-if="loading && !status" class="fdir-state">
      <div class="fdir-spinner"></div>
      <p class="fdir-state-sub">{{ t('federationView.directory.loading') }}</p>
    </div>

    <div v-else-if="failed" class="fdir-state fdir-state--err">
      <Icon name="mdi:alert" :size="16" />
      <div>
        <p class="fdir-state-title">{{ t('federationView.directory.unreachable') }}</p>
        <!-- the reason, verbatim: an index that refused us is a different problem from one that
             is empty, and only the message can tell them apart -->
        <p class="fdir-state-sub fdir-mono">{{ failed }}</p>
        <button class="fdir-btn" @click="load(true)">{{ t('federationView.directory.retry') }}</button>
      </div>
    </div>

    <template v-else-if="status">
      <!-- ── the index's own numbers ─────────────────────────────────────────────────────── -->
      <div class="fdir-kpis">
        <div class="fdir-kpi">
          <span class="fdir-kpi-label">{{ t('federationView.directory.kpi.agents') }}</span>
          <span class="fdir-kpi-value">{{ fmt(status.agentsTotal) }}</span>
        </div>
        <div class="fdir-kpi">
          <span class="fdir-kpi-label">{{ t('federationView.directory.kpi.registries') }}</span>
          <span class="fdir-kpi-value">
            {{ status.registriesVerified }}<span class="fdir-kpi-of">/{{ status.registriesTotal }}</span>
          </span>
          <span class="fdir-kpi-sub">{{ t('federationView.directory.kpi.verified') }}</span>
        </div>
        <div class="fdir-kpi">
          <span class="fdir-kpi-label">{{ t('federationView.directory.kpi.listings') }}</span>
          <span class="fdir-kpi-value">{{ fmt(status.listingsTotal) }}</span>
        </div>
        <div class="fdir-kpi">
          <span class="fdir-kpi-label">{{ t('federationView.directory.kpi.lastCycle') }}</span>
          <!-- NOT MEASURED is its own state: an index that has never completed a cycle must not
               read as one that completed a moment ago. -->
          <span class="fdir-kpi-value fdir-kpi-value--sm">{{ lastCycleLabel }}</span>
        </div>
      </div>

      <div class="fdir-meta">
        <span>{{ live.lastRefreshedLabel.value ? t('federationView.refreshed') + ' ' + live.lastRefreshedLabel.value : '' }}</span>
        <span v-if="live.lastFetchedAt.value" class="fdir-meta-sep">·</span>
        <span v-if="live.lastFetchedAt.value">{{ t('federationView.next') }} {{ live.nextRefreshInSeconds.value }}s</span>
        <button class="fdir-btn fdir-btn--ghost" @click="load(true)">
          <Icon name="mdi:refresh" :size="13" /> {{ t('federationView.directory.refresh') }}
        </button>
      </div>

      <!-- ── what the index reads, and whether it trusts it ──────────────────────────────── -->
      <h3 class="fdir-h3">{{ t('federationView.directory.sources') }}</h3>
      <p class="fdir-hint">{{ t('federationView.directory.sourcesHint') }}</p>
      <p class="fdir-hint fdir-hint--sm">{{ t('federationView.directory.hopHint') }}</p>
      <div class="fdir-table-wrap">
        <table class="fdir-table">
          <thead>
            <tr>
              <th>{{ t('federationView.directory.col.source') }}</th>
              <th>{{ t('federationView.directory.col.state') }}</th>
              <th class="fdir-num">{{ t('federationView.directory.col.agents') }}</th>
              <th class="fdir-num">{{ t('federationView.directory.col.listings') }}</th>
              <th>{{ t('federationView.directory.col.hop') }}</th>
              <th>{{ t('federationView.directory.col.currency') }}</th>
              <th>{{ t('federationView.directory.col.why') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sources" :key="s.name" :class="{ 'fdir-row--self': isSelf(s.name) }">
              <td>
                <span class="fdir-src">{{ s.name }}</span>
                <span v-if="isSelf(s.name)" class="fdir-tag">{{ t('federationView.directory.thisFrame') }}</span>
              </td>
              <td>
                <span class="fdir-pill" :class="stateClass(s)">{{ stateLabel(s) }}</span>
              </td>
              <td class="fdir-num">{{ fmt(s.agentsIndexed) }}</td>
              <td class="fdir-num">
                {{ fmt(s.listingsIndexed) }}
                <span v-if="!s.feedSupported" class="fdir-tag fdir-tag--muted"
                      :title="t('federationView.directory.noFeedHint')">{{ t('federationView.directory.noFeed') }}</span>
              </td>
              <!-- §FEDDIR-HOP — distance FROM THIS FRAME, from the same derivation the Network
                   rings are drawn with. The index's own crawl depth answers a different question
                   (how far it walked from ITS anchors) and is kept in the tooltip rather than
                   thrown away: a source we do not peer with has no distance from here at all. -->
              <td class="fdir-mono" :title="hopTitle(s)">{{ hopLabel(s) }}</td>
              <td class="fdir-mono">{{ s.currency || '—' }}</td>
              <!-- `reason` is the index's own word for why it does or does not trust a source.
                   Rendered verbatim rather than mapped: a label we invent here would be a second
                   opinion about someone else's verdict. -->
              <td class="fdir-why">{{ s.reason || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- ── venues, the same row Discovery shows ────────────────────────────────────────── -->
      <template v-if="listings.length">
        <h3 class="fdir-h3">{{ t('federationView.directory.venues') }}</h3>
        <div class="fdir-venues">
          <span v-for="l in listings" :key="l.symbol + (l.source || '')" class="fdir-venue">
            <strong>{{ l.symbol }}</strong>
            <span v-if="l.currency" class="fdir-venue-ccy">· {{ l.currency }}</span>
            <span v-if="l.venue?.name" class="fdir-venue-at">· {{ l.venue.name }}</span>
          </span>
        </div>
      </template>

      <p class="fdir-foot">{{ t('federationView.directory.foot') }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * §FEDDIR — the federated index as a Federation tab.
 *
 * Reuses `services/api/directory.ts::snapshot()` (one GraphQL round-trip through the registry's
 * own mTLS proxy) and `useRegistryConfig`'s `directoryUrl` / `directoryDiscoveryEnabled` — the
 * server decides the address, never a build-time constant. Nothing new was added to the backend.
 *
 * The clock is `useLiveRefresh`, the same one /federation and /admin/compliance now use, so the
 * three surfaces cannot disagree about what "Next 52s" means.
 */
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import {
  directoryService,
  type DirectoryStatus,
  type DirectorySource,
  type DirectoryListing,
} from '@/services/api/directory'

const props = defineProps<{
  /** name (lowercased) → hop distance from THIS frame, built by Federation.vue from `chainHopOf`
   *  — the same walk the Network tab lays its rings out with. Optional: with no map the column
   *  says so rather than falling back to the index's own count, which is what read wrong. */
  hopByName?: Map<string, number>
}>()

const { t, tp } = useI18n()
const { directoryUrl, directoryDiscoveryEnabled, config } = useRegistryConfig()

const status = ref<DirectoryStatus | null>(null)
const listings = ref<DirectoryListing[]>([])
const loading = ref(false)
const failed = ref<string>('')

const sources = computed<DirectorySource[]>(() => {
  const list = status.value?.sources ? [...status.value.sources] : []
  // this frame first, then the reachable ones, then the rest — an operator reads their own row
  // first and the broken ones next; alphabetical would bury both.
  return list.sort((a, b) => {
    const self = Number(isSelf(b.name)) - Number(isSelf(a.name))
    if (self) return self
    const ok = Number(b.reachable) - Number(a.reachable)
    if (ok) return ok
    return (a.name || '').localeCompare(b.name || '')
  })
})

function isSelf(name: string): boolean {
  const me = (config.value?.registry_name || '').trim().toLowerCase()
  return !!me && (name || '').trim().toLowerCase() === me
}

/** Hops from HERE. 0 is this frame; a source we hold no peer row for has no answer, not a zero. */
function hopFromHere(s: DirectorySource): number | null {
  if (isSelf(s.name)) return 0
  const h = props.hopByName?.get((s.name || '').trim().toLowerCase())
  return h === undefined ? null : h
}
function hopLabel(s: DirectorySource): string {
  const h = hopFromHere(s)
  return h === null ? '—' : 'h' + h
}
/** Never silently drop the index's own number — say whose count it is. */
function hopTitle(s: DirectorySource): string {
  // ⚠ tp(), not t(): the legacy t() takes EITHER params OR a fallback, and given both it returns
  // the fallback verbatim with a literal {n} in it.
  const idx = s.hop === null || s.hop === undefined
    ? t('federationView.directory.hopIndexUnknown', 'the index did not say how far it crawled')
    : tp('federationView.directory.hopIndex', 'index crawl depth: h{n}', { n: String(s.hop) })
  return hopFromHere(s) === null
    ? t('federationView.directory.hopNoPeer', 'not a peer of this frame') + ' · ' + idx
    : idx
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString(undefined)
}

const lastCycleLabel = computed(() => {
  const at = status.value?.lastCycleAt
  // §29e — "never completed a cycle" and "completed just now" must not render the same.
  if (!at) return t('federationView.directory.noCycle', 'never')
  const secs = Math.max(0, Math.floor(live.nowTick.value / 1000 - at))
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m`
  return `${Math.floor(mins / 60)}h`
})

function stateLabel(s: DirectorySource): string {
  if (!s.reachable) return t('federationView.directory.state.unreachable', 'unreachable')
  return s.verified
    ? t('federationView.directory.state.verified', 'verified')
    : t('federationView.directory.state.unverified', 'unverified')
}
function stateClass(s: DirectorySource): string {
  if (!s.reachable) return 'fdir-pill--err'
  return s.verified ? 'fdir-pill--ok' : 'fdir-pill--warn'
}

async function load(force = false): Promise<void> {
  if (!directoryDiscoveryEnabled.value) return
  if (loading.value && !force) return
  loading.value = true
  try {
    const snap = await directoryService.snapshot(directoryUrl.value, 200)
    status.value = snap.status
    // ⚠ `snapshot()` already unwraps `.edges` — it returns a flat array, unlike `listings()`.
    listings.value = snap.listings ?? []
    failed.value = ''
    // stamp only on SUCCESS — a clock that says "just now" over a failed refresh is a probe that
    // cannot distinguish its own failure from success.
    live.markFetched()
  } catch (e: unknown) {
    // The message is kept and shown. An index that refused us is a different problem from an
    // empty one, and swallowing this would render "nobody is out there".
    failed.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

const live = useLiveRefresh(() => { void load() }, { intervalMs: 60_000 })

void load()
</script>

<style scoped>
.fdir { display: flex; flex-direction: column; gap: 14px; }

.fdir-state {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 16px 18px; border-radius: 12px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04);
}
.fdir-state--off { border-color: rgba(148, 163, 184, 0.28); background: rgba(148, 163, 184, 0.06); }
.fdir-state--err { border-color: rgba(239, 68, 68, 0.35); background: rgba(239, 68, 68, 0.06); }
.fdir-state-title { font-weight: 600; margin: 0 0 3px; }
.fdir-state-sub { font-size: 0.8rem; opacity: 0.75; margin: 0; }
.fdir-spinner {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25);
  border-top-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.9);
  animation: fdir-spin 0.8s linear infinite;
}
@keyframes fdir-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .fdir-spinner { animation-duration: 2.4s; } }

.fdir-hint--sm { opacity: 0.6; }

.fdir-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.fdir-kpi {
  display: flex; flex-direction: column; gap: 3px;
  padding: 12px 14px; border-radius: 12px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
  background: rgba(255, 255, 255, 0.02);
}
.fdir-kpi-label { font-size: 0.66rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.62; }
.fdir-kpi-value { font-size: 1.5rem; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.fdir-kpi-value--sm { font-size: 1.05rem; }
.fdir-kpi-of { font-size: 0.9rem; font-weight: 500; opacity: 0.55; }
.fdir-kpi-sub { font-size: 0.64rem; opacity: 0.55; }

.fdir-meta {
  display: flex; align-items: center; gap: 7px;
  font-size: 0.72rem; opacity: 0.68; font-variant-numeric: tabular-nums;
}
.fdir-meta-sep { opacity: 0.4; }

.fdir-h3 { font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.75; margin: 4px 0 0; }
.fdir-hint { font-size: 0.72rem; opacity: 0.55; margin: 0; }

/* wide content scrolls inside its own box — the page body must never scroll sideways */
.fdir-table-wrap { overflow-x: auto; }
.fdir-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.fdir-table th {
  text-align: left; font-size: 0.64rem; letter-spacing: 0.07em; text-transform: uppercase;
  opacity: 0.55; padding: 6px 10px; white-space: nowrap;
}
.fdir-table td { padding: 8px 10px; border-top: 1px solid rgba(148, 163, 184, 0.14); vertical-align: top; }
.fdir-num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.fdir-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.74rem; opacity: 0.8; }
.fdir-row--self { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05); }
.fdir-src { font-weight: 600; }
.fdir-why { font-size: 0.72rem; opacity: 0.7; max-width: 30ch; }

.fdir-pill {
  display: inline-block; padding: 2px 8px; border-radius: 99px;
  font-size: 0.64rem; letter-spacing: 0.05em; text-transform: uppercase; white-space: nowrap;
}
.fdir-pill--ok { color: #34d399; background: rgba(52, 211, 153, 0.12); border: 1px solid rgba(52, 211, 153, 0.3); }
.fdir-pill--warn { color: #fbbf24; background: rgba(251, 191, 36, 0.12); border: 1px solid rgba(251, 191, 36, 0.3); }
.fdir-pill--err { color: #f87171; background: rgba(248, 113, 113, 0.12); border: 1px solid rgba(248, 113, 113, 0.3); }

.fdir-tag {
  margin-left: 6px; padding: 1px 6px; border-radius: 99px; font-size: 0.6rem;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35);
  color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.95);
}
.fdir-tag--muted { border-color: rgba(148, 163, 184, 0.3); color: rgba(148, 163, 184, 0.85); }

.fdir-venues { display: flex; flex-wrap: wrap; gap: 7px; }
.fdir-venue {
  padding: 3px 9px; border-radius: 8px; font-size: 0.72rem;
  border: 1px solid rgba(148, 163, 184, 0.22); background: rgba(255, 255, 255, 0.02);
}
.fdir-venue-ccy, .fdir-venue-at { opacity: 0.6; }

.fdir-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: 8px; font-size: 0.72rem; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3);
  background: transparent; color: inherit;
}
.fdir-btn:hover { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.6); }
.fdir-btn--ghost { margin-left: auto; }

.fdir-foot { font-size: 0.7rem; opacity: 0.5; margin: 2px 0 0; }
</style>
