import { describe, expect, it } from 'vitest'
import { FRAME_FEATURE_SWITCHES, type FrameRequestAdminRead } from './api/frameRequests'
import {
  FEATURE_GROUPS, FIRST_YEAR_CATEGORIES, LICENCE_CATEGORIES, MAP_BAND, STEPS, blankDraft, buildRequestPayload, changedFeatures, draftWarnings, firstStepWithIssues,
  frameAddresses, fromMapPoint, mercatorBandRange, networkNames, partnerOptions, provisioningPrefill, requestTags, restoreDraft,
  serializeDraft, setFeature, stepIssues, suggestFrameName, suggestTicker, toMapPoint, validateDraft,
  type FrameRequestDraft,
} from './frameRequestForm'

const complete = (over: Partial<FrameRequestDraft> = {}): FrameRequestDraft => ({
  ...blankDraft(),
  organization: 'Plum Industries GmbH', contact_name: 'Ada Plum', email: 'ada@plum.example',
  frame_name: 'plum', display_name: 'Plum Proof', description: 'A frame for plum logistics.',
  ticker: 'PLUM', currency_name: 'Plum Unit', mint: '1,000,000', genesis_grant: '1000',
  location: 'Freilassing, Bavaria', lat: '47.84', lng: '12.98', website: 'https://plum.example', tags: ['logistics', 'eu'],
  partners: ['EU'], use_case: 'Our regulator wants identity issuance inside our jurisdiction.',
  ...over,
})

describe('validateDraft', () => {
  it('accepts a complete draft', () => {
    expect(validateDraft(complete())).toEqual({})
  })

  it('holds a frame name to what the host frame runner can provision', () => {
    for (const bad of ['Plum', 'pl', 'plum-', '1plum', 'p'.repeat(32), 'plum_proof']) {
      expect(validateDraft(complete({ frame_name: bad })).frame_name?.key, bad).toBe('frameCommanderView.errors.frameName')
    }
    for (const good of ['plm', 'plum-proof-2', 'p'.repeat(31)]) expect(validateDraft(complete({ frame_name: good })).frame_name, good).toBeUndefined()
  })

  it('refuses a name the platform or the network already answers on, and names it', () => {
    expect(validateDraft(complete({ frame_name: 'eu' })).frame_name?.key).toBe('frameCommanderView.errors.frameName')
    const issue = validateDraft(complete({ frame_name: 'asia' })).frame_name
    expect(issue?.key).toBe('frameCommanderView.errors.frameNameTaken')
    expect(issue?.params).toEqual({ name: 'asia' })
    expect(validateDraft(complete({ frame_name: 'lisbon' }), ['Lisbon']).frame_name?.key).toBe('frameCommanderView.errors.frameNameTaken')
  })

  it('checks currency, mint and grant as people type them', () => {
    expect(validateDraft(complete({ ticker: 'PLUMMY7' })).ticker?.key).toBe('frameCommanderView.errors.ticker')
    expect(validateDraft(complete({ ticker: 'plum' })).ticker?.key).toBe('frameCommanderView.errors.ticker')
    expect(validateDraft(complete({ mint: '1 000 000 000' })).mint).toBeUndefined()
    expect(validateDraft(complete({ mint: '1000000001' })).mint?.key).toBe('frameCommanderView.errors.mint')
    expect(validateDraft(complete({ mint: '0' })).mint?.key).toBe('frameCommanderView.errors.mint')
    expect(validateDraft(complete({ genesis_grant: '2000000' })).genesis_grant?.key).toBe('frameCommanderView.errors.grant')
    expect(validateDraft(complete({ genesis_grant: '' })).genesis_grant).toBeUndefined()
  })

  it('requires a declared place: coordinates in range, an https website or none', () => {
    expect(validateDraft(complete({ lat: '' })).lat?.key).toBe('frameCommanderView.errors.required')
    expect(validateDraft(complete({ lat: '91' })).lat?.key).toBe('frameCommanderView.errors.lat')
    expect(validateDraft(complete({ lng: '47,5' })).lng).toBeUndefined()
    expect(validateDraft(complete({ lng: '-181' })).lng?.key).toBe('frameCommanderView.errors.lng')
    expect(validateDraft(complete({ website: 'http://plum.example' })).website?.key).toBe('frameCommanderView.errors.website')
    expect(validateDraft(complete({ website: '' })).website).toBeUndefined()
    expect(validateDraft(complete({ tags: ['x'.repeat(25)] })).tags?.key).toBe('frameCommanderView.errors.tags')
  })

  it('asks for a hostname only when the frame runs on the requester\'s own infrastructure', () => {
    expect(validateDraft(complete({ hostname: '' })).hostname).toBeUndefined()
    expect(validateDraft(complete({ hosting: 'self', hostname: '' })).hostname?.key).toBe('frameCommanderView.errors.required')
    expect(validateDraft(complete({ hosting: 'self', hostname: 'frame.plum.example' })).hostname).toBeUndefined()
    expect(validateDraft(complete({ hosting: 'self', hostname: 'localhost' })).hostname?.key).toBe('frameCommanderView.errors.hostname')
  })

  it('wants a reason of at least ten characters', () => {
    const issue = validateDraft(complete({ use_case: 'because' })).use_case
    expect(issue?.key).toBe('frameCommanderView.errors.useCaseShort')
    expect(issue?.params).toEqual({ min: 10 })
  })
})

