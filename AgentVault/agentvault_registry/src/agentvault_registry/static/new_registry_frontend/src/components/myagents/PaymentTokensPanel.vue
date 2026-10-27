<template>
  <!-- Build #2 (2026-05-07): A2A Payment Token Manager.
       Drop-in panel for MyAgents.vue. Mirrors funding-section's collapsible
       header pattern so the visual rhythm of the page is preserved.
       Strategy doc §4 Build #2 — first frontend integration of f045 protocol. -->
  <div class="pt-section">

    <!-- Collapsible header — pattern matches funding-section -->
    <div class="pt-header" @click="expanded = !expanded">
      <span class="pt-glyph">⏣</span>
      {{ t('myAgentsView.actions.paymentTokens') }}
      <!-- §FESUITE (V0577): the list is read only once the panel opens, so a "0" here was drawn before any read (and
           after a failed one); like the Statement's header, a count shows only when there is one -->
      <span v-if="tokens.length" class="pt-count">{{ tokens.length }}</span>
      <span class="pt-hint-inline">A2A — authorize · verify · settle</span>
      <span v-if="hasActiveAuthorized" class="pt-pill pt-pill--amber" title="Authorizations hold units until they are settled or released">
        {{ activeAuthorizedCount }} active
      </span>
      <span class="pt-flex"></span>
      <span class="pt-toggle">{{ expanded ? '▾' : '▸' }}</span>
    </div>

    <!-- Body — only rendered when expanded -->
    <div v-if="expanded" class="pt-body">

      <!-- No agent — gate with helpful message -->
      <div v-if="!agentDid" class="pt-note">
        <span class="pt-note-icon">!</span>
        <span>Select an agent above to view its A2A payment authorizations.</span>
      </div>

      <!-- All other states require an agent -->
      <template v-else>
        <!-- Toolbar — filter + auto-refresh + action -->
        <div class="pt-toolbar">
          <div class="pt-toolbar-left">
            <span class="pt-toolbar-label">FILTER</span>
            <button
              v-for="f in FILTERS"
              :key="f.id || 'all'"
              class="pt-chip"
              :class="{ 'pt-chip--active': activeFilter === f.id }"
              :title="f.title"
              @click="setFilter(f.id)"
            >
              {{ f.label }}
              <span v-if="f.id === activeFilter && tokens.length" class="pt-chip-count">{{ tokens.length }}</span>
            </button>
          </div>
          <div class="pt-toolbar-right">
            <span class="pt-meta-key">Last refresh</span>
            <span class="pt-meta-val">{{ lastRefreshAt || '—' }}</span>
            <button
              class="pt-btn pt-btn--ghost"
              :title="autoRefresh ? 'Pause auto-refresh' : 'Resume auto-refresh (30s)'"
              @click="toggleAutoRefresh"
            >
              <span class="pt-live-dot" :class="{ 'pt-live-dot--on': autoRefresh }"></span>
              {{ autoRefresh ? 'Pause' : 'Resume' }}
            </button>
            <button class="pt-btn pt-btn--ghost" :disabled="loading" @click="refresh">↻ Refresh</button>
          </div>
        </div>

        <!-- §FEPARITY-5 — the authorize / verify / settle rails (service methods
             existed since Build #2 with zero component callers; the money move
             was MCP/SDK-only). Two tools: outbound hold creation, and the
             inbound verify→settle flow a service agent runs to collect. -->
        <div class="pt-tools">
          <button class="pt-btn pt-btn--ghost" :class="{ 'pt-chip--active': showAuthorize }" data-tour="pt-authorize"
                  @click="showAuthorize = !showAuthorize; if (showAuthorize) showIncoming = false">
            ＋ Authorize payment
          </button>
          <button class="pt-btn pt-btn--ghost" :class="{ 'pt-chip--active': showIncoming }" data-tour="pt-incoming"
                  @click="showIncoming = !showIncoming; if (showIncoming) showAuthorize = false">
            ⇩ Verify / settle incoming
          </button>
        </div>

        <!-- Outbound: authorize a new hold -->
        <div v-if="showAuthorize" class="pt-form">
          <div class="pt-form-title">AUTHORIZE A PAYMENT</div>
          <p class="pt-form-hint">
            Creates an <strong>AUTHORIZED</strong> hold against this agent's balance. The target agent
            verifies the authorization, performs the work, then settles — moving the funds. Unsettled holds
            expire at TTL or can be released above.
          </p>
          <div class="pt-form-row">
            <input v-model.trim="authTarget" class="pt-input" placeholder="target agent DID (did:…)" />
            <input v-model.trim="authAmount" class="pt-input pt-input--sm" :placeholder="`amount (${localCurrency})`" />
            <input v-model.number="authTtl" type="number" min="60" max="3600" class="pt-input pt-input--xs" title="TTL seconds (60–3600)" />
            <input v-model.trim="authContract" class="pt-input pt-input--xs" placeholder="contract # (opt)" />
            <button class="pt-btn pt-btn--ghost" :disabled="!canAuthorize || authBusy" @click="doAuthorize">
              <span v-if="authBusy" class="pt-spinner"></span> Authorize
            </button>
          </div>
          <p v-if="authError" class="pt-form-err">{{ authError }}</p>
          <div v-if="authResult" class="pt-token-box">
            <div class="pt-token-box-head">
              <Icon name="mdi:alert" /> Plaintext authorization — shown <strong>ONCE</strong>, never retrievable again. Hand it to the target agent.
            </div>
            <div class="pt-token-box-row">
              <code class="pt-token-code">{{ authResult.token }}</code>
              <button class="pt-icon-btn" title="Copy authorization" @click="copyText(authResult.token)">⎘</button>
            </div>
            <div class="pt-form-hint">
              {{ formatAmount(authResult.amount) }} {{ localCurrency }} held for
              <code>{{ shortDid(authResult.target_agent_did) }}</code> · expires {{ formatAbs(authResult.expires_at) }}
            </div>
          </div>
        </div>

        <!-- Inbound: verify then settle (the collecting side) -->
        <div v-if="showIncoming" class="pt-form">
          <div class="pt-form-title">VERIFY / SETTLE AN INCOMING AUTHORIZATION</div>
          <p class="pt-form-hint">
            Paste an authorization another agent issued <strong>to this agent</strong>. Verify checks the hold;
            Settle collects it (moves the funds to this agent) after the work is done.
          </p>
          <div class="pt-form-row">
            <input v-model.trim="incomingToken" class="pt-input" placeholder="apt_… (plaintext payment authorization)" spellcheck="false" />
            <button class="pt-btn pt-btn--ghost" :disabled="!incomingToken || verifyBusy" @click="doVerify">
              <span v-if="verifyBusy" class="pt-spinner"></span> Verify
            </button>
            <button v-if="verifyResult?.valid" class="pt-btn pt-btn--danger" :disabled="settleBusy" @click="settleModalOpen = true">
              Settle…
            </button>
          </div>
          <p v-if="verifyError" class="pt-form-err">{{ verifyError }}</p>
          <div v-if="verifyResult" class="pt-verify-box" :class="verifyResult.valid ? 'pt-verify-box--ok' : 'pt-verify-box--bad'">
            <template v-if="verifyResult.valid">
              <div><strong>VALID</strong> · {{ formatAmount(verifyResult.amount || 0) }} {{ localCurrency }}
                from <code>{{ shortDid(verifyResult.caller_did || '') }}</code>
                · status {{ (verifyResult.status || '').toUpperCase() }}
                <template v-if="verifyResult.expires_at"> · expires {{ formatAbs(verifyResult.expires_at) }}</template>
              </div>
              <div v-if="(verifyResult.status || '').toUpperCase() === 'CONSUMED'" class="pt-form-err">
                ⚠ Already CONSUMED — verify still answers valid=true on consumed authorizations (P25-001).
                Do <strong>not</strong> re-do paid work for this authorization; settlement should already be in flight.
              </div>
            </template>
            <template v-else>
              <strong>INVALID</strong> · {{ verifyResult.error || verifyResult.status || 'authorization rejected' }}
            </template>
          </div>
          <div v-if="settleResult" class="pt-token-box">
            <div class="pt-token-box-head"><Icon name="mdi:check-circle" /> Settled</div>
            <div class="pt-form-hint">
              {{ formatAmount(settleResult.amount) }} {{ localCurrency }} moved to <code>{{ shortDid(settleResult.target_agent_did) }}</code>
              · status {{ settleResult.status }}
              <template v-if="settleResult.settlement_tx_id"> · tx <code>{{ settleResult.settlement_tx_id }}</code></template>
            </div>
          </div>
        </div>

        <!-- Stats row -->
        <!-- §FESUITE (V0577): counts of a list that could not be read are "—", never 0 -->
        <div class="pt-stats" :data-unread="listUnread ? '1' : '0'">
          <div class="pt-stat-cell">
            <span class="pt-stat-value">{{ listUnread ? '—' : statsByStatus.AUTHORIZED }}</span>
            <span class="pt-stat-label">AUTHORIZED</span>
          </div>
          <div class="pt-stat-cell">
            <span class="pt-stat-value pt-stat-value--cyan">{{ listUnread ? '—' : statsByStatus.SETTLED }}</span>
            <span class="pt-stat-label">SETTLED</span>
          </div>
          <div class="pt-stat-cell">
            <span class="pt-stat-value pt-stat-value--muted">{{ listUnread ? '—' : statsByStatus.RELEASED + statsByStatus.EXPIRED }}</span>
            <span class="pt-stat-label">RELEASED / EXPIRED</span>
          </div>
          <div class="pt-stat-cell">
            <span class="pt-stat-value pt-stat-value--bad">{{ listUnread ? '—' : statsByStatus.FAILED }}</span>
            <span class="pt-stat-label">FAILED</span>
          </div>
        </div>

        <!-- Inline error -->
        <div v-if="error" class="pt-error" role="alert">
          <span><Icon name="mdi:alert" /> {{ error }}</span>
          <button class="pt-btn pt-btn--ghost" @click="refresh">Retry</button>
        </div>

        <!-- §FESUITE (V0577): the tokens could not be read; the error above says so, and nothing below claims
             "No payment tokens yet" under it -->
        <template v-if="listUnread" />
        <!-- Loading skeleton -->
        <div v-else-if="loading && tokens.length === 0" class="pt-skeleton">
          <div v-for="i in 3" :key="i" class="pt-skel-row"></div>
        </div>

        <!-- Empty -->
        <div v-else-if="tokens.length === 0" class="pt-empty">
          <div class="pt-empty-glyph"><Icon name="mdi:hand-coin-outline" /></div>
          <p class="pt-empty-title">No payment authorizations yet</p>
          <p class="pt-empty-sub">
            <template v-if="activeFilter">
              Nothing matches the <strong>{{ activeFilter }}</strong> filter.
            </template>
            <template v-else>
              When this agent calls another agent's paid endpoint via SDK with <code>payment_required=true</code>, an authorization is created automatically.
              <a href="#/legal/a2a-protocol-docs" class="pt-link" @click="$event.preventDefault(); navigateToA2ADocs()">Read the protocol docs →</a>
            </template>
          </p>
          <button v-if="activeFilter" class="pt-btn pt-btn--ghost" @click="setFilter(null)">Clear filter</button>
        </div>

        <!-- Tokens table -->
        <div v-else class="pt-list">
          <div v-for="t in tokens" :key="t.token_id" class="pt-row" :class="rowClass(t)">
            <button class="pt-row-head" @click="toggleExpand(t.token_id)" :aria-expanded="expandedId === t.token_id">
              <span class="pt-status-dot" :class="dotClass(t)" :title="t.status"></span>

              <span class="pt-row-token" :title="t.token_id">{{ shortId(t.token_id) }}</span>

              <span class="pt-row-arrow">→</span>

              <span class="pt-row-target" :title="t.target_agent_did">{{ shortDid(t.target_agent_did) }}</span>

              <span class="pt-pill" :class="pillClass(t)">{{ (t.status || '').toUpperCase() }}</span>

              <span v-if="t.contract_id" class="pt-pill pt-pill--soft" :title="`Linked to contract #${t.contract_id}`">CONTRACT #{{ t.contract_id }}</span>

              <span class="pt-row-spacer"></span>

              <span class="pt-row-amount">{{ formatAmount(t.amount) }} {{ localCurrency }}</span>

              <span
                v-if="t.status?.toUpperCase() === 'AUTHORIZED'"
                class="pt-ttl"
                :class="{ 'pt-ttl--urgent': isExpiringSoon(t) }"
                :title="`Expires ${formatAbs(t.expires_at)}`"
              >{{ ttlLabel(t.expires_at) }}</span>

              <span v-else class="pt-row-time" :title="formatAbs(t.settled_at || t.created_at)">{{ timeAgo(t.settled_at || t.created_at) }}</span>

              <span class="pt-row-caret">{{ expandedId === t.token_id ? '▾' : '▸' }}</span>
            </button>

            <!-- Expanded detail -->
            <div v-if="expandedId === t.token_id" class="pt-detail">
              <!-- Idempotency warning for CONSUMED tokens (P25-001 from CLAUDE.md) -->
              <div v-if="t.status?.toUpperCase() === 'CONSUMED'" class="pt-warn-banner">
                <span class="pt-warn-glyph"><Icon name="mdi:alert" /></span>
                <div>
                  <strong>Idempotency note:</strong>
                  This authorization has been verified by the target agent. If your service agent re-checks
                  <code>verify()</code> after consumption, the backend will return <code>valid=true</code> again
                  (P25-001). Service agents must track local consumption to avoid re-doing paid work.
                </div>
              </div>

              <!-- Metadata grid -->
              <div class="pt-meta-grid">
                <div class="pt-meta-pair">
                  <span class="pt-meta-key">Authorization ID</span>
                  <span class="pt-meta-val pt-meta-val--code">
                    <code>{{ t.token_id }}</code>
                    <button class="pt-icon-btn" title="Copy authorization ID" @click.stop="copyText(t.token_id)">⎘</button>
                  </span>
                </div>
                <div class="pt-meta-pair">
                  <span class="pt-meta-key">Target agent</span>
                  <span class="pt-meta-val pt-meta-val--code">
                    <code>{{ t.target_agent_did }}</code>
                    <button class="pt-icon-btn" title="Copy DID" @click.stop="copyText(t.target_agent_did)">⎘</button>
                  </span>
                </div>
                <div class="pt-meta-pair">
                  <span class="pt-meta-key">Amount</span>
                  <span class="pt-meta-val pt-meta-val--strong">{{ formatAmount(t.amount) }} {{ localCurrency }}</span>
                </div>
                <div class="pt-meta-pair">
                  <span class="pt-meta-key">Status</span>
                  <span class="pt-meta-val">{{ t.status }}</span>
                </div>
                <div class="pt-meta-pair">
                  <span class="pt-meta-key">Created</span>
                  <span class="pt-meta-val">{{ formatAbs(t.created_at) }}</span>
                </div>
                <div class="pt-meta-pair">
                  <span class="pt-meta-key">Expires</span>
                  <span class="pt-meta-val">{{ formatAbs(t.expires_at) }} <span style="opacity:0.6">({{ timeUntilLabel(t.expires_at) }})</span></span>
                </div>
                <div v-if="t.settled_at" class="pt-meta-pair">
                  <span class="pt-meta-key">Settled</span>
                  <span class="pt-meta-val pt-meta-val--ok">{{ formatAbs(t.settled_at) }}</span>
                </div>
                <div v-if="t.contract_id" class="pt-meta-pair">
                  <span class="pt-meta-key">Contract</span>
                  <span class="pt-meta-val">
                    <a :href="`#/contracts?id=${t.contract_id}`" class="pt-link">#{{ t.contract_id }}</a>
                  </span>
                </div>
              </div>

              <!-- Actions -->
              <div class="pt-detail-actions">
                <button
                  v-if="t.status?.toUpperCase() === 'AUTHORIZED'"
                  class="pt-btn pt-btn--danger"
                  :disabled="releasingId === t.token_id"
                  @click="confirmRelease(t)"
                >
                  <span v-if="releasingId === t.token_id" class="pt-spinner"></span>
                  Release authorization
                </button>
                <span v-else class="pt-detail-action-note">
                  <template v-if="t.status?.toUpperCase() === 'SETTLED'">
                    ✓ The units already moved to the target — no further action.
                  </template>
                  <template v-else-if="t.status?.toUpperCase() === 'RELEASED'">
                    The caller released the authorization. The units held were returned.
                  </template>
                  <template v-else-if="t.status?.toUpperCase() === 'EXPIRED'">
                    TTL elapsed. The authorization can no longer be settled. The units held were returned.
                  </template>
                  <template v-else-if="t.status?.toUpperCase() === 'FAILED'">
                    Settlement attempt failed. The authorization's state is final.
                  </template>
                  <template v-else-if="t.status?.toUpperCase() === 'CONSUMED'">
                    Verified — settlement should follow. Read-only.
                  </template>
                  <template v-else-if="t.status?.toUpperCase() === 'SETTLING'">
                    Settlement in flight — backend processing async transfer.
                  </template>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="pt-footer">
          <span>
            Showing {{ tokens.length }} of the last 50 authorizations<span v-if="activeFilter"> · filtered to <strong>{{ activeFilter }}</strong></span>
          </span>
        </div>
      </template>
    </div>

    <!-- Themed release confirm -->
    <ConfirmActionModal
      :show="releaseModalOpen"
      title="// RELEASE PAYMENT AUTHORIZATION"
      :message="releasingToken
        ? `Release this <strong>AUTHORIZED</strong> payment, returning <strong>${formatAmount(releasingToken.amount)} ${localCurrency}</strong> to your agent? It will become RELEASED and cannot be settled.`
        : ''"
      tone="warn"
      warning="The target agent will be unable to settle this authorization if you release it. Only release if you know the work was not (or will not be) performed."
      warning-title="⚠ Caller-side release"
      confirm-text="Release Authorization"
      busy-text="Releasing…"
      :busy="releaseBusy"
      @close="cancelRelease"
      @confirm="executeRelease"
    />

    <!-- §FEPARITY-5 — themed settle confirm (the money move) -->
    <ConfirmActionModal
      :show="settleModalOpen"
      title="// SETTLE PAYMENT AUTHORIZATION"
      :message="verifyResult?.valid
        ? `Settle this authorization — <strong>${formatAmount(verifyResult.amount || 0)} ${localCurrency}</strong> moves from <code>${shortDid(verifyResult.caller_did || '')}</code> to this agent via the canonical transfer rail. Settle only after the paid work is done.`
        : ''"
      tone="warn"
      warning="Settlement is one-shot and final. A consumed token that settles twice does not pay twice — the rail is idempotent — but the caller sees the token as spent either way."
      warning-title="⚠ One settlement"
      confirm-text="Settle & collect"
      busy-text="Settling…"
      :busy="settleBusy"
      @close="settleModalOpen = false"
      @confirm="doSettle"
    />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * PaymentTokensPanel — A2A payment token UI panel for MyAgents.
 *
 * Build #2 (2026-05-07) — first frontend surface for f045.
 * Strategy doc: STRATEGY_2026-05-07_FRONTEND_BUILD_ROADMAP.md §4 Build #2.
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import {
  a2aPaymentService,
  type A2APaymentTokenItem,
  type TokenStatusFilter,
  type AuthorizeResponse,
  type VerifyResponse,
  type SettleResponse,
} from '@/services/api/a2aPayment'
import { useUIStore } from '@/stores/ui'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'

