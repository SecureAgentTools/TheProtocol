/**
 * §FESUITE V0595 (his word 2026-10-11, "also correct the avt prose in the docs"): the docs show the parts that apply only
 * where a switch is on only where this registry says it is on, and every doc source's markers are sound. The wording
 * half at the end is an early warning for the build; lifecycle 51 (public wording, read live as a visitor) decides.
 */
import { describe, it, expect } from 'vitest'
import { applySwitchBlocks, knownSwitches, offBlocks, switchBlockProblems, switchEnvNames } from './switchBlocks'
import { renderDocsMarkdown, extractHeadings } from './useDocsMarkdown'

const TABLE = [
  '| Task | Purpose |',
  '|------|---------|',
  '| Federation Sync | push and pull cards |',
  '<!-- on: staking_rewards -->',
  '| Distributor | pays where the switch is on |',
  '<!-- /on -->',
  '| EigenTrust | scores |',
].join('\n')

describe('switch blocks', () => {
  it('keeps a table whole either way: the rows of a block show where the switch is on and leave no line where it is not', () => {
    const on = applySwitchBlocks(TABLE, { staking_rewards: true })
    expect(on.text.split('\n')).toEqual([
      '| Task | Purpose |', '|------|---------|', '| Federation Sync | push and pull cards |',
      '| Distributor | pays where the switch is on |', '| EigenTrust | scores |'])
    expect(on.leftOut).toEqual([])
    const off = applySwitchBlocks(TABLE, { staking_rewards: false })
    expect(off.text.split('\n')).toEqual([
      '| Task | Purpose |', '|------|---------|', '| Federation Sync | push and pull cards |', '| EigenTrust | scores |'])
    expect(off.leftOut).toEqual(['staking_rewards'])
    // rendered, the table keeps its last row: a blank or a comment line would have ended it
    expect(renderDocsMarkdown(off.text, { classPrefix: 'opd' })).toMatch(/<td>EigenTrust<\/td>/)
  })

  it('a block inside one line takes only its own words', () => {
    const src = 'Federation and smart contracts<!-- on: fiat_onramp -->, and the euro purchase lane<!-- /on -->.'
    expect(applySwitchBlocks(src, { fiat_onramp: true }).text).toBe('Federation and smart contracts, and the euro purchase lane.')
    expect(applySwitchBlocks(src, { fiat_onramp: false }).text).toBe('Federation and smart contracts.')
  })

  it('a switch this registry did not say shows its parts nowhere, and is reported as unread, never as off', () => {
    const g = applySwitchBlocks(TABLE, {})
    expect(g.text).not.toMatch(/Distributor/)
    expect(g.unread).toEqual(['staking_rewards'])
    expect(g.leftOut, 'an unread switch said "off"').toEqual([])
  })

  it('no marker ever reaches a page, and a source without one is untouched', () => {
    for (const k of [{ staking_rewards: true }, { staking_rewards: false }, {}]) {
      expect(applySwitchBlocks(TABLE, k).text).not.toMatch(/<!--|-->|\u0000/)
    }
    const plain = 'no blocks here\n\n| a | b |\n'
    expect(applySwitchBlocks(plain, {}).text).toBe(plain)
  })

  it('a line inside a code fence can be a block too, and a heading a block takes leaves the table of contents', () => {
    const src = '## Kept\n\n```\nA ──> B\n<!-- on: staking_rewards -->\nA ──> rate\n<!-- /on -->\n```\n\n<!-- on: staking_rewards -->\n## Rate engine\n\ntext\n<!-- /on -->\n'
    const off = applySwitchBlocks(src, { staking_rewards: false }).text
    expect(off).toContain('A ──> B\n```')
    expect(extractHeadings(off).map((h) => h.text)).toEqual(['Kept'])
    expect(extractHeadings(applySwitchBlocks(src, { staking_rewards: true }).text).map((h) => h.text)).toEqual(['Kept', 'Rate engine'])
  })

  it('reads the switches from the registry config only when the read answered', () => {
    const cfg = { staking_rewards_enabled: false, fiat_onramp_enabled: true, agora_distributions_enabled: 'yes' }
    expect(knownSwitches(cfg, true)).toEqual({ staking_rewards: false, fiat_onramp: true })
    expect(knownSwitches(cfg, false), 'a failed read is not the registry\'s answer').toEqual({})
    expect(knownSwitches(null, true)).toEqual({})
    expect(switchEnvNames(['fiat_onramp', 'staking_rewards'])).toEqual(['FIAT_ONRAMP_ENABLED', 'STAKING_REWARDS_ENABLED'])
  })

  it('an off part stands in where the switch is off, and shows neither way where it is not said', () => {
    const src = '| LOW | <!-- on: staking_rewards -->9<!-- /on --><!-- off: staking_rewards -->8<!-- /off --> | R-1, <!-- on: staking_rewards -->R-4, <!-- /on -->R-6 |'
    expect(applySwitchBlocks(src, { staking_rewards: true }).text).toBe('| LOW | 9 | R-1, R-4, R-6 |')
    const off = applySwitchBlocks(src, { staking_rewards: false })
    expect(off.text).toBe('| LOW | 8 | R-1, R-6 |')
    expect(off.leftOut).toEqual(['staking_rewards'])
    const unread = applySwitchBlocks(src, {})
    expect(unread.text, 'an unread switch shows the off words as if it had said off').toBe('| LOW |  | R-1, R-6 |')
    expect(unread.unread).toEqual(['staking_rewards'])
    expect(applySwitchBlocks('<!-- off: fiat_onramp -->x<!-- /off -->', { fiat_onramp: true }).leftOut, 'an off part hidden where the switch is on is not "left out"').toEqual([])
  })

  it('the source gate names every authoring error', () => {
    expect(switchBlockProblems(TABLE)).toEqual([])
    expect(switchBlockProblems('<!-- on: rewards -->x<!-- /on -->')[0]).toMatch(/not a switch a doc may name/)
    expect(switchBlockProblems('<!-- on: staking_rewards -->a<!-- on: fiat_onramp -->b<!-- /on -->').join(' ')).toMatch(/do not nest/)
    expect(switchBlockProblems('<!-- on: staking_rewards -->a').join(' ')).toMatch(/never closes/)
    expect(switchBlockProblems('a<!-- /on -->').join(' ')).toMatch(/no block open/)
    expect(switchBlockProblems('a <!-- a note --> b').join(' ')).toMatch(/not a switch marker/)
    expect(switchBlockProblems('<!-- on:Staking -->a<!-- /on -->').join(' ')).toMatch(/not a switch marker/)
    expect(switchBlockProblems('<!-- on: staking_rewards -->a<!-- /off -->').join(' ')).toMatch(/closes the "on" block/)
    expect(switchBlockProblems('<!-- off: fiat_onramp -->a<!-- /off -->')).toEqual([])
  })
})

