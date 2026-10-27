import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §COCKPITDESK (2026-10-15) — /webhooks: a deleted endpoint leaves the bulk selection (it stayed selected unseen, and a
 * bulk pause counted it among the endpoints that succeeded); a refused delete keeps its confirmation without throwing out
 * of the click, and a second press sends no second DELETE; the deliveries drawer shows the endpoint opened last.
 */
const h = vi.hoisted(() => ({
  svc: { listWebhooks: vi.fn(), deleteWebhook: vi.fn(), getDeliveries: vi.fn(), testWebhook: vi.fn(), updateWebhook: vi.fn() },
}))
vi.mock('@/services/api/webhookService', async (orig) => ({ ...(await orig<Record<string, unknown>>()), webhookService: h.svc }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showWarning: vi.fn() }) }))

import WebhookManager from './WebhookManager.vue'
import { useWebhookStore } from '@/stores/webhooks'

const hook = (id: string) => ({ id, url: `https://example.org/${id}`, events: ['agent.created'], is_active: true,
  description: '', created_at: '2026-10-14T00:00:00Z', failure_count: 0 })
const stubs = { Icon: true, WebhookModal: true, WebhookDeliveries: true, Teleport: true, teleport: true }
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}
const rows = (w: ReturnType<typeof mount>) => w.findAll('[data-testid="whm-row"]')

describe('the webhooks page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h.svc)) f.mockReset()
    h.svc.listWebhooks.mockResolvedValue([hook('w1'), hook('w2')])
  })

  it('a deleted endpoint leaves the bulk selection', async () => {
    h.svc.deleteWebhook.mockResolvedValue(undefined)
    const w = mount(WebhookManager, { global: { stubs } })
    await flushPromises()
    for (const r of rows(w)) await r.find('input.whm-check').trigger('click')
    expect(w.find('[data-testid="whm-bulk"]').classes()).toContain('whm-bulk--active')
    await rows(w)[0].find('.webhook-btn--delete').trigger('click')
    await w.find('.webhook-btn--confirm-delete').trigger('click')
    await flushPromises()
    expect(rows(w)).toHaveLength(1)
    expect(w.find('[data-testid="whm-bulk"]').text(), 'only the endpoint that exists stays selected').toMatch(/\b1\b/)
    w.unmount()
  })

  it('a refused delete keeps its confirmation, and a second press sends no second DELETE', async () => {
    const pending = deferred<never>()
    h.svc.deleteWebhook.mockImplementation(() => pending.promise)
    const w = mount(WebhookManager, { global: { stubs } })
    await flushPromises()
    await rows(w)[0].find('.webhook-btn--delete').trigger('click')
    const confirm = w.find('.webhook-btn--confirm-delete')
    await confirm.trigger('click')
    await confirm.trigger('click')
    expect(h.svc.deleteWebhook).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('a refused delete does not throw out of the click and keeps the confirmation', async () => {
    h.svc.deleteWebhook.mockRejectedValue(Object.assign(new Error('Request failed with status code 403'), { response: { status: 403 } }))
    const w = mount(WebhookManager, { global: { stubs } })
    await flushPromises()
    await rows(w)[0].find('.webhook-btn--delete').trigger('click')
    await w.find('.webhook-btn--confirm-delete').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="whm-delete-confirm"]').exists(), 'the confirmation stays to retry or cancel').toBe(true)
    expect(rows(w)).toHaveLength(2)
    w.unmount()
  })

  it("endpoint A's deliveries landing after B's drawer opened are dropped", async () => {
    const slowA = deferred<{ deliveries: unknown[] }>()
    h.svc.getDeliveries.mockImplementation((id: string) =>
      id === 'w1' ? slowA.promise : Promise.resolve({ deliveries: [{ id: 'd-b', webhook_id: 'w2' }] }))
    const store = useWebhookStore()
    await store.fetchWebhooks()
    const first = store.fetchDeliveries('w1')
    await store.fetchDeliveries('w2')
    slowA.resolve({ deliveries: [{ id: 'd-a', webhook_id: 'w1' }] })
    await first
    expect(store.deliveries.map((d: { id: string }) => d.id)).toEqual(['d-b'])
    expect(store.selectedWebhook?.id).toBe('w2')
    expect(store.isLoadingDeliveries).toBe(false)
  })
})
