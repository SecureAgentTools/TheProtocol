<!-- POCKET · Send + Receive sheets (2026-07-08). Send = pick a credentialed agent → recipient DID +
     amount → smartSend DRY-RUN route preview (local / cross-registry / FX + fee) → confirm. Rides the
     existing /teg/send rail (Δ=0). Receive = copy/share/QR your agent's DID. -->
<template>
  <transition name="ps-sheet">
    <div v-if="open" class="ps-scrim" @click.self="close">
      <div ref="trapEl" class="ps-sheet" role="dialog" aria-modal="true" :aria-label="mode === 'send' ? t('pocket.send.title', 'Send') : t('pocket.send.receiveTitle', 'Receive')">
        <div class="ps-grip" aria-hidden="true"></div>

        <!-- SEND -->
        <template v-if="mode === 'send'">
          <h2 class="ps-title"><Icon name="mdi:send" /> {{ t('pocket.send.title', 'Send') }}</h2>

          <label class="ps-lab">{{ t('pocket.send.fromAgent', 'From agent') }}</label>
          <!-- §OURSTATE-6 — choosing here CHANGES the acting agent immediately.
               Before, this select was a sheet-local ref while the notice below
               read the store, so the banner and the money could name different
               agents; and the ref initialised once, so switching agents in the
               header never reached it. One field now feeds the label, the
               currency and the route. -->
          <select v-model="fromDid" class="ps-in" :disabled="sending" data-testid="ps-from" :aria-label="t('pocket.send.fromAgent', 'From agent')"
                  @change="adoptFrom">
            <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shorten(a.did) }}</option>
          </select>
          <p v-if="!credAgents.length" class="ps-note ps-warn">{{ noAgentReason }}</p>
          <p v-if="fromSwitching" class="ps-note" data-testid="ps-from-switching">
            {{ t('pocket.send.switchingAgent', 'Switching acting agent…') }}</p>

          <label class="ps-lab">{{ t('pocket.send.toDid', 'To (recipient DID)') }}</label>
          <input v-model.trim="toDid" class="ps-in ps-mono" placeholder="did:theprotocol:…" :disabled="sending" :aria-label="t('pocket.send.toDid', 'To (recipient DID)')" />
          <p v-if="toDidWarn" class="ps-note ps-warn" data-testid="ps-did-warn">{{ toDidWarn }}</p>
          <button v-if="nfc.supported.value" class="ps-nfc" :class="{ live: nfc.scanning.value }" :disabled="sending" @click="tapToPay">
            <Icon name="mdi:contactless-payment" />
            {{ nfc.scanning.value ? t('pocket.nfc.holdNear', 'Hold near the payment tag…') : t('pocket.send.tapToPay', 'Tap to pay (NFC)') }}
          </button>

          <label class="ps-lab">{{ t('pocket.stake.amount', 'Amount') }}</label>
          <div class="ps-amt-row">
            <input v-model="amount" class="ps-in ps-amt" type="text" inputmode="decimal" placeholder="0.00" :disabled="sending"
                   :aria-label="t('pocket.stake.amount', 'Amount')" :aria-invalid="!!amountWarn" />
            <span class="ps-amt-ccy">{{ ccy }}</span>
          </div>
          <p v-if="amountWarn" class="ps-note ps-warn" data-testid="ps-amount-warn">{{ amountWarn }}</p>

          <input v-model.trim="memo" class="ps-in" :placeholder="t('pocket.send.memo', 'Memo (optional)')" maxlength="200" :disabled="sending" />

          <!-- route preview -->
          <div v-if="preview" class="ps-route" :class="{ err: preview.error }">
            <template v-if="!preview.error">
              <div class="ps-route-line"><span>{{ t('pocket.send.route', 'Route') }}</span><strong>{{ routeLabel }}</strong></div>
              <div class="ps-route-line" v-if="preview.receiver_registry && preview.method !== 'local'">
                <span>{{ t('pocket.send.theirRegistry', 'Their registry') }}</span><strong>{{ preview.receiver_registry }}</strong></div>
              <div class="ps-route-line" v-if="preview.method === 'fx' && preview.fx_quote">
                <span>{{ t('pocket.send.fxRate', 'FX rate') }}</span><strong>{{ preview.fx_quote.rate }} ({{ ((+preview.fx_quote.fee_rate || 0) * 100).toFixed(1) }}% {{ t('pocket.send.feeWord', 'fee') }})</strong></div>
              <div class="ps-route-line" v-if="previewRecv">
                <span>{{ t('pocket.send.theyReceive', 'They receive') }}</span><strong>{{ preview.method === 'local' ? '' : '≈ ' }}{{ previewRecv.amt }} {{ previewRecv.ccy }}</strong></div>
              <div class="ps-route-line" v-if="previewCost">
                <span>{{ t('pocket.send.youPay', 'You pay') }}</span><strong>≈ {{ previewCost }} {{ ccy }} <small class="ps-fee-note">{{ t('pocket.send.networkFee', '(0.5% network fee)') }}</small></strong></div>
            </template>
            <div v-else class="ps-route-err">{{ preview.error }}</div>
          </div>

          <!-- §FOREIGNACT — a send from a foreign agent debits THAT registry's
               balance in THAT registry's currency. Say so before the confirm. -->
          <ActingContextNotice strong />

          <!-- §OURSTATE-6 THE PRE-SEND ASSERTION. Four facts in one place: who
               pays, from which registry, in what currency, and what actually
               arrives. Both of the 2026-08-24 mis-sends would have been visible
               here before the money moved. -->
          <div v-if="confirmReady" class="ps-assert" data-testid="ps-assert">
            <div class="ps-assert-line">
              <span>{{ t('pocket.send.assertWho', 'Paying as') }}</span>
              <strong data-testid="ps-assert-who">{{ fromName }}</strong>
            </div>
            <div class="ps-assert-line">
              <span>{{ t('pocket.send.assertWhere', 'On') }}</span>
              <strong data-testid="ps-assert-where">{{ fromRegistryLabel }}</strong>
            </div>
            <div class="ps-assert-line">
              <span>{{ t('pocket.send.assertDebit', 'Debited') }}</span>
              <strong data-testid="ps-assert-debit">{{ amountText }} {{ ccy }}</strong>
            </div>
            <div class="ps-assert-line" v-if="previewRecv">
              <span>{{ t('pocket.send.assertArrives', 'They receive') }}</span>
              <strong data-testid="ps-assert-arrives"
                      :class="{ 'ps-assert-diff': arrivesDiffers }">
                <template v-if="previewRecv.amt">{{ preview.method === 'local' ? '' : '≈ ' }}{{ previewRecv.amt }} {{ previewRecv.ccy }}</template>
                <template v-else>{{ tp('pocket.send.arrivesAtRate', 'in {ccy}, at the rate when it is sent', { ccy: previewRecv.ccy }) }}</template></strong>
            </div>
            <p v-if="convertedNote" class="ps-assert-warn" data-testid="ps-assert-warn">
              {{ convertedNote }}</p>
          </div>

          <div class="ps-actions">
            <button class="ps-btn ps-ghost" :disabled="sending" @click="close">{{ t('common.cancel', 'Cancel') }}</button>
            <button v-if="!confirmReady" class="ps-btn ps-primary" :disabled="!canPreview || previewing" @click="doPreview">
              {{ previewing ? t('pocket.send.checking', 'Checking…') : t('pocket.send.preview', 'Preview') }}
            </button>
            <button v-else class="ps-btn ps-send" :disabled="sending || sentOk" @click="doSend">
              <Icon :name="lock.enabled.value ? 'mdi:fingerprint' : 'mdi:check-circle'" />
              {{ sending ? (verifying ? t('pocket.send.confirmBio', 'Confirm biometrics…') : t('pocket.send.sending', 'Sending…'))
                 : lock.enabled.value ? tp('pocket.send.confirmSend', 'Confirm & send {amount} {ccy}', { amount: amountText, ccy })
                 : tp('pocket.send.sendAmount', 'Send {amount} {ccy}', { amount: amountText, ccy }) }}
            </button>
          </div>
          <p v-if="result" class="ps-result" :class="result.ok ? 'ok' : result.unknown ? 'unknown' : 'bad'" :data-testid="result.unknown ? 'ps-unknown-outcome' : undefined">{{ result.msg }}</p>
          <p v-if="nfcMsg" class="ps-note">{{ nfcMsg }}</p>
        </template>

        <!-- RECEIVE -->
        <template v-else>
          <h2 class="ps-title"><Icon name="mdi:arrow-down" /> {{ t('pocket.send.receiveTitle', 'Receive') }}</h2>
          <p class="ps-lab">{{ t('pocket.send.shareRequest', 'Share this payment request — QR, NFC tag, or link') }}</p>
          <select v-if="credAgents.length > 1" v-model="fromDid" class="ps-in" :aria-label="t('pocket.send.receiveAgent', 'Receiving agent')">
            <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shorten(a.did) }}</option>
          </select>
          <label class="ps-lab">{{ t('pocket.send.requestAmount', 'Request amount (optional)') }}</label>
          <div class="ps-amt-row">
            <input v-model="reqAmount" class="ps-in ps-amt" type="text" inputmode="decimal" :placeholder="t('pocket.send.anyAmount', 'any amount')" @change="makeQr" />
            <span class="ps-amt-ccy">{{ ccy }}</span>
          </div>
          <div v-if="qrDataUrl" class="ps-qr"><img :src="qrDataUrl" :alt="t('pocket.send.qrAlt', 'Payment request QR code')" /></div>
          <button v-if="nfc.supported.value" class="ps-nfc" :disabled="nfc.writing.value || !fromDid" @click="writeTag">
            <Icon name="mdi:contactless-payment" />
            {{ nfc.writing.value ? t('pocket.nfc.holdWritable', 'Hold a writable NFC tag to the phone…') : t('pocket.send.writeTag', 'Write to NFC tag') }}
          </button>
          <div class="ps-did-box ps-mono">{{ fromDid || '—' }}</div>
          <p v-if="nfcMsg" class="ps-note">{{ nfcMsg }}</p>
          <div class="ps-actions">
            <button class="ps-btn ps-ghost" @click="doCopy"><Icon name="mdi:content-copy" /> {{ copied ? t('pocket.common.copied', 'Copied') : t('cta.copy', 'Copy') }}</button>
            <button v-if="canShare" class="ps-btn ps-primary" @click="doShare"><Icon name="mdi:share-variant" /> {{ t('cta.share', 'Share') }}</button>
          </div>
        </template>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { useFocusTrap } from '@/composables/useFocusTrap'
