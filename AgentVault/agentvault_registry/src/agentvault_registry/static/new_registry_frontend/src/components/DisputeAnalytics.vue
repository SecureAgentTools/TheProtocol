<template>
  <div class="da-view">
    <div class="da-header">
      <h2 class="da-title">Dispute Analytics</h2>
      <p class="da-sub">Resolution metrics · category patterns · volume trends</p>
    </div>

    <!-- §FESUITE (V0578): this tab draws what the disputes list and the stats answered, and nothing it did not read. It
         read the store's zeros whatever its reads did (0.0%, "No disputes on record", a 0/0/0/0 ruling breakdown over a
         failed list), and two trends were literals: "+5.2%" whenever any dispute existed, "↓ 2h" always. Nothing here
         reads a trend, so those deltas are gone. -->
    <ReadFailedNotice v-if="listFailed && !listKnown" data-testid="da-read-failed" :retry="retry"
      text="The disputes could not be read just now, so nothing here has been measured." />
    <ReadFailedNotice v-else-if="listFailed" dense data-testid="da-stale" :retry="retry"
      text="The latest read of the disputes failed. The figures here are from the last read that answered." />

    <!-- Metric cards -->
    <div class="da-metrics">
      <div class="da-metric-card">
        <div class="da-metric-card__accent" style="background:rgb(34,197,94)"></div>
        <div class="da-metric-card__top"></div>
        <div class="da-metric-card__value" data-testid="da-resolution-rate">{{ statsRead && stats.resolution_rate !== null ? stats.resolution_rate.toFixed(1) + '%' : '—' }}</div>
        <div class="da-metric-card__label">Resolution Rate</div>
      </div>

      <div class="da-metric-card">
        <div class="da-metric-card__accent" style="background:rgb(167,139,250)"></div>
        <div class="da-metric-card__top"></div>
        <div class="da-metric-card__value">{{ statsRead && stats.average_resolution_time !== null ? stats.average_resolution_time + 'h' : '—' }}</div>
        <div class="da-metric-card__label">Avg Resolution Time</div>
      </div>

      <div class="da-metric-card">
        <div class="da-metric-card__accent" style="background:rgb(59,130,246)"></div>
        <div class="da-metric-card__top">
          <span v-if="listKnown" class="da-metric-card__delta da-neutral">{{ escalationRate.toFixed(1) }}%</span>
        </div>
        <div class="da-metric-card__value">{{ listKnown ? escalatedCount : '—' }}</div>
        <div class="da-metric-card__label">Escalated Cases</div>
      </div>

      <div class="da-metric-card">
        <div class="da-metric-card__accent" style="background:rgb(249,115,22)"></div>
        <div class="da-metric-card__top">
          <span v-if="listKnown" class="da-metric-card__delta da-neutral">{{ repeatOffenders }} repeat</span>
        </div>
        <div class="da-metric-card__value">{{ listKnown ? uniqueParties : '—' }}</div>
        <div class="da-metric-card__label">Unique Parties</div>
      </div>
    </div>

    <!-- Charts row -->
    <div class="da-charts">

      <!-- Disputes Over Time — 14-day bar chart -->
      <div class="da-panel">
        <div class="da-panel__header">
          Disputes Over Time
          <span class="da-panel__sub">last 14 days</span>
        </div>
        <div v-if="timelineBars.some(b => b.value > 0)" class="da-chart-area">
          <div class="da-chart-bars">
            <div
              v-for="(bar, i) in timelineBars"
              :key="i"
              class="da-bar-col"
              :title="`${bar.label}: ${bar.value} dispute${bar.value !== 1 ? 's' : ''}`"
            >
              <div class="da-bar-track">
                <div
                  class="da-bar-fill"
                  :class="bar.value > 0 ? 'da-bar-fill--active' : ''"
                  :style="{ height: bar.height + '%' }"
                ></div>
              </div>
              <div class="da-bar-label">{{ bar.shortLabel }}</div>
            </div>
          </div>
        </div>
        <div v-else-if="listKnown" class="da-chart-empty">No disputes in the last 14 days</div>
      </div>

      <!-- Dispute Categories -->
      <div class="da-panel">
        <div class="da-panel__header">Dispute Categories</div>
        <div v-if="disputeCategories.length > 0" class="da-cat-list">
          <div v-for="cat in disputeCategories" :key="cat.name" class="da-cat-row">
            <div class="da-cat-row__label">
              <span class="da-cat-dot"></span>
              <span class="da-cat-name">{{ cat.name }}</span>
            </div>
            <div class="da-cat-row__bar">
              <div class="da-cat-track">
                <div class="da-cat-fill" :style="{ width: cat.percentage + '%' }"></div>
              </div>
              <span class="da-cat-count">{{ cat.count }}</span>
            </div>
          </div>
        </div>
        <div v-else-if="listKnown" class="da-chart-empty">No category data yet</div>
      </div>
    </div>

    <!-- Resolution breakdown row -->
    <div class="da-resolution-row">

      <!-- Ruling Breakdown -->
      <div class="da-panel">
        <div class="da-panel__header">Ruling Breakdown</div>
        <div class="da-ruling-grid">
          <div class="da-ruling-stat da-ruling-stat--open">
            <div class="da-ruling-stat__value">{{ listKnown ? openCount : '—' }}</div>
            <div class="da-ruling-stat__label">Open</div>
          </div>
          <div class="da-ruling-stat da-ruling-stat--resolved">
            <div class="da-ruling-stat__value">{{ listKnown ? resolvedCount : '—' }}</div>
            <div class="da-ruling-stat__label">Resolved</div>
          </div>
          <div class="da-ruling-stat da-ruling-stat--dismissed">
            <div class="da-ruling-stat__value">{{ listKnown ? dismissedCount : '—' }}</div>
            <div class="da-ruling-stat__label">Dismissed</div>
          </div>
          <div class="da-ruling-stat da-ruling-stat--investigating">
            <div class="da-ruling-stat__value">{{ listKnown ? investigatingCount : '—' }}</div>
            <div class="da-ruling-stat__label">Investigating</div>
          </div>
        </div>
        <!-- Resolution bar -->
        <div v-if="stats.total_disputes > 0" class="da-res-bar-wrap">
          <div class="da-res-bar">
            <div class="da-res-seg da-res-seg--resolved"  :style="{ width: resolvedPct + '%'  }" :title="`Resolved: ${resolvedCount}`"></div>
            <div class="da-res-seg da-res-seg--dismissed" :style="{ width: dismissedPct + '%' }" :title="`Dismissed: ${dismissedCount}`"></div>
            <div class="da-res-seg da-res-seg--investigating" :style="{ width: investigatingPct + '%' }" :title="`Investigating: ${investigatingCount}`"></div>
            <div class="da-res-seg da-res-seg--open"      :style="{ width: openPct + '%'     }" :title="`Open: ${openCount}`"></div>
          </div>
          <div class="da-res-bar-legend">
            <span class="da-legend-dot da-legend-dot--resolved"></span> Resolved
            <span class="da-legend-dot da-legend-dot--dismissed" style="margin-left:0.75rem"></span> Dismissed
            <span class="da-legend-dot da-legend-dot--open" style="margin-left:0.75rem"></span> Open
          </div>
        </div>
      </div>

      <!-- Recent Activity -->
      <div class="da-panel">
        <div class="da-panel__header">Recent Activity</div>
        <div v-if="!listKnown" class="da-chart-empty"></div>
        <div v-else-if="recentDisputes.length === 0" class="da-chart-empty">No disputes on record</div>
        <div v-else class="da-activity-list">
          <div v-for="d in recentDisputes" :key="d.id" class="da-activity-row">
            <span :class="['da-activity-pill', `da-activity-pill--${d.status}`]">{{ fmtStatus(d.status) }}</span>
            <span class="da-activity-desc">{{ truncate(d.description, 55) }}</span>
            <span class="da-activity-ago">{{ timeAgo(d.created_at) }}</span>
          </div>
        </div>
      </div>

    </div>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useDisputesStore } from '@/stores/disputes'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

