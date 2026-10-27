<template>
  <!-- Build #6 (2026-05-07): EventStore Explorer.
       New top-level admin view at /admin/events.
       Strategy doc §4 Build #6 — final build of the roadmap. -->
  <div class="ae">
    <!-- Ambient -->
    <div class="ae-ambient">
      <div class="ae-grid"></div>
      <div class="ae-glow ae-glow-1"></div>
      <div class="ae-glow ae-glow-2"></div>
    </div>

    <!-- Hero -->
    <section class="ae-hero">
      <div class="ae-hero-inner" data-tour="events-hero">
        <div class="ae-chip"><span class="ae-chip-dot"></span>EVENTSTORE</div>
        <h1 class="ae-h1">{{ t('adminEventsView.hero.h1a') }}<span class="ae-accent">{{ t('adminEventsView.hero.h1Accent') }}</span>{{ t('adminEventsView.hero.h1b') }}</h1>
        <p class="ae-lead">
          {{ t('adminEventsView.hero.lead') }}
        </p>
      </div>
    </section>

    <!-- Body — sidebar filter + main panel -->
    <div class="ae-body">

      <!-- Sidebar -->
      <aside class="ae-sidebar">
        <!-- Frame switch (§FEDEVENTS 2026-08-03): the LOCAL registry, plus ONLY
             the sibling frames holding a live Multi-Frame Console session. No
             hardcoded letters — works unchanged on hetzner-frame / any future
             deployment whose identity the static seed has never heard of. -->
        <div class="ae-side-section" data-tour="events-frame">
          <div class="ae-side-title">{{ t('adminEventsView.sidebar.frame') }}</div>
          <div class="ae-side-help">{{ t('adminEventsView.sidebar.frameHelpDynamic', 'This registry — plus any sibling frame you have connected in the Multi-Frame Console.') }}</div>
          <div class="ae-frame-switch" :class="{ 'ae-frame-switch--solo': selectableFrames.length === 1 }">
            <button
              v-for="opt in selectableFrames"
              :key="opt.key"
              class="ae-frame-btn"
              :class="{ 'ae-frame-btn--active': selectedKey === opt.key }"
              :title="opt.isLocal ? `${opt.label} — this registry` : `${opt.label} — connected sibling frame`"
              @click="setFrame(opt.key)"
            >
              <span class="ae-frame-dot" :style="{ background: opt.accentHex, boxShadow: `0 0 6px ${opt.accentHex}99` }"></span>
              {{ opt.label }}
            </button>
          </div>
          <router-link
            v-if="selectableFrames.length === 1"
            class="ae-connect-link"
            to="/settings?tab=multiframe"
          >{{ t('adminEventsView.sidebar.connectFrames', 'Connect sibling frames in Settings →') }}</router-link>
        </div>

        <div class="ae-side-section">
          <div class="ae-side-title">{{ t('adminEventsView.sidebar.eventType') }}</div>
          <div class="ae-side-help">{{ t('adminEventsView.sidebar.eventTypeHelp') }}</div>
          <select v-model="filterEventType" class="ae-select" @change="reloadOnFilterChange" :aria-label="t('adminEventsView.eventTypeAria', 'Filter by event type')">
            <option value="">{{ t('adminEventsView.sidebar.eventTypeAll') }}</option>
            <option v-for="et in eventTypeOptions" :key="et" :value="et">{{ et }}</option>
          </select>
        </div>

        <!-- Sort order toggle (bug fix 2026-05-07) — only meaningful when no event_type filter -->
        <div class="ae-side-section">
          <div class="ae-side-title">{{ t('adminEventsView.sidebar.sortOrder') }}</div>
          <div class="ae-side-help">{{ t('adminEventsView.sidebar.sortOrderHelp') }}</div>
          <div class="ae-frame-switch">
            <button
              class="ae-frame-btn"
              :class="{ 'ae-frame-btn--active': effectiveSort === 'desc' }"
              :disabled="loading"
              @click="setSortOrder('desc')"
              title="Newest first"
            >{{ t('adminEventsView.sidebar.newest') }}</button>
            <button
              class="ae-frame-btn"
              :class="{ 'ae-frame-btn--active': effectiveSort === 'asc' }"
              :disabled="loading || !!filterEventType"
              @click="setSortOrder('asc')"
              :title="filterEventType
                ? t('adminEventsView.sidebar.ascDisabled', 'Type-filtered search is served newest-first by the EventStore index')
                : 'Oldest first (genesis-period browsing)'"
            >{{ t('adminEventsView.sidebar.oldest') }}</button>
          </div>
        </div>

        <div class="ae-side-section" data-tour="events-aggregate">
          <div class="ae-side-title">{{ t('adminEventsView.sidebar.aggregate') }}</div>
          <div class="ae-side-help">{{ t('adminEventsView.sidebar.aggregateHelp') }}</div>
          <input
            v-model.lazy="aggregateInput"
            type="text"
            :placeholder="t('adminEventsView.sidebar.aggregatePh')"
            class="ae-input"
            @keyup.enter="searchByAggregate"
          />
          <div class="ae-side-actions">
            <button class="ae-btn ae-btn--primary" :disabled="!aggregateInput || loading" @click="searchByAggregate">{{ t('adminEventsView.sidebar.searchAggregate') }}</button>
            <button class="ae-btn ae-btn--ghost" :disabled="loading" @click="resetSearch">{{ t('adminEventsView.sidebar.reset') }}</button>
          </div>
        </div>

        <div class="ae-side-section">
          <div class="ae-side-title">{{ t('adminEventsView.sidebar.page') }}</div>
          <div class="ae-side-pager">
            <button class="ae-btn ae-btn--ghost" :disabled="page <= 0 || loading" @click="prevPage">{{ t('adminEventsView.sidebar.prev') }}</button>
            <span class="ae-side-pager-info">{{ totalPages ? `${page + 1} / ${totalPages}` : page + 1 }}</span>
            <button class="ae-btn ae-btn--ghost" :disabled="!canNextPage || loading" @click="nextPage">{{ t('adminEventsView.sidebar.next') }}</button>
          </div>
          <label class="ae-pagesize">
            <span class="ae-pagesize-label">{{ t('adminEventsView.sidebar.perPage') }}</span>
            <select v-model.number="pageSize" class="ae-select ae-select--compact" :disabled="loading" @change="onPageSizeChange">
              <option v-for="n in PAGE_SIZE_OPTIONS" :key="n" :value="n">{{ n === ALL_PAGE ? 'All' : n }}</option>
            </select>
          </label>
          <div v-if="totalCount != null && eventsCurrent" class="ae-side-help">
            {{ totalCount.toLocaleString(appLocale()) }} {{ t('adminEventsView.sidebar.totalEvents', 'total events') }}
          </div>
        </div>

        <div class="ae-side-section" data-tour="events-saved">
          <div class="ae-side-title">{{ t('adminEventsView.sidebar.savedSearches') }}</div>
          <div v-if="!savedSearches.length" class="ae-side-help">{{ t('adminEventsView.sidebar.noneSaved') }}</div>
          <div v-else class="ae-saved-list">
            <div v-for="s in savedSearches" :key="s.name" class="ae-saved-item">
              <button class="ae-saved-load" @click="loadSaved(s)">{{ s.name }}</button>
              <button class="ae-saved-delete" @click="deleteSaved(s.name)" title="Remove saved search">✕</button>
            </div>
          </div>
          <template v-if="savingSearch">
            <input
              v-model.trim="searchNameInput"
              type="text"
              :placeholder="t('adminEventsView.sidebar.searchNamePh')"
              class="ae-input"
              maxlength="60"
              @keyup.enter="commitSavingSearch"
              @keyup.esc="cancelSavingSearch"
              ref="savingInput"
              autofocus
            />
            <div class="ae-side-actions">
              <button class="ae-btn ae-btn--primary" :disabled="!searchNameInput.trim()" @click="commitSavingSearch">⤓ Save</button>
              <button class="ae-btn ae-btn--ghost" @click="cancelSavingSearch">{{ t('adminEventsView.sidebar.cancel') }}</button>
            </div>
          </template>
          <button v-else class="ae-btn ae-btn--ghost ae-btn--full" :disabled="!filterEventType && !aggregateMode" @click="startSavingSearch">⤓ Save current</button>
        </div>

        <div class="ae-side-section" data-tour="events-export">
          <div class="ae-side-title">EXPORT</div>
          <button class="ae-btn ae-btn--primary ae-btn--full" :disabled="!exportCount" @click="exportJson">⤓ Export {{ exportCount.toLocaleString(appLocale()) }} as JSON</button>
        </div>
      </aside>

      <!-- Main panel -->
      <main class="ae-main" data-tour="events-results">
        <!-- Toolbar -->
        <div class="ae-toolbar" data-tour="events-toolbar">
          <div class="ae-toolbar-left">
            <span class="ae-mono-label">Showing</span>
            <!-- §FESUITE (V0578): counted only under the frame the events were read from -->
            <span class="ae-mono-val" data-testid="ae-showing">{{ lastRefreshAt && eventsCurrent ? events.length : '—' }}</span>
            <span v-if="totalCount != null && eventsCurrent" class="ae-mono-label">of {{ totalCount.toLocaleString(appLocale()) }}</span>
            <span class="ae-mono-label">events from</span>
            <span class="ae-pill" :style="framePillStyle">{{ selectedOption.label }}</span>
            <span v-if="filterEventType && !aggregateMode" class="ae-pill ae-pill--cyan">type: {{ filterEventType }}</span>
            <span v-if="aggregateMode" class="ae-pill ae-pill--cyan" :title="aggregateInput">aggregate: {{ shortDid(aggregateInput) }}</span>
            <template v-if="aggregateMode && chainWindow">
              <span
                class="ae-pill ae-pill--muted"
                :title="t('adminEventsView.chain.windowTitle', 'Chains are fetched in bounded ~30-day windows so million-event aggregates stay responsive. Step through history with older / newer.')"
              >{{ windowLabel }}</span>
              <button class="ae-btn ae-btn--ghost" :disabled="loading" @click="chainOlder">‹ {{ t('adminEventsView.chain.older', 'older') }}</button>
              <button class="ae-btn ae-btn--ghost" :disabled="loading || !chainWindowEnd" @click="chainNewer">{{ t('adminEventsView.chain.newer', 'newer') }} ›</button>
              <button v-if="chainWindowEnd" class="ae-btn ae-btn--ghost" :disabled="loading" @click="chainLatest">{{ t('adminEventsView.chain.latest', 'latest') }}</button>
              <span v-if="chainWalked" class="ae-pill ae-pill--orange" :title="t('adminEventsView.chain.walkedTitle', 'The most recent windows were empty — jumped back to the latest window with activity.')">
                ⇤ {{ t('adminEventsView.chain.walked', 'jumped to latest activity') }}
              </span>
              <span v-if="chainTruncated" class="ae-pill ae-pill--orange"><Icon name="mdi:alert" /> {{ t('adminEventsView.chain.truncated', 'window capped at 10k rows') }}</span>
            </template>
            <span
              v-if="allFetchTruncated"
              class="ae-pill ae-pill--orange"
              :title="`Unfiltered 'All' is bounded to ${UNFILTERED_ALL_GUARD.toLocaleString(appLocale())} rows to keep the page responsive — add a type filter for the complete set.`"
            ><Icon name="mdi:alert" /> capped at {{ UNFILTERED_ALL_GUARD.toLocaleString(appLocale()) }}</span>
          </div>
          <div class="ae-toolbar-right">
            <span class="ae-mono-label">{{ t('common.lastRefresh') }}</span>
            <span class="ae-mono-val">{{ lastRefreshAt || '—' }}</span>
            <button class="ae-btn ae-btn--ghost" :disabled="loading" @click="refresh">↻ {{ t('common.refresh') }}</button>
          </div>
        </div>

        <!-- Loading -->
        <!-- §FESUITE (V0578): a read for another frame is out: the previous frame's events are not drawn under this one -->
        <div v-if="loading && (!events.length || !eventsCurrent)" class="ae-center" data-testid="ae-loading">
          <div class="ae-spinner"></div>
          <p class="ae-loading-text">{{ allFetchProgress ? `Loading all events… ${allFetchProgress.toLocaleString(appLocale())} so far` : 'Querying EventStore…' }}</p>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="ae-center">
          <p class="ae-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
          <button class="ae-btn ae-btn--ghost" @click="refresh">{{ t('adminEventsView.error.retry') }}</button>
        </div>

        <!-- Empty -->
        <div v-else-if="!events.length" class="ae-empty">
          <div class="ae-empty-glyph">∅</div>
          <p class="ae-empty-title">No events match this query</p>
          <p class="ae-empty-sub">
            <template v-if="aggregateMode">
              {{ t('adminEventsView.empty.aggregateWindowed', 'No events for aggregate') }} <code>{{ shortDid(aggregateInput) }}</code>
              <template v-if="chainWindow"> {{ t('adminEventsView.empty.inWindow', 'in window') }} {{ windowLabel }} — {{ t('adminEventsView.empty.stepOlder', 'step "older" to keep searching history.') }}</template>
            </template>
            <template v-else-if="filterEventType">
              No events of type <code>{{ filterEventType }}</code> on {{ selectedOption.label }}.
            </template>
            <template v-else>
              EventStore returned an empty page. Try resetting filters.
            </template>
          </p>
          <div class="ae-side-actions" style="justify-content:center">
            <button v-if="aggregateMode && chainWindow" class="ae-btn ae-btn--primary" @click="chainOlder">‹ {{ t('adminEventsView.chain.older', 'older') }}</button>
            <button class="ae-btn ae-btn--ghost" @click="resetSearch">{{ t('adminEventsView.error.resetFilters') }}</button>
          </div>
        </div>

        <!-- Event list -->
        <div v-else class="ae-list">
          <div
            v-for="(ev, idx) in events"
            :key="ev.id || `${ev.timestamp}-${idx}`"
            class="ae-row"
            :class="{ 'ae-row--expanded': expandedIdx === idx }"
            @click="toggleExpand(idx)"
          >
            <div class="ae-row-head">
              <span class="ae-row-time" :title="ev.timestamp">{{ formatHHMMSS(ev.timestamp) }}</span>
              <span class="ae-row-date" :title="ev.timestamp">{{ formatDate(ev.timestamp) }}</span>
              <span class="ae-row-type-pill" :class="typePillClass(ev.event_type)">{{ ev.event_type }}</span>
              <span v-if="ev.aggregate_id" class="ae-row-agg" :title="ev.aggregate_id">
                <span class="ae-row-agg-key">aggr</span>
                <code>{{ shortDid(ev.aggregate_id) }}</code>
              </span>
              <span v-if="ev.aggregate_type" class="ae-row-agg-type">{{ ev.aggregate_type }}</span>
              <span class="ae-row-spacer"></span>
              <span class="ae-row-caret">{{ expandedIdx === idx ? '▾' : '▸' }}</span>
            </div>

            <!-- Expanded detail -->
            <div v-if="expandedIdx === idx" class="ae-detail" @click.stop>
              <div class="ae-detail-meta">
                <div class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Event ID</span>
                  <span class="ae-detail-val ae-mono">
                    <code>{{ ev.id || '—' }}</code>
                    <button v-if="ev.id" class="ae-icon-btn" @click.stop="copyText(ev.id!)" title="Copy event ID">⎘</button>
                  </span>
                </div>
                <div class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Timestamp</span>
                  <span class="ae-detail-val">{{ formatAbs(ev.timestamp) }}</span>
                </div>
                <div v-if="ev.aggregate_id" class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Aggregate</span>
                  <span class="ae-detail-val ae-mono">
                    <code>{{ ev.aggregate_id }}</code>
                    <button class="ae-icon-btn" @click.stop="copyText(ev.aggregate_id!)" title="Copy aggregate ID">⎘</button>
                    <button class="ae-icon-btn" @click.stop="filterToAggregate(ev.aggregate_id!)" title="Filter to this aggregate">⤴</button>
                  </span>
                </div>
                <div v-if="ev.version != null" class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Schema v</span>
                  <span class="ae-detail-val">{{ ev.version }}</span>
                </div>
                <div v-if="ev.source_service" class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Emitted by</span>
                  <span class="ae-detail-val">{{ ev.source_service }}</span>
                </div>
                <div v-if="ev.seq != null" class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Sequence</span>
                  <span class="ae-detail-val ae-mono">{{ ev.seq }}</span>
                </div>
                <div v-if="ev.idempotency_key" class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Idempotency key</span>
                  <span class="ae-detail-val ae-mono">
                    <code>{{ ev.idempotency_key }}</code>
                    <button class="ae-icon-btn" @click.stop="copyText(ev.idempotency_key!)" title="Copy idempotency key">⎘</button>
                  </span>
                </div>
                <div class="ae-detail-meta-pair">
                  <span class="ae-detail-key">Type</span>
                  <span class="ae-detail-val">
                    {{ ev.event_type }}
                    <button class="ae-icon-btn" @click.stop="filterToType(ev.event_type)" title="Filter to this event type">⤴</button>
                  </span>
                </div>
              </div>

              <div class="ae-detail-section">
                <JsonViewer :data="ev.data || {}" label="Data (event payload)" bordered />
              </div>
              <div v-if="ev.metadata && Object.keys(ev.metadata).length" class="ae-detail-section">
                <JsonViewer :data="ev.metadata" label="Metadata" bordered />
              </div>
              <div v-else class="ae-detail-section ae-detail-meta-pair">
                <span class="ae-detail-key">Metadata</span>
                <span class="ae-detail-val ae-meta-empty">— (none)</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="ae-footer">
          <code>{{ aggregateMode ? '/admin/forensics/search' : '/admin/events/search' }}</code>
          <span> · {{ lastRefreshAt ? events.length : '—' }}<template v-if="totalCount != null"> of {{ totalCount.toLocaleString(appLocale()) }}</template> events shown</span>
          <span> · page {{ page + 1 }}<template v-if="totalPages"> / {{ totalPages }}</template></span>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * AdminEvents — EventStore explorer for admins.
 *
 * Build #6 (2026-05-07) — final build of the strategy doc roadmap.
 * Backend: registry-side admin proxies → EventStore at internal :8200.
 *
 * Features:
 *  - Single event_type filter (server-side; backend returns recent-N when set)
 *  - Aggregate ID search (different endpoint)
 *  - Pagination (offset/limit) when not filtering by event_type or aggregate
 *  - Expandable row with full payload + metadata via shared JsonViewer
 *  - "Filter to this aggregate" / "Filter to this type" actions for quick drilldown
 *  - Saved searches (localStorage)
 *  - JSON export of current view
 *  - URL-bookmarkable via query params
 *  - Theme-aware
 */
