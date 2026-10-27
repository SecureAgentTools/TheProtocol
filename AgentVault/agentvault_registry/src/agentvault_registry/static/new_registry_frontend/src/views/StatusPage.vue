<template>
  <div class="st" data-testid="status-root" :data-overall="overall">
    <!-- the landing page's ambient: the grid, the scan beam, the three glows (his word: take the landing's background) -->
    <div class="st-ambient" aria-hidden="true">
      <div class="st-grid"></div>
      <div class="st-scan"></div>
      <div class="st-glow st-glow-1"></div>
      <div class="st-glow st-glow-2"></div>
      <div class="st-glow st-glow-3"></div>
    </div>

    <nav class="st-nav">
      <RouterLink to="/" class="st-brand" data-testid="status-home"><ProtocolMark :size="30" alive /><span>THE PROTOCOL</span></RouterLink>
      <div class="st-nav-links">
        <RouterLink to="/">{{ t('status.nav.home', 'Home') }}</RouterLink>
        <RouterLink v-if="journalEnabled" to="/blog">{{ t('status.nav.journal', 'Journal') }}</RouterLink>
        <RouterLink to="/docs">{{ t('status.nav.docs', 'Docs') }}</RouterLink>
      </div>
    </nav>

    <main id="main-content" class="st-main app-main" tabindex="-1">
      <header class="st-hero" :class="`st-hero--${overall}`">
        <div class="st-hero-left">
          <span class="st-kicker">{{ t('status.title', 'System status') }}</span>
          <h1 class="st-verdict" data-testid="status-overall"><span class="st-verdict-dot" aria-hidden="true"></span>{{ overallLabel }}</h1>
          <!-- §FESUITE (the loading sweep): "0 of 0 components responding" was a claim the page made before its read -->
          <p class="st-summary" data-testid="status-summary" role="status">
            <template v-if="readState === 'read'">
              {{ tp('status.summary', '{up} of {total} components responding', { up: upCount, total: components.length }) }}
              <span class="st-sep">·</span>{{ tp('status.checked', 'checked {ago}', { ago: checkedAgo }) }}
              <template v-if="since"><span class="st-sep">·</span>{{ tp('status.since', 'history since {date}', { date: since }) }}</template>
            </template>
            <template v-else-if="readState === 'reading'">{{ t('common.loading', 'Loading…') }}</template>
          </p>
          <p v-if="error" class="st-error" data-testid="status-error">{{ error }}</p>
        </div>
        <div class="st-hero-right">
          <div class="st-stat"><span class="st-stat-val">{{ pctOrDash(fleetAvailability) }}</span><span class="st-stat-label">{{ t('status.fleetAvailability', 'fleet availability, measured days') }}</span></div>
          <div class="st-stat"><span class="st-stat-val">{{ readState === 'read' ? incidents.length : '—' }}</span><span class="st-stat-label">{{ t('status.incidents.title', 'Incidents') }}</span></div>
          <div class="st-stat"><span class="st-stat-val">{{ readState === 'read' ? dips.length : '—' }}</span><span class="st-stat-label">{{ t('status.dips.title', 'Measured dips') }}</span></div>
        </div>
      </header>

      <section v-for="g in groups" :key="g.key" class="st-card" :data-testid="`status-group-${g.key}`">
        <div class="st-card-head">
          <h2 class="st-card-title">{{ g.title }}</h2>
          <span class="st-card-meta">{{ readState === 'read' ? tp('status.groupUp', '{up} of {total} up', { up: g.items.filter(c => c.status === 'up').length, total: g.items.length }) : '—' }}</span>
          <span class="st-card-axis" aria-hidden="true"><span>{{ tp('status.daysAgo', '{n} days ago', { n: windowDays }) }}</span><span>{{ t('status.today', 'today') }}</span></span>
        </div>
        <div v-for="c in g.items" :key="c.key" class="st-row" :data-testid="`status-comp-${c.key}`" :data-status="c.status">
          <span class="st-dot" :class="`st-dot--${c.status}`" aria-hidden="true"></span>
          <!-- §SLUGCONVERGE — four operators run in a container named after their pre-June identity. The name is
               the IDENTITY. The container used to render as a second span, but `.st-row` is a FIVE-column grid
               and that span was a sixth child, so for exactly those four operators the availability bar wrapped
               onto a second grid row. The hint now rides the title attribute: same information, no grid cell,
               no second name on the page. Keep `data-infra-label` — it is how a battery asserts the mapping
               without the label being visible. -->
          <component :is="c.public_url && c.status === 'up' ? 'a' : 'span'" class="st-name"
                     :href="c.public_url && c.status === 'up' ? c.public_url : undefined"
                     :title="c.infra_label ? tp('status.infraLabel', 'runs in the container {label}', { label: c.infra_label }) : undefined"
                     :data-infra-label="c.infra_label || undefined"
                     :data-testid="`status-label-${c.key}`"
                     :target="c.public_url ? '_blank' : undefined" :rel="c.public_url ? 'noopener noreferrer' : undefined">{{ c.name }}</component>
          <span class="st-lat">{{ c.latency_ms != null ? tp('status.latency', '{ms} ms', { ms: c.latency_ms }) : '—' }}</span>
          <div class="st-bar" :data-job="c.job || ''" :title="c.job ? '' : t('status.noHistory', 'No history: nothing scrapes this component yet.')">
            <span v-for="d in c.days" :key="d.date" class="st-cell" :class="cellClass(d.up)"
                  :title="`${d.date} · ${d.up == null ? t('status.legend.nodata', 'no data') : pct(d.up)}`"></span>
          </div>
          <span class="st-avail" :title="tp('status.daysKnown', '{n} days measured', { n: c.days_known })">{{ pctOrDash(c.availability) }}</span>
        </div>
        <!-- §FESUITE (2026-10-05): "Nothing probed yet." was drawn in both groups before the read and over a failed one; the
             header says the rail did not answer, the groups say nothing they did not read -->
        <p v-if="readState === 'read' && !g.items.length" class="st-empty" :data-testid="`status-none-${g.key}`">{{ t('status.noComponents', 'Nothing probed yet.') }}</p>
      </section>

      <section class="st-card" data-testid="status-incidents">
        <div class="st-card-head"><h2 class="st-card-title">{{ t('status.incidents.title', 'Incidents') }}</h2><span class="st-card-meta">{{ readState === 'read' ? incidents.length : '—' }}</span></div>
        <p v-if="readState === 'read' && !incidents.length" class="st-empty" data-testid="status-no-incidents">{{ t('status.incidents.none', 'No incidents recorded.') }}</p>
        <ol v-else class="st-timeline">
          <li v-for="inc in incidents" :key="inc.id" class="st-inc" :data-testid="`status-inc-${inc.id}`" :data-impact="inc.impact">
            <span class="st-inc-node" :class="`st-inc-node--${inc.impact}`" aria-hidden="true"></span>
            <div class="st-inc-body">
              <div class="st-inc-head">
                <span class="st-badge" :class="`st-badge--${inc.impact}`">{{ impactLabel(inc.impact) }}</span>
                <span class="st-badge st-badge--status">{{ statusLabel(inc.status) }}</span>
                <span class="st-inc-when">{{ fmtDate(inc.started_at) }}<template v-if="inc.resolved_at"> → {{ fmtDate(inc.resolved_at) }}</template></span>
              </div>
              <h3 class="st-inc-title">{{ inc.title }}</h3>
              <p v-if="inc.components.length" class="st-inc-comps"><span v-for="c in inc.components" :key="c" class="st-chip">{{ c }}</span></p>
              <ul v-if="inc.updates.length" class="st-inc-updates">
                <li v-for="(u, i) in inc.updates" :key="i">
                  <span class="st-upd-when">{{ fmtDate(u.at) }}</span>
                  <span class="st-upd-status">{{ statusLabel(u.status) }}</span>
                  <span class="st-upd-text">{{ u.text }}</span>
                </li>
              </ul>
            </div>
          </li>
        </ol>
      </section>

      <section class="st-card" data-testid="status-dips">
        <details class="st-details">
          <summary class="st-card-head st-card-head--summary">
            <h2 class="st-card-title">{{ t('status.dips.title', 'Measured dips') }}</h2>
            <span class="st-card-meta">{{ readState === 'read' ? dips.length : '—' }}</span>
            <span class="st-card-hint">{{ t('status.dips.lead', 'Days on which a component averaged below 99.9% availability, read from the metrics with no narrative attached.') }}</span>
          </summary>
          <p v-if="readState === 'read' && !dips.length" class="st-empty" data-testid="status-no-dips">{{ t('status.dips.none', 'None in the recorded window.') }}</p>
          <ul v-else class="st-dips">
            <li v-for="d in dips" :key="d.date + d.component_key"><span class="st-upd-when">{{ d.date }}</span><span>{{ d.name }}</span><span class="st-dip-pct">{{ pct(d.up) }}</span></li>
          </ul>
        </details>
      </section>

      <footer class="st-foot">
        <p>{{ t('status.method', 'Components are probed by this registry itself; availability is the per-day mean of each service\'s scrape signal, and the window grows from the day this page shipped.') }}</p>
        <div class="st-legend" aria-hidden="true">
          <span class="st-cell st-cell--up"></span>{{ t('status.legend.up', '≥ 99.9%') }}
          <span class="st-cell st-cell--dip"></span>{{ t('status.legend.dip', '99 – 99.9%') }}
          <span class="st-cell st-cell--down"></span>{{ t('status.legend.down', '< 99%') }}
          <span class="st-cell st-cell--nodata"></span>{{ t('status.legend.nodata', 'no data') }}
        </div>
      </footer>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import apiClient from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import ProtocolMark from '@/components/ProtocolMark.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'

