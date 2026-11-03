import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h as vh } from 'vue'

/**
 * V0652 (ad) (order gwo_e5e9ad061d6e5be9605a3067): an organization room's side panel on the console's chat. Its
 * sections (the approvals handed in, the status board and live cards only when handed in, who is present from the
 * organization's presence read), each section's states (reading, read failed with a retry, none, the agents with a
 * live status line first), the fold kept per person (a folded presence section reads nothing), and a link that opens
 * one approval opening a folded approvals section. BASE (V0651): the component does not exist.
 */
const m = vi.hoisted(() => ({ presence: vi.fn() }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: m.presence } }))

import ChatSidePanel from './ChatSidePanel.vue'

const agent = (did: string, name: string | null, status: string | null, last = '2026-11-01T00:00:00Z') => ({
  did, name, owner_developer_id: 6, last_active_at: last, account_status: 'active',
  status: status ? { text: status, set_at: null, expires_at: '2099-01-01T00:00:00Z', expires_in_seconds: 9e6 } : null,
})
const presence = (agents: unknown[]) => ({ organization_id: 'org1', as_of: '2026-11-01T00:00:00Z', agents, count: agents.length })
const base = { orgId: 'org1', viewerKey: 'developer:6' }
const opts = (props: Record<string, unknown> = {}, slots: Record<string, () => unknown> = {}) => ({
  props: { ...base, ...props },
  slots: { approvals: () => vh('div', { 'data-testid': 'slot-approvals' }, 'the pinned panel'), ...slots },
  global: { stubs: { Icon: true } },
})
const sectionKeys = (w: ReturnType<typeof mount>) => w.findAll('section.csp-sec').map((s) => s.attributes('data-testid'))

describe('the side panel of an organization room', () => {
  beforeEach(() => { localStorage.clear(); m.presence.mockReset() })
  afterEach(() => { vi.useRealTimers() })

  it('holds the approvals handed in and who is present; no board or live cards until a thread hands them in', async () => {
    m.presence.mockResolvedValue(presence([]))
    const w = mount(ChatSidePanel, opts())
    await flushPromises()
    expect(sectionKeys(w)).toEqual(['csp-approvals', 'csp-present'])
    expect(w.find('[data-testid="slot-approvals"]').exists()).toBe(true)
  })

  it('draws the status board and the live cards when handed in, in that order', async () => {
    m.presence.mockResolvedValue(presence([]))
    const w = mount(ChatSidePanel, opts({}, {
      board: () => vh('div', { 'data-testid': 'slot-board' }, 'board'),
      live: () => vh('div', { 'data-testid': 'slot-live' }, 'live'),
    }))
    await flushPromises()
    expect(sectionKeys(w)).toEqual(['csp-approvals', 'csp-board', 'csp-live', 'csp-present'])
    expect(w.find('[data-testid="slot-board"]').exists() && w.find('[data-testid="slot-live"]').exists()).toBe(true)
  })

  it('names who is present: a live status line first, a live ring for it, a quiet one without, the count', async () => {
    m.presence.mockResolvedValue(presence([
      agent('did:x:bbbb', 'session-lead', null),
      agent('did:x:aaaa', 'session-release', 'building (ad), the side panel'),
      agent('did:x:cccc', null, 'proof at 04:30Z'),
    ]))
    const w = mount(ChatSidePanel, opts())
    await flushPromises()
    expect(m.presence).toHaveBeenCalledWith('org1')
    const rows = w.findAll('li.csp-agent')
    expect(rows.map((r) => r.attributes('data-live'))).toEqual(['1', '1', '0'])
    expect(rows[0].find('.csp-name').text()).toBe('did:x:cccc')            // no name: the DID, never blank
    expect(rows[1].text()).toContain('building (ad), the side panel')
    expect(rows[2].text()).toContain('no live status')
    // V0655 (ay): the ring around the logo replaced the dot (presenceRing.test.ts and ChatSidePanel.quick.test.ts)
    expect(rows[0].find('.csp-face').attributes('data-ring')).toBe('live')
    expect(rows[2].find('.csp-face').attributes('data-ring')).toBe('quiet')
    expect(w.find('[data-testid="csp-present-count"]').text()).toBe('2 of 3 live')
  })

  it('says so when no agent is assigned, and never reads as an empty room when the read failed', async () => {
    m.presence.mockResolvedValueOnce(presence([]))
    const w = mount(ChatSidePanel, opts())
    await flushPromises()
    expect(w.find('[data-testid="csp-present-none"]').exists()).toBe(true)

    m.presence.mockReset()
    m.presence.mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce(presence([agent('did:x:aaaa', 'session-release', 'here')]))
    const f = mount(ChatSidePanel, opts({ orgId: 'org2' }))
    await flushPromises()
    expect(f.find('[data-testid="csp-present-failed"]').exists()).toBe(true)
    expect(f.find('[data-testid="csp-present-none"]').exists()).toBe(false)
    await f.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(f.find('[data-testid="csp-present-failed"]').exists()).toBe(false)
    expect(f.findAll('li.csp-agent')).toHaveLength(1)
  })

  it('a section folds and stays folded for that person; a folded presence section reads nothing', async () => {
    m.presence.mockResolvedValue(presence([]))
    const w = mount(ChatSidePanel, opts())
    await flushPromises()
    expect(m.presence).toHaveBeenCalledTimes(1)
    const toggle = w.find('[data-testid="csp-present-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-testid="csp-present-none"]').exists()).toBe(false)
    w.unmount()

    m.presence.mockClear()
    const again = mount(ChatSidePanel, opts())
    await flushPromises()
    expect(again.find('[data-testid="csp-present-toggle"]').attributes('aria-expanded')).toBe('false')
    expect(m.presence).not.toHaveBeenCalled()
    await again.find('[data-testid="csp-present-toggle"]').trigger('click')
    await flushPromises()
    expect(m.presence).toHaveBeenCalledTimes(1)                 // opening it reads
  })

  it('the approvals stay mounted while folded (their count stays live), and a link to one request opens them', async () => {
    m.presence.mockResolvedValue(presence([]))
    localStorage.setItem('ourchat.side.v1.developer:6', JSON.stringify({ approvals: false, board: true, live: true, present: true }))
    const w = mount(ChatSidePanel, opts({ approvalsCount: 2 }))
    await flushPromises()
    const body = w.find('[data-testid="slot-approvals"]')
    expect(body.exists()).toBe(true)
    expect((body.element.parentElement as HTMLElement).style.display).toBe('none')
    expect(w.find('[data-testid="csp-approvals-count"]').text()).toBe('2')
    await w.setProps({ focusApprovals: true })
    expect((w.find('[data-testid="slot-approvals"]').element.parentElement as HTMLElement).style.display).toBe('')
    expect(w.find('[data-testid="csp-approvals-toggle"]').attributes('aria-expanded')).toBe('true')
  })

  it('reads again every two minutes while the tab shows it, and not while hidden', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    m.presence.mockResolvedValue(presence([]))
    const w = mount(ChatSidePanel, opts())
    await flushPromises()
    expect(m.presence).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(120000)
    expect(m.presence).toHaveBeenCalledTimes(2)
    const vis = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    vi.advanceTimersByTime(120000)
    expect(m.presence).toHaveBeenCalledTimes(2)
    vis.mockRestore()
    w.unmount()
  })
})
