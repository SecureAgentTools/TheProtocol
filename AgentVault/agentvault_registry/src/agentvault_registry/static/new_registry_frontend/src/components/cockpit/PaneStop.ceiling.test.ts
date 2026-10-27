/**
 * §FESUITE (V0577): the desk's STOP pane shows each live mandate's standing consent ("not asking below {amount}…") with
 * "Ask me again" beside it: the one place it is withdrawn. Its read swallowed every failure as "a mandate without one is
 * the normal case", but the registry answers 200 with `ceiling: null` for none, so a failed read hid a standing consent
 * that exists, and the row looked like it carried none. The pane now says the read failed and offers it again; a
 * mandate the registry says has none still shows nothing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const MID = 'mandate-0001'
const h = vi.hoisted(() => ({ getCeiling: vi.fn() }))
vi.mock('@/services/api/liability', () => ({
  liabilityApi: {
    myMandates: vi.fn(async () => ({
      mandates: [{ id: 'mandate-0001', agent_did: 'did:theprotocol:a1', status: 'signed', scope: ['transfer'], tier: 'standard' }],
    })),
    getCeiling: h.getCeiling,
  },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(async () => ({ data: [] })), delete: vi.fn() } }))
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: () => {} }))
vi.mock('@/composables/useActingContext', () => ({ useActingContext: () => ({ actingAgent: ref(null) }) }))

import PaneStop from './PaneStop.vue'

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const consent = {
  mandate_id: MID, posture: 'standard', ceilings_allowed: true, decay_hours_default: 24, org_max_amount: null,
  ceiling: { scope: 'transfer', max_per_tx: '5', currency: 'ECU', live: true, state: 'live' },
}

async function pane() {
  const w = mount(PaneStop, { global: { stubs: { AgentLink: true } } })
  await flushPromises()
  return w
}

describe("the STOP pane when a mandate's standing-consent read fails", () => {
  beforeEach(() => { h.getCeiling.mockReset() })

  it('says the read failed and offers it again, and the consent shows once it answers', async () => {
    h.getCeiling.mockRejectedValue(noAnswer())
    const w = await pane()
    const notice = w.find(`[data-testid="ckd-stop-ceiling-unread-${MID}"]`)
    expect(notice.exists(), 'the pane said nothing about a standing consent it could not read').toBe(true)
    expect(notice.text()).toContain('could not be read')

    h.getCeiling.mockResolvedValue(consent)
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find(`[data-testid="ckd-stop-ceiling-unread-${MID}"]`).exists()).toBe(false)
    expect(w.find('[data-testid="ckd-stop-ceiling"]').text()).toContain('not asking below 5 ECU for transfer')
  })

  it('a mandate the registry says has no standing consent shows none, and no failure', async () => {
    h.getCeiling.mockResolvedValue({ ...consent, ceiling: null })
    const w = await pane()
    expect(w.find('[data-testid="ckd-stop-ceiling"]').exists()).toBe(false)
    expect(w.find(`[data-testid="ckd-stop-ceiling-unread-${MID}"]`).exists()).toBe(false)
  })
})
