import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): a failed read of the moderation queue toasted and drew the shield and "no reports" under it, with
 * 0 / 0 / 0 above: an all-clear the page never read. The queue says its read failed and its counts read a dash; an
 * answered empty queue still says none.
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: http.get, post: vi.fn() } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))

import AdminMarketplace from './AdminMarketplace.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true } } }

describe('the moderation queue says what it read', () => {
  beforeEach(() => { http.get.mockReset() })

  it('a failed read is no all-clear, and the counts read a dash', async () => {
    http.get.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(AdminMarketplace, opts)
    await flushPromises()
    expect(w.find('.am-empty').exists()).toBe(false)
    expect(w.find('[data-testid="am-reports-failed"]').exists()).toBe(true)
    expect(w.findAll('.am-stat-n').map((n) => n.text())).toEqual(['—', '—', '—'])
    w.unmount()
  })

  it('an answered empty queue says none, with its counts', async () => {
    http.get.mockResolvedValue({ data: { reports: [], summary: { open: 0, resolved: 2, total: 2 } } })
    const w = mount(AdminMarketplace, opts)
    await flushPromises()
    expect(w.find('.am-empty').exists()).toBe(true)
    expect(w.find('[data-testid="am-reports-failed"]').exists()).toBe(false)
    expect(w.findAll('.am-stat-n').map((n) => n.text())).toEqual(['0', '2', '2'])
    w.unmount()
  })
})