import { ref, computed, onMounted, watch } from 'vue'
import { eventStoreAdminService, LOCAL_FRAME, type EventStoreEvent, type SortOrder } from '@/services/api/eventStoreAdmin'
import { useUIStore } from '@/stores/ui'
import { useRoute, useRouter } from 'vue-router'
import JsonViewer from '@/components/common/JsonViewer.vue'
import { useI18n } from '@/composables/useI18n'
import { useAdminFrames, FrameNotConnectedError } from '@/composables/useAdminFrames'
import { fetchAggregateChain, type ChainWindow } from '@/services/api/eventChain'

const { t } = useI18n()
const uiStore = useUIStore()
const route = useRoute()
const router = useRouter()
// §FEDEVENTS 2026-08-03: frames = LOCAL (self-identified — seed letter OR the
// registry card's own name, so hetzner-frame & friends label themselves) plus
// ONLY the sibling frames holding a live Multi-Frame Console session. A foreign
// frame is read through ITS OWN registry via the same-origin peer proxy — this
// view never touches a foreign EventStore URL or key directly.
const { selectableFrames, resolveOption, frameGet, ensureTargets } = useAdminFrames()

// Common event types — populated from CLAUDE.md PART 3 + observed prod
const COMMON_EVENT_TYPES = [
  'TokensTransferred',
  'TokensIssued',
  'TokensStaked',
  'TransactionFeeCollected',
  'CrossRegistryTransferCompleted',
  'CrossFrameTransferInitiated',
  'CrossFrameTransferSettled',
  'CrossFrameTransferRefunded',
  'A2APaymentSettled',
  'A2APaymentReleased',
  'A2APaymentExpired',
  'AgentSuspended',
  'AgentReinstated',
  'AgentSlashed',
  'BalanceCorrected',
  'RewardsDistributed',
  'DisputeFiled',
  'DisputeResolved',
  'AttestationCreated',
  'AttestationRevoked',
  'FundingRequestApproved',
  'FundingRequestRejected',
  'ProposalTallied',
  'VoteCast',
  'WebhookDelivered',
  'WebhookDeliveryFailed',
  'SupplyInvariantBreach',
  'PeerUrlSelfHealed',
  'BridgeTransferInitiated',
  'BridgeTransferExpired',
  'OperatorApplicationApproved',
  'OperatorApplicationRevoked',
  'FederationLicenseSuspended',
  'FederationLicenseReinstated',
  'AgentMtlsEnrolled',
]

