import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): the AGORA desk's fundamentals said what the server never did. A failed distributions read said
 * "No distributions declared yet."; a failed membership read, or a treasury read that got no answer, said the treasury is
 * "visible to organization members" (to a member too). Each says its read failed now; a 403 is still the boundary.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), listOrganizations: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get } }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { listOrganizations: h.listOrganizations } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 } }) }))

import FundamentalsPanel from './FundamentalsPanel.vue'

const refused = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })
const TRACK = { name: 'Firm', verified_jobs: 3, commissioned: { orders: 1 }, stars_n: 0 }
const sel = (id: string) => `[data-testid="${id}"]`

function answer(over: { track?: unknown; divs?: unknown; treasury?: unknown } = {}) {
  h.get.mockImplementation(async (url: string) => {
    const pick = url.includes('/track-record') ? over.track : url.includes('/distributions') ? over.divs : over.treasury
    if (pick instanceof Error) throw pick
    return { data: pick }
  })
}
const mountIt = () => mount(FundamentalsPanel, { props: { listingRef: 'FIRM', organizationId: 'org-1', currency: 'ECU' } })

beforeEach(() => { h.get.mockReset(); h.listOrganizations.mockReset() })

describe('the fundamentals panel', () => {
  it('a failed distributions read is a failed read, never "No distributions declared yet."', async () => {
    answer({ track: TRACK, divs: refused(502), treasury: { totals: { balance: '12' } } })
    h.listOrganizations.mockResolvedValue([{ id: 'org-1' }])
    const w = mountIt(); await flushPromises()
    expect(w.find(sel('fp-divs-none')).exists()).toBe(false)
    expect(w.find(sel('fp-dividends')).find(sel('read-failed')).exists()).toBe(true)
    expect(w.text()).toContain('12 ECU')
  })

  it('a treasury read that got no answer is a failed read, never "members only"', async () => {
    answer({ track: TRACK, divs: { dividends: [] }, treasury: refused(502) })
    h.listOrganizations.mockResolvedValue([{ id: 'org-1' }])
    const w = mountIt(); await flushPromises()
    expect(w.find(sel('fp-treasury-gated')).exists()).toBe(false)
    expect(w.find(sel('fp-treasury')).find(sel('read-failed')).exists()).toBe(true)
  })

  it('a failed membership read is a failed read, never "members only"', async () => {
    answer({ track: TRACK, divs: { dividends: [] }, treasury: { totals: { balance: '12' } } })
    h.listOrganizations.mockRejectedValue(new Error('Failed to list organizations'))
    const w = mountIt(); await flushPromises()
    expect(w.find(sel('fp-treasury-gated')).exists()).toBe(false)
    expect(w.find(sel('fp-treasury')).find(sel('read-failed')).exists()).toBe(true)
  })

  it('a 403 is still the members-only boundary', async () => {
    answer({ track: TRACK, divs: { dividends: [] }, treasury: refused(403) })
    h.listOrganizations.mockResolvedValue([{ id: 'org-1' }])
    const w = mountIt(); await flushPromises()
    expect(w.find(sel('fp-treasury-gated')).exists()).toBe(true)
    expect(w.find(sel('read-failed')).exists()).toBe(false)
  })

  it('a failed track-record read says so in the firm section', async () => {
    answer({ track: refused(502), divs: { dividends: [] }, treasury: { totals: { balance: '1' } } })
    h.listOrganizations.mockResolvedValue([{ id: 'org-1' }])
    const w = mountIt(); await flushPromises()
    expect(w.find(sel('fp-track-failed')).find(sel('read-failed')).exists()).toBe(true)
  })
})
