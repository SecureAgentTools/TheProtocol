<script setup lang="ts">
/**
 * §COCKPIT P5 (§DECIDE) — THE decision queue. One implementation, two mounts.
 *
 * The desk mounts it full-size inside the Decisions pane; Pocket's Approvals view
 * mounts it phone-sized. Before this, Pocket rendered confirms one way and the desk
 * rendered them another, and only one of them acked, hashed what it showed, or knew
 * the posture — so a receipt's meaning depended on which screen the human happened to
 * be at. A second copy of "what a decision looks like and what answering it does" is
 * the §ORGLEAK class in a costume: the copies agree until they do not.
 *
 * What is NOT shared, and should not be: SIGNING. The two surfaces genuinely hold
 * different credentials — the phone signs with the Pocket biometric lock's key, the
 * desk with a credential enrolled through the device-agnostic self routes. That is a
 * real difference, so it is injected as `signWith` rather than branched inside.
 *
 * I1 — QUEUE OF ONE. Exactly one decision is answerable at a time, FIFO by
 * `created_at` so nothing starves. The rest are visible (a hidden queue is a queue you
 * cannot plan around) and INERT (a screen full of live buttons is how you approve the
 * wrong one).
 *
 * §6b — SAMENESS IS RENDERED, NEVER ASSUMED. The badge and the diff both key on the
 * SERVER's `facts_digest`, the same digest the read floor matches previews on and the
 * streak counts with. This component never re-derives "is this the same thing".
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { liabilityApi, type DenyReason, type Intent, type Receipt } from '@/services/api/liability'
import { useI18n } from '@/composables/useI18n'
import { useCockpitBus } from '@/composables/useCockpitBus'
import { useConsentPosture } from '@/composables/useConsentPosture'
import { useDeviceSigner } from '@/composables/useDeviceSigner'
import { buildPresentation, presentationHash, RENDER_VERSION, type PresentedLine } from './presentation'

interface Challenge {
  id: string; mandate_id: string | null; action_type: string
  action_ref: string | null; facts: Record<string, any>
  challenge_hash: string; created_at: string; expires_at: string
  facts_digest?: string; posture?: string; read_floor_ms?: number
}

/** What a surface must provide to SIGN. Returning null = "this surface cannot sign
 *  right now", which is a state to render, not an error to throw. */
export type SignFn = (challengeHashHex: string) => Promise<
  { device_id: number; signature: string; credential_id?: string;
    authenticator_data?: string; client_data_json?: string } | null>

const props = withDefaults(defineProps<{
  variant?: 'desk' | 'phone'
  /** Injected signer. Omitted ⇒ the desk's own self-enrolled credential. */
  signWith?: SignFn | null
  /** How many queued-but-inert decisions to list under the presentable one. */
  maxQueued?: number
  pollSeconds?: number
}>(), { variant: 'desk', signWith: null, maxQueued: 6, pollSeconds: 20 })

const emit = defineEmits<{ (e: 'count', n: number): void; (e: 'resolved', id: string): void }>()

const { t, tp, locale } = useI18n()
/* §CEILING (P7) — the proposal door. At the posture's streak count the badge stops being
 * a remark and offers a way out: "stop asking me about this". It FILLS the grant form
 * and never fires it (the §VOICEHIRE law) — a door that acts on its own is not an offer,
 * it is a decision somebody else made. Granting it is still a signature, and under every
 * posture it is a WebAuthn one. */
const proposeOpen = ref(false)
const proposeHours = ref<number | null>(null)
const proposeMsg = ref('')
// Destructured on purpose: only TOP-LEVEL setup refs are unwrapped in a template.
// `posture.deskAuthenticatorAllowed` reached through the returned object stays a Ref —
// always truthy — so a v-if on it would silently always pass.
const {
  readFloorMs, deskAuthenticatorAllowed, methodFloor, streakBadgeAt,
  posture: postureObj, load: loadPosture,
} = useConsentPosture()
const signer = useDeviceSigner()
const surface = computed<'desk' | 'device'>(() => (props.variant === 'phone' ? 'device' : 'desk'))

const rows = ref<Challenge[]>([])
const receipts = ref<Receipt[]>([])
const loading = ref(true)
const err = ref('')
const msg = ref('')
const acting = ref(false)
const totpCode = ref('')
const denyOpen = ref(false)
const now = ref(Date.now())
/** Set by a server 425 — the authority on when consent becomes possible. */
const serverEligibleAt = ref<number | null>(null)
const enrolling = ref(false)
/* 🔴 THE DESK'S CREDENTIAL MUST OUTLIVE THE PAGE. Held only in component state, an
 * enrolment survived exactly one page load: after a reload `canSignHere` went false and
 * Approve silently fell through to the TOTP branch with an empty box — a human who had
 * just enrolled a fingerprint was told to "enter your code", and a second enrolment
 * would rewrite the same device row. Found by a battery leg that approved four
 * identical decisions in a row and got a streak of zero, because three of the four
 * never actually approved.
 *
 * WHICH credential a browser holds is knowable only to that browser — the server sees
 * device rows, not which one is sitting in front of you — so the id is stored locally,
 * exactly as Pocket's own lock does it (`pocketCredentialId`). Losing this key costs a
 * re-enrolment, never authority: the SERVER decides what a signature is worth. */
const DESK_SIGNER_KEY = 'ckd_desk_signer'
function loadDeskCredential(): { device_id: number; credential_id: string } | null {
  try {
    const raw = JSON.parse(localStorage.getItem(DESK_SIGNER_KEY) || 'null')
    return raw && typeof raw.device_id === 'number' && raw.credential_id ? raw : null
  } catch { return null }
}
const deskCredential = ref<{ device_id: number; credential_id: string } | null>(
  props.variant === 'desk' ? loadDeskCredential() : null)
/** §FESUITE (V0594): a fingerprint not given with the desk's key: a cancel, or a key the device no longer holds (the
 *  browser says NotAllowedError for both). The key is kept and enrolling again is offered beside Approve. */
