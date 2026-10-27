import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): a status-filter switch whose read failed only toasted and left the previous filter's deliveries
 * under the new chip. A switch never shows the old filter's rows; a failed read with nothing to show says so.
 */
const svc = vi.hoisted(() => ({ aggregate: vi.fn(), recentDeliveries: vi.fn(), disableWebhook: vi.fn(), testWebhook: vi.fn() }))
vi.mock('@/services/api/webhooksAdmin', () => ({ webhooksAdminService: svc }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined) }) }))

import AdminWebhooks from './AdminWebhooks.vue'

const AGG = { period: '24h', as_of: '2026-10-05T11:00:00Z',
  webhooks: { total: 1, active: 1, inactive: 0, developers_with_webhooks: 1 },
  deliveries_in_window: { total: 1, success: 1, failed: 0, pending: 0, retried: 0, success_rate_pct: 100 },
  top_event_types: [], top_failing_webhooks: [] }
const ROW = { id: 'd-all-1', webhook_id: 'w1', webhook_url: 'https://example.invalid/hook', developer_id: 1,
  developer_email: 'dev@example.invalid', event_type: 'agent.created', response_status: 200, response_body: null,
  retry_count: 0, next_retry_at: null, delivered_at: '2026-10-05T11:00:00Z', error_message: null }

describe('the deliveries feed says what it read', () => {
  beforeEach(() => {
    for (const f of Object.values(svc)) f.mockReset()
    svc.aggregate.mockResolvedValue(AGG)
  })

  it('a failed filter switch shows neither the old filter rows nor "no deliveries"', async () => {
    svc.recentDeliveries.mockResolvedValueOnce({ deliveries: [ROW] })
    const w = mount(AdminWebhooks, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
    await flushPromises()
    expect(w.text(), 'the first read drew its row').toContain('agent.created')
    svc.recentDeliveries.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const failedChip = w.findAll('button.aw-chip-btn').find((b) => b.text() === 'Failed')!
    await failedChip.trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('agent.created')
    expect(w.text()).not.toContain('No deliveries match this filter.')
    expect(w.find('[data-testid="aw-deliveries-failed"]').exists()).toBe(true)
    w.unmount()
  })

  // §FESUITE V0578: the period half of the same shape
  it("a period switch whose read failed does not leave the previous period's figures under the new button", async () => {
    svc.recentDeliveries.mockResolvedValue({ deliveries: [ROW] })
    svc.aggregate.mockResolvedValueOnce({ ...AGG, webhooks: { ...AGG.webhooks, total: 4321 } })
    const w = mount(AdminWebhooks, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
    await flushPromises()
    expect(w.text(), "the 24h figures").toContain('4321')
    svc.aggregate.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    await w.findAll('button.aw-period-btn').find((b) => b.text() === '7 days')!.trigger('click')
    await flushPromises()
    expect(w.text(), "24h's figures under the 7-day button").not.toContain('4321')
    expect(w.find('.aw-error-text').exists(), 'the read says it failed').toBe(true)
    svc.aggregate.mockResolvedValueOnce({ ...AGG, period: '7d', webhooks: { ...AGG.webhooks, total: 8765 } })
    await w.findAll('button.aw-btn--ghost').find((b) => b.text().length > 0)!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('8765')
    w.unmount()
  })
})