describe('steps', () => {
  it('file every issue under the step that asks the field, and find the first step to fix', () => {
    const issues = validateDraft(complete({ email: 'nope', ticker: '' }))
    expect(Object.keys(stepIssues(issues, 'contact'))).toEqual(['email'])
    expect(Object.keys(stepIssues(issues, 'currency'))).toEqual(['ticker'])
    expect(firstStepWithIssues(issues)).toBe(STEPS.indexOf('contact'))
    expect(firstStepWithIssues(validateDraft(complete()))).toBe(-1)
  })
})

describe('frameAddresses', () => {
  it('derives a hosted frame\'s addresses the way the host frame runner does', () => {
    expect(frameAddresses({ frame_name: 'plum', hosting: 'theprotocol', hostname: '' })).toEqual({
      console: 'https://plum.theprotocol.cloud', ledger: 'https://plum-es.theprotocol.cloud',
      trustDomain: 'plum.theprotocol.cloud', spiffe: 'spiffe://plum.theprotocol.cloud',
      federation: 'https://plum.theprotocol.cloud:8443',
    })
    expect(frameAddresses({ frame_name: 'Plum', hosting: 'theprotocol', hostname: '' })).toBeNull()
  })

  it('uses the requester\'s own hostname when they host it', () => {
    const a = frameAddresses({ frame_name: 'plum', hosting: 'self', hostname: 'Frame.Plum.example' })
    expect(a?.console).toBe('https://frame.plum.example')
    expect(a?.ledger).toBeNull()
    expect(frameAddresses({ frame_name: 'plum', hosting: 'self', hostname: '' })).toBeNull()
  })
})

describe('suggestions', () => {
  it('offers a frame name from the organization', () => {
    expect(suggestFrameName('Sovereign Org GmbH')).toBe('sovereign-org')
    expect(suggestFrameName('Ōsaka Trade Co.')).toBe('osaka-trade')
    expect(suggestFrameName('42 Labs Ltd')).toBe('labs')
    expect(suggestFrameName('AB')).toBe('')
  })

  it('offers a ticker from a name', () => {
    expect(suggestTicker('Plum Unit')).toBe('PLUM')
    expect(suggestTicker('Juicer Unit Token')).toBe('JUT')
    expect(suggestTicker('X')).toBe('')
  })
})

describe('features', () => {
  it('group every catalog switch exactly once, so a new switch cannot vanish from the form', () => {
    const grouped = FEATURE_GROUPS.flatMap(g => g.keys)
    expect([...grouped].sort()).toEqual(FRAME_FEATURE_SWITCHES.map(sw => sw.key).sort())
    expect(new Set(grouped).size).toBe(grouped.length)
  })

  it('move agent permissions and delegation together', () => {
    const next = setFeature(blankDraft().features, 'agent_permissions', 'enforce')
    expect([next.agent_permissions, next.delegation]).toEqual(['enforce', 'enforce'])
    expect(setFeature(next, 'delegation', 'off').agent_permissions).toBe('off')
  })

  it('send only what changed', () => {
    const f = setFeature(blankDraft().features, 'fiat_onramp', 'yes')
    expect(changedFeatures(f)).toEqual({ fiat_onramp: 'yes' })
    expect(changedFeatures(blankDraft().features)).toEqual({})
  })

  it('warn about a switch the request cannot yet use', () => {
    const keys = (d: FrameRequestDraft) => draftWarnings(d).map(w => w.key.split('.').pop())
    expect(keys(complete())).toEqual([])
    expect(keys(complete({ intent: 'standalone' }))).toContain('needsFederation')
    expect(keys(complete({ features: setFeature(blankDraft().features, 'invite_only', 'no') }))).toContain('openDoor')
    expect(keys(complete({ hosting: 'self', hostname: 'frame.plum.example' }))).toContain('selfHosted')
  })

  it('does not say a self-hosted frame waits for the release where the frame kit is offered (§HELLOFRAME)', () => {
    const self = complete({ hosting: 'self', hostname: 'frame.plum.example' })
    const keys = (o: { kitOffered?: boolean }) => draftWarnings(self, o).map(w => w.key.split('.').pop())
    expect(keys({ kitOffered: true })).not.toContain('selfHosted')
    expect(keys({ kitOffered: false })).toContain('selfHosted')   // the control: off, the warning stands
    expect(keys({})).toContain('selfHosted')
  })
})

