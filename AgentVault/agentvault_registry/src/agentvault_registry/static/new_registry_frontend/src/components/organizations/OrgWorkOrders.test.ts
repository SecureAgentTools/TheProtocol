/**
 * §FESUITE (V0577): an open work order's detail (its bids) that could not be read said "No open bids yet."; it now
 * says the read failed, and Try again reads it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  org: { listOrgWorkOrders: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  guild: { detail: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/organizationService', () => ({ organizationService: h.org }))
vi.mock('@/services/api/guild', () => ({ guildApi: h.guild }))

import OrgWorkOrders from './OrgWorkOrders.vue'

describe('an org work order whose detail could not be read', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.org.listOrgWorkOrders.mockResolvedValue({ orders: [{ id: 'o1', title: 'Index the ledger', status: 'open', bounty: '5', currency: 'ECU', bid_count: 2 }] })
  })

  it('says the read failed (not "No open bids yet."), and Try again reads it', async () => {
    h.guild.detail.mockRejectedValue(new Error('502'))
    const w = mount(OrgWorkOrders, { props: { orgId: 'org-1', canManage: true } })
    await flushPromises()
    await w.find('[data-testid="owo-row-o1"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="read-failed"]').exists(), 'the detail says its read failed').toBe(true)
    expect(w.text()).not.toContain('No open bids yet.')

    h.guild.detail.mockResolvedValue({ bids: [{ id: 'b1', status: 'open', bidder_did: 'did:theprotocol:x', price: '4' }] })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="read-failed"]').exists()).toBe(false)
    expect(w.find('[data-testid="owo-award-b1"]').exists(), 'the bid that was read is offered').toBe(true)
  })
})