import Icon from '@/components/Icon.vue'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'
import { useAuthStore } from '@/stores/auth'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { isDidLike, isUuidLike } from '@/services/bridge/identity'
import { tegApi } from '@/services/api/teg'
import { useCurrency } from '@/composables/useCurrency'
import { usePocketLock } from '@/composables/usePocketLock'
import { usePocketNfc, buildPayUri } from '@/composables/usePocketNfc'
import { useI18n } from '@/composables/useI18n'
import { typedAmount } from '@/services/money/typedAmount'
import { answeredAgain, failedSendOutcome, SendKey, sendReference } from '@/services/money/sendOutcome'
import { wholeLedgerRefusalSentence } from '@/services/api/ledgerRefusal'
import { sendArrival } from '@/services/money/sendArrival'
import { newIdempotencyKey } from '@/services/api/idempotencyKey'

const { t, tp } = useI18n()


// §POCKETBRIDGE5 W-D — the dialog role was already declared; the trap makes it TRUE:
// focus enters on open, Tab cycles inside, and RETURNS to the opener on close.
const trapEl = ref<HTMLElement | null>(null)
const props = defineProps<{ open: boolean; mode: 'send' | 'receive'; ccy?: string
  initialTo?: string; initialAmount?: string; initialMemo?: string }>()
