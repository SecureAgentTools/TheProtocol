<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// Cross-Frame FX Desk — admin console for the AVT⇄BVT reserve-mediated swap booth.
// Strategy §12 (Desk) + §14 (POOL/AMM) + §18.3 (card fx config). Data sources are
// all FE-reachable (services/api/fx.ts): card fees.fx (config), /teg/fx/pool
// (x/y/k/spot/MtM), /teg/fx/quote (sim), /admin/events/search (swap feed).
// Integrity panel (I1/I2/I3) is pending a registry proxy for cross-frame-audit (B8).
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { useFrames } from '@/composables/useFrames'
import { useMultiFrameSession } from '@/stores/multiFrameSession'
import { useAdminFrames } from '@/composables/useAdminFrames'
import { LOCAL_FRAME } from '@/services/api/eventStoreAdmin'
import { fxService, fetchFxConfig, type FxConfig, type FxPool, type FxSwapRow, type FxQuote, type CrossFrameAudit, type FxRate, type FxRouteRow, type FxRouteStatus, type FxRouterKeeper, type FxReserveKeeper, type FxDeadLetterRow } from '@/services/api/fx'
import JsonViewer from '@/components/common/JsonViewer.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const { t } = useI18n()
const { describe } = useCurrency()
const { localFx, localCurrency } = useFrames()   // cached card fx (fallback); this frame's own unit
const mf = useMultiFrameSession()                // foreign-frame admin tokens (peer-proxy)
// §FEDEVENTS: feed frames = LOCAL (self-identified, any deployment) + connected
// Multi-Frame Console sessions — the hardcoded A/B/C chip row defaulting to 'A'
// landed frame-b/c/hetzner admins on a foreign frame's feed out of the box.
const { selectableFrames, resolveOption } = useAdminFrames()

const config = ref<FxConfig | null>(null)
const pool = ref<FxPool | null>(null)
const swaps = ref<FxSwapRow[]>([])
/** §FESUITE (the loading sweep): true while the shown feed is a successful read; a failure empties the feed and clears
 *  it, so the counts show a dash then, never a 0 ("none"). */
const swapsRead = ref(false)
// §FESUITE (2026-10-04): the route feed said "No routes recorded" with its read failed; it answers like the swaps
const routesRead = ref(false)
const loadingConfig = ref(true)
const loadingPool = ref(true)
const loadingFeed = ref(true)
const poolError = ref<string | null>(null)
const feedFrame = ref<string>(LOCAL_FRAME)  // source frame of the swaps to list (default: THIS registry)
const feedNote = ref<string | null>(null)   // actionable note (e.g. foreign frame not connected)
const feedFrameLabel = computed(() => resolveOption(feedFrame.value).label)
const expandedTx = ref<string | null>(null)
const lastRefreshedAt = ref<Date | null>(null)   // freshness indicator for the live desk
const audit = ref<CrossFrameAudit | null>(null)  // live cross-frame integrity (I1/I2/I3) — B8
const loadingAudit = ref(true)
const rate = ref<FxRate | null>(null)            // public env-authoritative enabled signal (fast)
const rateResolved = ref(false)                  // have we heard back from /teg/fx/rate yet?
const routes = ref<FxRouteRow[]>([])             // op→op cross-frame FX routes (gateway-delegated egress)
const loadingRoutes = ref(true)
const routeStatus = ref<FxRouteStatus | null>(null)   // @fx_router transit account + route config
// §FESUITE V0578: the integrity panel said "Cross-frame audit not exposed on this frame (non-FX frame, or admin sign-in
// required)" over ANY failed read, and Route Operations and Keepers vanished over one. Each says its read failed now
// (Try again); a refresh that fails keeps what was shown. Answers (available: false, a refusal, no route) keep their words.
const auditFailed = ref(false)
const routeStatusFailed = ref(false)
const keepersFailed = ref(false)
const sweep = ref<{ to: string; amount: string }>({ to: '', amount: '' })
const sweeping = ref(false)
const sweepConfirm = ref(false)
const sweepError = ref<string | null>(null)
const sweepResult = ref<{ amount: string; to: string; tx?: string } | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null

// ── derived ────────────────────────────────────────────────────────────────
// §FEFRAME W2: the pool's legs as the rate names them (local_currency = this frame's unit, the x leg; peer_currency =
// the other frame's), never a seeded AVT numeraire over a BVT counter: on EU and ASIA both read as currencies that
// do not exist there.
const numeraire = computed(() => String(rate.value?.local_currency || localCurrency.value || ''))
const counter = computed(() => String(rate.value?.peer_currency
  || (config.value?.currency && config.value.currency !== numeraire.value ? config.value.currency : '')))
// D6-058 (2026-10-25): the pool card's units are the ones the registry names for each figure (x_currency, y_currency,
// mtm_currency). The pool keys keep the AVT/BVT pool's order, so x is the PEER frame's reserve wherever this frame's unit
// is not AVT: EU's desk showed ASIA's ACU reserve as ECU, its own ECU reserve as ACU and the spot's unit inverted. A
// registry that names no unit (before V0642) keeps the frame's pair, as before.
const poolX = computed(() => String(pool.value?.x_currency || numeraire.value))
const poolY = computed(() => String(pool.value?.y_currency || counter.value))
const poolMtm = computed(() => String(pool.value?.mtm_currency || poolX.value))
const x = computed(() => Number(pool.value?.x ?? NaN))   // the x reserve, in poolX
const y = computed(() => Number(pool.value?.y ?? NaN))   // the y reserve, in poolY
const spot = computed(() => {                 // poolX per poolY (x/y)
  const p = Number(pool.value?.spot_P)
  if (Number.isFinite(p)) return p
  return Number.isFinite(x.value) && Number.isFinite(y.value) && y.value !== 0 ? x.value / y.value : NaN
})
const inverseSpot = computed(() => (Number.isFinite(spot.value) && spot.value !== 0 ? 1 / spot.value : NaN))
const k = computed(() => {
  const kk = Number(pool.value?.k)
  if (Number.isFinite(kk)) return kk
  return Number.isFinite(x.value) && Number.isFinite(y.value) ? x.value * y.value : NaN
})
const mtm = computed(() => {
  const m = Number(pool.value?.mtm_avt)
  if (Number.isFinite(m)) return m
  return Number.isFinite(x.value) && Number.isFinite(y.value) && Number.isFinite(spot.value) ? x.value + y.value * spot.value : NaN
})
const feePct = computed(() => config.value?.fee_pct ?? null)
const rateMode = computed(() => config.value?.rate_mode ?? null)
// Enabled = the card says so OR the fast public rate signal (env-authoritative
// `_fx_enabled()`) says so. Tri-state (fxStatus) so the desk NEVER flashes
// "DISABLED" while the slower well-known card fetch is still in flight — the bug
// where a heavily-loaded mainframe (sandbox-a) showed FX DISABLED for ~2-5s.
const fxEnabled = computed(() => config.value?.enabled === true || rate.value?.available === true)
const fxResolved = computed(() => rateResolved.value || !loadingConfig.value)
// §FESUITE (2026-10-04): with the rate read failed and no card config at all, neither "enabled" nor "disabled" is known:
// the desk said "FX DISABLED" and "No fx block on this registry's card (FX off here)." with every read failed. publicRate
// answers null only when its read failed (a frame without FX answers available: false), so that null is "unread".
const fxUnread = computed(() => rateResolved.value && !loadingConfig.value && rate.value === null && !config.value)
const fxStatus = computed<'enabled' | 'disabled' | 'loading' | 'unread'>(() =>
  fxEnabled.value ? 'enabled' : fxUnread.value ? 'unread' : (fxResolved.value ? 'disabled' : 'loading'))
function retryFx() { void loadConfig(); void loadRate() }
// Pool fetched OK but no reserves yet (corridor not seeded on this frame).
const poolEmpty = computed(() => !loadingPool.value && !poolError.value && !Number.isFinite(x.value) && !Number.isFinite(y.value))

const settledCount = computed(() => swaps.value.filter(s => s.status === 'settled').length)
const refundedCount = computed(() => swaps.value.filter(s => s.status === 'refunded').length)

function fmtNum(n: number | undefined, dp = 2): string {
  if (n === undefined || !Number.isFinite(n)) return '—'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: dp })
}
function invOk(ok: boolean | undefined): string {
  return ok === true ? 'fx-idot--ok' : ok === false ? 'fx-idot--bad' : 'fx-idot--unknown'
}

// ── quote simulator (read-only; no funds move) ───────────────────────────────
const q = ref<{ receiver_did: string; amount: string }>({ receiver_did: '', amount: '1000' })
const quoteResult = ref<FxQuote | null>(null)
const quoteError = ref<string | null>(null)
const quoting = ref(false)
async function runQuote() {
  quoteError.value = null
  quoteResult.value = null
  if (!q.value.receiver_did || !q.value.amount) { quoteError.value = t('adminFxView.quoteValidationError'); return }
  quoting.value = true
  try {
    quoteResult.value = await fxService.quote({ receiver_did: q.value.receiver_did.trim(), amount: q.value.amount })
  } catch (e: any) {
    quoteError.value = e?.response?.data?.detail || e?.message || t('adminFxView.quoteFailed')
  } finally {
    quoting.value = false
  }
}

