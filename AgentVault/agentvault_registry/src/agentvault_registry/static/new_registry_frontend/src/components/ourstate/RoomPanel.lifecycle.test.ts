import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0663 (order gwo_daf7fc3c8b3174f6f73c0d8a, session-tester's soak): archive, unarchive and close a room from its panel. The
 * room's operators on its host see them; an archived room says it can be read, not posted in, and offers Unarchive; a refusal
 * the registry sentences (a room with messages cannot be closed) shows as it is said; a close that goes through tells the thread.
 * The harness is RoomPanel.test.ts's.
 */
const m = vi.hoisted(() => ({ info: vi.fn(), act: vi.fn(), close: vi.fn() }))
vi.mock('@/services/api/chat', () => ({ chatApi: { roomInfo: m.info, roomAct: m.act, closeRoom: m.close } }))

import RoomPanel from './RoomPanel.vue'

const members = [{ key: 'dev:1', name: 'owner', remote: false, role: 'owner', state: 'active', can_post: true }]
const info = (over: Record<string, any> = {}) => ({ address: 'room:r1@https://a.example', join_rule: 'anyone', hosted_here: true,
  host_registry: null, i_moderate: true, my_role: 'owner', member_count: 1, members, archived: false, ...over })
const props = { token: 'dev-tok', conversationId: 'r1' }
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
async function opened(over: Record<string, any> = {}) {
  m.info.mockResolvedValue(info(over))
  const w = mount(RoomPanel, { props })
  await flushPromises()
  await tid(w, 'room-panel-toggle').trigger('click')
  return w
}

describe('a room panel: archive, unarchive and close', () => {
  beforeEach(() => { m.info.mockReset(); m.act.mockReset(); m.close.mockReset() })

  it('an operator on the host archives the room and the panel reads again', async () => {
    const w = await opened()
    m.act.mockResolvedValue({ ok: true, archived: true })
    expect(tid(w, 'room-archive').exists()).toBe(true)
    expect(tid(w, 'room-unarchive').exists()).toBe(false)
    expect(tid(w, 'room-archived-note').exists()).toBe(false)
    await tid(w, 'room-archive').trigger('click')
    await flushPromises()
    expect(m.act).toHaveBeenCalledWith('dev-tok', 'r1', { action: 'archive', member: undefined, value: undefined })
    expect(m.info).toHaveBeenCalledTimes(2)
    expect(w.emitted('acted')![0]).toEqual(['archive'])
  })

  it('an archived room says it can be read, not posted in, and offers Unarchive instead', async () => {
    const w = await opened({ archived: true })
    expect(tid(w, 'room-archived-note').text()).toContain('read, not posted in')
    expect(tid(w, 'room-archive').exists()).toBe(false)
    m.act.mockResolvedValue({ ok: true, archived: false })
    await tid(w, 'room-unarchive').trigger('click')
    await flushPromises()
    expect(m.act).toHaveBeenCalledWith('dev-tok', 'r1', { action: 'unarchive', member: undefined, value: undefined })
  })

  it('a close that goes through tells the thread; one the registry refuses shows its sentence and tells nobody', async () => {
    const w = await opened()
    m.close.mockRejectedValueOnce(Object.assign(new Error('x'), { detail: 'This room has messages: archive it instead, which keeps its history' }))
    await tid(w, 'room-close').trigger('click')
    await flushPromises()
    expect(tid(w, 'room-error').text()).toContain('archive it instead')
    expect(w.emitted('closed')).toBeUndefined()
    m.close.mockResolvedValueOnce({ ok: true, closed: 'r1' })
    await tid(w, 'room-close').trigger('click')
    await flushPromises()
    expect(m.close).toHaveBeenCalledWith('dev-tok', 'r1')
    expect(w.emitted('closed')).toHaveLength(1)
  })

  it('shows none of it to a member, or on a copy hosted elsewhere', async () => {
    const w1 = await opened({ i_moderate: false, my_role: 'member' })
    expect(tid(w1, 'room-lifecycle').exists()).toBe(false)
    const w2 = await opened({ hosted_here: false, host_registry: 'https://b.example' })
    expect(tid(w2, 'room-lifecycle').exists()).toBe(false)
  })
})
