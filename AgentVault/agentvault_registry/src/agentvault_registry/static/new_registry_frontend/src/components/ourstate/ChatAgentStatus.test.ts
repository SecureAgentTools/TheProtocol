import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0662 (OurChat lane, the batch's item 11): the session board section. It draws what the registry reports per session (state, wake
 * mode, last wake, wakes in 24 hours), never guesses ("unknown" stays unknown and shows no count), reads again every minute, and is not
 * there at all for a viewer the registry refuses. BASE (f6a47e3c9): no component.
 */
const h = vi.hoisted(() => ({ status: (async (..._a: any[]) => ({ sessions: [] })) as any }))
vi.mock('@/services/api/chat', () => ({ chatApi: { agentStatus: (...a: any[]) => h.status(...a) } }))

import ChatAgentStatus from './ChatAgentStatus.vue'

const ago = (s: number) => new Date(Date.now() - s * 1000).toISOString()
const row = (key: string, over: Record<string, any> = {}) => ({ key, name: key.replace('agt:', ''), state: 'active', wake_mode: 'listen', wakes_24h: 12,
  last_wake_at: ago(180), reported_at: ago(20), age_s: 20, ...over })
const flush = async () => { for (let i = 0; i < 4; i++) await flushPromises() }
const board = (extra: Record<string, any> = {}) => mount(ChatAgentStatus, { props: { token: 'dev.tok', conversationId: 'room-a', ...extra } })

describe('the session board', () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] }) })
  afterEach(() => { vi.useRealTimers() })

  it('draws each session: state, wake mode, wakes in 24 h, last wake and how old the report is', async () => {
    h.status = vi.fn().mockResolvedValue({ sessions: [row('agt:session-lead'), row('agt:session-code', { state: 'paused', wake_mode: 'off', wakes_24h: 3, last_wake_at: null })] })
    const w = board()
    await flush()
    expect(h.status).toHaveBeenCalledWith('dev.tok', 'room-a')
    const lead = w.find('[data-testid="ost-agent-agt:session-lead"]')
    expect(lead.text()).toContain('active')
    expect(lead.text()).toContain('wake mode: listen')
    expect(lead.text()).toContain('12 wakes in 24 h')
    expect(lead.text()).toContain('last wake 3 min ago')
    expect(lead.text()).toContain('reported 20 s ago')
    const code = w.find('[data-testid="ost-agent-agt:session-code"]')
    expect(code.text()).toContain('paused')
    expect(code.text()).toContain('no wake yet')
  })
  it('an unknown session stays unknown: no mode, no count', async () => {
    h.status = vi.fn().mockResolvedValue({ sessions: [row('agt:old', { state: 'unknown', wake_mode: null, wakes_24h: null, age_s: 900 })] })
    const w = board()
    await flush()
    const r = w.find('[data-testid="ost-agent-agt:old"]')
    expect(r.text()).toContain('unknown')
    expect(r.text()).not.toContain('wakes in 24 h')
    expect(r.text()).not.toContain('wake mode')
    expect(r.text()).toContain('reported 15 min ago')
  })
  it('says so when the desk has not reported anything', async () => {
    h.status = vi.fn().mockResolvedValue({ sessions: [] })
    const w = board()
    await flush()
    expect(w.find('[data-testid="ost-agent-status-empty"]').exists()).toBe(true)
  })
  it('is not there for a viewer the registry refuses (never "nobody")', async () => {
    h.status = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { status: 403 }))
    const w = board()
    await flush()
    expect(w.find('[data-testid="ost-agent-status"]').exists()).toBe(false)
  })
  it('reads again every minute and follows the answer, and stops when it goes', async () => {
    h.status = vi.fn().mockResolvedValueOnce({ sessions: [row('agt:a', { wakes_24h: 1 })] }).mockResolvedValue({ sessions: [row('agt:a', { wakes_24h: 9 })] })
    const w = board()
    await flush()
    expect(w.text()).toContain('1 wakes in 24 h')
    await vi.advanceTimersByTimeAsync(60_000)
    await flush()
    expect(h.status).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('9 wakes in 24 h')
    w.unmount()
    await vi.advanceTimersByTimeAsync(120_000)
    expect(h.status).toHaveBeenCalledTimes(2)
  })
  it('an answer for a conversation no longer shown is dropped', async () => {
    let late: (v: any) => void = () => {}
    h.status = vi.fn().mockImplementationOnce(() => new Promise((res) => { late = res })).mockResolvedValue({ sessions: [] })
    const w = board()
    await w.setProps({ conversationId: 'room-b' })
    late({ sessions: [row('agt:old-room')] })
    await flush()
    expect(w.find('[data-testid="ost-agent-agt:old-room"]').exists()).toBe(false)
  })
})
