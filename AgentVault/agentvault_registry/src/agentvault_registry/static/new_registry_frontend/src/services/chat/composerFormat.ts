/**
 * V0662 (OurChat lane): the composer's formatting, as pure text-and-selection transforms.
 *
 * A toolbar button (or Ctrl/Cmd+B, I, K) hands the textarea's text and selection to `applyFormat` and gets the new text
 * and the selection to restore. Every kind TOGGLES: formatting what is already formatted removes it. The markers are
 * the ones the thread's own renderer reads (`renderMarkdown`: markdown-it, raw HTML off), so what the Preview shows is
 * what posts.
 *
 * Pure: no DOM. The textarea's `setSelectionRange` and the `input` event are the caller's.
 */

export type FormatKind = 'bold' | 'italic' | 'code' | 'quote' | 'list' | 'link'

export interface Edit {
  text: string
  selStart: number
  selEnd: number
}

const URL_ONLY = /^https?:\/\/\S+$/
const clamp = (n: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, n))

/** The run of `ch` ending at the end of `s`, and the run starting at the start of `s`. */
function runEnd(s: string, ch: string): number {
  let n = 0
  while (n < s.length && s[s.length - 1 - n] === ch) n++
  return n
}
function runStart(s: string, ch: string): number {
  let n = 0
  while (n < s.length && s[n] === ch) n++
  return n
}

/** `**` and `*` wrap the selection; wrapped already, they come off (a run of asterisks counted, so bold inside italic
 *  and the reverse are not mistaken for each other). */
function wrapAsterisks(text: string, s: number, e: number, marker: '**' | '*'): Edit {
  const before = text.slice(0, s)
  const sel = text.slice(s, e)
  const after = text.slice(e)
  const need = marker.length
  const around = Math.min(runEnd(before, '*'), runStart(after, '*'))
  // wrapped outside the selection: `**x**` with x selected. For one asterisk the run must be odd (1 or 3), for two
  // it must be 2 or more.
  const wrapped = need === 1 ? around % 2 === 1 : around >= 2
  if (wrapped) {
    return { text: before.slice(0, -need) + sel + after.slice(need), selStart: s - need, selEnd: e - need }
  }
  // the markers are inside the selection: `**x**` selected whole
  const inner = Math.min(runStart(sel, '*'), runEnd(sel, '*'))
  const innerWrapped = sel.length > need * 2 && (need === 1 ? inner % 2 === 1 : inner >= 2)
  if (innerWrapped) {
    const body = sel.slice(need, sel.length - need)
    return { text: before + body + after, selStart: s, selEnd: s + body.length }
  }
  return { text: before + marker + sel + marker + after, selStart: s + need, selEnd: e + need }
}

/** Backticks wrap a line of code; a selection over several lines becomes a fenced block, and a fenced block comes off. */
function wrapCode(text: string, s: number, e: number): Edit {
  const before = text.slice(0, s)
  const sel = text.slice(s, e)
  const after = text.slice(e)
  if (sel.includes('\n')) {
    if (sel.startsWith('```\n') && sel.endsWith('\n```') && sel.length >= 8) {
      const body = sel.slice(4, sel.length - 4)
      return { text: before + body + after, selStart: s, selEnd: s + body.length }
    }
    const fenced = '```\n' + sel + '\n```'
    return { text: before + fenced + after, selStart: s + 4, selEnd: s + 4 + sel.length }
  }
  if (before.endsWith('`') && after.startsWith('`')) {
    return { text: before.slice(0, -1) + sel + after.slice(1), selStart: s - 1, selEnd: e - 1 }
  }
  if (sel.length > 2 && sel.startsWith('`') && sel.endsWith('`')) {
    const body = sel.slice(1, -1)
    return { text: before + body + after, selStart: s, selEnd: s + body.length }
  }
  return { text: before + '`' + sel + '`' + after, selStart: s + 1, selEnd: e + 1 }
}

/** `> ` and `- ` go at the start of every line the selection touches; on lines that all carry it already, they come off. */
function prefixLines(text: string, s: number, e: number, prefix: string): Edit {
  // a selection that ends just after a line break does not take the next, untouched line
  const last = e > s && text[e - 1] === '\n' ? e - 1 : e
  const lineStart = text.lastIndexOf('\n', s - 1) + 1
  const nl = text.indexOf('\n', last)
  const lineEnd = nl === -1 ? text.length : nl
  const lines = text.slice(lineStart, lineEnd).split('\n')
  const filled = lines.filter((l) => l.trim() !== '')
  const allPrefixed = filled.length > 0 && filled.every((l) => l.startsWith(prefix))
  const next = lines.map((l) => {
    if (allPrefixed) return l.startsWith(prefix) ? l.slice(prefix.length) : l
    // a mix takes the prefix on the lines that lack it and leaves the others: never a quote inside a quote by accident
    if (l.startsWith(prefix)) return l
    // a lone empty line takes the prefix too, so a caret on a new line can start a list
    return l.trim() === '' && lines.length > 1 ? l : prefix + l
  })
  const block = next.join('\n')
  const out = text.slice(0, lineStart) + block + text.slice(lineEnd)
  return s === e
    ? { text: out, selStart: lineStart + block.length, selEnd: lineStart + block.length }
    : { text: out, selStart: lineStart, selEnd: lineStart + block.length }
}

/** `[text](https://)` around the selection, the address ready to type; a selected address becomes `[](address)`. */
function makeLink(text: string, s: number, e: number): Edit {
  const before = text.slice(0, s)
  const sel = text.slice(s, e)
  const after = text.slice(e)
  if (URL_ONLY.test(sel.trim())) {
    return { text: before + '[](' + sel.trim() + ')' + after, selStart: s + 1, selEnd: s + 1 }
  }
  if (sel === '') return { text: before + '[](https://)' + after, selStart: s + 1, selEnd: s + 1 }
  const at = s + 1 + sel.length + 2
  return { text: before + '[' + sel + '](https://)' + after, selStart: at, selEnd: at + 'https://'.length }
}

/** The text and selection after applying `kind` to the selection `selStart`..`selEnd` of `text`. */
export function applyFormat(text: string, selStart: number, selEnd: number, kind: FormatKind): Edit {
  const t = text || ''
  const a = clamp(Number.isFinite(selStart) ? selStart : 0, 0, t.length)
  const b = clamp(Number.isFinite(selEnd) ? selEnd : a, 0, t.length)
  const s = Math.min(a, b)
  const e = Math.max(a, b)
  switch (kind) {
    case 'bold': return wrapAsterisks(t, s, e, '**')
    case 'italic': return wrapAsterisks(t, s, e, '*')
    case 'code': return wrapCode(t, s, e)
    case 'quote': return prefixLines(t, s, e, '> ')
    case 'list': return prefixLines(t, s, e, '- ')
    case 'link': return makeLink(t, s, e)
  }
}

/** The format a key press asks for: Ctrl or Cmd with B, I or K; nothing for any other key or with Shift or Alt held. */
export function shortcutFormat(e: { key: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; altKey?: boolean }): FormatKind | null {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return null
  switch ((e.key || '').toLowerCase()) {
    case 'b': return 'bold'
    case 'i': return 'italic'
    case 'k': return 'link'
    default: return null
  }
}
