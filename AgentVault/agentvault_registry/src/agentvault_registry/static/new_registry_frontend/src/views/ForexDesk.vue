<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
/**
 * ForexDesk.vue — public agent Forex / Treasury desk.
 *
 * Lets a logged-in developer move value FROM any agent they own TO any agent:
 *   • another agent they own (same registry)      → local  /teg/transfer
 *   • an agent on another registry, same currency  → cross  /teg/cross-registry-transfer
 *   • an agent on a different-currency frame        → FX swap (auto-detected by the
 *     quote's same_currency=false; settled through /teg/cross-registry-transfer)
 *
 * Auth model: picking a FROM agent switches the active agent (auth store), which
 * mints that agent's JWT — the api client injects it on /teg/* calls. Mirrors the
 * Staking view's AAA+ look via tp-staking.css tokens; background painted by the
 * route's viewAmbientTone + DashboardLayout's <ViewAmbient>. [Commander 2026-06-07]
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useCurrency } from '@/composables/useCurrency'
import { useLogger } from '@/composables/useLogger'
import { useAlive } from '@/composables/useAlive'
import { tegApi, type TEGTransaction } from '@/services/api/teg'
import { fxService, type FxQuote, type FxRate } from '@/services/api/fx'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import '@/components/staking/tp-staking.css'

const { t } = useI18n()

const authStore = useAuthStore()
const uiStore = useUIStore()
const { localCurrency, glyphFor } = useCurrency()
const log = useLogger('ForexDesk')

// ── State ───────────────────────────────────────────────────────
const agents = computed<any[]>(() => authStore.availableAgents || [])
const fromDid = ref('')
const recipient = ref('')
const amount = ref('')
const message = ref('')

const step = ref<'form' | 'confirm' | 'result'>('form')
const sending = ref(false)
const switching = ref(false)
const loadingAgents = ref(false)

const fxRate = ref<FxRate | null>(null)
const fxRates = ref<any>(null)   // §2026-06-14 — all-pairs /fx/rates (the AVT/JDAY/BVT triangle)
const rateLoading = ref(false)
const rateUpdatedAt = ref<number | null>(null)

const fxQuote = ref<FxQuote | null>(null)
const fxQuoting = ref(false)
let fxQuoteTimer: ReturnType<typeof setTimeout> | null = null
let fxQuoteSeq = 0

const result = ref<any | null>(null)
const resultOk = ref(false)

const recent = ref<TEGTransaction[]>([])
const recentLoading = ref(false)
// §FESUITE (2026-10-05): a failed read of the agent's transactions said "No recent transactions for this agent."; it says
// the read failed now, with Try again. The list answers one agent: a failed refresh of the same agent keeps it, an answer
// for an agent no longer picked is dropped.
const recentFailed = ref(false)
let recentFor: string | null = null

let rateTimer: ReturnType<typeof setInterval> | null = null

// ── Derived ─────────────────────────────────────────────────────
const didOf = (a: any): string => a?.did || a?.agent_did || ''
const fromAgent = computed(() => agents.value.find(a => didOf(a) === fromDid.value) || null)
const fromHasCreds = computed(() => !!fromAgent.value?.hasCredentials)
const fromLiquid = computed(() => Number(fromAgent.value?.liquidBalance ?? 0))
const fromStaked = computed(() => Number(fromAgent.value?.stakedBalance ?? 0))
// Every agent a developer owns lives on THIS (local) frame → the sender's
// currency is always the local frame's currency.
const fromCurrency = computed(() => localCurrency.value)

const ownedDids = computed(() => new Set(agents.value.map(didOf).filter(Boolean)))
const otherOwned = computed(() => agents.value.filter(a => didOf(a) !== fromDid.value))

const recipientTrim = computed(() => recipient.value.trim())
const recipientIsOwnedLocal = computed(() =>
  !!recipientTrim.value && ownedDids.value.has(recipientTrim.value) && recipientTrim.value !== fromDid.value)
const recipientValid = computed(() =>
  recipientTrim.value.startsWith('did:') && recipientTrim.value !== fromDid.value)

const isCrossCurrency = computed(() => fxQuote.value?.same_currency === false)
const destCurrency = computed(() => fxQuote.value?.dest_currency || '')

/** local | cross | fx | none — the routing decision shown to the user. */
const transferKind = computed<'local' | 'cross' | 'fx' | 'none'>(() => {
  if (!recipientValid.value) return 'none'
  if (recipientIsOwnedLocal.value) return 'local'
  if (isCrossCurrency.value) return 'fx'
  return 'cross'
})

const amountNum = computed(() => parseFloat(amount.value))
const amountValid = computed(() =>
  !isNaN(amountNum.value) && amountNum.value > 0 && amountNum.value <= fromLiquid.value + 1e-9)
const overBalance = computed(() =>
  !isNaN(amountNum.value) && amountNum.value > fromLiquid.value + 1e-9)

const canSend = computed(() =>
  !!fromAgent.value && fromHasCreds.value && recipientValid.value && amountValid.value && !switching.value)

/** Explicit reason Send is unavailable — surfaced under the button (never leave the
 *  user guessing why the CTA is dim). */
const sendHint = computed(() => {
  if (!fromAgent.value) return 'Select an agent to send from.'
  if (!fromHasCreds.value) return 'This agent has no stored credentials — re-add it in My Agents to transact.'
  if (switching.value) return 'Authenticating as this agent…'
  if (!recipientTrim.value) return 'Enter a recipient agent DID.'
  if (!recipientValid.value) return recipientTrim.value === fromDid.value ? 'Pick a recipient other than the sender.' : 'Recipient must be a valid DID.'
  if (!amount.value) return 'Enter an amount to send.'
  if (overBalance.value) return 'Amount exceeds the available balance.'
  if (!amountValid.value) return 'Enter an amount greater than zero.'
  return ''
})

