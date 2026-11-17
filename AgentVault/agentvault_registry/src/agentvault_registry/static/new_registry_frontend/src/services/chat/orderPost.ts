/**
 * V0662 (OurChat lane, the batch's item 5): `/order  <bounty> [CCY] <title>` in the composer.
 *
 * The command opens a DOOR, it posts nothing: a Guild order locks its bounty from the posting agent in the Guild's escrow, so a
 * person fills a small form and presses a button that says how much it locks. The post goes through the Guild's own rail
 * (POST /api/v1/guild/orders, with `room_id` so the Guild rail shows the order as one card in this conversation and keeps it
 * current); this builds the body and refuses what the rail would refuse, so a person sees why before anything is sent. Moves
 * no money by itself and invents no money path.
 */
export const DEADLINE_DAYS = [1, 3, 7, 14, 30] as const
export const TITLE_MAX = 200
export const SPEC_MAX = 8000
const DAY_S = 86_400

export interface OrderForm { title: string; bounty: string; currency: string; spec: string; deadlineDays: number; showInRoom: boolean }
export interface OrderBody { title: string; bounty: number; currency: string; spec?: string; deadline_seconds: number; room_id?: string }
export type OrderRefusal = 'title' | 'bounty' | 'currency' | 'spec' | 'deadline'

/** A bounty typed by a person: "12,5" and "12.5" alike; a positive finite number or null. */
export function parseBounty(raw: string | number | null | undefined): number | null {
  const n = typeof raw === 'number' ? raw : Number(String(raw ?? '').trim().replace(',', '.'))
  return Number.isFinite(n) && n > 0 ? n : null
}

/** The body the Guild rail takes, or the first thing a person has to fix. `roomId` is this conversation's id (sent only when the
 *  person wants the order shown here). */
export function orderBody(f: OrderForm, roomId: string | null): { ok: true; body: OrderBody } | { ok: false; reason: OrderRefusal } {
  const title = f.title.trim()
  if (!title || title.length > TITLE_MAX) return { ok: false, reason: 'title' }
  const bounty = parseBounty(f.bounty)
  if (bounty === null) return { ok: false, reason: 'bounty' }
  const currency = f.currency.trim().toUpperCase()
  if (!/^[A-Z]{2,12}$/.test(currency)) return { ok: false, reason: 'currency' }
  const spec = f.spec.trim()
  if (spec.length > SPEC_MAX) return { ok: false, reason: 'spec' }
  if (!(DEADLINE_DAYS as readonly number[]).includes(f.deadlineDays)) return { ok: false, reason: 'deadline' }
  const body: OrderBody = { title, bounty, currency, deadline_seconds: f.deadlineDays * DAY_S }
  if (spec) body.spec = spec
  if (f.showInRoom && roomId) body.room_id = roomId
  return { ok: true, body }
}