const deskKeyDoubt = ref(false)
function forgetDeskKey() {
  deskCredential.value = null
  deskKeyDoubt.value = false
  try { localStorage.removeItem(DESK_SIGNER_KEY) } catch { /* nothing to forget */ }
}

let poll: ReturnType<typeof setInterval> | null = null
let tick: ReturnType<typeof setInterval> | null = null

/* ── the queue ──────────────────────────────────────────────────────────────── */
// FIFO: OLDEST first. The pending endpoint returns newest-first, which for a queue of
// one would answer the freshest ask forever and starve the oldest — I1's whole point.
const ordered = computed(() =>
  [...rows.value].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()))
const head = computed<Challenge | null>(() => ordered.value[0] ?? null)
const queued = computed(() => ordered.value.slice(1, 1 + props.maxQueued))
const empty = computed(() => !loading.value && !err.value && rows.value.length === 0)

async function load() {
  try {
    // ⚠ `pendingChallenges()` already unwraps to `.data`. Destructuring `{ data }` off
    // it yields undefined and an empty queue that never errors — silent, and green.
    const res = await liabilityApi.pendingChallenges()
    rows.value = Array.isArray((res as any)?.challenges) ? (res as any).challenges : []
    err.value = ''
  } catch (e: any) {
    // 404 = liability is off on this registry. That is darkness, not an outage, and it
    // must not paint an error on a surface where the feature simply is not enabled.
    if (e?.response?.status === 404) { rows.value = []; err.value = '' }
    else err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally {
    loading.value = false
    emit('count', rows.value.length)
  }
}

/* ── §PREFLIGHT (P8) — what agents have ANNOUNCED but not yet attempted ────────
 *
 * 🔴 These are UNVERIFIED CLAIMS BY AN AGENT. Nothing here has been checked against a
 * mandate, a balance, a counterparty or a ceiling, and NOTHING here is signable — the
 * approve affordance does not exist in this state at all (I9: absent, not disabled,
 * because a disabled control is one CSS mistake from being a live one).
 *
 * They earn their place by buying READING TIME: the human starts reading before the
 * real ask exists, so when it arrives the read floor may already be satisfied. The
 * credit itself is granted SERVER-side off a `consent_previews` row stamped with the
 * server's clock — never off anything an agent said (P4/R9).
 */
const intents = ref<Intent[]>([])
const intentsAvailable = ref(true)

async function loadIntents() {
  // `preflight: false` is `hardened` saying every action asks. Rendering announcements
  // there would be decoration for a dial whose whole meaning is that nothing appears
  // before a challenge exists.
  if (postureObj.value && postureObj.value.dials?.preflight === false) {
    intents.value = []; intentsAvailable.value = true; return
  }
  try {
    const r = await liabilityApi.pendingIntents()
    intents.value = Array.isArray(r?.items) ? r.items : []
    // An honest GAP, not an empty list: "the rail is down" and "no agent announced
    // anything" are different facts and the strip says which one it is.
    intentsAvailable.value = r?.available !== false
  } catch (e: any) {
    intents.value = []
    intentsAvailable.value = e?.response?.status === 404 ? true : false
  }
}

/** An announcement is superseded the instant the real ask for the same action lands:
 *  showing both would put the same action on the desk twice, once answerable and once
 *  not, which is the surest way to answer the wrong one. */
const liveIntents = computed(() => {
  const claimed = new Set(rows.value.map(r => r.action_ref).filter(Boolean))
  const nowMs = now.value
  return intents.value
    .filter(i => !claimed.has(i.action_ref))
    .filter(i => new Date(i.expires_at).getTime() > nowMs)
    .slice(0, 5)
})

function intentSecsLeft(i: Intent): number {
  return Math.max(0, Math.round((new Date(i.expires_at).getTime() - now.value) / 1000))
}

/** Did the ask that arrived match what the agent announced? Same ONE diff. */
const preflightDiff = computed<Record<string, { was: string; now: string }>>(() => {
  const h = head.value
  if (!h) return {}
  const announced = intents.value.find(i => i.action_ref && i.action_ref === h.action_ref)
  if (!announced) return {}
  return diffPresented(announced.facts_preview, linesFor(h), announced.facts_digest, h.facts_digest)
})

/* §FESUITE (V0577): the earlier decisions could not be read. They feed "Changed since your last decision" (the catch for
 * an agent re-asking on different terms) and the streak, so a failed read silently switched both off; the card now says
 * the comparison could not be made, the way the pre-flight strip says when announcements are unavailable. */
const receiptsFailed = ref(false)

async function loadReceipts() {
  try {
    receipts.value = (await liabilityApi.receipts({ limit: 40 })).receipts || []
    receiptsFailed.value = false
  } catch { receipts.value = []; receiptsFailed.value = true }
}

/* ── §6b — the previous decision, and the streak ─────────────────────────────
 * "Identical to the one you approved 40 s ago · 4th in a row" is only worth saying if
 * both halves are true, so both read the SERVER's digest off receipts this human
 * actually resolved. A deny breaks the streak: the point of the badge is that nobody
 * has looked lately, and a deny is proof that somebody did.
 */
const resolvedDecisions = computed(() =>
  receipts.value
    .filter(r => r.event_type === 'challenge_approved' || r.event_type === 'challenge_denied')
    .filter(r => !!r.challenge)
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime()))

const previous = computed(() => resolvedDecisions.value[0] ?? null)

/** 🔴 §COCKPITBOOK — THE ONE TO DIFF AGAINST, WHICH IS NOT SIMPLY THE LAST ONE.
 *
 * His screenshots: five unrelated asks in a queue, and every card wore
 * "CHANGED SINCE YOUR LAST DECISION" with four struck-through rows — `guild.post` shown as
 * a changed version of `treasury.remit`, amount ~~12000~~ → 2000, counterparty
 * ~~Meridian Ledger Works~~ → The Guild board. All of it true as arithmetic and meaningless
 * as a claim: those are two different asks, not one ask that changed.
 *
 * That banner exists to catch ONE thing — an agent re-asking on different terms after you
 * decided (the bait-and-switch). Firing it on unrelated pairs is crying wolf, and it trains
 * the reader to skip the exact signal that is supposed to stop them. So the comparison now
 * requires the two to be the same KIND of ask: same mandate, same action type. It searches
 * back rather than taking the immediate predecessor, which also makes it STRONGER — an
 * agent cannot bury a re-ask by interleaving unrelated ones.
 */