const fxAvailable = computed(() => fxRates.value?.available === true || fxRate.value?.available === true)
// §FESUITE (2026-10-04): both rate reads failed is not "single currency": the desk said "corridor off here" and "This
// frame settles in a single currency." with its reads failed. publicRate/publicRates answer null only when their read
// failed (a frame without FX answers available: false).
const rateUnread = ref(false)
// §BATCH9: honest keys first (any pair), legacy AVT/BVT keys as the fallback; the labels follow the payload.
const localCcy = computed<string>(() => String(fxRate.value?.local_currency || localCurrency.value || ''))
// §FEFRAME W2: no seeded peer unit: the payload names the peer's currency or the desk shows none
const peerCcy = computed<string>(() => String(fxRate.value?.peer_currency || ''))
const avtPerBvt = computed(() => Number(fxRate.value?.local_per_peer ?? fxRate.value?.avt_per_bvt))
const bvtPerAvt = computed(() => Number(fxRate.value?.peer_per_local ?? fxRate.value?.bvt_per_avt))
// §2026-06-14 — all live cross-currency pairs (the triangle). Each: "1 b = rate a".
const fxCurrencies = computed<string[]>(() => (fxRates.value?.currencies as string[]) || [])
const fxEdges = computed(() => {
  const fr: any = fxRates.value
  if (!fr || !fr.available || !Array.isArray(fr.pairs)) return []
  return fr.pairs.map((p: any) => ({ key: `${p.a}-${p.b}`, a: p.a, b: p.b, rate: fmtRate(Number(p.a_per_b)) }))
})

// ── Formatting ──────────────────────────────────────────────────
function fmt(v: string | number | undefined, dp = 2): string {
  const n = typeof v === 'string' ? parseFloat(v) : (v ?? 0)
  if (n === undefined || isNaN(n as number)) return '0.00'
  return (n as number).toLocaleString(appLocale(), { minimumFractionDigits: dp, maximumFractionDigits: dp })
}
function fmtRate(v: number): string {
  if (!Number.isFinite(v)) return '—'
  return v.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 6 })
}
/** A ledger type reads as words ("reward_fund_genesis_grant" -> "reward fund genesis grant"), so a long one can wrap. */
function txTypeLabel(t?: string | null): string {
  return (t || 'transfer').replace(/[_-]+/g, ' ').trim() || 'transfer'
}
function shortDid(d: string): string {
  if (!d) return ''
  return d.length <= 28 ? d : `${d.slice(0, 16)}…${d.slice(-8)}`
}
function clockOf(ts: number | null): string {
  if (!ts) return ''
  try { return new Date(ts).toLocaleTimeString(appLocale()) } catch { return '' }
}

// ── Data loads ──────────────────────────────────────────────────
async function ensureAgents() {
  if (agents.value.length) return
  loadingAgents.value = true
  try { await authStore.fetchAvailableAgents() }
  catch (e) { log.warn('fetchAvailableAgents failed', e) }
  finally { loadingAgents.value = false }
}

async function loadRate() {
  rateLoading.value = true
  try {
    const [single, all] = await Promise.all([fxService.publicRate(), fxService.publicRates()])
    fxRate.value = single
    fxRates.value = all
    rateUnread.value = single === null && all === null
    rateUpdatedAt.value = Date.now()
  } catch (e) { log.warn('publicRate failed', e) }
  finally { rateLoading.value = false }
}

async function loadRecent() {
  if (!fromHasCreds.value) { recent.value = []; recentFailed.value = false; return }
  const who = fromDid.value
  recentLoading.value = true
  try {
    const { transactions } = await tegApi.getTransactions({ limit: 8 })
    if (fromDid.value !== who) return
    recent.value = transactions || []
    recentFor = who
    recentFailed.value = false
  } catch (e) {
    log.warn('getTransactions failed', e)
    if (fromDid.value !== who) return
    if (recentFor !== who) { recent.value = []; recentFailed.value = true }
  } finally { recentLoading.value = false }
}

// ── From-agent selection (switches the active agent → mints its JWT) ─────────
async function selectFrom(did: string) {
  if (!did || did === fromDid.value) return
  fromDid.value = did
  recipient.value = ''
  amount.value = ''
  fxQuote.value = null
  result.value = null
  step.value = 'form'
  const a = agents.value.find(x => didOf(x) === did)
  if (!a?.hasCredentials) { recent.value = []; return }
  switching.value = true
  try {
    await authStore.switchAgent(did)
    await loadRecent()
  } catch (e) {
    log.warn('switchAgent failed', e)
    uiStore.showError('Agent switch failed', 'Could not authenticate as this agent. Re-add its credentials and retry.')
  } finally {
    switching.value = false
  }
}

// ── FX quote (debounced, seq-guarded) — only for EXTERNAL recipients ─────────
watch([recipient, amount, fromDid], () => {
  fxQuote.value = null
  if (fxQuoteTimer) clearTimeout(fxQuoteTimer)
  const seq = ++fxQuoteSeq
  // Owned-local transfers are 1:1 same-currency → no quote. Only external DIDs
  // can be cross-registry / cross-currency.
  if (recipientIsOwnedLocal.value || !recipientValid.value || !amountValid.value) return
  fxQuoteTimer = setTimeout(async () => {
    fxQuoting.value = true
    try {
      const q = await fxService.quote({ receiver_did: recipientTrim.value, amount: String(amount.value) })
      if (seq === fxQuoteSeq) fxQuote.value = q
    } catch {
      if (seq === fxQuoteSeq) fxQuote.value = null   // 401/no-corridor → plain cross-reg UX
    } finally {
      if (seq === fxQuoteSeq) fxQuoting.value = false
    }
  }, 400)
})