useFocusTrap(trapEl, { activeWhen: computed(() => props.open) })
/* `sent` carries the transaction reference. §OURSTATE-5a needs it: a priced
   first contact is proved by a transfer that already happened, and the proof
   is the ref. Additive — existing listeners that take no argument are
   unaffected. */
/* `sent` carries the whole receipt, not just a ref: §OURSTATE-5a needs the
   reference, and §OURSTATE-6 needs the amounts BOTH sides saw so the thread can
   post a receipt card that says what actually arrived. Additive — listeners
   that take fewer arguments are unaffected. */
export interface SentReceipt {
  ref?: string
  method?: string
  amount?: string
  currency?: string
  receivedAmount?: string | null
  receivedCurrency?: string | null
  toDid?: string
  fromDid?: string
}
const emit = defineEmits<{ (e: 'close'): void; (e: 'sent', r?: SentReceipt | string): void }>()

const auth = useAuthStore()
const ccy = computed(() => props.ccy || currentOwnCurrency())
const shorten = (s: string) => !s ? '—' : s.length > 28 ? s.slice(0, 15) + '…' + s.slice(-6) : s

// agents that have stored credentials (can act / receive) — §POCKETBRIDGE #PK3:
// the ONE shared brain, so the sealed-vault distinction exists everywhere at once.
const { credAgents, noAgentReason, ensureAgentFor } = usePocketAgent()

