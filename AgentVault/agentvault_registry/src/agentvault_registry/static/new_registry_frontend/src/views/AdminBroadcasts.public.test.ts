import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d, his yes seq 3638): an admin marks an announcement PUBLIC from the compose form and from
 * a broadcast's edit drawer. The mark is off unless chosen, it cannot be chosen for a broadcast aimed at an organization (the registry
 * refuses it; the form says why instead of sending it), and a copy of a broadcast never inherits it. BASE: the form has no such choice.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post, delete: vi.fn(), put: h.put } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 1, is_admin: true } }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }))

import AdminBroadcasts from './AdminBroadcasts.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true, Teleport: true, teleport: true } } }
const BC = {
  id: 5, title: 'Window on Saturday', body: 'Ten minutes.', broadcast_type: 'info', created_by: 1, created_at: '2026-11-14T10:00:00Z',
  is_active: true, send_email: false, email_sent_at: null, ws_recipients: 3, public: false,
}

async function opened() {
  const w = mount(AdminBroadcasts, opts)
  await flushPromises()
  await w.find('.adb-compose-btn').trigger('click')
  await w.find('.adb-modal input').setValue('Release V0663')
  await w.find('.adb-modal textarea').setValue('Mentions, the bell and workflows.')
  return w
}

describe('marking an announcement public', () => {
  beforeEach(() => {
    h.get.mockReset().mockImplementation(async (url: string) => url.endsWith('/stats')
      ? { data: { broadcast_id: 5, title: BC.title, is_active: true, ws_recipients_at_send: 3, email_sent: false, read_count: 0,
          total_developers: 1, read_pct: 0, recent_readers: [] } }
      : url.endsWith('/overview')
      ? { data: { total: 0, active: 0, retracted: 0, last_24h: 0, last_7d: 0, by_type: {}, emails_sent: 0, total_recipients_lifetime: 0,
          ws_connections_now: 1, verified_developers: 1, scope: 'frame', scope_description: '' } }
      : { data: [BC] })
    h.post.mockReset().mockResolvedValue({ data: { id: 6 } })
    h.put.mockReset().mockResolvedValue({ data: { ...BC, public: true } })
  })

  it('sends public: false unless the admin chose it', async () => {
    const w = await opened()
    expect((w.get('[data-testid="adb-public"]').element as HTMLInputElement).checked).toBe(false)
    await w.find('.adb-modal .adb-btn-primary').trigger('click')
    await flushPromises()
    expect(h.post.mock.calls[0][1]).toMatchObject({ public: false })
  })

  it('sends public: true when chosen', async () => {
    const w = await opened()
    await w.get('[data-testid="adb-public"]').setValue(true)
    await w.find('.adb-modal .adb-btn-primary').trigger('click')
    await flushPromises()
    expect(h.post.mock.calls[0][1]).toMatchObject({ public: true })
  })

  it('cannot be chosen for a broadcast aimed at an organization, and says why', async () => {
    const w = await opened()
    await w.get('[data-testid="adb-public"]').setValue(true)
    await w.find('.adb-modal input[maxlength="255"]').setValue('org-7')
    await flushPromises()
    const box = w.get('[data-testid="adb-public"]').element as HTMLInputElement
    expect(box.disabled).toBe(true)
    expect(box.checked).toBe(false)
    expect(w.get('[data-testid="adb-public-hint"]').text()).toContain('everyone')
    await w.find('.adb-modal .adb-btn-primary').trigger('click')
    await flushPromises()
    expect(h.post.mock.calls[0][1]).toMatchObject({ public: false, target_org_id: 'org-7' })
  })

  it('the edit drawer sends the mark with the edit', async () => {
    const w = mount(AdminBroadcasts, opts)
    await flushPromises()
    await w.find('.adb-row').trigger('click')
    await flushPromises()
    await w.find('button[title]:not(.adb-compose-btn)').exists()
    const edit = w.findAll('button').find((b) => b.attributes('title') === 'Edit this broadcast' || /edit/i.test(b.text()))
    await edit!.trigger('click')
    await w.get('[data-testid="adb-edit-public"]').setValue(true)
    await w.find('.adb-edit-actions .adb-btn-primary').trigger('click')
    await flushPromises()
    expect(h.put.mock.calls[0][1]).toMatchObject({ public: true })
  })

  it('a copy of a broadcast starts private', async () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'AdminBroadcasts.vue'), 'utf8')
    const copy = src.slice(src.indexOf('function copyAsNew'), src.indexOf('async function saveEdit'))
    expect(copy).toContain('public: false')
  })
})
