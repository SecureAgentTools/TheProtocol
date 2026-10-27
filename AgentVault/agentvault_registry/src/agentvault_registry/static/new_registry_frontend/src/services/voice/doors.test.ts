// §VOICEHIRE — doors unit coverage (file born in this batch; the grammar's
// tests live beside it in intentGrammar.test.ts).
import { describe, it, expect } from 'vitest'
import { doorFor } from './doors'

/* §VOICEHIRE — the three doors: fill-only targets on EXISTING surfaces. */
describe('voice-hire doors', () => {
  it('market-find opens the Discover lane; a cap opens the paid lane', () => {
    expect(doorFor({ kind: 'market-find', query: 'translation', maxPrice: 2, currency: 'AVT', mcpTool: 'discoverAgents' }))
      .toEqual({ path: '/pocket/agents', query: { lane: 'discover', dq: 'translation', pricing: 'paid' } })
    expect(doorFor({ kind: 'market-find', query: 'research', mcpTool: 'discoverAgents' }))
      .toEqual({ path: '/pocket/agents', query: { lane: 'discover', dq: 'research' } })
  })
  it('offer opens the thread door with the proposal deep-link', () => {
    expect(doorFor({ kind: 'offer', toQuery: 'sybil', to: { did: 'did:x:s', name: 'Sybil' }, amount: 5, currency: 'AVT', title: 'logo design' }))
      .toEqual({ path: '/pocket/ourchat', query: { propose: '1', to: 'did:x:s', ptitle: 'logo design', ptotal: '5', pccy: 'AVT' } })
    expect(doorFor({ kind: 'offer', toQuery: 'stranger' }))
      .toEqual({ path: '/pocket/ourchat', query: { propose: '1', q: 'stranger' } })
  })
  it('hire-firm opens the Discovery firms lane at the name', () => {
    expect(doorFor({ kind: 'hire-firm', name: 'meridian' }))
      .toEqual({ path: '/discover', query: { firm: 'meridian' } })
  })
})
