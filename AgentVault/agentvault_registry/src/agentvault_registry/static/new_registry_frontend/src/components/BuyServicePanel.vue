<!--
  §BUYSERVICE (2026-08-24) — buy an agent's service, by hand, and see the answer.

  Before this, the primary CTA on a paid agent routed to `/my-agents?hire=<did>`
  and NOTHING consumed `?hire=` (grep: zero hits) — on a phone it threw you into a
  desktop fleet view. This is the door that button always described: quote, one
  confirm, the call, the answer, a receipt.

  The registry places the A2A call, not the browser: the buyer's registry and the
  agent are different origins, and the payment token must never reach page JS.
  So this component owns no money logic — it renders `/a2a-payment/quote` and
  posts `/a2a-payment/buy`.
-->
<template>
  <div class="bsp" data-testid="bsp">
    <!-- ── no acting agent: say which thing is missing, never a blank panel ── -->
    <div v-if="noAgentReason" class="bsp-blocked" data-testid="bsp-blocked">
      {{ noAgentReason }}
    </div>

    <template v-else>
      <div v-if="loading" class="bsp-muted" data-testid="bsp-loading">
        {{ t('buy.pricing', 'Pricing this service…') }}
      </div>

      <div v-else-if="quoteError" class="bsp-blocked" data-testid="bsp-quote-error">
        {{ quoteError }}
      </div>

      <template v-else-if="quote">
        <!-- ── the price, in both currencies, with the rate stated ── -->
        <div class="bsp-price" data-testid="bsp-price">
          <template v-if="quote.payment_required">
            <span class="bsp-price-main" data-testid="bsp-price-yours">
              {{ quote.recommended_amount }} {{ quote.your_currency }}
            </span>
            <span v-if="!quote.same_currency" class="bsp-price-note" data-testid="bsp-price-card">
              {{ t('buy.cardCharges', 'card charges') }}
              {{ quote.price }} {{ quote.price_currency }}
              · {{ t('buy.rate', 'rate') }} {{ quote.rate }}
              <span v-if="rateAge" class="bsp-rate-age">({{ rateAge }})</span>
            </span>
            <span v-else class="bsp-price-note">{{ t('buy.perRequest', 'per request') }}</span>
          </template>
          <span v-else class="bsp-price-main bsp-price-main--free" data-testid="bsp-price-yours">
            {{ t('buy.free', 'No charge') }}
          </span>
        </div>

        <!-- Honesty: the agent re-prices at delivery, so this is indicative and the
             quoted number carries headroom. Saying so is cheaper than a refusal. -->
        <p v-if="quote.payment_required && !quote.same_currency" class="bsp-fineprint"
           data-testid="bsp-fineprint">
          {{ tp('buy.fineprint',
                'Converted at the live rate and rounded up by {pct}% so a moving rate does not underpay the agent. It prices the payment again on delivery; anything unused is not charged.',
                { pct: quote.headroom_pct }) }}
        </p>

        <label class="bsp-label" for="bsp-prompt">{{ t('buy.ask', 'What do you want to ask it?') }}</label>
        <textarea id="bsp-prompt" v-model="prompt" class="bsp-input" rows="2"
                  :placeholder="promptPlaceholder" data-testid="bsp-prompt"></textarea>

        <!-- §FOREIGNACT — a purchase debits the ACTING agent on ITS registry. -->
        <ActingContextNotice strong />

        <div class="bsp-actions">
          <button class="bsp-go" type="button" :disabled="busy || !quote.can_buy || !prompt.trim()"
                  @click="doBuy" data-testid="bsp-go">
            {{ busy
              ? t('buy.working', 'Working…')
              : quote.payment_required
                ? tp('buy.buy', 'Buy · {amt} {ccy}', { amt: quote.recommended_amount, ccy: quote.your_currency })
                : t('buy.call', 'Call this agent') }}
          </button>
          <span v-if="quote.issuer" class="bsp-issuer" data-testid="bsp-issuer">
            {{ t('buy.paidFrom', 'paid from') }} {{ issuerHost }}
          </span>
        </div>

        <!-- ── the answer ── -->
        <div v-if="result" class="bsp-result" data-testid="bsp-result">
          <div class="bsp-result-head">{{ t('buy.answer', 'Answer') }}</div>
          <div v-if="resultSummary" class="bsp-result-summary" data-testid="bsp-result-summary">
            {{ resultSummary }}
          </div>
          <pre class="bsp-result-raw" data-testid="bsp-result-raw">{{ resultPretty }}</pre>
        </div>

        <!-- ── the receipt: what moved, where, and whether it actually settled ── -->
        <div v-if="receipt" class="bsp-receipt" data-testid="bsp-receipt">
          <span v-if="receipt.paid_amount">
            {{ t('buy.paid', 'Paid') }} <strong>{{ receipt.paid_amount }} {{ receipt.paid_currency }}</strong>
            <template v-if="receipt.price && receipt.price_currency !== receipt.paid_currency">
              ({{ receipt.price }} {{ receipt.price_currency }} @ {{ receipt.rate }})
            </template>
          </span>
          <span v-if="receipt.settlement_status" :class="settlementClass" data-testid="bsp-settlement">
            · {{ settlementLabel }}
          </span>
          <span v-if="receipt.token_id" class="bsp-token">· {{ t('buy.token', 'authorization') }} {{ receipt.token_id.slice(0, 8) }}</span>
          <button v-if="canBuyAgain" class="bsp-again" type="button" @click="doBuy" data-testid="bsp-again">
            {{ t('buy.again', 'Buy again') }}
          </button>
        </div>

        <div v-if="buyError" class="bsp-error" data-testid="bsp-error">{{ buyError }}</div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { useAuthStore } from '@/stores/auth'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'