dayjs.extend(relativeTime)

const disputesStore = useDisputesStore()
const stats    = computed(() => disputesStore.stats)
const disputes = computed(() => disputesStore.disputes)

// what the reads answered: the list at least once (a 404 is the server's "none"), the stats at least once
const listKnown  = computed(() => disputesStore.listRead)
const listFailed = computed(() => disputesStore.listFailed)
const statsRead  = computed(() => disputesStore.statsRead)
function retry() { return disputesStore.fetchDisputes() }

// ── Metric deltas ─────────────────────────────────────────────────────────

const escalatedCount = computed(() => disputes.value.filter(d => d.status === 'investigating').length)
const escalationRate = computed(() => {
  if (!disputes.value.length) return 0
  return (escalatedCount.value / disputes.value.length) * 100
})
const uniqueParties = computed(() => {
  const s = new Set<string>()
  disputes.value.forEach(d => { s.add(d.claimant_did); s.add(d.respondent_did) })
  return s.size
})
const repeatOffenders = computed(() => {
  const counts: Record<string, number> = {}
  disputes.value.forEach(d => {
    counts[d.claimant_did]   = (counts[d.claimant_did]   || 0) + 1
    counts[d.respondent_did] = (counts[d.respondent_did] || 0) + 1
  })
  return Object.values(counts).filter(c => c > 1).length
})