const props = defineProps<{
  /** The selected agent's DID. Required to scope token list. */
  agentDid: string | null | undefined
  /** Whether the agent JWT is currently active for this agent. */
  hasAgentToken: boolean
}>()

const uiStore = useUIStore()
const router = useRouter()
const { t } = useI18n()
import { useCurrency } from '@/composables/useCurrency'
const { localCurrency } = useCurrency()

const expanded = ref(false)  // Collapsed by default — match funding-section pattern
const tokens = ref<A2APaymentTokenItem[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
/** the token list could not be read (its error shows): no counts, no "No payment tokens yet" */
const listUnread = computed(() => !!error.value && tokens.value.length === 0)
const lastRefreshAt = ref<string>('')
const autoRefresh = ref(true)
const expandedId = ref<string | null>(null)

const releaseModalOpen = ref(false)
const releasingToken = ref<A2APaymentTokenItem | null>(null)
const releaseBusy = ref(false)
const releasingId = ref<string | null>(null)

const activeFilter = ref<TokenStatusFilter>(null)

// §FEPARITY-5 — authorize / verify / settle tool state
const showAuthorize = ref(false)
const showIncoming = ref(false)
const authTarget = ref('')
const authAmount = ref('')
const authTtl = ref(900)
const authContract = ref('')
const authBusy = ref(false)
const authError = ref('')
const authResult = ref<AuthorizeResponse | null>(null)
const incomingToken = ref('')
const verifyBusy = ref(false)
const verifyError = ref('')
const verifyResult = ref<VerifyResponse | null>(null)
const settleModalOpen = ref(false)
const settleBusy = ref(false)
const settleResult = ref<SettleResponse | null>(null)

const canAuthorize = computed(() =>
  authTarget.value.startsWith('did:') &&
  /^\d+(\.\d+)?$/.test(authAmount.value) && Number(authAmount.value) > 0 &&
  authTtl.value >= 60 && authTtl.value <= 3600 &&
  (!authContract.value || /^\d+$/.test(authContract.value)),
)

async function doAuthorize() {
  if (!canAuthorize.value || !props.hasAgentToken) {
    authError.value = props.hasAgentToken ? 'check the inputs' : 'Agent JWT not active — switch to this agent first.'
    return
  }
  authBusy.value = true
  authError.value = ''
  authResult.value = null
  try {
    authResult.value = await a2aPaymentService.authorize({
      target_agent_did: authTarget.value,
      amount: authAmount.value,   // string — backend Decimal precision (schemas.py rule)
      ttl_seconds: authTtl.value,
      ...(authContract.value ? { contract_id: Number(authContract.value) } : {}),
    })
    uiStore.showSuccess?.('Payment Authorized', `${formatAmount(authResult.value.amount)} ${localCurrency} held — copy the authorization now, it is shown once.`)
    await refresh()
  } catch (e: any) {
    authError.value = e?.response?.data?.detail || e?.message || 'authorize failed'
  } finally {
    authBusy.value = false
  }
}

async function doVerify() {
  if (!incomingToken.value) return
  verifyBusy.value = true
  verifyError.value = ''
  verifyResult.value = null
  settleResult.value = null
  try {
    verifyResult.value = await a2aPaymentService.verify({
      token: incomingToken.value,
      ...(props.agentDid ? { target_agent_did: props.agentDid } : {}),
    })
  } catch (e: any) {
    verifyError.value = e?.response?.data?.detail || e?.message || 'verify failed'
  } finally {
    verifyBusy.value = false
  }
}

async function doSettle() {
  if (!incomingToken.value || !props.hasAgentToken) {
    verifyError.value = 'Agent JWT not active — settle runs as the target agent.'
    settleModalOpen.value = false
    return
  }
  settleBusy.value = true
  try {
    settleResult.value = await a2aPaymentService.settle({ token: incomingToken.value, success: true })
    uiStore.showSuccess?.('Settled', `${formatAmount(settleResult.value.amount)} ${localCurrency} collected.`)
    settleModalOpen.value = false
    verifyResult.value = null
    incomingToken.value = ''
    await refresh()
  } catch (e: any) {
    verifyError.value = e?.response?.data?.detail || e?.message || 'settle failed'
    settleModalOpen.value = false
  } finally {
    settleBusy.value = false
  }
}

const FILTERS: { id: TokenStatusFilter; label: string; title: string }[] = [
  { id: null,           label: 'All',         title: 'All recent authorizations' },
  { id: 'AUTHORIZED',   label: 'Authorized',  title: 'Holds awaiting settlement' },
  { id: 'CONSUMED',     label: 'Consumed',    title: 'Verified — pending settle' },
  { id: 'SETTLED',      label: 'Settled',     title: 'Paid to the target' },
  { id: 'RELEASED',     label: 'Released',    title: 'Caller cancelled the hold' },
  { id: 'EXPIRED',      label: 'Expired',     title: 'TTL elapsed without settle' },
  { id: 'FAILED',       label: 'Failed',      title: 'Settlement error' },
]

let pollHandle: ReturnType<typeof setInterval> | null = null
let ttlTickHandle: ReturnType<typeof setInterval> | null = null

const _now = ref(Date.now())  // tick every second to drive TTL countdown reactivity

onMounted(() => {
  // Tick for TTL countdowns
  ttlTickHandle = setInterval(() => { _now.value = Date.now() }, 1000)
  // Visibility-guarded auto-refresh
  pollHandle = setInterval(() => {
    if (!autoRefresh.value) return
    if (document.visibilityState === 'hidden') return
    if (!expanded.value) return  // skip refresh while collapsed
    void refresh()
  }, 30_000)
})

onBeforeUnmount(() => {
  if (pollHandle) clearInterval(pollHandle)
  if (ttlTickHandle) clearInterval(ttlTickHandle)
})

watch(
  () => props.agentDid,
  () => {
    tokens.value = []
    error.value = null
    expandedId.value = null
    if (expanded.value) void refresh()
  },
)

watch(
  () => activeFilter.value,
  () => {
    if (expanded.value) void refresh()
  },
)

watch(
  () => expanded.value,
  (v) => {
    if (v && tokens.value.length === 0 && !loading.value) {
      void refresh()
    }
  },
)

async function refresh() {
  if (!props.agentDid) return
  if (!props.hasAgentToken) {
    error.value = 'Agent JWT not active. Switch to this agent to load its authorizations.'
    return
  }
  loading.value = true
  error.value = null
  try {
    const list = await a2aPaymentService.listMyTokens({
      status: activeFilter.value || undefined,
      limit: 50,
    })
    tokens.value = list
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Failed to load authorizations'
    error.value = msg
    uiStore.showError?.('Tokens', msg)
  } finally {
    loading.value = false
  }
}

function setFilter(id: TokenStatusFilter) {
  activeFilter.value = id
  expandedId.value = null
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) void refresh()
}

