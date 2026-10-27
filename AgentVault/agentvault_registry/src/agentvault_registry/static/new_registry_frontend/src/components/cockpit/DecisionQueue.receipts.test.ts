/**
 * §FESUITE (V0577): the decision card's "Changed since your last decision" is the catch for an agent re-asking on
 * different terms after you decided, and it (with the streak) is computed from your earlier decisions
 * (liabilityApi.receipts). A failed receipts read left them empty, so the catch could not fire and nothing on the card
 * said so: a re-ask on new terms read exactly like an unchanged one. The card now says the earlier decisions could not be
 * read and offers the read again; once they answer, the change shows as it always did.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ receipts: vi.fn() }))
const NOW = Date.now()
const iso = (ms: number) => new Date(NOW + ms).toISOString()
const ASK = {
  id: 'ch-2', mandate_id: 'm-1', action_type: 'treasury.remit', action_ref: null,
  facts: { amount: '12', currency: 'ECU', counterparty: 'Meridian Ledger Works' },
  challenge_hash: 'ab', created_at: iso(-10_000), expires_at: iso(600_000), facts_digest: 'digest-now', posture: 'standard',
}
const EARLIER = {
  evidence_id: 1, mandate_id: 'm-1', event_type: 'challenge_approved', at: iso(-60_000), action_ref: null, payload: {},
  challenge: {
    id: 'ch-1', action_type: 'treasury.remit', facts: { amount: '10', currency: 'ECU', counterparty: 'Meridian Ledger Works' },
    status: 'approved', method: 'webauthn_uv', device_id: 1, created_at: iso(-70_000), expires_at: iso(-10_000),
    resolved_at: iso(-60_000), delivery_acked_at: null, facts_digest: 'digest-before',
  },
}

vi.mock('@/services/api/liability', () => ({
  liabilityApi: {
    pendingChallenges: vi.fn(async () => ({ challenges: [ASK] })),
    pendingIntents: vi.fn(async () => ({ items: [], available: true })),
    receipts: h.receipts,
    ackChallenge: vi.fn(async () => ({})),
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

async function queue() {
  const w = mount(DecisionQueue, { props: { variant: 'desk' } })
  await flushPromises()
  return w
}

describe('the decision card when the earlier decisions cannot be read', () => {
  beforeEach(() => { h.receipts.mockReset() })

  it('says the comparison could not be made, and shows the change once the read answers', async () => {
    h.receipts.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await queue()
    expect(w.find('[data-testid="dq-diff"]').exists()).toBe(false)
    const notice = w.find('[data-testid="dq-receipts-unread"]')
    expect(notice.exists(), 'the card said nothing about earlier decisions it could not read').toBe(true)
    expect(notice.text()).toContain('cannot be checked')

    h.receipts.mockResolvedValue({ receipts: [EARLIER], count: 1 })
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="dq-receipts-unread"]').exists()).toBe(false)
    expect(w.find('[data-testid="dq-diff"]').text()).toContain('Changed since your last decision')
  })

  it('with the earlier decisions read and nothing changed, the card says neither', async () => {
    h.receipts.mockResolvedValue({ receipts: [], count: 0 })
    const w = await queue()
    expect(w.find('[data-testid="dq-diff"]').exists()).toBe(false)
    expect(w.find('[data-testid="dq-receipts-unread"]').exists()).toBe(false)
  })
})
