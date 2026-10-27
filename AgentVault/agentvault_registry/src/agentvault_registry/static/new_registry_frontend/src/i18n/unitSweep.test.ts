import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { createI18n } from 'vue-i18n'

/**
 * D6-835 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "sweep for avt again ... currency agnostic"):
 * the console said AVT on every frame in the places the docs gallery shows (Fiat Operations, the Treasury's mint, Agent
 * Forge, the Senate's funding card, the reactors' worker cards, the command palette, the Pocket assistant's examples,
 * the org policy) and in a few more (the FX desk's notes, the CI/CD template prices, the payment-token states). EU's
 * unit is ECU, ASIA's ACU, the sandbox's SBXA and SBXB; AVT is Frame A's alone. Each such label now names the frame's
 * unit, or none where none is known. D6-836: Fiat Operations greys out in the sidebar while the euro on-ramp is off.
 * Left as they are: the journal posts, the legal texts, the flare names ("AVT", "AVT LEAK") and art, the sim console's
 * retired A/B/C layout (EigenTrust Command) and AgentWorld's triangle legend (backlog).
 * RED control: against V0641 the bundles name AVT in these keys, the calls pass no unit, and the swept files say AVT.
 */
const SRC = path.resolve(__dirname, '..')
const LOCALES = path.resolve(__dirname, 'locales') + '/'
const AVT = /\bAVT\b/

type Tree = { [k: string]: string | Tree }
function get(o: Tree, key: string): string | undefined {
  let v: string | Tree | undefined = o
  for (const k of key.split('.')) v = v && typeof v === 'object' ? v[k] : undefined
  return typeof v === 'string' ? v : undefined
}
const bundle = (file: string): Tree => JSON.parse(readFileSync(LOCALES + file, 'utf-8'))
const files = readdirSync(LOCALES).filter((f) => f.endsWith('.json'))
const read = (rel: string) => readFileSync(path.join(SRC, rel), 'utf-8')

/** the keys and the files that call them, each call passing the unit */
const KEYS: Array<[string, string]> = [
  ['adminFiatOpsView.hero.h1a', 'views/AdminFiatOps.vue'],
  ['adminFiatOpsView.hero.h1b', 'views/AdminFiatOps.vue'],
  ['adminTreasuryView.mintAvt', 'views/AdminTreasury.vue'],
  ['adminTreasuryView.mintAvtTitle', 'views/AdminTreasury.vue'],
  ['adminTreasuryView.mintModal.title', 'views/AdminTreasury.vue'],
  ['agentForgeView.subtitle', 'views/AgentForge.vue'],
  ['agentForgeView.steps.welcome.lead', 'views/AgentForge.vue'],
  ['senateView.funding.pendingAvt', 'views/SenateFloor.vue'],
]

/** the swept files: none names AVT outside a comment */
const SWEPT = [
  'views/AdminFiatOps.vue', 'views/AdminTreasury.vue', 'views/AgentForge.vue', 'views/SenateFloor.vue',
  'components/admin/WorkerTasksPanel.vue', 'components/admin/CanaryRebalancerModal.vue',
  'components/admin/SupplyAuditorModal.vue', 'components/common/CommandPalette.vue', 'views/ForexDesk.vue',
  'components/landing/ShowcaseChat.vue', 'components/cicd/TemplateSelectionModal.vue',
  'components/myagents/PaymentTokensPanel.vue', 'components/DashboardSidebar.vue', 'services/voice/intentGrammar.ts',
  'composables/useAssistantBrains.ts',
]

/** the text a reader can meet: block comments, HTML comments and line comments taken out (a URL's // keeps its colon) */
function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .split('\n').map((l) => l.replace(/(^|[^:'"`])\/\/.*$/, '$1')).join('\n')
}

describe('the frame\'s unit, never AVT on every frame', () => {
  it('has the nine bundles and the keys in English, each with {unit}', () => {
    expect(files.length).toBe(9)
    const en = bundle('en.json')
    const pair = (get(en, KEYS[0][0]) || '') + (get(en, KEYS[1][0]) || '')
    expect(pair.match(/\{unit\}/g)?.length).toBe(1)
    for (const [key] of KEYS.slice(2)) expect(get(en, key), key).toContain('{unit}')
  })

  it.each(files)('%s names no AVT in these keys, and {unit} only where English has it', (file) => {
    const b = bundle(file)
    const en = bundle('en.json')
    for (const [key] of KEYS) {
      const v = get(b, key)
      if (v === undefined) continue
      expect(v, key).not.toMatch(AVT)
      if (v.includes('{unit}')) expect(key.startsWith('adminFiatOpsView.hero.') || (get(en, key) || '').includes('{unit}'), key).toBe(true)
    }
  })

  it('every call of these keys passes the unit through tp()', () => {
    let calls = 0
    for (const [key, file] of KEYS) {
      const src = read(file)
      const bare = new RegExp(`\\bt\\('${key.replace(/\./g, '\\.')}'`)
      expect(src, `${file}: a bare t() of ${key}`).not.toMatch(bare)
      const re = new RegExp(`tp\\('${key.replace(/\./g, '\\.')}', '[^']*', \\{ unit(: \\w+)? \\}\\)`, 'g')
      const n = [...src.matchAll(re)].length
      expect(n, `${file}: ${key}`).toBeGreaterThan(0)
      calls += n
    }
    expect(calls).toBe(8)
  })

  it.each(['en', 'de'])('vue-i18n renders each key with the unit (%s)', (locale) => {
    type Loose = (o: Record<string, unknown>) => { global: { t: (key: string, params: Record<string, string>) => string } }
    const { t } = (createI18n as unknown as Loose)({ legacy: false, locale, fallbackLocale: 'en',
      messages: { en: bundle('en.json'), [locale]: bundle(`${locale}.json`) } }).global
    const out = KEYS.map(([key]) => t(key, { unit: 'ECU' })).join(' | ')
    expect(out).not.toMatch(/AVT|\{unit\}/)
    expect(out.match(/ECU/g)?.length).toBeGreaterThanOrEqual(7)
  })

  it.each(SWEPT)('%s names AVT nowhere a reader meets it', (file) => {
    const hits = withoutComments(read(file)).split('\n').filter((l) => AVT.test(l)).map((l) => l.trim().slice(0, 120))
    expect(hits).toEqual([])
  })
})

describe('Fiat Operations greys out in the sidebar while the euro on-ramp is off (D6-836)', () => {
  const src = read('components/DashboardSidebar.vue')
  it('the item asks for the on-ramp, and the lock reads the registry\'s own switch', () => {
    const item = src.match(/\{ name: 'Fiat Operations',[^\n]*\}/)
    expect(item, 'the Fiat Operations item').not.toBeNull()
    expect(item![0]).toContain('requiresFiat: true')
    expect(src).toMatch(/if \(item\.requiresFiat && !_fiatEnabled\.value\) return true/)
    expect(src).toMatch(/const _fiatEnabled = computed\(\(\) => !!_sharedCfg\.value\.fiat_onramp_enabled\)/)
  })
  it('the lock says why, naming the switch', () => {
    const reason = src.match(/kind: 'fiat', title: '([^']+)', sub: '([^']+)'/)
    expect(reason).not.toBeNull()
    expect(reason![1]).toMatch(/on-ramp off/i)
    expect(reason![2]).toContain('FIAT_ONRAMP_ENABLED')
  })
})
