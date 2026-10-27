import { describe, it, expect } from 'vitest'
import { coerceContracts, offersAwaiting, milestonesAwaiting, openDisputeCount } from './attention'

const ME = 'did:theprotocol:me'
const THEM = 'did:theprotocol:them'

describe('attention derivation', () => {
  it('THE BUG: accepts the real {items:[...]} envelope, not just an array', () => {
    // `/contracts/v2/mine` returns { items: [...] }. Passing that envelope to
    // `.filter` threw inside a computed and the error boundary blanked the
    // WHOLE bridge on the live canary. This is that defect, pinned.
    const real = { items: [{ id: 'c1', status: 'offered', provider_did: ME, title: 'T', total_amount: '5', currency: 'BVT' }] }
    expect(coerceContracts(real)).toHaveLength(1)
    expect(offersAwaiting(real, ME)).toHaveLength(1)
  })

  it('never throws on any shape, because throwing here destroys the view', () => {
    for (const junk of [null, undefined, 0, '', 'nope', 42, {}, { items: 'no' }, { items: null }, [null, undefined]]) {
      expect(() => coerceContracts(junk)).not.toThrow()
      expect(() => offersAwaiting(junk, ME)).not.toThrow()
      expect(() => milestonesAwaiting(junk, ME)).not.toThrow()
      expect(() => openDisputeCount(junk)).not.toThrow()
    }
    expect(coerceContracts('nope')).toEqual([])
  })

  it('offers: only OFFERED, only where I am the provider', () => {
    const rows = { items: [
      { id: 'a', status: 'offered',     provider_did: ME,   title: 'mine' },
      { id: 'b', status: 'offered',     provider_did: THEM, title: 'theirs' },
      { id: 'c', status: 'in_progress', provider_did: ME,   title: 'running' },
    ] }
    expect(offersAwaiting(rows, ME).map(o => o.id)).toEqual(['a'])
  })

  it('milestones: only SUBMITTED, only where I am the client', () => {
    const rows = { items: [
      { id: 'a', client_did: ME, currency: 'BVT', title: 'C-A', milestones: [
        { seq: 1, status: 'submitted', title: 'm1', amount: '10' },
        { seq: 2, status: 'released',  title: 'm2', amount: '20' } ] },
      { id: 'b', client_did: THEM, currency: 'BVT', title: 'C-B', milestones: [
        { seq: 1, status: 'submitted', title: 'not mine', amount: '30' } ] },
      { id: 'c', client_did: ME, currency: 'BVT', title: 'C-C' },   // no milestones key at all
    ] }
    const got = milestonesAwaiting(rows, ME)
    expect(got).toHaveLength(1)
    expect(got[0]).toMatchObject({ contractId: 'a', seq: 1, amount: '10', currency: 'BVT' })
  })

  it('an absent acting agent yields nothing rather than everything', () => {
    const rows = { items: [{ id: 'a', status: 'offered', provider_did: ME }] }
    expect(offersAwaiting(rows, null)).toEqual([])
    expect(milestonesAwaiting(rows, null)).toEqual([])
  })

  it('disputes: open and investigating count, resolved does not', () => {
    expect(openDisputeCount([
      { status: 'open' }, { status: 'investigating' }, { status: 'resolved' }, { status: 'dismissed' },
    ])).toBe(2)
  })
})

// ── §BRIDGE R15.1 — the command-queue derivations ───────────────────────────
import { votesAwaiting, guildAwaiting, offersExpiring, claimableRewards,
         attestationsExpiring, humanLeft } from './attention'

const NOW = Date.parse('2026-08-20T12:00:00Z')
const inH = (h: number) => new Date(NOW + h * 3600_000).toISOString()

