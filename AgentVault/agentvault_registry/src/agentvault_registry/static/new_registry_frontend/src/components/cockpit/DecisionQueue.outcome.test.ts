/**
 * §FESUITE (2026-10-10, lifecycle 90): what became of an answer stays on screen after its card leaves. The outcome
 * ("Approved.", "Denied.") lived inside the card, and the queue re-reads right after an answer, so the answered card left
 * at once and the outcome with it: on a phone the person saw the card vanish and "Nothing is waiting on you.", never what
 * became of their answer. It now stands above the queue and names what was answered. And a fingerprint the phone did
 * not get (declined, cancelled, timed out: NotAllowedError) sent nothing and showed the browser's own sentence: it says
 * so in words, nothing is sent, and the card stays to be answered. The receipts test's harness, the phone's mount.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'

const NOW = Date.now()
const iso = (ms: number) => new Date(NOW + ms).toISOString()
const ASK = {
  id: 'ch-9', mandate_id: 'm-1', action_type: 'support_reply', action_ref: 'fes-1',
  facts: { note: 'the console suite asks' }, challenge_hash: 'ab', created_at: iso(-10_000), expires_at: iso(600_000),
  facts_digest: 'd1', posture: 'standard',
}
const h = vi.hoisted(() => ({ pending: vi.fn(), approve: vi.fn(), deny: vi.fn() }))
vi.mock('@/services/api/liability', () => ({
  liabilityApi: {
    pendingChallenges: h.pending,
    pendingIntents: vi.fn(async () => ({ items: [], available: true })),
    receipts: vi.fn(async () => ({ receipts: [], count: 0 })),
    ackChallenge: vi.fn(async () => ({})),
    approveChallenge: h.approve,
    denyChallenge: h.deny,
  },
}))
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: () => {} }))
vi.mock('@/composables/useConsentPosture', () => ({
  useConsentPosture: () => ({
    posture: ref(null), readFloorMs: computed(() => 0), deskAuthenticatorAllowed: computed(() => false),
    methodFloor: computed(() => 'webauthn_uv'), streakBadgeAt: computed(() => 3), load: vi.fn(async () => {}),
  }),
}))
vi.mock('@/composables/useDeviceSigner', () => ({
  useDeviceSigner: () => ({ supported: false, platformAvailable: ref(false), register: vi.fn(), sign: vi.fn() }),
}))

import DecisionQueue from './DecisionQueue.vue'

const assertion = { device_id: 4, credential_id: 'c', authenticator_data: 'a', client_data_json: 'j', signature: 's' }

async function phoneQueue(signWith: (hash: string) => Promise<any>) {
  const w = mount(DecisionQueue, { props: { variant: 'phone', signWith } })
  await flushPromises()
  // the read floor counts from the moment the card was presented: one tick of the queue's clock passes it (floor 0)
  await new Promise((r) => setTimeout(r, 1100))
  await flushPromises()
  return w
}

describe('the outcome of an answer on the phone', () => {
  beforeEach(() => {
    let answered = false
    h.pending.mockReset().mockImplementation(async () => ({ challenges: answered ? [] : [ASK] }))
    h.approve.mockReset().mockImplementation(async () => { answered = true; return { status: 'approved' } })
    h.deny.mockReset().mockImplementation(async () => { answered = true; return { status: 'denied' } })
  })

  it('approved: the card leaves and the outcome stays, naming what was approved', async () => {
    const w = await phoneQueue(vi.fn(async () => assertion))
    await w.find('[data-testid="dq-approve"]').trigger('click')
    await flushPromises()
    expect(h.approve).toHaveBeenCalledWith('ch-9', assertion)
    expect(w.find('[data-testid="dq-presentable"]').exists(), 'the answered card left').toBe(false)
    expect(w.find('[data-testid="dq-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="dq-msg"]').text()).toBe('Approved: support_reply.')
  })

  it('denied: the same, naming what was denied', async () => {
    const w = await phoneQueue(vi.fn(async () => assertion))
    await w.find('[data-testid="dq-deny"]').trigger('click')
    await w.find('[data-testid="dq-deny-menu"] button').trigger('click')
    await flushPromises()
    expect(h.deny).toHaveBeenCalled()
    expect(w.find('[data-testid="dq-presentable"]').exists()).toBe(false)
    expect(w.find('[data-testid="dq-msg"]').text()).toBe('Denied: support_reply.')
  })

  it('a fingerprint not given: nothing sent, said in words, the card stays', async () => {
    const sign = vi.fn(async () => { throw new DOMException('The operation either timed out or was not allowed. See: https://www.w3.org/TR/webauthn-2/#sec-assertion-privacy.', 'NotAllowedError') })
    const w = await phoneQueue(sign)
    await w.find('[data-testid="dq-approve"]').trigger('click')
    await flushPromises()
    expect(h.approve).not.toHaveBeenCalled()
    const said = w.find('[data-testid="dq-msg"]').text()
    expect(said).toMatch(/fingerprint was not confirmed, so nothing was sent/i)
    expect(said).not.toMatch(/operation|w3\.org/i)
    expect(w.find('[data-testid="dq-presentable"]').exists(), 'the card stays to be answered').toBe(true)
  })
})