const previousComparable = computed(() => {
  const h = head.value
  if (!h) return null
  return resolvedDecisions.value.find(r =>
    !!r.challenge
    && r.challenge.action_type === h.action_type
    && (r.mandate_id ?? null) === (h.mandate_id ?? null)) ?? null
})

const streak = computed(() => {
  const d = head.value?.facts_digest
  if (!d) return 0
  let n = 0
  for (const r of resolvedDecisions.value) {
    if (r.event_type === 'challenge_approved' && r.challenge?.facts_digest === d) n++
    else break
  }
  return n
})
const streakShown = computed(() => streak.value >= (streakBadgeAt.value || 3))
const proposeAt = computed(() => postureObj.value?.dials.streak_propose_ceiling_at ?? null)
const canPropose = computed(() =>
  !!proposeAt.value && streak.value >= (proposeAt.value as number)
  && !!head.value?.mandate_id && !!head.value?.facts?.amount
  && (postureObj.value?.dials.ceilings !== false))

async function requestCeiling() {
  const c = head.value
  if (!c?.mandate_id) return
  proposeMsg.value = ''
  try {
    await liabilityApi.raiseCeiling(c.mandate_id, {
      scope: c.action_type,
      max_per_tx: String(c.facts?.amount ?? ''),
      currency: String(c.facts?.currency ?? ''),
      ...(proposeHours.value ? { hours: proposeHours.value } : {}),
    })
    proposeOpen.value = false
    proposeMsg.value = t('cockpit.ceiling.requested',
      'Asked. It appears below as a confirmation — sign it with your enrolled device.')
    await load()
  } catch (e: any) {
    const d = serverDetail(e)
    proposeMsg.value = String(d.remedy || d.error || e?.response?.data?.detail || e?.message
      || t('cockpit.ceiling.failed', 'Could not ask for that.'))
  }
}
const sincePrevious = computed(() => {
  const p = previous.value
  if (!p) return ''
  const secs = Math.max(0, Math.round((now.value - new Date(p.at).getTime()) / 1000))
  return secs < 90 ? `${secs}s` : `${Math.round(secs / 60)}m`
})

/* Diff against the previous decision — rendered, so a human sees WHAT changed rather
 * than being asked to spot it. Keys are compared over the presented lines, because
 * those are the words that were on the screen. */
/** THE diff. ONE implementation, two consumers (P8 requires exactly this): the
 *  "changed since your last decision" banner, and the pre-flight divergence banner.
 *
 *  🔴 Two implementations of "are these the same facts" is how the fast path and the
 *  safe path start disagreeing — and here the fast path is one that lets a human
 *  consent IMMEDIATELY. The digest short-circuit is the server's own
 *  `facts_comparable_digest`, so client and server answer that question identically;
 *  the line walk exists only to say WHICH field moved, in the words that were on screen.
 */
function diffPresented(
  wasFacts: Record<string, any> | null | undefined,
  nowLines: PresentedLine[],
  wasDigest?: string | null,
  nowDigest?: string | null,
): Record<string, { was: string; now: string }> {
  if (!wasFacts) return {}
  if (wasDigest && nowDigest && wasDigest === nowDigest) return {}
  const a = new Map(buildPresentation(wasFacts || {}, t as any).map(l => [l.key, l]))
  const out: Record<string, { was: string; now: string }> = {}
  for (const l of nowLines) {
    const was = a.get(l.key)
    if (was && was.value !== l.value) out[l.label] = { was: was.value, now: l.value }
  }
  return out
}

const diff = computed<Record<string, { was: string; now: string }>>(() => {
  const h = head.value, p = previousComparable.value
  if (!h || !p?.challenge) return {}
  return diffPresented(p.challenge.facts, linesFor(h), p.challenge.facts_digest, h.facts_digest)
})

/* ── §SHOWN — render the lines, hash the same array, ack once per surface ────── */
const lineCache = new Map<string, PresentedLine[]>()
function linesFor(c: Challenge): PresentedLine[] {
  const hit = lineCache.get(c.id)
  if (hit) return hit
  const built = buildPresentation(c.facts || {}, t as any)
  lineCache.set(c.id, built)
  return built
}

/** The GLANCE amount, READ OFF THE PRESENTED LINES.
 *
 * 🔴 Restored after the P1 battery caught its absence. The extraction dropped this
 * headline and kept only the itemised lines — and the words "unit unrecorded" sitting
 * inline in a list are not the same warning as a dashed amber chip beside the number.
 * I11 / §FOREIGNACT is precisely about a label that lies QUIETLY: the Commander staked
 * "1.337" believing BVT and locked 1337 AVT with every ledger correct. A missing unit
 * has to be loud.
 *
 * ⚠ It reads off `linesFor()` and never off `c.facts`, because two paths to one display
 * is what `presentation.ts` exists to prevent: the hash covers the lines, so a headline
 * sourced anywhere else could disagree with the very thing the receipt attests to.
 */
function amountOf(c: Challenge): { amount: string; currency: string } | null {
  const line = linesFor(c).find(l => l.key === 'amount')
  if (!line) return null
  const ccy = String(c.facts?.currency || '').trim()
  const idx = line.value.indexOf(' ')
  return idx < 0
    ? { amount: line.value, currency: '' }
    : { amount: line.value.slice(0, idx), currency: ccy ? line.value.slice(idx + 1) : '' }
}

const acked = new Map<string, number>()   // challenge id → local ms at first paint
async function ackIfNew(c: Challenge) {
  if (acked.has(c.id)) return
  acked.set(c.id, Date.now())
  try {
    const hash = await presentationHash(linesFor(c), String(locale.value || 'en'))
    await liabilityApi.ackChallenge(c.id, {
      surface: surface.value,
      render_version: RENDER_VERSION,
      locale: String(locale.value || 'en'),
      presentation_hash: hash,
      first_presented_at: new Date().toISOString(),
    })
  } catch {
    // An ack that fails must never stop the human seeing the decision: it records
    // delivery, it is not a precondition for it.
    acked.delete(c.id)
  }
}
// Only the PRESENTABLE decision is acked. Acking the inert queue behind it would
// claim a human was shown things they cannot answer and did not read.
watch(head, (c) => { if (c) void ackIfNew(c) }, { immediate: true })