// ── Actions ─────────────────────────────────────────────────────
function setMax() { if (fromLiquid.value > 0) amount.value = String(fromLiquid.value) }
function pickRecipient(did: string) { recipient.value = did }
function openConfirm() { if (canSend.value) step.value = 'confirm' }
function backToForm() { step.value = 'form' }

async function doSend() {
  if (!canSend.value) return
  sending.value = true
  try {
    if (transferKind.value === 'local') {
      const r = await tegApi.transfer({
        receiver_agent_id: recipientTrim.value,
        amount: String(amount.value),
        message: message.value || undefined,
      })
      resultOk.value = (r.status ?? 'completed') !== 'failed'
      result.value = { transfer_id: r.transaction_id, status: r.status || 'completed', amount: String(amount.value), kind: 'local' }
    } else {
      const r = await tegApi.transferCrossRegistry({
        receiver_did: recipientTrim.value,
        amount: String(amount.value),
        message: message.value || undefined,
      })
      resultOk.value = r.status === 'completed'
      result.value = { ...r, kind: transferKind.value }
    }
    step.value = 'result'
    if (resultOk.value) {
      uiStore.showSuccess('Transfer sent', `${fmt(amount.value)} ${fromCurrency.value} → ${shortDid(recipientTrim.value)}`)
    } else {
      uiStore.showError('Transfer failed', result.value?.error_message || 'The transfer did not complete')
    }
    loadRecent()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.response?.data?.title || e?.message || 'Transfer failed'
    uiStore.showError('Transfer failed', String(msg))
    step.value = 'form'
  } finally {
    sending.value = false
  }
}

function resetForm() {
  step.value = 'form'
  recipient.value = ''
  amount.value = ''
  message.value = ''
  fxQuote.value = null
  result.value = null
}

function copyText(t?: string) {
  if (!t) return
  navigator.clipboard?.writeText(t).then(() => uiStore.showSuccess('Copied', 'Copied to clipboard')).catch(() => {})
}

// ── Lifecycle ───────────────────────────────────────────────────
// §FESUITE (the leave sweep): a page left during its first read starts no rate poll when it lands
const alive = useAlive()
onMounted(async () => {
  await ensureAgents()
  if (!alive()) return
  loadRate()
  rateTimer = setInterval(loadRate, 30000)
  // Default FROM = the active agent, else the first agent with stored credentials.
  const active = authStore.activeAgent ? didOf(authStore.activeAgent) : ''
  if (active && ownedDids.value.has(active)) {
    fromDid.value = active
    loadRecent()
  } else {
    const first = agents.value.find(a => a.hasCredentials) || agents.value[0]
    if (first) await selectFrom(didOf(first))
  }
})
onUnmounted(() => {
  if (fxQuoteTimer) clearTimeout(fxQuoteTimer)
  if (rateTimer) clearInterval(rateTimer)
})
</script>

