/** §OURSTATE-1 — /audit's pure half: absence renders as a statement, never an
 *  insinuation (99.8% of agents have no history — §DISCREFINE base rate). */
import { describe, it, expect, vi } from 'vitest'

// trustCard → trackRecord → apiClient → errorHandler → router, which needs a
// DOM this node-env suite deliberately does not have. The pure functions under
// test never touch the client — cut the chain at the axios module.
vi.mock('@/services/api/client', () => ({ apiClient: {}, default: {} }))

import { trustLines } from './trustCard'

const tr = (over: any = {}) => ({
  jobs: 0, stars: null, five_star: 0, on_time_met: 0, on_time_of: 0,
  traveled: 0, cross_registry: 0, disputes: 0, open_disputes: 0, lost_disputes: 0,
  last_verified_at: null, ...over,
})

describe('trustLines', () => {
  it('absence is the honest line, alone', () => {
    const lines = trustLines({ track: null, reputation: null, reputationKnown: false })
    expect(lines).toEqual([{ kind: 'no-history' }])
  })

  it('zero jobs still says no-history even with a track object', () => {
    const lines = trustLines({ track: tr() as any, reputation: null, reputationKnown: false })
    expect(lines.some(l => l.kind === 'no-history')).toBe(true)
    expect(lines.some(l => l.kind === 'jobs')).toBe(false)
  })

  it('a proven agent shows jobs, stars, tier — and NOT the empty line', () => {
    const lines = trustLines({
      track: tr({ jobs: 12, stars: 4.8, five_star: 9, cross_registry: 3 }) as any,
      reputation: 0.72, reputationKnown: true,
    })
    const kinds = lines.map(l => l.kind)
    expect(kinds).toContain('jobs')
    expect(kinds).toContain('stars')
    expect(kinds).toContain('tier')
    expect(kinds).toContain('reputation')
    expect(kinds).not.toContain('no-history')
    // EARNED_TIERS stores lowercase slugs ('seasoned' at 10+ jobs); display
    // casing is the renderer's job.
    expect((lines.find(l => l.kind === 'tier') as any).tier).toBe('seasoned')
  })

  it('disputes render honestly, open and lost counted', () => {
    const lines = trustLines({
      track: tr({ jobs: 2, disputes: 3, open_disputes: 1, lost_disputes: 1 }) as any,
      reputation: null, reputationKnown: false,
    })
    expect(lines.find(l => l.kind === 'disputes')).toMatchObject({ open: 1, total: 3, lost: 1 })
  })
})
