import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-10, lifecycle 87): a broadcast aimed at one organization said it was "pushed to 37 live
 * connection(s)" (every connection on the frame) and its button offered "Send to 37 live + 120 verified". Its reach is
 * the organization's members: the button and the toast say that. The control: a broadcast to everyone keeps the
 * frame's counts.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), showSuccess: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post, delete: vi.fn(), put: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 1, is_admin: true } }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: h.showSuccess, showError: vi.fn() }) }))

import AdminBroadcasts from './AdminBroadcasts.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true, Teleport: true, teleport: true } } }

async function composed(org: string) {
  const w = mount(AdminBroadcasts, opts)
  await flushPromises()
  await w.find('.adb-compose-btn').trigger('click')
  await w.find('.adb-modal input').setValue('Window on Saturday')
  await w.find('.adb-modal textarea').setValue('We will be down for ten minutes.')
  await w.find('.adb-modal input[maxlength="255"]').setValue(org)
  return w
}

describe('a broadcast says who it reaches', () => {
  beforeEach(() => {
    h.get.mockReset().mockImplementation(async (url: string) => url.endsWith('/overview')
      ? { data: { total: 0, active: 0, retracted: 0, last_24h: 0, last_7d: 0, by_type: {}, emails_sent: 0,
          total_recipients_lifetime: 0, ws_connections_now: 37, verified_developers: 120, scope: 'frame', scope_description: '' } }
      : { data: [] })
    h.post.mockReset().mockResolvedValue({ data: { id: 5 } })
    h.showSuccess.mockReset()
  })

  it('aimed at an organization: its members, not the frame\'s connections', async () => {
    const w = await composed('org-7')
    const send = w.find('.adb-modal-footer .adb-btn-primary')
    expect(send.text()).toMatch(/send to the organization's members/i)
    expect(send.text()).not.toMatch(/37/)
    await send.trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledWith('/admin/broadcasts', expect.objectContaining({ target_org_id: 'org-7' }))
    const [, body] = h.showSuccess.mock.calls[0]
    expect(body).toMatch(/sent to the organization's members/i)
    expect(body).not.toMatch(/37|live connection/i)
  })

  it('control: to everyone, the frame\'s counts', async () => {
    const w = await composed('')
    expect(w.find('.adb-modal-footer .adb-btn-primary').text()).toMatch(/37/)
    await w.find('.adb-modal-footer .adb-btn-primary').trigger('click')
    await flushPromises()
    expect(String(h.showSuccess.mock.calls[0][1])).toMatch(/37/)
  })
})