describe('buildRequestPayload', () => {
  it('builds the body the registry validates, with only the groups that carry something', () => {
    const p = buildRequestPayload(complete({ features: setFeature(blankDraft().features, 'canaries', 'yes') }))
    expect(p).toMatchObject({
      organization: 'Plum Industries GmbH', email: 'ada@plum.example', frame_name: 'plum', display_name: 'Plum Proof',
      trust_domain: 'plum.theprotocol.cloud', ticker: 'PLUM', currency_name: 'Plum Unit', federation_choice: 'A',
    })
    expect(p.hostname).toBeUndefined()
    expect(p.notes).toBeUndefined()
    expect(p.answers).toEqual({
      features: { canaries: 'yes' },
      treasury: { mint: '1000000', genesis_grant: '1000' },
      card: { theme: 'neural', description: 'A frame for plum logistics.', website: 'https://plum.example',
              location: 'Freilassing, Bavaria', lat: 47.84, lng: 12.98, tags: ['logistics', 'eu'] },
      network: { intent: 'federate_later', partners: ['EU'] },
      provisioning: { hosting: 'theprotocol', posture: 'pilot', operators: 0 },
    })
  })

  it('names partners only for a frame that means to federate, and carries a self-hosted name', () => {
    const p = buildRequestPayload(complete({ intent: 'standalone_test_operator', hosting: 'self', hostname: 'Frame.Plum.example' }))
    expect(p.federation_choice).toBe('C')
    expect(p.answers?.network).toEqual({ intent: 'standalone_test_operator' })
    expect([p.hostname, p.trust_domain]).toEqual(['frame.plum.example', 'frame.plum.example'])
  })

  it('stays far under the registry\'s 8 KB answers bound even when every field is full', () => {
    const all = Object.fromEntries(FRAME_FEATURE_SWITCHES.map(sw => [sw.key, sw.options.find(o => o !== sw.def) || sw.def]))
    const p = buildRequestPayload(complete({
      features: all, description: 'd'.repeat(400), tags: Array.from({ length: 8 }, (_, i) => `tag-${i}-${'x'.repeat(16)}`),
      partners: Array.from({ length: 8 }, (_, i) => `frame-${i}`),
    }))
    expect(Object.keys(p.answers || {}).length).toBeLessThanOrEqual(8)
    expect(JSON.stringify(p.answers).length).toBeLessThan(4000)
  })
})

describe('restoreDraft', () => {
  it('reads a saved draft back and keeps the step', () => {
    const d = complete()
    expect(restoreDraft(serializeDraft(d, 3))).toEqual({ draft: d, step: 3 })
  })

  it('ignores what it cannot trust', () => {
    expect(restoreDraft(null)).toBeNull()
    expect(restoreDraft('{not json')).toBeNull()
    expect(restoreDraft(JSON.stringify({ v: 1, step: 0, draft: complete() }))).toBeNull()
    expect(restoreDraft(serializeDraft(blankDraft(), 2))).toBeNull()
    const tampered = JSON.parse(serializeDraft(complete(), 99))
    tampered.draft.hosting = 'moon'
    tampered.draft.tags = [1, 2]
    tampered.draft.features.canaries = 'maybe'
    tampered.draft.injected = 'x'
    const back = restoreDraft(JSON.stringify(tampered))
    expect(back?.step).toBe(STEPS.length - 1)
    expect(back?.draft.hosting).toBe('theprotocol')
    expect(back?.draft.tags).toEqual([])
    expect(back?.draft.features.canaries).toBe('no')
    expect(back?.draft).not.toHaveProperty('injected')
  })
})

describe('the network', () => {
  const rail = [
    { registry_name: 'lisbon', peer_type: 'cloud_operator', public_url: 'https://lisbon.op.theprotocol.cloud' },
    { registry_name: 'asia', peer_type: 'frame', public_url: 'https://asia.theprotocol.cloud' },
    { registry_name: 'EU', peer_type: 'frame', public_url: 'https://eu.theprotocol.cloud' },
    { registry_name: 'shenzhen', peer_type: 'discovered', public_url: null },
  ]

  it('offers this frame first and its peer frames, never an operator or a retired name', () => {
    expect(partnerOptions(rail, { name: 'EU', url: 'https://theprotocol.cloud' })).toEqual([
      { name: 'EU', url: 'https://theprotocol.cloud', self: true },
      { name: 'asia', url: 'https://asia.theprotocol.cloud', self: false },
    ])
  })

  it('knows every name the network answers on', () => {
    expect(networkNames(rail, 'EU').sort()).toEqual(['asia', 'eu', 'lisbon', 'shenzhen'])
  })
})