function confirmRelease(t: A2APaymentTokenItem) {
  releasingToken.value = t
  releaseModalOpen.value = true
}
function cancelRelease() {
  releaseModalOpen.value = false
  releasingToken.value = null
}
async function executeRelease() {
  const t = releasingToken.value
  if (!t) return
  releaseBusy.value = true
  releasingId.value = t.token_id
  try {
    await a2aPaymentService.releaseToken(t.token_id)
    uiStore.showSuccess?.('Authorization Released', `${formatAmount(t.amount)} ${localCurrency} held released back to agent.`)
    releaseModalOpen.value = false
    releasingToken.value = null
    await refresh()
  } catch (e: any) {
    uiStore.showError?.('Release Failed', e?.response?.data?.detail || e?.message || 'Unknown error')
  } finally {
    releaseBusy.value = false
    releasingId.value = null
  }
}

// ── Computed ────────────────────────────────────────────────────────────────

const statsByStatus = computed(() => {
  const acc: Record<string, number> = {
    AUTHORIZED: 0, CONSUMED: 0, SETTLING: 0, SETTLED: 0,
    RELEASED: 0, EXPIRED: 0, FAILED: 0,
  }
  for (const t of tokens.value) {
    const s = (t.status || '').toUpperCase()
    if (acc[s] !== undefined) acc[s]++
  }
  return acc
})

