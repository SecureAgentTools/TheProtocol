// V0666 the Flare view reworked: who wears what, as one pure model. The developer and each agent are bearers; a bought ring or corner is worn by the one agent that bears the slot
// (and by the developer's own avatar); an earned ring or badge is ONE copy worn by one bearer at a time; a title is the developer's.
import { describe, expect, it } from 'vitest'
import { bearersOf, filterBearers, holderOfEarned, ME, wornBy, wornCount, type AgentFlareRow, type DeveloperFlare } from './flareBearers'

const dev = (over: Partial<DeveloperFlare> = {}): DeveloperFlare => ({ name: 'Ada', flare_encirclement_variant: null, flare_corner_variant: null, selected_corner_flare: null, selected_encirclement_flare: null, title: null, ...over })
const ag = (did: string, over: Partial<AgentFlareRow> = {}): AgentFlareRow => ({ did, name: did.toUpperCase(), bears_corner_flare: false, bears_encirclement_flare: false, flare_encirclement_variant: null, flare_corner_variant: null, ...over })

describe('the bearers', () => {
  it('lists the developer first, then the agents that wear something, then the rest by name', () => {
    const list = bearersOf(dev({ selected_encirclement_flare: 'shadow_chancellor' }), [ag('zed'), ag('bob', { flare_corner_variant: 'initiate' }), ag('amy'), ag('cat', { bears_encirclement_flare: true })])
    expect(list.map((b) => b.key)).toEqual([ME, 'bob', 'cat', 'amy', 'zed'])
    expect(list[0]).toMatchObject({ kind: 'developer', did: null, name: 'Ada' })
    expect(list[1]).toMatchObject({ kind: 'agent', did: 'bob', name: 'BOB' })
  })
  it('names an agent without a name by its did tail, never blank', () => {
    expect(bearersOf(dev(), [ag('did:theprotocol:eu:0123456789abcdef', { name: '' })])[1].name).toBe('…89abcdef')
  })
  it('finds a bearer by name or did, and the developer stays in every answer', () => {
    const list = bearersOf(dev(), [ag('amy'), ag('bob')])
    expect(filterBearers(list, 'bo').map((b) => b.key)).toEqual([ME, 'bob'])
    expect(filterBearers(list, '  ').map((b) => b.key)).toEqual([ME, 'amy', 'bob'])
    expect(filterBearers(list, 'zzz').map((b) => b.key)).toEqual([ME])
  })
})

describe('what a bearer wears', () => {
  it("shows the developer's earned ring and badge and the title", () => {
    const w = wornBy(bearersOf(dev(), [])[0], dev({ flare_encirclement_variant: 'ember', flare_corner_variant: 'initiate', title: 'patchwright' }), [])
    expect(w).toEqual({ ring: { key: 'ember', source: 'earned' }, badge: { key: 'initiate', source: 'earned' }, title: 'patchwright' })
  })
  it("shows the developer's bought ring and corner when no earned one is worn", () => {
    const w = wornBy(bearersOf(dev(), [])[0], dev({ selected_encirclement_flare: 'shadow_chancellor', selected_corner_flare: 'founder' }), [])
    expect(w.ring).toEqual({ key: 'shadow_chancellor', source: 'bought' })
    expect(w.badge).toEqual({ key: 'founder', source: 'bought' })
  })
  it('an agent wears what it was given: the bought slot it bears, else the earned item on it', () => {
    const d = dev({ selected_encirclement_flare: 'shadow_chancellor', selected_corner_flare: 'founder', flare_encirclement_variant: 'ember' })
    const agents = [ag('a', { bears_encirclement_flare: true }), ag('b', { flare_corner_variant: 'lantern-key', flare_encirclement_variant: 'abyss' }), ag('c')]
    const list = bearersOf(d, agents)
    const by = (k: string) => wornBy(list.find((b) => b.key === k)!, d, agents)
    expect(by('a').ring).toEqual({ key: 'shadow_chancellor', source: 'bought' })
    expect(by('a').badge).toBeNull()                                            // it bears the ring, not the corner
    expect(by('b')).toEqual({ ring: { key: 'abyss', source: 'earned' }, badge: { key: 'lantern-key', source: 'earned' }, title: null })
    expect(wornCount(by('c'))).toBe(0)                                          // the developer's earned ring is not on every agent
  })
  it('an agent never wears a title', () => {
    const list = bearersOf(dev({ title: 'patchwright' }), [ag('a')])
    expect(wornBy(list[1], dev({ title: 'patchwright' }), [ag('a')]).title).toBeNull()
  })
  it('a bought variant name in an agent column is not an earned item', () => {
    const list = bearersOf(dev(), [ag('a', { flare_encirclement_variant: 'sauron' })])
    expect(wornBy(list[1], dev(), [ag('a', { flare_encirclement_variant: 'sauron' })]).ring).toBeNull()
  })
})

describe('who holds an earned copy', () => {
  it('names the one bearer that wears it, the developer or an agent, and nobody when it is free', () => {
    const agents = [ag('a', { flare_encirclement_variant: 'abyss', flare_corner_variant: 'quill' }), ag('b')]
    expect(holderOfEarned('encirclement', 'ember', dev({ flare_encirclement_variant: 'ember' }), agents)).toBe(ME)
    expect(holderOfEarned('encirclement', 'abyss', dev(), agents)).toBe('a')
    expect(holderOfEarned('corner', 'quill', dev(), agents)).toBe('a')
    expect(holderOfEarned('corner', 'initiate', dev(), agents)).toBeNull()
  })
})
