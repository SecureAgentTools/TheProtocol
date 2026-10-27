import { describe, it, expect, vi } from 'vitest'

vi.mock('./client', () => ({ apiClient: {} }))

import { MembershipApi } from './membership'

/** §MEMBERSHIP (2026-10-02, plan § 2.3) — the two membership reads, and a `me` that never hands a screen undefined. */
describe('MembershipApi', () => {
  it('reads the public stats from /membership/stats', async () => {
    const get = vi.fn().mockResolvedValue({ data: { mode: 'member', members: 3 } })
    const s = await new MembershipApi({ get } as any).stats()
    expect(get).toHaveBeenCalledWith('/membership/stats')
    expect(s.members).toBe(3)
  })

  it('me: a sparse body becomes a complete, not-a-member answer with today\'s defaults', async () => {
    const get = vi.fn().mockResolvedValue({ data: { mode: 'member', agents: [{ did: 'did:a', qualifies: false }] } })
    const m = await new MembershipApi({ get } as any).me()
    expect(get).toHaveBeenCalledWith('/membership/me')
    expect(m.is_member).toBe(false)
    expect(m.weight).toBe(0)
    expect(m.presence_mode).toBe('off')
    expect(m.next_step).toBe('post_bond')
    expect(m.next_step_text).toBeNull()
    expect(m.agents[0].reasons).toEqual([])
    // an older registry names no counts: its list is the whole population
    expect([m.agents_total, m.agents_qualifying, m.agents_shown]).toEqual([1, 0, 1])
  })

  it('control: a full answer passes through unchanged', async () => {
    const full = {
      mode: 'member', is_member: true, member_since: '2026-10-07T00:00:00+00:00', weight: 1.2, points: 120,
      tenure_days: 73, tenure_full_days: 365, min_bond_age_days: 30, requires_matured_bond: false,
      presence_mode: 'conditional', agents: [], agents_total: 2907, agents_qualifying: 3, agents_shown: 0,
      missing: [], next_step: 'none', next_step_at: null, next_step_text: null,
    }
    const m = await new MembershipApi({ get: vi.fn().mockResolvedValue({ data: full }) } as any).me()
    expect(m).toEqual(full)
  })

  it('me keeps the server\'s sentence for the step (the console shows it only for a code it does not know)', async () => {
    const text = 'Your account is scheduled for deletion; cancel the deletion and you are a member again.'
    const get = vi.fn().mockResolvedValueOnce({ data: { next_step: 'cancel_deletion', next_step_text: text, missing: ['deletion_pending'] } })
      .mockResolvedValueOnce({ data: { next_step: 'post_bond', next_step_text: '' } })
    const api = new MembershipApi({ get } as any)
    const m = await api.me()
    expect([m.next_step, m.next_step_text, m.missing]).toEqual(['cancel_deletion', text, ['deletion_pending']])
    expect((await api.me()).next_step_text).toBeNull()                  // an empty sentence is no sentence
  })
})
