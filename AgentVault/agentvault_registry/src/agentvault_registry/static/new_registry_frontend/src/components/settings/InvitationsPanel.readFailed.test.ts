import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (2026-10-05): a failed list read drew the banner ("Could not load invite codes.", or the missing admin right on
 * a 403) AND "No invite codes yet" under it. The list says nothing it did not read; an answered empty list still says
 * none.
 */
const api = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/services/api/inviteCodes', () => ({
  listInviteCodes: api.list, generateInviteCodes: vi.fn(), revokeInviteCode: vi.fn(),
  ADMIN_FLAGS: [], flagLabel: (f: string) => f,
}))

import InvitationsPanel from './InvitationsPanel.vue'

describe('the invitations list says what it read', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.list.mockReset()
  })

  it('a failed read shows the banner and no "none" under it', async () => {
    api.list.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(InvitationsPanel, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
    await flushPromises()
    expect(w.text()).toContain('Could not load invite codes.')
    expect(w.find('[data-testid="iv-none"]').exists()).toBe(false)
    expect(w.text()).not.toContain('No invite codes yet')
  })

  it('a refused read (no admin right) says so, and no "none" either', async () => {
    api.list.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 403'), { response: { status: 403 } }))
    const w = mount(InvitationsPanel, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
    await flushPromises()
    expect(w.text()).toContain('admin_support')
    expect(w.find('[data-testid="iv-none"]').exists()).toBe(false)
    expect(w.text()).not.toContain('No invite codes yet')
  })

  it('an answered empty list still says none', async () => {
    api.list.mockResolvedValueOnce([])
    const w = mount(InvitationsPanel, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
    await flushPromises()
    expect(w.find('[data-testid="iv-none"]').exists()).toBe(true)
  })
})
