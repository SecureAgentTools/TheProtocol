// V0664 (order gwo_c101e38685cd18581be34c2f; his phone report, the sessions' room seq 3741 to 3761): pictures sent with a message.
//
// The composer sends each staged file as a media card and then the text. Before this, the cards were top-level messages (a reply's
// pictures did not belong to the reply), they showed as plain files, and a reader saw the pictures and the words as separate
// messages or, in a folded reply thread, the words alone. Now:
//   * the cards and the text of one send carry one batch in their client_ref (att-<batch>-<n> and att-<batch>-t) and the same
//     reply_to, so they belong together for every reader on any client;
//   * the thread folds a run of one sender's media cards into the text that closes it (by the batch when there is one, else by the
//     sender, the order and two minutes: a send from before this change reads the same);
//   * a picture is shown as a picture; any other file stays a file chip.
// Pure: no Vue, no fetch; the thread, the card and their tests call it.

const PICTURE_MIME = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif'])   // chat_media.ALLOWED_MIME's pictures; SVG never (script)

export function isPictureMime(mime: string | null | undefined): boolean {
  return PICTURE_MIME.has(String(mime || '').toLowerCase())
}

const REF = /^att-([0-9a-f]{8})-(\d+|t)$/

export function batchRefs(batch: string, n: number): { cards: string[]; text: string } {
  return { cards: Array.from({ length: n }, (_, i) => `att-${batch}-${i}`), text: `att-${batch}-t` }
}

export function cardPayload(card: unknown, clientRef: string, replyTo?: string | null) {
  return { kind: 'card' as const, card, client_ref: clientRef, ...(replyTo ? { reply_to: replyTo } : {}) }
}

/** What one send posts: a card per staged file, then the text, all with the same batch and the same reply. */
export function planSend(batch: string, files: Array<{ id: string }>, replyTo: string | null) {
  const refs = batchRefs(batch, files.length)
  return {
    cards: files.map((f, i) => ({ id: f.id, client_ref: refs.cards[i], ...(replyTo ? { reply_to: replyTo } : {}) } as { id: string; client_ref: string; reply_to?: string })),
    text: { client_ref: refs.text, ...(replyTo ? { reply_to: replyTo } : {}) } as { client_ref: string; reply_to?: string },
  }
}

function batchOf(m: any): string | null {
  const g = REF.exec(String(m?.client_ref || ''))
  return g ? g[1] : null
}
const isMediaCard = (m: any): boolean => m?.kind === 'card' && m?.card?.type === 'media' && !m?.deleted_at && !m?.deleted
const sameSender = (a: any, b: any): boolean => a.sender_ptype === b.sender_ptype && String(a.sender_id) === String(b.sender_id)
const at = (m: any): number => { const t = Date.parse(String(m?.created_at || '')); return Number.isFinite(t) ? t : NaN }
const WINDOW_MS = 120_000

/** The list as it is drawn: each run of one sender's media cards folded into the text that closes it. `pictures` maps that text's id
 *  to its cards, in order. Cards with no text after them (files sent alone), a text before its pictures, another sender's text, a
 *  card that is not media and a message taken back are left where they are. */
export function foldPictures(list: any[]): { list: any[]; pictures: Map<string, any[]> } {
  const pictures = new Map<string, any[]>()
  const hidden = new Set<string>()
  for (let i = 0; i < list.length; i++) {
    if (!isMediaCard(list[i])) continue
    let j = i
    while (j + 1 < list.length && isMediaCard(list[j + 1]) && sameSender(list[j + 1], list[i])) j++
    const closer = list[j + 1]
    if (closer && closer.kind === 'text' && sameSender(closer, list[i]) && !closer.deleted_at && !closer.deleted) {
      const run = list.slice(i, j + 1)
      const bt = batchOf(closer)
      const mine = run.filter((c) => (bt ? batchOf(c) === bt : batchOf(c) === null))
      const near = bt ? mine : mine.filter((c) => { const d = at(closer) - at(c); return Number.isFinite(d) && d >= 0 && d <= WINDOW_MS })
      if (near.length) {
        pictures.set(closer.id, near)
        for (const c of near) hidden.add(c.id)
      }
    }
    i = j
  }
  return { list: list.filter((m) => !hidden.has(m.id)), pictures }
}

/** The part of the layout viewport a software keyboard covers, in pixels. Chrome on a phone keeps the layout and shrinks only the
 *  visual viewport, so a composer pinned to the layout's bottom ends under the keyboard (his seq 3744: "I can't see what I type").
 *  A difference under 60 px is a browser bar or a notch, not a keyboard. */
export function keyboardInset(innerHeight: number, visualHeight: number, visualTop: number): number {
  if (!Number.isFinite(innerHeight) || !Number.isFinite(visualHeight)) return 0
  const top = Number.isFinite(visualTop) ? visualTop : 0
  const inset = Math.round(innerHeight - visualHeight - top)
  return inset >= 60 ? inset : 0
}

/** How far to shrink the thread so its composer clears the keyboard: the part of the thread that lies below the visible area, while a
 *  keyboard is up (a tab bar under the thread is covered too, so the shrink is less than the keyboard's own height). `applied` is the
 *  shrink already in force: it is added back to the measured bottom, so reading the state after the shrink gives the same answer and
 *  the two do not chase each other. */
export function composerLift(innerHeight: number, visualHeight: number, visualTop: number, rootBottom: number, applied: number): number {
  if (!keyboardInset(innerHeight, visualHeight, visualTop)) return 0
  if (!Number.isFinite(rootBottom)) return 0
  const base = rootBottom + (Number.isFinite(applied) ? applied : 0)
  const lift = Math.round(base - (visualTop + visualHeight))
  return lift > 0 ? lift : 0
}