/* ── the read floor ─────────────────────────────────────────────────────────── */
/* This countdown is a COURTESY, not the gate. The server enforces the floor against
 * its OWN clock and refuses early signatures with a `retry_after_ms`; when that
 * happens we adopt the server's number, because a client clock that runs fast would
 * otherwise offer a button that keeps being refused. */
const floorMs = computed(() => head.value?.read_floor_ms ?? readFloorMs.value)
const eligibleAt = computed(() => {
  if (serverEligibleAt.value) return serverEligibleAt.value
  const c = head.value
  if (!c) return 0
  return (acked.get(c.id) ?? new Date(c.created_at).getTime()) + (floorMs.value || 0)
})
const waitMs = computed(() => Math.max(0, eligibleAt.value - now.value))
const canConsent = computed(() => !!head.value && waitMs.value <= 0 && !acting.value)
const secsLeft = computed(() => {
  const c = head.value
  if (!c) return 0
  return Math.max(0, Math.floor((new Date(c.expires_at).getTime() - now.value) / 1000))
})

/* ── consent ────────────────────────────────────────────────────────────────── */
const canSignHere = computed(() =>
  props.variant === 'phone' ? !!props.signWith
    : (deskAuthenticatorAllowed.value && !!deskCredential.value))
const totpOffered = computed(() => methodFloor.value !== 'webauthn_uv')
/** Stricter postures move the answer to a device this surface is not. */
const answerElsewhere = computed(() =>
  props.variant === 'desk' && !deskAuthenticatorAllowed.value)

async function enrolDesk() {
  enrolling.value = true; msg.value = ''
  try {
    if (!(await signer.platformAvailable())) {
      msg.value = t('cockpit.decide.noAuthenticator',
        'This browser has no platform authenticator (fingerprint or device PIN) to sign with.')
      return
    }
    const opts = await liabilityApi.webauthnSelfOptions()
    const reg = await signer.register(opts as any)
    const res = await liabilityApi.webauthnSelfRegister(reg)
    deskCredential.value = { device_id: res.device_id, credential_id: res.credential_id }
    deskKeyDoubt.value = false
    try { localStorage.setItem(DESK_SIGNER_KEY, JSON.stringify(deskCredential.value)) } catch { /* private mode: enrolment holds for this page only, and says so by asking again */ }
    msg.value = t('cockpit.decide.enrolled', 'This device can now sign decisions.')
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || e?.message || t('cockpit.decide.enrolFailed', 'Enrolment was cancelled.')
  } finally { enrolling.value = false }
}

/** The server's refusal bodies are JSON-encoded into `detail` by the house error
 *  handler. Parse it, because the WHOLE point of R3 is that the human reads a reason
 *  and not a status code. */
function serverDetail(e: any): Record<string, any> {
  const d = e?.response?.data?.detail ?? e?.response?.data?.error?.detail
  if (d && typeof d === 'object') return d
  try { return JSON.parse(String(d || '{}')) } catch { return {} }
}

function absorbRefusal(e: any): boolean {
  const st = e?.response?.status
  const d = serverDetail(e)
  if (st === 425) {
    // The server's clock is the authority. Adopt its eligibility, do not argue.
    serverEligibleAt.value = Date.now() + Number(d.retry_after_ms || 0)
    msg.value = tp('cockpit.decide.tooEarly',
      'Not yet — this posture asks for {ms} ms with the facts on screen.', { ms: d.read_floor_ms ?? floorMs.value })
    return true
  }
  if (st === 403 && d.method_floor) {
    msg.value = String(d.remedy || t('cockpit.decide.methodRefused', 'This posture needs a stronger confirmation.'))
    return true
  }
  return false
}

async function approve() {
  const c = head.value
  if (!c) return
  acting.value = true; msg.value = ''
  let signedWithDesk = false
  try {
    let body: Record<string, any> | null = null
    if (canSignHere.value) {
      if (props.variant === 'phone' && props.signWith) {
        body = await props.signWith(c.challenge_hash)
      } else if (deskCredential.value) {
        signedWithDesk = true
        const a = await signer.sign(c.challenge_hash, deskCredential.value.credential_id)
        body = { device_id: deskCredential.value.device_id, ...a }
      }
    }
    if (!body) {
      if (!totpCode.value) {
        msg.value = t('cockpit.decide.needMethod', 'Enter your code, or enable signing on this device.')
        return
      }
      body = { totp_code: totpCode.value }
    }
    await liabilityApi.approveChallenge(c.id, body as any)
    totpCode.value = ''
    deskKeyDoubt.value = false
    serverEligibleAt.value = null
    msg.value = tp('cockpit.decide.approvedWhat', 'Approved: {what}.', { what: c.action_type })
    emit('resolved', c.id)
    await Promise.all([load(), loadReceipts()])
  } catch (e: any) {
    // a fingerprint not given (declined, cancelled, timed out: NotAllowedError) sent nothing and was the person's
    // choice: said in words, not as the browser's own sentence (§FESUITE lifecycle 90, the approve page's fix (1)).
    // §FESUITE (V0594): a key the device no longer holds raises the same NotAllowedError and the browser cannot tell
    // the two apart, so the key is KEPT (one cancelled prompt threw it away and asked for a new enrolment next time)
    // and enrolling again is offered beside Approve: the person's call
    if (e?.name === 'NotAllowedError' || e?.name === 'AbortError') {
      if (signedWithDesk) deskKeyDoubt.value = true
      msg.value = t('cockpit.decide.notConfirmed', 'Your fingerprint was not confirmed, so nothing was sent. Approve again, or deny.')
      return
    }
    // A credential this browser remembers but the server no longer honours (revoked, or the row rebuilt): the
    // registry's 401 on the desk's own signature (or the authenticator's InvalidStateError). Forget it and offer
    // enrolment again rather than retrying into the same wall. (The old test read the HTTP client's message, which
    // never names a credential, so a refusal never forgot the key while a cancel always did.)
    if (signedWithDesk && (e?.name === 'InvalidStateError' || e?.response?.status === 401)) {
      forgetDeskKey()
      msg.value = t('cockpit.decide.keyRefused',
        'This device\'s signing key was not accepted, so nothing was approved. Enable signing on this device again, or deny.')
      return
    }
    if (!absorbRefusal(e)) {
      msg.value = serverDetail(e)?.error || e?.response?.data?.detail || e?.message
        || t('cockpit.decide.rejected', 'Not accepted.')
    }
  } finally { acting.value = false }
}

