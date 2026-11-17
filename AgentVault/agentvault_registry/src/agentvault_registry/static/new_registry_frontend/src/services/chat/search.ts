/**
 * V0662 (OurChat lane): search in a thread, the console's pure rules (the registry's: services/chat_service.py::
 * search_messages, GET /chat/conversations/{id}/search?q=).
 *
 * The registry finds the text lines whose words hold the query (case ignored, the person's own % and _ taken literally).
 * This decides when a query is worth sending, and cuts what to show of a hit: a short stretch of the line around the first
 * match, the match marked. Text only: parts are drawn as text nodes, never as markup, so a line's words can never become HTML.
 */
export const SEARCH_MIN = 2
export const SEARCH_MAX = 100
export const SNIPPET_RADIUS = 60

/** The query as it would be sent (trimmed), or null when it is too short or too long to ask. */
export function searchQuery(raw: string | null | undefined): string | null {
  const q = String(raw ?? '').trim()
  return q.length >= SEARCH_MIN && q.length <= SEARCH_MAX ? q : null
}

export interface SnippetPart { text: string; hit: boolean }

/** A hit's words around the first match: `…before [match] after…`, with the match marked. No match (the registry matches
 *  more loosely than a plain substring can) shows the line's start. Never throws on odd input. */
export function snippetParts(body: string | null | undefined, query: string | null | undefined, radius = SNIPPET_RADIUS): SnippetPart[] {
  const text = String(body ?? '').replace(/\s+/g, ' ').trim()
  const q = String(query ?? '').trim()
  if (!text) return []
  const at = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1
  if (at < 0) return [{ text: text.length > radius * 2 ? `${text.slice(0, radius * 2)}…` : text, hit: false }]
  const from = Math.max(0, at - radius)
  const to = Math.min(text.length, at + q.length + radius)
  const out: SnippetPart[] = []
  const before = text.slice(from, at)
  const after = text.slice(at + q.length, to)
  if (before || from > 0) out.push({ text: `${from > 0 ? '…' : ''}${before}`, hit: false })
  out.push({ text: text.slice(at, at + q.length), hit: true })
  if (after || to < text.length) out.push({ text: `${after}${to < text.length ? '…' : ''}`, hit: false })
  return out
}

/** Whether the thread's loaded messages reach back to `seq` (so a jump to it can scroll instead of loading older ones). */
export function loadedReaches(messages: Array<{ seq?: number }>, seq: number): boolean {
  const first = Number(messages[0]?.seq)
  return Number.isFinite(first) && first <= seq
}
