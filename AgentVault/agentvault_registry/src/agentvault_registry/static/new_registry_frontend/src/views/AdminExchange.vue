<template>
  <div class="adx">
    <!-- ── HERO ─────────────────────────────────────────────────────── -->
    <header class="adx-hero">
      <div>
        <div class="adx-eyebrow"><Icon name="mdi:scale-balance" /> AGORA · MARKET COMMAND</div>
        <h1>AGORA Administration</h1>
        <p class="adx-sub">Listings lifecycle, conservation invariants, compliance registry and the market kill switch, every money leg escrow-settled, Δ=0 by construction.</p>
      </div>
      <div class="adx-hero-r">
        <div class="adx-chips">
          <!-- §FESUITE (2026-10-05): before the overview answered, and over a failed read, these said MARKET DARK and
               PASSPORT OFF: states the page never read. They say a dash until it answers. -->
          <span class="adx-chip" :class="!ov ? 'dim' : ov.venue_enabled ? 'on' : 'off'" data-testid="adx-market-chip">
            <i></i>{{ !ov ? 'MARKET —' : ov.venue_enabled ? 'MARKET LIVE' : 'MARKET DARK' }}
          </span>
          <span class="adx-chip" :class="ov?.passport_enabled ? 'on' : 'dim'">
            <Icon name="mdi:shield-check" />PASSPORT {{ !ov ? '—' : ov.passport_enabled ? 'ON' : 'OFF' }}
          </span>
          <span class="adx-chip accent" v-if="ov?.currency">{{ ov.currency }}</span>
        </div>
        <button
          class="adx-halt" :class="{ halted: ov?.global_halt }"
          :disabled="!ov" @click="askGlobalHalt"
        >
          <Icon name="mdi:alert" />
          {{ ov?.global_halt ? 'MARKET HALTED · RESUME' : 'GLOBAL HALT' }}
        </button>
      </div>
    </header>

    <ReadFailedNotice v-if="!ov && ovRead === 'unread'" dense text="The market's overview could not be read just now." :retry="refreshAll" data-testid="adx-overview-failed" />

    <div v-if="ov && !ov.venue_enabled" class="adx-darkbar">
      <Icon name="mdi:information" /> The market ships dark on this registry (<code>EXCHANGE_ENABLED</code> unset). Reads work; order/settlement paths are gated off.
    </div>

    <!-- ── STAT STRIP ───────────────────────────────────────────────── -->
    <section class="stat-grid" v-if="ov">
      <div class="stat-tile">
        <span class="stat-label">ESCROW BALANCE</span>
        <span class="stat-num tick" :key="'esc' + (ov.escrow_balance ?? '')">{{ fmtBig(ov.escrow_balance) }} <i class="stat-ccy">{{ ov.currency }}</i></span>
        <span class="stat-sub">teg:system:exchange_escrow — all in-flight money</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">TRADES · 24H</span>
        <span class="stat-num tick" :key="'t24' + ov.trades_24h">{{ ov.trades_24h.toLocaleString(appLocale()) }}</span>
        <span class="stat-sub">{{ fmtBig(ov.notional_24h) }} {{ ov.currency }} notional · {{ ov.trades_total.toLocaleString(appLocale()) }} lifetime</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">OPEN ORDERS</span>
        <span class="stat-num tick" :key="'oo' + openOrders">{{ openOrders.toLocaleString(appLocale()) }}</span>
        <span class="stat-sub">{{ orderSub }}</span>
      </div>
      <div class="stat-tile">
        <span class="stat-label">PARTICIPANTS</span>
        <span class="stat-num">{{ participantTotal }}</span>
        <span class="stat-sub">{{ participantSub }}</span>
      </div>
      <div class="stat-tile" :class="{ 'stat--warn': ov.settlement.oldest_lag_seconds > 60 }">
        <span class="stat-label">SETTLEMENT</span>
        <span class="stat-num">{{ ov.settlement.pending }}</span>
        <span class="stat-sub">{{ ov.settlement.pending ? `oldest ${Math.round(ov.settlement.oldest_lag_seconds)}s ago` : 'drained, lag 0s' }}<template v-if="ov.dividends_unpaid"> · {{ ov.dividends_unpaid }} distribution(s) settling</template></span>
      </div>
    </section>

    <div class="adx-grid">
      <!-- ── CONSERVATION ───────────────────────────────────────────── -->
      <div class="adx-card adx-span2">
        <div class="adx-card-head">
          <Icon name="mdi:shield-check" /> CONSERVATION INVARIANTS
          <span class="adx-head-note" v-if="inv">checked {{ timeOnly(inv.checked_at) }}</span>
          <button class="adx-btn sm" :disabled="invBusy" @click="runInvariant">
            <Icon name="mdi:refresh" /> {{ invBusy ? 'checking…' : 'RUN CHECK' }}
          </button>
        </div>

        <div v-if="inv" class="adx-inv">
          <div class="adx-verdict" :class="inv.ok ? 'ok' : 'breach'">
            <Icon :name="inv.ok ? 'mdi:check-circle' : 'mdi:alert-circle'" />
            <span>{{ inv.ok ? 'ALL INVARIANTS HOLD' : 'INVARIANT BREACH — investigate before any admin action' }}</span>
          </div>

          <div class="adx-inv-row" v-if="inv['I-X3_escrow']">
            <span class="adx-inv-name">I-X3 · ESCROW SOLVENCY</span>
            <template v-if="!inv['I-X3_escrow'].error">
              <span>expected <b>{{ fmtBig(inv['I-X3_escrow'].expected) }}</b></span>
              <span>actual <b>{{ fmtBig(inv['I-X3_escrow'].actual) }}</b></span>
              <span>Δ <b :class="inv['I-X3_escrow'].ok ? 'up' : 'down'">{{ fmtDelta(inv['I-X3_escrow'].delta) }}</b></span>
              <span class="adx-pill" :class="inv['I-X3_escrow'].ok ? 'ok' : 'breach'">{{ inv['I-X3_escrow'].ok ? 'EXACT' : 'BREACH' }}</span>
            </template>
            <span v-else class="down">TEG read failed: {{ inv['I-X3_escrow'].error }}</span>
          </div>

          <div class="adx-inv-row" v-if="inv['I-X4_settlement_liveness']">
            <span class="adx-inv-name">I-X4 · SETTLEMENT LIVENESS</span>
            <span>stuck over SLO <b>{{ inv['I-X4_settlement_liveness'].stuck_over_slo }}</b></span>
            <span class="adx-pill" :class="inv['I-X4_settlement_liveness'].ok ? 'ok' : 'breach'">{{ inv['I-X4_settlement_liveness'].ok ? 'LIVE' : 'STALLED' }}</span>
            <span class="adx-inv-note" v-if="inv.funding_orders_in_transition">{{ inv.funding_orders_in_transition }} order(s) mid-funding — the one legitimate transient I-X3 window</span>
          </div>

          <table class="adx-table" v-if="inv.listings.length">
            <thead><tr><th>LISTING</th><th>I-X1 POINTS</th><th>POSITIONS Σ / EXPECTED</th><th>I-X2 LOCKS</th><th>LOCKED Σ / RESTING SELLS</th></tr></thead>
            <tbody>
              <tr v-for="l in inv.listings" :key="l.symbol">
                <td class="adx-sym">${{ l.symbol }}</td>
                <td><span class="adx-pill" :class="l['I-X1_share_conservation'] ? 'ok' : 'breach'">{{ l['I-X1_share_conservation'] ? 'CONSERVED' : 'BREACH' }}</span></td>
                <td class="mono">{{ l.positions_sum.toLocaleString(appLocale()) }} / {{ l.expected.toLocaleString(appLocale()) }}</td>
                <td><span class="adx-pill" :class="l['I-X2_lock_honesty'] ? 'ok' : 'breach'">{{ l['I-X2_lock_honesty'] ? 'HONEST' : 'BREACH' }}</span></td>
                <td class="mono">{{ l.locked_sum.toLocaleString(appLocale()) }} / {{ l.open_sell_remaining.toLocaleString(appLocale()) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="adx-empty"><Icon name="mdi:timer-sand" /><span>{{ invBusy ? 'running the conservation pass…' : adxRead === 'reading' ? 'Loading…' : 'no check run yet' }}</span></div>
      </div>

      <!-- ── LISTINGS LIFECYCLE ─────────────────────────────────────── -->
      <div class="adx-card adx-span2">
        <div class="adx-card-head">
          <Icon name="mdi:chart-candlestick" /> LISTINGS
          <span class="adx-head-note">{{ listingsRead === 'read' ? listings.length : '—' }} on the books</span>
        </div>
        <table class="adx-table" v-if="listings.length">
          <thead><tr><th>TICKER</th><th>ORG</th><th>STATUS</th><th>LAST</th><th>LAUNCH</th><th>ALLOCATION / TOTAL</th><th class="adx-ta-r">ACTIONS</th></tr></thead>
          <tbody>
            <tr v-for="l in listings" :key="l.id">
              <td class="adx-sym">${{ l.symbol }}</td>
              <td class="adx-name">{{ l.display_name }}</td>
              <td><span class="adx-pill" :class="'st-' + l.status">{{ l.status.toUpperCase() }}</span><span v-if="!l.approved" class="adx-pill pending">UNAPPROVED</span><span v-if="l.cb_pct" class="adx-pill" style="background:rgba(245,158,11,.12);color:#f59e0b" :title="'circuit-breaker armed — auto-halts on a ' + (l.cb_pct/100) + '% move'">CB {{ (l.cb_pct / 100).toFixed(0) }}%</span></td>
              <td class="mono">{{ fmtPx(l.stats?.last) }} <span class="adx-chg" :class="chgClass(l.stats?.change_24h_pct)">{{ chgFmt(l.stats?.change_24h_pct) }}</span></td>
              <td class="mono">{{ l.ipo_sold.toLocaleString(appLocale()) }} / {{ l.ipo_float.toLocaleString(appLocale()) }}</td>
              <td class="mono">{{ l.ipo_float.toLocaleString(appLocale()) }} / {{ l.total_shares.toLocaleString(appLocale()) }}</td>
              <td class="adx-actions">
                <button v-if="!l.approved" class="adx-btn sm ok" :disabled="acting" @click="doApprove(l)"><Icon name="mdi:check" /> APPROVE</button>
                <button v-if="l.status === 'trading'" class="adx-btn sm warn" :disabled="acting" @click="doHalt(l, true)"><Icon name="mdi:pause" /> HALT</button>
                <button v-if="l.status === 'halted'" class="adx-btn sm ok" :disabled="acting" @click="doHalt(l, false)"><Icon name="mdi:lightning-bolt" /> RESUME</button>
                <button v-if="l.status !== 'delisted'" class="adx-btn sm" :disabled="acting" @click="setCb(l)" title="Set the volatility circuit-breaker threshold (auto-halts on a large move)"><Icon name="mdi:shield-alert" /> BREAKER</button>
                <button v-if="l.status !== 'delisted'" class="adx-btn sm danger" :disabled="acting" @click="askDelist(l)"><Icon name="mdi:close-circle" /> DELIST</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else class="adx-empty"><Icon name="mdi:telescope" /><span>{{ listingsRead === 'read' ? 'no listings yet — org owners list via POST /api/v1/agora/listings' : listingsRead === 'unread' ? 'the listings could not be read just now' : 'Loading…' }}</span></div>

        <!-- REGAUTH — an approval parked by the jurisdiction declaration. The
             checklist names the act, the authority and the fix (E1b pattern). -->
        <div v-if="regParked" class="adx-reg-park" data-tour="adx-reg-park" data-testid="reg-park-checklist">
          <p class="adx-reg-park-title">
            <Icon name="mdi:scale-balance" :size="14" />
            {{ t('adminExchange.regParkTitle', 'Approving ${symbol} is parked until these are resolved:').replace('{symbol}', regParked.symbol) }}
          </p>
          <ul class="adx-reg-park-list">
            <li v-for="(b, i) in regParked.blockers" :key="i">
              <span class="adx-reg-park-line">
                <code>{{ b.action }}</code>
                {{ ' ' + t('adminExchange.regParkNeeds', 'needs an authorization from') + ' ' }}
                <strong>{{ b.authority }}</strong>
                <!-- Vue condenses inter-element whitespace: keep the spaces INSIDE the bindings -->
                <template v-if="b.subject_ref">{{ ' ' + t('adminExchange.regParkFor', 'for') + ' ' }}<code>{{ b.subject_ref }}</code></template>
              </span>
              <span class="adx-reg-park-how">{{ b.how }}</span>
            </li>
          </ul>
          <div class="adx-reg-park-actions">
            <button class="adx-btn sm ok" @click="router.push('/admin/jurisdiction')" data-testid="reg-park-open-panel">
              <Icon name="mdi:scale-balance" /> {{ t('adminExchange.regParkOpen', 'Open the Jurisdiction panel') }}
            </button>
            <button class="adx-btn sm" @click="regParked = null">{{ t('adminExchange.regParkDismiss', 'Dismiss') }}</button>
          </div>
        </div>
      </div>

      <!-- (Demand Director moved to the AGORA Sim panel — /ui#/eigentrust · §2026-06-18) -->

      <!-- ── COMPLIANCE REGISTRY ────────────────────────────────────── -->
      <div class="adx-card adx-span2">
        <div class="adx-card-head">
          <Icon name="mdi:account-group" /> COMPLIANCE REGISTRY
          <span class="adx-head-note">D25 — no anonymous ghosts: every trading DID carries owner identity</span>
        </div>
        <table class="adx-table" v-if="parts.length">
          <thead><tr><th>AGENT DID</th><th>HOME</th><th>OWNER</th><th>CONTACT</th><th>VERIFICATION</th><th>STATUS</th><th>FIRST SEEN</th></tr></thead>
          <tbody>
            <tr v-for="p in parts" :key="p.agent_did">
              <td class="mono adx-did" :title="p.agent_did">{{ shortDid(p.agent_did) }}</td>
              <td class="mono">{{ p.home_registry }}</td>
              <td>{{ p.owner_dev_name || '—' }}</td>
              <td class="mono dim">{{ p.owner_dev_contact || '—' }}</td>
              <td><span class="adx-pill" :class="p.verification_source === 'dev_card' ? 'passport' : 'local'"><Icon :name="p.verification_source === 'dev_card' ? 'mdi:shield-check' : 'mdi:fingerprint'" />{{ p.verification_source === 'dev_card' ? 'DEVCARD' : 'LOCAL' }}</span></td>
              <td><span class="adx-pill" :class="p.compliance_status === 'verified' ? 'ok' : p.compliance_status === 'blocked' ? 'breach' : 'pending'">{{ p.compliance_status.toUpperCase() }}</span></td>
              <td class="mono dim">{{ dateOnly(p.first_seen) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="adx-empty"><Icon name="mdi:inbox" /><span>{{ partsRead === 'read' ? 'no participants yet, the registry fills on first order / launch buy' : partsRead === 'unread' ? 'the participants could not be read just now' : 'Loading…' }}</span></div>
      </div>
    </div>

    <ConfirmActionModal
      :show="confirm.show"
      :title="confirm.title"
      :message="confirm.message"
      tone="danger"
      :required-match="confirm.match"
      :confirm-text="confirm.cta"
      :busy="acting"
      @confirm="confirm.run"
      @close="confirm.show = false"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * AGORA Exchange Administration (§V0064, 2026-06-13) — the venue command view
 * the Commander drives sims + fleet decisions from. Design_Language house
 * style; admin endpoints (admin_federation flag) via exchangeAdminService.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { exchangeAdminService, type ExchangeOverview, type InvariantReport, type Participant } from '@/services/api/exchangeAdminService'
import { exchangeService, type Listing } from '@/services/api/exchangeService'
import { parseBlockers } from '@/services/api/jurisdictionAdmin'
import { useI18n } from '@/composables/useI18n'
import { useAlive } from '@/composables/useAlive'
import { useUIStore } from '@/stores/ui'

const uiStore = useUIStore()
const router = useRouter()
const { t } = useI18n()
// REGAUTH — the last approval that parked on a missing regulatory authorization.
const regParked = ref<{ symbol: string; blockers: any[] } | null>(null)

const ov = ref<ExchangeOverview | null>(null)
const inv = ref<InvariantReport | null>(null)
const listings = ref<Listing[]>([])
const parts = ref<Participant[]>([])
const invBusy = ref(false)
const acting = ref(false)
const confirm = reactive({ show: false, title: '', message: '', match: '', cta: 'Execute', run: () => {} })
let timer: number | undefined

/* Demand Director moved to EigenTrustCommand.vue (the sim panel) §2026-06-18 */

const openOrders = computed(() => {
  const by = ov.value?.orders_by_status ?? {}
  return (by['open'] || 0) + (by['partial'] || 0) + (by['funding'] || 0)
})
const orderSub = computed(() => {
  const by = ov.value?.orders_by_status ?? {}
  const bits = Object.entries(by).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}`)
  return bits.length ? bits.join(' · ') : 'book is clear'
})
const participantTotal = computed(() =>
  Object.values(ov.value?.participants_by_source ?? {}).reduce((a, b) => a + b, 0))
const participantSub = computed(() => {
  const by = ov.value?.participants_by_source ?? {}
  const local = by['local'] || 0
  const card = by['dev_card'] || 0
  return `${local} local · ${card} via DevCard passport`
})

function fmtPx(p?: string | null): string {
  const v = parseFloat(p || '')
  if (!isFinite(v)) return '—'
  return v >= 1 ? v.toFixed(2) : v.toPrecision(3)
}
function fmtBig(s?: string | null): string {
  const v = parseFloat(s || '')
  if (!isFinite(v)) return '—'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M'
  return v.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
}
function fmtDelta(s?: string): string {
  const v = parseFloat(s || '')
  if (!isFinite(v)) return '—'
  return v === 0 ? '0 (exact)' : v.toFixed(18).replace(/0+$/, '')
}
function chgClass(c?: string | null) { const v = parseFloat(c || '0'); return v > 0 ? 'up' : v < 0 ? 'down' : 'dim' }
function chgFmt(c?: string | null) { if (c == null) return ''; const v = parseFloat(c); return `${v > 0 ? '▲' : v < 0 ? '▼' : ''}${Math.abs(v).toFixed(1)}%` }
function shortDid(d: string): string { return d.length > 30 ? d.slice(0, 18) + '…' + d.slice(-6) : d }
function timeOnly(iso: string): string { return new Date(iso).toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }
function dateOnly(iso?: string | null): string { return iso ? new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' }) : '—' }

// §FESUITE (the loading sweep): a table says "none yet" only after its own read came back; a failed read says so and a
// failed refresh keeps what was shown (could not read is not none)
const adxRead = ref<'reading' | 'read'>('reading')
const ovRead = ref<'reading' | 'read' | 'unread'>('reading')
const listingsRead = ref<'reading' | 'read' | 'unread'>('reading')
const partsRead = ref<'reading' | 'read' | 'unread'>('reading')
async function refreshAll() {
  try { ov.value = await exchangeAdminService.overview(); ovRead.value = 'read' } catch { if (ovRead.value !== 'read') ovRead.value = 'unread' }
  try { listings.value = (await exchangeService.listings()).listings; listingsRead.value = 'read' } catch { if (listingsRead.value !== 'read') listingsRead.value = 'unread' }
  try { parts.value = (await exchangeAdminService.participants()).participants; partsRead.value = 'read' } catch { if (partsRead.value !== 'read') partsRead.value = 'unread' }
  adxRead.value = 'read'
}

async function runInvariant() {
  invBusy.value = true
  try {
    inv.value = await exchangeAdminService.invariant()
    if (!inv.value.ok) uiStore.showError('Invariant breach detected', 'Inspect I-X rows before any admin action')
  } catch (e: any) {
    uiStore.showError('Invariant check failed', e?.response?.data?.detail || e?.message)
  } finally {
    invBusy.value = false
  }
}

function askGlobalHalt() {
  if (!ov.value) return
  const halting = !ov.value.global_halt
  confirm.title = halting ? 'HALT THE ENTIRE MARKET' : 'Resume the market'
  confirm.message = halting
    ? 'Every order on every listing will be <b>rejected</b> until resume. Escrowed funds stay safe. Type <b>HALT</b> to confirm.'
    : 'Trading resumes on all non-halted listings. Type <b>RESUME</b> to confirm.'
  confirm.match = halting ? 'HALT' : 'RESUME'
  confirm.cta = halting ? 'Halt market' : 'Resume market'
  confirm.run = async () => {
    acting.value = true
    try {
      await exchangeAdminService.globalHalt(halting)
      uiStore.showSuccess(halting ? 'Market halted' : 'Market resumed')
      confirm.show = false
      await refreshAll()
    } catch (e: any) {
      uiStore.showError('Action failed', e?.response?.data?.detail || e?.message)
    } finally { acting.value = false }
  }
  confirm.show = true
}

async function doApprove(l: Listing) {
  acting.value = true
  try {
    await exchangeAdminService.approve(l.symbol)
    uiStore.showSuccess(`$${l.symbol} approved: retained points to org treasury, launch opens`)
    regParked.value = null
    await refreshAll()
  } catch (e: any) {
    // REGAUTH (SPEC 2026-08-15): a declared-regulated approval parks with 409 +
    // a blockers checklist (stringified RFC7807 detail — parseBlockers handles it).
    // Render the checklist instead of a dead-end toast.
    const blockers = parseBlockers(e).filter((b: any) => b?.kind === 'regulatory_authorization_required')
    if (blockers.length) {
      regParked.value = { symbol: l.symbol, blockers }
      uiStore.showError('Approval parked', `$${l.symbol} needs a recorded regulatory authorization first: see the checklist below the listings table`)
    } else {
      uiStore.showError('Approve failed', e?.response?.data?.detail || e?.message)
    }
  } finally { acting.value = false }
}

async function doHalt(l: Listing, halted: boolean) {
  acting.value = true
  try {
    await exchangeAdminService.halt(l.symbol, halted)
    uiStore.showSuccess(`$${l.symbol} ${halted ? 'halted' : 'resumed'}`)
    await refreshAll()
  } catch (e: any) {
    uiStore.showError('Action failed', e?.response?.data?.detail || e?.message)
  } finally { acting.value = false }
}

async function setCb(l: Listing) {
  const cur = l.cb_pct ? (l.cb_pct / 100).toString() : '0'
  const ans = window.prompt(`Circuit-breaker threshold for $${l.symbol}\nPercent move (from a rolling reference) that auto-halts the listing. 0 = off. Recommended 15–20.`, cur)
  if (ans === null) return
  const pct = parseFloat(ans)
  if (isNaN(pct) || pct < 0 || pct > 100) { uiStore.showError('Invalid threshold', 'enter a percent between 0 and 100'); return }
  acting.value = true
  try {
    await exchangeAdminService.setCircuitBreaker(l.symbol, Math.round(pct * 100))
    uiStore.showSuccess(`$${l.symbol} circuit-breaker ${pct > 0 ? 'armed at ' + pct + '%' : 'disabled'}`)
    await refreshAll()
  } catch (e: any) {
    uiStore.showError('Action failed', e?.response?.data?.detail || e?.message)
  } finally { acting.value = false }
}

function askDelist(l: Listing) {
  confirm.title = `Delist $${l.symbol}`
  confirm.message = `Cancels <b>every resting order</b>, refunds buy escrow, unlocks points, and ends trading permanently. Positions remain on the ledger. Type the ticker to confirm.`
  confirm.match = l.symbol
  confirm.cta = 'Delist permanently'
  confirm.run = async () => {
    acting.value = true
    try {
      await exchangeAdminService.delist(l.symbol)
      uiStore.showSuccess(`$${l.symbol} delisted — refunds drain via settlement`)
      confirm.show = false
      await refreshAll()
    } catch (e: any) {
      uiStore.showError('Delist failed', e?.response?.data?.detail || e?.message)
    } finally { acting.value = false }
  }
  confirm.show = true
}

// §FESUITE (the leave sweep): a page left during its first read starts no poll when it lands
const alive = useAlive()
onMounted(async () => {
  await refreshAll()
  if (!alive()) return
  void runInvariant()
  timer = window.setInterval(refreshAll, 30000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
/* Design_Language house style (§1 tokens, §2 card, §3 stat tiles). */
.adx {
  --cyan: var(--nc-primary);
  --cyan-rgb: var(--nc-primary-rgb);
  position: relative; z-index: 1; min-height: 100%;
  padding: 18px 22px 40px; color: rgba(255, 255, 255, 0.88);
}
.up { color: #10b981; } .down { color: #ef4444; } .dim { opacity: 0.55; }
.mono { font-family: ui-monospace, monospace; font-variant-numeric: tabular-nums; }
.tick { display: inline-block; animation: adx-tick 0.45s ease-out; }
@keyframes adx-tick { 0% { transform: scale(1.05); } 100% { transform: scale(1); } }

/* hero */
.adx-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap; margin-bottom: 14px; }
.adx-eyebrow { display: inline-flex; align-items: center; gap: 7px; font-size: 10px; letter-spacing: 0.18em; color: rgba(var(--cyan-rgb), 0.8); font-family: ui-monospace, monospace; }
.adx-eyebrow :deep(svg) { width: 13px; height: 13px; }
.adx-hero h1 { font-size: 28px; font-weight: 800; margin: 3px 0 4px; }
.adx-sub { font-size: 12px; opacity: 0.6; max-width: 640px; }
.adx-hero-r { display: flex; flex-direction: column; align-items: flex-end; gap: 9px; }
.adx-chips { display: flex; gap: 7px; flex-wrap: wrap; }
.adx-chip { display: inline-flex; align-items: center; gap: 6px; font-size: 9px; letter-spacing: 0.14em; font-family: ui-monospace, monospace; padding: 4px 11px; border-radius: 99px; border: 1px solid rgba(255, 255, 255, 0.2); opacity: 0.85; }
.adx-chip :deep(svg) { width: 11px; height: 11px; }
.adx-chip i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.adx-chip.on { color: #10b981; border-color: rgba(16, 185, 129, 0.5); }
.adx-chip.on i { animation: adx-pulse 1.9s infinite; }
.adx-chip.off { color: #f59e0b; border-color: rgba(245, 158, 11, 0.5); }
.adx-chip.accent { color: rgba(var(--cyan-rgb), 1); border-color: rgba(var(--cyan-rgb), 0.45); font-weight: 800; }
@keyframes adx-pulse { 50% { opacity: 0.45; } }
.adx-halt {
  display: inline-flex; align-items: center; gap: 8px; cursor: pointer; min-height: 44px;
  font-family: ui-monospace, monospace; font-size: 12px; font-weight: 800; letter-spacing: 0.1em;
  color: #ef4444; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.5);
  border-radius: 10px; padding: 10px 18px; transition: all 0.15s;
}
.adx-halt:hover:not(:disabled) { background: rgba(239, 68, 68, 0.22); box-shadow: 0 0 18px rgba(239, 68, 68, 0.3); }
.adx-halt.halted { color: #10b981; background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.5); animation: adx-pulse 1.6s infinite; }
.adx-halt :deep(svg) { width: 15px; height: 15px; }
.adx-halt:disabled { opacity: 0.35; cursor: not-allowed; }
.adx-darkbar { display: flex; gap: 8px; align-items: center; color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.07); padding: 9px 13px; border-radius: 9px; font-size: 12px; margin-bottom: 13px; }
.adx-darkbar :deep(svg) { width: 15px; height: 15px; flex: none; }
.adx-darkbar code { font-size: 11px; opacity: 0.85; }

/* stat strip */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 14px; }
.stat-tile {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.035);
  border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 10px; backdrop-filter: blur(9px);
  padding: 11px 14px; display: flex; flex-direction: column; gap: 2px;
}
.stat-tile.stat--warn { border-color: rgba(245, 158, 11, 0.45); background: rgba(245, 158, 11, 0.04); }
.stat-label { font-size: 9px; letter-spacing: 0.16em; opacity: 0.55; font-family: ui-monospace, monospace; }
.stat-num { font-size: 22px; font-weight: 800; font-variant-numeric: tabular-nums; text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.32); }
.stat-ccy { font-style: normal; font-size: 11px; font-weight: 600; opacity: 0.5; }
.stat-sub { font-size: 10px; opacity: 0.45; font-family: ui-monospace, monospace; }

/* grid + cards */
.adx-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; }
.adx-span2 { grid-column: 1 / -1; }
/* minmax(0, 1fr): a 1fr column grew to the widest table (the conservation invariants, ~700 px) and every card ran past
   a phone's edge; on a phone a wide table scrolls inside its card (the camera, 2026-10-13) */
@media (max-width: 899.98px) { .adx-grid { grid-template-columns: minmax(0, 1fr); } }
.adx-card {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.035);
  border: 1px solid rgba(var(--cyan-rgb), 0.18); border-radius: 12px; backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
  padding: 13px 15px;
}
.adx-card:hover { border-color: rgba(var(--cyan-rgb), 0.3); }
.adx-card-head { display: flex; align-items: center; gap: 8px; font-size: 10px; letter-spacing: 0.16em; color: rgba(var(--cyan-rgb), 0.85); font-family: ui-monospace, monospace; margin-bottom: 11px; }
.adx-card-head :deep(svg) { width: 13px; height: 13px; }
.adx-head-note { font-size: 9px; letter-spacing: 0.06em; opacity: 0.45; }
.adx-card-head .adx-btn { margin-left: auto; }
.adx-empty { display: flex; flex-direction: column; align-items: center; gap: 7px; font-size: 11px; opacity: 0.45; padding: 22px 8px; font-family: ui-monospace, monospace; }
.adx-empty :deep(svg) { width: 22px; height: 22px; }

/* invariants */
.adx-verdict { display: flex; align-items: center; gap: 9px; font-weight: 800; font-size: 13px; letter-spacing: 0.06em; padding: 10px 13px; border-radius: 9px; margin-bottom: 10px; font-family: ui-monospace, monospace; }
.adx-verdict.ok { color: #10b981; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.35); }
.adx-verdict.breach { color: #ef4444; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.45); animation: adx-pulse 1.4s infinite; }
.adx-verdict :deep(svg) { width: 17px; height: 17px; }
.adx-inv-row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; font-size: 11px; font-family: ui-monospace, monospace; padding: 7px 4px; border-bottom: 1px dashed rgba(var(--cyan-rgb), 0.12); }
.adx-inv-name { color: rgba(var(--cyan-rgb), 0.9); font-weight: 700; letter-spacing: 0.08em; min-width: 200px; }
.adx-inv-row b { font-variant-numeric: tabular-nums; margin-left: 4px; }
.adx-inv-note { opacity: 0.5; font-size: 10px; }

/* tables */
.adx-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.adx-table th { text-align: left; font-size: 8.5px; letter-spacing: 0.14em; opacity: 0.45; font-family: ui-monospace, monospace; padding: 6px 8px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.16); }
.adx-table td { padding: 8px; border-bottom: 1px dashed rgba(var(--cyan-rgb), 0.1); vertical-align: middle; }
.adx-table tr:hover td { background: rgba(var(--cyan-rgb), 0.05); }
.adx-sym { font-family: ui-monospace, monospace; font-weight: 800; color: rgba(var(--cyan-rgb), 0.95); }
.adx-name { opacity: 0.75; }
.adx-did { max-width: 230px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.adx-chg { font-size: 10px; margin-left: 5px; }
.adx-ta-r { text-align: right; }
.adx-actions { display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap; }

/* pills + buttons */
.adx-pill { display: inline-flex; align-items: center; gap: 4px; font-size: 8.5px; letter-spacing: 0.1em; padding: 3px 9px; border-radius: 99px; border: 1px solid currentColor; font-family: ui-monospace, monospace; margin-right: 4px; }
.adx-pill :deep(svg) { width: 10px; height: 10px; }
.adx-pill.ok, .adx-pill.st-trading { color: #10b981; }
.adx-pill.breach, .adx-pill.st-delisted { color: #ef4444; }
.adx-pill.pending, .adx-pill.st-halted { color: #f59e0b; }
.adx-pill.st-ipo, .adx-pill.local { color: rgba(var(--cyan-rgb), 0.95); }
.adx-pill.passport { color: #10b981; }
.adx-btn {
  display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
  font-family: ui-monospace, monospace; font-weight: 800; letter-spacing: 0.08em;
  color: rgba(var(--cyan-rgb), 1); background: rgba(var(--cyan-rgb), 0.1);
  border: 1px solid rgba(var(--cyan-rgb), 0.4); border-radius: 7px; transition: all 0.15s;
}
.adx-btn.sm { font-size: 9px; padding: 5px 10px; min-height: 28px; }
.adx-btn :deep(svg) { width: 11px; height: 11px; }
.adx-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.22); }
.adx-btn.ok { color: #10b981; background: rgba(16, 185, 129, 0.1); border-color: rgba(16, 185, 129, 0.45); }
.adx-btn.ok:hover:not(:disabled) { background: rgba(16, 185, 129, 0.22); }
.adx-btn.warn { color: #f59e0b; background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.45); }
.adx-btn.warn:hover:not(:disabled) { background: rgba(245, 158, 11, 0.22); }
.adx-btn.danger { color: #ef4444; background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.45); }
.adx-btn.danger:hover:not(:disabled) { background: rgba(239, 68, 68, 0.22); }
.adx-btn:disabled { opacity: 0.35; cursor: not-allowed; }

/* (demand-director styles moved to EigenTrustCommand.vue §2026-06-18) */

@media (max-width: 639.98px) {
  .adx { padding: 12px 10px 32px; }
  .adx-card { min-width: 0; overflow-x: auto; }
  .adx-card-head { flex-wrap: wrap; }
  .adx-hero h1 { font-size: 22px; }
  .adx-table { font-size: 10.5px; }
  .adx-table th, .adx-table td { padding: 5px; }
}

/* REGAUTH — parked-approval checklist (the E1b delete-blockers pattern) */
.adx-reg-park { margin-top: 14px; border: 1px solid rgba(245, 158, 11, .45); background: rgba(245, 158, 11, .07); border-radius: 10px; padding: 12px 14px; }
.adx-reg-park-title { display: flex; align-items: center; gap: 7px; margin: 0 0 8px; font-size: 13px; color: #f0c95c; font-weight: 600; }
.adx-reg-park-list { list-style: none; margin: 0 0 10px; padding: 0; display: grid; gap: 8px; }
.adx-reg-park-line { display: block; font-size: 12.5px; }
.adx-reg-park-line code { color: #f0c95c; }
.adx-reg-park-how { display: block; font-size: 11.5px; opacity: .75; margin-top: 2px; line-height: 1.45; }
.adx-reg-park-actions { display: flex; gap: 8px; }
</style>