/** I7 — deny is available at EVERY posture and needs no step-up. Refusing is never the
 *  dangerous direction, and a posture that makes saying no harder than saying yes has
 *  the incentive backwards. */
async function deny(reason: DenyReason) {
  const c = head.value
  if (!c) return
  acting.value = true; denyOpen.value = false
  try {
    await liabilityApi.denyChallenge(c.id, reason)
    msg.value = tp('cockpit.decide.deniedWhat', 'Denied: {what}.', { what: c.action_type })
    emit('resolved', c.id)
    await Promise.all([load(), loadReceipts()])
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || e?.message || t('cockpit.decide.denyFailed', 'Could not deny.')
  } finally { acting.value = false }
}

// ⚠ `denyReason.*`, NOT `deny.*`: `cockpit.decide.deny` is the button's own label, and
// a key cannot be a leaf and a branch at once — nesting under it made the label
// resolve to an object and render as nothing. The raw-key gate caught it in English.
const DENY_REASONS: DenyReason[] = ['wrong_amount', 'wrong_counterparty', 'not_now', 'never']
const denyLabel = (r: DenyReason) => ({
  wrong_amount: t('cockpit.decide.denyReason.wrongAmount', 'The amount is wrong'),
  wrong_counterparty: t('cockpit.decide.denyReason.wrongCounterparty', 'The counterparty is wrong'),
  not_now: t('cockpit.decide.denyReason.notNow', 'Not now'),
  never: t('cockpit.decide.denyReason.never', 'Never for this'),
}[r])

useCockpitBus({
  'liability.cue': () => { void Promise.all([load(), loadIntents()]) },
  'liability.resolved': () => { void Promise.all([load(), loadReceipts()]) },
  // §PREFLIGHT — an announcement is worth nothing if it lands after the challenge it
  // was meant to precede, so it rides the live socket like the ask itself.
  'liability.intent': () => { void loadIntents() },
})

watch(head, (c, prev) => { if (c?.id !== prev?.id) { serverEligibleAt.value = null; totpCode.value = '' } })

onMounted(() => {
  void loadPosture()
  void load(); void loadReceipts(); void loadIntents()
  poll = setInterval(() => { void load(); void loadIntents() },
                     Math.max(5, props.pollSeconds) * 1000)
  tick = setInterval(() => { now.value = Date.now() }, 250)
})
onUnmounted(() => {
  if (poll) clearInterval(poll); poll = null
  if (tick) clearInterval(tick); tick = null
})

defineExpose({ reload: load })
</script>

