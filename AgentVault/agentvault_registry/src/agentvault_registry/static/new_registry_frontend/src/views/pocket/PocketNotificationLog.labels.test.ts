import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0655 (az) (order gwo_16a6212cd90dbe18baa3537c): the notification history names each type as its settings row does
 * (the catalog's label, notifCatalog.<key with underscores>.label), not by the key's tail ("Session offline" beside the
 * row "A session went quiet"), and a notice held back because you were in the app says so ("you were in the app", on
 * every channel). BASE (V0654): the tail of the key, the reason's raw value and the channel's raw value.
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get }, default: { get: h.get } }))

import PocketNotificationLog from './PocketNotificationLog.vue'

const row = (id: number, type_key: string, extra: Record<string, unknown> = {}) => ({ id, type_key, category: 'chat',
  severity: 'info', channel: 'push_desktop', outcome: 'delivered', reason: null, mode: 'on', device_id: 1, title: 't',
  message: 'm', created_at: new Date().toISOString(), ...extra })

describe('the notification history names what it lists', () => {
  beforeEach(() => {
    h.get.mockReset().mockResolvedValue({ data: { enabled: true, mode: 'on', retention_days: 30, summary: [
      { outcome: 'suppressed', reason: 'present', count: 1 }], entries: [
      row(1, 'org.session_offline'),
      row(2, 'support.desk'),
      row(3, 'chat.approval_requested', { outcome: 'suppressed', reason: 'present', channel: 'all', device_id: null }),
      row(4, 'brand.new_kind_of_thing'),
    ] } })
  })

  it('each type by its settings row\'s label; a type no bundle names yet by its key', async () => {
    const w = mount(PocketNotificationLog, { global: { stubs: { Icon: true, ReadFailedNotice: true } } })
    await flushPromises()
    expect(h.get).toHaveBeenCalledWith('/notifications/history', expect.anything())
    expect(w.find('[data-testid="nl-label-1"]').text()).toBe('A session went quiet')
    expect(w.find('[data-testid="nl-label-2"]').text()).toBe('A support ticket waits for the desk')
    expect(w.find('[data-testid="nl-label-3"]').text()).toBe('Approval asked of you')
    expect(w.find('[data-testid="nl-label-4"]').text()).toBe('New kind of thing')
  })

  it('a notice held back because you were in the app says so, on every channel', async () => {
    const w = mount(PocketNotificationLog, { global: { stubs: { Icon: true, ReadFailedNotice: true } } })
    await flushPromises()
    const held = w.findAll('li.nl-row')[2]
    expect(held.text()).toContain('every channel')
    expect(held.find('.nl-reason').text()).toBe('you were in the app')
    expect(w.find('.nl-sum-label').text()).toContain('you were in the app')
  })
})
