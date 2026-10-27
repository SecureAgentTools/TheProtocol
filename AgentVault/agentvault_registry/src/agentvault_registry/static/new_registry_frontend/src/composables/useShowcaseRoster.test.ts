import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useShowcaseRoster, __showcaseRosterInternals as I } from './useShowcaseRoster'

function mockFetch(body: unknown, ok = true) {
  const f = vi.fn(async (_url: string, _init?: RequestInit) => ({ ok, json: async () => body }))
  ;(globalThis as any).fetch = f
  return f
}

beforeEach(() => { I.reset() })

describe('§FRESHFRAME useShowcaseRoster', () => {
  it('sandbox-a shape (disabled, a reason) → absent, ONE request for two callers', async () => {
    const f = mockFetch({ agents: [], count: 0, enabled: false, reason: 'The showcase is disabled on this deployment.' })
    const a = useShowcaseRoster(); const b = useShowcaseRoster()
    await a.load(); await b.load()
    expect(a.decision.value).toBe('absent')
    expect(b.decision.value).toBe('absent')
    expect(f.mock.calls.length).toBe(1)
    expect(String(f.mock.calls[0][0])).toContain('/api/v1/public/showcase/agents')
  })
  it('flagship shape (agents, no enabled key) → here', async () => {
    mockFetch({ agents: new Array(11).fill({ name: 'x' }), count: 11 })
    const r = useShowcaseRoster(); await r.load()
    expect(r.decision.value).toBe('here')
  })
  it('a failed read stays unknown (nothing is rendered, nothing is claimed)', async () => {
    mockFetch(null, false)
    const r = useShowcaseRoster(); await r.load()
    expect(r.decision.value).toBe('unknown')
  })
})
