/**
 * V0652 (ac) (order gwo_2ae43c7789db1e808ea1417f): threads in a room, pure.
 *
 * The maintainer (the sessions' room, seq 257): "this makes me miss the sequence to evaluate who posts what from just the
 * chat". A reply folds under the message it answers, and the messages that name a Guild order fold into that order's
 * thread (the order id as the thread key; the order's live card is its root when it is in view), so the room stays short
 * and each order reads on its own. A thread is drawn where its LATEST message is (its root, then its bar; opened, its
 * messages under the root in their order), so new activity, your own reply included, shows at the bottom of the room
 * and never vanishes into a fold far above. The bar says how many messages the thread holds, how many are new to you
 * and how many are for you. A reply whose message is not in view (paged out) stays where it is.
 *
 * Nothing addressed to you hides in a fold (session-lead's review, seq 419): in a room where most messages name an
 * order, a question to you would otherwise sit behind a bar. A thread that holds something NEW for you (it names you,
 * or asks something of the room) opens by itself and stays open until you have read it. A fold by hand covers what was
 * there when you folded it: a newer message for you opens the thread again (seq 425).
 */
export const ORDER_ID_RE = /\bgwo_[0-9a-f]{24}\b/
const ORDER_ID_EXACT = /^gwo_[0-9a-f]{24}$/

export interface ThreadMsg { id: string; seq: number; kind?: string; body?: string | null; card?: any; reply_to?: string | null
  sender_ptype?: string; sender_id?: string; sender_name?: string; created_at?: string | null; [k: string]: any }

/** The Guild order a message is about: its card's order (refs.order_id, or a Guild card's data), else the first order
 *  id its text names. */
export function orderIdOf(m: ThreadMsg | null | undefined): string | null {
  const c = m?.card
  if (c && typeof c === 'object') {
    const id = c.refs?.order_id ?? (String(c.type || '').startsWith('guild.order') ? (c.data?.order_id ?? c.data?.ref) : null)
    if (typeof id === 'string' && ORDER_ID_EXACT.test(id)) return id
  }
  if (m?.kind === 'text' && typeof m.body === 'string') {
    const hit = m.body.match(ORDER_ID_RE)
    if (hit) return hit[0]
  }
  return null
}

export interface ThreadBar {
  key: string
  /** `reply` (a message's replies) or `order` (a Guild order's thread) */
  kind: 'reply' | 'order'
  orderId: string | null
  count: number
  unread: number
  forMe: number
  /** what is new to you AND for you: while there is any, the thread opens by itself */
  forMeNew: number
  last: ThreadMsg | null
  expanded: boolean
}

export interface Folded {
  /** what the thread draws, in order: the messages outside threads, each thread's root, and an open thread's messages
   *  right under its root */
  list: ThreadMsg[]
  /** a root's bar, by the root's message id */
  bars: Record<string, ThreadBar>
  /** the messages drawn inside an open thread (indented) */
  inThread: Set<string>
  /** where each folded message lives: its root's id */
  rootOf: Record<string, string>
}

export function foldThreads(messages: ThreadMsg[], o: {
  expanded: Set<string>
  /** threads the viewer folded by hand, each with the seq of its newest message then: it stays folded over what was
   *  there, and a newer message for the viewer opens it again */
  collapsed?: Map<string, number>
  lastReadSeq: number
  isMine: (m: ThreadMsg) => boolean
  forMe: (m: ThreadMsg) => boolean
}): Folded {
  const byId = new Map(messages.map((m) => [m.id, m]))
  const threadOf = new Map<string, { key: string; rootId: string }>()
  const firstOfKey = new Map<string, string>()
  // an order's live card roots its order's thread when it is in view
  for (const m of messages) {
    if (m.card?.type === 'guild.order.live') {
      const oid = orderIdOf(m)
      if (oid && !firstOfKey.has(`o:${oid}`)) firstOfKey.set(`o:${oid}`, m.id)
    }
  }
  for (const m of messages) {
    const parent = m.reply_to ? byId.get(m.reply_to) : undefined
    if (parent && parent.id !== m.id) {
      let t = threadOf.get(parent.id)
      if (!t) { t = { key: `r:${parent.id}`, rootId: parent.id }; threadOf.set(parent.id, t) }
      threadOf.set(m.id, t)
      continue
    }
    const oid = orderIdOf(m)
    if (!oid) continue
    const key = `o:${oid}`
    const root = firstOfKey.get(key)
    if (!root) { firstOfKey.set(key, m.id); threadOf.set(m.id, { key, rootId: m.id }); continue }
    threadOf.set(m.id, { key, rootId: root })
    if (!threadOf.has(root)) threadOf.set(root, { key, rootId: root })
  }
  const children = new Map<string, ThreadMsg[]>()
  const rootOf: Record<string, string> = {}
  for (const m of messages) {
    const t = threadOf.get(m.id)
    if (!t || t.rootId === m.id) continue
    rootOf[m.id] = t.rootId
    const list = children.get(t.rootId) ?? []
    list.push(m)
    children.set(t.rootId, list)
  }
  const bars: Record<string, ThreadBar> = {}
  const inThread = new Set<string>()
  const list: ThreadMsg[] = []
  // where a thread is drawn: the index of its latest message
  const lastAt = new Map<string, number>()
  messages.forEach((m, i) => {
    const r = rootOf[m.id] ?? (children.has(m.id) ? m.id : null)
    if (r) lastAt.set(r, i)
  })
  messages.forEach((m, i) => {
    const r = rootOf[m.id] ?? (children.has(m.id) ? m.id : null)
    if (!r) { list.push(m); return }
    if (lastAt.get(r) !== i) return
    const root = byId.get(r)!
    const kids = children.get(r)!
    const key = threadOf.get(r)!.key
    const isNew = (k: ThreadMsg) => (Number(k.seq) || 0) > (Number(o.lastReadSeq) || 0) && !o.isMine(k)
    const forMeNew = kids.filter((k) => isNew(k) && o.forMe(k)).length
    const foldedAt = o.collapsed?.get(key)
    const reopens = kids.some((k) => isNew(k) && o.forMe(k) && (foldedAt == null || (Number(k.seq) || 0) > foldedAt))
    const expanded = o.expanded.has(key) || reopens
    bars[r] = {
      key, kind: key.startsWith('o:') ? 'order' : 'reply', orderId: key.startsWith('o:') ? key.slice(2) : null,
      count: kids.length,
      unread: kids.filter(isNew).length,
      forMe: kids.filter((k) => o.forMe(k)).length,
      forMeNew,
      last: kids[kids.length - 1], expanded,
    }
    list.push(root)
    if (expanded) for (const k of kids) { list.push(k); inThread.add(k.id) }
  })
  return { list, bars, inThread, rootOf }
}
