import { describe, it, expect } from 'vitest'
import { buildStarPlan, directoryKeyForUrl, type DirectoryLike } from './ownedHomes'

/*
 * The directory as frame-c actually serves it (2026-08-21, 16 entries). The
 * shape matters: an operator's trust_domain is its PARENT FRAME, so a
 * trust-domain fallback would put every op-berlin agent in orbit around
 * Registry-A. That is why placement here matches on NAME only.
 */
const DIR: DirectoryLike[] = [
  { key: 'frame-c', name: 'frame-c', trustDomain: 'frame-c.theprotocol.cloud', names: ['frame-c'] },
  { key: 'frame-b', name: 'Frame-B', trustDomain: 'frame-b.theprotocol.cloud', names: ['Frame-B', 'frame-b'] },
  { key: 'registry-a', name: 'Registry-A', trustDomain: 'agentvault.com', names: ['Registry-A', 'registry-a'] },
  { key: 'op-berlin', name: 'op-berlin', trustDomain: 'agentvault.com', names: ['op-berlin'] },
  { key: 'op-doha', name: 'op-doha', trustDomain: 'frame-c.theprotocol.cloud', names: ['op-doha'] },
  { key: 'op-london', name: 'op-london', trustDomain: 'agentvault.com', names: ['op-london'] },
  { key: 'op-losangeles', name: 'op-losangeles', trustDomain: 'frame-b.theprotocol.cloud', names: ['op-losangeles'] },
]
const ORIGIN = 'https://frame-c.theprotocol.cloud'

describe('directoryKeyForUrl', () => {
  it('names an operator from its host label', () => {
    expect(directoryKeyForUrl('https://op-berlin.op.theprotocol.cloud', DIR)).toBe('op-berlin')
  })
  it('a RENAMED operator answers on its original host, and that is the key', () => {
    // §R11: singapore answers on op-losangeles.*; the directory still keys it
    // op-losangeles, so matching the host label is right, not a bug.
    expect(directoryKeyForUrl('https://op-losangeles.op.theprotocol.cloud/', DIR)).toBe('op-losangeles')
  })
  it('returns null for a host it cannot name, rather than a guess', () => {
    expect(directoryKeyForUrl('https://somewhere-else.example/', DIR)).toBeNull()
    expect(directoryKeyForUrl('not a url', DIR)).toBeNull()
    expect(directoryKeyForUrl(null, DIR)).toBeNull()
  })
})

describe('buildStarPlan — his account, measured', () => {
  // 4,440 owned on frame-c (live count, /developers/me/agent-dids) and ~131 on
  // each operator he is signed in to (live count on op-berlin: 131).
  const localDids = Array.from({ length: 4440 }, (_, i) => `did:local:${i}`)
  const opKeys = ['op-berlin', 'op-doha', 'op-london', 'op-losangeles', 'registry-a', 'frame-b']
  const foreign = opKeys.flatMap(k => Array.from({ length: 131 }, (_, i) => ({ did: `did:${k}:${i}`, key: k })))

  const plan = () => buildStarPlan({
    localKey: 'frame-c', cap: 240, localOrigin: ORIGIN, directory: DIR, localDids, foreign,
  })

  it('THE DEFECT: without foreign candidates only one registry is covered', () => {
    const before = buildStarPlan({ localKey: 'frame-c', cap: 240, localOrigin: ORIGIN, directory: DIR, localDids })
    expect(before.registries).toBe(1)
  })

  it('every registry he owns agents on gets stars', () => {
    const p = plan()
    expect(p.chosen.length).toBe(240)
    expect(p.registries).toBe(7)            // frame-c + 6
    expect(p.unplaced).toBe(0)
  })

  it('each foreign star carries a home the stage can resolve', () => {
    const p = plan()
    const berlin = p.homes.filter(h => (h.names || []).includes('op-berlin'))
    expect(berlin.length).toBeGreaterThan(0)
    for (const h of berlin) { expect(h.local).toBeFalsy(); expect(h.names).toContain('op-berlin') }
  })

  it('local stars are marked local and never carry a foreign name', () => {
    const p = plan()
    const locals = p.homes.filter(h => h.local)
    expect(locals.length).toBeGreaterThan(0)
    for (const h of locals) expect(h.names).toBeUndefined()
  })

  it('homes line up with chosen, one for one, in order', () => {
    const p = plan()
    expect(p.homes.map(h => h.did)).toEqual(p.chosen)
  })
})