const activeAuthorizedCount = computed(() => statsByStatus.value.AUTHORIZED)
const hasActiveAuthorized = computed(() => statsByStatus.value.AUTHORIZED > 0)

// ── Helpers ─────────────────────────────────────────────────────────────────

function shortId(id: string): string {
  if (!id) return ''
  if (id.length <= 14) return id
  return `${id.slice(0, 6)}…${id.slice(-4)}`
}
function shortDid(did: string): string {
  if (!did) return ''
  if (did.length <= 30) return did
  return `${did.slice(0, 16)}…${did.slice(-6)}`
}
function formatAmount(amount: string | number): string {
  const n = Number(amount || 0)
  if (Number.isNaN(n)) return String(amount)
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 4 })
}

function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
function formatHHMMSS(d: Date): string {
  return d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}

function ttlLabel(expiresIso: string | null | undefined): string {
  if (!expiresIso) return ''
  const ms = new Date(expiresIso).getTime() - _now.value
  if (ms <= 0) return 'expired'
  if (ms < 60_000) return `${Math.floor(ms / 1_000)}s`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1_000)}s`
  return `${Math.floor(ms / 3_600_000)}h ${Math.floor((ms % 3_600_000) / 60_000)}m`
}
function timeUntilLabel(expiresIso: string | null | undefined): string {
  const ms = new Date(expiresIso || '').getTime() - _now.value
  if (ms <= 0) return 'expired'
  if (ms < 60_000) return `in ${Math.floor(ms / 1_000)}s`
  if (ms < 3_600_000) return `in ${Math.floor(ms / 60_000)}m`
  return `in ${Math.floor(ms / 3_600_000)}h`
}

function isExpiringSoon(t: A2APaymentTokenItem): boolean {
  if ((t.status || '').toUpperCase() !== 'AUTHORIZED') return false
  const ms = new Date(t.expires_at).getTime() - _now.value
  return ms < 60_000  // <1 min
}

function rowClass(t: A2APaymentTokenItem): string[] {
  const out: string[] = ['pt-row']
  const s = (t.status || '').toUpperCase()
  if (s === 'AUTHORIZED') out.push('pt-row--auth')
  else if (s === 'SETTLED') out.push('pt-row--ok')
  else if (s === 'CONSUMED' || s === 'SETTLING') out.push('pt-row--in-flight')
  else if (s === 'RELEASED' || s === 'EXPIRED') out.push('pt-row--done')
  else if (s === 'FAILED') out.push('pt-row--err')
  if (expandedId.value === t.token_id) out.push('pt-row--expanded')
  return out
}

function dotClass(t: A2APaymentTokenItem): string {
  const s = (t.status || '').toUpperCase()
  if (s === 'AUTHORIZED') return 'pt-status-dot--amber'
  if (s === 'CONSUMED' || s === 'SETTLING') return 'pt-status-dot--cyan'
  if (s === 'SETTLED') return 'pt-status-dot--ok'
  if (s === 'FAILED') return 'pt-status-dot--err'
  return 'pt-status-dot--muted'
}

function pillClass(t: A2APaymentTokenItem): string {
  const s = (t.status || '').toUpperCase()
  if (s === 'AUTHORIZED') return 'pt-pill--amber'
  if (s === 'CONSUMED' || s === 'SETTLING') return 'pt-pill--cyan'
  if (s === 'SETTLED') return 'pt-pill--ok'
  if (s === 'FAILED') return 'pt-pill--err'
  return 'pt-pill--muted'
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    uiStore.showSuccess?.('Copied', text.length > 40 ? text.slice(0, 40) + '…' : text)
  } catch {
    /* expected */
  }
}

function navigateToA2ADocs() {
  // §LEGALKIT (W7): the old route landed on the legal page's not-found branch; the A2A payment flow is documented on the public docs site.
  window.open('https://docs.theprotocol.cloud/learn/units-and-fees', '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
/* Section shell — mirrors funding-section so both panels coexist visually. */
.pt-section {
  margin-top: 14px;
  background: rgba(10, 13, 22, 0.5);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 8px;
  overflow: hidden;
}

.pt-header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.7rem 1rem;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  letter-spacing: 0.12em;
  font-weight: 600;
  color: rgba(var(--nc-primary-rgb), 0.85);
  background: rgba(var(--nc-primary-rgb), 0.04);
  transition: background 0.15s;
}
.pt-header:hover { background: rgba(var(--nc-primary-rgb), 0.08); }

.pt-glyph {
  font-size: 1rem;
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.pt-count {
  background: rgba(var(--nc-primary-rgb), 0.15);
  color: rgba(var(--nc-primary-rgb), 1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 0.65rem;
  font-weight: 700;
}
.pt-flex { flex: 1; }
.pt-hint-inline { font-size: 0.6rem; letter-spacing: 0.04em; color: var(--nc-text-muted); font-weight: 400; }
.pt-toggle {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  color: rgba(var(--nc-primary-rgb), 0.5);
}

.pt-body {
  padding: 0.85rem 1rem 1rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.pt-note {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.85rem 1rem;
  background: rgba(99, 179, 237, 0.06);
  border: 1px solid rgba(99, 179, 237, 0.2);
  border-radius: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.75);
}
.pt-note-icon {
  width: 18px; height: 18px;
  border-radius: 50%;
  background: rgba(99, 179, 237, 0.25);
  color: rgba(99, 179, 237, 1);
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700;
}

/* ── Toolbar ────────────────────────────────────────────── */
.pt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
  padding-bottom: 0.7rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.pt-toolbar-left, .pt-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.pt-toolbar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb), 0.55);
  font-weight: 600;
  margin-right: 0.25rem;
}
.pt-meta-key {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem;
  letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb), 0.6);
  font-weight: 600;
}
.pt-meta-val {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.85);
}
.pt-meta-val--code {
  display: inline-flex; align-items: center; gap: 0.4rem;
}
.pt-meta-val--code code {
  background: rgba(var(--nc-primary-rgb), 0.08);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
  word-break: break-all;
}
.pt-meta-val--strong {
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
}
.pt-meta-val--ok { color: var(--nc-success); }

/* ── §FEPARITY-5 tools (authorize / verify / settle) ────── */
.pt-tools { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.pt-form {
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 6px;
  background: rgba(var(--nc-primary-rgb), 0.04);
  padding: 0.75rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.pt-form-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.14em;
  font-weight: 700;
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.pt-form-hint {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: var(--nc-text-muted);
  line-height: 1.5;
  margin: 0;
}
.pt-form-hint code { background: rgba(var(--nc-primary-rgb), 0.1); padding: 0 4px; border-radius: 3px; }
.pt-form-row { display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
.pt-form-err {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: var(--nc-danger);
  margin: 0;
}
.pt-input {
  flex: 1;
  min-width: 0;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.9);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  padding: 6px 9px;
}
.pt-input--sm { flex: 0 1 140px; }
.pt-input--xs { flex: 0 0 110px; }
.pt-token-box {
  border: 1px solid rgba(255, 149, 0, 0.35);
  background: rgba(255, 149, 0, 0.06);
  border-radius: 6px;
  padding: 0.6rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.pt-token-box-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: var(--nc-warning);
}
.pt-token-box-row { display: flex; align-items: center; gap: 0.5rem; }
.pt-token-code {
  flex: 1;
  min-width: 0;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 4px;
  padding: 5px 8px;
  font-size: 0.68rem;
  word-break: break-all;
  color: rgba(255, 255, 255, 0.92);
}
.pt-verify-box {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  border-radius: 6px;
  padding: 0.55rem 0.75rem;
  border: 1px solid;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  line-height: 1.5;
}
.pt-verify-box--ok { border-color: rgba(0, 255, 136, 0.35); background: rgba(0, 255, 136, 0.05); color: rgba(255, 255, 255, 0.85); }
.pt-verify-box--bad { border-color: rgba(255, 51, 102, 0.4); background: rgba(255, 51, 102, 0.06); color: var(--nc-danger); }
.pt-verify-box code { background: rgba(var(--nc-primary-rgb), 0.1); padding: 0 4px; border-radius: 3px; }

/* ── Chips ──────────────────────────────────────────────── */
.pt-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--nc-primary-rgb), 0.04);
  cursor: pointer;
  transition: all 0.15s;
}
.pt-chip:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
}
.pt-chip--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  color: rgba(var(--nc-primary-rgb), 1);
}
.pt-chip-count {
  background: rgba(0, 0, 0, 0.35);
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 0.55rem;
}

/* ── Buttons ────────────────────────────────────────────── */
.pt-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: 'IBM Plex Mono', monospace;
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
.pt-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.pt-btn--ghost {
  background: transparent;
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.pt-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  color: rgba(var(--nc-primary-rgb), 1);
}
.pt-btn--danger {
  background: rgba(255, 51, 102, 0.12);
  border-color: rgba(255, 51, 102, 0.4);
  color: var(--nc-danger);
}
.pt-btn--danger:hover:not(:disabled) {
  background: rgba(255, 51, 102, 0.22);
  border-color: rgba(255, 51, 102, 0.6);
}

.pt-live-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--nc-text-muted);
  transition: background 0.15s, box-shadow 0.15s;
}
.pt-live-dot--on {
  background: var(--nc-success);
  box-shadow: 0 0 8px rgba(0, 255, 136, 0.6);
  animation: pt-pulse 2s ease-in-out infinite;
}
@keyframes pt-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(0, 255, 136, 0.6); }
  50% { box-shadow: 0 0 14px rgba(0, 255, 136, 0.9); }
}
.pt-spinner {
  width: 10px; height: 10px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: pt-spin 0.8s linear infinite;
}
@keyframes pt-spin { to { transform: rotate(360deg); } }

/* ── Stats ─────────────────────────────────────────────── */
.pt-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.6rem;
}
.pt-stat-cell {
  background: var(--nc-deep, #0a0d16);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 5px;
  padding: 0.6rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
}
.pt-stat-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.1;
  color: var(--nc-warning);
}
.pt-stat-value--cyan { color: rgba(var(--nc-primary-rgb), 1); }
.pt-stat-value--muted { color: rgba(255, 255, 255, 0.5); }
.pt-stat-value--bad { color: var(--nc-danger); }
.pt-stat-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
}

/* ── Error ─────────────────────────────────────────────── */
.pt-error {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.3);
  color: var(--nc-danger);
  padding: 0.5rem 0.85rem;
  border-radius: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
}
.pt-error span { flex: 1; min-width: 0; }

/* ── Skeleton ──────────────────────────────────────────── */
.pt-skeleton { display: flex; flex-direction: column; gap: 0.45rem; }
.pt-skel-row {
  height: 36px;
  border-radius: 5px;
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.05) 0%,
    rgba(var(--nc-primary-rgb), 0.12) 50%,
    rgba(var(--nc-primary-rgb), 0.05) 100%);
  background-size: 200% 100%;
  animation: pt-shimmer 1.4s linear infinite;
}
@keyframes pt-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* ── Empty ─────────────────────────────────────────────── */
.pt-empty {
  text-align: center;
  padding: 2rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.pt-empty-glyph { font-size: 1.8rem; opacity: 0.5; margin-bottom: 0.4rem; }
.pt-empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.25rem;
}
.pt-empty-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-text-muted);
  max-width: 36rem;
  margin-bottom: 0.6rem;
  line-height: 1.5;
}
.pt-empty-sub code {
  background: rgba(var(--nc-primary-rgb), 0.1);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.66rem;
}
.pt-link { color: rgba(var(--nc-primary-rgb), 0.95); text-decoration: underline; cursor: pointer; }

/* ── List rows ─────────────────────────────────────────── */
.pt-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  max-height: 28rem;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb), 0.2) transparent;
  padding-right: 0.25rem;
}
.pt-list::-webkit-scrollbar { width: 5px; }
.pt-list::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb), 0.25); border-radius: 3px; }

.pt-row {
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-left-width: 3px;
  border-radius: 5px;
  overflow: hidden;
  transition: background 0.15s;
}
.pt-row--auth     { border-left-color: var(--nc-warning); }
.pt-row--ok       { border-left-color: var(--nc-success); }
.pt-row--in-flight { border-left-color: rgba(var(--nc-primary-rgb), 0.7); }
.pt-row--done     { border-left-color: var(--nc-text-muted); opacity: 0.78; }
.pt-row--err      { border-left-color: var(--nc-danger); background: rgba(255, 51, 102, 0.04); }
.pt-row--expanded { background: rgba(var(--nc-primary-rgb), 0.08); }

.pt-row-head {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  color: inherit;
}
.pt-row-head:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.pt-row-head:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: -2px; }

.pt-status-dot {
  width: 7px; height: 7px; border-radius: 50%;
  flex-shrink: 0;
}
.pt-status-dot--amber { background: var(--nc-warning); }
.pt-status-dot--cyan  { background: rgba(var(--nc-primary-rgb), 1); }
.pt-status-dot--ok    { background: var(--nc-success); box-shadow: 0 0 6px rgba(0, 255, 136, 0.5); }
.pt-status-dot--err   { background: var(--nc-danger); }
.pt-status-dot--muted { background: var(--nc-text-muted); opacity: 0.5; }

.pt-row-token, .pt-row-target {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
}
.pt-row-arrow {
  color: rgba(var(--nc-primary-rgb), 0.5);
  font-size: 0.8rem;
}
.pt-row-spacer { flex: 1; }
.pt-row-amount {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
}
.pt-row-time, .pt-ttl {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
  white-space: nowrap;
}
.pt-ttl {
  color: var(--nc-warning);
}
.pt-ttl--urgent {
  color: var(--nc-danger);
  animation: pt-urgent 1s ease-in-out infinite;
}
@keyframes pt-urgent {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.pt-row-caret {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(var(--nc-primary-rgb), 0.6);
  margin-left: 0.4rem;
}

/* ── Pills ─────────────────────────────────────────────── */
.pt-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
  white-space: nowrap;
}
.pt-pill--amber { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }
.pt-pill--cyan  { background: rgba(var(--nc-primary-rgb), 0.1); color: rgba(var(--nc-primary-rgb), 1); border-color: rgba(var(--nc-primary-rgb), 0.3); }
.pt-pill--ok    { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.pt-pill--err   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger); border-color: rgba(255, 51, 102, 0.3); }
.pt-pill--muted { background: rgba(var(--nc-primary-rgb), 0.06); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--nc-primary-rgb), 0.18); }
.pt-pill--soft  { background: rgba(var(--nc-primary-rgb), 0.08); color: rgba(var(--nc-primary-rgb), 0.85); border-color: rgba(var(--nc-primary-rgb), 0.22); }

/* ── Detail panel ──────────────────────────────────────── */
.pt-detail {
  padding: 0.6rem 0.85rem 0.85rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.pt-warn-banner {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
  background: rgba(255, 149, 0, 0.08);
  border: 1px solid rgba(255, 149, 0, 0.3);
  border-radius: 5px;
  padding: 0.55rem 0.75rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(255, 149, 0, 0.95);
  line-height: 1.5;
}
.pt-warn-banner code {
  background: rgba(255, 149, 0, 0.15);
  padding: 1px 5px;
  border-radius: 3px;
}
.pt-warn-glyph { font-size: 0.95rem; line-height: 1.2; }

.pt-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.5rem 0.85rem;
}
.pt-meta-pair {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  min-width: 0;
}

.pt-detail-actions {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-wrap: wrap;
  padding-top: 0.4rem;
}
.pt-detail-action-note {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-text-muted);
  font-style: italic;
}

.pt-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--nc-primary-rgb), 0.7);
  font-family: monospace;
  font-size: 0.7rem;
  padding: 0 5px;
  cursor: pointer;
  transition: all 0.12s;
}
.pt-icon-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: rgba(var(--nc-primary-rgb), 1);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
}

.pt-footer {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
  padding-top: 0.4rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}

/* ── Responsive ────────────────────────────────────────── */
@media (max-width: 768px) {
  .pt-stats { grid-template-columns: repeat(2, 1fr); }
  .pt-toolbar { flex-direction: column; align-items: flex-start; }
  .pt-toolbar-right { width: 100%; justify-content: flex-end; }
  .pt-row-head { flex-wrap: wrap; gap: 0.4rem; }
  .pt-row-token, .pt-row-target { font-size: 0.65rem; }
}
</style>
