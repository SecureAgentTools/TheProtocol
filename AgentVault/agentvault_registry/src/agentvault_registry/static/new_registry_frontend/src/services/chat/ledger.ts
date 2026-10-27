/**
 * services/chat/ledger.ts — §OURSTATE-2 `/ledger`: where you and this
 * counterparty stand, computed from the thread you are looking at.
 *
 * `/audit` answers "who are they"; `/ledger` answers "where do we stand".
 *
 * TWO RULES, both structural:
 *  1. LOCAL-ONLY. It reads the cards already loaded in this thread — no new
 *     endpoint, no server aggregation, nothing about the counterparty that the
 *     thread did not already tell you. It is a summary of your own view.
 *  2. IT STATES ITS BOUND. A thread page is capped (PAGE_MAX) and burn-for-me
 *     hides rows, so this can never be "the totals" — it is "the totals from
 *     the last N messages I can see", and `bounds` carries exactly that so the
 *     renderer can print it. A number without its window is a lie by omission
 *     (the honest-caption discipline).
 *
 * Currency-honest: amounts NEVER cross currencies. Each currency gets its own
 * line — a summed total across BVT and AVT would be a fabricated number
 * (§FOREIGNACT: empty unit, never the wrong unit).
 */
import type { ChatCard } from './cards'

export interface LedgerMessageLike {
  seq?: number
  kind?: string
  card?: ChatCard | null
  sender_ptype?: string
  sender_id?: string
  deleted?: boolean
}

export interface LedgerLine {
  currency: string
  paidByYou: number
  paidToYou: number
  net: number            // + = they owe you, − = you owe them (settled flows only)
  requestedOfYou: number
  requestedOfThem: number
}

export interface LedgerOpenItem {
  kind: 'pay.request' | 'service.call' | 'contract.offer' | 'guild.order'
  label: string
  amount: string | null
  currency: string | null
  ref: string | null
  mine: boolean
}

export interface LedgerView {
  lines: LedgerLine[]
  open: LedgerOpenItem[]
  counted: number
  bounds: { messages: number; firstSeq: number | null; lastSeq: number | null; clipped: boolean }
  empty: boolean
}

const num = (v: any): number => {
  const n = Number(String(v ?? '').replace(',', '.'))
  return Number.isFinite(n) ? n : 0
}

/**
 * @param messages the loaded thread page (oldest → newest)
 * @param isMine   predicate: was this message sent by the viewer's household?
 * @param pageBound the server's stated page cap, for the honest window line
 */
export function buildLedger(
  messages: LedgerMessageLike[],
  isMine: (m: LedgerMessageLike) => boolean,
  pageBound = 40,
): LedgerView {
  const byCcy = new Map<string, LedgerLine>()
  const line = (ccy: string): LedgerLine => {
    let l = byCcy.get(ccy)
    if (!l) {
      l = { currency: ccy, paidByYou: 0, paidToYou: 0, net: 0, requestedOfYou: 0, requestedOfThem: 0 }
      byCcy.set(ccy, l)
    }
    return l
  }
  const open: LedgerOpenItem[] = []
  let counted = 0
  const visible = messages.filter(m => !m.deleted)

  for (const m of visible) {
    const c = m.kind === 'card' ? m.card : null
    if (!c || c.v !== 1) continue
    const d: any = c.data || {}
    const mine = isMine(m)
    counted++
    switch (c.type) {
      case 'pay.receipt': {
        // A receipt is a CLAIM with a ledger ref (the card's own words) — it is
        // counted as a settled flow because that is what it asserts; the ref is
        // what the reader verifies against their activity.
        if (!d.currency) break
        const l = line(String(d.currency))
        const amt = num(d.amount)
        if (mine) { l.paidByYou += amt; l.net -= amt } else { l.paidToYou += amt; l.net += amt }
        break
      }
      case 'pay.request': {
        if (!d.currency) break
        const l = line(String(d.currency))
        const amt = num(d.amount)
        if (mine) l.requestedOfThem += amt; else l.requestedOfYou += amt
        open.push({ kind: 'pay.request', label: String(d.memo || 'payment request'),
                    amount: d.amount != null ? String(d.amount) : null,
                    currency: String(d.currency), ref: null, mine })
        break
      }
      case 'service.result': {
        // Only a SETTLED call moved money; a delivered-but-unsettled one is an
        // open item, said in those words rather than counted as paid.
        const ccy = d.paid_currency ? String(d.paid_currency) : null
        const settled = String(d.settlement_status || '') === 'settled'
        if (ccy && settled) {
          const l = line(ccy)
          const amt = num(d.paid_amount)
          if (mine) { l.paidByYou += amt; l.net -= amt } else { l.paidToYou += amt; l.net += amt }
        } else if (d.paid_amount != null && !settled) {
          open.push({ kind: 'service.call', label: 'service call — delivered, not settled',
                      amount: String(d.paid_amount), currency: ccy, ref: null, mine })
        }
        break
      }
      case 'contract.offer':
      case 'guild.order':
        open.push({ kind: c.type, label: String(d.title || c.type),
                    amount: d.amount != null ? String(d.amount) : null,
                    currency: d.currency ? String(d.currency) : null,
                    ref: d.ref ? String(d.ref) : null, mine })
        break
      default:
        counted--   // not an economic card; it is not part of the count
    }
  }

  const seqs = visible.map(m => Number(m.seq || 0)).filter(n => n > 0)
  const firstSeq = seqs.length ? Math.min(...seqs) : null
  const lastSeq = seqs.length ? Math.max(...seqs) : null
  return {
    lines: [...byCcy.values()].sort((a, b) => a.currency.localeCompare(b.currency)),
    open,
    counted,
    bounds: {
      messages: visible.length,
      firstSeq, lastSeq,
      // Clipped when the page is full (older history exists) OR when burn /
      // deletion removed rows — either way the window is not the whole story.
      clipped: visible.length >= pageBound ||
        (firstSeq != null && lastSeq != null && (lastSeq - firstSeq + 1) > visible.length),
    },
    empty: byCcy.size === 0 && open.length === 0,
  }
}
