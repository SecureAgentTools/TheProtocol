import { describe, it, expect } from 'vitest'
import { rowCategory, rowLabel, rowKinds, rowKindPhrases, probeMetaPhrases, type RowKinds } from '../categories'
import en from '@/i18n/locales/en.json'

const none: RowKinds = { rows: 0, tools: 0, probes: 0, families: 0, federation: 0, console: 0, unlisted: 0 }

describe('the rows of a run that are not tools', () => {
  it('names each kind by its own category and leaves a tool row (or an unknown prefix) to the view', () => {
    expect(rowCategory('ui:wallet_flow.open_sheet')).toBe('Console · wallet flow')
    expect(rowCategory('federation_suite: federation_handshake/test_mtls')).toBe('Federation · handshake')
    expect(rowCategory('federation_suite: cross_frame_economic_flows/test_x')).toBe('Federation · cross frame economic flows')
    expect(rowCategory('hygiene: discoverAgents')).toBe('Probe · Input hygiene')
    expect(rowCategory('enfprop_payee_refused')).toBe('Probe · Enforcement')
    expect(rowCategory('theprotocol_getMyAgents')).toBeNull()
    expect(rowCategory('nosuchfamily: x')).toBeNull()
  })

  it('shows in its cell what its category does not already say', () => {
    expect(rowLabel('federation_suite: federation_handshake/test_mtls')).toBe('test_mtls')
    expect(rowLabel('ui:wallet_flow.open_sheet')).toBe('open_sheet')
    expect(rowLabel('hygiene: discoverAgents')).toBe('discoverAgents')
    expect(rowLabel('theprotocol_getMyAgents')).toBe('getMyAgents')
    expect(rowLabel('theprotocol.getMyAgents')).toBe('getMyAgents')
  })
})

describe('what a run\'s rows are', () => {
  it('counts tools, probe checks and their families, federation tests and console steps, adding up to the total', () => {
    const names = ['theprotocol_a', 'theprotocol_b', 'hygiene: a', 'hygiene: b', 'write_hygiene: c', 'federation_suite: g/t1', 'ui:l.s1']
    expect(rowKinds(names, 7)).toEqual({ rows: 7, tools: 2, probes: 3, families: 2, federation: 1, console: 1, unlisted: 0 })
  })

  it('counts a row the run counts and its list lacks as a tool row, and says how many the list lacks', () => {
    expect(rowKinds(['theprotocol_a', 'hygiene: a'], 3)).toEqual({ rows: 3, tools: 2, probes: 1, families: 1, federation: 0, console: 0, unlisted: 1 })
  })

  it('takes the list\'s length when the run\'s total is lower, so nothing goes negative', () => {
    expect(rowKinds(['theprotocol_a', 'theprotocol_b'], 1)).toMatchObject({ rows: 2, tools: 2, unlisted: 0 })
  })
})

describe('the words for those counts', () => {
  it('says one and many with separate keys, and nothing for a kind that is zero', () => {
    expect(rowKindPhrases({ ...none, rows: 1, tools: 1 })).toEqual([{ key: 'mcpTester.rows.tool', fallback: '1 tool row', params: {} }])
    const many = rowKindPhrases({ ...none, rows: 10, tools: 5, probes: 3, families: 2, federation: 1, unlisted: 1 })
    expect(many.map((p) => p.key)).toEqual(['mcpTester.rows.tools', 'mcpTester.rows.probes', 'mcpTester.rows.federationTest', 'mcpTester.rows.unlisted'])
    expect(many[1].params).toEqual({ n: 3, families: 2 })
    expect(rowKindPhrases(none)).toEqual([])
  })

  it('says one family when every probe check is of one, and one check as one', () => {
    expect(rowKindPhrases({ ...none, rows: 4, probes: 4, families: 1 })[0])
      .toEqual({ key: 'mcpTester.rows.probesOneFamily', fallback: '{n} probe checks in 1 family', params: { n: 4 } })
    expect(rowKindPhrases({ ...none, rows: 1, probes: 1, families: 1 })[0].key).toBe('mcpTester.rows.probe')
  })

  it('gives the Probes tab its three counts', () => {
    expect(probeMetaPhrases(1, 1, 0).map((p) => p.key)).toEqual(['mcpTester.probes.family', 'mcpTester.probes.check', 'mcpTester.probes.bugFinds'])
    expect(probeMetaPhrases(21, 459, 2).map((p) => p.params)).toEqual([{ n: 21 }, { n: 459 }, { n: 2 }])
  })

  it('asks only for keys the English bundle carries', () => {
    const all = [
      ...rowKindPhrases({ rows: 9, tools: 2, probes: 2, families: 2, federation: 2, console: 2, unlisted: 2 }),
      ...rowKindPhrases({ rows: 5, tools: 1, probes: 1, families: 1, federation: 1, console: 1, unlisted: 1 }),
      ...rowKindPhrases({ ...none, rows: 3, probes: 3, families: 1 }),
      ...probeMetaPhrases(1, 1, 0), ...probeMetaPhrases(2, 2, 2),
    ]
    const lookup = (key: string): unknown =>
      key.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), en)
    const missing = [...new Set(all.map((p) => p.key))].filter((k) => typeof lookup(k) !== 'string')
    expect(missing).toEqual([])
  })
})