const fromDid = ref('')
const toDid = ref('')
const amount = ref('')
const memo = ref('')
const lock = usePocketLock()
const nfc = usePocketNfc()
const nfcMsg = ref('')
const reqAmount = ref('')  // optional amount on a payment REQUEST (receive mode)
const previewing = ref(false)
const sending = ref(false)
const verifying = ref(false)
const preview = ref<any>(null)
const result = ref<{ ok: boolean; msg: string; unknown?: boolean } | null>(null)
// §FESUITE (2026-10-05): one Idempotency-Key per request (this recipient, amount and memo). A send that got no answer, or a
// 5xx, may have gone through: it says so, never "Send failed", and pressing again asks once more with the SAME key, which
// the server answers from its claim instead of paying twice. A success or a refusal ends the request.
const sendKey = new SendKey(newIdempotencyKey)
const copied = ref(false)
const qrDataUrl = ref('')
const canShare = typeof (navigator as any).share === 'function'

/* §POCKETBRIDGE #PK20 — the ONE identity classifier on the pay target (§R9:
   an aggregate UUID once reached a treasury dialog wearing a DID's clothes).
   A UUID is refused WITH A REASON; only a real did:… can be previewed. */
/* §FESUITE — the amount the server receives: typedAmount refuses what Number() waved through ("1e309" is
   Infinity, "0x10" is 16) and reads "1,5" as one and a half. */
const amountText = computed(() => typedAmount(amount.value))
const amountWarn = computed(() => (String(amount.value).trim() && !amountText.value)
  ? t('pocket.common.amountWarn', 'Not an amount: digits with one decimal point, more than zero.') : '')
const canPreview = computed(() => !!fromDid.value && isDidLike(toDid.value) && !!amountText.value)
const toDidWarn = computed(() => {
  const v = toDid.value
  if (!v) return ''
  if (isUuidLike(v)) return t('pocket.send.uuidWarn', 'That looks like an internal record id (UUID), not an agent DID — payments need a did:… address.')
  return ''
})
const confirmReady = computed(() => !!preview.value && !preview.value.error)
const routeLabel = computed(() => {
  const m = (preview.value?.method || preview.value?.route || 'local').toString()
  const map: Record<string, string> = {
    local: t('pocket.send.routeLocal', 'LOCAL'),
    '2pc': t('pocket.send.routeXreg', 'CROSS-REGISTRY'),
    async: t('pocket.send.routeXregAsync', 'CROSS-REGISTRY (async)'),
    fx: t('pocket.send.routeFx', 'CROSS-FRAME FX'),
  }
  return map[m] || m.toUpperCase()
})
// what arrives, in the unit it arrives in (services/money/sendArrival.ts; an FX route without a quote names no number)
const previewRecv = computed(() => sendArrival(preview.value))
/* Sender-side cost line for LOCAL routes (base 0.5%, velocity-scaled — the
 * preview says "≈" and the ledger is the truth). */
const previewCost = computed(() => {
  const p: any = preview.value || {}
  if (p.method !== 'local') return null
  const n = Number(p.amount || 0)
  return n ? (n * 1.005).toFixed(4) : null
})

function reset() { preview.value = null; result.value = null }
watch([toDid, amount, fromDid, memo], reset)

