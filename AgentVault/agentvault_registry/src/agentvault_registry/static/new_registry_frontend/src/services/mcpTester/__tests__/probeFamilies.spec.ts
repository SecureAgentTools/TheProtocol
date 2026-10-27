import { describe, it, expect } from 'vitest'
import { PROBE_FAMILIES, familyOf, probeSubject, tallyFamilies } from '../probeFamilies'
import { rowCategory, rowLabel, rowKinds, rowKindPhrases, probeMetaPhrases } from '../categories'

// Row names as round 10 recorded them (run 8a6ad7313a8f4666 on sbx-alpha, 2026-10-01), one or two per family, plus the
// four families V0532-V0533 added (ledger, filter, enum, a2a_race).
const PROBE_ROWS = [
  'hygiene: discoverAgents', 'write_hygiene: createApiKey', 'types: describeTools', 'range: getActivityFeedByType',
  'amount: authorizePayment NaN', 'bounds: getAdminAgents', 'pagination: discoverAgents',
  'list_detail: discoverAgents -> getAgentProfile', 'owner_scoping: addTeamMember (another org\'s admin)',
  'scope: narrowed key, admin surface', 'revocation: deleteMyApiKey', 'race: createOrganizationTeam concurrent',
  'overdraft: transferUnits', 'idempotency: concurrent transferUnits', 'mcp_protocol: completion',
  'mcp_tester: credential_exposure_census', 'enfprop_refusal', 'enfprop_control_active',
  'ledger: the run\'s sentinel over the lifecycle phase', 'filter: getMyAgents', 'enum: getInviteCodes', 'a2a_race: settle twice at once',
  // the cloud-op sweep's token-scope row, counted since V0529 and shown since V0536
  'token_scope: operator admin at its parent frame',
]

describe('§MCPTEST30 V0535: every probe row has a family, and every family is named once', () => {
  it('places every probe row round 10 recorded, and the families added since', () => {
    for (const name of PROBE_ROWS) {
      expect(familyOf(name), name).not.toBeNull()
    }
  })

  it('leaves tool rows, console rows and unknown prefixes to the view\'s own rules', () => {
    expect(familyOf('theprotocol_getMyAgents')).toBeNull()
    expect(familyOf('ui:wallet_send.step_3')).toBeNull()
    expect(familyOf('nosuchfamily: getMyAgents')).toBeNull()
    expect(familyOf('federation_suite: a2a_payment/a2a_payment_endpoint_routing_per_frame')).toBeNull()
  })

  it('names each family once, with a label and a sentence saying what its pass means', () => {
    const ids = PROBE_FAMILIES.map((f) => f.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const f of PROBE_FAMILIES) {
      expect(f.label.key).toBe(`mcpTester.probes.${f.id}.label`)
      expect(f.proves.key).toBe(`mcpTester.probes.${f.id}.proves`)
      expect(f.label.fallback.length).toBeGreaterThan(2)
      expect(f.proves.fallback).toMatch(/\.$/)
    }
  })

  it('reads the subject after the prefix', () => {
    expect(probeSubject('list_detail: discoverAgents -> getAgentProfile')).toBe('discoverAgents -> getAgentProfile')
    expect(probeSubject('enfprop_refusal')).toBe('enfprop_refusal')
  })

  it('tallies passes, BUG-FINDs, other failures and NOT MEASURED apart, in family order, ignoring tool rows', () => {
    const rows = [
      { tool: 'pagination: discoverAgents', healthy: true, skipped: false, error: null },
      { tool: 'pagination: getMyAgentLogs', healthy: true, skipped: true, error: null },
      { tool: 'pagination: getAdminAgents', healthy: false, skipped: false, error: 'BUG-FIND: pagination: two rows twice' },
      { tool: 'hygiene: discoverAgents', healthy: false, skipped: false, error: 'HTTP 500 from the route' },
      { tool: 'theprotocol_getMyAgents', healthy: true, skipped: false, error: null },
    ]
    const t = tallyFamilies(rows)
    expect(t.map((x) => x.family.id)).toEqual(['hygiene', 'pagination'])
    expect(t[1]).toMatchObject({ total: 3, passed: 1, notMeasured: 1, bugFinds: 1, failed: 0 })
    expect(t[0]).toMatchObject({ total: 1, passed: 0, bugFinds: 0, failed: 1 })
  })
})

describe('§MCPTEST30 V0535: rows that are not tools get categories of their own', () => {
  it('groups a federation suite row by its group, without the "federation_" prefix', () => {
    expect(rowCategory('federation_suite: federation_handshake/peers_answer')).toBe('Federation · handshake')
    expect(rowCategory('federation_suite: cross_frame_economic_flows/fx_quote')).toBe('Federation · cross frame economic flows')
    expect(rowCategory('federation_suite: a2a_payment/a2a_payment_verify_endpoint_routing')).toBe('Federation · a2a payment')
  })

  it('groups a probe row by its family, and keeps agentvault2-44\'s console category', () => {
    expect(rowCategory('hygiene: discoverAgents')).toBe('Probe · Input hygiene')
    expect(rowCategory('enfprop_refusal')).toBe('Probe · Enforcement')
    expect(rowCategory('ui:wallet_send_between_own_agents.open_wallet')).toBe('Console · wallet send between own agents')
  })

  it('returns null for a tool row, so the tool rules still decide it', () => {
    expect(rowCategory('theprotocol_getMyAgents')).toBeNull()
    expect(rowCategory('testApiEndpoint')).toBeNull()
  })

  it('labels a row with what its category does not already say', () => {
    expect(rowLabel('federation_suite: a2a_payment/a2a_payment_expiry_reactor_active')).toBe('a2a_payment_expiry_reactor_active')
    expect(rowLabel('pagination: getAdminAgents')).toBe('getAdminAgents')
    expect(rowLabel('ui:wallet_send.open_wallet')).toBe('open_wallet')
    expect(rowLabel('theprotocol_getMyAgents')).toBe('getMyAgents')
    expect(rowLabel('nosuchfamily: x')).toBe('nosuchfamily: x')
  })
})