// ── loaders ──────────────────────────────────────────────────────────────────
async function loadPool() {
  loadingPool.value = true
  poolError.value = null
  try { pool.value = await fxService.pool() }
  catch (e: any) { poolError.value = e?.response?.status === 401 ? t('adminFxView.poolSignInError') : t('adminFxView.poolUnavailable') }
  finally { loadingPool.value = false; lastRefreshedAt.value = new Date() }
}
// §FESUITE V0578: a slow read of one frame's feed (a peer frame goes through the peer proxy) could answer after the
// frame picked next and land its swaps and routes under that frame's chip; only the newest pick's answer is drawn.
let feedSeq = 0
async function loadFeed() {
  const seq = ++feedSeq
  loadingFeed.value = true
  loadingRoutes.value = true
  feedNote.value = null
  // FX events land on the swap's SOURCE-frame ES. Local frame → read directly
  // with the `local` sentinel (no letter guessing on any deployment); foreign
  // frame → relay via the Multi-Frame peer-proxy to its own registry. A foreign
  // frame is only offered while its console session exists, so the
  // not-connected note is a stale-selection safety net (§FEDEVENTS).
  const opt = resolveOption(feedFrame.value)
  const f = opt.isLocal ? LOCAL_FRAME : opt.key
  let peerTok: string | null = null
  if (!opt.isLocal) {
    peerTok = mf.adminTokenFor(opt.key)
    if (!peerTok) {
      swaps.value = []
      swapsRead.value = false
      routes.value = []
      routesRead.value = false
      feedNote.value = t('adminFxView.foreignFrameNotConnected', { frame: opt.label })
      loadingFeed.value = false
      loadingRoutes.value = false
      lastRefreshedAt.value = new Date()
      return
    }
  }
  try {
    const rows = await fxService.swapEvents(f, 100, peerTok)
    if (seq !== feedSeq) return
    swaps.value = rows; swapsRead.value = true
  } catch {
    if (seq !== feedSeq) return
    swaps.value = []; swapsRead.value = false
  } finally { if (seq === feedSeq) loadingFeed.value = false }
  // Same frame selector drives the op→op route feed (gateway-delegated egress).
  try {
    const rows = await fxService.routeEvents(f, 50, peerTok)
    if (seq !== feedSeq) return
    routes.value = rows; routesRead.value = true
  } catch {
    if (seq !== feedSeq) return
    routes.value = []; routesRead.value = false
  } finally { if (seq === feedSeq) { loadingRoutes.value = false; lastRefreshedAt.value = new Date() } }
}
async function loadConfig() {
  loadingConfig.value = true
  try {
    // Resilient fetch (retries transient failures); fall back to the card fx the
    // useFrames composable already cached, so a single flaky well-known fetch
    // never mislabels an FX-enabled frame as "FX off here".
    const cfg = await fetchFxConfig()
    config.value = cfg || (localFx.value as unknown as FxConfig | null) || null
  } finally { loadingConfig.value = false }
}
async function loadRate() {
  // Fast, env-authoritative enabled signal (independent of the slow card fetch).
  try { rate.value = await fxService.publicRate() }
  catch { rate.value = null }
  finally { rateResolved.value = true }
}
async function loadAudit() {
  loadingAudit.value = true
  try { audit.value = await fxService.crossFrameAudit(); auditFailed.value = false }
  catch { auditFailed.value = !audit.value }
  finally { loadingAudit.value = false; lastRefreshedAt.value = new Date() }
}
async function loadRouteStatus() {
  try { routeStatus.value = await fxService.routeStatus(); routeStatusFailed.value = false }
  catch { routeStatusFailed.value = !routeStatus.value }
}

// ── §FEPARITY-R3: the two keepers + the parked-route queue ────────────────────
// Both keepers run live (the router holds real float and auto-refunds parked
// routes; the reserve pegs against the anchor) and the desk had no word for
// either. Config edits are a PUT of only the changed fields.
const rKeeper = ref<FxRouterKeeper | null>(null)
const vKeeper = ref<FxReserveKeeper | null>(null)
const deadLetters = ref<FxDeadLetterRow[]>([])
const dlFilter = ref<'pending' | 'all'>('pending')
// §FESUITE (2026-10-04): "No parked routes — nothing is waiting on recovery." was drawn with the read failed (the
// service answered [] for every failure): an all-clear on a money page that nobody had measured. The queue now says
// only what a read answered: 'read' for the filter it shows, 'failed' when this filter was never read.
const dlState = ref<'loading' | 'read' | 'failed'>('loading')
let dlShownFor: string | null = null   // the filter whose answer the list shows
const keeperEdit = ref<Record<string, string>>({})   // field → edited value (router keeper)
const keeperSaving = ref(false)
const keeperMsg = ref<{ ok: boolean; text: string } | null>(null)

async function loadKeepers() {
  const [r, v] = await Promise.allSettled([fxService.routerKeeper(), fxService.reserveKeeper()])
  if (r.status === 'fulfilled') rKeeper.value = r.value
  if (v.status === 'fulfilled') vKeeper.value = v.value
  keepersFailed.value = (r.status === 'rejected' && !rKeeper.value) || (v.status === 'rejected' && !vKeeper.value)
}
async function loadDeadLetters() {
  const filter = dlFilter.value
  if (dlShownFor !== filter) { deadLetters.value = []; dlState.value = 'loading' }
  try {
    const rows = await fxService.deadLetters(filter, 50)
    if (filter !== dlFilter.value) return   // a newer filter's read owns the list
    deadLetters.value = rows
    dlShownFor = filter
    dlState.value = 'read'
  } catch {
    if (filter !== dlFilter.value) return
    // a refresh that fails keeps what this filter last read; a filter never read says its read failed
    if (dlShownFor !== filter) dlState.value = 'failed'
  }
}
function editKeeper(field: string, cur: string) {
  keeperEdit.value = { ...keeperEdit.value, [field]: cur }
}
async function saveRouterKeeper(patch: Record<string, unknown>) {
  keeperSaving.value = true; keeperMsg.value = null
  try {
    await fxService.updateRouterKeeper(patch as any)
    keeperMsg.value = { ok: true, text: t('adminFxView.keeperSaved', 'Keeper config updated.') }
    keeperEdit.value = {}
    await loadKeepers()
  } catch (e: any) {
    // PUT throws by design — never imply a rejected config change saved.
    keeperMsg.value = { ok: false, text: e?.response?.data?.detail || e?.message || 'update failed' }
  } finally { keeperSaving.value = false }
}
async function saveReserveKeeper(patch: Record<string, unknown>) {
  keeperSaving.value = true; keeperMsg.value = null
  try {
    await fxService.updateReserveKeeper(patch as any)
    keeperMsg.value = { ok: true, text: t('adminFxView.keeperSaved', 'Keeper config updated.') }
    await loadKeepers()
  } catch (e: any) {
    keeperMsg.value = { ok: false, text: e?.response?.data?.detail || e?.message || 'update failed' }
  } finally { keeperSaving.value = false }
}
const dlParked = computed(() => deadLetters.value.reduce((s, r) => s + Number(r.amount || 0), 0))
const dlRemote = computed(() => deadLetters.value.filter(r => !r.locally_refundable && !r.held).length)
// §REPATLANE-2 (V0603): rows whose paying leg's outcome is not known; nothing refunds them on its own
const dlHeld = computed(() => deadLetters.value.filter(r => r.held).length)
// Sweep the @fx_router transit residue 1:1 to a target (admin, Δ-safe). Confirmed
// (financial action). Surfaces backend errors verbatim; refreshes residue on success.
async function doSweep() {
  sweepError.value = null; sweepResult.value = null
  const to = sweep.value.to.trim(); const amt = sweep.value.amount.trim()
  if (!to || !amt) { sweepError.value = t('adminFxView.sweepValidationError'); sweepConfirm.value = false; return }
  sweeping.value = true
  try {
    const res = await fxService.sweepRouter(to, amt)
    sweepResult.value = { amount: res.amount, to: res.to || to, tx: res.tx }
    sweep.value.amount = ''
    void loadRouteStatus()
  } catch (e: any) {
    sweepError.value = e?.response?.data?.detail || e?.message || t('adminFxView.sweepFailed')
  } finally { sweeping.value = false; sweepConfirm.value = false }
}
// loadConfig is part of refresh now — a transient miss on mount self-heals on the
// next tick instead of stranding the desk on "FX off here" until a manual reload.
function refreshAll() { void loadConfig(); void loadRate(); void loadPool(); void loadFeed(); void loadAudit(); void loadRouteStatus(); void loadKeepers(); void loadDeadLetters() }

