import { isLedgerRefusalAsItCame, routeCameBackSentence } from '@/services/api/ledgerRefusal'

/**
 * §FESUITE (2026-10-05): what a failed value-moving request tells the person who pressed. A response below 500 is the
 * server's answer: the request was refused and nothing moved (a 4xx), so the next press is a new request. No response at
 * all (a network error, a timeout, an abort) or a 5xx is NOT an answer: the registry or the TEG behind it could not say,
 * and the value may have moved (a late TEG answer is a 503). That outcome is unknown, never "failed": a person told
 * "Send failed" presses again, and a second press with a new Idempotency-Key is a second payment. An unknown outcome keeps
 * the request's key, so pressing again asks once more and the server answers from its claim instead of paying twice.
 */
export type FailedSendOutcome = 'refused' | 'unknown'

/**
 * §REPATLANE-5 (V0606): an answer below 500 that is no refusal. The registry answers some sends whose money may have moved
 * with a 4xx (an FX route's "(outcome not known): nothing refunded, held" is a 409), and a send while an earlier one under
 * the same key still runs with a 422. Read as a refusal, the next press got a NEW key and sent the payment a second time.
 * These sentences are the payout lane's (services/payout_outcome.py _MOVED and _CLAIMED, pinned the same by a test): a 4xx
 * carrying one is unknown, so the key stays and the server answers the repeat with what the earlier send left.
 */
export const MAY_HAVE_MOVED = [
  '(outcome not known)',
  'the ingress is parked at the gateway',
  'failed post-conversion',
  'partial commit',
  'core swap did not complete',
] as const
export const STILL_CLAIMED = ['is claimed on this endpoint', 'already in progress'] as const

function answerText(e: unknown): string {
  const data = (e as { response?: { data?: unknown } } | null)?.response?.data
  if (data === undefined || data === null) return ''
  if (typeof data === 'string') return data
  try {
    return JSON.stringify(data)
  } catch {
    return ''
  }
}

export function failedSendOutcome(e: unknown): FailedSendOutcome {
  const status = (e as { response?: { status?: unknown } } | null)?.response?.status
  if (typeof status === 'number' && status >= 400 && status < 500) {
    const low = answerText(e).toLowerCase()
    return [...MAY_HAVE_MOVED, ...STILL_CLAIMED].some(s => low.includes(s)) ? 'unknown' : 'refused'
  }
  // §LEDGERGATE: the TEG's ledger gate answered, and its answer is that nothing moved (a 503 passed on whole); or the
  // route's own answer that the payment came back (V0605)
  return isLedgerRefusalAsItCame(e) || routeCameBackSentence(e) !== null ? 'refused' : 'unknown'
}

/** One key per request: the same recipient, amount and memo keep it until the server has answered (a success or a
 *  refusal); anything else gets a new one. */
export class SendKey {
  private key: string | null = null
  private intent = ''

  constructor(private readonly mint: () => string) {}

  for(intent: string): string {
    if (!this.key || this.intent !== intent) {
      this.key = this.mint()
      this.intent = intent
    }
    return this.key
  }

  /** the server answered (a success or a refusal): the next press is a new request */
  answered(): void {
    this.key = null
    this.intent = ''
  }
}

/** §REPATLANE-7: the header the registry puts on an answer it gives again under the same Idempotency-Key (the payment an
 *  earlier press already made, answered again; nothing moved a second time). */
export const REPLAYED_HEADER = 'idempotent-replayed'

/** The answer, marked `replayed: true` when the registry says it is an earlier request's own (axios headers or a plain
 *  object; any other shape is left as it came). */
export function markReplayed<T>(data: T, headers: unknown): T {
  let v: unknown
  const h = headers as { get?: (k: string) => unknown } & Record<string, unknown> | null | undefined
  if (h && typeof h.get === 'function') v = h.get(REPLAYED_HEADER)
  if (v === undefined && h && typeof h === 'object') v = h[REPLAYED_HEADER] ?? h['Idempotent-Replayed']
  if (String(v ?? '').toLowerCase() === 'true' && data && typeof data === 'object' && !Array.isArray(data)) {
    return { ...(data as object), replayed: true } as T
  }
  return data
}

/** The answer is an earlier press's own payment, given again (markReplayed). */
export function answeredAgain(answer: unknown): boolean {
  return !!answer && typeof answer === 'object' && (answer as { replayed?: unknown }).replayed === true
}

/** §REPATLANE-7: the reference of a sent payment. /teg/send answers it as `transfer_id` (SmartSendResponse) and keeps the
 *  inner endpoint's answer under `detail`; the console read `transaction_id`, which it never carries, so every send said
 *  "confirmed" instead of its reference, and a receipt (the one a priced contact opens its thread with) had none. */
export function sendReference(answer: unknown): string {
  if (!answer || typeof answer !== 'object') return ''
  const a = answer as Record<string, unknown>
  const d = (a.detail && typeof a.detail === 'object' ? a.detail : {}) as Record<string, unknown>
  for (const v of [a.transfer_id, a.transaction_id, d.transaction_id, d.transfer_id, d.swap_id]) {
    if (typeof v === 'string' && v.trim()) return v.trim()
  }
  return ''
}
