import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h as vh } from 'vue'

/**
 * V0654 (aq) (order gwo_238870d0f3c281c7d870554d): the side panel's sessions show what of the room wakes each member,
 * and give the room's owner (signed in) the switch: listen, on call, off. An agent of the organization that is not a
 * member of the room shows none. BASE (V0653): no mode is shown, no switch.
 */
const m = vi.hoisted(() => ({ presence: vi.fn() }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: m.presence } }))

import ChatSidePanel from './ChatSidePanel.vue'

const LEAD = 'did:theprotocol:eu.test:LEAD', TESTER = 'did:theprotocol:eu.test:tester', OUT = 'did:theprotocol:eu.test:outside'
const agent = (did: string, name: string) => ({ did, name, owner_developer_id: 6, last_active_at: '2026-11-02T16:00:00Z',
  account_status: 'active', status: { text: 'working', set_at: null, expires_at: '2099-01-01T00:00:00Z', expires_in_seconds: 9e6 } })
const modes = { 'agt:did:theprotocol:eu.test:lead': 'on-call', 'agt:did:theprotocol:eu.test:tester': 'listen' }
const mountPanel = (props: Record<string, unknown>) => mount(ChatSidePanel, {
  props: { orgId: 'org1', viewerKey: 'dev:6', ...props },
  slots: { approvals: () => vh('div', 'pinned') },
  global: { stubs: { Icon: true } },
})

describe('the sessions and their wake modes', () => {
  beforeEach(() => {
    localStorage.clear()
    m.presence.mockReset().mockResolvedValue({ organization_id: 'org1', as_of: 'x', count: 3,
      agents: [agent(LEAD, 'session-lead'), agent(TESTER, 'session-tester'), agent(OUT, 'outsider')] })
  })

  it('the room\'s owner gets a switch for each member, set to its mode, and none for an agent outside the room', async () => {
    const w = mountPanel({ wakeModes: modes, canSetWake: true })
    await flushPromises()
    expect(w.find(`[data-testid="wake-switch-${LEAD}"]`).attributes('data-mode')).toBe('on-call')
    expect(w.find(`[data-testid="wake-on-call-${LEAD}"]`).attributes('aria-checked')).toBe('true')
    expect(w.find(`[data-testid="wake-switch-${TESTER}"]`).attributes('data-mode')).toBe('listen')
    expect(w.find(`[data-testid="wake-switch-${OUT}"]`).exists()).toBe(false)
  })

  it('a press asks for that member\'s new mode by its key; the mode it has asks nothing', async () => {
    const w = mountPanel({ wakeModes: modes, canSetWake: true })
    await flushPromises()
    await w.find(`[data-testid="wake-off-${TESTER}"]`).trigger('click')
    await w.find(`[data-testid="wake-on-call-${LEAD}"]`).trigger('click')
    expect(w.emitted('set-wake')).toEqual([['agt:did:theprotocol:eu.test:tester', 'off']])
  })

  it('anyone else reads the mode, never a switch, and a listening member shows nothing extra', async () => {
    const w = mountPanel({ wakeModes: modes, canSetWake: false })
    await flushPromises()
    expect(w.find('[data-testid^="wake-switch-"]').exists()).toBe(false)
    expect(w.find(`[data-testid="csp-wake-${LEAD}"]`).text()).toBe('On call')
    expect(w.find(`[data-testid="csp-wake-${TESTER}"]`).exists()).toBe(false)
  })
})
