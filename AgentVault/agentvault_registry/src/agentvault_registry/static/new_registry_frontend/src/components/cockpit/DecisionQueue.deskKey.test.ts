/**
 * §FESUITE (V0594): the desk's own signing key and a fingerprint not given. The desk forgot its enrolled key on a
 * NotAllowedError, which is also what a mere cancel of the prompt raises (named at V0592: one cancelled prompt asked for
 * a new enrolment next time), while a refusal by the registry never forgot it (the test read the HTTP client's message,
 * which never names a credential). Now a cancel keeps the key and offers enrolling again beside Approve; the registry's
 * 401 on the desk's own signature forgets it and says so. The outcome test's harness, the desk's mount.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'

const NOW = Date.now()
const iso = (ms: number) => new Date(NOW + ms).toISOString()
const ASK = {
  id: 'ch-7', mandate_id: 'm-1', action_type: 'support_reply', action_ref: 'fes-2',
  facts: { note: 'the console suite asks' }, challenge_hash: 'ab', created_at: iso(-10_000), expires_at: iso(600_000),
  facts_digest: 'd1', posture: 'standard',
}
const KEY = 'ckd_desk_signer'
const h = vi.hoisted(() => ({ pending: vi.fn(), approve: vi.fn(), sign: vi.fn() }))
vi.mock('@/services/api/liability', () => ({
  liabilityApi: {
    pendingChallenges: h.pending,
    pendingIntents: vi.fn(async () => ({ items: [], available: true })),
    receipts: vi.fn(async () => ({ receipts: [], count: 0 })),
    ackChallenge: vi.fn(async () => ({})),
    approveChallenge: h.approve,
    denyChallenge: vi.fn(async () => ({})),
  },
}))
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: () => {} }))
vi.mock('@/composables/useConsentPosture', () => ({
  useConsentPosture: () => ({
    posture: ref(null), readFloorMs: computed(() => 0), deskAuthenticatorAllowed: computed(() => true),
    methodFloor: computed(() => 'webauthn_uv'), streakBadgeAt: computed(() => 3), load: vi.fn(async () => {}),
  }),
}))
vi.mock('@/composables/useDeviceSigner', () => ({
  useDeviceSigner: () => ({ supported: true, platformAvailable: vi.fn(async () => true), register: vi.fn(), sign: h.sign }),
}))

import DecisionQueue from './DecisionQueue.vue'

const assertion = { authenticator_data: 'a', client_data_json: 'j', signature: 's', credential_id: 'cred-1' }
const refused401 = () => Object.assign(new Error('Request failed with status code 401'), {
  name: 'AxiosError', response: { status: 401, data: { detail: 'Presence check failed' } },
})

async function deskQueue() {
  const w = mount(DecisionQueue, { props: { variant: 'desk' }, global: { stubs: { Icon: true } } })
  await flushPromises()
  // the read floor counts from the moment the card was presented: one tick of the queue's clock passes it (floor 0)
  await new Promise((r) => setTimeout(r, 1100))
  await flushPromises()
  return w
}
const stored = () => localStorage.getItem(KEY)

describe("the desk's signing key and a fingerprint not given", () => {
  beforeEach(() => {
    localStorage.setItem(KEY, JSON.stringify({ device_id: 4, credential_id: 'cred-1' }))
    h.pending.mockReset().mockResolvedValue({ challenges: [ASK] })
    h.approve.mockReset()
    h.sign.mockReset()
  })

  it('a cancelled prompt keeps the key and offers enrolling again, nothing sent', async () => {
    h.sign.mockRejectedValue(new DOMException('The operation either timed out or was not allowed.', 'NotAllowedError'))
    const w = await deskQueue()
    expect(w.find('[data-testid="dq-enrol"]').exists(), 'an enrolled desk offers no enrolment before an answer').toBe(false)
    await w.find('[data-testid="dq-approve"]').trigger('click')
    await flushPromises()
    expect(h.sign).toHaveBeenCalledWith('ab', 'cred-1')
    expect(h.approve).not.toHaveBeenCalled()
    expect(stored(), 'one cancelled prompt threw the enrolled key away').not.toBeNull()
    expect(w.find('[data-testid="dq-msg"]').text()).toMatch(/fingerprint was not confirmed, so nothing was sent/i)
    expect(w.find('[data-testid="dq-enrol"]').exists(), 'enrolling again is offered, the person\'s call').toBe(true)
  })

  it("the registry's refusal of the desk's signature forgets the key and says so", async () => {
    h.sign.mockResolvedValue(assertion)
    h.approve.mockRejectedValue(refused401())
    const w = await deskQueue()
    await w.find('[data-testid="dq-approve"]').trigger('click')
    await flushPromises()
    expect(h.approve).toHaveBeenCalledWith('ch-7', { device_id: 4, ...assertion })
    expect(stored(), 'a key the registry refused stayed, to fail again').toBeNull()
    expect(w.find('[data-testid="dq-msg"]').text()).toMatch(/signing key was not accepted, so nothing was approved/i)
    expect(w.find('[data-testid="dq-enrol"]').exists()).toBe(true)
  })

  it('an accepted signature keeps the key and offers no enrolment', async () => {
    h.sign.mockResolvedValue(assertion)
    h.approve.mockResolvedValue({ status: 'approved' })
    const w = await deskQueue()
    await w.find('[data-testid="dq-approve"]').trigger('click')
    await flushPromises()
    expect(h.approve).toHaveBeenCalledWith('ch-7', { device_id: 4, ...assertion })
    expect(stored()).not.toBeNull()
    expect(w.find('[data-testid="dq-msg"]').text()).toBe('Approved: support_reply.')
  })
})