const ensureAgent = () => ensureAgentFor(fromDid.value)

/* §OURSTATE-6 — the picker is authoritative in BOTH directions. Choosing an
   agent here makes it the ACTING agent immediately, so the notice, the
   currency and the route cannot describe a different agent than the one the
   money leaves. Before this, `fromDid` was a sheet-local ref: the label read
   the store, the routing read the ref, and they disagreed exactly when someone
   switched agents between opens. */
const fromSwitching = ref(false)
async function adoptFrom() {
  if (!fromDid.value) return
  fromSwitching.value = true
  try { await ensureAgentFor(fromDid.value) } finally { fromSwitching.value = false }
}

const fromName = computed(() => {
  const a = credAgents.value.find(x => x.did === fromDid.value)
  return a?.name || (fromDid.value ? shorten(fromDid.value) : '—')
})
const fromRegistryLabel = computed(() => {
  const a: any = credAgents.value.find(x => x.did === fromDid.value)
  const u = a?.registry_url || (auth as any).activeAgentRegistryUrl || ''
  // The HOSTNAME, never the whole URL: `URL.host` carries the port and the
  // §BLOGREFINE hostLabel bug came from exactly that.
  try { return u ? new URL(u).hostname : t('pocket.send.thisRegistry', 'this registry') }
  catch { return u || t('pocket.send.thisRegistry', 'this registry') }
})
/* Does the recipient get a DIFFERENT unit than the one you are debited? That
   is the sentence the 102 BVT -> 85.71 AVT send never showed. */
/* Narrowed in script, not in the template: a `v-if` cannot narrow, which is
   how two type errors arrived with this block (the ratchet caught them). */
const convertedNote = computed<string | null>(() => {
  const r: any = previewRecv.value
  if (!arrivesDiffers.value || !r) return null
  if (!r.amt) return tp('pocket.send.assertConvertedAtRate',
            'This crosses frames: {a} {b} leaves you and arrives as {d}, at the rate when it is sent.',
            { a: amountText.value, b: ccy.value, d: r.ccy })
  return tp('pocket.send.assertConverted',
            'This crosses frames: {a} {b} leaves you and about {c} {d} arrives.',
            { a: amountText.value, b: ccy.value, c: r.amt, d: r.ccy })
})

const arrivesDiffers = computed(() => {
  const r: any = previewRecv.value
  if (!r?.ccy) return false
  return String(r.ccy).toUpperCase() !== String(ccy.value).toUpperCase()
})

async function doPreview() {
  if (!canPreview.value) return
  previewing.value = true; result.value = null
  try {
    if (!await ensureAgent()) { preview.value = { error: t('pocket.send.authFailed', 'Could not authenticate as that agent.') }; return }
    const r = await tegApi.smartSend({ receiver_did: toDid.value, amount: String(amountText.value), message: memo.value || undefined, dry_run: true })
    preview.value = r
  } catch (e: any) {
    preview.value = { error: e?.response?.data?.detail || e?.message || t('pocket.send.previewFailed', 'Preview failed') }
  } finally { previewing.value = false }
}

/* §FESUITE — one press moves value once: a press while the first is in flight, or in the second between the
   success and the sheet closing, is refused here as well as by the disabled button. */
