/**
 * §COCKPITDESK (2026-10-15) — the board's "needs a look" line: panes report what waits, the line lists the waiting first,
 * a count of nothing takes an entry back, a pane that leaves takes its entry with it, and pressing an entry gives that
 * pane the board.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reportAttention, clearAttention, attentionList } from '@/services/cockpit/attention'
import DeskAttention from './DeskAttention.vue'

afterEach(() => { for (const a of [...attentionList.value]) clearAttention(a.id) })

describe('the attention list', () => {
  it('lists what waits on someone before what is only worth knowing, and drops a count of nothing', () => {
    reportAttention('senate', 2, '2 votes close within a day', 'info')
    reportAttention('webhooks', 3, '3 webhooks failing')
    reportAttention('settlements', 0, '0 settlements wait')
    expect(attentionList.value.map(a => a.id)).toEqual(['webhooks', 'senate'])
    reportAttention('webhooks', 0, '0 webhooks failing')
    expect(attentionList.value.map(a => a.id)).toEqual(['senate'])
    clearAttention('senate')
    expect(attentionList.value).toEqual([])
  })
})

describe('the line above the board', () => {
  it('says nothing when nothing waits, and gives a pane the board on a press', async () => {
    const arrange = { maxId: null as string | null, toggleMax: vi.fn(function (this: any, id: string) { arrange.maxId = arrange.maxId === id ? null : id }) }
    const w = mount(DeskAttention, { props: { arrange: arrange as any } })
    expect(w.find('[data-testid="ckd-attention"]').exists()).toBe(false)
    reportAttention('webhooks', 1, '1 webhooks failing'); await flushPromises()
    const chip = w.find('[data-attn="webhooks"]')
    expect(chip.text()).toBe('1 webhooks failing')
    await chip.trigger('click')
    expect(arrange.toggleMax).toHaveBeenCalledWith('webhooks')
    await chip.trigger('click')
    expect(arrange.toggleMax, 'a second press does not take the board back: Escape does').toHaveBeenCalledTimes(1)
  })
})
