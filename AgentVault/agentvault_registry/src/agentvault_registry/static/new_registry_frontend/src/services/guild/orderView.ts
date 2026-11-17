// V0662 console polish, item 3 (order gwo_0aa7b875cbf65b6347f5f775): the Guild order page in words.
//
// The page showed the delivery as raw JSON, each event by its stored name (xf_stage_retained) and each party as fifteen
// characters of a DID. These are the page's words: a delivery as fields a person can copy, an event as a word (the
// stored name stays for the hover), a party by the name the order's answer gives (`names`, the DID on hover).

type T = (key: string, fallback: string) => string

export interface DeliveryField {
  key: string
  label: string
  value: string
  copy: boolean
  /** Only an http or https address is ever a link. */
  href?: string
  /** A second line under the value (a commit's repository). */
  detail?: string
}

const KNOWN = ['uri', 'text', 'hash', 'commits'] as const

function present(v: unknown): boolean {
  return v !== null && v !== undefined && !(typeof v === 'string' && v.trim() === '')
}

function asText(v: unknown): string {
  if (typeof v === 'string') return v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try { return JSON.stringify(v) } catch { return String(v) }
}

function httpHref(v: string): string | undefined {
  try {
    const u = new URL(v)
    return u.protocol === 'http:' || u.protocol === 'https:' ? v : undefined
  } catch { return undefined }
}

/** 'some_key' or 'someKey' -> 'Some key'. */
export function humanize(name: string): string {
  const words = String(name || '').replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ').trim().toLowerCase()
  return words ? words[0].toUpperCase() + words.slice(1) : ''
}

/** The delivery's fields: the link, the note, the hash, each commit, then any other key by its name. */
export function deliveryFields(deliverable: unknown, t: T): DeliveryField[] {
  if (!deliverable || typeof deliverable !== 'object' || Array.isArray(deliverable)) {
    return present(deliverable) ? [{ key: 'value', label: t('guild.deliv.value', 'Delivery'), value: asText(deliverable), copy: true }] : []
  }
  const d = deliverable as Record<string, unknown>
  const out: DeliveryField[] = []
  if (present(d.uri)) {
    const value = asText(d.uri)
    out.push({ key: 'uri', label: t('guild.deliv.link', 'Link'), value, copy: true, href: httpHref(value) })
  }
  if (present(d.text)) out.push({ key: 'text', label: t('guild.deliv.note', 'Note'), value: asText(d.text), copy: true })
  if (present(d.hash)) out.push({ key: 'hash', label: t('guild.deliv.hash', 'Hash'), value: asText(d.hash), copy: true })
  if (Array.isArray(d.commits)) {
    d.commits.forEach((c: any, i: number) => {
      const commit = c && typeof c === 'object' ? c.commit ?? c.sha : c
      if (!present(commit)) return
      const repo = c && typeof c === 'object' && present(c.repo) ? asText(c.repo) : undefined
      out.push({ key: `commit:${i}`, label: t('guild.deliv.commit', 'Commit'), value: asText(commit), copy: true, detail: repo })
    })
  } else if (present(d.commits)) {
    out.push({ key: 'commits', label: t('guild.deliv.commits', 'Commits'), value: asText(d.commits), copy: true })
  }
  for (const k of Object.keys(d).filter((k) => !(KNOWN as readonly string[]).includes(k)).sort()) {
    if (!present(d[k])) continue
    out.push({ key: k, label: humanize(k) || k, value: asText(d[k]), copy: true })
  }
  return out
}

// every event_type the registry writes to guild_order_events (routers/guild.py _audit, the order reaper,
// services/quantum_acceptance; `refunded` from older rows); a new one still reads as its words through humanize()
const EVENT_WORDS: Record<string, [string, string]> = {
  posted: ['guild.ev.posted', 'Posted'],
  bid: ['guild.ev.bid', 'Bid placed'],
  awarded: ['guild.ev.awarded', 'Awarded'],
  submitted: ['guild.ev.submitted', 'Work submitted'],
  settling: ['guild.ev.settling', 'Paying out'],
  verified: ['guild.ev.verified', 'Accepted'],
  settled: ['guild.ev.settled', 'Paid out'],
  refunded: ['guild.ev.refunded', 'Refunded'],
  disputed: ['guild.ev.disputed', 'Disputed'],
  resolving: ['guild.ev.resolving', 'Dispute being resolved'],
  cancelled: ['guild.ev.cancelled', 'Cancelled'],
  expired: ['guild.ev.expired', 'Expired'],
  stuck_reverted: ['guild.ev.stuckReverted', 'Stuck payout put back'],
  eval_bounty_scored: ['guild.ev.evalScored', 'Evaluation scored'],
  xf_stage_retained: ['guild.ev.xfStageRetained', 'Cross-frame stage kept'],
  quantum_test_agreed: ['guild.ev.quantumAgreed', 'Acceptance test agreed'],
  quantum_verdict: ['guild.ev.quantumVerdict', 'Acceptance test verdict'],
}

export function eventWord(type: string | null | undefined, t: T): string {
  const k = String(type || '')
  const w = EVENT_WORDS[k]
  if (w) return t(w[0], w[1])
  return humanize(k) || t('guild.ev.unknown', 'Event')
}

export function shortDid(d?: string | null): string {
  return !d ? '—' : d.length > 26 ? d.slice(0, 15) + '…' + d.slice(-5) : d
}

/** A party as the page names it: "you" for the reader, the card's name, else the DID shortened. */
export function partyLabel(did: string | null | undefined, names: Record<string, string | null> | null | undefined,
  isMe: boolean, t: T): string {
  if (!did) return '—'
  if (isMe) return t('guild.you', 'you')
  const n = names?.[did]
  return typeof n === 'string' && n.trim() ? n : shortDid(did)
}