import apiClient from '@/services/api/client'

const { t, tp } = useI18n() as any

const props = defineProps<{ did: string; agentName?: string }>()

const { noAgentReason, chooseReason, restoreActing } = usePocketAgent()
const auth = useAuthStore()

/** V0641 (agentvault2-66's review of be05537f): the door acts as the store's acting agent. When none is acting and none
 *  can be chosen for the member (several of theirs, none chosen) or the sign-in failed, it says why and calls nothing:
 *  a quote or a buy sent without an agent's token answered 401, whose words were shown as the reason. */
function notActingReason(): string {
  return noAgentReason.value || chooseReason.value
    || t('buy.signInFailed', 'Could not sign in as your agent right now. Try again in a moment.')
}

const loading = ref(false)
const busy = ref(false)
const quote = ref<any>(null)
const quoteError = ref('')
const buyError = ref('')
const result = ref<any>(null)
const receipt = ref<any>(null)
const prompt = ref('')

const promptPlaceholder = computed(() =>
  t('buy.placeholder', 'e.g. weather in Berlin'))

const issuerHost = computed(() => {
  try { return new URL(quote.value?.issuer || '').hostname } catch { return quote.value?.issuer || '' }
})

const rateAge = computed(() => {
  const iso = quote.value?.rate_as_of
  if (!iso) return ''
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (secs < 90) return t('buy.rateFresh', 'just now')
  return tp('buy.rateAge', '{m} min old', { m: String(Math.round(secs / 60)) })
})

/** The showcase agents answer with a human `summary`; surface it above the raw
 *  envelope so a person is not asked to read JSON-RPC to learn the weather. */
const resultSummary = computed(() => {
  try {
    const arts = result.value?.result?.artifacts || []
    for (const a of arts) {
      const s = a?.data?.summary
      if (typeof s === 'string' && s.trim()) return s
    }
  } catch { /* fall through to the raw view */ }
  return ''
})
const resultPretty = computed(() => {
  try { return JSON.stringify(result.value, null, 2).slice(0, 4000) } catch { return '' }
})

const canBuyAgain = computed(() => !!result.value && !busy.value)

const settlementLabel = computed(() => {
  const s = receipt.value?.settlement_status
  if (s === 'settled') return t('buy.settled', 'settled')
  if (s === 'settling') return t('buy.settling', 'settling…')
  if (s === 'released') return t('buy.released', 'nothing charged')
  if (s === 'consumed') return t('buy.unsettled', 'not settled yet')
  return t('buy.settleFailed', 'NOT PAID — retry settlement')
})
const settlementClass = computed(() =>
  ['settled', 'settling', 'released'].includes(receipt.value?.settlement_status)
    ? 'bsp-ok' : 'bsp-warn')

async function loadQuote() {
  quoteError.value = ''
  quote.value = null
  loading.value = true
  try {
    if (!(await restoreActing())) { quoteError.value = notActingReason(); return }
    const { data } = await apiClient.get('/a2a-payment/quote', {
      params: { target_agent_did: props.did },
    })
    quote.value = data
    if (!data.can_buy && data.reason) quoteError.value = data.reason
  } catch (e: any) {
    // An error is not an empty state: say the price is unknown, never imply free.
    quoteError.value = e?.response?.data?.detail
      || t('buy.quoteFailed', 'Could not price this service right now.')
  } finally {
    loading.value = false
  }
}

/** D6-839 (agentvault2-5b, 2026-10-25): /a2a-payment/settle answers "settling" at once and settles in a background task
 *  (both of the suite's purchases on sbx-alpha settled within half a second), and /buy hands that word on, so the receipt
 *  read "settling…" for as long as the page stayed open. After such an answer the panel reads the token's own state from
 *  /a2a-payment/my-tokens until it is final (settled, failed, released, expired), about 20 s at most. A read that fails
 *  changes nothing (the next one may answer); a newer purchase takes the receipt and this one stops. */
