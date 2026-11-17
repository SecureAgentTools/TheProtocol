import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatMentionsList from './ChatMentionsList.vue'

/** V0663 (order 418) and V0664 (his report, seq 4032): the side panel's Mentions section. The UNREAD mentions of you, newest first; the read ones
 *  fold under "Earlier mentions (N)", closed; "Mark all read" moves the room's read mark; a preview draws the way the thread draws the line. */
const row = (seq: number, over: Record<string, any> = {}) => ({ id: `m${seq}`, seq, body: `line ${seq}`, sender_name: 'Mira', created_at: '2026-11-13T10:00:00Z', ...over })
const mountList = (props: Record<string, any>) => mount(ChatMentionsList, { props: props as any, global: { stubs: { Icon: true } } })
const ids = (w: any, scope = '') => w.findAll(`${scope} [data-testid^="cml-row-"]`).map((r: any) => r.attributes('data-testid'))

describe('ChatMentionsList', () => {
  it('shows the unread mentions, newest first, and a jump emits its line; the read ones are not in the list', async () => {
    const w = mountList({ rows: [row(2), row(5), row(9), row(11)], readFloor: 4, seen: new Set([11]) })
    expect(ids(w, '[data-testid="cml-unread-list"]')).toEqual(['cml-row-9', 'cml-row-5'])      // 11 was seen, 2 is read
    await w.find('[data-testid="cml-jump-5"]').trigger('click')
    expect((w.emitted('jump') as any[][])[0][0]).toMatchObject({ id: 'm5', seq: 5 })
  })

  it('folds the read ones under "Earlier mentions (N)", closed by default, newest first', () => {
    const w = mountList({ rows: [row(2), row(3), row(9)], readFloor: 4 })
    const d = w.find('[data-testid="cml-earlier"]')
    expect(d.exists()).toBe(true)
    expect(d.attributes('open')).toBeUndefined()
    expect(w.find('[data-testid="cml-earlier-sum"]').text()).toBe('Earlier mentions (2)')
    expect(ids(w, '[data-testid="cml-earlier"]')).toEqual(['cml-row-3', 'cml-row-2'])
  })

  it('"Mark all read" asks the thread to move the read mark (once), and waits while it does', async () => {
    const w = mountList({ rows: [row(5), row(9)], readFloor: 4 })
    await w.find('[data-testid="cml-markall"]').trigger('click')
    expect(w.emitted('markAllRead')).toHaveLength(1)
    await w.setProps({ busy: true })
    expect(w.find('[data-testid="cml-markall"]').attributes('disabled')).toBeDefined()
  })

  it('has nothing to mark when nothing is unread, and says so while the earlier ones stay one press away', () => {
    const w = mountList({ rows: [row(2), row(3)], readFloor: 9 })
    expect(w.find('[data-testid="cml-markall"]').exists()).toBe(false)
    expect(w.find('[data-testid="cml-allread"]').exists()).toBe(true)
    expect(w.find('[data-testid="cml-earlier-sum"]').text()).toBe('Earlier mentions (2)')
  })

  it('says so when nobody has mentioned you, and when the read failed', () => {
    expect(mountList({ rows: [] }).find('[data-testid="cml-none"]').exists()).toBe(true)
    const failed = mountList({ rows: [], failed: true })
    expect(failed.find('[data-testid="cml-failed"]').exists()).toBe(true)
    expect(failed.find('[data-testid="cml-none"]').exists()).toBe(false)       // never "nobody" over a failed read
  })

  it('draws a preview the way the thread does: the mention in the mention colour (the viewer\'s own marked), the sender named, the time on the right', () => {
    const r = row(5, { body: 'Please look, @Commander and @Mira', mentions: [{ key: 'dev:6', token: 'Commander' }, { key: 'dev:7', token: 'Mira' }] })
    const w = mountList({ rows: [r], readFloor: 0, myKey: 'dev:6' })
    const ats = w.findAll('[data-testid="cml-row-5"] .cm-mention')
    expect(ats.map((a) => a.text())).toEqual(['@Commander', '@Mira'])
    expect(ats[0].classes()).toContain('cm-me')
    expect(ats[1].classes()).not.toContain('cm-me')
    expect(w.find('[data-testid="cml-row-5"] .cml-who').text()).toBe('Mira')
    expect(w.find('[data-testid="cml-row-5"] time').exists()).toBe(true)
  })

  it('keeps a long history to the newest in each part', () => {
    const rows = Array.from({ length: 40 }, (_, i) => row(i + 1))
    const w = mountList({ rows, readFloor: 20, max: 10 })
    expect(ids(w, '[data-testid="cml-unread-list"]')).toHaveLength(10)
    expect(ids(w, '[data-testid="cml-earlier"]')).toHaveLength(10)
    expect(w.find('[data-testid="cml-earlier-sum"]').text()).toBe('Earlier mentions (20)')       // the count is the whole, the list the newest
  })
})
