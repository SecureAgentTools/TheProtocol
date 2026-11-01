import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0652 (aa) (order gwo_840aa2b590306f7eba147758): a card's history, oldest first: when it was posted, then each update
 * (who, when, what changed: a state, a step added or dropped). A card that never changed says so; a failed read says so
 * and offers it again, never an empty history. BASE (V0651): the component does not exist.
 */
const m = vi.hoisted(() => ({ history: vi.fn() }))
vi.mock('@/services/api/chat', () => ({ chatApi: { cardHistory: m.history } }))

import ChatCardHistory from './ChatCardHistory.vue'

const props = { token: 'dev-tok', conversationId: 'room1', messageId: 'm7', title: 'V0651 pair proof' }

describe('the history of a card', () => {
  beforeEach(() => { m.history.mockReset() })

  it('posted, then each update: who, when and what changed', async () => {
    m.history.mockResolvedValue({ card_rev: 2, posted_at: '2026-11-01T00:00:00Z', updates: [
      { rev: 1, at: '2026-11-01T00:10:00Z', by: { ptype: 'agent', id: 'did:x:t', name: 'session-tester' },
        changes: [{ path: 'step console', from: 'running', to: 'done' }, { path: 'step pair', from: null, to: 'running' }] },
      { rev: 2, at: '2026-11-01T00:40:00Z', by: { ptype: 'agent', id: 'did:x:t', name: 'session-tester' },
        changes: [{ path: 'state', from: 'running', to: 'passed' }, { path: 'step lint', from: 'pending', to: null }] },
    ] })
    const w = mount(ChatCardHistory, { props })
    await flushPromises()
    expect(m.history).toHaveBeenCalledWith('dev-tok', 'room1', 'm7')
    expect(w.find('[data-testid="cch-posted"]').exists()).toBe(true)
    const r1 = w.find('[data-testid="cch-rev-1"]').text()
    expect(r1).toContain('session-tester')
    expect(r1).toContain('step console: running → done')
    expect(r1).toContain('step pair: running (new)')
    const r2 = w.find('[data-testid="cch-rev-2"]').text()
    expect(r2).toContain('state: running → passed')
    expect(r2).toContain('step lint: removed')
    await w.find('[data-testid="cch-close"]').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('a card that never changed says so', async () => {
    m.history.mockResolvedValue({ card_rev: 0, posted_at: '2026-11-01T00:00:00Z', updates: [] })
    const w = mount(ChatCardHistory, { props })
    await flushPromises()
    expect(w.find('[data-testid="cch-none"]').exists()).toBe(true)
  })

  it('a failed read says so and offers it again', async () => {
    m.history.mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce({ card_rev: 0, posted_at: null, updates: [] })
    const w = mount(ChatCardHistory, { props })
    await flushPromises()
    expect(w.find('[data-testid="cch-failed"]').exists()).toBe(true)
    expect(w.find('[data-testid="cch-none"]').exists()).toBe(false)
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="cch-failed"]').exists()).toBe(false)
    expect(w.find('[data-testid="cch-none"]').exists()).toBe(true)
  })
})