// ── Status counts ─────────────────────────────────────────────────────────
const openCount         = computed(() => disputes.value.filter(d => d.status === 'open').length)
const resolvedCount     = computed(() => disputes.value.filter(d => d.status === 'resolved').length)
const dismissedCount    = computed(() => disputes.value.filter(d => d.status === 'dismissed').length)
const investigatingCount = computed(() => disputes.value.filter(d => d.status === 'investigating').length)

const total = computed(() => disputes.value.length || 1)
const resolvedPct     = computed(() => (resolvedCount.value     / total.value) * 100)
const dismissedPct    = computed(() => (dismissedCount.value    / total.value) * 100)
const investigatingPct = computed(() => (investigatingCount.value / total.value) * 100)
const openPct         = computed(() => (openCount.value         / total.value) * 100)

// ── Timeline bars — 14-day window for readable bar widths ─────────────────
const timelineBars = computed(() => {
  const counts: Record<string, number> = {}
  const labels: string[] = []
  const shortLabels: string[] = []

  for (let i = 13; i >= 0; i--) {
    const d = dayjs().subtract(i, 'day')
    const key = d.format('YYYY-MM-DD')
    counts[key] = 0
    labels.push(d.format('MMM D'))
    shortLabels.push(i === 0 ? 'Today' : d.format('D'))
  }

  disputes.value.forEach(d => {
    const key = dayjs(d.created_at).format('YYYY-MM-DD')
    if (key in counts) counts[key]++
  })

  const values = Object.values(counts)
  const maxVal = Math.max(...values, 1)

  return values.map((v, i) => ({
    value: v,
    label: labels[i],
    shortLabel: shortLabels[i],
    height: v === 0 ? 0 : Math.max(8, Math.round((v / maxVal) * 100))
  }))
})

// ── Categories ────────────────────────────────────────────────────────────
const disputeCategories = computed(() => {
  const cats: Record<string, number> = {}
  disputes.value.forEach(d => {
    const key = d.reason && d.reason !== 'Contract dispute' ? d.reason : 'Other'
    cats[key] = (cats[key] || 0) + 1
  })
  const tot = disputes.value.length || 1
  return Object.entries(cats)
    .map(([name, count]) => ({
      name: name.length > 22 ? name.slice(0, 22) + '…' : name,
      count,
      percentage: Math.round((count / tot) * 100)
    }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6)
})

// ── Recent disputes ───────────────────────────────────────────────────────
const recentDisputes = computed(() =>
  [...disputes.value]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 6)
)

