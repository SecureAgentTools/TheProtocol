// §FEDLICENCE (2026-09-28, agentvault2-a4's review item 5): which network-licence state the registry-card viewer shows.
// A peer signs its own card, so the card's `federation.licence.state` is what the peer says about ITSELF: a frame whose
// licence was revoked can still publish "licensed". For a peer the viewer shows THIS registry's verdict (the envelope's
// licence_state, from our own peer row) and labels the card's value "as the card states"; with no verdict here it says so
// and never borrows the card's claim. On this registry's own card the block IS our own derivation.

export const LICENCE_LABELS: Record<string, string> = {
  genesis: 'Genesis (the network root)',
  licensed: 'Licensed',
  unlicensed: 'Standalone (not licensed for federation)',
  unverified: 'Unverified',
  expired: 'Expired',
  revoked: 'Revoked',
  suspended: 'Suspended',
  invalid: 'Invalid',
  'same-domain': 'Same trust domain (not a crossing)',
}

// the verdicts FEDERATION_LICENCE_MODE=enforce refuses (services/federation_licence.py REFUSED_STATES)
export const REFUSED_LICENCE_STATES: readonly string[] = ['unlicensed', 'expired', 'revoked', 'suspended', 'invalid']

export type LicenceTone = 'ok' | 'refused' | 'neutral' | 'unmeasured'

export function licenceLabel(s: unknown): string {
  const k = String(s ?? '').trim()
  return k ? (LICENCE_LABELS[k] || k) : '—'
}

// An OPERATOR carries no network licence of its own: the block on its card is the licence of the frame it rides (the
// operator's own licence sits beside it). "Genesis (the network root)" on an operator's card read as if the operator were
// the root (agentvault2-41's production visitor probe, 2026-09-28), so on an operator's card a passing state names the
// frame it comes through. Every other state, and every frame's card, reads as before.
export function licenceLabelRiding(s: unknown, ridesFrame?: string | null): string {
  const k = String(s ?? '').trim()
  const frame = String(ridesFrame ?? '').trim()
  if (!frame || (k !== 'genesis' && k !== 'licensed')) return licenceLabel(s)
  return `${k === 'genesis' ? 'Genesis' : 'Licensed'} (via its frame, ${frame})`
}

export function licenceOk(s: unknown): boolean {
  return s === 'genesis' || s === 'licensed'
}

export function licenceTone(s: unknown): LicenceTone {
  const k = String(s ?? '').trim()
  if (licenceOk(k)) return 'ok'
  if (REFUSED_LICENCE_STATES.includes(k)) return 'refused'
  return 'neutral'
}

export interface LicenceRow {
  text: string             // the state shown as the verdict
  tone: LicenceTone
  hint: string             // whose statement it is, when it was reached, why
  cardSays: string | null  // a peer's own claim, for the view to label "as the card states"; null on self
}

export function licenceRow(args: {
  isSelf: boolean
  cardState?: string | null
  ourState?: string | null
  ourReason?: string | null
  ourCheckedAt?: string | null
  ridesFrame?: string | null  // an operator's card: the trust domain of the frame whose licence it carries
}): LicenceRow | null {
  const card = String(args.cardState ?? '').trim() || null
  if (args.isSelf) {
    if (!card) return null
    return {
      text: licenceLabelRiding(card, args.ridesFrame), tone: licenceTone(card), cardSays: null,
      hint: "This registry's own licence, derived from the certificates it holds.",
    }
  }
  const ours = String(args.ourState ?? '').trim() || null
  if (!ours && !card) return null
  const cardSays = card ? licenceLabelRiding(card, args.ridesFrame) : null
  if (!ours) {
    return {
      text: 'not evaluated here', tone: 'unmeasured', cardSays,
      hint: "This registry has not reached a verdict about this peer's licence (no network configured here, or not " +
        'checked yet). The card only says what the peer states about itself.',
    }
  }
  const when = String(args.ourCheckedAt ?? '').slice(0, 16).replace('T', ' ')
  const why = String(args.ourReason ?? '').trim()
  return {
    text: licenceLabel(ours), tone: licenceTone(ours), cardSays,
    hint: `This registry's own verdict${when ? `, checked ${when} UTC` : ''}${why ? `: ${why}` : ''}.`,
  }
}
