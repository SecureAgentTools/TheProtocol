import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * §MEMBERSHIP (2026-10-02) — the membership panel says, from the server's own answer, whether the developer is a member,
 * with which weight, and otherwise the one next step. It never names a reward, a yield or a share.
 */
const h = vi.hoisted(() => ({ me: vi.fn(), stats: vi.fn(), signedIn: true }))
vi.mock('@/services/api/membership', () => ({ membershipApi: { me: h.me, stats: h.stats } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: h.signedIn }) }))
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))

import MembershipPanel from './MembershipPanel.vue'
import { _resetMembership } from '@/composables/useMembership'

const STATS = { mode: 'member', members: 3, joined_30d: 2, left_30d: 1, network_points: 337, points_per_weight: 100,
  min_bond_age_days: 30, requires_matured_bond: false, tenure_full_days: 365, max_weight: 2, presence_mode: 'conditional', as_of: '' }
const BASE = { mode: 'member', member_since: null, weight: 0, points: 0, tenure_days: 0, tenure_full_days: 365,
  min_bond_age_days: 30, requires_matured_bond: false, presence_mode: 'conditional', agents: [], missing: [], next_step_at: null }

function mountPanel() {
  return mount(MembershipPanel, { global: { stubs: { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
}
const FORBIDDEN = /\b(yield|apy|dividends?|shares?|returns?|investments?|rewards?|interest)\b/i

beforeEach(() => {
  _resetMembership()
  h.signedIn = true
  h.me.mockReset(); h.stats.mockReset()
  h.stats.mockResolvedValue(STATS)
})

describe('the membership panel', () => {
  it('a member sees the date, the weight and the way to full weight', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: true, member_since: '2026-10-07T00:00:00+00:00', weight: 1.2, points: 120,
      tenure_days: 73, next_step: 'none' })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="membership-status"]').attributes('data-member')).toBe('1')
    expect(w.find('[data-testid="membership-weight"]').text()).toContain('1.20')
    expect(w.text()).toContain('Full weight in 292 days')
    expect(w.find('[data-testid="membership-next"]').exists()).toBe(false)
    expect(w.find('[data-testid="membership-registry"]').text()).toContain('3 members')
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it('a waiting developer sees when the bond counts, said once, and a link to the agent', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: false, next_step: 'wait_until', next_step_at: '2026-10-07T00:00:00+00:00',
      missing: ['bond_age'], agents: [{ did: 'did:theprotocol:a', name: 'Teller', bond_status: 'locked', funded_by: 'self',
        locked_at: '2026-09-07T00:00:00+00:00', qualifies_at: '2026-10-07T00:00:00+00:00', qualifies: false, reasons: ['bond_age'] }] })
    const w = mountPanel(); await flushPromises()
    const next = w.find('[data-testid="membership-next"]')
    expect(next.attributes('data-step')).toBe('wait_until')
    expect(next.text()).toContain('Oct 7, 2026')
    const bonds = w.find('[data-testid="membership-bonds"]').text()
    expect(bonds).toContain('counts from Oct 7, 2026')
    expect(bonds).not.toContain('bond too recent')
    expect(bonds).toContain('paid by the agent')
    expect(w.find('a').attributes('data-to')).toContain('did:theprotocol:a')
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it('a developer without a bond is told to post one, with the registry\'s waiting period', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: false, next_step: 'post_bond', missing: ['bond'] })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="membership-next"]').text()).toContain('30 days later')
    expect(w.find('[data-testid="membership-presence"]').text()).toContain('phone')
  })

  it('signed out: only the public numbers load, and no personal read is made', async () => {
    h.signedIn = false
    const w = mountPanel(); await flushPromises()
    expect(h.me).not.toHaveBeenCalled()
    expect(w.attributes('data-state')).toBe('signed-out')
    expect(w.find('[data-testid="membership-registry"]').exists()).toBe(true)
  })

  it('a developer with more bonds than the answer lists is told the list is a slice, in the reader\'s numbers', async () => {
    const bond = (n: number, qualifies: boolean) => ({ did: `did:theprotocol:b${n}`, name: `Bond ${n}`, bond_status: 'locked',
      funded_by: 'self', locked_at: '2026-09-01T00:00:00+00:00', qualifies_at: '2026-10-01T00:00:00+00:00', qualifies, reasons: [] })
    h.me.mockResolvedValue({ ...BASE, is_member: true, member_since: '2026-10-01T00:00:00+00:00', weight: 1, points: 100,
      next_step: 'none', agents: [bond(1, true), bond(2, false)], agents_total: 2907, agents_qualifying: 1, agents_shown: 2 })
    const w = mountPanel(); await flushPromises()
    const slice = w.find('[data-testid="membership-bonds-slice"]')
    expect(slice.text()).toContain('Showing 2 of 2,907 bonds')
    expect(slice.text()).toContain('bonds that count: 1')
    expect(w.findAll('[data-testid="membership-bonds"] .mbp-agent')).toHaveLength(2)
  })

  it('control: a list that is the whole population carries no slice line', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: false, next_step: 'wait_until', next_step_at: '2026-10-07T00:00:00+00:00',
      agents: [{ did: 'did:theprotocol:a', name: 'Teller', bond_status: 'locked', funded_by: 'self', locked_at: null,
        qualifies_at: '2026-10-07T00:00:00+00:00', qualifies: false, reasons: ['bond_age'] }], agents_total: 1, agents_qualifying: 0, agents_shown: 1 })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="membership-bonds"]').exists()).toBe(true)
    expect(w.find('[data-testid="membership-bonds-slice"]').exists()).toBe(false)
  })

  it('a developer whose deletion is pending is told to cancel it, with the way to the button that does', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: false, missing: ['deletion_pending'], next_step: 'cancel_deletion',
      next_step_text: 'Your account is scheduled for deletion; cancel the deletion and you are a member again.',
      agents: [{ did: 'did:a', name: 'Ada', bond_status: 'locked', funded_by: 'self', locked_at: '2026-09-01T00:00:00+00:00',
        qualifies_at: '2026-10-01T00:00:00+00:00', qualifies: true, reasons: [] }] })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="membership-status"]').attributes('data-member')).toBe('0')
    const next = w.find('[data-testid="membership-next"]')
    expect(next.attributes('data-step')).toBe('cancel_deletion')
    expect(next.text()).toContain('scheduled for deletion')
    expect(next.text()).toContain('original start date')
    expect(next.text()).not.toContain('Post the reputation bond')
    expect(JSON.parse(w.find('[data-testid="membership-cancel-deletion"]').attributes('data-to') || '{}'))
      .toEqual({ path: '/settings', query: { tab: 'security' } })
    expect(w.text()).not.toMatch(FORBIDDEN)
  })

  it('control: a step this console does not know yet shows the server\'s own sentence, never another step\'s advice', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: false, next_step: 'renew_identity', next_step_text: 'Renew your identity document first.' })
    const w = mountPanel(); await flushPromises()
    const next = w.find('[data-testid="membership-next"]')
    expect(next.text()).toContain('Renew your identity document first.')
    expect(next.text()).not.toContain('Post the reputation bond')
    expect(w.find('[data-testid="membership-cancel-deletion"]').exists()).toBe(false)
  })

  it('control: an unknown step with no sentence shows no step at all rather than a wrong one', async () => {
    h.me.mockResolvedValue({ ...BASE, is_member: false, next_step: 'renew_identity', next_step_text: null })
    const w = mountPanel(); await flushPromises()
    expect(w.find('[data-testid="membership-status"]').attributes('data-member')).toBe('0')
    expect(w.find('[data-testid="membership-next"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Post the reputation bond')
  })

  it('control: an unreadable membership says so instead of claiming "not a member"', async () => {
    h.me.mockRejectedValue(new Error('500'))
    const w = mountPanel(); await flushPromises()
    expect(w.attributes('data-state')).toBe('failed')
    expect(w.find('[data-testid="membership-status"]').exists()).toBe(false)
    expect(w.text()).toContain('could not be read')
  })
})
