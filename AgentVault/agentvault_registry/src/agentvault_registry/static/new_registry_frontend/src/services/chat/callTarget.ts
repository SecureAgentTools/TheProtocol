/**
 * §S13 — WHO does `/call` ask?
 *
 * His report: *"`/call weather in berlin` doesnt work. if i type
 * `/call did:theprotocol:ce1031a8-… berlin` it works. otherwise not. we need
 * the did identifier to call here or the rules seem to confuse everything and
 * dont produce a good answer."*
 *
 * Extracted from `ShowcaseChat.vue` so it can be asserted directly. The
 * showcase lives on the landing page, which carries a WebGL hero; this box has
 * no GPU, and driving it with Playwright under load hangs (the standing rule
 * about the heavy visual views). Parsing that decides who gets asked — and
 * therefore who gets PAID — should not be verifiable only through a page that
 * cannot be relied on to open.
 *
 * The rules, and why each is what it is:
 *
 *  1. A `did:` token anywhere in the line is the target. Unambiguous by
 *     construction, which is why it was the only form that worked before.
 *  2. An `@name` token is the target. Kept, though nobody guesses it.
 *  3. A first token that EXACTLY matches an agent's name is the target.
 *     🔴 Exact only. An earlier cut of this also matched the stem, so
 *     `WeatherAgent` resolved from a bare `weather` — and THE AGENT'S OWN CARD
 *     says that is wrong: WeatherAgent publishes
 *     `examples: ['weather in Berlin', 'Freilassing']` and describes its input
 *     as *"A city name, or 'weather in <city>'"*. In his exact line the word
 *     `weather` is part of the QUESTION; consuming it as a name would have
 *     asked the agent "in berlin". A heuristic that eats a token out of the ask
 *     has to be certain, and only a full-name match is.
 *  4. No target and no chosen partner ⇒ REFUSE and suggest. Standing in for a
 *     missing argument is only honest when the reader actually chose the
 *     counterparty — the same rule §SHOWCASEBAL gave `/card`. A near miss is
 *     OFFERED, carrying his own question back, never silently consumed.
 */

export interface CallService { id: string; name: string; price?: any; currency?: string }

export interface CallTarget {
  /** DID to call, or '' when the caller's own thread partner should be used. */
  targetDid: string
  /** The question, with any target token removed. */
  askText: string
  /** True when there is nothing to ask and nobody was chosen. */
  needsAgent: boolean
  /** An exact line the reader can send, when one can be offered. */
  suggestion: string
  /** '@name' that matched nothing — the caller names what it could not find. */
  unknownAt: string
  /** Several agents prefix-match the first word. Listed, never picked from. */
  ambiguous: string[]
}

export function resolveCallTarget(opts: {
  ask: string
  services: CallService[]
  partnerChosen: boolean
}): CallTarget {
  const services = Array.isArray(opts.services) ? opts.services : []
  const toks = String(opts.ask || '').trim().split(/\s+/).filter(Boolean)
  const didTok = toks.find(x => x.toLowerCase().startsWith('did:')) || ''
  const atTok = toks.find(x => x.startsWith('@')) || ''

  const exactByName = (tok: string): CallService | null => {
    const w = String(tok || '').toLowerCase()
    if (!w) return null
    const hit = services.filter(sv => String(sv.name || '').toLowerCase() === w)
    return hit.length === 1 ? hit[0] : null
  }

  // Only a leading token can be a name, and only when something follows it —
  // `/call WeatherAgent` alone is a request for instructions, not a question.
  const nameSvc = (!didTok && !atTok && toks.length > 1) ? exactByName(toks[0]) : null
  const nameTok = nameSvc ? toks[0] : ''

  let targetDid = didTok || (nameSvc ? String(nameSvc.id) : '')
  let unknownAt = ''
  if (!targetDid && atTok) {
    const want = atTok.slice(1).toLowerCase()
    const hit = services.find(sv => String(sv.name || '').toLowerCase() === want)
             || services.find(sv => String(sv.name || '').toLowerCase().startsWith(want))
    if (hit) targetDid = String(hit.id)
    else unknownAt = atTok.slice(1)
  }

  const askText = toks.filter(x => x !== didTok && x !== atTok && x !== nameTok).join(' ').trim()
  const needsAgent = !targetDid && !atTok && !opts.partnerChosen

  let suggestion = ''
  let ambiguous: string[] = []
  if (needsAgent) {
    const w = String(toks[0] || '').toLowerCase()
    const near = w ? services.filter(sv => String(sv.name || '').toLowerCase().startsWith(w)) : []
    if (near.length === 1) {
      // Hand back the SAME question with an agent in front of it, so what he
      // gets is a line to send rather than a shape to reassemble.
      suggestion = `/call ${near[0].name}${askText ? ' ' + askText : ''}`.trim()
    } else if (near.length > 1) {
      /* 🔴 CAUGHT BY ITS OWN TEST. This used to fall through to `services[0]`
         whenever there was not exactly one near match — including when there
         were SEVERAL, so an ambiguous `pay …` was answered with a confident
         `/call PayAgent pay …` picked purely by list order. That is the silent
         pick this function exists to avoid, re-introduced by its own fallback.
         Several matches is not an error and must not resolve to one of them
         (the rule `/card` already follows): they are LISTED. */
      ambiguous = near.map(sv => String(sv.name))
    } else if (services.length) {
      // No near match at all — a generic example is not a guess about intent.
      suggestion = `/call ${services[0].name}${askText ? ' ' + askText : ''}`.trim()
    }
  }

  return { targetDid, askText, needsAgent, suggestion, unknownAt, ambiguous }
}
