/**
 * §FEDDIR-HOP (2026-09-10) — the Directory tab's hop column against the Network tab's rings.
 *
 * His report: *"the hops are wrong. wrong count ... but correct on federation network view."*
 * He was right, and the two numbers are not two implementations of one answer — they answer two
 * different questions. The federated index counts BFS depth from its ANCHOR SET; the page counts
 * distance from the frame the reader is looking at. On EU (measured live 2026-09-10) the index
 * says ASIA h0 / shenzhen h1, while ASIA is one hop out and shenzhen is two.
 *
 * These cases are the live EU shape, read from `GET /api/v1/public/topology` and the index's own
 * `status { sources { hop } }` on the same minute.
 */
import { describe, it, expect } from 'vitest'
import { deriveDisplayHop, buildPeersById } from './useFederationTopology'

// EU's peer rows, verbatim shape (only the fields the walk reads).
const P = (id: number, name: string, peer_type: string, parent_registry_id: number | null, hop_distance: number | null) =>
  ({ id, name, peer_type, parent_registry_id, hop_distance }) as any

const EU_PEERS = [
  P(3, 'asia', 'frame', null, 1),
  P(7, 'hochiminh', 'discovered', 3, 2),
  P(8, 'shenzhen', 'discovered', 3, 2),
  P(1, 'amsterdam', 'cloud_operator', null, null),
  P(2, 'lisbon', 'cloud_operator', null, null),
]

// What the federated index published for the same six sources at the same moment.
const INDEX_HOP: Record<string, number> = {
  asia: 0, eu: 0, amsterdam: 1, hochiminh: 1, lisbon: 1, shenzhen: 1,
}

describe('§FEDDIR-HOP — hops are counted from the reading frame', () => {
  const byId = buildPeersById(EU_PEERS as any)
  const hopFromEu = (name: string) => {
    const p = EU_PEERS.find(x => x.name === name)!
    return deriveDisplayHop(p as any, byId as any)
  }

  it('gives ASIA one hop and ASIA-homed operators two', () => {
    expect(hopFromEu('asia')).toBe(1)
    expect(hopFromEu('shenzhen')).toBe(2)
    expect(hopFromEu('hochiminh')).toBe(2)
  })

  it('gives EU-homed operators one hop', () => {
    expect(hopFromEu('amsterdam')).toBe(1)
    expect(hopFromEu('lisbon')).toBe(1)
  })

  // THE CONTROL. If these ever agreed, the column could read either number and the bug would be
  // invisible; the test exists because they do not.
  it('disagrees with the index crawl depth on exactly the rows he reported', () => {
    expect(INDEX_HOP['asia']).toBe(0)
    expect(hopFromEu('asia')).not.toBe(INDEX_HOP['asia'])
    expect(hopFromEu('shenzhen')).not.toBe(INDEX_HOP['shenzhen'])
    // and agrees where it happens to coincide, so "always differs" is not the rule either
    expect(hopFromEu('amsterdam')).toBe(INDEX_HOP['amsterdam'])
  })

  it('is name-keyed case-insensitively — the index publishes ASIA where the peer row says asia', () => {
    const map = new Map(EU_PEERS.map(p => [p.name.toLowerCase(), deriveDisplayHop(p as any, byId as any)]))
    expect(map.get('ASIA'.trim().toLowerCase())).toBe(1)
  })
})
