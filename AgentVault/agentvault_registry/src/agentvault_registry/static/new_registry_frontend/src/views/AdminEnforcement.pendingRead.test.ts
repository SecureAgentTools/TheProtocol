import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): a failed read of the two-man queue put a toast up and said "the queue is clear" under it. The
 * queue says its read failed; an answered empty queue still says clear.
 */
const adm = vi.hoisted(() => ({ listPending: vi.fn(), getPolicy: vi.fn(), getPolicyDefaults: vi.fn(), getResolvedPolicy: vi.fn(), agentStatus: vi.fn() }))
vi.mock('@/services/api/enforcementAdmin', () => ({ enforcementAdmin: adm }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

import AdminEnforcement from './AdminEnforcement.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true } } }

describe('the two-man queue says what it read', () => {
  beforeEach(() => {
    for (const f of Object.values(adm)) f.mockReset()
    adm.getPolicy.mockResolvedValue({})
    adm.getPolicyDefaults.mockResolvedValue({})
    adm.getResolvedPolicy.mockRejectedValue(new Error('not in this test'))   // the posture block stays out (resolved null)
  })

  it('a failed queue read is no "the queue is clear"', async () => {
    adm.listPending.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(AdminEnforcement, opts)
    await flushPromises()
    expect(w.text()).not.toContain('the queue is clear')
    expect(w.find('[data-testid="enf-pending-failed"]').exists()).toBe(true)
    w.unmount()
  })

  it('an answered empty queue says it is clear', async () => {
    adm.listPending.mockResolvedValue({ pending: [] })
    const w = mount(AdminEnforcement, opts)
    await flushPromises()
    expect(w.text()).toContain('the queue is clear')
    expect(w.find('[data-testid="enf-pending-failed"]').exists()).toBe(false)
    w.unmount()
  })
})