describe('§MCPTEST30 V0536: a run\'s rows are named by what they are', () => {
  it('counts a federation run\'s tests as tests, not tools (round 10: 586 rows)', () => {
    const names = Array.from({ length: 586 }, (_, i) => `federation_suite: group_${i % 159}/test_${i}`)
    const k = rowKinds(names, 586)
    expect(k).toMatchObject({ rows: 586, tools: 0, probes: 0, federation: 586, console: 0 })
    expect(rowKindPhrases(k).map((p) => [p.key, p.params])).toEqual([['mcpTester.rows.federationTests', { n: 586 }]])
  })

  it('splits a strict run into tool rows and probe checks by family, and counts console steps apart', () => {
    const names = ['theprotocol_getMyAgents', 'theprotocol_discoverAgents', 'hygiene: discoverAgents',
      'pagination: getAdminAgents', 'pagination: discoverAgents', 'ui:wallet_send.open_wallet']
    const k = rowKinds(names, names.length)
    expect(k).toMatchObject({ rows: 6, tools: 2, probes: 3, families: 2, federation: 0, console: 1 })
    expect(rowKindPhrases(k).map((p) => p.key)).toEqual(['mcpTester.rows.tools', 'mcpTester.rows.probes', 'mcpTester.rows.consoleStep'])
  })

  it('says one in the singular, and one family when there is one', () => {
    expect(rowKindPhrases(rowKinds(['theprotocol_x', 'token_scope: operator admin at its parent frame'], 2)).map((p) => p.key))
      .toEqual(['mcpTester.rows.tool', 'mcpTester.rows.probe'])
    expect(rowKindPhrases(rowKinds(['hygiene: a', 'hygiene: b'], 2)).map((p) => [p.key, p.params]))
      .toEqual([['mcpTester.rows.probesOneFamily', { n: 2 }]])
  })

  it('adds up to the run\'s own count: a counted row the list lacks is a tool row (the cloud-op run before V0536)', () => {
    const k = rowKinds(['mcp_tester: credential_exposure_census', 'theprotocol_getMyAgents'], 3)
    expect(k).toMatchObject({ rows: 3, tools: 2, probes: 1 })
    expect(rowKindPhrases(rowKinds([], 0))).toEqual([])
  })

  it('V0539: says how many counted rows the list does not carry (All tools read 749 beside "750 rows")', () => {
    const k = rowKinds(['mcp_tester: credential_exposure_census', 'theprotocol_getMyAgents'], 3)
    expect(k.unlisted).toBe(1)
    expect(rowKindPhrases(k).map((p) => p.key)).toEqual(['mcpTester.rows.tools', 'mcpTester.rows.probe', 'mcpTester.rows.unlisted'])
    expect(rowKindPhrases(rowKinds(['theprotocol_a'], 4)).slice(-1)[0]).toEqual(
      { key: 'mcpTester.rows.unlistedMany', fallback: '{n} not in the list', params: { n: 3 } })
    expect(rowKinds(['theprotocol_a', 'theprotocol_b'], 1).unlisted).toBe(0)
  })
})

describe('§MCPTEST30 V0539: the Probes tab counts in its own words', () => {
  it('says one family and one check in the singular ("1 FAMILIES")', () => {
    expect(probeMetaPhrases(1, 2, 0).map((p) => [p.key, p.params])).toEqual([
      ['mcpTester.probes.family', {}], ['mcpTester.probes.checks', { n: 2 }], ['mcpTester.probes.bugFinds', { n: 0 }]])
    expect(probeMetaPhrases(22, 1, 3).map((p) => p.key)).toEqual(
      ['mcpTester.probes.families', 'mcpTester.probes.check', 'mcpTester.probes.bugFinds'])
  })
})

describe('§MCPTEST30 V0636: the families the console placed nowhere', () => {
  it('places refusal, zk v2, chat and achievements rows in a family of their own', () => {
    expect(familyOf('refusal: rotateAgentCredentials an agent that does not exist')?.id).toBe('refusal')
    expect(familyOf('zk v2: the catalog')?.id).toBe('zk_v2')
    expect(probeSubject('zk v2: the catalog')).toBe('the catalog')
    expect(familyOf('chat: a thread read by an agent that is no participant')?.id).toBe('chat')
    expect(familyOf('achievements: an unearned claim pays nothing')?.id).toBe('achievements')
  })
})