describe('votesAwaiting', () => {
  const props = [
    { id: 'p1', title: 'open, not voted',  status: 'active', votingEnd: inH(10) },
    { id: 'p2', title: 'already voted',    status: 'active', votingEnd: inH(10) },
    { id: 'p3', title: 'already closed',   status: 'active', votingEnd: inH(-1) },
    { id: 'p4', title: 'already decided',  status: 'passed', votingEnd: inH(10) },
  ]
  it('surfaces only the vote that is genuinely blocked on you', () => {
    const got = votesAwaiting(props, { votes: [{ proposalId: 'p2' }] }, NOW)
    expect(got.map(v => v.id)).toEqual(['p1'])
    expect(got[0].closesInMs).toBe(10 * 3600_000)
  })
  it('accepts the several shapes a vote list arrives in', () => {
    for (const mine of [[{ proposal_id: 'p1' }], { votes: [{ proposal: { id: 'p1' } }] }]) {
      expect(votesAwaiting(props, mine, NOW).some(v => v.id === 'p1')).toBe(false)
    }
  })
  it('a proposal with no end date is still a request, not a silent drop', () => {
    expect(votesAwaiting([{ id: 'x', status: 'voting' }], [], NOW)).toEqual([
      { id: 'x', title: '', closesInMs: null },
    ])
  })
})

describe('guildAwaiting', () => {
  const ME = 'did:theprotocol:me', OTHER = 'did:theprotocol:other'
  const orders = {
    orders: [
      { id: 'g1', title: 'bids in',      status: 'open',      poster_did: ME,    bid_count: 3 },
      { id: 'g2', title: 'no bids yet',  status: 'open',      poster_did: ME,    bid_count: 0 },
      { id: 'g3', title: 'mine to do',   status: 'awarded',   worker_did: ME, bounty: '50', currency: 'BVT' },
      { id: 'g4', title: 'to verify',    status: 'submitted', poster_did: ME, bounty: '80', currency: 'BVT' },
      { id: 'g5', title: 'not mine',     status: 'submitted', poster_did: OTHER },
    ],
  }
  it('separates the three states that are blocked on a human', () => {
    const g = guildAwaiting(orders, ME)
    expect(g.bidsToAward.map(x => x.id)).toEqual(['g1'])   // g2 has no bids: nothing to decide
    expect(g.awardedToYou.map(x => x.id)).toEqual(['g3'])
    expect(g.toVerify.map(x => x.id)).toEqual(['g4'])      // g5 is someone else's
  })
  it('without an acting agent it claims nothing', () => {
    const g = guildAwaiting(orders, null)
    expect(g.bidsToAward.concat(g.awardedToYou as any, g.toVerify as any)).toEqual([])
  })
})

describe('offersExpiring', () => {
  const ME = 'did:theprotocol:me'
  it('only offers YOU sent, only inside the window, never already-lapsed', () => {
    const cs = { items: [
      { id: 'c1', title: 'soon',    status: 'offered', client_did: ME, offer_expires_at: inH(5) },
      { id: 'c2', title: 'distant', status: 'offered', client_did: ME, offer_expires_at: inH(200) },
      { id: 'c3', title: 'lapsed',  status: 'offered', client_did: ME, offer_expires_at: inH(-2) },
      { id: 'c4', title: 'no date', status: 'offered', client_did: ME },
    ] }
    expect(offersExpiring(cs, ME, NOW).map(o => o.id)).toEqual(['c1'])
  })
})

describe('claimableRewards', () => {
  it('reads scientific notation, which is how balances arrive here', () => {
    expect(claimableRewards({ availableRewards: '1E+3' })).toBe(1000)
  })
  it('zero and junk are not a request', () => {
    for (const v of [{ availableRewards: '0' }, {}, null, { availableRewards: 'x' }]) {
      expect(claimableRewards(v)).toBe(0)
    }
  })
})

describe('attestationsExpiring', () => {
  it('lapsing soon counts; already lapsed does not (the decision is past)', () => {
    const recs = [{ id: 'a1', expires_at: inH(24) }, { id: 'a2', expires_at: inH(-1) },
                  { id: 'a3', valid_until: inH(24 * 30) }]
    expect(attestationsExpiring(recs, NOW).map(a => a.id)).toEqual(['a1'])
  })
})

