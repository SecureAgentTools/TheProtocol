/**
 * services/guildActions.ts — §POCKETBRIDGE2 W5 (#PK18, the guild brain).
 *
 * ONE derivation of "who am I on this order and what can I do about it",
 * shared by PocketEarn, BridgeWorkView and GuildBoard. Before this module the
 * NEEDS YOU queue advertised "work awarded to you" and "deliveries to verify"
 * while Pocket could only browse and bid — doors onto walls (the §R5 class).
 *
 * Pure functions over the order shape `guild/mine` and `guild/orders/{id}`
 * return (S6): no fetching here, no component state, fully unit-tested. The
 * EXECUTION stays on guildApi — the rails all exist; this module decides which
 * of them the current human may be offered, and says WHY when none (S5).
 */

export type GuildRole = 'poster' | 'worker' | 'observer'

export interface GuildOrderLike {
  id?: string | number
  status?: string
  poster_did?: string
  worker_did?: string
  bid_count?: number
}

export interface GuildActionOffer {
  key: 'award' | 'submit' | 'verify' | 'cancel' | 'bid'
  label: string
  /** true = this action settles money (verify-accept releases the bounty) — S8 step-up applies. */
  money?: boolean
  danger?: boolean
}

export function roleOn(order: GuildOrderLike | null | undefined, myDid: string | null | undefined): GuildRole {
  if (!order || !myDid) return 'observer'
  if (String(order.poster_did || '') === myDid) return 'poster'
  if (String(order.worker_did || '') === myDid) return 'worker'
  return 'observer'
}

const st = (o: GuildOrderLike | null | undefined) => String(o?.status || '').toLowerCase()

/**
 * The offer set for one order. `note` explains an EMPTY set — a blocked
 * surface that does not say why is a defect, not a design.
 *
 * §POCKETI18N — `note` stays ENGLISH here and `noteKey` names it, because this
 * module is pure and its unit tests run in a node env with no i18n. Callers
 * render t('pocket.guild.note.' + noteKey, note): the English is the fallback,
 * the key is what resolves. `noteParams` carries the interpolations so a
 * locale can order the sentence its own way.
 * ACTION LABELS carry no key on purpose — GuildActionOffer is asserted with a
 * deep toEqual in the test suite, so an extra field there would break it; the
 * label set is closed (award/submit/verify/cancel/bid) and callers translate
 * off `key`.
 */
export function actionsFor(order: GuildOrderLike | null | undefined, myDid: string | null | undefined):
  { role: GuildRole; actions: GuildActionOffer[]; note: string; noteKey: string; noteParams?: Record<string, string> } {
  const role = roleOn(order, myDid)
  const s = st(order)
  const actions: GuildActionOffer[] = []
  let note = ''
  let noteKey = ''
  let noteParams: Record<string, string> | undefined

  if (!order) return { role, actions, note: 'No order loaded.', noteKey: 'noOrder' }
  if (!myDid) return { role, actions, note: 'Pick an acting agent to interact with this order.', noteKey: 'pickAgent' }

  if (role === 'poster') {
    if (s === 'open') {
      if (Number(order.bid_count || 0) > 0) actions.push({ key: 'award', label: 'Award a bid' })
      actions.push({ key: 'cancel', label: 'Cancel order', danger: true })
      if (!actions.some(a => a.key === 'award')) { note = 'No bids yet — workers see this order on the network board.'; noteKey = 'noBids' }
    } else if (s === 'submitted' || s === 'delivered') {
      actions.push({ key: 'verify', label: 'Verify delivery', money: true })
    } else if (s === 'awarded' || s === 'in_progress') {
      note = 'Awarded — waiting on the worker to deliver.'; noteKey = 'posterAwarded'
    } else if (s === 'settled') {
      note = 'Settled — the bounty has been paid.'; noteKey = 'posterSettled'
    } else if (s === 'cancelled' || s === 'canceled') {
      note = 'Cancelled.'; noteKey = 'cancelled'
    } else {
      note = `Status "${s}" needs nothing from you right now.`; noteKey = 'statusIdle'; noteParams = { status: s }
    }
  } else if (role === 'worker') {
    if (s === 'awarded' || s === 'in_progress') {
      actions.push({ key: 'submit', label: 'Submit work' })
    } else if (s === 'submitted' || s === 'delivered') {
      note = 'Delivered — waiting on the poster to verify. Money moves at their acceptance.'; noteKey = 'workerDelivered'
    } else if (s === 'settled') {
      note = 'Settled — you have been paid.'; noteKey = 'workerSettled'
    } else {
      note = `Status "${s}" needs nothing from you right now.`; noteKey = 'statusIdle'; noteParams = { status: s }
    }
  } else {
    if (s === 'open') actions.push({ key: 'bid', label: 'Place a bid' })
    else { note = 'You are neither the poster nor the worker on this order.'; noteKey = 'observer' }
  }

  return { role, actions, note, noteKey, noteParams }
}
