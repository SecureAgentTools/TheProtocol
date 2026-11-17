/**
 * V0662 (OurChat lane): a link to one message, and what opening one does.
 *
 * The link is the thread's own address plus the message id: `<console>/#/pocket/ourchat/<conversation>?m=<message id>`.
 * /pocket/ourchat/:id is the stable external form (push notifications and handle QRs use it, and it resolves on the desktop
 * as well), `<origin><path>#/...` is right on the apex (path `/`) and on a registry (path `/ui/`) alike. A person who opens it
 * is taken to the line (older pages are read until it is loaded) and the line is marked for a moment; a person who is not in
 * the conversation sees what any thread link shows them, never the message: the link carries an id, not the words.
 */
export function messageLink(o: { origin: string; pathname: string; conversationId: string; messageId: string }): string {
  const path = o.pathname && o.pathname.endsWith('/') ? o.pathname : `${o.pathname || ''}/`
  return `${o.origin}${path}#/pocket/ourchat/${encodeURIComponent(o.conversationId)}?m=${encodeURIComponent(o.messageId)}`
}

/** The message a thread was opened at (`?m=`), or null: only a plain id-shaped value counts (a uuid or alike; no markup). */
export function messageFromQuery(q: unknown): string | null {
  const v = Array.isArray(q) ? q[0] : q
  const s = typeof v === 'string' ? v.trim() : ''
  return /^[A-Za-z0-9_-]{8,64}$/.test(s) ? s : null
}
