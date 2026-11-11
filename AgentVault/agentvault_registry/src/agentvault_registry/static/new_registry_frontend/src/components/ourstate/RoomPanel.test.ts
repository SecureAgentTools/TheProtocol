import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0659 (f): a cross-frame room's panel, at the top of its thread. Folded: the member count, the join rule and, on a
 * copy, where the room is hosted. Open: the address to share, the members, and for an operator on the HOST one menu
 * per member (never on the owner); a copy on another registry shows and never moderates. A failed read says so and
 * offers it again. BASE (V0657's cut): the component does not exist.
 */
const m = vi.hoisted(() => ({ info: vi.fn(), act: vi.fn() }))
vi.mock('@/services/api/chat', () => ({ chatApi: { roomInfo: m.info, roomAct: m.act } }))

import RoomPanel from './RoomPanel.vue'

const ADDR = 'room:r1@https://a.example'
const members = [
  { key: 'dev:1', name: 'owner', remote: false, role: 'owner', state: 'active', can_post: true },
  { key: 'dev:5@https://b.example', name: 'outsider', remote: true, role: 'member', state: 'active', can_post: true },
  { key: 'dev:6@https://b.example', name: 'asker', remote: true, role: 'member', state: 'pending', can_post: true },
]
const hostInfo = { address: ADDR, join_rule: 'request', hosted_here: true, host_registry: null, i_moderate: true,
                   my_role: 'owner', member_count: 2, members }
const props = { token: 'dev-tok', conversationId: 'r1' }

describe('a cross-frame room panel', () => {
  beforeEach(() => { m.info.mockReset(); m.act.mockReset() })

  it('folded: the member count and the rule; open: the address and the members', async () => {
    m.info.mockResolvedValue(hostInfo)
    const w = mount(RoomPanel, { props })
    await flushPromises()
    expect(m.info).toHaveBeenCalledWith('dev-tok', 'r1')
    expect(w.find('[data-testid="room-member-count"]').text()).toContain('2')
    expect(w.find('[data-testid="room-rule"]').text()).toContain('asks')
    expect(w.find('[data-testid="room-address"]').exists()).toBe(false)
    await w.find('[data-testid="room-panel-toggle"]').trigger('click')
    expect(w.find('[data-testid="room-address"]').text()).toBe(ADDR)
    expect(w.findAll('[data-testid="room-members"] li')).toHaveLength(3)
  })

  it('the host operator acts on a member, never on the owner, and the list reads again', async () => {
    m.info.mockResolvedValue(hostInfo)
    m.act.mockResolvedValue({ ok: true })
    const w = mount(RoomPanel, { props })
    await flushPromises()
    await w.find('[data-testid="room-panel-toggle"]').trigger('click')
    const owner = w.find('[data-key="dev:1"]')
    expect(owner.findAll('button')).toHaveLength(0)
    const asker = w.find('[data-key="dev:6@https://b.example"]')
    expect(asker.text()).toContain('asks to join')
    await asker.find('[data-testid="room-act-accept"]').trigger('click')
    await flushPromises()
    expect(m.act).toHaveBeenCalledWith('dev-tok', 'r1', { action: 'accept', member: 'dev:6@https://b.example', value: undefined })
    expect(m.info).toHaveBeenCalledTimes(2)
    expect(w.emitted('acted')?.[0]).toEqual(['accept'])
  })

  it('a copy on another registry names its host and offers no menu', async () => {
    m.info.mockResolvedValue({ ...hostInfo, hosted_here: false, host_registry: 'https://a.example', i_moderate: false,
                               my_role: 'member', members: members.slice(0, 2) })
    const w = mount(RoomPanel, { props })
    await flushPromises()
    expect(w.find('[data-testid="room-hosted-elsewhere"]').text()).toContain('a.example')
    await w.find('[data-testid="room-panel-toggle"]').trigger('click')
    expect(w.find('[data-testid="room-rule-select"]').exists()).toBe(false)
    expect(w.findAll('[data-testid^="room-act-"]')).toHaveLength(0)
  })

  it('a refused act shows the server sentence and keeps the list', async () => {
    m.info.mockResolvedValue(hostInfo)
    m.act.mockRejectedValue({ detail: 'only the owner names a moderator' })
    const w = mount(RoomPanel, { props })
    await flushPromises()
    await w.find('[data-testid="room-panel-toggle"]').trigger('click')
    await w.find('[data-key="dev:5@https://b.example"] [data-testid="room-act-mute"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="room-error"]').text()).toBe('only the owner names a moderator')
    expect(w.findAll('[data-testid="room-members"] li')).toHaveLength(3)
  })

  it('a failed read says so and offers it again', async () => {
    m.info.mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce(hostInfo)
    const w = mount(RoomPanel, { props })
    await flushPromises()
    expect(w.find('[data-testid="room-member-count"]').exists()).toBe(false)
    expect(w.text().length).toBeGreaterThan(0)
    await (w.vm as any).load()
    await flushPromises()
    expect(w.find('[data-testid="room-member-count"]').exists()).toBe(true)
  })
})
