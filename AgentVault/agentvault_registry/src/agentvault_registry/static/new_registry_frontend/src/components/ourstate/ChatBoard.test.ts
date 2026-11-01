import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0652 (ac) (order gwo_2ae43c7789db1e808ea1417f): the room's status board. Its text (markdown, sanitized), who last
 * edited it; Edit for the owner and the named (the whole text, against the revision read); an edit that lost to someone
 * else's says so, shows their version and keeps the draft; History; the owner names who keeps it; above the history it
 * is a strip that folds to its first line, the fold kept per person. BASE (V0651): the component does not exist.
 */
const m = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>>, presence: vi.fn() }))
vi.mock('@/services/api/chat', () => ({ chatApi: new Proxy({}, { get: (_t, k: string) => (m.chat[k] ??= vi.fn()) }) }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: m.presence } }))

import ChatBoard from './ChatBoard.vue'

const board = (over: Record<string, unknown> = {}) => ({ text: '**Release:** V0651 at 05:00Z\n- open: (ac), (q)', rev: 2,
  updated_at: '2026-11-01T01:00:00Z', updated_by: { ptype: 'developer', id: '6', name: 'maintainer' }, can_edit: false, ...over })
const base = { token: 'dev-tok', conversationId: 'room1', orgId: 'org1', viewerKey: 'dev:6' }
const opts = (props: Record<string, unknown>): any => ({ props: { ...base, ...props }, global: { stubs: { Icon: true } }, attachTo: document.body })

describe('the status board', () => {
  beforeEach(() => { m.chat = {}; m.presence.mockReset(); localStorage.clear() })
  afterEach(() => { document.body.innerHTML = '' })

  it('reads as markdown, says who edited it last, and a member gets no Edit', async () => {
    const w = mount(ChatBoard, opts({ board: board() }))
    expect(w.find('[data-testid="ost-board-text"] strong').text()).toBe('Release:')
    expect(w.find('[data-testid="ost-board-by"]').text()).toContain('maintainer')
    expect(w.find('[data-testid="ost-board-edit"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-board-editors"]').exists()).toBe(false)     // not the owner
    expect(w.find('[data-testid="ost-board-history"]').exists()).toBe(true)
  })

  it('an editor writes the whole text against the revision read, and the new board goes up', async () => {
    m.chat.putBoard = vi.fn().mockResolvedValue({ board: board({ text: 'new', rev: 3, can_edit: true }), changed: true })
    const w = mount(ChatBoard, opts({ board: board({ can_edit: true }) }))
    await w.find('[data-testid="ost-board-edit"]').trigger('click')
    await w.find('[data-testid="ost-board-draft"]').setValue('new')
    await w.find('[data-testid="ost-board-save"]').trigger('click')
    await flushPromises()
    expect(m.chat.putBoard).toHaveBeenCalledWith('dev-tok', 'room1', 'new', 2)
    expect((w.emitted('update') as any[])[0][0]).toMatchObject({ text: 'new', rev: 3 })
    expect(w.find('[data-testid="ost-board-editor"]').exists()).toBe(false)
  })

  it("an edit that lost to someone else's says so, shows theirs and keeps the draft", async () => {
    m.chat.putBoard = vi.fn().mockRejectedValue(Object.assign(new Error('409'), { status: 409 }))
    m.chat.getBoard = vi.fn().mockResolvedValue(board({ text: 'theirs', rev: 3, can_edit: true }))
    const w = mount(ChatBoard, opts({ board: board({ can_edit: true }) }))
    await w.find('[data-testid="ost-board-edit"]').trigger('click')
    await w.find('[data-testid="ost-board-draft"]').setValue('mine')
    await w.find('[data-testid="ost-board-save"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-board-err"]').text()).toContain('Someone else changed the board')
    expect((w.emitted('update') as any[])[0][0]).toMatchObject({ text: 'theirs', rev: 3 })
    expect((w.find('[data-testid="ost-board-draft"]').element as HTMLTextAreaElement).value).toBe('mine')
  })

  it('the history: every edit, newest first, with its text', async () => {
    m.chat.boardHistory = vi.fn().mockResolvedValue({ revisions: [
      { rev: 1, at: '2026-11-01T00:00:00Z', by: { name: 'maintainer' }, text: 'first' },
      { rev: 2, at: '2026-11-01T01:00:00Z', by: { name: 'session-lead' }, text: '' }] })
    const w = mount(ChatBoard, opts({ board: board() }))
    await w.find('[data-testid="ost-board-history"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-board-rev-2"]').text()).toContain('session-lead')
    expect(w.find('[data-testid="ost-board-rev-2"]').text()).toContain('(cleared)')
    expect(w.find('[data-testid="ost-board-rev-1"]').text()).toContain('first')
  })

  it('the owner names who keeps it: the members and the agents, the owner never among them', async () => {
    m.presence.mockResolvedValue({ agents: [{ did: 'did:x:LEAD', name: 'session-lead' }] })
    m.chat.roomMembers = vi.fn().mockResolvedValue({ members: [
      { ptype: 'developer', developer_id: 6, name: 'maintainer', org_role: 'owner' },
      { ptype: 'developer', developer_id: 7, name: 'a member', org_role: 'member' }] })
    m.chat.putBoardEditors = vi.fn().mockResolvedValue(board({ can_edit: true, editors: [{ key: 'agt:did:x:lead', name: 'session-lead' }] }))
    const w = mount(ChatBoard, opts({ board: board({ can_edit: true, editors: [] }) }))
    await w.find('[data-testid="ost-board-editors"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-board-cand-dev:6"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-board-cand-dev:7"]').exists()).toBe(true)
    await w.find('[data-testid="ost-board-cand-agt:did:x:lead"] input').setValue(true)
    await w.find('[data-testid="ost-board-editors-save"]').trigger('click')
    await flushPromises()
    expect(m.chat.putBoardEditors).toHaveBeenCalledWith('dev-tok', 'room1', ['agt:did:x:lead'])
  })

  it('above the history it starts folded to its first line; opened, it stays open for that person', async () => {
    const w = mount(ChatBoard, opts({ board: board(), strip: true }))
    const toggle = w.find('[data-testid="ost-board-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.text()).toContain('Release: V0651 at 05:00Z')                  // the first line, as plain text
    await toggle.trigger('click')
    expect(w.find('[data-testid="ost-board-toggle"]').attributes('aria-expanded')).toBe('true')
    w.unmount()
    const again = mount(ChatBoard, opts({ board: board(), strip: true }))
    expect(again.find('[data-testid="ost-board-toggle"]').attributes('aria-expanded')).toBe('true')
  })

  it('an empty board asks an editor to start it, and tells a member there is none', () => {
    const ed = mount(ChatBoard, opts({ board: board({ text: '', rev: 0, updated_by: null, can_edit: true }) }))
    expect(ed.find('[data-testid="ost-board-empty"]').text()).toContain('write what the room should see first')
    const mem = mount(ChatBoard, opts({ board: board({ text: '', rev: 0, updated_by: null }) }))
    expect(mem.find('[data-testid="ost-board-empty"]').text()).toBe('Nothing on the board yet.')
  })
})
