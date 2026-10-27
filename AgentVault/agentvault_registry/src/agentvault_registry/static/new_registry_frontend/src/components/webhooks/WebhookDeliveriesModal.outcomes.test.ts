/**
 * §DOCSFIX D6-786 (2026-10-17): the delivery log counts a redirect as the failed attempt it is.
 *
 * The registry's "failed" filter now lists every answer other than 2xx (a 3xx is not followed and is retried, D6-765).
 * The log counted "failed" as 4xx/5xx on its own, titled the chip "HTTP 4xx/5xx responses" and showed a retry slot only
 * for 4xx/5xx or no answer, so a redirect was counted in no outcome and its next retry was hidden. The log is mounted
 * on a stand-in delivery list: one 2xx, one 301 and one 404 (each with a retry slot where it failed), one with no answer.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const soon = new Date(Date.now() + 5 * 60_000).toISOString()
const at = new Date(Date.now() - 60_000).toISOString()
const ROWS = [
  { id: 'd-ok', event_type: 'webhook.test', response_status: 200, retry_count: 0, delivered_at: at, next_retry_at: null },
  { id: 'd-301', event_type: 'webhook.test', response_status: 301, retry_count: 1, delivered_at: at, next_retry_at: soon },
  { id: 'd-404', event_type: 'webhook.test', response_status: 404, retry_count: 0, delivered_at: at, next_retry_at: soon },
  { id: 'd-none', event_type: 'webhook.test', response_status: null, retry_count: 0, delivered_at: at, next_retry_at: soon,
    error_message: 'Request timeout' },
]

vi.mock('@/services/api/webhookService', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  webhookService: { getDeliveries: vi.fn(async () => ({ total: ROWS.length, deliveries: ROWS })) },
}))

import WebhookDeliveriesModal from './WebhookDeliveriesModal.vue'

function stat(w: ReturnType<typeof mount>, label: string): string {
  const cell = w.findAll('.wh-dl-stat-cell').find((c) => c.find('.wh-dl-stat-label').text() === label)
  return cell ? cell.find('.wh-dl-stat-value').text() : `no ${label} cell`
}

describe('the webhook delivery log', () => {
  it('counts a redirect as failed, says so on the Failed chip, and shows its next retry', async () => {
    setActivePinia(createPinia())
    const w = mount(WebhookDeliveriesModal, {
      props: { webhook: { id: 'wh-1', url: 'https://hooks.example/in', is_active: true, events: [] } as any },
      global: { stubs: { Teleport: true, JsonViewer: true } },
    })
    await flushPromises()
    expect(stat(w, 'SHOWING')).toBe('4')
    expect([stat(w, 'SUCCESS'), stat(w, 'FAILED'), stat(w, 'PENDING')]).toEqual(['1', '2', '1'])
    const chip = w.findAll('.wh-dl-chip').find((c) => c.text().startsWith('Failed'))
    expect(chip?.attributes('title')).toMatch(/redirect/)
    expect(chip?.attributes('title')).not.toMatch(/4xx\/5xx/)
    const redirect = w.findAll('.wh-dl-row-head').find((r) => r.text().includes('301'))
    expect(redirect?.text()).toContain('NEXT')
    w.unmount()
  })
})
