/**
 * V0667 the public pages readable without JavaScript (order gwo_a9f121caa4138ec9b369814c): every page of the table, rendered from the app's OWN
 * view and en.json (staticPages/render.ts: Vue's server renderer over the route's view, no headless browser, no network), carries the page's
 * real text. For each instance:
 *   - at least its minimum of text, and the two phrases its source renders (so an empty shell or a page of "Loading…" fails)
 *   - no region marked live remains; the network stand-ins refuse every call (the generator also runs with no network at all)
 *   - the value-word rule of the console (vocabulary.test.ts, English): no stake word, and a token word only in the senses that rule keeps
 *     (a credential: bootstrap, payment, bearer, session tokens; read 2026-11-16, all 52 on these pages) or in a denial ("no new token");
 *     the legal pages have a review of their own there too. The rule is tested against sentences it must refuse.
 */
import { beforeAll, describe, expect, it } from 'vitest'
import { installNoNetwork } from './noNetwork'
import { PAGES } from './pages'
import { pageGate, pageText } from './document'

const STAKE = /\b(?:un)?stak(?:e|ed|es|er|ers|ing)?\b/i
const TOKEN = /\btokens?\b/gi
const CREDENTIAL = /bootstrap|payment|authoriz|bearer|\bjwt\b|session|oauth|credential|header|verif|sha-256|apt_|client_|request-token|\/token|\$[A-Z_]*TOKEN|x-payment|\/api\//i
const DENIAL = /\b(?:no|not|never|without|nor|none|nothing)\b[^.]{0,80}$/i

/** The value-sense words a page carries: every stake word, and every token word with no credential cue within 200 characters and no denial
 *  before it in its sentence. */
function valueWords(text: string): string[] {
  const out: string[] = []
  const stake = text.match(STAKE)
  if (stake) out.push(stake[0])
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0
    const around = text.slice(Math.max(0, at - 200), at + 200)
    const before = text.slice(Math.max(0, at - 120), at)
    if (!CREDENTIAL.test(around) && !DENIAL.test(before.split(/[.!?]\s/).pop() || '')) out.push(text.slice(Math.max(0, at - 40), at + 20))
  }
  return out
}

describe('the value-word rule the pages are held to', () => {
  it('refuses value senses and keeps credentials and denials', () => {
    expect(valueWords('Earn tokens by holding units.')).toHaveLength(1)
    expect(valueWords('Holders stake their units for a share.')).toEqual(['stake'])
    expect(valueWords('Every member receives a token for each vote cast in the season.')).toHaveLength(1)
    expect(valueWords('Request a bootstrap token. It expires in five minutes.')).toEqual([])
    expect(valueWords('No mining and no new token.')).toEqual([])
    expect(valueWords('None needs a new ledger, a new consensus mechanism or a new token.')).toEqual([])
    expect(valueWords('All under /api/v1. An agent acts with its own token, a developer with theirs.')).toEqual([])
    expect(valueWords('The caller sends the X-Payment-Token header with the call.')).toEqual([])
  })
})

beforeAll(() => { installNoNetwork(globalThis as any) })

describe('every static page renders its real text from the app\'s own source', () => {
  const cases = PAGES.flatMap((p) => p.instances.map((inst) => ({ page: p, inst })))

  it.each(cases.map((c) => [`${c.page.route} ${JSON.stringify(c.inst.params)}`, c]))('%s', async (_name, c: any) => {
    const { renderPage } = await import('./render')
    const out = await renderPage(c.page.route, c.inst.params)
    const text = pageText(out.body)
    expect(pageGate(text, c.inst), `${c.page.route}: ${text.slice(0, 200)}`).toEqual([])
    expect(out.body).not.toContain('data-static="omit"')
    expect(out.title.length).toBeGreaterThan(2)
    expect(out.description.length).toBeGreaterThan(20)
    if (!c.page.legal) expect(valueWords(text), c.page.route).toEqual([])
  }, 60000)
})