<template>
  <div class="forex-desk px-6 py-6">
    <!-- Header -->
    <div class="sk-header flex flex-wrap items-end justify-between gap-4">
      <div>
        <div class="sk-header__eyebrow">// AGENT FOREX</div>
        <h1 class="sk-header__title" data-tour="fx-hero">Forex <span class="sk-header__title-accent">Desk</span></h1>
        <p class="sk-header__subtitle">Move value between your agents — across registries and currencies.</p>
      </div>
      <div class="fd-rate-chip" :class="{ 'fd-rate-chip--on': fxAvailable }" :title="fxAvailable ? 'Live cross-frame FX rates' : rateUnread ? '' : 'Single-currency frame'">
        <span v-if="fxCurrencies.length" class="fd-rate-chip__pair">
          <template v-for="(c, i) in fxCurrencies" :key="c">{{ glyphFor(c) }} {{ c }}<template v-if="i < fxCurrencies.length - 1"> ⇄ </template></template>
        </span>
        <span v-if="fxAvailable" class="fd-rate-chip__val">{{ fxEdges.length }} live pair{{ fxEdges.length === 1 ? '' : 's' }}</span>
        <span v-else-if="rateUnread && !rateLoading" class="fd-rate-chip__val">—</span>
        <span v-else class="fd-rate-chip__off">{{ rateLoading ? 'checking…' : 'corridor off here' }}</span>
        <button class="fd-icon-btn" :disabled="rateLoading" title="Refresh rates" @click="loadRate">↻</button>
      </div>
    </div>

    <!-- Loading agents -->
    <div v-if="loadingAgents" class="sk-card fd-loading">
      <span class="fd-spin"></span> Loading your agents…
    </div>

    <!-- §FESUITE (2026-10-05): a failed agent-list read said "No agents yet: Create an agent first"; it says the read
         failed now (authStore.agentFetchFailed), with Try again -->
    <div v-else-if="!agents.length && authStore.agentFetchFailed" class="sk-card fd-empty" data-testid="fd-agents-failed">
      <ReadFailedNotice :retry="ensureAgents" />
    </div>

    <!-- No agents -->
    <div v-else-if="!agents.length" class="sk-card fd-empty">
      <div class="fd-empty__title">No agents yet</div>
      <p class="fd-empty__sub">Create an agent first — then you can move value from the Forex Desk.</p>
      <RouterLink to="/my-agents" class="sk-btn sk-btn--primary">Go to My Agents</RouterLink>
    </div>

    <template v-else>
      <!-- Top grid: FROM agent + FX rate -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <!-- FROM agent -->
        <div class="sk-card lg:col-span-2 fd-from" data-tour="fx-from">
          <div class="sk-card-header"><span class="sk-card-title">From agent</span>
            <span v-if="switching" class="fd-muted">switching…</span></div>
          <div class="fd-from__row">
            <select class="sk-select fd-from__select" :aria-label="t('forexDeskView.fromAria', 'Pay from agent')" :value="fromDid" @change="selectFrom(($event.target as HTMLSelectElement).value)">
              <option v-for="a in agents" :key="didOf(a)" :value="didOf(a)">
                {{ a.name || shortDid(didOf(a)) }}{{ a.hasCredentials ? '' : ' — (no credentials)' }}
              </option>
            </select>
          </div>
          <div class="fd-bal-grid">
            <div class="fd-bal">
              <span class="fd-bal__label">Liquid</span>
              <span class="fd-bal__val">{{ glyphFor(fromCurrency) }} {{ fmt(fromLiquid) }} <small>{{ fromCurrency }}</small></span>
            </div>
            <div class="fd-bal">
              <span class="fd-bal__label">Locked</span>
              <span class="fd-bal__val fd-bal__val--muted">{{ glyphFor(fromCurrency) }} {{ fmt(fromStaked) }} <small>{{ fromCurrency }}</small></span>
            </div>
            <div class="fd-bal">
              <span class="fd-bal__label">DID</span>
              <span class="fd-bal__did" :title="fromDid">{{ shortDid(fromDid) }}
                <button class="fd-copy" title="Copy DID" @click="copyText(fromDid)">⧉</button></span>
            </div>
          </div>
          <div v-if="fromAgent && !fromHasCreds" class="sk-warn-box fd-creds-warn">
            <svg class="fd-warn-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12" y2="17"/></svg>
            This agent's credentials aren't stored on this device — re-add them in My Agents to transact as it.
          </div>
        </div>

        <!-- FX rate panel -->
        <div class="sk-card fd-rate" data-tour="fx-rate">
          <div class="sk-card-header"><span class="sk-card-title">Live FX</span>
            <span class="fd-muted fd-rate-at">{{ rateUpdatedAt ? clockOf(rateUpdatedAt) : '' }}</span></div>
          <template v-if="fxAvailable && fxEdges.length">
            <div v-for="e in fxEdges" :key="e.key" class="fd-rate__big">1 <b>{{ glyphFor(e.b) }} {{ e.b }}</b> = <b class="fd-rate__num">{{ e.rate }}</b> {{ glyphFor(e.a) }} {{ e.a }}</div>
            <div class="fd-rate__meta">
              <span class="sk-badge fd-badge-mode">{{ fxRates?.rate_mode || fxRate?.rate_mode || 'pool' }}</span>
              <span class="fd-muted">{{ fxEdges.length }} pair{{ fxEdges.length === 1 ? '' : 's' }}</span>
            </div>
          </template>
          <template v-else-if="fxAvailable">
            <div class="fd-rate__big">1 <b>{{ glyphFor(peerCcy) }} {{ peerCcy }}</b> = <b class="fd-rate__num">{{ fmtRate(avtPerBvt) }}</b> {{ glyphFor(localCcy) }} {{ localCcy }}</div>
            <div class="fd-rate__inv">1 {{ glyphFor(localCcy) }} {{ localCcy }} = {{ fmtRate(bvtPerAvt) }} {{ glyphFor(peerCcy) }} {{ peerCcy }}</div>
          </template>
          <ReadFailedNotice v-else-if="rateUnread" :retry="loadRate" dense />
          <div v-else class="fd-rate__off">
            <div class="fd-rate__off-glyph">⇄</div>
            <p>This frame settles in a single currency. Cross-currency swaps appear when a recipient is on a different-currency frame.</p>
          </div>
        </div>
      </div>

      <!-- Transfer panel -->
      <div class="sk-card fd-send" data-tour="fx-amount">
        <div class="sk-card-header">
          <span class="sk-card-title">Send</span>
          <span class="fd-route" :class="`fd-route--${transferKind}`" aria-live="polite">
            <template v-if="transferKind === 'local'">⇄ Local transfer</template>
            <template v-else-if="transferKind === 'fx'">◆◈ Cross-frame FX swap</template>
            <template v-else-if="transferKind === 'cross'">⛓ Cross-registry transfer</template>
            <template v-else>— pick a recipient</template>
          </span>
        </div>

        <div class="fd-send__grid">
          <!-- Recipient -->
          <div class="fd-field">
            <label class="sk-label" for="fd-recipient">Recipient agent DID</label>
            <input id="fd-recipient" v-model="recipient" type="text" class="sk-input sk-input--mono"
              placeholder="did:theprotocol:… or did:cos:…" spellcheck="false" @keyup.enter="openConfirm" />
            <div v-if="recipientTrim && !recipientValid" class="sk-input-error">
              {{ recipientTrim === fromDid ? 'Choose a different recipient than the sender' : 'Must be a valid DID (starts with did:)' }}
            </div>
            <div v-if="otherOwned.length" class="fd-chips">
              <span class="fd-chips__label">My agents:</span>
              <button v-for="a in otherOwned.slice(0, 6)" :key="didOf(a)" class="fd-chip"
                :class="{ 'fd-chip--on': recipientTrim === didOf(a) }" @click="pickRecipient(didOf(a))">
                {{ a.name || shortDid(didOf(a)) }}
              </button>
            </div>
          </div>

          <!-- Amount -->
          <div class="fd-field">
            <label class="sk-label" for="fd-amount">Amount ({{ fromCurrency }})</label>
            <div class="relative">
              <input id="fd-amount" v-model="amount" type="number" step="0.01" min="0" :max="fromLiquid"
                class="sk-input" placeholder="0.00" style="padding-right:4rem;" @keyup.enter="openConfirm" />
              <button class="sk-btn sk-btn--max absolute right-2" style="top:50%;transform:translateY(-50%);" @click="setMax">MAX</button>
            </div>
            <div class="sk-input-hint">
              Available: {{ glyphFor(fromCurrency) }} {{ fmt(fromLiquid) }} {{ fromCurrency }}
            </div>
            <div v-if="overBalance" class="sk-input-error">Amount exceeds available balance</div>
          </div>
        </div>

        <!-- FX quote preview -->
        <div v-if="fxQuoting" class="fd-quote fd-quote--loading">checking corridor…</div>
        <div v-else-if="isCrossCurrency && fxQuote" class="fd-quote" aria-live="polite">
          <div class="fd-quote__top">
            <span class="fd-quote__tag">◆◈ cross-frame swap</span>
            <span class="fd-quote__out">≈ {{ glyphFor(destCurrency) }} {{ fmt(fxQuote.amount_out) }} {{ destCurrency }}</span>
          </div>
          <div class="fd-quote__meta">
            <span>rate {{ fmtRate(Number(fxQuote.rate)) }}</span>
            <span v-if="fxQuote.fee != null">fee {{ fmt(fxQuote.fee) }}</span>
            <span v-if="fxQuote.slippage != null">slippage {{ (Number(fxQuote.slippage) * 100).toFixed(3) }}%</span>
            <span v-if="fxQuote.expires_at">valid until {{ new Date(fxQuote.expires_at).toLocaleTimeString(appLocale()) }}</span>
          </div>
          <div class="fd-quote__note">Indicative — the pool rate moves until settlement.</div>
        </div>

        <!-- Message -->
        <div class="fd-field">
          <label class="sk-label" for="fd-message">Message <span style="opacity:.5;">(optional)</span></label>
          <input id="fd-message" v-model="message" type="text" maxlength="256" class="sk-input" placeholder="Transfer note" />
        </div>

        <div class="fd-send__actions">
          <span v-if="sendHint" class="fd-send__hint" aria-live="polite">{{ sendHint }}</span>
          <button class="sk-btn sk-btn--primary fd-send__btn" data-tour="fx-send" :disabled="!canSend" @click="openConfirm">
            Review transfer →
          </button>
        </div>
      </div>

      <!-- Recent transactions -->
      <div class="sk-card fd-recent" data-tour="fx-recent">
        <div class="sk-card-header"><span class="sk-card-title">Recent activity</span>
          <button class="fd-icon-btn" :disabled="recentLoading" title="Refresh" @click="loadRecent">↻</button></div>
        <div v-if="recentLoading" class="fd-muted fd-recent__msg">Loading…</div>
        <ReadFailedNotice v-else-if="recentFailed" dense :retry="loadRecent" />
        <div v-else-if="!recent.length" class="fd-muted fd-recent__msg">No recent transactions for this agent.</div>
        <!-- A phone shows five columns by scrolling this box sideways, never by pushing the page past its edge. -->
        <div v-else class="fd-table-scroll" data-testid="fx-recent-scroll" tabindex="0" role="region" aria-label="Recent activity">
        <table class="fd-table">
          <thead><tr><th>Type</th><th>Counterparty</th><th class="ta-r">Amount</th><th>Status</th><th class="ta-r">When</th></tr></thead>
          <tbody>
            <tr v-for="tx in recent" :key="tx.transaction_id">
              <td><span class="fd-tx-type">{{ txTypeLabel(tx.transaction_type) }}</span></td>
              <td class="fd-mono">{{ shortDid(tx.receiver_agent_id || tx.sender_agent_id || '') }}</td>
              <td class="ta-r fd-mono fd-nowrap">{{ fmt(tx.amount) }}</td>
              <td><span class="sk-badge" :class="{ 'sk-badge--distributed': tx.status==='completed', 'sk-badge--pending': tx.status==='pending', 'sk-badge--failed': tx.status==='failed' }">{{ tx.status }}</span></td>
              <td class="ta-r fd-muted fd-nowrap">{{ tx.timestamp ? new Date(tx.timestamp).toLocaleString(appLocale()) : '' }}</td>
            </tr>
          </tbody>
        </table>
        </div>
      </div>
    </template>

    <!-- Confirm / Result overlay (kept INSIDE .forex-desk so --sk-* tokens resolve) -->
    <div v-if="step !== 'form'" class="fd-overlay" @click.self="step === 'confirm' ? backToForm() : resetForm()">
      <div class="sk-modal fd-modal">
        <!-- Confirm -->
        <template v-if="step === 'confirm'">
          <div class="sk-modal-header"><span class="sk-modal-title">Confirm transfer</span>
            <button class="fd-x" @click="backToForm">✕</button></div>
          <div class="sk-modal-body space-y-3">
            <div class="sk-card fd-sum">
              <div class="fd-sum__row"><span>From</span><b class="fd-mono">{{ fromAgent?.name || shortDid(fromDid) }}</b></div>
              <div class="fd-sum__row"><span>To</span><b class="fd-mono">{{ shortDid(recipientTrim) }}</b></div>
              <div class="fd-sum__row"><span>Amount</span><b class="fd-sum__amt">{{ glyphFor(fromCurrency) }} {{ fmt(amount) }} {{ fromCurrency }}</b></div>
              <div v-if="transferKind === 'fx' && fxQuote" class="fd-sum__row"><span>Recipient receives ≈</span>
                <b class="fd-sum__dest">{{ glyphFor(destCurrency) }} {{ fmt(fxQuote.amount_out) }} {{ destCurrency }}</b></div>
              <div class="fd-sum__row"><span>Route</span>
                <span class="fd-route" :class="`fd-route--${transferKind}`">
                  {{ transferKind === 'local' ? 'Local' : transferKind === 'fx' ? 'Cross-frame FX' : 'Cross-registry' }}
                </span></div>
              <div v-if="message" class="fd-sum__row"><span>Message</span><span class="fd-mono">{{ message }}</span></div>
            </div>
            <div class="sk-info-box fd-info">
              <template v-if="transferKind === 'local'">Instant same-registry transfer. A small network fee applies.</template>
              <template v-else-if="transferKind === 'fx'">Cross-frame swap through the FX pool between the two frames' units — the rate is final at settlement. If the target is unreachable, funds return automatically.</template>
              <template v-else>2-phase-commit cross-registry transfer — funds lock, move, then commit atomically; auto-returned if the target is unreachable.</template>
            </div>
          </div>
          <div class="sk-modal-footer">
            <button class="sk-btn sk-btn--ghost flex-1" :disabled="sending" @click="backToForm">← Back</button>
            <button class="sk-btn sk-btn--primary flex-1" :disabled="sending" @click="doSend">{{ sending ? 'Sending…' : 'Confirm & send' }}</button>
          </div>
        </template>

        <!-- Result -->
        <template v-else-if="step === 'result' && result">
          <div class="sk-modal-header"><span class="sk-modal-title">Transfer {{ resultOk ? 'sent' : 'result' }}</span>
            <button class="fd-x" @click="resetForm">✕</button></div>
          <div class="sk-modal-body space-y-3">
            <div class="fd-result__icon" :class="resultOk ? 'fd-result__icon--ok' : 'fd-result__icon--bad'">{{ resultOk ? '✓' : '✕' }}</div>
            <div class="fd-result__title">{{ resultOk ? 'Transfer complete' : (result.status || 'Failed') }}</div>
            <p v-if="result.error_message" class="fd-result__err">{{ result.error_message }}</p>
            <div class="sk-card fd-sum">
              <div v-if="result.transfer_id" class="fd-sum__row"><span>Reference</span>
                <span class="fd-mono">{{ shortDid(result.transfer_id) }} <button class="fd-copy" @click="copyText(result.transfer_id)">⧉</button></span></div>
              <div class="fd-sum__row"><span>Amount</span><b class="fd-sum__amt">{{ glyphFor(fromCurrency) }} {{ fmt(result.amount || amount) }} {{ fromCurrency }}</b></div>
              <div class="fd-sum__row"><span>Status</span>
                <span class="sk-badge" :class="resultOk ? 'sk-badge--distributed' : 'sk-badge--failed'">{{ result.status }}</span></div>
              <div v-if="result.source_teg" class="fd-sum__row"><span>Route</span><span class="fd-mono">{{ result.source_teg }} → {{ result.target_teg }}</span></div>
            </div>
          </div>
          <div class="sk-modal-footer">
            <button class="sk-btn sk-btn--outline flex-1" @click="resetForm">New transfer</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* tp-staking.css provides --sk-* tokens + the sk-* classes (root .forex-desk is in
   that token selector). Below = Forex-specific flourishes (fd-*). */

