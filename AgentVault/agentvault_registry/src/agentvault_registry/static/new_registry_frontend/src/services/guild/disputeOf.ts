// V0658 (d), polish 16 of the disputes discovery: Pocket's "View the dispute record" opened the dispute LIST. A rejected
// Guild order files its dispute and records the id on the order's 'disputed' event (routers/guild.py verify:
// payload.ddr_dispute); Pocket's shell already opens one dispute from ?dispute=<id> (PocketShell.vue).

export interface OrderEvent {
  seq?: number
  event_type?: string
  payload?: unknown
}

function payloadOf(e: OrderEvent): Record<string, any> {
  const p = e?.payload
  if (typeof p === 'string') {
    try { return JSON.parse(p) || {} } catch { return {} }
  }
  return p && typeof p === 'object' ? (p as Record<string, any>) : {}
}

/** The order's dispute as a string id, or null: the order's own dispute_id first (the poster's reject and the deadline
 *  sweep both set it; the sweep writes no ddr_dispute in its event), else its latest 'disputed' event's. */
export function disputeIdOf(events: OrderEvent[] | undefined | null, order?: { dispute_id?: unknown } | null): string | null {
  const own = order?.dispute_id
  if (own !== undefined && own !== null && String(own) !== '') return String(own)
  const disputed = (events || []).filter((e) => e?.event_type === 'disputed')
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
  for (let i = disputed.length - 1; i >= 0; i--) {
    const id = payloadOf(disputed[i]).ddr_dispute
    if (id !== undefined && id !== null && String(id) !== '') return String(id)
  }
  return null
}

/** Pocket's route query for the door: the dispute itself when its id is known, else the dispute list. */
export function disputeDoorQuery(query: Record<string, any>, events: OrderEvent[] | undefined | null,
                                 order?: { dispute_id?: unknown } | null): Record<string, any> {
  const id = disputeIdOf(events, order)
  return id ? { ...query, dispute: id } : { ...query, work: 'disputes' }
}