type Day = { date: string; up: number | null }
type Component = { key: string; name: string; group: string; status: 'up' | 'down' | 'unknown'; latency_ms: number | null;
  public_url: string | null; job: string | null; infra_label?: string | null; availability: number | null; days_known: number; days: Day[] }
type Update = { at: string; status: string; text: string }
type Incident = { id: string; title: string; impact: string; status: string; components: string[]; started_at: string; resolved_at: string | null; updates: Update[] }
type Dip = { date: string; component_key: string; name: string; up: number }

const { t, tp } = useI18n()
const { journalEnabled } = useRegistryConfig()
const components = ref<Component[]>([])
const incidents = ref<Incident[]>([])
const dips = ref<Dip[]>([])
const overall = ref<'operational' | 'degraded' | 'outage' | 'unknown'>('unknown')
const since = ref<string | null>(null)
const checkedAt = ref<number | null>(null)
const error = ref('')
/** §FESUITE (the loading sweep): no figure before the first answer; a page that never got one says so above */
const readState = ref<'reading' | 'read' | 'unread'>('reading')
const now = ref(Date.now())

const upCount = computed(() => components.value.filter(c => c.status === 'up').length)
const windowDays = computed(() => components.value[0]?.days?.length || 90)
/* the fleet figure: the mean of every component that HAS measured days (the grey ones cannot vote) */
const fleetAvailability = computed<number | null>(() => {
  const known = components.value.filter(c => c.availability != null)
  return known.length ? known.reduce((a, c) => a + (c.availability as number), 0) / known.length : null
})
function pctOrDash(x: number | null | undefined): string { return x == null ? '—' : pct(x) }
const groups = computed(() => [
  { key: 'core', title: t('status.groups.core', 'This registry'), items: components.value.filter(c => c.group === 'core') },
  { key: 'operator', title: t('status.groups.operator', 'Federation'), items: components.value.filter(c => c.group !== 'core') },
])
const overallLabel = computed(() => ({
  operational: t('status.overall.operational', 'All systems operational'),
  degraded: t('status.overall.degraded', 'Partially degraded'),
  outage: t('status.overall.outage', 'Service disruption'),
  unknown: t('status.overall.unknown', 'Status unknown'),
}[overall.value]))
const checkedAgo = computed(() => {
  if (!checkedAt.value) return t('status.checking', 'checking…')
  const s = Math.max(0, Math.round((now.value - checkedAt.value) / 1000))
  return s < 60 ? tp('status.secondsAgo', '{n} s ago', { n: s }) : tp('status.minutesAgo', '{n} min ago', { n: Math.round(s / 60) })
})