describe('the map picker', () => {
  it('round-trips a point on the Web Mercator basemap band', () => {
    for (const [lat, lng] of [[47.84, 12.98], [1.29, 103.85], [-33.87, 151.21], [64.15, -21.94]]) {
      const p = toMapPoint(lat, lng, 720, 365)
      expect(fromMapPoint(p.x, p.y, 720, 365)).toEqual({ lat, lng })
    }
  })

  it('places the band edges on the map edges and clamps outside them', () => {
    expect(toMapPoint(MAP_BAND.north, -180, 720, 365)).toEqual({ x: 0, y: 0 })
    expect(toMapPoint(89, 0, 720, 365).y).toBe(0)
    expect(fromMapPoint(-5, 9999, 720, 365)).toEqual({ lat: MAP_BAND.south, lng: -180 })
    const { top, bottom } = mercatorBandRange()
    expect(top).toBeGreaterThan(0)
    expect(bottom).toBeLessThan(1)
  })
})

describe('provisioningPrefill', () => {
  const row = (over: Partial<FrameRequestAdminRead> = {}): FrameRequestAdminRead => ({
    id: 'r1', status: 'pending', created_at: '', updated_at: '', contact_name: 'Ada Plum', contact_email: 'ada@plum.example',
    organization: 'Plum Industries', frame_name: 'plum', display_name: 'Plum Proof', ticker: 'PLUM', currency_name: 'Plum Unit',
    use_case: 'Our regulator wants identity issuance inside our jurisdiction.',
    answers: { treasury: { mint: '250000' }, card: { theme: 'sovereign', location: 'Freilassing', lat: 47.84, lng: 12.98, website: 'https://plum.example' } },
    ...over,
  })

  it('fills the provisioning form from a request', () => {
    expect(provisioningPrefill(row())).toEqual({
      name: 'plum', frame_label: 'Plum Proof', ticker: 'PLUM', currency_name: 'Plum Unit', mint: 250000, theme: 'sovereign',
      description: 'Our regulator wants identity issuance inside our jurisdiction.', operator_label: 'Plum Industries',
      location_label: 'Freilassing', lat: 47.84, lng: 12.98, website: 'https://plum.example',
    })
  })

  it('reads a row stored before the rebuild', () => {
    const old = row({ answers: { card: { location: 'Munich', tags: 'robotics, eu', lat: '48.1' } } })
    const p = provisioningPrefill(old)
    expect([p.location_label, p.lat, p.mint, p.theme]).toEqual(['Munich', undefined, undefined, undefined])
    expect(requestTags(old)).toEqual(['robotics', 'eu'])
  })
})

describe('the stage word (V0364)', () => {
  it('reads a V0363 draft whose stage was still called sandbox as pilot', () => {
    const saved = restoreDraft(JSON.stringify({ v: 2, step: 4, draft: { organization: 'Harbor Systems', posture: 'sandbox' } }))
    expect(saved?.draft.posture).toBe('pilot')
    expect(saved?.step).toBe(4)
  })

  it('never sends the word sandbox', () => {
    expect(JSON.stringify(buildRequestPayload(blankDraft()))).not.toMatch(/sandbox/i)
  })
})

describe('the network licence category (his words 2026-09-28)', () => {
  it('is the server plan list without the network\'s own two, the first year for enterprise and government only', () => {
    expect([...LICENCE_CATEGORIES]).toEqual(['private', 'educational', 'research', 'non-profit', 'enterprise', 'government'])
    expect([...FIRST_YEAR_CATEGORIES]).toEqual(['enterprise', 'government'])
  })

  it('travels only when the frame federates and a category was chosen', () => {
    expect(buildRequestPayload(complete({ licence_category: 'educational' })).answers?.network)
      .toEqual({ intent: 'federate_later', partners: ['EU'], licence_category: 'educational' })
    expect(buildRequestPayload(complete()).answers?.network).not.toHaveProperty('licence_category')
    // control: a standalone frame needs no licence, so a category left from an earlier choice stays home
    expect(buildRequestPayload(complete({ intent: 'standalone', licence_category: 'government' })).answers?.network)
      .toEqual({ intent: 'standalone' })
  })

  it('a saved category comes back, an unknown one does not', () => {
    const d = complete({ licence_category: 'government' })
    expect(restoreDraft(serializeDraft(d, 4))?.draft.licence_category).toBe('government')
    const tampered = JSON.parse(serializeDraft(d, 4))
    tampered.draft.licence_category = 'founding'
    expect(restoreDraft(JSON.stringify(tampered))?.draft.licence_category).toBe('')
  })
})