<template>
  <!-- §COCKPITTILES T1 — publish emptiness so the enclosing tile can collapse.
       `PaneDecisions` passes `:empty="false"` to PaneShell BECAUSE this component owns
       every state, which meant the shell reported `data-empty="0"` while the queue was
       saying "Nothing is waiting on you" — and the slot held a two-row void around one
       sentence. The desk's collapse rule matches ANY descendant publishing the flag, so
       saying it here is all that was missing. Read off the screenshot, not a battery. -->
  <div class="dq" :class="`dq--${variant}`" data-testid="dq-root"
       :data-empty="(!loading && !err && empty) ? '1' : '0'">
    <!-- ══ §PREFLIGHT (P8) — ANNOUNCED, NOT ASKED ═══════════════════════════════
         🔴 There is NO approve affordance anywhere inside this section — not a
         disabled one, none at all. An intent is an agent's own unverified claim; the
         only thing a human can do with it is read it. Rendering a greyed-out button
         here would put a control one CSS rule away from signing something the server
         has never checked. (I9)                                                    -->
    <section v-if="liveIntents.length" class="dq-pf" data-testid="dq-preflight">
      <header class="dq-pf-head">
        <Icon name="mdi:radar" class="dq-pf-icon" />
        <span class="dq-pf-title">{{ t('cockpit.preflight.title', 'Announced by agents') }}</span>
        <span class="dq-pf-tag" data-testid="dq-preflight-unverified">
          {{ t('cockpit.preflight.unverified', 'unverified · not signable') }}
        </span>
      </header>
      <ul class="dq-pf-list">
        <li v-for="i in liveIntents" :key="i.id" class="dq-pf-row" data-testid="dq-preflight-row">
          <span class="dq-pf-verb">{{ i.action_type }}</span>
          <span class="dq-pf-ref">{{ i.action_ref }}</span>
          <!-- Visible expiry: an announcement that never becomes an ask must be seen to
               lapse, not just quietly vanish from a list. -->
          <span class="dq-pf-clock" data-testid="dq-preflight-expiry">{{ intentSecsLeft(i) }}s</span>
        </li>
      </ul>
      <p class="dq-pf-note">{{ t('cockpit.preflight.note',
        'These have not been checked against a mandate, a balance or a ceiling. Reading now means the real confirmation can be answered sooner.') }}</p>
    </section>
    <p v-else-if="!intentsAvailable" class="dq-note" data-testid="dq-preflight-gap">
      {{ t('cockpit.preflight.unavailable',
           'Pre-flight is unavailable, so nothing is announced ahead. Confirmations are unaffected.') }}
    </p>

    <!-- §FESUITE (lifecycle 90): the outcome of an answer outlives its card. It lived inside the card, and the queue
         re-reads right after an answer, so the answered card (and "Approved." with it) left at once: the person saw the
         card vanish and "Nothing is waiting on you.", never what became of their answer. -->
    <p v-if="msg" class="dq-msg" data-testid="dq-msg" role="status">{{ msg }}</p>
    <p v-if="loading" class="dq-note">{{ t('cockpit.decide.loading', 'Reading the queue…') }}</p>
    <p v-else-if="err" class="dq-note dq-err" data-testid="dq-error">{{ err }}</p>
    <p v-else-if="empty" class="dq-note" data-testid="dq-empty">
      {{ t('cockpit.decisions.empty', 'Nothing is waiting on you.') }}
    </p>

    <template v-else-if="head">
      <!-- THE ONE ANSWERABLE DECISION -->
      <article class="dq-head" data-testid="dq-presentable">
        <header class="dq-top">
          <span class="dq-verb">{{ head.action_type }}</span>
          <span v-if="head.posture" class="dq-posture" data-testid="dq-posture-badge"
                :title="t('cockpit.decide.postureHint', 'The consent posture in force for this decision.')">
            {{ head.posture }}
          </span>
          <span class="dq-clock" :class="{ 'is-urgent': secsLeft <= 20 }" data-testid="dq-expiry">{{ secsLeft }}s</span>
        </header>

        <!-- §6b — sameness, rendered. -->
        <p v-if="streakShown" class="dq-streak" data-testid="dq-streak">
          <Icon name="mdi:repeat-variant" />
          {{ tp('cockpit.decide.streak',
                'Identical to the one you approved {ago} ago · {n} in a row.',
                { ago: sincePrevious, n: streak }) }}
        </p>
        <div v-if="canPropose" class="dq-propose" data-testid="dq-propose">
          <button class="dq-btn" data-testid="dq-propose-open" @click="proposeOpen = !proposeOpen">
            <Icon name="mdi:infinity" /> {{ t('cockpit.ceiling.propose', 'Stop asking me about this') }}
          </button>
          <div v-if="proposeOpen" class="dq-propose-form" data-testid="dq-propose-form">
            <!-- PREFILLED from the decision in front of you, and inert until you press
                 Ask: the form is the proposal, the button is the decision. -->
            <p class="dq-propose-line">
              {{ tp('cockpit.ceiling.upTo', 'Up to {amount} {currency} for {verb}, then ask me again.',
                    { amount: head.facts?.amount, currency: head.facts?.currency, verb: head.action_type }) }}
            </p>
            <label class="dq-propose-hours">
              {{ t('cockpit.ceiling.hours', 'hours') }}
              <input v-model.number="proposeHours" type="number" min="1" max="720"
                     data-testid="dq-propose-hours"
                     :placeholder="String(postureObj?.dials.ceiling_decay_hours ?? 24)" />
            </label>
            <button class="dq-btn dq-btn-yes" data-testid="dq-propose-send" @click="requestCeiling">
              {{ t('cockpit.ceiling.ask', 'Ask for it') }}
            </button>
            <p class="dq-propose-note">
              {{ t('cockpit.ceiling.signNote',
                    'Granting this is itself a decision, and it needs your enrolled device — not a code.') }}
            </p>
          </div>
          <p v-if="proposeMsg" class="dq-msg" data-testid="dq-propose-msg">{{ proposeMsg }}</p>
        </div>
        <!-- §PREFLIGHT: the ask did NOT match what the agent announced. Loud, and ABOVE
             the quieter "changed since your last decision" line, because this one means
             the thing you spent your reading time on is not the thing being asked. -->
        <div v-if="Object.keys(preflightDiff).length" class="dq-pfdiff" data-testid="dq-preflight-diff">
          <span class="dq-pfdiff-h">
            <Icon name="mdi:alert" class="dq-pfdiff-icon" />
            {{ t('cockpit.preflight.diverged',
                 'This is not what the agent announced. Your reading time does not count for it.') }}
          </span>
          <span v-for="(v, k) in preflightDiff" :key="k" class="dq-diff-row" data-testid="dq-preflight-diff-row">
            <b>{{ k }}</b>: <s>{{ v.was }}</s> → {{ v.now }}
          </span>
        </div>
        <div v-else-if="Object.keys(diff).length" class="dq-diff" data-testid="dq-diff">
          <span class="dq-diff-h">{{ t('cockpit.decide.changed', 'Changed since your last decision') }}</span>
          <span v-for="(v, k) in diff" :key="k" class="dq-diff-row" data-testid="dq-diff-row">
            <b>{{ k }}</b><s>{{ v.was }}</s><Icon name="mdi:arrow-right" /><i>{{ v.now }}</i>
          </span>
        </div>
        <ReadFailedNotice v-else-if="receiptsFailed" dense :retry="loadReceipts" data-testid="dq-receipts-unread"
          :text="t('cockpit.decide.receiptsUnread', 'Your earlier decisions could not be read just now, so whether this changed since your last one cannot be checked.')" />

        <div v-if="amountOf(head)" class="dq-amount" data-testid="dq-amount">
          <span class="dq-amt">{{ amountOf(head)!.amount }}</span>
          <span v-if="amountOf(head)!.currency" class="dq-cur">{{ amountOf(head)!.currency }}</span>
          <span v-else class="dq-cur-missing" data-testid="ckd-unit-unrecorded"
                :title="t('cockpit.decisions.unitUnrecordedHint', 'The challenge did not record a currency. Showing the registry currency here would be a guess.')">
            <Icon name="mdi:help-circle-outline" class="dq-cur-icon" />
            {{ t('cockpit.decisions.unitUnrecorded', 'unit unrecorded') }}
          </span>
        </div>
        <dl class="dq-lines" data-testid="dq-lines">
          <div v-for="l in linesFor(head)" :key="l.key" class="dq-line">
            <dt>{{ l.label }}</dt><dd>{{ l.value }}</dd>
          </div>
        </dl>

        <!-- consent -->
        <div v-if="answerElsewhere" class="dq-elsewhere" data-testid="dq-answer-elsewhere">
          <Icon name="mdi:cellphone-key" />
          <span>{{ t('cockpit.decide.answerOnDevice',
                     'This posture wants the answer from your device. Confirm there — this pane updates itself.') }}</span>
        </div>
        <div v-else class="dq-actions">
          <button v-if="variant === 'desk' && (!deskCredential || deskKeyDoubt) && deskAuthenticatorAllowed"
                  class="dq-btn" :disabled="enrolling" data-testid="dq-enrol" @click="enrolDesk">
            <Icon name="mdi:fingerprint" />
            {{ enrolling ? t('cockpit.decide.enrolling', 'Enrolling…')
                         : t('cockpit.decide.enrol', 'Enable signing on this device') }}
          </button>
          <input v-if="totpOffered && !canSignHere" v-model="totpCode" class="dq-code" maxlength="8"
                 inputmode="numeric" autocomplete="one-time-code" data-testid="dq-totp"
                 :placeholder="t('cockpit.decide.code', 'code')" />
          <button class="dq-btn dq-btn-yes" :disabled="!canConsent" data-testid="dq-approve" @click="approve">
            <Icon :name="canSignHere ? 'mdi:fingerprint' : 'mdi:check'" />
            <span v-if="waitMs > 0" data-testid="dq-floor-wait">
              {{ tp('cockpit.decide.waiting', 'Read first — {s}s', { s: Math.ceil(waitMs / 1000) }) }}
            </span>
            <span v-else>{{ t('cockpit.decide.approve', 'Approve') }}</span>
          </button>
          <button class="dq-btn dq-btn-no" :disabled="acting" data-testid="dq-deny" @click="denyOpen = !denyOpen">
            <Icon name="mdi:close" /> {{ t('cockpit.decide.deny', 'Deny') }}
          </button>
        </div>
        <ul v-if="denyOpen" class="dq-deny-menu" data-testid="dq-deny-menu">
          <li v-for="r in DENY_REASONS" :key="r">
            <button :data-testid="`dq-deny-${r}`" @click="deny(r)">{{ denyLabel(r) }}</button>
          </li>
        </ul>
      </article>

      <!-- I1 — visible, and inert. -->
      <section v-if="queued.length" class="dq-queue" data-testid="dq-queue">
        <h4>{{ tp('cockpit.decide.queued', '{n} more waiting', { n: rows.length - 1 }) }}</h4>
        <ul>
          <li v-for="c in queued" :key="c.id" class="dq-q-row" data-testid="dq-queued-row" aria-disabled="true">
            <span class="dq-q-verb">{{ c.action_type }}</span>
            <!-- The queue is visible SO THAT it can be planned around, and you cannot
                 plan around asks whose size you cannot see. The unit chip rides along
                 for the same reason it exists at all: the earlier a missing unit is
                 visible, the less chance it is noticed only at the moment of signing. -->
            <span v-if="amountOf(c)" class="dq-q-amt">
              {{ amountOf(c)!.amount }}
              <template v-if="amountOf(c)!.currency">{{ amountOf(c)!.currency }}</template>
              <span v-else class="dq-cur-missing" data-testid="ckd-unit-unrecorded"
                    :title="t('cockpit.decisions.unitUnrecordedHint', 'The challenge did not record a currency. Showing the registry currency here would be a guess.')">
                {{ t('cockpit.decisions.unitUnrecorded', 'unit unrecorded') }}
              </span>
            </span>
            <span class="dq-q-ref">{{ c.action_ref || '—' }}</span>
          </li>
        </ul>
        <p class="dq-q-note">{{ t('cockpit.decide.oneAtATime',
          'One at a time, oldest first. The rest stay visible so you can plan, and inert so you cannot answer the wrong one.') }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.dq { display: flex; flex-direction: column; gap: .5rem; }
.dq-note { margin: 0; font-size: .72rem; color: var(--nc-text-dim, #8b949e); }
.dq-err { color: var(--nc-danger, #f85149); }
.dq-head {
  border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.09));
  border-radius: 8px; padding: .55rem .6rem;
  background: rgba(var(--nc-primary-rgb, 0,229,255), 0.03);
}
.dq-top { display: flex; align-items: baseline; gap: .5rem; }
.dq-verb { flex: 1; font-size: .8rem; font-weight: 600; font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-primary, #e6edf3); }
.dq-posture { font-size: .6rem; letter-spacing: .06em; text-transform: uppercase; padding: 0 .3rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.16); color: var(--nc-text-dim, #8b949e); }
.dq-clock { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .72rem; color: var(--nc-text-dim, #8b949e); }
.dq-clock.is-urgent { color: var(--nc-danger, #f85149); }
.dq-streak { margin: .35rem 0 0; display: flex; align-items: center; gap: .3rem; font-size: .68rem; color: var(--nc-warning, #d29922); }
.dq-propose { margin: .35rem 0 0; display: flex; flex-direction: column; gap: .25rem; align-items: flex-start; }
.dq-propose-form { display: flex; flex-wrap: wrap; gap: .35rem; align-items: center;
  border: 1px dashed rgba(210,153,34,.35); border-radius: 6px; padding: .35rem .45rem; }
.dq-propose-line { margin: 0; flex: 1 1 100%; font-size: .7rem; color: var(--nc-text-secondary, #c9d1d9); }
.dq-propose-hours { display: inline-flex; align-items: center; gap: .25rem; font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
.dq-propose-hours input { width: 4rem; font-size: .72rem; padding: .2rem .3rem; border-radius: 5px;
  border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.14)); background: rgba(0,0,0,.25); color: inherit; }
.dq-propose-note { margin: 0; flex: 1 1 100%; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.dq-diff { margin: .35rem 0 0; display: flex; flex-direction: column; gap: .15rem; }
.dq-diff-h { font-size: .62rem; letter-spacing: .05em; text-transform: uppercase; color: var(--nc-warning, #d29922); }
.dq-diff-row { display: flex; align-items: center; gap: .3rem; font-size: .7rem; }
/* §PREFLIGHT — deliberately DIM and deliberately buttonless. The visual language says
   "read this, you cannot act on it"; the DOM says the same by containing no control. */
.dq-pf {
  border: 1px dashed var(--nc-border-subtle, rgba(255,255,255,.12));
  border-radius: 8px; padding: .45rem .55rem; opacity: .72;
  background: rgba(255,255,255,.015);
}
.dq-pf-head { display: flex; align-items: center; gap: .35rem; }
.dq-pf-icon { font-size: .8rem; color: var(--nc-text-dim, #8b949e); }
.dq-pf-title { flex: 1; font-size: .7rem; letter-spacing: .04em; text-transform: uppercase; color: var(--nc-text-dim, #8b949e); }
.dq-pf-tag { font-size: .58rem; letter-spacing: .05em; text-transform: uppercase; padding: 0 .3rem; border-radius: 3px; border: 1px dashed rgba(255,255,255,.2); color: var(--nc-text-dim, #8b949e); }
.dq-pf-list { list-style: none; margin: .3rem 0 0; padding: 0; display: flex; flex-direction: column; gap: .15rem; }
.dq-pf-row { display: flex; align-items: baseline; gap: .4rem; font-size: .68rem; }
.dq-pf-verb { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-secondary, #c9d1d9); }
.dq-pf-ref { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--nc-text-dim, #8b949e); }
.dq-pf-clock { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-dim, #8b949e); }
.dq-pf-note { margin: .3rem 0 0; font-size: .63rem; color: var(--nc-text-dim, #8b949e); }
/* The divergence banner is the LOUD one: it means the reading you already did was of a
   different thing, so it must not look like the quiet "changed since last time" note. */
.dq-pfdiff {
  margin: .35rem 0 0; display: flex; flex-direction: column; gap: .15rem;
  border-left: 2px solid var(--nc-danger, #f85149); padding-left: .4rem;
}
.dq-pfdiff-h { display: flex; align-items: center; gap: .3rem; font-size: .68rem; font-weight: 600; color: var(--nc-danger, #f85149); }
.dq-pfdiff-icon { font-size: .78rem; }
.dq-diff-row b { color: var(--nc-text-muted, #6e7681); font-weight: 500; }
.dq-diff-row s { color: var(--nc-text-dim, #8b949e); }
.dq-diff-row i { color: var(--nc-warning, #d29922); font-style: normal; font-weight: 600; }
.dq-amount { margin-top: .3rem; display: flex; align-items: baseline; gap: .35rem; flex-wrap: wrap; }
.dq-amt { font-size: .98rem; font-weight: 600; color: var(--nc-text-primary, #e6edf3); }
.dq-cur { font-size: .75rem; color: var(--nc-primary, #00e5ff); letter-spacing: .04em; }
.dq-cur-missing {
  display: inline-flex; align-items: center; gap: .2rem;
  font-size: .66rem; letter-spacing: .03em; color: var(--nc-warning, #d29922);
  border: 1px dashed rgba(210,153,34,.4); border-radius: 4px; padding: 0 .25rem;
}
.dq-cur-icon { width: 11px; height: 11px; }
.dq-lines { margin: .4rem 0 0; display: flex; flex-direction: column; gap: .1rem; }
.dq-line { display: flex; gap: .4rem; font-size: .7rem; }
.dq-line dt { margin: 0; color: var(--nc-text-muted, #6e7681); flex: 0 0 8.5rem; }
.dq-line dd { margin: 0; color: var(--nc-text-secondary, #c9d1d9); min-width: 0; }
/* 🔴 The identifiers on a SIGNING screen are the two longest values and were the two that
   got ellipsised away: his phone showed `did:theprotocol:65f488a8-d8a5-0…` and
   `lm_7e40ca3a0c443f1e0939c3403…` directly above Approve. A value you cannot read is not
   presented, whatever the hash covers. They wrap now instead of truncating.
   ⚠ The VALUE stays the raw identifier on purpose — these lines are inside the
   presentation hash, and a resolved NAME that one surface has and the other does not
   would make two honest surfaces disagree in the same locale, manufacturing exactly the
   tampering signal this batch stopped over-firing. */
.dq-line dd { overflow-wrap: anywhere; word-break: break-word; }
.dq-actions { margin-top: .55rem; display: flex; flex-wrap: wrap; gap: .35rem; align-items: center; }
.dq-btn {
  display: inline-flex; align-items: center; gap: .25rem; cursor: pointer;
  border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.14)); border-radius: 6px;
  background: transparent; color: var(--nc-text-secondary, #c9d1d9);
  font-size: .72rem; padding: .28rem .55rem;
}
.dq-btn:disabled { opacity: .45; cursor: not-allowed; }
.dq-btn-yes { border-color: rgba(63,185,80,.5); color: var(--nc-success, #3fb950); }
.dq-btn-no { border-color: rgba(248,81,73,.4); color: var(--nc-danger, #f85149); }
.dq-code { width: 5.5rem; font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .78rem;
  padding: .25rem .35rem; border-radius: 6px; border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.14));
  background: rgba(0,0,0,.25); color: var(--nc-text-primary, #e6edf3); }
.dq-elsewhere { margin-top: .5rem; display: flex; gap: .35rem; align-items: flex-start;
  font-size: .7rem; color: var(--nc-text-dim, #8b949e); }
.dq-deny-menu { list-style: none; margin: .35rem 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: .25rem; }
.dq-deny-menu button {
  cursor: pointer; font-size: .68rem; padding: .2rem .45rem; border-radius: 5px;
  border: 1px solid rgba(248,81,73,.3); background: transparent; color: var(--nc-text-secondary, #c9d1d9);
}
.dq-msg { margin: .4rem 0 0; font-size: .7rem; color: var(--nc-text-secondary, #c9d1d9); }
.dq-queue { border-top: 1px dashed var(--nc-border-subtle, rgba(255,255,255,.09)); padding-top: .4rem; }
.dq-queue h4 { margin: 0 0 .25rem; font-size: .66rem; letter-spacing: .05em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.dq-queue ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .15rem; }
.dq-q-row { display: flex; gap: .5rem; font-size: .68rem; opacity: .55; }
.dq-q-verb { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-secondary, #c9d1d9); }
.dq-q-amt { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-text-secondary, #c9d1d9); }
.dq-q-ref { color: var(--nc-text-muted, #6e7681); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dq-q-note { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.dq--phone .dq-line dt { flex: 0 0 6.5rem; }
</style>
