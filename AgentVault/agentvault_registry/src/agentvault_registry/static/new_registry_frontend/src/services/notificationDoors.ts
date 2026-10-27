/**
 * services/notificationDoors.ts — §POCKETBRIDGE5 W-B.
 *
 * ONE pure mapping from a typed notification (mig 0139 feed: `type_key` +
 * `click`) to the pocket surface that answers it. The backend has carried
 * type_key and click end-to-end since §NOTIFV2 — the FE simply never consumed
 * the feed; rows rendered and went nowhere.
 *
 * Rules:
 *  1. A click URL that already points INTO pocket wins verbatim (the
 *     price-alert watcher and push-login already emit pocket-native clicks,
 *     query included).
 *  2. Otherwise the TYPE decides the pocket door. Most emit sites carry
 *     desktop clicks (`/ui/#/guild` …) — on a phone the type is the truth.
 *  3. A type with no pocket door returns null: the row is the message, and a
 *     tap marks it read without pretending there is somewhere to go.
 *
 * Pure and unit-tested (S6): no router, no store, no window.
 */

export interface NotifDoorInput {
  type_key?: string | null
  click?: string | null
}

export interface NotifDoor {
  path: string
  query?: Record<string, string>
}

/** A click that already targets pocket (`…#/pocket/…`, query preserved). */
export function pocketClick(click?: string | null): NotifDoor | null {
  if (!click) return null
  const m = String(click).match(/#(\/pocket\/[^?#\s]*)(?:\?([^#\s]*))?/)
  if (!m) return null
  const query: Record<string, string> = {}
  if (m[2]) for (const [k, v] of new URLSearchParams(m[2])) query[k] = v
  return Object.keys(query).length ? { path: m[1], query } : { path: m[1] }
}

export function doorForNotification(e: NotifDoorInput): NotifDoor | null {
  const direct = pocketClick(e.click)
  if (direct) return direct

  const t = String(e.type_key || '')
  if (!t) return null

  // Security first — approvals are the phone's home turf.
  if (t === 'security.login_approval') return { path: '/pocket/approve-login' }
  if (t === 'security.spend_approval') return { path: '/pocket/approvals' }
  if (t.startsWith('security.') || t.startsWith('account.')) return { path: '/pocket/approvals' }

  // Work record — the WORK modal lanes (A': ?work= opens it on the lane).
  if (t.startsWith('dispute.')) return { path: '/pocket/home', query: { work: 'disputes' } }
  if (t.startsWith('contract.') || t === 'jurisdiction.countersign_broken') {
    return { path: '/pocket/home', query: { work: 'contracts' } }
  }

  // The labor market and the venue.
  if (t.startsWith('guild.')) return { path: '/pocket/payments' }
  if (t.startsWith('exchange.')) return { path: '/pocket/trade' }

  // Agent lifecycle and authority.
  if (t.startsWith('capability.') || t.startsWith('delegation.') || t.startsWith('agent.')) {
    return { path: '/pocket/agents' }
  }

  // Units that landed — the home screen.
  if (t === 'money.received' || t === 'staking.rewards' || t === 'funding.decided'
    || t.startsWith('fiat.') || t === 'forge.royalty_received') {
    return { path: '/pocket/home' }
  }

  // Broadcasts, ops, cicd, evals: the row is the message.
  return null
}
