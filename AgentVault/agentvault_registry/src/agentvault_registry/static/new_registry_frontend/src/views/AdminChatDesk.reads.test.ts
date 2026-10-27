import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the support desk swallowed two reads. The status chips counted "Open · 0"
 * and the rest over a failed first stats read, and a failed review-grants read said "No review grants on this ticket.
 * The customer grants access from their own thread." in the consent lane. The chips read "—" until an answer; the lane
 * says its read failed (Try again). Opening another ticket no longer shows the previous ticket's grants meanwhile.
 */
const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), patch: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: true, user: { developer_id: 1 } }) }))
vi.mock('@/composables/useSupportStream', () => ({ useSupportStream: () => ({}) }))

import AdminChatDesk from './AdminChatDesk.vue'

const opts = { global: { stubs: { Icon: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const TICKET = { id: 7, subject: 'Help', status: 'open', priority: 'normal', category: 'general', created_at: '2026-10-05T12:00:00Z',
  updated_at: '2026-10-05T12:00:00Z', developer_email: 'a@example.com', messages: [] }

function routes(o: { stats: 'fail' | 'ok'; grants: 'fail' | 'ok' }) {
  h.get.mockImplementation(async (url: string) => {
    if (url === '/admin/support/tickets/stats') { if (o.stats === 'fail') throw failure(); return { data: { open: 0, in_progress: 0, resolved: 0, closed: 0 } } }
    if (url.endsWith('/review-grants')) { if (o.grants === 'fail') throw failure(); return { data: { grants: [] } } }
    if (url === '/admin/support/tickets/7') return { data: TICKET }
    if (url === '/admin/support/tickets') return { data: [TICKET] }
    return { data: {} }
  })
}
const chips = (w: ReturnType<typeof mount>) => ['open', 'in_progress', 'resolved', 'closed'].map((s) => w.find(`[data-testid="acd-stat-${s}"]`).text())

describe('the support desk says what its reads answered', () => {
  beforeEach(() => { h.get.mockReset() })

  it('a failed stats read: no "· 0" chips', async () => {
    routes({ stats: 'fail', grants: 'ok' })
    const w = mount(AdminChatDesk, opts)
    await flushPromises()
    expect(chips(w).every((c) => c.endsWith('· —')), chips(w).join(' | ')).toBe(true)
    w.unmount()
  })

  it('a failed grants read: no "No review grants" in the consent lane', async () => {
    routes({ stats: 'ok', grants: 'fail' })
    const w = mount(AdminChatDesk, opts)
    await flushPromises()
    await (w.vm as any).openTicket(7)
    await flushPromises()
    expect(w.text()).not.toContain('No review grants on this ticket.')
    expect(w.find('[data-testid="acd-review-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('answered: counts of 0 and "No review grants" stand', async () => {
    routes({ stats: 'ok', grants: 'ok' })
    const w = mount(AdminChatDesk, opts)
    await flushPromises()
    expect(chips(w).every((c) => c.endsWith('· 0')), chips(w).join(' | ')).toBe(true)
    await (w.vm as any).openTicket(7)
    await flushPromises()
    expect(w.text()).toContain('No review grants on this ticket.')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