const sentOk = computed(() => result.value?.ok === true)
async function doSend() {
  if (!confirmReady.value || sending.value || sentOk.value) return
  sending.value = true
  try {
    // biometric confirmation gate: fingerprint before units move.
    if (lock.enabled.value) {
      verifying.value = true
      const okBio = await lock.verify()
      verifying.value = false
      if (!okBio) { result.value = { ok: false, msg: t('pocket.send.bioFailed', 'Biometric confirmation failed — nothing sent.') }; return }
    }
    if (!await ensureAgent()) { result.value = { ok: false, msg: t('pocket.stake.authFailed', 'Agent auth failed.') }; return }
    const key = sendKey.for(`${fromDid.value}|${toDid.value}|${amountText.value}|${memo.value || ''}`)
    const r = await tegApi.smartSend({ receiver_did: toDid.value, amount: String(amountText.value), message: memo.value || undefined, dry_run: false },
      { idempotencyKey: key })
    sendKey.answered()
    // §REPATLANE-7: the reference is the answer's transfer_id (it never carried transaction_id), and an answer the registry
    // gave again under this key says that the first press had gone through
    const sentRef = sendReference(r)
    const shownRef = sentRef ? sentRef.slice(0, 12) + '…' : t('pocket.send.confirmed', 'confirmed')
    result.value = { ok: true, msg: answeredAgain(r)
      ? tp('pocket.send.sentFromFirst', 'Sent: your first press had already gone through ({ref})', { ref: shownRef })
      : tp('pocket.send.sent', 'Sent — {ref}', { ref: shownRef }) }
    try { (navigator as any).vibrate?.([8, 40, 8]) } catch {}
    const recv: any = previewRecv.value
    const receipt: SentReceipt = {
      ref: sentRef || undefined,
      method: String(preview.value?.method || 'local'),
      amount: String(amountText.value),
      currency: ccy.value,
      // What ARRIVED, in the recipient's unit — the fact a bare "sent 102"
      // hides on a cross-frame route.
      receivedAmount: recv?.amt ?? null,
      receivedCurrency: recv?.ccy ?? null,
      toDid: toDid.value,
      fromDid: fromDid.value,
    }
    setTimeout(() => { emit('sent', receipt); close() }, 1100)
  } catch (e: any) {
    if (failedSendOutcome(e) === 'unknown') {
      // the value may have moved: the key stays, so pressing again cannot pay twice
      result.value = { ok: false, unknown: true, msg: t('pocket.send.unknownOutcome', 'The send may have gone through: no answer said whether it did. Pressing send again asks once more with the same request, which never pays twice.') }
    } else {
      sendKey.answered()
      result.value = { ok: false, msg: wholeLedgerRefusalSentence(e) || e?.response?.data?.detail || e?.message || t('pocket.send.sendFailed', 'Send failed') }
    }
  } finally { sending.value = false }
}

async function makeQr() {
  qrDataUrl.value = ''
  if (!fromDid.value) return
  try { const QR = (await import('qrcode')).default
    // the QR is a payment-request URI — any camera app becomes an NFC-fallback reader
    const uri = buildPayUri({ to: fromDid.value, amount: reqAmount.value || undefined, ccy: props.ccy })
    qrDataUrl.value = await QR.toDataURL(uri, { margin: 1, width: 220, color: { dark: '#e6edf3', light: '#0a0d1200' } })
  } catch (e: any) {
    qrDataUrl.value = ''
    // §POCKETBRIDGE2 W1 — a missing QR with no word looks like "no QR feature".
    nfcMsg.value = tp('pocket.send.qrFailed', 'QR could not be rendered: {err}. The DID box below still works.', { err: e?.message || t('pocket.send.rendererFailed', 'renderer failed') })
  }
}

async function tapToPay() {
  nfcMsg.value = ''
  if (nfc.scanning.value) { nfc.stopScan(); return }
  const req = await nfc.scanPayRequest((st) => { nfcMsg.value = st })
  if (req) {
    toDid.value = req.to
    if (req.amount) amount.value = req.amount
    if (req.memo) memo.value = req.memo
    nfcMsg.value = t('pocket.send.requestRead', 'Payment request read — review and confirm.')
    try { (navigator as any).vibrate?.(8) } catch {}
  }
}

async function writeTag() {
  nfcMsg.value = ''
  await nfc.writePayRequest({ to: fromDid.value, amount: reqAmount.value || undefined, ccy: props.ccy },
                            (st) => { nfcMsg.value = st })
}
async function doCopy() { try { await navigator.clipboard.writeText(fromDid.value); copied.value = true; setTimeout(() => copied.value = false, 1500) } catch { nfcMsg.value = t('pocket.send.copyFailed', 'Copy failed — long-press the DID box to copy manually.') } }
async function doShare() { try { await (navigator as any).share({ title: t('pocket.send.shareTitle', 'My agent DID'), text: fromDid.value }) } catch (e: any) { if (e?.name !== 'AbortError') nfcMsg.value = t('pocket.send.shareUnavailable', 'Sharing is not available here — use Copy instead.') } }