const SETTLE_READS_MS = [500, 1000, 1500, 2000, 3000, 4000, 4000, 4000]
let settleSeq = 0
async function followSettlement(tokenId: string) {
  const seq = ++settleSeq
  const ours = () => seq === settleSeq && receipt.value?.token_id === tokenId
  for (const wait of SETTLE_READS_MS) {
    await new Promise((r) => setTimeout(r, wait))
    if (!ours()) return
    try {
      const { data } = await apiClient.get('/a2a-payment/my-tokens', { params: { limit: 20 } })
      const row = (Array.isArray(data) ? data : []).find((x: any) => x?.token_id === tokenId)
      const st = String(row?.status || '').toLowerCase()
      if (!['settled', 'failed', 'released', 'expired'].includes(st)) continue
      if (!ours()) return
      receipt.value = { ...receipt.value, settlement_status: st }
      if (st === 'failed' || st === 'expired') {
        buyError.value = tp('buy.settleFailedAfter',
          'Service delivered, but settlement failed. You owe this agent: retry settle on authorization {id}.',
          { id: tokenId.slice(0, 8) })
      }
      return
    } catch { /* a failed read leaves the receipt as it was */ }
  }
}

async function doBuy() {
  if (busy.value) return
  busy.value = true
  buyError.value = ''
  result.value = null
  receipt.value = null
  settleSeq++   // a purchase still being followed hands the receipt over
  try {
    if (!(await restoreActing())) { buyError.value = notActingReason(); return }
    const { data } = await apiClient.post('/a2a-payment/buy', {
      target_agent_did: props.did,
      text: prompt.value.trim(),
    })
    receipt.value = data
    if (data.ok) {
      result.value = data.result
      // A delivered-but-unsettled purchase must not read as clean success.
      if (data.error) buyError.value = data.error
      if (data.settlement_status === 'settling' && data.token_id) void followSettlement(String(data.token_id))
    } else {
      buyError.value = data.error || t('buy.failed', 'The agent did not deliver.')
    }
  } catch (e: any) {
    buyError.value = e?.response?.data?.detail
      || t('buy.failed', 'The agent did not deliver.')
  } finally {
    busy.value = false
  }
}

onMounted(loadQuote)
watch(() => props.did, loadQuote)
// the member chose an agent in the switcher after the door asked for one: price it now
watch(() => (auth as any).activeAgent?.did, (did) => { if (did && !quote.value && !loading.value) loadQuote() })
</script>

<style scoped>
.bsp { margin-top: 0.7rem; }
.bsp-blocked, .bsp-muted {
  font-size: 0.76rem; color: var(--nc-text-muted, #94a3b8); line-height: 1.5;
}
.bsp-price { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.bsp-price-main {
  font-size: 1.02rem; font-weight: 700; font-variant-numeric: tabular-nums;
  color: rgba(var(--nc-primary-rgb), 0.98);
}
.bsp-price-main--free { color: var(--nc-text-muted, #94a3b8); font-weight: 600; }
.bsp-price-note { font-size: 0.72rem; color: var(--nc-text-muted, #94a3b8); }
.bsp-rate-age { opacity: 0.75; }
.bsp-fineprint {
  font-size: 0.7rem; line-height: 1.45; color: var(--nc-text-muted, #94a3b8);
  margin: 0.35rem 0 0.5rem;
}
.bsp-label {
  display: block; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--nc-text-muted, #94a3b8); margin: 0.55rem 0 0.25rem;
}
.bsp-input {
  width: 100%; box-sizing: border-box; resize: vertical;
  font-size: 16px; /* iOS refuses to not zoom below 16px */
  padding: 0.45rem 0.6rem; border-radius: 0.35rem;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  background: rgba(0, 0, 0, 0.18); color: inherit;
}
.bsp-actions { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; margin-top: 0.55rem; }
.bsp-go {
  min-height: 44px; padding: 0.45rem 1rem; border-radius: 0.35rem;
  font-size: 0.82rem; font-weight: 600; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.5);
  background: rgba(var(--nc-primary-rgb), 0.18); color: rgba(var(--nc-primary-rgb), 0.98);
}
.bsp-go:disabled { opacity: 0.45; cursor: not-allowed; }
.bsp-issuer { font-size: 0.68rem; color: var(--nc-text-muted, #94a3b8); }
.bsp-result { margin-top: 0.7rem; }
.bsp-result-head {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--nc-text-muted, #94a3b8); margin-bottom: 0.3rem;
}
.bsp-result-summary { font-size: 0.92rem; font-weight: 600; margin-bottom: 0.4rem; }
.bsp-result-raw {
  max-height: 190px; overflow: auto; font-size: 0.68rem; line-height: 1.45;
  padding: 0.5rem 0.6rem; border-radius: 0.35rem; margin: 0;
  background: rgba(0, 0, 0, 0.28); color: var(--nc-text-muted, #cbd5e1);
}
.bsp-receipt {
  margin-top: 0.6rem; font-size: 0.72rem; display: flex; gap: 0.35rem;
  align-items: center; flex-wrap: wrap; color: var(--nc-text-muted, #94a3b8);
  font-variant-numeric: tabular-nums;
}
.bsp-ok { color: #4ade80; }
.bsp-warn { color: #fbbf24; font-weight: 600; }
.bsp-token { opacity: 0.7; }
.bsp-again {
  min-height: 32px; padding: 0.2rem 0.6rem; border-radius: 0.3rem; cursor: pointer;
  font-size: 0.72rem; border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
  background: transparent; color: rgba(var(--nc-primary-rgb), 0.92);
}
.bsp-error { margin-top: 0.55rem; font-size: 0.74rem; color: #fbbf24; line-height: 1.45; }
</style>