const SOURCES = {
  ...import.meta.glob('@/assets/docs/**/*.md', { query: '?raw', import: 'default', eager: true }),
  ...import.meta.glob('@/content/compliance/*.md', { query: '?raw', import: 'default', eager: true }),
} as Record<string, string>

describe('the doc sources', () => {
  it('every marker in every doc source is sound', () => {
    const files = Object.keys(SOURCES)
    expect(files.length, 'the globs found no sources: the gate would pass on nothing').toBeGreaterThan(40)
    const bad = files.flatMap((f) => switchBlockProblems(SOURCES[f]).map((p) => `${f} ${p}`))
    expect(bad).toEqual([])
  })

  it('the sources the docs site also renders hold no off part', () => {
    // docs-site/sync-content.mjs keeps every marker's content and drops the markers: an off part would stand beside the
    // on part it replaces there. The compliance documents are the console's alone and may hold them.
    const shared = Object.keys(SOURCES).filter((f) => f.includes('/assets/docs/'))
    expect(shared.length).toBeGreaterThan(30)
    expect(shared.filter((f) => offBlocks(SOURCES[f]) > 0)).toEqual([])
  })

  /**
   * Early warning for lifecycle 51 on a frame with production's switches (rewards, distributions and the euro lane
   * off): the chapters it flagged on 2026-10-11 (fes-20261011T032003Z-17e0) read clean with every block left out. The
   * patterns are lifecycle 51's rewards, euro and always rules (the ones these chapters hit); an identifier-shaped word
   * (it carries . / or _, a route or a setting) is a code name on a docs page, as 5b ruled for /docs/*. The two '*'
   * sentences are lifecycle 51's allowlist entries for every page (5b).
   */
  const RULES: Array<[string, RegExp]> = [
    ['apy', /\b(?:APY|APR)\b/gi],
    ['yield', /\byields?\b/gi],
    ['reward-flow', /\brewards?\s(?:distribute|daily|rate)\b/gi],
    ['staking-rewards', /\bstaking\srewards?\b/gi],
    ['ipo', /\bIPO\b/gi],
    ['euro-near-money', /\b(?:buy|purchase|price|per month)\b[^.\n]{0,40}\beuros?\b|\beuros?\b[^.\n]{0,40}\b(?:buy|purchase|price|per month)\b/gi],
    ['legacy-unit', /\b(?:AVT|JDAY|BVT)\b/g],
    ['tokens-as-units', /\btoken\s+grants?\b|(?<!\b(?:auth|authentication|access|bearer|refresh|api|jwt|capability|payment|bootstrap|session|csrf|pull|push|device|agent|developer|verification|reset|invite|invitation|signed|spiffe|oauth|id|one-time|join|att_|apt_)[\s-])\btokens\b/gi],
  ]
  const STAR = [
    'They have no euro price, cannot be exchanged back into money, and carry no claim to money.',
  ]
  const FLAGGED = [
    'operator/01_architecture.md', 'operator/02_configuration.md', 'operator/03_federation.md', 'operator/04_token_economy.md',
    'operator/05_api_reference.md', 'operator/10_compliance.md', 'oracle/13_tutorials.md',
    'compliance/AI_System_Lifecycle.md', 'compliance/ISO_42001_Alignment.md', 'compliance/Risk_Assessment_Framework.md',
    'compliance/Incident_Response_Procedures.md', 'compliance/Data_Protection_Policy.md', 'compliance/Change_Management_Policy.md',
    'compliance/Compliance_Audit_Procedures.md',
  ]
  const textOf = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")

  it.each(FLAGGED)('%s reads clean with production\'s switches', (file) => {
    const key = Object.keys(SOURCES).find((k) => k.endsWith('/' + file))
    expect(key, `${file} not found`).toBeTruthy()
    const docsPage = !file.startsWith('compliance/')
    const off = applySwitchBlocks(SOURCES[key as string], { staking_rewards: false, agora_distributions: false, fiat_onramp: false })
    const text = textOf(renderDocsMarkdown(off.text, { classPrefix: 'opd' }))
    const hits: string[] = []
    for (const line of text.split(/\n+/).map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean)) {
      if (STAR.some((s) => line.includes(s))) continue
      for (const [id, re] of RULES) {
        for (const m of line.matchAll(re)) {
          const at = m.index ?? 0
          let a = at
          let b = at + m[0].length
          while (a > 0 && !/\s/.test(line[a - 1])) a--
          while (b < line.length && !/\s/.test(line[b])) b++
          const word = line.slice(a, b).replace(/^[("'`[{]+/, '').replace(/[,;:!?)\]}"'`]+$/, '').replace(/\.+$/, '')
          if (docsPage && word !== m[0] && /[./_]/.test(word)) continue
          hits.push(`[${id}] "${m[0]}" in: ${line.slice(Math.max(0, at - 60), at + 80)}`)
        }
      }
    }
    expect(hits).toEqual([])
  })
})