describe('R15 derivations never throw', () => {
  it('survives every junk shape, because a throw here blanks the bridge', () => {
    for (const j of [null, undefined, 0, '', 'no', 42, {}, { items: 'x' }, [null], { orders: 3 }]) {
      expect(() => votesAwaiting(j, j, NOW)).not.toThrow()
      expect(() => guildAwaiting(j, 'did:x')).not.toThrow()
      expect(() => offersExpiring(j, 'did:x', NOW)).not.toThrow()
      expect(() => claimableRewards(j)).not.toThrow()
      expect(() => attestationsExpiring(j, NOW)).not.toThrow()
    }
  })
})

describe('humanLeft', () => {
  it('states a deadline the way a person would', () => {
    expect(humanLeft(30 * 60000)).toBe('30m')
    expect(humanLeft(5 * 3600_000)).toBe('5h')
    expect(humanLeft(50 * 3600_000)).toBe('2d 2h')
  })
  it('says nothing rather than something false when there is no deadline', () => {
    for (const v of [null, undefined, 0, -1, NaN]) expect(humanLeft(v as any)).toBe('')
  })
})

// ── §BRIDGE R15.4 — the cross-registry fan-out ──────────────────────────────
import { foreignRegistryGroups, foreignNeedsCount } from './attention'

describe('foreignRegistryGroups', () => {
  const HERE = 'https://frame-c.theprotocol.cloud'
  const creds = {
    a: { did: 'a', client_id: 'ca', client_secret: 's', registry_url: HERE },                      // same origin
    b: { did: 'b', client_id: 'cb', client_secret: 's', registry_url: 'https://op-berlin.op.x/' },
    c: { did: 'c', client_id: 'cc', client_secret: 's', registry_url: 'https://op-berlin.op.x/ui' },
    d: { did: 'd', client_id: 'cd', client_secret: 's', registry_url: 'https://op-tokyo.op.x' },
    e: { did: 'e', client_id: 'ce', registry_url: 'https://op-paris.op.x' },                        // no secret
    f: { did: 'f', client_id: 'cf', client_secret: 's', registry_url: 'not a url' },
    g: { did: 'g', client_id: 'cg', client_secret: 's' },                                           // no url
  }
  it('groups by ORIGIN and excludes this origin', () => {
    const g = foreignRegistryGroups(creds, HERE)
    expect(g.map(x => x.host)).toEqual(['op-berlin.op.x', 'op-tokyo.op.x'])
    expect(g[0].agents.map((a: any) => a.did)).toEqual(['b', 'c'])   // same origin, two paths
  })
  it('drops anything it could not act on: no secret, no url, bad url', () => {
    const hosts = foreignRegistryGroups(creds, HERE).map(x => x.host)
    expect(hosts).not.toContain('op-paris.op.x')
  })
  it('is bounded, because each group costs real requests', () => {
    const many: any = {}
    for (let i = 0; i < 20; i++) many[`k${i}`] = { did: `d${i}`, client_id: 'c', client_secret: 's', registry_url: `https://r${i}.x` }
    expect(foreignRegistryGroups(many, HERE).length).toBe(6)
    expect(foreignRegistryGroups(many, HERE, 2).length).toBe(2)
  })
  it('never throws on junk', () => {
    for (const j of [null, undefined, 0, 'x', [], { a: null }]) {
      expect(() => foreignRegistryGroups(j, HERE)).not.toThrow()
    }
  })
})

describe('foreignNeedsCount', () => {
  it('uses the same derivations as the local queue', () => {
    const ME = 'did:me'
    const contracts = { items: [
      { id: 'c1', status: 'offered', provider_did: ME },
      { id: 'c2', client_did: ME, milestones: [{ seq: 1, status: 'submitted' }] },
    ] }
    const guild = { orders: [{ id: 'g', status: 'open', poster_did: ME, bid_count: 2 }] }
    expect(foreignNeedsCount(contracts, guild, ME)).toBe(3)
  })
  it('is zero without an agent, never everything', () => {
    expect(foreignNeedsCount({ items: [{ status: 'offered', provider_did: 'x' }] }, null, null)).toBe(0)
  })
})
