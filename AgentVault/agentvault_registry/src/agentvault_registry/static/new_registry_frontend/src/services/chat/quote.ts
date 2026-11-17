/**
 * V0662 (OurChat lane): quote a message into the composer.
 *
 * Quote is not Reply: Reply folds your answer under the message it answers (a thread); Quote copies a few lines of it into what
 * you are writing, as a markdown quote (the renderer draws `>` lines as a quotation), so the answer carries what it answers
 * wherever it is read. Pure text work: nothing is sent, nothing is posted, the registry is not asked.
 */
export const QUOTE_MAX_LINES = 6
export const QUOTE_MAX_CHARS = 400

/** `> name: first lines...` as a markdown quote, ending with a blank line and then the cursor. The quoted text is cut to
 *  QUOTE_MAX_LINES lines and QUOTE_MAX_CHARS characters (an ellipsis marks a cut), and any line already quoted keeps its own `>`. */
export function quoteBlock(sender: string | null | undefined, body: string | null | undefined): string {
  const text = String(body ?? '').replace(/\r\n?/g, '\n').trim()
  if (!text) return ''
  let lines = text.split('\n')
  let cut = false
  if (lines.length > QUOTE_MAX_LINES) { lines = lines.slice(0, QUOTE_MAX_LINES); cut = true }
  let joined = lines.join('\n')
  if (joined.length > QUOTE_MAX_CHARS) { joined = joined.slice(0, QUOTE_MAX_CHARS).replace(/\s+\S*$/, ''); cut = true }
  const who = String(sender ?? '').replace(/\s+/g, ' ').trim()
  const out = joined.split('\n').map((l, i) => `> ${i === 0 && who ? `${who}: ` : ''}${l}`.trimEnd())
  if (cut) out[out.length - 1] = `${out[out.length - 1]} …`
  return `${out.join('\n')}\n\n`
}

/** What the composer holds after Quote: the block goes at the end of what is already there, a blank line between. */
export function withQuote(current: string, block: string): string {
  if (!block) return current
  const base = current.replace(/\s+$/, '')
  return base ? `${base}\n\n${block}` : block
}
