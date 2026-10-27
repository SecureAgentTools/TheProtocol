import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): Ledger Forensics' Open Findings inbox. Its service turned EVERY failed
 * findings read into `scanner_inactive: true`, so the inbox said "Scanner inactive … FORENSIC_SCANNER_ENABLED=false", a
 * claim about the frame's configuration the read never made (and the store's own catch never ran). Only a registry
 * without the route (404) has no scanner to ask now; any other failure says the read failed, with Try again. A filter
 * switched while a read is in flight takes the newest answer only, and an ack reads again under the filter on screen
 * (it read every finding, so the acked one stayed listed under Open).
 */
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post } }))

import FindingsTab from './FindingsTab.vue'

const opts = { global: { stubs: { Icon: true } } }
const failed = (status?: number) => Object.assign(new Error(status ? `Request failed with status code ${status}` : 'Network Error'),
  status ? { response: { status } } : {})
const finding = (key: string, status: string) => ({ finding_key: key, source: 'rails', severity: 'warn', title: `F ${key}`, status })

describe('the findings inbox says what its read answered', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.get.mockReset()
    h.post.mockReset()
  })

  for (const [what, err] of [['a 502', failed(502)], ['no answer', failed()], ['a 403', failed(403)]] as const) {
    it(`${what}: the read failed, not "Scanner inactive" and not "No open findings."`, async () => {
      h.get.mockRejectedValueOnce(err)
      const w = mount(FindingsTab, opts)
      await flushPromises()
      expect(w.text()).not.toContain('Scanner inactive')
      expect(w.text()).not.toContain('findings.')
      expect(w.find('[data-read-failed]').exists()).toBe(true)
      h.get.mockResolvedValueOnce({ data: { findings: [finding('a', 'open')], count: 1 } })
      await w.find('[data-testid="read-failed-retry"]').trigger('click')
      await flushPromises()
      expect(w.find('[data-read-failed]').exists()).toBe(false)
      expect(w.text()).toContain('F a')
      w.unmount()
    })
  }

  it('a registry without the route (404) still reads as an inactive scanner; an answered empty inbox says none', async () => {
    h.get.mockRejectedValueOnce(failed(404))
    const w = mount(FindingsTab, opts)
    await flushPromises()
    expect(w.text()).toContain('Scanner inactive')
    w.unmount()
    h.get.mockResolvedValueOnce({ data: { findings: [], count: 0 } })
    const w2 = mount(FindingsTab, opts)
    await flushPromises()
    expect(w2.text()).toContain('No open findings.')
    w2.unmount()
  })

  it('a late answer for a filter already left does not land; an ack reads again under the filter on screen', async () => {
    h.get.mockResolvedValueOnce({ data: { findings: [finding('o1', 'open')], count: 1 } })
    const w = mount(FindingsTab, opts)
    await flushPromises()
    let release: (v: unknown) => void = () => {}
    h.get.mockImplementationOnce(() => new Promise((res) => { release = res }))            // Acknowledged: held
    await w.findAll('button.lff-t').find((b) => b.text() === 'Acknowledged')!.trigger('click')
    h.get.mockResolvedValueOnce({ data: { findings: [finding('o1', 'open')], count: 1 } })  // Open: answers at once
    await w.findAll('button.lff-t').find((b) => b.text() === 'Open')!.trigger('click')
    await flushPromises()
    release({ data: { findings: [finding('k1', 'acked')], count: 1 } })                     // Acknowledged: late
    await flushPromises()
    expect(w.text()).toContain('F o1')
    expect(w.text()).not.toContain('F k1')
    h.post.mockResolvedValueOnce({})
    h.get.mockResolvedValueOnce({ data: { findings: [], count: 0 } })
    await w.find('button.lff-ack').trigger('click')
    await flushPromises()
    expect(h.get.mock.calls[h.get.mock.calls.length - 1]?.[1]).toEqual({ params: { status: 'open' } })
    w.unmount()
  })
})
