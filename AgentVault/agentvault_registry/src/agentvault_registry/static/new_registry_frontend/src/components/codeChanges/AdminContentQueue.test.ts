/**
 * V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the content changes in the platform's Contributions inbox: every organization's, newest first, filtered by state and kind, our checker's record and the applied
 * before and after on each, and the platform's undo of an applied one.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ items: [] as any[], list: vi.fn(), undo: vi.fn() }))
vi.mock('@/services/api/contentChanges', async () => ({
  ...(await vi.importActual<any>('@/services/api/contentChanges')),
  adminListContentChanges: (...a: any[]) => h.list(...a),
  undoContentChange: (...a: any[]) => h.undo(...a),
}))

import Queue from './AdminContentQueue.vue'

const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const ROW = (over: any = {}) => ({ id: 'ct_1', kind: 'branding', target: 'branding', title: 'New look', state: 'applied', content: { tagline: 'Hi' }, checker: { ok: true, rules: ['schema'], bytes: 9 },
  code_distribution: { release_name: 'V0666_lyceum' }, before: { value: null }, after: { value: { tagline: 'Hi' } }, can_undo: true, ballot: { result: { status: 'PASSED' } }, ...over })
const mountIt = async () => { const w = mount(Queue); await flushPromises(); return w }

beforeEach(() => { h.list.mockReset(); h.undo.mockReset(); h.list.mockResolvedValue([ROW()]) })

describe('the content queue of the inbox', () => {
  it('lists every organization\'s change with its release, checker record and applied before and after', async () => {
    const w = await mountIt()
    expect(tid(w, 'acq-ct_1').text()).toContain('V0666_lyceum'); expect(tid(w, 'acq-ct_1').text()).toContain('New look')
    expect(tid(w, 'acq-checker').text()).toBe('Our checker passed it: schema (9 bytes).')
    expect(tid(w, 'acq-diff').exists()).toBe(true)
  })
  it('asks the registry for the state and kind chosen, and says so when none is there', async () => {
    const w = await mountIt()
    h.list.mockResolvedValue([])
    await tid(w, 'acq-f-state').setValue('failed'); await tid(w, 'acq-f-kind').setValue('kit'); await flushPromises()
    expect(h.list).toHaveBeenLastCalledWith({ state: 'failed', kind: 'kit' })
    expect(tid(w, 'acq-none').exists()).toBe(true)
  })
  it('undoes an applied change and shows the registry\'s sentence when it refuses', async () => {
    h.undo.mockRejectedValue({ response: { data: { detail: 'the content has been changed by something else since this change: it is not overwritten' } } })
    const w = await mountIt()
    await tid(w, 'acq-undo').trigger('click'); await flushPromises()
    expect(h.undo).toHaveBeenCalledWith('ct_1', '')
    expect(w.text()).toContain('it is not overwritten')
  })
  it('says so when the queue cannot be read', async () => {
    h.list.mockRejectedValue(new Error('down'))
    expect(tid(await mountIt(), 'acq-error').exists()).toBe(true)
  })
  it('V0667 D7: a compliance pack says it is a declaration no rail enforces', async () => {
    h.list.mockResolvedValue([ROW({ id: 'ct_p', kind: 'compliance_pack', target: 'eu-retention', content: { rules: { reporting: { interval_days: 90 } } } })])
    const w = await mountIt()
    expect(tid(w, 'acq-pack-note').text()).toBe('A pack records the organization’s own policy values: stored, voted on and carried in the signed report. No rail enforces it in this release.')
  })
})
