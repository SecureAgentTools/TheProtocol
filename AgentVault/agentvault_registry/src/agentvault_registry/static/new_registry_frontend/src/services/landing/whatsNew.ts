// V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4424): the landing page's "What's new", read from the docs' release
// notes (assets/docs/oracle/38_release_notes.md, newest release first, one page per release). The newest release's member
// lines ("**For members**", each "- **Lead-in.** body"): the lead-in and the body's first sentence, links and code marks
// taken out, at most a few, and never a line that says a value word (the console's wording sweep reads the landing page).

export interface WhatsNewItem { title: string; line: string }
export interface WhatsNew { version: string; items: WhatsNewItem[] }

const VALUE_WORDS = /\b(?:un)?stak(?:e|ed|es|er|ers|ing)?\b|\btokens?\b|\byield|\bearn|\bbank|\bfloats?\b|\bprofit|\binvest|\binterest\b|\bdividend|\breward|\bapy\b|\breturns?\b/i

/** A line of the notes as plain text: a markdown link keeps its words, a trailing chapter link goes, code marks go. */
function plain(s: string): string {
  return s.replace(/\s*\(\[[^\]]*\]\([^)]*\)\)\s*$/, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/`/g, '').replace(/\*\*/g, '').trim()
}

function firstSentence(s: string): string {
  const m = /^(.*?[.!?])(\s|$)/.exec(s)
  return (m ? m[1]! : s).trim()
}

export function parseWhatsNew(md: string, max = 4): WhatsNew {
  const lines = md.split('\n')
  const start = lines.findIndex((l) => /^## V\d{4,6}\s*$/.test(l))
  if (start < 0) return { version: '', items: [] }
  const version = lines[start]!.replace(/^##\s*/, '').trim()
  const items: WhatsNewItem[] = []
  let inMembers = false
  for (const l of lines.slice(start + 1)) {
    if (/^## /.test(l)) break
    if (/^\*\*[^*]+\*\*\s*$/.test(l.trim())) { inMembers = /^\*\*For members\*\*$/.test(l.trim()); continue }
    if (!inMembers) continue
    const m = /^- \*\*(.+?)\*\*\s*(.*)$/.exec(l)
    if (!m) continue
    const title = m[1]!.replace(/[.:]\s*$/, '').trim()
    const line = firstSentence(plain(m[2]!))
    if (!title || !line || VALUE_WORDS.test(title) || VALUE_WORDS.test(line)) continue
    items.push({ title, line })
    if (items.length >= max) break
  }
  return { version, items }
}