// State
// rawEvents holds either the current SERVER page (search mode) or the FULL
// aggregate result set (aggregate mode). The rendered `events` (computed below)
// derives from it — aggregate mode is paginated client-side so the DOM never
// v-fors over the entire set (the 100k+-row freeze this view used to hit).
const rawEvents = ref<EventStoreEvent[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const expandedIdx = ref<number | null>(null)

const filterEventType = ref<string>('')
const aggregateInput = ref<string>('')
const aggregateMode = ref(false)  // true while we're displaying byAggregate results
const page = ref(0)
// User-adjustable page size (was a hardcoded const). Bounded by the search
// proxy's server-side cap of 1000.
// "All" is a sentinel page size — renders the whole fetched set on one page.
const ALL_PAGE = 1_000_000_000
const PAGE_SIZE_OPTIONS = [25, 50, 100, 250, 500, 1000, ALL_PAGE] as const
const pageSize = ref(100)
// "All" loop-fetches the WHOLE set in CHUNK-sized hops (the EventStore route +
// proxy both cap a single request at 10000). A *filtered* "All" pulls the
// entire type — the real 130k/millions, no artificial cap. An *unfiltered*
// "All" is the whole ledger (millions); it's bounded by UNFILTERED_ALL_GUARD so
// the whole-ledger case can't hang the tab, with a visible "capped" notice
// telling the operator to add a type filter for the complete set.
const ALL_FETCH_CHUNK = 10000
const UNFILTERED_ALL_GUARD = 200_000
// Absolute failsafe — a paging bug must never spin forever.
const ALL_FETCH_HARD_MAX = 5_000_000
// Rows pulled so far during an "All" loop (drives the loading text); set true
// when an unfiltered "All" stops at the guard.
const allFetchProgress = ref(0)
const allFetchTruncated = ref(false)
// §FEDEVENTS: selected frame KEY — LOCAL_FRAME sentinel or a connected session
// key. Default is ALWAYS local (the old uiStore-seeded 'A' default landed
// frame-b/c/hetzner admins on a FOREIGN frame's error state out of the box).
// uiStore.activeFrame / URL ?frame= are honored in onMounted only when they
// resolve to a frame that is actually selectable right now.
const selectedKey = ref<string>(LOCAL_FRAME)
const selectedOption = computed(() => resolveOption(selectedKey.value))
// §FESUITE (V0578): the frame the events on screen were read from. The frame buttons stay live during a read (the other
// controls do not), so a switch left the previous frame's events under the new frame's button ("Showing 50 events from
// ASIA") while its read was out, a slower read (an "All" loop over a large ledger) landing after a later one replaced it
// under the wrong frame, and an "All" loop switched mid-way read its remaining chunks from the new frame into the same
// list. An answer is drawn only under the frame it was read for; a superseded read never lands, and a loop stops.
const eventsFor = ref<string | null>(null)
const eventsCurrent = computed(() => eventsFor.value === selectedKey.value)
let readSeq = 0
const framePillStyle = computed(() => {
  const hex = selectedOption.value.accentHex
  return { background: `${hex}1f`, color: hex, borderColor: `${hex}55` }
})
// Bug fix (2026-05-07): sort order for unfiltered pagination. Defaults to
// 'desc' so the first page shows the most recent events; 'asc' preserves
// the legacy genesis-first browsing path.
const sortOrder = ref<SortOrder>('desc')
// The EventStore serves a TYPE-FILTERED search newest-first only (index-driven);
// reflect that honestly instead of silently ignoring an 'asc' choice (§FEDEVENTS
// — this was one of the "search doesn't fully work" reports).
const effectiveSort = computed<SortOrder>(() => (filterEventType.value ? 'desc' : sortOrder.value))

// ── Aggregate chain windowing (§FEDEVENTS) ──────────────────────────────
// Chains ride the indexed forensics search in bounded ~30d windows — the old
// unbounded /events/aggregate rail dies on production aggregates (1.4M events
// measured). null windowEnd = the latest window (auto-walks back to activity).
const chainWindowEnd = ref<Date | null>(null)
const chainWindow = ref<ChainWindow | null>(null)
const chainTruncated = ref(false)
const chainWalked = ref(0)
const windowLabel = computed(() => {
  if (!chainWindow.value) return ''
  const fmt = (iso: string) => new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
  return `${fmt(chainWindow.value.start)} → ${fmt(chainWindow.value.end)}`
})

// ── Derived view state (pagination + dynamic filter) ──────────────
// Rendered rows. Search mode shows the server page as-is; aggregate mode slices
// the full set client-side so the DOM only ever holds one page.
// Paginate CLIENT-SIDE only when we hold the full set locally: aggregate mode or
// the "All" page size (which loop-fetches everything). Numeric pages — filtered
// OR unfiltered — are true server-side offset paging now that the EventStore
// honours offset for a single event_type (see refresh()).
const clientPaginate = computed(
  () => aggregateMode.value || pageSize.value === ALL_PAGE,
)
const sliceSize = computed(() => (pageSize.value === ALL_PAGE ? Number.MAX_SAFE_INTEGER : pageSize.value))
const events = computed<EventStoreEvent[]>(() =>
  clientPaginate.value
    ? rawEvents.value.slice(page.value * sliceSize.value, (page.value + 1) * sliceSize.value)
    : rawEvents.value,
)
// Total is known whenever we hold the full set (client-paginate). Pure server
// paging has no count, so it stays null and the pager uses the
// "page came back full ⇒ assume more" heuristic.
const totalCount = computed<number | null>(() =>
  clientPaginate.value ? rawEvents.value.length : null,
)
const totalPages = computed<number | null>(() =>
  clientPaginate.value ? Math.max(1, Math.ceil(rawEvents.value.length / sliceSize.value)) : null,
)
// Export always emits the full backing set (whole aggregate / current server page).
const exportCount = computed<number>(() => (eventsCurrent.value ? rawEvents.value.length : 0))

// Event-type filter options — sourced live from the emission-policy table
// (~170 types) unioned with EventStore stats keys + the curated fallback, so
// the dropdown lists every known event type. Names only (valid across frames).
const dynamicEventTypes = ref<string[]>([])
const eventTypeOptions = computed<string[]>(() =>
  Array.from(new Set<string>([...dynamicEventTypes.value, ...COMMON_EVENT_TYPES])).sort((a, b) =>
    a.localeCompare(b),
  ),
)

// Saved searches in localStorage
interface SavedSearch { name: string; eventType?: string; aggregateId?: string }
const savedSearches = ref<SavedSearch[]>([])

const SAVED_KEY = 'admin_events_saved_searches'

onMounted(() => {
  // Load saved searches
  try {
    const raw = localStorage.getItem(SAVED_KEY)
    if (raw) savedSearches.value = JSON.parse(raw)
  } catch { /* expected */ }

  // Restore from URL params. A ?frame= (or the persisted uiStore.activeFrame)
  // is honored ONLY when it resolves to a selectable frame right now — console
  // sessions are memory-only, so after a reload every foreign choice honestly
  // falls back to LOCAL instead of an error state (§FEDEVENTS).
  const qType = route.query.event_type as string | undefined
  const qAggr = route.query.aggregate_id as string | undefined
  void ensureTargets()
  const qFrame = route.query.frame as string | undefined
  const wanted = qFrame || uiStore.activeFrame
  if (wanted) {
    const opt = resolveOption(wanted)
    if (opt.isLocal || selectableFrames.value.some((o) => o.key === opt.key)) {
      selectedKey.value = opt.key
    }
  }
  const qSort = (route.query.sort as string | undefined)?.toLowerCase()
  if (qSort === 'asc' || qSort === 'desc') sortOrder.value = qSort as SortOrder
  const qPageSize = Number(route.query.page_size)
  if ((PAGE_SIZE_OPTIONS as readonly number[]).includes(qPageSize)) pageSize.value = qPageSize

  // Populate the event-type filter from live store stats (best-effort).
  void loadEventTypes()

  if (qAggr) {
    aggregateInput.value = qAggr
    aggregateMode.value = true
    void searchByAggregate()
  } else if (qType) {
    filterEventType.value = qType
    void refresh()
  } else {
    void refresh()
  }
})

watch([filterEventType, aggregateMode, selectedKey, sortOrder, pageSize], () => {
  // Update URL when filters change
  const q: Record<string, any> = {}
  if (filterEventType.value && !aggregateMode.value) q.event_type = filterEventType.value
  if (aggregateMode.value && aggregateInput.value) q.aggregate_id = aggregateInput.value
  if (!selectedOption.value.isLocal) q.frame = selectedKey.value
  if (sortOrder.value !== 'desc') q.sort = sortOrder.value
  if (pageSize.value !== 100) q.page_size = pageSize.value
  router.replace({ query: q }).catch(() => {})
})

function setFrame(key: string) {
  if (selectedKey.value === key) return
  selectedKey.value = key
  // Keep the cross-view frame memory (Treasury etc.) in sync, by frame key (§FEFRAME W2).
  uiStore.setActiveFrame(key)
  page.value = 0
  expandedIdx.value = null
  chainWindowEnd.value = null
  // Re-query against the new frame using current filter settings
  if (aggregateMode.value && aggregateInput.value) {
    void searchByAggregate()
  } else {
    void refresh()
  }
}

function setSortOrder(s: SortOrder) {
  if (sortOrder.value === s) return
  if (s === 'asc' && filterEventType.value) return  // index serves typed queries desc-only
  sortOrder.value = s
  page.value = 0
  expandedIdx.value = null
  // Sort only meaningful for unfiltered list path; aggregate mode is fine to skip.
  if (!aggregateMode.value) void refresh()
}

// Aggregate mode knows its total, so Next is gated precisely; search mode falls
// back to "the page came back full ⇒ there's probably more".
const canNextPage = computed(() =>
  clientPaginate.value
    ? page.value + 1 < (totalPages.value ?? 1)
    : rawEvents.value.length === pageSize.value,
)

// Frame-routed EventStore fetch (§FEDEVENTS): local frame → this registry with
// frame=local; foreign frame → that frame's OWN registry via the same-origin
// peer proxy + its session admin token (so events are never mislabelled or read
// with the wrong store credentials). A missing session throws
// FrameNotConnectedError, surfaced as the actionable connect message.
async function frameAwareSearch(
  params: { limit: number; offset: number; event_type?: string; sort_order: SortOrder },
  frameKey: string = selectedKey.value,
): Promise<{ events: EventStoreEvent[]; count: number }> {
  const qp: Record<string, any> = {
    limit: params.limit, offset: params.offset, sort_order: params.sort_order,
  }
  if (params.event_type) qp.event_type = params.event_type
  const data = await frameGet<any>(frameKey, 'admin/events/search', qp)
  return { events: (data?.events ?? []) as EventStoreEvent[], count: data?.count ?? 0 }
}

async function refresh() {
  if (aggregateMode.value && aggregateInput.value) {
    return searchByAggregate()
  }
  const seq = ++readSeq
  const asked = selectedKey.value
  loading.value = true
  error.value = null
  allFetchTruncated.value = false
  try {
    if (pageSize.value === ALL_PAGE) {
      // "All" → loop-fetch the entire set. Filtered = the whole type (uncapped);
      // unfiltered = the whole ledger, bounded by UNFILTERED_ALL_GUARD.
      const all = await fetchAllPages(seq, asked)
      if (seq !== readSeq) return   // superseded (another frame or query): never lands
      rawEvents.value = all
    } else {
      // Numeric page → true server-side offset paging (works filtered AND not,
      // now the EventStore honours offset for a single event_type).
      const result = await frameAwareSearch({
        limit: pageSize.value,
        offset: page.value * pageSize.value,
        event_type: filterEventType.value || undefined,
        sort_order: effectiveSort.value,
      }, asked)
      if (seq !== readSeq) return
      rawEvents.value = result.events
    }
    eventsFor.value = asked
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    if (seq !== readSeq) return
    eventsFor.value = null
    const msg = e instanceof FrameNotConnectedError
      ? e.message
      : e?.response?.data?.detail || e?.message || 'Failed to load events'
    error.value = msg
    rawEvents.value = []
    lastRefreshAt.value = ''  // §FESUITE: the list was emptied, so its count is not known (it read 0)
    if (!(e instanceof FrameNotConnectedError)) uiStore.showError?.('EventStore', msg)
  } finally {
    if (seq === readSeq) {
      loading.value = false
      allFetchProgress.value = 0
    }
  }
}

// Loop-fetch every page of the current query into one array, so "All"/Export
// hold the REAL full set (Commander: the real 130k/millions). Terminates when a
// page returns fewer than CHUNK rows (last page). Filtered "All" is unbounded
// (only the ALL_FETCH_HARD_MAX failsafe); unfiltered "All" stops at
// UNFILTERED_ALL_GUARD (whole-ledger guard) and flags allFetchTruncated.
// De-dupes by id so a concurrent insert at a chunk boundary can't double-count;
// best-effort snapshot under live writes.
async function fetchAllPages(seq: number, frameKey: string): Promise<EventStoreEvent[]> {
  const all: EventStoreEvent[] = []
  const seen = new Set<string>()
  const filtered = !!filterEventType.value
  const cap = filtered ? ALL_FETCH_HARD_MAX : UNFILTERED_ALL_GUARD
  let offset = 0
  for (;;) {
    const result = await frameAwareSearch({
      limit: ALL_FETCH_CHUNK,
      offset,
      event_type: filterEventType.value || undefined,
      sort_order: effectiveSort.value,
    }, frameKey)
    if (seq !== readSeq) break   // superseded mid-loop: stop, never read the rest from another frame
    for (const ev of result.events) {
      if (ev.id) {
        if (seen.has(ev.id)) continue
        seen.add(ev.id)
      }
      all.push(ev)
    }
    allFetchProgress.value = all.length
    if (result.events.length < ALL_FETCH_CHUNK) break  // last page
    offset += ALL_FETCH_CHUNK
    if (all.length >= cap) { allFetchTruncated.value = true; break }
  }
  return all
}

// §FEDEVENTS: the aggregate chain rides the indexed forensics search in bounded
// ~30d windows (the old unbounded /events/aggregate rail cannot survive
// production aggregates — 1.4M events measured on one DID). The first search
// auto-walks back through empty windows to the latest activity; the toolbar
// steppers move through history explicitly.
async function searchByAggregate(opts?: { autoWalk?: boolean }) {
  if (!aggregateInput.value.trim()) return
  const seq = ++readSeq
  const asked = selectedKey.value
  loading.value = true
  error.value = null
  aggregateMode.value = true
  filterEventType.value = ''  // chained state fix: a type filter never applies here
  page.value = 0  // start at page 1 of the client-side-paginated set
  try {
    const result = await fetchAggregateChain(
      (params) => frameGet<any>(asked, 'admin/forensics/search', params),
      aggregateInput.value.trim(),
      { windowEnd: chainWindowEnd.value ?? undefined, autoWalk: opts?.autoWalk ?? (chainWindowEnd.value == null) },
    )
    if (seq !== readSeq) return   // superseded (another frame or search): never lands
    // A page error with rows already fetched = PARTIAL window (warn, keep rows);
    // only a zero-row error is a real failure.
    if (result.error && !result.events.length) throw new Error(result.error)
    rawEvents.value = result.events
    eventsFor.value = asked
    chainWindow.value = result.window
    chainTruncated.value = result.truncated
    chainWalked.value = result.walkedBack
    if (result.walkedBack > 0) chainWindowEnd.value = new Date(result.window.end)
    if (result.error) uiStore.showError?.('EventStore', `Chain window partially loaded: ${result.error}`)
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    const msg = e instanceof FrameNotConnectedError
      ? e.message
      : e?.response?.data?.detail || e?.message || 'Failed to load aggregate events'
    if (seq !== readSeq) return
    eventsFor.value = null
    error.value = msg
    rawEvents.value = []
    lastRefreshAt.value = ''  // §FESUITE: the list was emptied, so its count is not known (it read 0)
    if (!(e instanceof FrameNotConnectedError)) uiStore.showError?.('EventStore', msg)
  } finally {
    if (seq === readSeq) loading.value = false
  }
}

function chainOlder() {
  if (!chainWindow.value) return
  chainWindowEnd.value = new Date(chainWindow.value.start)
  void searchByAggregate({ autoWalk: false })
}
function chainNewer() {
  if (!chainWindow.value) return
  const next = new Date(chainWindow.value.end).getTime() + 30 * 86_400_000
  chainWindowEnd.value = next >= Date.now() ? null : new Date(next)
  void searchByAggregate({ autoWalk: false })
}
function chainLatest() {
  chainWindowEnd.value = null
  void searchByAggregate({ autoWalk: true })
}

async function loadEventTypes() {
  // Emission policies are the authoritative source (~170 types); EventStore
  // stats keys augment when populated (empty in prod today). Both service calls
  // swallow their own errors, so the curated COMMON_EVENT_TYPES fallback (in the
  // eventTypeOptions computed) always guarantees a usable list.
  const [policyTypes, stats] = await Promise.all([
    eventStoreAdminService.emissionPolicyTypes(),
    eventStoreAdminService.stats(),
  ])
  dynamicEventTypes.value = [...policyTypes, ...Object.keys(stats?.event_counts ?? {})]
}

function reloadOnFilterChange() {
  page.value = 0
  aggregateMode.value = false
  void refresh()
}

function resetSearch() {
  filterEventType.value = ''
  aggregateInput.value = ''
  aggregateMode.value = false
  chainWindowEnd.value = null
  chainWindow.value = null
  chainTruncated.value = false
  chainWalked.value = 0
  page.value = 0
  expandedIdx.value = null
  void refresh()
}

function toggleExpand(idx: number) {
  expandedIdx.value = expandedIdx.value === idx ? null : idx
}

function nextPage() {
  if (!canNextPage.value) return
  page.value += 1
  expandedIdx.value = null
  // Client-paginated modes (aggregate / event_type filter / All) re-slice
  // reactively; unfiltered server paging pulls the next page.
  if (!clientPaginate.value) void refresh()
}
function prevPage() {
  if (page.value <= 0) return
  page.value -= 1
  expandedIdx.value = null
  if (!clientPaginate.value) void refresh()
}
// Page-size selector. Reset to page 1; search mode refetches with the new limit,
// aggregate mode just re-slices the set it already holds.
function onPageSizeChange() {
  page.value = 0
  expandedIdx.value = null
  if (!aggregateMode.value) void refresh()
}

function filterToAggregate(aggrId: string) {
  aggregateInput.value = aggrId
  aggregateMode.value = true
  filterEventType.value = ''
  expandedIdx.value = null
  chainWindowEnd.value = null   // fresh aggregate → latest window, auto-walk on
  void searchByAggregate()
}
function filterToType(type: string) {
  filterEventType.value = type
  aggregateMode.value = false
  aggregateInput.value = ''
  page.value = 0
  expandedIdx.value = null
  void refresh()
}

// ── Saved searches ───────────────────────────────────
// Polish 2026-05-07: replaced native `prompt()` with inline input flow.
// Click "Save current" → toggles `savingSearch=true` → shows input row →
// Enter or Save commits, ESC or Cancel aborts.
const savingSearch = ref(false)
const searchNameInput = ref('')

function startSavingSearch() {
  searchNameInput.value = ''
  savingSearch.value = true
}
function cancelSavingSearch() {
  savingSearch.value = false
  searchNameInput.value = ''
}
function commitSavingSearch() {
  const name = searchNameInput.value.trim()
  if (!name) {
    cancelSavingSearch()
    return
  }
  const entry: SavedSearch = { name }
  if (filterEventType.value && !aggregateMode.value) entry.eventType = filterEventType.value
  if (aggregateMode.value) entry.aggregateId = aggregateInput.value
  savedSearches.value = [...savedSearches.value.filter(s => s.name !== entry.name), entry]
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(savedSearches.value)) } catch { /* expected */ }
  uiStore.showSuccess?.('Saved', `"${name}" saved.`)
  cancelSavingSearch()
}
function loadSaved(s: SavedSearch) {
  filterEventType.value = s.eventType || ''
  aggregateInput.value = s.aggregateId || ''
  aggregateMode.value = !!s.aggregateId
  page.value = 0
  expandedIdx.value = null
  void refresh()
}
function deleteSaved(name: string) {
  savedSearches.value = savedSearches.value.filter(s => s.name !== name)
  try { localStorage.setItem(SAVED_KEY, JSON.stringify(savedSearches.value)) } catch { /* expected */ }
}