describe('buildStarPlan — honesty rules', () => {
  it('a foreign DID with no key is counted unplaced, NOT drawn as local', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 10, localOrigin: ORIGIN, directory: DIR,
      localDids: ['did:local:1'],
      foreign: [{ did: 'did:orphan:1', key: null }],
    })
    expect(p.unplaced).toBe(1)
    const orphan = p.homes.find(h => h.did === 'did:orphan:1')
    expect(orphan).toBeDefined()
    expect(orphan!.local).toBeFalsy()
    expect(orphan!.names).toBeUndefined()      // no name => the stage draws nothing
  })

  it('a key missing from the directory is unplaced, not invented', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 10, localOrigin: ORIGIN, directory: DIR,
      foreign: [{ did: 'did:ghost:1', key: 'op-atlantis' }],
    })
    expect(p.unplaced).toBe(1)
    expect(p.homes[0].names).toBeUndefined()
  })

  it('a credential on an unnameable host never steals a local slot', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 4, localOrigin: ORIGIN, directory: DIR,
      credentialed: [{ did: 'did:weird:1', registryUrl: 'https://elsewhere.example/' }],
      localDids: ['l1', 'l2', 'l3', 'l4', 'l5', 'l6'],
    })
    // Its own bucket: it is drawn nowhere, but it also did not displace a
    // local agent that WOULD have been drawn.
    const weird = p.homes.find(h => h.did === 'did:weird:1')
    expect(weird?.local).toBeFalsy()
    expect(p.unplaced).toBe(1)
  })

  it('a same-origin credential is local even with a registry_url set', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 4, localOrigin: ORIGIN, directory: DIR,
      credentialed: [{ did: 'd1', registryUrl: `${ORIGIN}/api/v1` }],
    })
    expect(p.homes[0].local).toBe(true)
    expect(p.unplaced).toBe(0)
  })

  it('credentialed agents win their registry slots, and keep their names', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 3, localOrigin: ORIGIN, directory: DIR,
      credentialed: [{ did: 'hagrid', name: 'Hypervisor Hagrid', registryUrl: 'https://registry-a.theprotocol.cloud' }],
      localDids: ['l1', 'l2', 'l3', 'l4'],
    })
    expect(p.chosen).toContain('hagrid')
    expect(p.homes.find(h => h.did === 'hagrid')?.name).toBe('Hypervisor Hagrid')
    expect(p.homes.find(h => h.did === 'hagrid')?.names).toContain('registry-a')
  })

  it('the same DID from two sources takes exactly one slot', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 10, localOrigin: ORIGIN, directory: DIR,
      localDids: ['dup'], foreign: [{ did: 'dup', key: 'op-berlin' }],
    })
    expect(p.chosen).toEqual(['dup'])
    expect(p.homes.length).toBe(1)
  })

  it('an empty account plans nothing and claims nothing', () => {
    const p = buildStarPlan({ localKey: 'frame-c', cap: 240, localOrigin: ORIGIN, directory: DIR })
    expect(p.chosen).toEqual([])
    expect(p.registries).toBe(0)
    expect(p.unplaced).toBe(0)
  })

  it('no directory yet: local still draws, foreign waits rather than lying', () => {
    // The directory arrives with the topology boot step; the computed re-runs.
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 10, localOrigin: ORIGIN, directory: [],
      localDids: ['l1', 'l2'], foreign: [{ did: 'f1', key: 'op-berlin' }],
    })
    expect(p.homes.filter(h => h.local).length).toBe(2)
    expect(p.unplaced).toBe(1)
    expect(p.homes.find(h => h.did === 'f1')?.names).toBeUndefined()
  })
})

describe('buildStarPlan — the relay speaks letters', () => {
  it("a home recorded as 'A' still resolves to Registry-A", () => {
    // /admin/peer/targets returns key 'A' with canonical 'registry-a'. After a
    // reload, sessions come back under the LETTER. Before this, every
    // Registry-A agent came home unnameable and was silently not drawn.
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 10, localOrigin: ORIGIN, directory: DIR,
      foreign: [{ did: 'a1', key: 'registry-a' }],
    })
    expect(p.unplaced).toBe(0)
    expect(p.homes[0].names).toContain('Registry-A')
  })

  it('matches a home by any alias the directory declares', () => {
    const p = buildStarPlan({
      localKey: 'frame-c', cap: 10, localOrigin: ORIGIN, directory: DIR,
      foreign: [{ did: 'b1', key: 'Frame-B' }],     // the display name, not the key
    })
    expect(p.unplaced).toBe(0)
    expect(p.homes[0].names).toContain('frame-b')
  })
})

/*
 * §STARCAP (Commander 2026-08-21) — "cap 1000 might be better option ... already
 * 40 sim agents are 4x 16 registries basically".
 *
 * Raising the cap alone does NOT deliver that: the local registry holds
 * thousands while each operator holds ~40, so proportional sharing sends almost
 * the whole surplus home and operators barely move. The FLOOR is what reaches
 * them. These tests fail on the old floor of 8.
 */
describe('buildStarPlan — a bigger cap has to reach the operators', () => {
  const many = (prefix: string, n: number) =>
    Array.from({ length: n }, (_, i) => `did:theprotocol:${prefix}-${i}`)

  const plan = (cap: number) => buildStarPlan({
    localKey: 'frame-c', cap, localOrigin: ORIGIN, directory: DIR,
    localDids: many('local', 4448),
    foreign: [
      ...many('berlin', 40).map(did => ({ did, key: 'op-berlin' })),
      ...many('doha', 40).map(did => ({ did, key: 'op-doha' })),
      ...many('london', 40).map(did => ({ did, key: 'op-london' })),
    ],
  })

  // A home carries its registry in `names[0]` — the same field the plan's own
  // `covered` set counts. There is no `key` on a StarHome.
  const perRegistry = (p: ReturnType<typeof plan>, name: string) =>
    p.homes.filter(h => !h.local && h.names?.[0] === name).length
  const localCount = (p: ReturnType<typeof plan>) => p.homes.filter(h => h.local).length

  it('draws the whole 40-agent fleet an operator actually holds', () => {
    const p = plan(1000)
    expect(perRegistry(p, 'op-berlin')).toBe(40)
    expect(perRegistry(p, 'op-doha')).toBe(40)
    expect(perRegistry(p, 'op-london')).toBe(40)
  })

  it('still spends the surplus at home rather than idling it', () => {
    const p = plan(1000)
    expect(p.chosen.length).toBe(1000)
    expect(localCount(p)).toBeGreaterThan(700)
  })

  it('the floor self-limits: a small cap cannot be over-committed', () => {
    const p = plan(80)
    expect(p.chosen.length).toBeLessThanOrEqual(80)
    // 4 groups, floor clamped to 80/4 = 20, so no operator can claim 40.
    expect(perRegistry(p, 'op-berlin')).toBeLessThanOrEqual(20)
  })

  it('every registry the account owns agents on is represented', () => {
    expect(plan(1000).registries).toBe(4)
  })
})