function close() { emit('close') }
// S7 (batch-2 rule): sheets close on Escape too — he tests from a desktop.
function onEscKey(e: KeyboardEvent) { if (e.key === 'Escape' && props.open && !sending.value) close() }
watch(() => props.open, (o) => {
  if (o) window.addEventListener('keydown', onEscKey)
  else window.removeEventListener('keydown', onEscKey)
}, { immediate: true })

watch(() => props.open, (o) => {
  if (o) {
    result.value = null; preview.value = null; copied.value = false; nfcMsg.value = ''
    // §OURSTATE-6 — re-derived on EVERY open, never `if (!fromDid.value)`.
    // That guard is why a sheet opened once kept paying from the agent you
    // used first, silently, for the rest of the session — measured on
    // 2026-08-24 when two sends 32 seconds apart left two different agents.
    if (credAgents.value.length) {
      const active = (auth as any).activeAgent?.did
      const stillHave = active && credAgents.value.some(a => a.did === active)
      fromDid.value = stillHave ? active : credAgents.value[0].did
    } else {
      fromDid.value = ''
    }
    // prefill from a payment request (NFC tag read by the OS, QR scan, or shared link)
    if (props.initialTo) toDid.value = props.initialTo
    if (props.initialAmount) amount.value = props.initialAmount
    if (props.initialMemo) memo.value = props.initialMemo
    if (props.mode === 'receive') makeQr()
  } else { nfc.stopScan() }
  // §OURSTATE-1 — immediate: a consumer that mounts the sheet ALREADY open
  // (v-if="ever" + :open="true" in one tick) never fires a lazy watcher, so
  // its prefill silently vanished (the §POCKETBRIDGE5 mount-with-show-true
  // class, fixed at this shared root). Mounting closed still no-ops.
}, { immediate: true })
watch(fromDid, () => { if (props.open && props.mode === 'receive') makeQr() })
</script>

<style scoped>
.ps-scrim { position: fixed; inset: 0; z-index: 90; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px);
  display: flex; align-items: flex-end; }
.ps-sheet { width: 100%; max-width: 560px; margin: 0 auto; background: #0c0f15; border: 1px solid rgba(255,255,255,0.09);
  border-radius: 22px 22px 0 0; padding: 0.8rem 1.1rem calc(1.4rem + env(safe-area-inset-bottom, 0px));
  box-shadow: 0 -20px 50px rgba(0,0,0,0.5); max-height: 92dvh; overflow-y: auto; }
