import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * §FESUITE (2026-10-03; the blind spot agentvault2-81 found): the console suite's wording guard (51-public-wording) reads
 * the public pages in English and German only. The seven other bundles kept translations of public texts after the
 * English was rewritten (the BaFin wording, the landing pass), so a visitor whose browser picks one of them still read
 * "tokens", "staking" and rewards in AVT. landing/v8 (784d00fb) removed them: a sparse bundle falls back to the current
 * English. This gate keeps it so, statically, for every key a public page can ask for:
 *  - the public pages are the router's own (`requiresAuth: false`) and the root shell every page renders inside (App.vue:
 *    the beta banner, the notices, the command palette), with every view or component they import, followed through
 *    the source; their namespaces are every 'ns.key' string in those files whose namespace en.json has (a key held in a
 *    variable or a table counts too). Scope comes from the code, not from a list kept by hand (that list named five
 *    namespaces en.json does not have and missed the shell's);
 *  - DRIFT: a translation names a listed concept (agentvault2-81's per-language words, plus the unit and frame names)
 *    while the current English names none of them: the English moved on and the translation did not;
 *  - DEAD: a public key a secondary bundle holds and the English no longer has (the residue of a rewrite).
 * German is read in a browser by 51 and is not part of this gate.
 */

const SRC = path.resolve(__dirname, '..')
const LOCALES = ['es', 'fr', 'pt', 'ru', 'ja', 'ko', 'zh'] as const
type Loc = typeof LOCALES[number]

/** agentvault2-81's lists (sparse_stale.py), with the Chinese "portfolio" (投资组合) left out of "invest" */
const CONCEPT: Record<Loc, RegExp> = {
  // §LANDINGTRUTH (29, agentvault2-45's find): the reputation bond is a deposit; a translation that makes it a debt
  // security (zh 债券), a bonus (pt bônus, es bono) or a loanword "bond" (ja ボンド, ko 본드) names a concept the
  // English does not, so it counts as drift unless the English itself says "bonus"
  es: /token|staking|recompensa|rentabilidad|APY|invers|\bbonos?\b/i,
  fr: /token|jeton|staking|récompens|rendement|APY|investiss/i,
  pt: /token|staking|recompensa|rendimento|APY|investiment|bônus/i,
  ru: /токен|стейкинг|вознагражд|доходност|APY|инвест/i,
  ja: /トークン|ステーキング|報酬|利回り|APY|投資|ボンド/i,
  ko: /토큰|스테이킹|보상|수익률|APY|투자|본드/i,
  zh: /代币|质押|奖励|收益|APY|投资(?!组合)|债券/i,
}
/** the unit and frame names read the same in every language (case kept: "frame a" in a sentence is not Frame A) */
const NAMES = /\b(?:AVT|JDAY|BVT)\b|\bFrame [ABC]\b|\bthree mainframes\b/
/** what the English names when a listed word in a translation is a faithful one (81's EN_CONCEPT, plus APR,
 *  compensation and portfolio, which the Korean 보상 and the Chinese 收益 / 投资组合 translate) */
const EN_CONCEPT = /token|stak|reward|yield|return|APY|APR|invest|earn|compensat|portfolio|bount|bonus|lock/i

type Bundle = Record<string, string>

function flat(o: unknown, p = '', out: Bundle = {}): Bundle {
  if (o && typeof o === 'object') {
    for (const [k, v] of Object.entries(o as Record<string, unknown>)) flat(v, p ? `${p}.${k}` : k, out)
  } else if (typeof o === 'string') out[p] = o
  return out
}

/** The keys of one secondary bundle the gate refuses, within the given namespaces. */
function translationDrift(en: Bundle, loc: Loc, tr: Bundle, namespaces: Set<string>): { drift: string[]; dead: string[] } {
  const drift: string[] = []
  const dead: string[] = []
  for (const [k, v] of Object.entries(tr)) {
    if (!namespaces.has(k.split('.')[0])) continue
    if (!(k in en)) { dead.push(k); continue }
    const said = CONCEPT[loc].test(v) || NAMES.test(v)
    if (said && !EN_CONCEPT.test(en[k]) && !NAMES.test(en[k])) drift.push(k)
  }
  return { drift, dead }
}

const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')
const bundle = (loc: string): Bundle => flat(JSON.parse(read(`i18n/locales/${loc}.json`)))

/** The views the router serves without a session. */
function publicViews(): string[] {
  const router = read('router/index.ts')
  const starts = [...router.matchAll(/\bpath:\s*['"`]/g)].map((m) => m.index ?? 0)
  const views = new Set<string>()
  starts.forEach((at, i) => {
    const seg = router.slice(at, starts[i + 1] ?? router.length)
    if (!/requiresAuth:\s*false/.test(seg)) return
    for (const m of seg.matchAll(/import\(\s*['"]@\/(views\/[^'"]+\.vue)['"]\s*\)/g)) views.add(m[1])
  })
  return [...views]
}

/** Every source file a public view reaches through its imports (.vue and .ts under src, not i18n, router, stores or the
 *  API clients: they render nothing of their own). */
function reachable(views: string[]): string[] {
  const seen = new Set<string>()
  const queue = [...views]
  const resolve = (from: string, spec: string): string | null => {
    const base = spec.startsWith('@/') ? spec.slice(2) : path.join(path.dirname(from), spec)
    for (const cand of [base, `${base}.ts`, `${base}.vue`, `${base}/index.ts`]) {
      if (fs.existsSync(path.join(SRC, cand)) && fs.statSync(path.join(SRC, cand)).isFile()) return path.normalize(cand)
    }
    return null
  }
  while (queue.length) {
    const rel = queue.pop()!
    if (seen.has(rel)) continue
    seen.add(rel)
    const text = read(rel)
    for (const m of text.matchAll(/(?:from\s+|import\(\s*)['"]((?:@\/|\.{1,2}\/)[^'"]+)['"]/g)) {
      const dep = resolve(rel, m[1])
      if (!dep || !/\.(vue|ts)$/.test(dep) || /\.test\.ts$/.test(dep)) continue
      if (/^(i18n|router|stores|services\/api)\//.test(dep)) continue
      queue.push(dep)
    }
  }
  return [...seen]
}

function namespacesOf(files: string[], enTop: Set<string>): Set<string> {
  const ns = new Set<string>()
  for (const f of files) {
    for (const m of read(f).matchAll(/['"`]([A-Za-z][\w]*)\.[\w-]+(?:\.[\w-]+)*['"`]/g)) if (enTop.has(m[1])) ns.add(m[1])
  }
  return ns
}

describe('translations of the public pages follow the English (no drift, no dead keys)', () => {
  it('controls: what the detector refuses, and what it keeps', () => {
    const en = { 'pub.a': 'Units carry voting weight only.', 'pub.b': 'Staking rewards are switched off.', 'pub.c': 'Open the console.' }
    const es = { 'pub.a': 'Los tokens generan recompensas en AVT.', 'pub.b': 'Las recompensas de staking están desactivadas.', 'pub.c': 'Abrir la consola.', 'pub.gone': 'x', 'member.a': 'tokens' }
    const r = translationDrift(en, 'es', es, new Set(['pub']))
    expect(r.drift).toEqual(['pub.a']) // the English moved away from tokens and rewards
    expect(r.dead).toEqual(['pub.gone']) // the English no longer has the key
    // a faithful translation of English that names the concept is not drift; a namespace out of scope is not read
    expect(translationDrift(en, 'zh', { 'pub.c': '打开控制台。', 'pub.b': '质押奖励已关闭。' }, new Set(['pub']))).toEqual({ drift: [], dead: [] })
    expect(translationDrift({ 'pub.p': 'Portfolio Value' }, 'zh', { 'pub.p': '投资组合价值' }, new Set(['pub'])).drift).toEqual([])
  })

  it('the seven secondary bundles, on every namespace a public page can ask for', () => {
    const en = bundle('en')
    const enTop = new Set(Object.keys(JSON.parse(read('i18n/locales/en.json'))))
    const views = publicViews()
    const files = reachable(['App.vue', ...views])
    const namespaces = namespacesOf(files, enTop)
    // floors: a router the parser no longer reads, or an import walk that stopped, would pass on nothing
    expect(views.length, 'public views found in the router').toBeGreaterThanOrEqual(30)
    expect(namespaces.size, 'namespaces the public pages ask for').toBeGreaterThanOrEqual(20)
    expect(namespaces.has('landingPage'), 'the landing page is among them').toBe(true)
    expect(namespaces.has('app'), 'the shell around every page is among them').toBe(true)
    const problems: string[] = []
    for (const loc of LOCALES) {
      const { drift, dead } = translationDrift(en, loc, bundle(loc), namespaces)
      for (const k of drift) problems.push(`${loc} DRIFT ${k}`)
      for (const k of dead) problems.push(`${loc} DEAD ${k}`)
    }
    expect(problems).toEqual([])
  }, 60_000)
})
