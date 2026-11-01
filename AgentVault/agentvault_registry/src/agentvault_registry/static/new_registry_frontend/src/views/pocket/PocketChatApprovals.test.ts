import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0651 (y) (the maintainer's bug report from his phone, 2026-10-31: "under approvals in pocket it's also not there"):
 * Pocket's Approvals lists the chat's approval requests the signed-in person decides, each opening its room on that
 * request (?approval=). A failed read says so; a registry without the list (404) or with approvals off (501) shows
 * nothing; an empty list says none waits. BASE (V0650): the component does not exist.
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>>, push: vi.fn() }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok' }) }))

import PocketChatApprovals from './PocketChatApprovals.vue'

const item = (id: string, over: Record<string, unknown> = {}) => ({
  id, conversation_id: 'room1', status: 'pending', title: `Request ${id}`, unlocks: `step ${id}`,
  requester: { agent_did: 'did:theprotocol:eu:00000000aaaaaa', name: 'session-release' },
  created_at: '2026-10-31T03:50:00Z', expires_at: new Date(Date.now() + 3600e3).toISOString(),
  room: { conversation_id: 'room1', title: 'TheProtocol Sessions', org_id: 'org1', org_name: 'TheProtocol Sessions' },
  ...over,
})
const opts = { global: { stubs: { Icon: true } } }
const err = (status: number) => Object.assign(new Error(`HTTP ${status}`), { status })

describe("Pocket's Approvals lists the chat's approval requests", () => {
  beforeEach(() => { h.chat = {}; h.push = vi.fn() })

  it('lists each waiting request with its room, its asker and whether it affects production', async () => {
    h.chat.listWaitingApprovals = vi.fn().mockResolvedValue({ items: [item('apr_1'), item('apr_2', { production_impact: true })] })
    const w = mount(PocketChatApprovals, opts)
    await flushPromises()
    expect(h.chat.listWaitingApprovals).toHaveBeenCalledWith('dev-tok')
    expect(w.find('[data-testid="pca-count"]').text()).toBe('2')
    const first = w.find('[data-testid="pca-item-apr_1"]')
    expect(first.text()).toContain('Request apr_1')
    expect(first.text()).toContain('TheProtocol Sessions')
    expect(first.text()).toContain('session-release')
    expect(w.find('[data-testid="pca-item-apr_2"] [data-testid="pca-prod"]').exists()).toBe(true)
    expect(first.find('[data-testid="pca-prod"]').exists()).toBe(false)
  })

  it('opens the room on the request it names', async () => {
    h.chat.listWaitingApprovals = vi.fn().mockResolvedValue({ items: [item('apr_7')] })
    const w = mount(PocketChatApprovals, opts)
    await flushPromises()
    await w.find('[data-testid="pca-item-apr_7"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith({ path: '/pocket/ourchat/room1', query: { approval: 'apr_7' } })
  })

  it('says when none waits, and when the list could not be read (never an empty list for a failure)', async () => {
    h.chat.listWaitingApprovals = vi.fn().mockResolvedValue({ items: [] })
    const none = mount(PocketChatApprovals, opts)
    await flushPromises()
    expect(none.find('[data-testid="pca-none"]').exists()).toBe(true)
    h.chat.listWaitingApprovals = vi.fn().mockRejectedValue(err(503))
    const failed = mount(PocketChatApprovals, opts)
    await flushPromises()
    expect(failed.find('[data-testid="pca-read-failed"]').exists()).toBe(true)
    expect(failed.find('[data-testid="pca-none"]').exists()).toBe(false)
  })

  it('shows nothing on a registry without the list or with approvals off', async () => {
    for (const status of [404, 501]) {
      h.chat.listWaitingApprovals = vi.fn().mockRejectedValue(err(status))
      const w = mount(PocketChatApprovals, opts)
      await flushPromises()
      expect(w.find('[data-testid="pca"]').exists()).toBe(false)
    }
  })
})
