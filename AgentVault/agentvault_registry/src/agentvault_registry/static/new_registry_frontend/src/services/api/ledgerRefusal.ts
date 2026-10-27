/**
 * §LEDGERGATE (2026-10-11): the TEG's "the ledger cannot record this right now" refusal, found in an API error.
 *
 * The TEG refuses a value movement while its ledger cannot record it: 503 with the detail "ledger_unavailable: The
 * ledger cannot record this right now. Nothing was moved. Try again shortly." The registry passes it on as it came
 * (/teg/transfer, with Retry-After) or inside its own words (the AGORA mover: "order deposit failed: exchange mover
 * 503: ledger_unavailable: ..."). Nothing moved, so the person is told that sentence, never "Server Error"; the
 * client does not send a write again on its own (mayResendOnItsOwn), the person decides.
 */
export const LEDGER_MARKER = 'ledger_unavailable:'
export const LEDGER_SENTENCE = 'The ledger cannot record this right now. Nothing was moved. Try again shortly.'
/** §LEDGERGATE (V0605): an FX route's answer when the receiving frame's ledger was down and the gateway returned the payment
 *  before anything converted (services/ledger_unavailable.py ROUTE_CAME_BACK; tests pin the two the same). */
export const ROUTE_CAME_BACK = "The receiving frame's ledger cannot record this right now. Your payment came back to you. Try again shortly."

/** The route's came-back refusal passed on whole (a 503 whose whole detail is that sentence): the payment came back, so a
 *  send that met it is refused, never "may have gone through". The sentence to say, else null. */
export function routeCameBackSentence(error: unknown): string | null {
  const res = (error as { response?: { status?: unknown, data?: unknown } } | null | undefined)?.response
  if (res?.status !== 503) return null
  const data = res.data as { detail?: unknown } | string | undefined
  const detail = typeof data === 'string' ? data : (typeof data?.detail === 'string' ? data.detail : '')
  return detail.trim() === ROUTE_CAME_BACK ? ROUTE_CAME_BACK : null
}

/** The sentence to show for an error that is the ledger gate's refusal, else null. */
export function ledgerRefusalSentence(error: unknown): string | null {
  const data = (error as { response?: { data?: unknown } } | null | undefined)?.response?.data as
    | { detail?: unknown, code?: unknown }
    | string
    | undefined
  const detail = typeof data === 'string' ? data : (typeof data?.detail === 'string' ? data.detail : '')
  const at = detail.indexOf(LEDGER_MARKER)
  const code = typeof data === 'object' && data !== null ? data.code : undefined
  if (at < 0 && code !== 'ledger_unavailable') return null
  // the sentence runs to the end of the detail, or to the quote, brace or backslash that closes it where a route wrapped
  // the TEG's words in its own JSON (V0596's /teg/send: {"smart_send_method": ..., "inner": "ledger_unavailable: ..."})
  const sentence = at >= 0 ? (detail.slice(at + LEDGER_MARKER.length).match(/^[^"'}\]\\]*/)?.[0] ?? '').trim() : ''
  return sentence || LEDGER_SENTENCE
}

/**
 * The gate's refusal passed on whole (a 503 whose detail starts with the marker, or that carries the gate's code): the
 * TEG moved nothing, so a send that met it is refused, never "may have gone through". A path that wrapped the words in its
 * own (a 502 from the AGORA mover, a multi-step route) is not this: something else may have moved, so it stays unknown.
 */
export function isLedgerRefusalAsItCame(error: unknown): boolean {
  const res = (error as { response?: { status?: unknown, data?: unknown } } | null | undefined)?.response
  if (res?.status !== 503) return false
  const data = res.data as { detail?: unknown, code?: unknown } | string | undefined
  const detail = typeof data === 'string' ? data : (typeof data?.detail === 'string' ? data.detail : '')
  const code = typeof data === 'object' && data !== null ? data.code : undefined
  return detail.trim().startsWith(LEDGER_MARKER) || code === 'ledger_unavailable'
}

/**
 * §LEDGERGATE (V0598): the sentence to SAY, only when the refusal came whole: the TEG moved nothing, so "Nothing was
 * moved" is true. A refusal inside a route's own words (a route of several legs, one of which may have moved before the
 * refusal) is left to those words, which name what happened; since V0598 every single-movement route passes it whole.
 */
export function wholeLedgerRefusalSentence(error: unknown): string | null {
  return isLedgerRefusalAsItCame(error) ? ledgerRefusalSentence(error) : null
}

/**
 * §LEDGERGATE (V0599): a message a component is about to show (most often an API error's raw `detail`) that IS the gate's
 * refusal as it came ("ledger_unavailable: <the sentence>"): the sentence alone, else null. A route's own words that
 * carry the code word inside them ("leg 2: ledger_unavailable: ...") stay theirs: they may name a leg that moved.
 */
export function wholeLedgerMessage(message: unknown): string | null {
  if (typeof message !== 'string') return null
  const m = message.trim()
  if (!m.startsWith(LEDGER_MARKER)) return null
  const sentence = (m.slice(LEDGER_MARKER.length).match(/^[^"'}\]\\]*/)?.[0] ?? '').trim()
  return sentence || LEDGER_SENTENCE
}