// ── Helpers ───────────────────────────────────────────────────────────────
function fmtStatus(s: string) { return s.charAt(0).toUpperCase() + s.slice(1) }
function timeAgo(d: string)   { return dayjs(d).fromNow() }
function truncate(s: string, n: number) { return s.length > n ? s.slice(0, n) + '…' : s }
</script>

<style scoped>
.da-view {
  padding: 0.5rem 0.25rem;
  display: flex; flex-direction: column; gap: 1.25rem;
}

.da-header { margin-bottom: 0.25rem; }
.da-title  { font-family: 'IBM Plex Mono', monospace; font-size: 1.25rem; font-weight: 700; color: rgb(0,210,210); }
.da-sub    { font-size: 0.78rem; color: #7b91b2; margin-top: 0.2rem; letter-spacing: 0.04em; }

/* Metric cards */
.da-metrics {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;
}
@media (max-width: 900px) { .da-metrics { grid-template-columns: repeat(2, 1fr); } }

.da-metric-card {
  background: var(--nc-surface, #111827);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 10px;
  padding: 1rem 1rem 0.85rem 1.2rem;
  position: relative; overflow: hidden;
}
.da-metric-card__accent { position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
.da-metric-card__top { display: flex; justify-content: flex-end; margin-bottom: 0.5rem; }
.da-metric-card__delta {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 600;
  padding: 0.15rem 0.5rem; border-radius: 9999px;
}
.da-pos     { background: rgba(34,197,94,0.1);  color: rgb(34,197,94); }
.da-neg     { background: rgba(239,68,68,0.1);  color: rgb(239,68,68); }
.da-neutral { background: rgba(var(--nc-primary-rgb),0.08); color: #6b7e96; }

.da-metric-card__value {
  font-family: 'IBM Plex Mono', monospace; font-size: 1.7rem; font-weight: 700; color: #e2e8f0; line-height: 1;
}
.da-metric-card__label {
  font-size: 0.7rem; color: #7b91b2; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.3rem;
}

/* Panels */
.da-panel {
  background: var(--nc-surface, #111827);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 10px; padding: 1.1rem 1.25rem;
}
.da-panel__header {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.1em; text-transform: uppercase; color: #8fa3be; margin-bottom: 1rem;
}
.da-panel__sub { font-size: 0.65rem; color: #7b91b2; margin-left: 0.5rem; text-transform: none; letter-spacing: 0; }
.da-chart-empty { text-align: center; padding: 1.5rem; font-size: 0.82rem; color: #7b91b2; }

.da-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 900px) { .da-charts { grid-template-columns: 1fr; } }

/* ── Bar chart ── */
.da-chart-area { padding: 0 0.25rem; }
.da-chart-bars {
  display: flex; align-items: flex-end; gap: 3px;
  height: 140px;
}
.da-bar-col {
  flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px;
  min-width: 0;
}
.da-bar-track {
  flex: 1; width: 100%; display: flex; align-items: flex-end;
}
.da-bar-fill {
  width: 100%; border-radius: 3px 3px 0 0; min-height: 0;
  background: transparent;
  transition: height 0.4s ease;
}
.da-bar-fill--active {
  background: rgba(var(--nc-primary-rgb),0.7);
}
.da-bar-fill--active:hover {
  background: rgb(0,210,210);
}
.da-bar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem; color: #3a4e65;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 100%; text-align: center;
}

/* Category bars */
.da-cat-list { display: flex; flex-direction: column; gap: 0.65rem; }
.da-cat-row  { display: flex; align-items: center; gap: 0.75rem; }
.da-cat-row__label { display: flex; align-items: center; gap: 0.5rem; flex: 0 0 140px; }
.da-cat-dot { width: 8px; height: 8px; border-radius: 50%; background: rgb(0,210,210); flex-shrink: 0; }
.da-cat-name { font-size: 0.78rem; color: #c8d6e8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.da-cat-row__bar { display: flex; align-items: center; gap: 0.6rem; flex: 1; }
.da-cat-track { flex: 1; height: 6px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.da-cat-fill  { height: 100%; background: rgb(0,210,210); border-radius: 3px; transition: width 0.5s ease; }
.da-cat-count { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: #8fa3be; width: 24px; text-align: right; }

/* ── Resolution breakdown row ── */
.da-resolution-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 900px) { .da-resolution-row { grid-template-columns: 1fr; } }

.da-ruling-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem;
  margin-bottom: 1rem;
}
.da-ruling-stat {
  background: rgba(255,255,255,0.02);
  border-radius: 8px; padding: 0.75rem 0.5rem;
  text-align: center; border: 1px solid transparent;
}
.da-ruling-stat--open        { border-color: rgba(239,68,68,0.2); }
.da-ruling-stat--resolved    { border-color: rgba(34,197,94,0.2); }
.da-ruling-stat--dismissed   { border-color: rgba(107,114,128,0.2); }
.da-ruling-stat--investigating { border-color: rgba(245,158,11,0.2); }

.da-ruling-stat__value {
  font-family: 'IBM Plex Mono', monospace; font-size: 1.4rem; font-weight: 700; line-height: 1;
}
.da-ruling-stat--open .da-ruling-stat__value        { color: rgb(239,68,68); }
.da-ruling-stat--resolved .da-ruling-stat__value    { color: rgb(34,197,94); }
.da-ruling-stat--dismissed .da-ruling-stat__value   { color: #9ca3af; }
.da-ruling-stat--investigating .da-ruling-stat__value { color: #f59e0b; }

.da-ruling-stat__label {
  font-size: 0.65rem; color: #7b91b2; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.25rem;
}

.da-res-bar-wrap { margin-top: 0.25rem; }
.da-res-bar {
  height: 10px; border-radius: 5px; overflow: hidden;
  display: flex; background: rgba(255,255,255,0.05);
}
.da-res-seg { height: 100%; transition: width 0.5s ease; }
.da-res-seg--resolved    { background: rgb(34,197,94); }
.da-res-seg--dismissed   { background: #6b7280; }
.da-res-seg--investigating { background: #f59e0b; }
.da-res-seg--open        { background: rgb(239,68,68); }

.da-res-bar-legend {
  display: flex; align-items: center; gap: 0.35rem;
  font-size: 0.7rem; color: #7b91b2; margin-top: 0.5rem;
}
.da-legend-dot {
  width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0;
}
.da-legend-dot--resolved  { background: rgb(34,197,94); }
.da-legend-dot--dismissed { background: #6b7280; }
.da-legend-dot--open      { background: rgb(239,68,68); }

/* Activity list */
.da-activity-list { display: flex; flex-direction: column; gap: 0.5rem; }
.da-activity-row  {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.4rem 0; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06);
}
.da-activity-row:last-child { border-bottom: none; }
.da-activity-pill {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; font-weight: 600;
  padding: 0.15rem 0.5rem; border-radius: 9999px; text-transform: uppercase; flex-shrink: 0;
}
.da-activity-pill--open          { background: rgba(239,68,68,0.12);  color: rgb(239,68,68); }
.da-activity-pill--investigating  { background: rgba(245,158,11,0.12); color: #f59e0b; }
.da-activity-pill--resolved      { background: rgba(34,197,94,0.12);  color: rgb(34,197,94); }
.da-activity-pill--dismissed     { background: rgba(107,114,128,0.15); color: #9ca3af; }
.da-activity-desc {
  flex: 1; font-size: 0.78rem; color: #8fa3be;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.da-activity-ago { font-size: 0.7rem; color: #7b91b2; flex-shrink: 0; }
</style>