// §FEDEVENTS: the default IS the local frame (sentinel — correct on every
// deployment, hetzner included), so the old letter-guessing auto-target watches
// are gone. If a selected foreign frame's session disconnects, fall back local.
function pickFeed(f: string) { feedFrame.value = f; void loadFeed() }
watch(selectableFrames, (opts) => {
  if (!opts.some(o => o.key === feedFrame.value)) { feedFrame.value = LOCAL_FRAME; void loadFeed() }
})

onMounted(() => {
  void loadConfig(); void loadRate(); void loadPool(); void loadFeed(); void loadAudit(); void loadRouteStatus()
  void loadKeepers(); void loadDeadLetters()
  refreshTimer = setInterval(refreshAll, 30000)
})
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })
</script>

<template>
  <div class="fx-desk">
    <!-- Header -->
    <header class="fx-head">
      <div class="fx-head-title">
        <h1>{{ t('adminFxView.pageTitle') }}</h1>
        <span class="fx-corridor">{{ numeraire }} ⇄ {{ counter }}</span>
      </div>
      <div class="fx-head-chips">
        <span class="fx-chip" aria-live="polite"
              :class="{ 'fx-chip--ok': fxStatus === 'enabled', 'fx-chip--off': fxStatus === 'disabled', 'fx-chip--pending': fxStatus === 'loading' || fxStatus === 'unread' }">
          {{ t('adminFxView.fxLabel') }} {{ fxStatus === 'enabled' ? t('adminFxView.fxEnabled') : fxStatus === 'disabled' ? t('adminFxView.fxDisabled') : fxStatus === 'unread' ? '—' : t('adminFxView.fxChecking') }}
        </span>
        <span class="fx-chip" v-if="rateMode">{{ t('adminFxView.modeLabel') }}: {{ String(rateMode).toUpperCase() }}</span>
        <span v-if="lastRefreshedAt" class="fx-updated" aria-live="polite">{{ t('adminFxView.updated') }} {{ lastRefreshedAt.toLocaleTimeString(appLocale()) }}</span>
        <button class="fx-chip fx-chip--btn" @click="refreshAll" :disabled="loadingPool" :title="t('adminFxView.refreshTitle')" :aria-label="loadingPool ? t('adminFxView.refreshingAriaLabel') : t('adminFxView.refreshAriaLabel')">{{ loadingPool ? t('adminFxView.refreshing') : t('adminFxView.refresh') }}</button>
      </div>
    </header>

    <!-- Rate strip -->
    <section class="fx-rate">
      <div class="fx-rate-main">
        <span class="fx-rate-pair">1 {{ counter }} =</span>
        <span class="fx-rate-val">{{ fmtNum(spot, 4) }}</span>
        <span class="fx-rate-unit">{{ numeraire }}</span>
      </div>
      <div class="fx-rate-meta">
        <span>1 {{ numeraire }} = {{ fmtNum(inverseSpot, 4) }} {{ counter }}</span>
        <span v-if="feePct !== null">{{ t('adminFxView.feeLabel') }} {{ feePct }}%</span>
        <span v-if="rateMode">{{ t('adminFxView.modeLabelLower') }} {{ rateMode }}</span>
        <span class="fx-rate-note">{{ t('adminFxView.rateNote') }}</span>
      </div>
    </section>

    <div class="fx-grid">
      <!-- Liquidity pool -->
      <section class="fx-card fx-pool">
        <h2>{{ t('adminFxView.liquidityPoolTitle') }} <small>{{ t('adminFxView.liquidityPoolSubtitle') }}</small></h2>
        <div v-if="loadingPool" class="fx-muted">{{ t('adminFxView.loadingPool') }}</div>
        <div v-else-if="poolError" class="fx-muted">{{ poolError }}</div>
        <div v-else-if="poolEmpty" class="fx-muted">{{ t('adminFxView.poolNotInitialized') }}</div>
        <template v-else>
          <div class="fx-pool-legs">
            <div class="fx-pool-leg" data-testid="fx-pool-x">
              <span class="fx-leg-glyph" :style="{ color: describe(poolX).accent }">{{ describe(poolX).glyph }}</span>
              <span class="fx-leg-amt">{{ fmtNum(x) }}</span>
              <span class="fx-leg-cur">{{ poolX }}</span>
              <span class="fx-leg-tag">{{ t('adminFxView.reserveX') }}</span>
            </div>
            <div class="fx-pool-leg" data-testid="fx-pool-y">
              <span class="fx-leg-glyph" :style="{ color: describe(poolY).accent }">{{ describe(poolY).glyph }}</span>
              <span class="fx-leg-amt">{{ fmtNum(y) }}</span>
              <span class="fx-leg-cur">{{ poolY }}</span>
              <span class="fx-leg-tag">{{ t('adminFxView.reserveY') }}</span>
            </div>
          </div>
          <div class="fx-pool-stats">
            <div data-testid="fx-pool-spot"><label>{{ t('adminFxView.spotP') }}</label><b>{{ fmtNum(spot, 5) }} {{ poolX }}/{{ poolY }}</b></div>
            <div><label>k</label><b>{{ fmtNum(k, 0) }}</b></div>
            <div data-testid="fx-pool-mtm"><label>{{ t('adminFxView.mtmLabel') }}</label><b>{{ fmtNum(mtm, 0) }} {{ poolMtm }}</b> <small>{{ t('adminFxView.mtmNote') }}</small></div>
          </div>
        </template>
      </section>

      <!-- Config (from card fees.fx) -->
      <section class="fx-card">
        <h2>{{ t('adminFxView.configTitle') }} <small>{{ t('adminFxView.configSubtitle') }}</small></h2>
        <div v-if="loadingConfig && !fxResolved" class="fx-muted">{{ t('adminFxView.loadingGeneric') }}</div>
        <template v-else-if="config && fxEnabled">
          <div class="fx-kv"><label>{{ t('adminFxView.rateModeLabel') }}</label><b>{{ config.rate_mode }}</b></div>
          <div class="fx-kv"><label>{{ t('adminFxView.feeLabel') }}</label><b>{{ config.fee_pct }}%</b></div>
          <div class="fx-kv" v-if="config.fee_split"><label>{{ t('adminFxView.feeSplitLabel') }}</label><b>{{ t('adminFxView.feeSplitPool') }} {{ config.fee_split.pool_retained_pct }}% · {{ t('adminFxView.feeSplitCollector') }} {{ config.fee_split.fee_collector_pct }}%</b></div>
          <div class="fx-kv" v-if="config.slippage_max != null"><label>{{ t('adminFxView.maxSlippageLabel') }}</label><b>{{ (config.slippage_max * 100).toFixed(2) }}%</b></div>
          <div class="fx-kv" v-if="config.breaker_pct != null"><label>{{ t('adminFxView.breakerLabel') }}</label><b>{{ (config.breaker_pct * 100).toFixed(2) }}%</b></div>
          <div class="fx-kv" v-if="config.size_cap"><label>{{ t('adminFxView.sizeCapLabel') }}</label><b>{{ Object.entries(config.size_cap).map(([c, v]) => `${fmtNum(Number(v))} ${c}`).join(' · ') }}</b></div>
          <div class="fx-kv" v-if="config.reserve_floor"><label>{{ t('adminFxView.reserveFloorLabel') }}</label><b>{{ Object.entries(config.reserve_floor).map(([c, v]) => `${fmtNum(Number(v))} ${c}`).join(' · ') }}</b></div>
        </template>
        <div v-else-if="!fxResolved" class="fx-muted">{{ t('adminFxView.checkingCorridor') }}</div>
        <div v-else-if="fxEnabled" class="fx-muted">{{ t('adminFxView.corridorLiveSyncing') }}</div>
        <ReadFailedNotice v-else-if="fxUnread" :retry="retryFx" dense />
        <div v-else-if="!config" class="fx-muted">{{ t('adminFxView.noFxBlock') }}</div>
        <div v-else class="fx-muted">{{ t('adminFxView.fxDisabledOnFrame', { numeraire, counter }) }}</div>
      </section>

      <!-- Integrity — live cross-frame-audit (I1/I2/I3) via the registry proxy (B8) -->
      <section class="fx-card fx-integrity">
        <h2>{{ t('adminFxView.integrityTitle') }} <small>{{ t('adminFxView.integritySubtitle') }}</small></h2>
        <div v-if="loadingAudit" class="fx-muted">{{ t('adminFxView.checkingInvariants') }}</div>
        <ReadFailedNotice v-else-if="auditFailed" :retry="loadAudit" dense data-testid="fx-audit-unread" />
        <div v-else-if="!audit" class="fx-muted">
          {{ t('adminFxView.auditNotExposed') }}
        </div>
        <template v-else>
          <div class="fx-integrity-head">
            <span class="fx-pill" :class="(audit.status === 'OK' || audit.cross_frame_consistent) ? 'fx-pill--ok' : 'fx-pill--refund'">{{ audit.status || (audit.cross_frame_consistent ? 'OK' : 'BREACH') }}</span>
            <span class="fx-muted" v-if="audit.total_foreign_events != null">{{ t('adminFxView.foreignEventsReplicated', { count: audit.total_foreign_events }) }}</span>
          </div>
          <div class="fx-ilist">
            <div class="fx-irow">
              <span class="fx-idot" :class="invOk(audit.fx_invariants?.I1_per_frame_delta_zero?.ok)" aria-hidden="true"></span>
              <span class="fx-ilabel">{{ t('adminFxView.i1Label') }}</span>
              <span class="fx-ival">Δ {{ fmtNum(audit.fx_invariants?.I1_per_frame_delta_zero?.delta, 4) }}</span>
            </div>
            <div class="fx-irow">
              <span class="fx-idot" :class="invOk(audit.fx_invariants?.I2_reserve_solvency?.ok)" aria-hidden="true"></span>
              <span class="fx-ilabel">{{ t('adminFxView.i2Label') }}</span>
              <span class="fx-ival">{{ fmtNum(audit.fx_invariants?.I2_reserve_solvency?.reserve_balance) }} / {{ t('adminFxView.floorLabel') }} {{ fmtNum(audit.fx_invariants?.I2_reserve_solvency?.floor) }} {{ audit.fx_invariants?.I2_reserve_solvency?.currency || '' }}</span>
            </div>
            <div class="fx-irow">
              <span class="fx-idot" :class="invOk(audit.fx_invariants?.I3_value_conservation?.ok)" aria-hidden="true"></span>
              <span class="fx-ilabel">{{ t('adminFxView.i3Label') }}</span>
              <span class="fx-ival">{{ audit.fx_invariants?.I3_value_conservation?.swaps_checked ?? 0 }} {{ t('adminFxView.checked') }} · {{ audit.fx_invariants?.I3_value_conservation?.breaches?.length ?? 0 }} {{ t('adminFxView.breaches') }}</span>
            </div>
          </div>
        </template>
      </section>
    </div>

    <!-- Flow + volume -->
    <section class="fx-card">
      <h2>{{ t('adminFxView.flowTitle') }} <small>{{ t('adminFxView.flowSubtitle', { frame: feedFrameLabel }) }}</small></h2>
      <div class="fx-flow">
        <div class="fx-flow-stat"><b>{{ swapsRead ? settledCount : '—' }}</b><label>{{ t('adminFxView.settled') }}</label></div>
        <div class="fx-flow-stat fx-flow-stat--warn"><b>{{ swapsRead ? refundedCount : '—' }}</b><label>{{ t('adminFxView.refunded') }}</label></div>
        <div class="fx-flow-stat"><b>{{ swapsRead ? swaps.length : '—' }}</b><label>{{ t('adminFxView.totalShown') }}</label></div>
      </div>
    </section>

    <!-- Live swap feed -->
    <section class="fx-card">
      <div class="fx-feed-head">
        <h2>{{ t('adminFxView.swapFeedTitle') }}</h2>
        <div class="fx-feed-frames">
          <!-- §FEDEVENTS: LOCAL + connected console sessions only — no dead letters. -->
          <button
            v-for="o in selectableFrames" :key="o.key" class="fx-fchip"
            :class="{ 'fx-fchip--on': feedFrame === o.key }" :aria-pressed="feedFrame === o.key"
            :aria-label="t('adminFxView.frameButtonAriaLabel', { frame: o.label })"
            :title="o.isLocal ? `${o.label} — this registry` : `${o.label} — connected sibling frame`"
            @click="pickFeed(o.key)"
          >{{ o.label }}</button>
        </div>
      </div>
      <div v-if="loadingFeed" class="fx-muted">{{ t('adminFxView.loadingSwaps') }}</div>
      <div v-else-if="feedNote" class="fx-muted">{{ feedNote }}</div>
      <ReadFailedNotice v-else-if="!swapsRead" :retry="loadFeed" dense />
      <div v-else-if="!swaps.length" class="fx-muted">{{ t('adminFxView.noSwapsRecorded', { frame: feedFrameLabel }) }}</div>
      <div v-else class="fx-table-wrap" style="overflow-x:auto;"><table class="fx-table">
        <thead><tr><th scope="col">{{ t('adminFxView.colTime') }}</th><th scope="col">{{ t('adminFxView.colDir') }}</th><th scope="col">{{ t('adminFxView.colIn') }}</th><th scope="col">{{ t('adminFxView.colRate') }}</th><th scope="col">{{ t('adminFxView.colFee') }}</th><th scope="col">{{ t('adminFxView.colOut') }}</th><th scope="col">{{ t('adminFxView.colStatus') }}</th><th scope="col"><span class="fx-sr-only">{{ t('adminFxView.colDetails') }}</span></th></tr></thead>
        <tbody>
          <template v-for="s in swaps" :key="s.txId + s.ts">
            <tr :class="{ 'fx-row--refund': s.status === 'refunded' }">
              <td class="fx-mono">{{ s.ts ? new Date(s.ts).toLocaleTimeString(appLocale()) : '—' }}</td>
              <td class="fx-mono">{{ s.sourceCurrency || '?' }}→{{ s.destCurrency || '?' }}</td>
              <td class="fx-mono">{{ fmtNum(s.amountIn) }} {{ s.sourceCurrency || '' }}</td>
              <td class="fx-mono">{{ fmtNum(s.rate, 4) }}</td>
              <td class="fx-mono">{{ fmtNum(s.fee) }}</td>
              <td class="fx-mono">{{ s.status === 'refunded' ? '—' : fmtNum(s.amountOut) }} {{ s.status === 'refunded' ? '' : (s.destCurrency || '') }}</td>
              <td><span class="fx-pill" :class="s.status === 'refunded' ? 'fx-pill--refund' : 'fx-pill--ok'" :title="s.refundReason || ''">{{ s.status }}</span></td>
              <td><button class="fx-expand" :class="{ 'fx-expand--open': expandedTx === (s.txId + s.ts) }" :aria-expanded="expandedTx === (s.txId + s.ts)" :aria-label="expandedTx === (s.txId + s.ts) ? t('adminFxView.hideRawEvent') : t('adminFxView.showRawEvent')" @click="expandedTx = expandedTx === (s.txId + s.ts) ? null : (s.txId + s.ts)"><span aria-hidden="true">▸</span></button></td>
            </tr>
            <tr v-if="expandedTx === (s.txId + s.ts)" class="fx-row-detail">
              <td colspan="8"><JsonViewer :data="s.raw" /></td>
            </tr>
          </template>
        </tbody>
      </table></div>
    </section>

    <!-- op→op route operations: @fx_router transit account + residue sweep (admin, Δ-safe) -->
    <section class="fx-card fx-routeops" v-if="routeStatus && (routeStatus.router_did || routeStatus.route_enabled)">
      <h2>{{ t('adminFxView.routeOpsTitle') }} <small>{{ t('adminFxView.routeOpsSubtitle') }}</small></h2>
      <div class="fx-routeops-grid">
        <div class="fx-kv"><label>{{ t('adminFxView.routeEngineLabel') }}</label><b :class="routeStatus.route_enabled ? 'fx-ok' : 'fx-off'">{{ routeStatus.route_enabled ? t('adminFxView.routeEngineEnabled') : t('adminFxView.routeEngineDisabled') }}</b></div>
        <div class="fx-kv" v-if="routeStatus.router_did"><label>{{ t('adminFxView.fxRouterLabel') }}</label><b class="fx-mono" :title="routeStatus.router_did">{{ routeStatus.router_did.slice(0, 30) }}…</b></div>
        <div class="fx-kv"><label>{{ t('adminFxView.liquidResidueLabel') }}</label><b>{{ routeStatus.router_liquid != null ? fmtNum(Number(routeStatus.router_liquid), 6) : '—' }} {{ routeStatus.local_currency }}</b></div>
        <div class="fx-kv" v-if="routeStatus.peers && routeStatus.peers.length"><label>{{ t('adminFxView.reservePeersLabel') }}</label><b>{{ routeStatus.peers.map(p => p.currency).filter(Boolean).join(' · ') || '—' }}</b></div>
        <div class="fx-kv" v-if="routeStatus.parent_gateway && routeStatus.parent_gateway.registry_id"><label>{{ t('adminFxView.parentGatewayLabel') }}</label><b class="fx-mono">{{ routeStatus.parent_gateway.registry_id }}</b></div>
      </div>
      <p class="fx-muted" style="margin:0 0 8px;">{{ t('adminFxView.sweepDescription') }}</p>
      <div class="fx-sweep-form">
        <label>{{ t('adminFxView.sweepToDIDLabel') }} <input v-model="sweep.to" type="text" :placeholder="t('adminFxView.sweepToDIDPlaceholder')" /></label>
        <label>{{ t('adminFxView.amountLabel') }}
          <span class="fx-inwrap"><input v-model="sweep.amount" type="text" inputmode="decimal" :placeholder="routeStatus.router_liquid || '0'" />
            <button type="button" class="fx-max" v-if="routeStatus.router_liquid && Number(routeStatus.router_liquid) > 0" @click="sweep.amount = routeStatus.router_liquid || ''">{{ t('adminFxView.maxButton') }}</button></span>
        </label>
        <button class="fx-qbtn" :disabled="sweeping || !sweep.to || !sweep.amount || !(Number(routeStatus.router_liquid) > 0)" @click="sweepConfirm = true">{{ t('adminFxView.sweepResidueButton') }}</button>
      </div>
      <div v-if="sweepConfirm" class="fx-sweep-confirm" role="alertdialog" :aria-label="t('adminFxView.sweepConfirmAriaLabel')">
        <span>{{ t('adminFxView.sweepConfirmText', { amount: sweep.amount, currency: routeStatus.local_currency, to: sweep.to.slice(0, 28) }) }}</span>
        <div class="fx-sweep-actions">
          <button class="fx-qbtn" :disabled="sweeping" @click="doSweep">{{ sweeping ? t('adminFxView.sweeping') : t('adminFxView.confirmSweep') }}</button>
          <button class="fx-chip fx-chip--btn" :disabled="sweeping" @click="sweepConfirm = false">{{ t('adminFxView.cancelButton') }}</button>
        </div>
      </div>
      <div v-if="sweepError" class="fx-muted fx-err">{{ sweepError }}</div>
      <div v-else-if="sweepResult" class="fx-muted fx-ok">{{ t('adminFxView.sweepSuccess', { amount: sweepResult.amount, currency: routeStatus.local_currency, to: sweepResult.to.slice(0, 24) }) }} <span v-if="sweepResult.tx">({{ t('adminFxView.txLabel') }} {{ sweepResult.tx.slice(0, 8) }})</span></div>
    </section>
    <section class="fx-card fx-routeops" v-else-if="routeStatusFailed" data-testid="fx-routeops-unread">
      <h2>{{ t('adminFxView.routeOpsTitle') }} <small>{{ t('adminFxView.routeOpsSubtitle') }}</small></h2>
      <ReadFailedNotice :retry="loadRouteStatus" dense />
    </section>

    <!-- §FEPARITY-R3 — FX KEEPERS. Both run live; the desk had no word for either. -->
    <section class="fx-card" v-if="rKeeper || vKeeper || keepersFailed" data-tour="fx-keepers">
      <div class="fx-feed-head">
        <h2>{{ t('adminFxView.keepersTitle', 'Keepers') }}
          <small>{{ t('adminFxView.keepersSubtitle', 'automatic liquidity managers — env gate beats config') }}</small></h2>
      </div>

      <ReadFailedNotice v-if="keepersFailed" :retry="loadKeepers" dense data-testid="fx-keepers-unread" />
      <div v-if="keeperMsg" class="fx-muted" :class="keeperMsg.ok ? 'fx-ok' : 'fx-err'">{{ keeperMsg.text }}</div>

      <div class="fx-keeper-grid">
        <!-- Router keeper -->
        <div class="fx-keeper" v-if="rKeeper">
          <div class="fx-keeper-head">
            <b>{{ t('adminFxView.routerKeeperTitle', 'Router float keeper') }}</b>
            <span class="fx-chip" :class="rKeeper.active ? 'fx-ok' : 'fx-off'">
              {{ rKeeper.active ? t('adminFxView.keeperActive', 'ACTIVE') : t('adminFxView.keeperInactive', 'INACTIVE') }}
            </span>
          </div>
          <p class="fx-muted fx-keeper-note">
            {{ t('adminFxView.routerKeeperNote', 'Tops @fx_router up to the target float and auto-refunds parked routes.') }}
            <template v-if="!rKeeper.env_gate_enabled">
              <br><b class="fx-err">{{ t('adminFxView.keeperEnvOff', 'FX_ROUTER_KEEPER_ENABLED is off — this keeper cannot run regardless of the config below.') }}</b>
            </template>
          </p>
          <div class="fx-routeops-grid">
            <div class="fx-kv"><label>{{ t('adminFxView.keeperFloatLabel', 'Router liquid') }}</label>
              <b>{{ rKeeper.router_liquid != null ? fmtNum(Number(rKeeper.router_liquid), 2) : '—' }} {{ rKeeper.currency }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperTargetLabel', 'Target float') }}</label>
              <b>{{ fmtNum(Number(rKeeper.config.target_float), 2) }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperMinLabel', 'Min float') }}</label>
              <b>{{ fmtNum(Number(rKeeper.config.min_float), 2) }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperSourceLabel', 'Top-up source') }}</label><b>{{ rKeeper.config.source }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperIntervalLabel', 'Check interval') }}</label><b>{{ rKeeper.config.check_interval_sec }}s</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperRefundLabel', 'Auto-refund') }}</label>
              <b :class="rKeeper.config.dead_letter_refund_enabled ? 'fx-ok' : 'fx-off'">
                {{ rKeeper.config.dead_letter_refund_enabled ? t('adminFxView.onLabel', 'on') : t('adminFxView.offLabel', 'off') }}
                ({{ t('adminFxView.keeperRetriesLabel', 'max') }} {{ rKeeper.config.dead_letter_max_retries }})</b></div>
          </div>
          <div class="fx-keeper-actions">
            <label class="fx-keeper-field">
              <span>{{ t('adminFxView.keeperTargetLabel', 'Target float') }}</span>
              <input type="text" inputmode="decimal"
                     :value="keeperEdit.target_float ?? rKeeper.config.target_float"
                     @input="editKeeper('target_float', ($event.target as HTMLInputElement).value)" />
            </label>
            <button class="fx-qbtn" :disabled="keeperSaving || keeperEdit.target_float === undefined"
                    @click="saveRouterKeeper({ target_float: keeperEdit.target_float })">
              {{ keeperSaving ? t('adminFxView.savingLabel', 'Saving…') : t('adminFxView.saveLabel', 'Save') }}
            </button>
            <button class="fx-chip fx-chip--btn" :disabled="keeperSaving"
                    @click="saveRouterKeeper({ enabled: !rKeeper.config.enabled })">
              {{ rKeeper.config.enabled ? t('adminFxView.keeperDisable', 'Disable') : t('adminFxView.keeperEnable', 'Enable') }}
            </button>
          </div>
          <div class="fx-muted fx-keeper-by" v-if="rKeeper.config.updated_by">
            {{ t('adminFxView.keeperUpdatedBy', 'last change') }} {{ rKeeper.config.updated_by }}
            <span v-if="rKeeper.config.updated_at">· {{ new Date(rKeeper.config.updated_at).toLocaleDateString(appLocale()) }}</span>
          </div>
        </div>

        <!-- Reserve peg keeper -->
        <div class="fx-keeper" v-if="vKeeper">
          <div class="fx-keeper-head">
            <b>{{ t('adminFxView.reserveKeeperTitle', 'Reserve peg keeper') }}</b>
            <span class="fx-chip" :class="vKeeper.active ? 'fx-ok' : 'fx-off'">
              {{ vKeeper.active ? t('adminFxView.keeperActive', 'ACTIVE') : t('adminFxView.keeperInactive', 'INACTIVE') }}
            </span>
          </div>
          <p class="fx-muted fx-keeper-note">
            {{ t('adminFxView.reserveKeeperNote', 'Holds the local reserve at a ratio against the anchor currency, within a deadband.') }}
            <template v-if="!vKeeper.env_gate_enabled">
              <br><b class="fx-err">{{ t('adminFxView.keeperEnvOffReserve', 'The reserve keeper env gate is off — config below is inert.') }}</b>
            </template>
          </p>
          <div class="fx-routeops-grid">
            <div class="fx-kv"><label>{{ t('adminFxView.keeperAnchorLabel', 'Anchor') }}</label>
              <b>{{ vKeeper.config.anchor_currency }} × {{ vKeeper.config.ratio_vs_anchor }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperTargetLabel', 'Target float') }}</label>
              <b>{{ fmtNum(Number(vKeeper.config.target_float), 0) }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperBandLabel', 'Band') }}</label>
              <b>{{ fmtNum(Number(vKeeper.config.min_float), 0) }} – {{ fmtNum(Number(vKeeper.config.max_float), 0) }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperDeadbandLabel', 'Deadband') }}</label><b>{{ vKeeper.config.deadband_pct }}%</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperMaxMoveLabel', 'Max move/cycle') }}</label>
              <b>{{ fmtNum(Number(vKeeper.config.max_move_per_cycle), 0) }}</b></div>
            <div class="fx-kv"><label>{{ t('adminFxView.keeperModeLabel', 'Mode') }}</label><b>{{ vKeeper.config.operator_mode }}</b></div>
          </div>
          <div class="fx-keeper-actions">
            <button class="fx-chip fx-chip--btn" :disabled="keeperSaving"
                    @click="saveReserveKeeper({ enabled: !vKeeper.config.enabled })">
              {{ vKeeper.config.enabled ? t('adminFxView.keeperDisable', 'Disable') : t('adminFxView.keeperEnable', 'Enable') }}
            </button>
          </div>
          <div class="fx-muted fx-keeper-by" v-if="vKeeper.config.updated_by">
            {{ t('adminFxView.keeperUpdatedBy', 'last change') }} {{ vKeeper.config.updated_by }}
            <span v-if="vKeeper.config.updated_at">· {{ new Date(vKeeper.config.updated_at).toLocaleDateString(appLocale()) }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- §FEPARITY-R3 — PARKED ROUTES. The keepers reported a count and nothing else. -->
    <section class="fx-card" data-tour="fx-deadletters">
      <div class="fx-feed-head">
        <h2>{{ t('adminFxView.parkedTitle', 'Parked routes') }}
          <small>{{ t('adminFxView.parkedSubtitle', 'funds sitting at an @fx_router after a failed route leg') }}</small></h2>
        <div class="fx-head-chips">
          <button class="fx-chip fx-chip--btn" :class="{ 'fx-chip--on': dlFilter === 'pending' }"
                  @click="dlFilter = 'pending'; loadDeadLetters()">{{ t('adminFxView.parkedPending', 'Pending') }}</button>
          <button class="fx-chip fx-chip--btn" :class="{ 'fx-chip--on': dlFilter === 'all' }"
                  @click="dlFilter = 'all'; loadDeadLetters()">{{ t('adminFxView.parkedAll', 'All') }}</button>
        </div>
      </div>

      <ReadFailedNotice v-if="dlState === 'failed'" :retry="loadDeadLetters" dense />
      <p v-else-if="dlState === 'loading'" class="fx-muted">{{ t('common.loading', 'Loading…') }}</p>
      <p v-else-if="!deadLetters.length" class="fx-muted">
        {{ dlFilter === 'pending'
            ? t('adminFxView.parkedNonePending', 'No parked routes — nothing is waiting on recovery.')
            : t('adminFxView.parkedNone', 'No parked routes on record.') }}
      </p>

      <template v-else>
        <div class="fx-routeops-grid">
          <div class="fx-kv"><label>{{ t('adminFxView.parkedCountLabel', 'Rows') }}</label><b>{{ deadLetters.length }}</b></div>
          <div class="fx-kv"><label>{{ t('adminFxView.parkedTotalLabel', 'Total parked') }}</label><b>{{ fmtNum(dlParked, 2) }}</b></div>
          <div class="fx-kv" v-if="dlRemote"><label>{{ t('adminFxView.parkedRemoteLabel', 'Awaiting far frame') }}</label><b class="fx-warn">{{ dlRemote }}</b></div>
          <div class="fx-kv" v-if="dlHeld" data-testid="fx-dl-held-count"><label>{{ t('adminFxView.parkedHeldLabel', 'Held') }}</label><b class="fx-warn">{{ dlHeld }}</b></div>
        </div>
        <p v-if="dlRemote" class="fx-muted fx-keeper-note">
          <b class="fx-warn">{{ t('adminFxView.parkedRemoteNoteTitle', 'Not retryable here.') }}</b>
          {{ t('adminFxView.parkedRemoteNote', 'Rows marked “far frame” parked at the DESTINATION frame’s @fx_router, so the local keeper skips them by design. Recovery is re-delivery on that frame; the egress carries a stable route memo so a retry dedupes at the TEG rather than paying twice.') }}
        </p>
        <p v-if="dlHeld" class="fx-muted fx-keeper-note" data-testid="fx-dl-held-note">
          <b class="fx-warn">{{ t('adminFxView.parkedHeldNoteTitle', 'Held, nothing refunded.') }}</b>
          {{ t('adminFxView.parkedHeldNote', 'Rows marked “held” are payments whose paying leg may have moved: refunding them could pay twice. The keeper finishes a held local delivery under its own key; a held swap, two-phase delivery, re-delivery or refund waits for a ledger read (its keys or transfer id are in the row); until then this frame does not deliver or refund that route again.') }}
        </p>
        <div class="fx-dl-list">
          <div v-for="r in deadLetters" :key="r.id" class="fx-dl-row" :class="{ 'fx-dl-row--remote': !r.locally_refundable && !r.held }">
            <!-- a row the keeper gave up on (failed) is not settled: it reads as a warning, like a pending one -->
            <span class="fx-chip" data-testid="fx-dl-status" :class="['pending', 'sweeping', 'failed'].includes(r.status) ? 'fx-warn' : 'fx-ok'">{{ r.status }}</span>
            <span class="fx-mono fx-dl-amt">{{ fmtNum(Number(r.amount), 4) }} {{ r.currency }}</span>
            <span class="fx-mono fx-dl-route" :title="r.route_id">{{ r.route_id.slice(0, 14) }}…</span>
            <span class="fx-chip fx-dl-phase" data-testid="fx-dl-phase" :title="r.held ? t('adminFxView.parkedHeldTip', 'a paying leg whose outcome is not known: nothing refunds it on its own') : r.locally_refundable ? t('adminFxView.parkedLocalTip', 'the local keeper can refund this') : t('adminFxView.parkedRemoteTip', 'parked on the destination frame — local keeper skips it')">
              {{ r.held ? t('adminFxView.parkedHeld', 'held') : r.locally_refundable ? t('adminFxView.parkedLocal', 'local') : t('adminFxView.parkedRemote', 'far frame') }}
            </span>
            <span class="fx-muted fx-dl-meta">{{ t('adminFxView.parkedRetriesLabel', 'retries') }} {{ r.retries }}</span>
            <span class="fx-muted fx-dl-meta" v-if="r.created_at">{{ new Date(r.created_at).toLocaleDateString(appLocale()) }}</span>
            <span class="fx-muted fx-dl-err" v-if="r.last_error" :title="r.last_error">{{ r.last_error.slice(0, 60) }}</span>
          </div>
        </div>
      </template>
    </section>

    <!-- op→op cross-frame FX routes (gateway-delegated egress) -->
    <section class="fx-card">
      <div class="fx-feed-head">
        <h2>{{ t('adminFxView.crossFrameRoutesTitle') }} <small>{{ t('adminFxView.crossFrameRoutesSubtitle', { frame: feedFrameLabel }) }}</small></h2>
        <span class="fx-muted" style="font-size:0.66rem;">{{ t('adminFxView.routeFlowDiagram') }}</span>
      </div>
      <div v-if="loadingRoutes" class="fx-muted">{{ t('adminFxView.loadingRoutes') }}</div>
      <div v-else-if="feedNote" class="fx-muted">{{ feedNote }}</div>
      <ReadFailedNotice v-else-if="!routesRead" :retry="loadFeed" dense />
      <div v-else-if="!routes.length" class="fx-muted">{{ t('adminFxView.noRoutesRecorded', { frame: feedFrameLabel }) }}</div>
      <div v-else class="fx-table-wrap" style="overflow-x:auto;"><table class="fx-table">
        <thead><tr><th scope="col">{{ t('adminFxView.colTime') }}</th><th scope="col">{{ t('adminFxView.colRoute') }}</th><th scope="col">{{ t('adminFxView.colDir') }}</th><th scope="col">{{ t('adminFxView.colIn') }}</th><th scope="col">{{ t('adminFxView.colOut') }}</th><th scope="col">{{ t('adminFxView.colHops') }}</th><th scope="col">{{ t('adminFxView.colStatus') }}</th><th scope="col"><span class="fx-sr-only">{{ t('adminFxView.colDetails') }}</span></th></tr></thead>
        <tbody>
          <template v-for="r in routes" :key="r.routeId + r.ts">
            <tr :class="{ 'fx-row--refund': r.status !== 'settled' }">
              <td class="fx-mono">{{ r.ts ? new Date(r.ts).toLocaleTimeString(appLocale()) : '—' }}</td>
              <td class="fx-mono" :title="r.routeId">{{ (r.routeId || '').slice(0, 8) || '—' }}</td>
              <td class="fx-mono">{{ r.sourceCurrency || '?' }}→{{ r.destCurrency || '?' }}</td>
              <td class="fx-mono">{{ fmtNum(r.amountIn) }} {{ r.sourceCurrency || '' }}</td>
              <td class="fx-mono">{{ r.status !== 'settled' ? '—' : fmtNum(r.amountOut) }} {{ r.status !== 'settled' ? '' : (r.destCurrency || '') }}</td>
              <td class="fx-mono">{{ r.hopCount ?? '—' }}</td>
              <td><span class="fx-pill" :class="r.status === 'settled' ? 'fx-pill--ok' : (r.status === 'dead_letter' ? 'fx-pill--dead' : 'fx-pill--refund')" :title="r.status === 'dead_letter' ? 'Converted funds parked at the destination gateway @fx_router (egress failed post-conversion) — swept by the dead-letter reconciler; NOT returned to sender' : ''">{{ r.status }}</span></td>
              <td><button class="fx-expand" :class="{ 'fx-expand--open': expandedTx === ('R' + r.routeId + r.ts) }" :aria-expanded="expandedTx === ('R' + r.routeId + r.ts)" :aria-label="expandedTx === ('R' + r.routeId + r.ts) ? t('adminFxView.hideRawRouteEvent') : t('adminFxView.showRawRouteEvent')" @click="expandedTx = expandedTx === ('R' + r.routeId + r.ts) ? null : ('R' + r.routeId + r.ts)"><span aria-hidden="true">▸</span></button></td>
            </tr>
            <tr v-if="expandedTx === ('R' + r.routeId + r.ts)" class="fx-row-detail">
              <td colspan="8"><JsonViewer :data="r.raw" /></td>
            </tr>
          </template>
        </tbody>
      </table></div>
    </section>

    <!-- Quote simulator (read-only) -->
    <section class="fx-card fx-quote">
      <h2>{{ t('adminFxView.quoteSimulatorTitle') }} <small>{{ t('adminFxView.quoteSimulatorSubtitle') }}</small></h2>
      <div class="fx-quote-form">
        <label>{{ t('adminFxView.recipientDIDLabel') }} <input v-model="q.receiver_did" type="text" :placeholder="t('adminFxView.recipientDIDPlaceholder')" @keyup.enter="runQuote" /></label>
        <label>{{ t('adminFxView.amountLabel') }} <input v-model="q.amount" type="text" inputmode="decimal" @keyup.enter="runQuote" /></label>
        <button class="fx-qbtn" :disabled="quoting || !q.receiver_did || !q.amount" @click="runQuote">{{ quoting ? t('adminFxView.quoting') : t('adminFxView.quoteButton') }}</button>
      </div>
      <div v-if="quoteError" class="fx-muted fx-err">{{ quoteError }}</div>
      <div v-else-if="quoteResult" class="fx-quote-out">
        <span v-if="quoteResult.same_currency" class="fx-muted">{{ t('adminFxView.sameCurrency') }}</span>
        <span>{{ t('adminFxView.quoteIn') }} <b>{{ fmtNum(Number(quoteResult.amount_in)) }} {{ quoteResult.source_currency }}</b></span>
        <span>{{ t('adminFxView.quoteRate') }} <b>{{ fmtNum(Number(quoteResult.rate), 5) }}</b> <small v-if="quoteResult.rate_mode">({{ quoteResult.rate_mode }})</small></span>
        <span v-if="quoteResult.slippage != null">{{ t('adminFxView.quoteSlippage') }} <b>{{ (Number(quoteResult.slippage) * 100).toFixed(3) }}%</b></span>
        <span>{{ t('adminFxView.quoteFeeLabel') }} <b>{{ fmtNum(Number(quoteResult.fee)) }}</b></span>
        <span class="fx-quote-net">{{ t('adminFxView.quoteReceive') }} <b>{{ fmtNum(Number(quoteResult.amount_out)) }} {{ quoteResult.dest_currency }}</b></span>
        <span v-if="quoteResult.expires_at" class="fx-muted">{{ t('adminFxView.quoteExpires') }} {{ new Date(quoteResult.expires_at).toLocaleTimeString(appLocale()) }}</span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fx-desk { padding: 18px; max-width: 1200px; margin: 0 auto; color: rgba(230, 249, 255, 0.92); }
.fx-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
.fx-head-title { display: flex; align-items: center; gap: 12px; }
.fx-head-glyph { font-size: 1.4rem; color: var(--nc-primary, #00d2d2); }
.fx-head-title h1 { font-size: 1.1rem; font-weight: 700; letter-spacing: 0.08em; margin: 0; font-family: 'Fira Code', monospace; }
.fx-corridor { font-family: 'Fira Code', monospace; font-size: 0.8rem; padding: 2px 10px; border: 1px solid rgba(var(--nc-primary-rgb), 0.3); border-radius: 12px; color: rgba(var(--nc-primary-rgb), 0.9); }
.fx-head-chips { display: flex; gap: 8px; align-items: center; }
.fx-chip { font-family: 'Fira Code', monospace; font-size: 0.7rem; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(255, 255, 255, 0.15); }
.fx-chip--ok { color: #00e676; border-color: rgba(0, 230, 118, 0.4); }
.fx-chip--off { color: #ff5252; border-color: rgba(255, 82, 82, 0.4); }
.fx-chip--pending { color: #ffd54f; border-color: rgba(255, 213, 79, 0.4); animation: fx-chip-pulse 1.2s ease-in-out infinite; }
@keyframes fx-chip-pulse { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
.fx-chip--btn { cursor: pointer; background: transparent; color: rgba(var(--nc-primary-rgb), 0.9); }
.fx-rate { background: rgba(8, 12, 20, 0.6); border: 1px solid rgba(var(--nc-primary-rgb), 0.14); border-radius: 10px; padding: 16px 20px; margin-bottom: 14px; }
.fx-rate-main { display: flex; align-items: baseline; gap: 10px; }
.fx-rate-pair { font-family: 'Fira Code', monospace; color: rgba(230, 249, 255, 0.6); }
.fx-rate-val { font-family: 'Fira Code', monospace; font-size: 2rem; font-weight: 700; color: var(--nc-primary, #00d2d2); }
.fx-rate-unit { font-family: 'Fira Code', monospace; color: rgba(230, 249, 255, 0.7); }
.fx-rate-meta { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 6px; font-size: 0.75rem; color: rgba(230, 249, 255, 0.55); font-family: 'Fira Code', monospace; }
.fx-rate-note { font-style: italic; opacity: 0.7; }
.fx-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin-bottom: 14px; }
.fx-card { background: rgba(8, 12, 20, 0.55); border: 1px solid rgba(var(--nc-primary-rgb), 0.12); border-radius: 10px; padding: 14px 16px; margin-bottom: 14px; }
.fx-card h2 { font-size: 0.85rem; font-weight: 700; letter-spacing: 0.04em; margin: 0 0 10px; font-family: 'Fira Code', monospace; }
.fx-card h2 small { font-weight: 400; opacity: 0.5; font-size: 0.7rem; margin-left: 6px; }
.fx-muted { color: rgba(230, 249, 255, 0.5); font-size: 0.8rem; }
.fx-err { color: #ff8a80; }
.fx-pool-legs { display: flex; gap: 18px; margin-bottom: 12px; }
.fx-pool-leg { display: flex; flex-direction: column; }
.fx-leg-glyph { font-size: 1.1rem; }
.fx-leg-amt { font-family: 'Fira Code', monospace; font-size: 1.2rem; font-weight: 700; }
.fx-leg-cur { font-family: 'Fira Code', monospace; font-size: 0.75rem; opacity: 0.7; }
.fx-leg-tag { font-size: 0.6rem; opacity: 0.4; text-transform: uppercase; letter-spacing: 0.1em; }
.fx-pool-stats { display: flex; gap: 22px; flex-wrap: wrap; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1); padding-top: 10px; }
.fx-pool-stats label { display: block; font-size: 0.6rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.1em; }
.fx-pool-stats b, .fx-kv b { font-family: 'Fira Code', monospace; }
.fx-pool-stats small { opacity: 0.4; font-size: 0.6rem; }
.fx-kv { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; font-size: 0.8rem; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
.fx-kv label { opacity: 0.55; }
.fx-integrity code { font-family: 'Fira Code', monospace; color: rgba(var(--nc-primary-rgb), 0.8); }
.fx-integrity-head { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.fx-ilist { display: flex; flex-direction: column; gap: 2px; }
.fx-irow { display: flex; align-items: center; gap: 10px; padding: 5px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.04); font-size: 0.78rem; }
.fx-idot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 8px; background: rgba(230, 249, 255, 0.3); box-shadow: 0 0 6px currentColor; }
.fx-idot--ok { background: #00e676; color: #00e676; }
.fx-idot--bad { background: #ff5252; color: #ff5252; }
.fx-idot--unknown { background: rgba(230, 249, 255, 0.3); color: transparent; box-shadow: none; }
.fx-ilabel { flex: 1; opacity: 0.8; }
.fx-ival { font-family: 'Fira Code', monospace; opacity: 0.7; }
.fx-flow { display: flex; gap: 26px; }
.fx-flow-stat b { font-family: 'Fira Code', monospace; font-size: 1.4rem; display: block; }
.fx-flow-stat label { font-size: 0.65rem; opacity: 0.5; text-transform: uppercase; letter-spacing: 0.08em; }
.fx-flow-stat--warn b { color: #ffb74d; }
.fx-feed-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.fx-feed-frames { display: flex; gap: 6px; }
.fx-fchip { font-family: 'Fira Code', monospace; font-size: 0.68rem; padding: 3px 10px; border-radius: 6px; border: 1px solid rgba(var(--nc-primary-rgb), 0.2); background: transparent; color: rgba(230, 249, 255, 0.7); cursor: pointer; }
.fx-fchip--on { background: rgba(var(--nc-primary-rgb), 0.16); color: rgba(var(--nc-primary-rgb), 1); }
.fx-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.fx-table th { text-align: left; font-weight: 600; opacity: 0.45; font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.08em; padding: 4px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
.fx-table td { padding: 5px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
.fx-mono { font-family: 'Fira Code', monospace; }
.fx-row--refund { opacity: 0.6; }
.fx-pill { font-size: 0.6rem; padding: 2px 7px; border-radius: 10px; text-transform: uppercase; letter-spacing: 0.06em; }
.fx-pill--ok { color: #00e676; border: 1px solid rgba(0, 230, 118, 0.35); }
.fx-pill--refund { color: #ffb74d; border: 1px solid rgba(255, 183, 77, 0.35); }
.fx-pill--dead { color: #ff5252; border: 1px solid rgba(255, 82, 82, 0.4); }
.fx-expand { background: transparent; border: none; color: rgba(var(--nc-primary-rgb), 0.7); cursor: pointer; }
.fx-row-detail td { background: rgba(0, 0, 0, 0.3); }
.fx-quote-form { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 10px; }
.fx-quote-form label { display: flex; flex-direction: column; gap: 4px; font-size: 0.7rem; opacity: 0.7; flex: 1; min-width: 180px; }
.fx-quote-form input { background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(var(--nc-primary-rgb), 0.2); border-radius: 6px; padding: 7px 10px; color: #e6f9ff; font-family: 'Fira Code', monospace; font-size: 0.8rem; }
.fx-qbtn { padding: 8px 18px; border-radius: 6px; border: 1px solid rgba(var(--nc-primary-rgb), 0.5); background: rgba(var(--nc-primary-rgb), 0.14); color: rgba(var(--nc-primary-rgb), 1); font-weight: 700; cursor: pointer; font-family: 'Fira Code', monospace; }
.fx-quote-out { display: flex; gap: 18px; flex-wrap: wrap; font-size: 0.8rem; font-family: 'Fira Code', monospace; align-items: baseline; }
.fx-quote-out b { color: #e6f9ff; }
.fx-quote-net b { color: var(--nc-primary, #00d2d2); }
.fx-updated { font-family: 'Fira Code', monospace; font-size: 0.66rem; opacity: 0.5; align-self: center; white-space: nowrap; }
.fx-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.fx-expand { display: inline-block; transition: transform 0.15s ease, color 0.15s ease; }
.fx-expand--open { transform: rotate(90deg); color: rgba(var(--nc-primary-rgb), 1); }
.fx-fchip { transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease; }
.fx-flow { flex-wrap: wrap; row-gap: 14px; }
/* hover + keyboard-focus affordances (a11y + delight) */
.fx-chip--btn:hover:not(:disabled), .fx-fchip:hover, .fx-qbtn:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb), 0.6); background: rgba(var(--nc-primary-rgb), 0.12); }
.fx-expand:hover { color: rgba(var(--nc-primary-rgb), 1); }
.fx-desk button:focus-visible,
.fx-quote-form input:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: 2px; }
.fx-chip--btn:disabled, .fx-qbtn:disabled { opacity: 0.45; cursor: not-allowed; }

/* Route Operations / residue sweep */
.fx-ok { color: #00e676; }
.fx-off { color: rgba(230, 249, 255, 0.5); }
.fx-routeops-grid { display: flex; gap: 22px; flex-wrap: wrap; margin-bottom: 10px; }
.fx-routeops-grid .fx-kv { border-bottom: none; padding: 2px 0; gap: 8px; }
.fx-sweep-form { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
.fx-sweep-form > label { display: flex; flex-direction: column; gap: 4px; font-size: 0.7rem; opacity: 0.7; flex: 1; min-width: 200px; }
.fx-inwrap { position: relative; display: block; }
.fx-sweep-form input { width: 100%; box-sizing: border-box; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(var(--nc-primary-rgb), 0.2); border-radius: 6px; padding: 7px 10px; color: #e6f9ff; font-family: 'Fira Code', monospace; font-size: 0.8rem; }
.fx-max { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); font-size: 0.6rem; padding: 2px 7px; border-radius: 5px; border: 1px solid rgba(var(--nc-primary-rgb), 0.4); background: rgba(var(--nc-primary-rgb), 0.12); color: rgba(var(--nc-primary-rgb), 1); cursor: pointer; font-family: 'Fira Code', monospace; }
.fx-sweep-confirm { margin-top: 10px; padding: 10px 12px; border: 1px solid rgba(255, 183, 77, 0.45); border-radius: 8px; background: rgba(255, 183, 77, 0.07); font-size: 0.8rem; display: flex; flex-direction: column; gap: 8px; }
.fx-sweep-actions { display: flex; gap: 10px; align-items: center; }

/* ── Polish pass (2026-06-07) — cohesion with the public Forex Desk + delight ── */
.fx-card { transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease; }
.fx-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.28); box-shadow: 0 12px 32px -20px rgba(var(--nc-primary-rgb), 0.5); }
/* section headers get a left accent bar — matches the desk's card rhythm */
.fx-card h2 { position: relative; padding-left: 11px; }
.fx-card h2::before { content: ''; position: absolute; left: 0; top: 3px; bottom: 3px; width: 3px; border-radius: 2px; background: rgba(var(--nc-primary-rgb), 0.55); }
/* the headline rate gets a soft glow + thin top hairline on its strip */
.fx-rate-val { text-shadow: 0 0 18px rgba(var(--nc-primary-rgb), 0.4); }
.fx-rate { position: relative; }
.fx-rate::before { content: ''; position: absolute; left: 16px; right: 16px; top: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.4), transparent); }
/* live feed + integrity rows brighten on hover; numbers align */
.fx-table tbody tr { transition: background 0.14s ease; }
.fx-table tbody tr:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
.fx-leg-amt, .fx-quote-out b, .fx-pool-stats b { font-variant-numeric: tabular-nums; }
.fx-pill { transition: all 0.15s ease; }
@media (prefers-reduced-motion: reduce) { .fx-card { transition: none; } }

/* §2026-06-07 premium-glass restyle — flat boxes → layered glass (Commander) */
.fx-card {
  background:
    linear-gradient(165deg, rgba(255,255,255,0.05), rgba(255,255,255,0.01) 45%, rgba(255,255,255,0) 72%),
    rgba(13, 19, 32, 0.6);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 14px;
  backdrop-filter: blur(16px) saturate(1.08);
  -webkit-backdrop-filter: blur(16px) saturate(1.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 16px 38px -28px rgba(0,0,0,0.9);
}
.fx-rate {
  background:
    linear-gradient(165deg, rgba(255,255,255,0.05), rgba(255,255,255,0) 60%),
    rgba(13, 19, 32, 0.64);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.16);
  border-radius: 14px;
  backdrop-filter: blur(16px) saturate(1.08);
  -webkit-backdrop-filter: blur(16px) saturate(1.08);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 18px 40px -28px rgba(0,0,0,0.9);
}

@media (max-width: 640px) {
  .fx-pool-legs { flex-direction: column; gap: 10px; }
  .fx-rate-val { font-size: 1.5rem; }
  .fx-rate-meta { gap: 10px; }
  .fx-flow { gap: 18px; }
  .fx-quote-out { gap: 10px; }
  .fx-head-title { gap: 8px; }
  .fx-head, .fx-head-chips { gap: 8px; }
}

/* ── §FEPARITY-R3: keepers + parked routes ─────────────────────────────── */
.fx-warn { color: #ffb74d; }
.fx-chip--on { background: rgba(0, 229, 255, 0.16); border-color: rgba(0, 229, 255, 0.5); }
.fx-keeper-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
.fx-keeper { border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 12px 14px; }
.fx-keeper-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
.fx-keeper-note { font-size: 0.7rem; line-height: 1.5; margin: 0 0 10px; }
.fx-keeper-actions { display: flex; align-items: flex-end; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.fx-keeper-field { display: flex; flex-direction: column; gap: 3px; font-size: 0.66rem; opacity: 0.75; }
.fx-keeper-field input { background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 4px; color: inherit; padding: 5px 8px; font-family: 'Fira Code', monospace; font-size: 0.72rem; width: 170px; }
.fx-keeper-by { font-size: 0.64rem; margin-top: 8px; opacity: 0.6; }
.fx-dl-list { display: flex; flex-direction: column; gap: 4px; max-height: 22rem; overflow-y: auto; margin-top: 10px; }
.fx-dl-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 6px 8px; border: 1px solid rgba(255, 255, 255, 0.07); border-left-width: 3px; border-left-color: rgba(0, 229, 255, 0.5); border-radius: 5px; font-size: 0.72rem; }
.fx-dl-row--remote { border-left-color: #ffb74d; }
.fx-dl-amt { font-weight: 700; }
.fx-dl-route { opacity: 0.75; }
.fx-dl-phase { font-size: 0.6rem; }
.fx-dl-meta { font-size: 0.66rem; }
.fx-dl-err { font-size: 0.64rem; opacity: 0.7; flex: 1; min-width: 0; }
</style>
