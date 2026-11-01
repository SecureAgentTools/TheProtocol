import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'

/**
 * V0652 (ai) (order gwo_b13813d486f28d456a324293): the desk's durable notice clicks to `#/admin/chatdesk?ticket=N`, and
 * the desk opens that ticket, on arrival and when the desk is already open (vue-router reuses the component on a
 * query-only change). BASE (V0651): the desk read no query; a notice opened the queue, not the ticket.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), route: null as any }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), patch: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: true, user: { developer_id: 1 } }) }))
vi.mock('@/composables/useSupportStream', () => ({ useSupportStream: () => ({}) }))
vi.mock('vue-router', () => ({ useRoute: () => h.route }))

import AdminChatDesk from './AdminChatDesk.vue'

const ticket = (id: number) => ({ id, subject: `Help ${id}`, status: 'open', priority: 'normal', category: 'general',
  created_at: '2026-10-31T20:00:00Z', updated_at: '2026-10-31T20:00:00Z', developer_email: 'p@example.com', messages: [] })

describe("the desk opens the ticket its notice names", () => {
  beforeEach(() => {
    h.get.mockReset()
    h.get.mockImplementation(async (url: string) => {
      const m = url.match(/^\/admin\/support\/tickets\/(\d+)$/)
      if (m) return { data: ticket(Number(m[1])) }
      if (url === '/admin/support/tickets/stats') return { data: { open: 2, in_progress: 0, resolved: 0, closed: 0 } }
      if (url === '/admin/support/tickets') return { data: [ticket(7), ticket(8)] }
      return { data: { grants: [] } }
    })
  })

  it('on arrival', async () => {
    h.route = reactive({ query: { ticket: '7' } })
    const w = mount(AdminChatDesk, { global: { stubs: { Icon: true } } })
    await flushPromises()
    expect(h.get.mock.calls.map((c) => c[0])).toContain('/admin/support/tickets/7')
    w.unmount()
  })

  it('when the desk is already open and the link changes', async () => {
    h.route = reactive({ query: {} as Record<string, string> })
    const w = mount(AdminChatDesk, { global: { stubs: { Icon: true } } })
    await flushPromises()
    expect(h.get.mock.calls.map((c) => c[0])).not.toContain('/admin/support/tickets/8')
    h.route.query = { ticket: '8' }
    await flushPromises()
    expect(h.get.mock.calls.map((c) => c[0])).toContain('/admin/support/tickets/8')
    w.unmount()
  })

  it('ignores what is not a ticket number (control)', async () => {
    h.route = reactive({ query: { ticket: 'x' } })
    const w = mount(AdminChatDesk, { global: { stubs: { Icon: true } } })
    await flushPromises()
    expect(h.get.mock.calls.map((c) => c[0]).filter((u) => /^\/admin\/support\/tickets\/\d+$/.test(u))).toEqual([])
    w.unmount()
  })
})
