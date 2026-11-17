/**
 * V0662 (OurChat lane): pinned messages, the console's pure rules (the registry's: services/chat_pins.py,
 * PUT/DELETE /chat/conversations/{id}/messages/{mid}/pin, GET .../pins).
 *
 * The registry keeps the pins and says who may pin (`can_pin`); the thread draws them in a strip under its header and offers
 * Pin / Unpin on a line. This holds what is worth testing apart from the view: which lines are pinned, what a pin shows,
 * and whether to offer the control on a line.
 */
export interface PinRow { message: Record<string, any>; pinned_by?: { name?: string | null } | null; at?: string | null }

/** The ids of the pinned messages. */
export function pinnedIds(pins: PinRow[] | null | undefined): Set<string> {
  return new Set((Array.isArray(pins) ? pins : []).map((p) => String(p?.message?.id || '')).filter(Boolean))
}

/** What a pin shows of its line: the words (whitespace folded, cut with an ellipsis), or a card's title or type. */
export function pinSummary(m: Record<string, any> | null | undefined, max = 90): string {
  if (!m) return ''
  let text = ''
  if (m.kind === 'card') text = String(m.card?.data?.title || m.card?.data?.name || m.card?.type || '')
  else text = String(m.body || '')
  text = text.replace(/\s+/g, ' ').trim()
  return text.length > max ? `${text.slice(0, Math.max(0, max - 1))}…` : text
}

/** Whether Pin / Unpin is offered on a line: the registry lets this reader pin here, and the line is a real one. */
export function canOfferPin(m: Record<string, any> | null | undefined, canPin: boolean): boolean {
  return !!canPin && !!m && !!m.id && !m.deleted && m.kind !== 'system'
}
