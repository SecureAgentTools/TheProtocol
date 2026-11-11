import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0659 (f): the chat list's doors to cross-frame rooms. "Open a room" makes one with its join rule and opens it;
 * "Join a room" takes an address, here or on another registry: an active seat opens the room, a pending one says the
 * operators decide. A ?join= link fills the address in and waits for the press: a link never joins anyone on its own.
 * BASE (V0657's cut): the component does not exist.
 */
const m = vi.hoisted(() => ({ create: vi.fn(), join: vi.fn() }))
vi.mock('@/services/api/chat', () => ({ chatApi: { createRoom: m.create, joinRoom: m.join } }))

import RoomDoors from './RoomDoors.vue'

const ADDR = 'room:r1@https://a.example'

describe('the room doors', () => {
  beforeEach(() => { m.create.mockReset(); m.join.mockReset() })

  it('open a room: a title and a rule, then the room opens', async () => {
    m.create.mockResolvedValue({ conversation_id: 'r9', address: 'room:r9@https://b.example' })
    const w = mount(RoomDoors, { props: { token: 't' } })
    await w.find('[data-testid="room-open-door"]').trigger('click')
    expect((w.find('[data-testid="room-open-go"]').element as HTMLButtonElement).disabled).toBe(true)
    await w.find('[data-testid="room-title"]').setValue('  Night shift  ')
    await w.find('[data-testid="room-rule"]').setValue('anyone')
    await w.find('[data-testid="room-open-form"]').trigger('submit')
    await flushPromises()
    expect(m.create).toHaveBeenCalledWith('t', { title: 'Night shift', join_rule: 'anyone' })
    expect(w.emitted('opened')?.[0]).toEqual(['r9'])
  })

  it('join: only an address passes, and an active seat opens the room', async () => {
    m.join.mockResolvedValue({ conversation_id: 'mirror1', state: 'active', local: false })
    const w = mount(RoomDoors, { props: { token: 't' } })
    await w.find('[data-testid="room-join-door"]').trigger('click')
    await w.find('[data-testid="room-address-in"]').setValue('dm:x@https://a.example')
    expect((w.find('[data-testid="room-join-go"]').element as HTMLButtonElement).disabled).toBe(true)
    await w.find('[data-testid="room-address-in"]').setValue(ADDR)
    await w.find('[data-testid="room-join-form"]').trigger('submit')
    await flushPromises()
    expect(m.join).toHaveBeenCalledWith('t', ADDR)
    expect(w.emitted('opened')?.[0]).toEqual(['mirror1'])
  })

  it('a pending seat says the operators decide and opens nothing', async () => {
    m.join.mockResolvedValue({ conversation_id: 'mirror2', state: 'pending', local: false })
    const w = mount(RoomDoors, { props: { token: 't', joinAddress: ADDR } })
    await w.find('[data-testid="room-join-form"]').trigger('submit')
    await flushPromises()
    expect(w.find('[data-testid="room-note"]').text()).toContain('operators decide')
    expect(w.emitted('opened')).toBeUndefined()
  })

  it('a link fills the address in and joins nobody until the press', async () => {
    const w = mount(RoomDoors, { props: { token: 't', joinAddress: ADDR } })
    await flushPromises()
    expect((w.find('[data-testid="room-address-in"]').element as HTMLInputElement).value).toBe(ADDR)
    expect(m.join).not.toHaveBeenCalled()
  })

  it('a refused join shows the host\'s sentence', async () => {
    m.join.mockRejectedValue({ detail: "this room's operators removed you for good" })
    const w = mount(RoomDoors, { props: { token: 't', joinAddress: ADDR } })
    await w.find('[data-testid="room-join-form"]').trigger('submit')
    await flushPromises()
    expect(w.find('[data-testid="room-door-error"]').text()).toContain('removed you for good')
    expect(w.emitted('opened')).toBeUndefined()
  })
})
