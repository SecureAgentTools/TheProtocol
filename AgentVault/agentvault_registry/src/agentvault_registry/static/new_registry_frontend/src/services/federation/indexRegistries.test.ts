/**
 * V0663, the Directory read path, step 3 (order gwo_0936844934f713153ede256c): the console's registry views read the
 * registries the federated index knows, through this registry (GET /public/directory/registries), which verified every
 * card itself. This module reads that answer into one shape the views draw: four states, never a broken index drawn as
 * "nobody is out there", and only a card this registry verified names a registry.
 * Red on 1fe82c44c: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { normaliseIndexRegistries, orderIndexRegistries } from './indexRegistries'

const verified = (name: string, relation: string, extra: Record<string, any> = {}) => ({
  name, trust_domain: `${name}.theprotocol.cloud`, tier: 'sovereign-mainframe', public_url: `https://${name}.example.org`,
  location: 'Brussels', currency: 'ECU', card_etag: 'e1', verified: true, reason: 'ok', relation, address_agrees: true,
  index: { name, public_url: `https://${name}.example.org`, trust_domain: null, reachable: true, verified: true,
           card_epoch: 'e1', last_sync_at: 1 }, ...extra })
const unverified = (indexName: string, reason: string) => ({
  name: null, trust_domain: null, tier: null, public_url: null, location: null, currency: null, card_etag: null,
  verified: false, reason, relation: 'unverified', address_agrees: null,
  index: { name: indexName, public_url: `https://${indexName}.example.org`, trust_domain: null, reachable: false,
           verified: false, card_epoch: null, last_sync_at: null } })

describe('the index registries answer', () => {
  it('reads a whole answer: registries, counts, the cards flag and the cut', () => {
    const a = normaliseIndexRegistries(200, { configured: true, index_serves_cards: true, truncated: false,
      counts: { index: 2, read: 2, verified: 1, unverified: 1 },
      registries: [verified('eu', 'peer'), unverified('ghost', 'signature invalid')] })
    expect(a.state).toBe('ok')
    expect(a.registries.map((r) => [r.name, r.verified, r.relation])).toEqual([['eu', true, 'peer'], [null, false, 'unverified']])
    expect(a.registries[1].indexName).toBe('ghost')
    expect(a.counts).toEqual({ index: 2, read: 2, verified: 1, unverified: 1 })
    expect(a.servesCards).toBe(true)
    expect(a.truncated).toBe(false)
  })

  it('a broken index is an error with its reason, never an empty list', () => {
    const a = normaliseIndexRegistries(502, { configured: true, error: 'the federated index is unreachable' })
    expect(a.state).toBe('error')
    expect(a.error).toBe('the federated index is unreachable')
    expect(a.registries).toEqual([])
  })

  it('no index on this registry is its own state', () => {
    expect(normaliseIndexRegistries(200, { configured: false, registries: [] }).state).toBe('unconfigured')
  })

  it('an answer that is not this shape is an error, not an empty index', () => {
    for (const [status, body] of [[200, null], [200, { configured: true }], [500, 'oops'], [200, { configured: true, registries: 'x' }]] as const) {
      const a = normaliseIndexRegistries(status, body)
      expect(a.state, JSON.stringify(body)).toBe('error')
    }
  })

  it('an unverified row never carries a name, a domain or a relation of its own', () => {
    const forged = { ...unverified('eu', 'signature invalid'), name: 'eu', trust_domain: 'eu.theprotocol.cloud', relation: 'peer' }
    const r = normaliseIndexRegistries(200, { configured: true, registries: [forged], counts: {} }).registries[0]
    expect([r.name, r.trustDomain, r.relation]).toEqual([null, null, 'unverified'])
  })

  it('orders this registry, its peers, known, candidates, then what did not verify; by name within each', () => {
    const a = normaliseIndexRegistries(200, { configured: true, counts: {}, registries: [
      unverified('zz', 'unsigned'), verified('lisbon', 'candidate'), verified('asia', 'known'),
      verified('eu', 'peer'), verified('here', 'self'), verified('amsterdam', 'candidate')] })
    expect(orderIndexRegistries(a.registries).map((r) => r.name ?? r.indexName))
      .toEqual(['here', 'eu', 'asia', 'amsterdam', 'lisbon', 'zz'])
  })
})