/* ── Polish pass 1 — layout, hierarchy, hero ───────────────────── */
.forex-desk { max-width: 1180px; margin-inline: auto; }
/* §2026-06-07 — the .sk-card body content sat FLUSH to the card edge (only the
   header carried a gutter) → the Send panel read cramped. Pad everything after the
   header to match the header's 1.5rem gutter + add breathing room. (Commander) */
.forex-desk .sk-card > .sk-card-header ~ * { padding-left: 1.5rem; padding-right: 1.5rem; }
.forex-desk .sk-card > .sk-card-header + * { padding-top: 1.4rem; }
.forex-desk .sk-card > .sk-card-header ~ *:last-child { padding-bottom: 1.5rem; }
/* the Send panel earns extra interior air — it's the hero */
.forex-desk .fd-send > .fd-send__grid { padding-top: 1.6rem; }
.forex-desk .fd-send__grid { gap: 1.25rem; margin-bottom: 1.1rem; }
.forex-desk .fd-send .fd-field { margin-bottom: 1.1rem; }
/* cards gently brighten on hover; the Send panel is the hero (always lit) */
.sk-card { transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.fd-from:hover, .fd-rate:hover, .fd-recent:hover { border-color: var(--sk-border-bright); }
.fd-send { border-color: var(--sk-border-bright); box-shadow: 0 0 44px -22px rgba(var(--nc-primary-rgb), 0.55); }

/* ── Polish pass 2 — motion & states ───────────────────────────── */
.fd-route { transition: color .2s ease, background .2s ease, border-color .2s ease; }
.fd-quote { animation: fd-quote-in .25s ease both; }
.fd-overlay { animation: fd-fade-in .18s ease both; }
.fd-modal { animation: fd-pop-in .22s cubic-bezier(.2,.8,.3,1) both; }
@keyframes fd-quote-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
@keyframes fd-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes fd-pop-in { from { opacity: 0; transform: translateY(8px) scale(.98); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .fd-quote, .fd-overlay, .fd-modal, .fd-spin { animation: none !important; }
}

/* live-rate chip in the header */
.fd-rate-chip { display:flex; align-items:center; gap:10px; padding:8px 12px; border-radius:10px;
  background:var(--sk-bg-card); border:1px solid var(--sk-border); font-family:'IBM Plex Mono',monospace; font-size:0.78rem; }
.fd-rate-chip--on { border-color:var(--sk-border-bright); box-shadow:0 0 18px -8px rgba(var(--nc-primary-rgb),0.5); }
.fd-rate-chip__pair { color:var(--sk-text-sec); }
.fd-rate-chip__val { color:var(--sk-cyan); font-weight:700; }
/* §FESUITE (2026-10-10, the operator batch): the muted token is 3.98:1 on the desk's #0d1117 (under 4.5); this chip is
   text a person reads, shown wherever a corridor is off (every cloud operator), so it takes the secondary token (7.4:1) */
.fd-rate-chip__off { color:var(--sk-text-sec); }
.fd-icon-btn { background:none; border:1px solid var(--sk-border); color:var(--sk-text-sec); width:24px; height:24px; border-radius:6px;
  cursor:pointer; line-height:1; transition:all .15s; }
.fd-icon-btn:hover:not(:disabled) { border-color:var(--sk-border-bright); color:var(--sk-cyan); }
.fd-icon-btn:disabled { opacity:.4; cursor:not-allowed; }

.fd-muted { color:var(--sk-text-muted); font-size:0.7rem; font-family:'IBM Plex Mono',monospace; }
.fd-mono { font-family:'IBM Plex Mono',monospace; color:var(--sk-text); font-size:0.82rem; }
.ta-r { text-align:right; }

.fd-loading, .fd-empty { display:flex; flex-direction:column; align-items:center; gap:10px; padding:2.5rem; text-align:center; color:var(--sk-text-sec); }
.fd-empty__title { font-size:1.1rem; color:var(--sk-text); font-weight:600; }
.fd-empty__sub { color:var(--sk-text-muted); font-size:0.85rem; }
.fd-spin { width:18px;height:18px;border:2px solid var(--sk-border);border-top-color:var(--sk-cyan);border-radius:50%;animation:fd-spin 0.8s linear infinite;display:inline-block; }
@keyframes fd-spin { to { transform:rotate(360deg); } }

/* FROM agent card */
.fd-from__row { margin-bottom:14px; }
.fd-from__select { width:100%; max-width:100%; }
.fd-bal-grid { display:grid; grid-template-columns:1fr 1fr 1.4fr; gap:12px; }
.fd-bal { display:flex; flex-direction:column; gap:3px; }
.fd-bal__label { font-size:0.6rem; letter-spacing:0.12em; text-transform:uppercase; color:var(--sk-text-muted); }
.fd-bal__val { font-family:'IBM Plex Mono',monospace; font-size:1.35rem; font-weight:700; color:var(--sk-cyan); font-variant-numeric:tabular-nums; letter-spacing:-0.015em; text-shadow:0 0 22px color-mix(in srgb, currentColor 20%, transparent); }
.fd-bal__val small { font-size:0.62rem; color:var(--sk-text-muted); font-weight:400; }
.fd-bal__val--muted { color:var(--sk-text-sec); }
.fd-bal__did { font-family:'IBM Plex Mono',monospace; font-size:0.8rem; color:var(--sk-text-sec); display:flex; align-items:center; gap:6px; }
.fd-copy, .fd-x { background:none; border:none; color:var(--sk-text-muted); cursor:pointer; }
.fd-copy:hover, .fd-x:hover { color:var(--sk-cyan); }
.fd-creds-warn { margin-top:12px; display:flex; align-items:flex-start; gap:8px; }
.fd-warn-ic { width:16px; height:16px; flex-shrink:0; margin-top:1px; color: var(--sk-amber); }

/* FX rate panel */
.fd-rate__big { font-size:1.05rem; color:var(--sk-text); margin:6px 0 4px; }
.fd-rate__big b { color:var(--sk-text); }
.fd-rate__num { color:var(--sk-cyan); }
.fd-rate__inv { font-family:'IBM Plex Mono',monospace; font-size:0.78rem; color:var(--sk-text-muted); }
.fd-rate__meta { display:flex; align-items:center; gap:10px; margin-top:10px; }
.fd-badge-mode { background:var(--sk-cyan-dim); color:var(--sk-cyan); border:1px solid var(--sk-border); text-transform:uppercase; }
.fd-rate__off { text-align:center; color:var(--sk-text-muted); padding:6px 4px; }
.fd-rate__off-glyph { font-size:1.8rem; color:var(--sk-text-sec); opacity:.5; }
.fd-rate__off p { font-size:0.74rem; margin-top:6px; line-height:1.45; }

/* send panel */
.fd-route { font-family:'IBM Plex Mono',monospace; font-size:0.72rem; padding:3px 10px; border-radius:20px; border:1px solid var(--sk-border); }
.fd-route--local { color:var(--sk-cyan); background:var(--sk-cyan-dim); border-color:rgba(var(--nc-primary-rgb),0.3); }
.fd-route--cross { color:var(--sk-purple); background:var(--sk-purple-dim); border-color:rgba(168,85,247,0.3); }
.fd-route--fx { color:var(--cur-bvt,#ff9d3c); background:rgba(255,157,60,0.08); border-color:rgba(255,157,60,0.4); }
.fd-route--none { color:var(--sk-text-muted); }
.fd-send__grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:14px; }
.fd-field { margin-bottom:14px; }
.fd-chips { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:8px; }
.fd-chips__label { font-size:0.62rem; color:var(--sk-text-muted); text-transform:uppercase; letter-spacing:0.08em; }
.fd-chip { font-family:'IBM Plex Mono',monospace; font-size:0.7rem; padding:3px 9px; border-radius:14px; cursor:pointer;
  background:var(--sk-bg-input); border:1px solid var(--sk-border); color:var(--sk-text-sec); transition:all .14s; }
.fd-chip:hover { border-color:var(--sk-border-bright); color:var(--sk-text); }
.fd-chip--on { background:var(--sk-cyan-dim); border-color:rgba(var(--nc-primary-rgb),0.4); color:var(--sk-cyan); }

.fd-quote { margin:2px 0 14px; padding:10px 12px; border-radius:8px; border:1px solid rgba(255,157,60,0.4); background:rgba(255,157,60,0.06); }
.fd-quote--loading { color:var(--sk-text-muted); border-color:var(--sk-border); background:transparent; font-size:0.78rem; }
.fd-quote__top { display:flex; justify-content:space-between; align-items:baseline; font-family:'IBM Plex Mono',monospace; font-size:0.82rem; }
.fd-quote__tag { color:rgba(255,157,60,0.95); }
.fd-quote__out { font-weight:700; color:var(--cur-bvt,#ff9d3c); }
.fd-quote__meta { display:flex; flex-wrap:wrap; gap:14px; margin-top:5px; font-size:0.66rem; opacity:.65; font-family:'IBM Plex Mono',monospace; }
.fd-quote__note { margin-top:4px; font-size:0.62rem; opacity:.5; }
.fd-send__actions { display:flex; align-items:center; justify-content:flex-end; gap:14px; margin-top:6px; }
.fd-send__hint { margin-right:auto; font-family:'IBM Plex Mono',monospace; font-size:0.72rem; color:var(--sk-text-muted); }
.fd-send__btn { min-width:200px; }

/* recent table */
.fd-recent { margin-top:16px; }
.fd-recent__msg { padding:1rem 0; text-align:center; }
.fd-table-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; max-width:100%; }
.fd-table-scroll:focus-visible { outline:1px solid rgba(var(--nc-primary-rgb), .6); outline-offset:2px; }
.fd-table { width:100%; border-collapse:collapse; font-size:0.8rem; }
.fd-nowrap { white-space:nowrap; }
.fd-table th { text-align:left; font-size:0.6rem; text-transform:uppercase; letter-spacing:0.1em; color:var(--sk-text-muted); padding:6px 8px; border-bottom:1px solid var(--sk-border-dim); }
.fd-table td { padding:8px; border-bottom:1px solid var(--sk-border-dim); color:var(--sk-text-sec); }
.fd-tx-type { font-family:'IBM Plex Mono',monospace; font-size:0.72rem; color:var(--sk-text); text-transform:capitalize; }

/* overlay (nested in .forex-desk → tokens resolve; no Teleport) */
.fd-overlay { position:fixed; inset:0; z-index:60; display:flex; align-items:center; justify-content:center; padding:1rem; background:rgba(2,4,10,0.78); backdrop-filter:blur(4px); }
.fd-modal { max-width:460px; width:100%; }
.fd-sum { padding:0.9rem 1rem; gap:0; }
.fd-sum__row { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:7px 0; border-bottom:1px solid var(--sk-border-dim); }
.fd-sum__row:last-child { border-bottom:none; }
.fd-sum__row > span:first-child { color:var(--sk-text-muted); font-size:0.78rem; }
.fd-sum__amt { font-family:'IBM Plex Mono',monospace; color:var(--sk-cyan); font-size:1.05rem; }
.fd-sum__dest { font-family:'IBM Plex Mono',monospace; color:var(--cur-bvt,#ff9d3c); }
.fd-info { font-size:0.76rem; }
.fd-result__icon { width:54px; height:54px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:1.6rem; margin:0 auto; }
.fd-result__icon--ok { background:var(--sk-green-dim); color:var(--sk-green); border:1px solid rgba(16,185,129,0.3); }
.fd-result__icon--bad { background:var(--sk-red-dim); color:var(--sk-red); border:1px solid rgba(239,68,68,0.3); }
.fd-result__title { text-align:center; font-weight:600; color:var(--sk-text); }
.fd-result__err { text-align:center; color:var(--sk-red); font-size:0.8rem; }

/* ── Polish pass 4 — a11y focus affordance ─────────────────────── */
.forex-desk :is(button, input, select):focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: 2px; }

/* ── Polish pass 5 — micro-interactions & cohesion ─────────────── */
.fd-bal__val, .fd-sum__amt, .fd-sum__dest, .fd-quote__out, .fd-mono { font-variant-numeric: tabular-nums; }
.fd-table tbody tr { transition: background .14s ease; }
.fd-table tbody tr:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
/* a live heartbeat dot in front of the rate value (only rendered when FX is on) */
.fd-rate-chip__val::before { content:''; display:inline-block; width:6px; height:6px; border-radius:50%;
  background:var(--sk-cyan); margin-right:6px; box-shadow:0 0 6px var(--sk-cyan); vertical-align:middle; animation: fd-live 2s ease-in-out infinite; }
@keyframes fd-live { 0%,100% { opacity:.45; } 50% { opacity:1; } }
.fd-send__btn { transition: transform .12s ease, background .15s ease; }
.fd-send__btn:not(:disabled):active { transform: translateY(1px); }
.fd-chip, .fd-icon-btn, .fd-copy { transition: all .14s ease; }
@media (prefers-reduced-motion: reduce) { .fd-rate-chip__val::before { animation: none !important; } }

@media (max-width: 720px) {
  .fd-send__grid { grid-template-columns:1fr; }
  .fd-bal-grid { grid-template-columns:1fr 1fr; }
  /* §COCKPITDESK (2026-10-15), the phone camera: the unit fell under the figure, and the send hint was a five-line
     column beside a 200 px button. The figure steps down a size; the hint and the button stack, full width. */
  .fd-bal__val { font-size: 1.08rem; }
  .fd-send__actions { flex-direction: column; align-items: stretch; gap: 10px; }
  .fd-send__hint { margin-right: 0; }
  .fd-send__btn { min-width: 0; width: 100%; }
}
/* §COCKPITDESK (2026-10-15): the camera read "Live FX12:13:08 PM": the time sat against the title */
.fd-rate-at { margin-left: .6rem; }
/* §COCKPITDESK (2026-10-15), the phone camera's small-target readings (WCAG 2.5.8, 24 x 24 CSS px): a finger's target grows, the glyph keeps its size */
@media (pointer: coarse), (max-width: 640px) {
  .fd-copy, .fd-x { min-width: 24px; min-height: 24px; padding: 4px; display: inline-flex; align-items: center; justify-content: center; }
}
</style>
