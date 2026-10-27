import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * §MEMBERSHIP (2026-10-02) — the step-up dialog of a member's binding vote. It shows what is being confirmed, hands
 * the parent the proof once the phone approved (from the socket, or from the pending list when the socket is down),
 * takes a code where the member has one, and says when the phone declined or the time ran out.
 */
const h = vi.hoisted(() => ({ handlers: {} as Record<string, (d: any) => void>, pending: vi.fn() }))
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: (hs: Record<string, (d: any) => void>) => { Object.assign(h.handlers, hs) } }))
vi.mock('@/services/api/liability', () => ({ liabilityApi: { pendingChallenges: h.pending } }))

import StepUpConfirm from './StepUpConfirm.vue'
import { parseStepUp, type StepUpChallenge } from '@/services/membership/membership'

function challenge(over: Record<string, unknown> = {}) {
  return parseStepUp({ error: 'step_up_required', step_up: {
    reason: 'governance_vote', challenge_id: 'ch_7', challenge_hash: 'ab', ttl_seconds: 120,
    expires_at: new Date(Date.now() + 120_000).toISOString(), methods: ['device', 'totp'],
    facts: { action: 'Cast a governance vote', kind: 'governance.vote', proposal_id: 7, proposal_title: 'Lower the fee', choice: 'for', weight: '1.37' },
    ...over,
  } })!
}
function mountIt(props: { challenge: StepUpChallenge | null; busy?: boolean; error?: string; canSignHere?: boolean }) {
  return mount(StepUpConfirm, { props: { show: true, ...props }, global: { stubs: { teleport: true } } })
}

beforeEach(() => {
  for (const k of Object.keys(h.handlers)) delete h.handlers[k]
  h.pending.mockReset().mockResolvedValue({ challenges: [{ id: 'ch_7' }], count: 1 })
})
afterEach(() => { vi.useRealTimers() })

describe('the step-up dialog', () => {
  it('shows what is confirmed, in the phone\'s own lines', () => {
    const w = mountIt({ challenge: challenge() })
    const lines = w.find('[data-testid="stepup-lines"]').text()
    expect(lines).toContain('#7 Lower the fee')
    expect(lines).toContain('For')
    expect(lines).toContain('1.37')
  })

  it('hands over the proof once the phone approves THIS challenge, and only once', async () => {
    const w = mountIt({ challenge: challenge() })
    h.handlers['liability.resolved']({ challenge_id: 'ch_other', status: 'approved' })
    expect(w.emitted('approved')).toBeUndefined()
    h.handlers['liability.resolved']({ challenge_id: 'ch_7', status: 'approved' })
    h.handlers['liability.resolved']({ challenge_id: 'ch_7', status: 'approved' })
    expect(w.emitted('approved')).toEqual([['ch_7']])
  })

  it('says so when the phone declined, and hands over nothing', async () => {
    const w = mountIt({ challenge: challenge() })
    h.handlers['liability.resolved']({ challenge_id: 'ch_7', status: 'denied' })
    await flushPromises()
    expect(w.find('[data-testid="stepup-denied"]').exists()).toBe(true)
    expect(w.emitted('approved')).toBeUndefined()
  })

  it('takes a code where the member has one, and refuses one that is not a code', async () => {
    const w = mountIt({ challenge: challenge() })
    const input = w.find('[data-testid="stepup-code"]')
    await input.setValue('12ab')
    expect(w.find('[data-testid="stepup-code-submit"]').attributes('disabled')).toBeDefined()
    await input.setValue('123456')
    await w.find('form').trigger('submit')
    expect(w.emitted('code')).toEqual([['123456']])
  })

  it('a member with a device only gets no code field', () => {
    const w = mountIt({ challenge: challenge({ methods: ['device'] }) })
    expect(w.find('[data-testid="stepup-phone"]').exists()).toBe(true)
    expect(w.find('[data-testid="stepup-code"]').exists()).toBe(false)
  })

  it('without the socket: a challenge that left the pending list is handed over; control: one still pending is not', async () => {
    vi.useFakeTimers()
    const w = mountIt({ challenge: challenge() })
    await vi.advanceTimersByTimeAsync(5000)
    expect(w.emitted('approved')).toBeUndefined()           // still pending: nothing
    h.pending.mockResolvedValue({ challenges: [], count: 0 })
    await vi.advanceTimersByTimeAsync(5000)
    expect(w.emitted('approved')).toEqual([['ch_7']])
  })

  it('an expired challenge says so and offers no way to confirm it', () => {
    const w = mountIt({ challenge: challenge({ expires_at: new Date(Date.now() - 1000).toISOString() }) })
    expect(w.find('[data-testid="stepup-expired"]').exists()).toBe(true)
    expect(w.find('[data-testid="stepup-code"]').exists()).toBe(false)
  })
})