const nf = new Intl.NumberFormat(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
function pct(x: number): string { return `${nf.format(x * 100)}%` }
function cellClass(up: number | null): string {
  if (up == null) return 'st-cell--nodata'
  if (up >= 0.999) return 'st-cell--up'
  if (up >= 0.99) return 'st-cell--dip'
  return 'st-cell--down'
}
function fmtDate(iso: string): string {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString(appLocale(), { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' })
}
function impactLabel(k: string): string {
  return ({ minor: t('status.incidents.impact.minor', 'Minor'), major: t('status.incidents.impact.major', 'Major'),
    critical: t('status.incidents.impact.critical', 'Critical'), maintenance: t('status.incidents.impact.maintenance', 'Maintenance') } as Record<string, string>)[k] || k
}
function statusLabel(k: string): string {
  return ({ investigating: t('status.incidents.status.investigating', 'Investigating'), identified: t('status.incidents.status.identified', 'Identified'),
    monitoring: t('status.incidents.status.monitoring', 'Monitoring'), resolved: t('status.incidents.status.resolved', 'Resolved'),
    scheduled: t('status.incidents.status.scheduled', 'Scheduled'), completed: t('status.incidents.status.completed', 'Completed') } as Record<string, string>)[k] || k
}

let poll: ReturnType<typeof setInterval> | null = null
let tick: ReturnType<typeof setInterval> | null = null
async function load(): Promise<void> {
  try {
    const res = await apiClient.get('/public/status')
    const d = res.data || {}
    components.value = Array.isArray(d.components) ? d.components : []
    incidents.value = Array.isArray(d.incidents) ? d.incidents : []
    dips.value = Array.isArray(d.measured_dips) ? d.measured_dips : []
    overall.value = d.overall || 'unknown'
    since.value = d.history?.since || null
    checkedAt.value = d.checked_at ? new Date(d.checked_at).getTime() : Date.now()
    error.value = ''
    readState.value = 'read'
  } catch (e: any) {
    error.value = t('status.loadFailed', 'The status rail did not answer; the last known state stays on screen.')
    if (readState.value !== 'read') readState.value = 'unread'
  }
}
function onVisibility(): void { if (document.visibilityState === 'visible') void load() }
onMounted(() => {
  void load()
  poll = setInterval(() => { if (document.visibilityState === 'visible') void load() }, 45000)
  tick = setInterval(() => { now.value = Date.now() }, 10000)
  document.addEventListener('visibilitychange', onVisibility)
})
onUnmounted(() => {
  if (poll) clearInterval(poll)
  if (tick) clearInterval(tick)
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<style scoped>
.st { --st-up: #00c853; --st-dip: #f5a623; --st-down: #ff3b30; --st-nodata: rgba(255,255,255,.07);
  position: relative; min-height: 100vh; background: var(--nc-deep, #060a10); color: var(--nc-text, #e6edf3); overflow-x: hidden; }
/* the landing page's ambient layers, verbatim */
.st-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.st-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.st-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: stScanBeam 12s linear infinite; }
@keyframes stScanBeam { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 3000px)); } }
.st-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.st-glow-1 { width: 600px; height: 600px; top: -200px; right: -100px; background: #00b8b8; opacity: 0.1; }
.st-glow-2 { width: 400px; height: 400px; bottom: 30%; left: -100px; background: #0066aa; opacity: 0.08; }
.st-glow-3 { width: 500px; height: 500px; top: 50%; right: -200px; background: #009966; opacity: 0.05; }
@media (prefers-reduced-motion: reduce) { .st-scan { animation: none; } }
/* nav */
.st-nav { position: relative; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .9rem 2rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb),.08); background: rgba(6,10,16,.6); }
.st-brand { display: flex; align-items: center; gap: .7rem; text-decoration: none; color: #e8edf2; }
.st-brand span { font-size: .85rem; letter-spacing: .22em; white-space: nowrap; }
.st-nav-links { display: flex; gap: 1.2rem; font-family: 'IBM Plex Mono', monospace; font-size: .64rem; letter-spacing: .14em; text-transform: uppercase; }
.st-nav-links a { color: rgba(var(--nc-primary-rgb),.85); text-decoration: none; }
.st-nav-links a:hover { color: var(--nc-primary, #00e5ff); }
/* main */
.st-main { position: relative; z-index: 1; max-width: 1120px; margin: 0 auto; padding: 1.6rem 1.25rem 3.5rem; }
.st-kicker { font-family: 'IBM Plex Mono', monospace; font-size: .6rem; letter-spacing: .22em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb),.75); }
.st-hero { display: flex; gap: 1.5rem; align-items: stretch; justify-content: space-between; flex-wrap: wrap; padding: 1.4rem 1.6rem; border-radius: 14px;
  border: 1px solid rgba(var(--nc-primary-rgb),.14); background: linear-gradient(135deg, rgba(10,18,26,.85), rgba(6,10,16,.75)); margin-bottom: 1.1rem; }
.st-hero--operational { border-color: rgba(0,200,83,.35); box-shadow: 0 0 60px rgba(0,200,83,.06) inset; }
.st-hero--degraded { border-color: rgba(245,166,35,.4); box-shadow: 0 0 60px rgba(245,166,35,.06) inset; }
.st-hero--outage { border-color: rgba(255,59,48,.5); box-shadow: 0 0 60px rgba(255,59,48,.08) inset; }
.st-hero-left { display: flex; flex-direction: column; gap: .35rem; min-width: 260px; flex: 1; }
.st-verdict { margin: .1rem 0; font-size: clamp(1.4rem, 3vw, 2rem); font-weight: 300; letter-spacing: -.01em; display: flex; align-items: center; gap: .75rem; color: #f0f4f8; }
.st-verdict-dot { width: 14px; height: 14px; border-radius: 50%; background: var(--st-nodata); flex: 0 0 auto; }
.st-hero--operational .st-verdict-dot { background: var(--st-up); box-shadow: 0 0 18px rgba(0,200,83,.8); }
.st-hero--degraded .st-verdict-dot { background: var(--st-dip); box-shadow: 0 0 18px rgba(245,166,35,.8); }
.st-hero--outage .st-verdict-dot { background: var(--st-down); box-shadow: 0 0 18px rgba(255,59,48,.8); }
.st-summary { margin: 0; font-family: 'IBM Plex Mono', monospace; font-size: .68rem; color: rgba(255,255,255,.55); letter-spacing: .04em; }
.st-sep { margin: 0 .45rem; opacity: .5; }
.st-error { margin: .2rem 0 0; font-size: .76rem; color: var(--st-dip); }
.st-hero-right { display: flex; gap: 1.2rem; align-items: center; flex-wrap: wrap; }
.st-stat { display: flex; flex-direction: column; gap: .15rem; min-width: 96px; padding: .5rem .8rem; border-left: 1px solid rgba(var(--nc-primary-rgb),.14); }
.st-stat-val { font-family: 'IBM Plex Mono', monospace; font-size: 1.15rem; color: var(--nc-primary, #00e5ff); font-variant-numeric: tabular-nums; }
.st-stat-label { font-family: 'IBM Plex Mono', monospace; font-size: .56rem; letter-spacing: .12em; text-transform: uppercase; color: rgba(255,255,255,.4); }
/* cards */
.st-card { border: 1px solid rgba(var(--nc-primary-rgb),.1); border-radius: 12px; background: rgba(8,13,20,.72); padding: .9rem 1rem 1rem; margin-bottom: 1rem; }
.st-card-head { display: flex; align-items: baseline; gap: .7rem; margin-bottom: .6rem; flex-wrap: wrap; }
.st-card-title { margin: 0; font-family: 'IBM Plex Mono', monospace; font-size: .62rem; letter-spacing: .2em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb),.85); }
.st-card-meta { font-family: 'IBM Plex Mono', monospace; font-size: .62rem; color: rgba(255,255,255,.45); letter-spacing: .06em; }
.st-card-hint { flex-basis: 100%; font-size: .72rem; color: rgba(255,255,255,.45); margin-top: .2rem; }
.st-card-axis { margin-left: auto; display: flex; gap: 1rem; font-family: 'IBM Plex Mono', monospace; font-size: .56rem; letter-spacing: .1em; text-transform: uppercase; color: rgba(255,255,255,.3); }
.st-row { display: grid; grid-template-columns: 10px minmax(130px, 210px) 64px 1fr 72px; gap: .7rem; align-items: center; padding: .48rem .55rem; border-radius: 8px; }
.st-row:hover { background: rgba(var(--nc-primary-rgb),.04); }
.st-row + .st-row { border-top: 1px solid rgba(255,255,255,.04); }
.st-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--st-nodata); }
.st-dot--up { background: var(--st-up); box-shadow: 0 0 8px rgba(0,200,83,.6); }
.st-dot--down { background: var(--st-down); box-shadow: 0 0 8px rgba(255,59,48,.6); }
.st-name { font-size: .82rem; color: #e6edf3; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
a.st-name:hover { color: var(--nc-primary, #00e5ff); }
.st-lat, .st-avail { font-family: 'IBM Plex Mono', monospace; font-size: .66rem; color: rgba(255,255,255,.55); font-variant-numeric: tabular-nums; text-align: right; }
.st-avail { color: #dfe7ee; }
.st-bar { display: flex; gap: 1px; height: 16px; min-width: 0; }
.st-cell { flex: 1 1 0; min-width: 2px; border-radius: 1px; background: var(--st-nodata); }
.st-cell--up { background: var(--st-up); opacity: .8; }
.st-cell--dip { background: var(--st-dip); }
.st-cell--down { background: var(--st-down); }
.st-cell--nodata { background: var(--st-nodata); }
.st-empty { font-size: .76rem; color: rgba(255,255,255,.45); margin: .2rem 0 .4rem; }
/* incidents: a timeline */
.st-timeline { list-style: none; margin: 0; padding: 0 0 0 1.1rem; border-left: 1px solid rgba(var(--nc-primary-rgb),.14); }
.st-inc { position: relative; padding: .2rem 0 1rem .9rem; }
.st-inc-node { position: absolute; left: -1.1rem; top: .55rem; width: 9px; height: 9px; border-radius: 50%; transform: translateX(-4px); background: rgba(255,255,255,.3); box-shadow: 0 0 0 3px var(--nc-deep, #060a10); }
.st-inc-node--minor { background: var(--st-dip); } .st-inc-node--major, .st-inc-node--critical { background: var(--st-down); } .st-inc-node--maintenance { background: var(--nc-primary, #00e5ff); }
.st-inc-head { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.st-inc-title { margin: .3rem 0 .2rem; font-size: .95rem; font-weight: 500; color: #f0f4f8; }
.st-inc-when, .st-upd-when { font-family: 'IBM Plex Mono', monospace; font-size: .6rem; color: rgba(255,255,255,.45); white-space: nowrap; }
.st-inc-comps { margin: .1rem 0 .3rem; display: flex; gap: .3rem; flex-wrap: wrap; }
.st-chip { font-family: 'IBM Plex Mono', monospace; font-size: .58rem; letter-spacing: .06em; padding: .12rem .45rem; border-radius: 999px; border: 1px solid rgba(var(--nc-primary-rgb),.25); color: rgba(var(--nc-primary-rgb),.85); }
.st-badge { font-family: 'IBM Plex Mono', monospace; font-size: .56rem; letter-spacing: .12em; text-transform: uppercase; padding: .15rem .45rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.14); color: rgba(255,255,255,.55); }
.st-badge--minor { color: var(--st-dip); border-color: rgba(245,166,35,.4); }
.st-badge--major, .st-badge--critical { color: var(--st-down); border-color: rgba(255,59,48,.45); }
.st-badge--maintenance { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb),.4); }
.st-inc-updates { list-style: none; margin: .45rem 0 0; padding: 0; display: flex; flex-direction: column; gap: .32rem; }
.st-inc-updates li { display: grid; grid-template-columns: 150px 100px 1fr; gap: .6rem; font-size: .76rem; align-items: baseline; color: rgba(255,255,255,.8); }
.st-upd-status { font-family: 'IBM Plex Mono', monospace; font-size: .58rem; letter-spacing: .1em; text-transform: uppercase; color: rgba(255,255,255,.45); }
/* dips: folded */
.st-details > summary { list-style: none; cursor: pointer; }
.st-details > summary::-webkit-details-marker { display: none; }
.st-card-head--summary::before { content: '▸'; font-size: .7rem; color: rgba(var(--nc-primary-rgb),.7); margin-right: .1rem; }
.st-details[open] > .st-card-head--summary::before { content: '▾'; }
.st-dips { list-style: none; margin: .4rem 0 0; padding: 0; }
.st-dips li { display: grid; grid-template-columns: 110px 1fr 80px; gap: .6rem; font-size: .76rem; padding: .28rem .2rem; border-top: 1px solid rgba(255,255,255,.05); }
.st-dip-pct { font-family: 'IBM Plex Mono', monospace; font-size: .66rem; color: var(--st-dip); text-align: right; }
/* footer */
.st-foot { margin-top: 1.6rem; font-size: .7rem; color: rgba(255,255,255,.45); }
.st-legend { display: flex; align-items: center; gap: .45rem; flex-wrap: wrap; margin-top: .45rem; font-family: 'IBM Plex Mono', monospace; font-size: .6rem; }
.st-legend .st-cell { flex: 0 0 auto; width: 14px; height: 10px; }
@media (max-width: 760px) {
  .st-nav { padding: .8rem 1rem; } .st-nav-links { gap: .8rem; }
  .st-hero { padding: 1rem 1.1rem; } .st-hero-right { width: 100%; }
  .st-row { grid-template-columns: 10px 1fr 56px 64px; }
  /* the bar takes its own row; the availability stays on the first, right of the latency, as on the desktop (the
     camera, 2026-10-13: auto-placement put it under the bar in the dot's 10 px column, 32 px past its box) */
  .st-avail { grid-row: 1; grid-column: 4; }
  .st-bar { grid-column: 1 / -1; grid-row: 2; height: 10px; }
  .st-inc-updates li, .st-dips li { grid-template-columns: 1fr; gap: .1rem; }
  .st-card-axis { display: none; }
}
</style>
