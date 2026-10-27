/**
 * §COCKPITDESK (2026-10-15) — the Disputes list holds every dispute the tiles count and shows twenty cards at a time
 * (a hundred made a 21,000 px page on a phone): "Show N more" until the end, the note above counts what is shown, and a
 * new filter starts at the top again.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ readAll: vi.fn() }))
vi.mock('@/services/api/disputes', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  disputesApi: { readAll: h.readAll },
}))
vi.mock('@/composables/useCurrency', async () => {
  const { ref } = await import('vue')
  return { useCurrency: () => ({ localCurrency: ref('ECU') }) }
})
// the page reads its disputes once an agent is known (with none it asks nothing)
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:a' }, isAuthenticated: true,
  user: { id: 1 } }) }))

import Disputes from './Disputes.vue'
import { useDisputesStore } from '@/stores/disputes'

const stubs = { Icon: true, DisputeTimeline: true, DisputeAnalytics: true, FileDisputeModal: true, ReadFailedNotice: true,
  teleport: true }
const at = (i: number) => new Date(Date.UTC(2026, 9, 14, 12, 0, 0) - i * 60_000).toISOString()
const rows = (n: number) => Array.from({ length: n }, (_, i) => ({
  id: String(n - i), status: 'open', reason: 'quality', description: `dispute ${n - i}`, created_at: at(i),
  claimant_did: 'did:theprotocol:a', respondent_did: 'did:theprotocol:b', evidence: [],
}))
const stats = (n: number) => ({ total_disputes: n, open_disputes: n, resolved_disputes: 0, resolution_rate: 0,
  average_resolution_time: 0, capped: false })
const cards = (w: ReturnType<typeof mount>) => w.findAll('.drc-card')

describe('the Disputes list, twenty at a time', () => {
  beforeEach(() => { setActivePinia(createPinia()); h.readAll.mockReset() })

  it('shows twenty, then twenty more, then the rest; the note counts what is shown', async () => {
    h.readAll.mockResolvedValue({ rows: rows(45), stats: stats(45) })
    const w = mount(Disputes, { global: { stubs } })
    await flushPromises()
    expect(cards(w)).toHaveLength(20)
    expect(cards(w)[0].text()).toContain('#45')                 // newest first
    expect(w.find('[data-testid="dsp-list-note"]').text()).toContain('20 of 45')
    const more = () => w.find('[data-testid="dsp-show-more"]')
    expect(more().text()).toContain('20')
    await more().trigger('click')
    expect(cards(w)).toHaveLength(40)
    expect(more().text()).toContain('5')
    await more().trigger('click')
    expect(cards(w)).toHaveLength(45)
    expect(more().exists(), 'nothing more to show').toBe(false)
    expect(w.find('[data-testid="dsp-list-note"]').exists(), 'every dispute is on screen').toBe(false)
    w.unmount()
  })

  it('a new filter starts at the top again', async () => {
    h.readAll.mockResolvedValue({ rows: rows(45), stats: stats(45) })
    const w = mount(Disputes, { global: { stubs } })
    await flushPromises()
    await w.find('[data-testid="dsp-show-more"]').trigger('click')
    expect(cards(w)).toHaveLength(40)
    useDisputesStore().setStatusFilter('open')
    await nextTick()
    expect(cards(w)).toHaveLength(20)
    w.unmount()
  })

  it('a short list shows whole, with no note and no button', async () => {
    h.readAll.mockResolvedValue({ rows: rows(7), stats: stats(7) })
    const w = mount(Disputes, { global: { stubs } })
    await flushPromises()
    expect(cards(w)).toHaveLength(7)
    expect(w.find('[data-testid="dsp-show-more"]').exists()).toBe(false)
    expect(w.find('[data-testid="dsp-list-note"]').exists()).toBe(false)
    w.unmount()
  })
})
