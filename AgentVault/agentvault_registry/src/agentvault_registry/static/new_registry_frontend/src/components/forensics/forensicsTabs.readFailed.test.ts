import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): three Ledger Forensics tabs over a read that failed.
 *  - Trace: "No events for <anchor> on <frame>." (an investigator reads "this transaction left no trace");
 *  - Emission policies: "No policies match." under chips counting 0, "⚠ Violations 0" among them, and "0 of 0 policies";
 *  - Query: the prompt "Pick a window + filters, then Search." came back, nothing said.
 * Each says its read failed now, with Try again; answered empties still say none (the controls).
 */
const h = vi.hoisted(() => ({ frameGet: vi.fn(), get: vi.fn() }))
vi.mock('@/composables/useAdminFrames', () => ({
  useAdminFrames: () => ({ frameGet: h.frameGet, resolveOption: () => ({ label: 'EU', frameParam: 'local' }) }),
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn(), put: vi.fn() } }))

import TraceTab from './TraceTab.vue'
import PolicyTab from './PolicyTab.vue'
import QueryTab from './QueryTab.vue'

const opts = { props: { frame: 'local' as any }, global: { stubs: { Icon: true, JsonViewer: true, RouterLink: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

describe('the forensics tabs say a failed read failed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.frameGet.mockReset()
    h.get.mockReset()
  })

  it('Trace: a failed txid trace is not "No events for …"; Try again traces it again', async () => {
    h.frameGet.mockRejectedValueOnce(failure())
    const w = mount(TraceTab, opts)
    await w.find('input').setValue('tx-123')
    const sel = w.find('select')
    if (sel.exists()) await sel.setValue('txid')
    await w.find('button.lft-btn').trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('No events for')
    expect(w.find('[data-read-failed]').exists()).toBe(true)
    h.frameGet.mockResolvedValueOnce({ events: [], count: 0 })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.text()).toContain('No events for')
    w.unmount()
  })

  it('Emission policies: no "No policies match." and no counted chips over a failed read', async () => {
    h.get.mockRejectedValueOnce(failure())
    const w = mount(PolicyTab, opts)
    await flushPromises()
    expect(w.text()).not.toContain('No policies match.')
    expect(w.findAll('.lfp-chip-n').map((c) => c.text())).toEqual(['—', '—', '—', '—', '—'])
    expect(w.text()).toContain('— of — policies')
    expect(w.find('[data-read-failed]').exists()).toBe(true)
    w.unmount()
  })

  it('Emission policies: an answered empty table still says none, and counts 0', async () => {
    h.get.mockResolvedValueOnce({ data: [] })
    const w = mount(PolicyTab, opts)
    await flushPromises()
    expect(w.text()).toContain('No policies match.')
    expect(w.findAll('.lfp-chip-n').map((c) => c.text())).toEqual(['0', '0', '0', '0', '0'])
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })

  it('Query: a failed search says so (it put the "Pick a window" prompt back); an answered empty one says none', async () => {
    h.frameGet.mockRejectedValueOnce(failure())
    const w = mount(QueryTab, opts)
    await w.find('button.lfq-btn').trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('Pick a window + filters, then Search.')
    expect(w.find('[data-read-failed]').exists()).toBe(true)
    h.frameGet.mockResolvedValueOnce({ events: [], count: 0 })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(w.text()).toContain('No events match in this window.')
    w.unmount()
  })
})