// ── Export ─────────────────────────────────────────
function exportJson() {
  if (!rawEvents.value.length) return
  const payload = {
    exported_at: new Date().toISOString(),
    filter: {
      event_type: filterEventType.value || null,
      aggregate_id: aggregateMode.value ? aggregateInput.value : null,
      page: aggregateMode.value ? null : page.value,
    },
    count: rawEvents.value.length,
    events: rawEvents.value,
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const tag = filterEventType.value || (aggregateMode.value ? 'aggregate' : 'all')
  a.download = `eventstore-${tag}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 4000)
  uiStore.showSuccess?.('Exported', `${rawEvents.value.length} events downloaded.`)
}

// ── Helpers ────────────────────────────────────────

function shortDid(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 30) return s
  return `${s.slice(0, 16)}…${s.slice(-6)}`
}
function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
function formatHHMMSS(iso: string | Date | null | undefined): string {
  if (!iso) return '—'
  const d = typeof iso === 'string' ? new Date(iso) : iso
  return d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
}

/** Color-code event type pill by domain prefix. */
function typePillClass(t: string): string {
  if (!t) return 'ae-pill--muted'
  const lower = t.toLowerCase()
  if (lower.includes('token') || lower.includes('reward') || lower.includes('fee'))      return 'ae-pill--green'
  if (lower.includes('cross') || lower.includes('bridge'))                                return 'ae-pill--cyan'
  if (lower.includes('agent') || lower.includes('mtls'))                                  return 'ae-pill--violet'
  if (lower.includes('vote') || lower.includes('proposal') || lower.includes('tally'))    return 'ae-pill--violet'
  if (lower.includes('attestation') || lower.includes('peer') || lower.includes('federation')) return 'ae-pill--indigo'
  if (lower.includes('webhook'))                                                          return 'ae-pill--orange'
  if (lower.includes('dispute') || lower.includes('slash') || lower.includes('breach'))   return 'ae-pill--red'
  if (lower.includes('a2a') || lower.includes('payment'))                                 return 'ae-pill--cyan'
  if (lower.includes('balance'))                                                          return 'ae-pill--green'
  if (lower.includes('funding'))                                                          return 'ae-pill--cyan'
  return 'ae-pill--muted'
}

async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}
</script>

<style scoped>
.ae {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* ── Ambient ─────────────────────────────────────────────── */
.ae-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.ae-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.ae-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.ae-glow-1 { width: 420px; height: 420px; background: rgba(var(--cyan-rgb), 0.6); top: -100px; right: -80px; }
.ae-glow-2 { width: 320px; height: 320px; background: rgba(168, 85, 247, 0.4); bottom: -60px; left: -100px; }

/* ── Hero ───────────────────────────────────────────────── */
.ae-hero {
  position: relative;
  z-index: 1;
  padding: 36px 32px 18px;
}
.ae-hero-inner { max-width: 1280px; margin: 0 auto; }
.ae-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.ae-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.ae-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.4rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.ae-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.ae-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
  line-height: 1.5;
  max-width: 60rem;
}

/* ── Body layout ────────────────────────────────────────── */
.ae-body {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 1.25rem;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
}

/* ── Sidebar ────────────────────────────────────────────── */
.ae-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.ae-side-section {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 0.85rem 0.95rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.ae-side-title {
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: var(--cyan);
  text-transform: uppercase;
}
.ae-side-help {
  font-family: var(--mono);
  font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.5);
  line-height: 1.5;
}
.ae-input, .ae-select {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  color: rgba(255, 255, 255, 0.9);
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 0.7rem;
  padding: 6px 9px;
  outline: none;
  transition: border-color 0.15s;
}
.ae-input:focus, .ae-select:focus {
  border-color: rgba(var(--cyan-rgb), 0.55);
}
.ae-side-actions { display: flex; gap: 0.4rem; flex-wrap: wrap; }
.ae-side-pager {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.ae-side-pager-info {
  flex: 1;
  text-align: center;
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--cyan);
}

/* Per-page size selector — sits under the pager in the PAGE section. */
.ae-pagesize {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.1rem;
}
.ae-pagesize-label {
  font-family: var(--mono);
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.5);
  text-transform: uppercase;
}
.ae-select--compact {
  width: auto;
  min-width: 4.5rem;
  padding: 4px 8px;
  font-size: 0.68rem;
}

/* ── Frame switch (Build #6.1) ────────────────────── */
.ae-frame-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
  padding: 3px;
}
.ae-frame-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  background: transparent;
  border: none;
  border-radius: 4px;
  padding: 6px 10px;
  cursor: pointer;
  font-family: var(--mono);
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
  text-transform: uppercase;
}
.ae-frame-btn:hover {
  color: rgba(255, 255, 255, 0.95);
  background: rgba(var(--cyan-rgb), 0.06);
}
.ae-frame-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  box-shadow: inset 0 0 0 1px rgba(var(--cyan-rgb), 0.35);
}
.ae-frame-dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}
/* §FEDEVENTS: dot colors ride inline accentHex now (dynamic frame list). */
.ae-frame-switch--solo { grid-template-columns: 1fr; }
.ae-connect-link {
  font-family: var(--mono);
  font-size: 0.62rem;
  color: rgba(var(--cyan-rgb), 0.75);
  text-decoration: none;
  margin-top: 0.15rem;
}
.ae-connect-link:hover { color: rgba(var(--cyan-rgb), 1); text-decoration: underline; }

.ae-saved-list {
  display: flex; flex-direction: column; gap: 0.25rem;
  max-height: 12rem;
  overflow-y: auto;
}
.ae-saved-item {
  display: flex; align-items: center; gap: 0.3rem;
  background: rgba(var(--cyan-rgb), 0.04);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 4px;
  padding: 3px 6px;
}
.ae-saved-load {
  flex: 1;
  background: transparent;
  border: none;
  text-align: left;
  cursor: pointer;
  color: rgba(var(--cyan-rgb), 0.95);
  font-family: var(--mono);
  font-size: 0.7rem;
  padding: 2px 4px;
}
.ae-saved-load:hover { color: rgba(var(--cyan-rgb), 1); }
.ae-saved-delete {
  background: transparent;
  border: 1px solid transparent;
  color: rgba(255, 51, 102, 0.5);
  cursor: pointer;
  font-size: 0.7rem;
  padding: 1px 4px;
  border-radius: 3px;
}
.ae-saved-delete:hover {
  color: var(--nc-danger);
  border-color: rgba(255, 51, 102, 0.3);
}

/* ── Main panel ─────────────────────────────────────── */
.ae-main {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.ae-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.85rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.ae-toolbar-left, .ae-toolbar-right {
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
}

.ae-mono-label {
  font-family: var(--mono);
  font-size: 0.6rem;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
}
.ae-mono-val {
  font-family: var(--mono);
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--cyan);
}

.ae-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: var(--mono);
  font-size: 0.65rem;
  letter-spacing: 0.08em;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.ae-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.ae-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
}
.ae-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
}
.ae-btn--primary {
  background: rgba(var(--cyan-rgb), 0.18);
  border-color: rgba(var(--cyan-rgb), 0.55);
  color: rgba(var(--cyan-rgb), 1);
}
.ae-btn--primary:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.3); }
.ae-btn--full { width: 100%; justify-content: center; }

.ae-pill {
  font-family: var(--mono);
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
  text-transform: uppercase;
}
.ae-pill--cyan   { background: rgba(var(--cyan-rgb), 0.1); color: rgba(var(--cyan-rgb), 1); border-color: rgba(var(--cyan-rgb), 0.3); }
.ae-pill--green  { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.ae-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.ae-pill--amber  { background: rgba(255, 157, 60, 0.1); color: #ff9d3c; border-color: rgba(255, 157, 60, 0.3); }
.ae-pill--indigo { background: rgba(99, 102, 241, 0.1); color: #a5b4fc; border-color: rgba(99, 102, 241, 0.3); }
.ae-pill--orange { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }
.ae-pill--red    { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger); border-color: rgba(255, 51, 102, 0.3); }
.ae-pill--muted  { background: rgba(var(--cyan-rgb), 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--cyan-rgb), 0.18); }

/* ── Center / loading / error ──────────────────────── */
.ae-center {
  text-align: center;
  padding: 4rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 6px;
}
.ae-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: ae-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes ae-spin { to { transform: rotate(360deg); } }
.ae-loading-text {
  font-family: var(--mono);
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.ae-error-text {
  font-family: var(--mono);
  font-size: 0.85rem;
  color: var(--nc-danger);
}

/* ── Empty ──────────────────────────────────────── */
.ae-empty {
  text-align: center;
  padding: 3rem 1rem;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.ae-empty-glyph {
  font-size: 2.4rem;
  color: rgba(var(--cyan-rgb), 0.4);
  font-family: var(--mono);
  margin-bottom: 0.3rem;
}
.ae-empty-title {
  font-family: var(--mono);
  font-size: 0.95rem;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.4rem;
}
.ae-empty-sub {
  font-family: var(--mono);
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.5);
  max-width: 32rem;
  line-height: 1.5;
  margin-bottom: 0.7rem;
}
.ae-empty-sub code {
  background: rgba(var(--cyan-rgb), 0.1);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── Event list ────────────────────────────── */
.ae-list {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  /* Page-level scroll instead of nested scroll — better for keyboard nav,
     screen readers, and full-page screenshot capture. */
}

.ae-row {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.ae-row:hover { background: rgba(var(--cyan-rgb), 0.04); border-color: rgba(var(--cyan-rgb), 0.25); }
.ae-row--expanded {
  background: rgba(var(--cyan-rgb), 0.06);
  border-color: rgba(var(--cyan-rgb), 0.4);
}

.ae-row-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  flex-wrap: wrap;
}
.ae-row-time {
  font-family: var(--mono);
  font-size: 0.72rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.ae-row-date {
  font-family: var(--mono);
  font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.5);
}
.ae-row-type-pill {
  font-family: var(--mono);
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 7px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.ae-row-agg {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-family: var(--mono);
  font-size: 0.65rem;
}
.ae-row-agg-key {
  font-size: 0.55rem;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
}
.ae-row-agg code {
  background: rgba(var(--cyan-rgb), 0.05);
  padding: 1px 4px;
  border-radius: 3px;
  color: rgba(255, 255, 255, 0.8);
}
.ae-row-agg-type {
  font-family: var(--mono);
  font-size: 0.6rem;
  color: #aa5af7;  /* §FESUITE: 4.87:1 on its tint (rgba(168,85,247,0.85) was 3.7:1) */
  background: rgba(168, 85, 247, 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid rgba(168, 85, 247, 0.2);
}
.ae-row-spacer { flex: 1; }
.ae-row-caret {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: rgba(var(--cyan-rgb), 0.6);
}

/* ── Detail panel ──────────────────────────── */
.ae-detail {
  padding: 0.6rem 0.85rem 0.85rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  cursor: default;
}
.ae-detail-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.4rem 0.85rem;
}
.ae-detail-meta-pair {
  display: flex; flex-direction: column; gap: 0.15rem;
}
.ae-detail-key {
  font-family: var(--mono);
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase;
  font-weight: 600;
}
.ae-detail-val {
  font-family: var(--mono);
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 0.35rem;
}
.ae-detail-val code {
  background: rgba(var(--cyan-rgb), 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  word-break: break-all;
  font-size: 0.65rem;
}
.ae-mono { font-family: var(--mono); }

.ae-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace;
  font-size: 0.7rem;
  padding: 0 5px;
  cursor: pointer;
  transition: all 0.12s;
}
.ae-icon-btn:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}

.ae-detail-section { margin-top: 0.2rem; }

/* ── Footer ───────────────────────────────── */
.ae-footer {
  margin-top: 0.85rem;
  padding-top: 0.6rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
  font-family: var(--mono);
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
}
.ae-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── Responsive ───────────────────────────── */
@media (max-width: 1024px) {
  .ae-body { grid-template-columns: 1fr; }
  .ae-sidebar { order: 2; }
  .ae-main { order: 1; }
}
@media (max-width: 768px) {
  .ae-hero { padding: 24px 16px 12px; }
  .ae-h1 { font-size: 1.5rem; }
  .ae-body { padding: 0 16px; }
  .ae-row-head { flex-wrap: wrap; gap: 0.35rem; }
}
</style>