.ps-grip { width: 40px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.1rem auto 0.9rem; }
.ps-title { display: flex; align-items: center; gap: 0.45rem; font-size: 1.1rem; margin: 0 0 0.9rem; }
.ps-title :deep(svg) { width: 1.3rem; height: 1.3rem; color: var(--nc-primary, #00d4ff); }
.ps-lab { display: block; font-size: 0.7rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 600; margin: 0.7rem 0 0.3rem; }
.ps-in { width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px; padding: 0.75rem 0.85rem; color: #e6edf3; font-size: 0.92rem; outline: none; transition: border-color 0.15s; }
.ps-in:focus { border-color: rgba(0,212,255,0.45); }
.ps-mono { font-family: ui-monospace, monospace; font-size: 0.8rem; }
.ps-amt-row { position: relative; }
.ps-amt { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; padding-right: 3.5rem; }
.ps-amt-ccy { position: absolute; right: 0.9rem; top: 50%; transform: translateY(-50%); font-size: 0.85rem; font-weight: 600; opacity: 0.55; }
.ps-note { font-size: 0.76rem; margin: 0.5rem 0 0; opacity: 0.7; }
.ps-nfc { display: inline-flex; align-items: center; justify-content: center; gap: 0.45rem; width: 100%; margin-top: 0.5rem;
  background: rgba(125,211,252,0.07); border: 1px dashed rgba(125,211,252,0.35); border-radius: 12px; padding: 0.65rem;
  color: #7dd3fc; font-size: 0.82rem; font-weight: 600; cursor: pointer; min-height: 44px; -webkit-tap-highlight-color: transparent; }
.ps-nfc.live { border-style: solid; animation: ps-nfc-pulse 1.4s ease-in-out infinite; }
.ps-nfc:disabled { opacity: 0.45; }
.ps-nfc :deep(svg) { width: 1.05rem; height: 1.05rem; }
@keyframes ps-nfc-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(125,211,252,0.25); } 50% { box-shadow: 0 0 0 6px rgba(125,211,252,0); } }
@media (prefers-reduced-motion: reduce) { .ps-nfc.live { animation: none; } }
.ps-warn { color: #fbbf24; }
/* §OURSTATE-6 — the pre-send assertion. Deliberately plainer than the route
   box above it: this is the last thing read before money moves, so it is a
   list of facts, not a panel. */
.ps-assert { margin: 0.6rem 0 0.2rem; padding: 0.6rem 0.7rem; border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.14); background: rgba(255,255,255,0.03); }
.ps-assert-line { display: flex; justify-content: space-between; gap: 12px; padding: 2px 0;
  font-size: 0.92rem; }
.ps-assert-line span { opacity: 0.7; }
.ps-assert-line strong { font-variant-numeric: tabular-nums; text-align: right; }
.ps-assert-diff { color: var(--nc-warning, #ffb347); }
.ps-assert-warn { margin: 0.45rem 0 0; font-size: 0.85rem; color: var(--nc-warning, #ffb347);
  line-height: 1.4; }

.ps-route { margin-top: 0.9rem; background: rgba(0,212,255,0.05); border: 1px solid rgba(0,212,255,0.2); border-radius: 13px; padding: 0.7rem 0.85rem; }
.ps-route.err { background: rgba(255,107,107,0.06); border-color: rgba(255,107,107,0.28); }
.ps-route-line { display: flex; justify-content: space-between; font-size: 0.82rem; padding: 0.16rem 0; }
.ps-route-line span { opacity: 0.6; } .ps-route-line strong { font-variant-numeric: tabular-nums; }
.ps-fee-note { font-weight: 400; opacity: 0.55; font-size: 0.72em; }
.ps-route-err { font-size: 0.82rem; color: #ff8a8a; }
.ps-actions { display: flex; gap: 0.6rem; margin-top: 1.1rem; }
.ps-btn { flex: 1 1 0; display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; border-radius: 13px;
  padding: 0.85rem; font-size: 0.9rem; font-weight: 650; cursor: pointer; min-height: 48px; border: 1px solid transparent;
  -webkit-tap-highlight-color: transparent; transition: transform 0.12s; }
.ps-btn:active { transform: scale(0.96); }
.ps-btn:disabled { opacity: 0.45; }
.ps-btn :deep(svg) { width: 1.1rem; height: 1.1rem; }
.ps-ghost { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.1); color: #e6edf3; }
.ps-primary { background: linear-gradient(160deg, rgba(0,212,255,0.2), rgba(0,212,255,0.08)); border-color: rgba(0,212,255,0.4); color: #e6edf3; }
.ps-send { background: linear-gradient(160deg, rgba(16,185,129,0.28), rgba(16,185,129,0.1)); border-color: rgba(16,185,129,0.45); color: #d1fae5; }
.ps-result { text-align: center; font-size: 0.84rem; margin: 0.8rem 0 0; }
.ps-result.ok { color: #34d399; } .ps-result.bad { color: #ff8a8a; } .ps-result.unknown { color: #fbbf24; }
.ps-qr { display: flex; justify-content: center; margin: 0.8rem 0; }
.ps-qr img { width: 200px; height: 200px; border-radius: 14px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); padding: 0.5rem; }
.ps-did-box { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 0.75rem; word-break: break-all; text-align: center; }
.ps-sheet-enter-active, .ps-sheet-leave-active { transition: opacity 0.2s ease; }
.ps-sheet-enter-active .ps-sheet, .ps-sheet-leave-active .ps-sheet { transition: transform 0.24s cubic-bezier(0.34,1.3,0.64,1); }
.ps-sheet-enter-from, .ps-sheet-leave-to { opacity: 0; }
.ps-sheet-enter-from .ps-sheet, .ps-sheet-leave-to .ps-sheet { transform: translateY(100%); }
@media (prefers-reduced-motion: reduce) { .ps-sheet-enter-active .ps-sheet, .ps-sheet-leave-active .ps-sheet { transition: none; } }
</style>
