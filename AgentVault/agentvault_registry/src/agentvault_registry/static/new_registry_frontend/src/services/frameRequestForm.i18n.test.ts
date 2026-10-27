/**
 * §FRAMEFORM rebuild (2026-09-13): the frame request asks some keys through a variable (a switch's label and hint, a
 * rule's sentence), and no literal extractor can see those, so the raw-key gate cannot hold them to the bundles. This
 * does, for English and for German (the two complete locales), and checks the German keeps every placeholder.
 */
import { describe, expect, it } from 'vitest'
import de from '@/i18n/locales/de.json'
import en from '@/i18n/locales/en.json'
import { FRAME_FEATURE_SWITCHES } from './api/frameRequests'
import helperSource from './frameRequestForm.ts?raw'

type Tree = Record<string, unknown>

const lookup = (bundle: Tree, key: string): unknown =>
  key.split('.').reduce<unknown>((node, part) => (node && typeof node === 'object' ? (node as Tree)[part] : undefined), bundle)

const leaves = (node: unknown, prefix: string): [string, string][] => {
  if (typeof node === 'string') return [[prefix, node]]
  if (!node || typeof node !== 'object') return []
  return Object.entries(node as Tree).flatMap(([k, v]) => leaves(v, `${prefix}.${k}`))
}

const placeholders = (text: string): string => [...new Set(text.match(/\{[A-Za-z]+\}/g) || [])].sort().join(',')

const RULE_CALL = /\b(error|warning)\('([A-Za-z]+)'/g
const ruleKeys = [...new Set([...helperSource.matchAll(RULE_CALL)]
  .map(m => `frameCommanderView.${m[1] === 'error' ? 'errors' : 'warnings'}.${m[2]}`))]
const switchKeys = FRAME_FEATURE_SWITCHES.flatMap(sw => [
  `frameCommanderView.switches.${sw.key}.label`,
  `frameCommanderView.switches.${sw.key}.hint`,
])
const english = leaves((en as Tree).frameCommanderView, 'frameCommanderView')

/**
 * §FESUITE V0595 (his rule 2026-10-04: no translation work now; each gap goes to
 * sessionlogs2026/BACKLOG_2026-10-04_TRANSLATIONS.md): the keys V0595 added in English, German still to come. Named one
 * by one so the German checks stay strict for every other key; a key leaves this list the day German gets it (the
 * last test below fails while a listed key has German, and while one is not in English at all).
 */
const BACKLOGGED_DE = new Set<string>([
  'frameCommanderView.switches.passport_trading.label',
  'frameCommanderView.switches.passport_trading.hint',
  'frameCommanderView.switches.contract_templates.label',
  'frameCommanderView.switches.contract_templates.hint',
  'frameCommanderView.switches.staking.label',
  'frameCommanderView.switches.staking.hint',
  'frameCommanderView.switches.staking_rewards.label',
  'frameCommanderView.switches.staking_rewards.hint',
  'frameCommanderView.switches.agora_distributions.label',
  'frameCommanderView.switches.agora_distributions.hint',
  'frameCommanderView.switches.genesis_grant.label',
  'frameCommanderView.switches.genesis_grant.hint',
  'frameCommanderView.switches.reputation_bond.label',
  'frameCommanderView.switches.reputation_bond.hint',
  'frameCommanderView.switches.governance_weight.label',
  'frameCommanderView.switches.governance_weight.hint',
  'frameCommanderView.switches.federation_ballots.label',
  'frameCommanderView.switches.federation_ballots.hint',
  'frameCommanderView.switches.commons.label',
  'frameCommanderView.switches.commons.hint',
  'frameCommanderView.switches.jurisdiction.label',
  'frameCommanderView.switches.jurisdiction.hint',
  'frameCommanderView.options.on',
  'frameCommanderView.options.member',
  'frameCommanderView.options.lock',
  'frameCommanderView.switchboard.resetFrame',
  'frameCommanderView.switchboard.frameValue',
  'frameCommanderView.switchboard.lockedBy',
  'frameCommanderView.switchboard.allFrame',
  'frameCommanderView.switchboard.changedOneFrame',
  'frameCommanderView.switchboard.changedManyFrame',
  'frameCommanderView.switchboard.groups.governanceTitle',
  'frameCommanderView.switchboard.groups.governanceLead',
])

describe('frame request keys asked through a variable', () => {
  it('reads the rule sentences out of the helper (a broken pattern would find none)', () => {
    expect(ruleKeys).toContain('frameCommanderView.errors.frameName')
    expect(ruleKeys).toContain('frameCommanderView.warnings.openDoor')
    expect(ruleKeys.length).toBeGreaterThanOrEqual(20)
  })

  for (const [name, bundle] of [['en', en], ['de', de]] as [string, Tree][]) {
    it(`resolves every switch label and hint in ${name}`, () => {
      const owed = name === 'de' ? BACKLOGGED_DE : new Set<string>()
      expect(switchKeys.filter(k => !owed.has(k) && typeof lookup(bundle, k) !== 'string')).toEqual([])
    })

    it(`resolves every rule and warning sentence in ${name}`, () => {
      expect(ruleKeys.filter(k => typeof lookup(bundle, k) !== 'string')).toEqual([])
    })
  }

  it('gives German every key English has', () => {
    expect(english.filter(([key]) => !BACKLOGGED_DE.has(key) && typeof lookup(de as Tree, key) !== 'string').map(([key]) => key)).toEqual([])
  })

  it('backlogs only keys English has and German does not', () => {
    expect([...BACKLOGGED_DE].filter(k => typeof lookup(en as Tree, k) !== 'string'), 'listed but not in English').toEqual([])
    expect([...BACKLOGGED_DE].filter(k => typeof lookup(de as Tree, k) === 'string'), 'has German now: take it off the list').toEqual([])
  })

  it('keeps every placeholder of the English sentence in the German one', () => {
    const drift = english
      .filter(([key, text]) => {
        const translated = lookup(de as Tree, key)
        return typeof translated === 'string' && placeholders(translated) !== placeholders(text)
      })
      .map(([key]) => key)
    expect(drift).toEqual([])
  })

  it('translates the German sentences rather than copying the English ones', () => {
    const copied = english.filter(([key, text]) => text.length > 24 && lookup(de as Tree, key) === text).map(([key]) => key)
    expect(copied).toEqual([])
  })
})
