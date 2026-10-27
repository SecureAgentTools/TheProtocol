/**
 * An agent card's humanReadableId from its name (quick onboarding, 2026-10-09).
 *
 * The humanReadableId is the last segment of the placeholder endpoint a quick card advertises
 * (`http://localhost:8000/agents/<slug>`) and a lookup key (the registry finds a card by it, case-insensitively, first
 * match), so it is a slug of [a-z0-9-]: the rule the Agent Builder holds a handle to (AgentForge's HRI_REGEX) and the
 * one the registry slugs a stub card's host with. It used to be the name lowercased with only whitespace replaced,
 * which put "#", "?", "/" and "%" into the path.
 *
 *   - Latin letters keep their base: Café -> cafe, Straße -> strasse, Đà Nẵng -> da-nang.
 *   - Every other run becomes one dash, no dash at either end, at most 64 characters.
 *   - A name with letters this cannot carry (研究助手, Помощник, مساعد) gets a mark of its own, six hex digits hashed
 *     from the name: "agent-<mark>", or its Latin part and the mark ("Помощник 2" -> "2-<mark>"). The same name always
 *     gets the same handle (the hint shows what will be sent), and two different names do not share one. Without the
 *     mark, every such name would get the one handle "agent".
 *   - A name with no letter or digit at all is "agent".
 *
 * The name itself stays the person's own words; names are not unique, the DID is the only address.
 */
export const AGENT_SLUG_MAX = 64

/** Latin letters that Unicode does not decompose into a base letter and marks. */
const LATIN_EXTRA: Readonly<Record<string, string>> = {
  'ß': 'ss', 'æ': 'ae', 'œ': 'oe', 'ø': 'o', 'đ': 'd', 'ð': 'd', 'þ': 'th', 'ł': 'l', 'ħ': 'h', 'ı': 'i',
  'ŀ': 'l', 'ĸ': 'k', 'ŋ': 'n', 'ſ': 's', 'ŧ': 't', 'ƒ': 'f',
}

const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u
// written as a property escape, never as literal combining characters (an editor can change those without a diff)
const COMBINING_MARKS = /\p{M}+/gu

/** FNV-1a (32 bit) over the name's UTF-16 code units, as six hex digits: short and stable, not a secret. */
export function nameMark(name: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < name.length; i++) {
    h ^= name.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0').slice(0, 6)
}

export function agentSlug(name: string | null | undefined): string {
  const own = String(name ?? '').normalize('NFC').trim().toLowerCase()
  const latin = Array.from(own.normalize('NFKD').replace(COMBINING_MARKS, ''))
    .map((ch) => LATIN_EXTRA[ch] ?? ch)
    .join('')
  // a letter or digit outside ASCII that is still here could not be carried: the handle needs the name's mark
  const untold = Array.from(latin).some((ch) => (ch.codePointAt(0) ?? 0) > 0x7f && LETTER_OR_DIGIT.test(ch))
  const base = latin
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (!untold) return base.slice(0, AGENT_SLUG_MAX).replace(/-+$/g, '') || 'agent'
  const mark = nameMark(own)
  const head = (base || 'agent').slice(0, AGENT_SLUG_MAX - mark.length - 1).replace(/-+$/g, '')
  return `${head || 'agent'}-${mark}`
}
