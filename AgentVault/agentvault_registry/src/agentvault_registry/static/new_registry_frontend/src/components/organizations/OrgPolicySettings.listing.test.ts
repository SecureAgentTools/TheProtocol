/**
 * V0658 (r), met on the way: the policy form turned a listed organization's listing OFF when its policy was saved for
 * another field. It read every stored value back as a string, and a switch sends `value === true`, so an untouched
 * switch that was on ('true') went out as false: saving a new contract expiry unlisted the organization, and its mark
 * left its agents' cards (here and on every peer), with nothing on screen to say why. The same string made a switch
 * that is off read "On". The form also tells the page when it saved, so the page's notice follows the listing.
 * RED on v0657/cut: the patch carries public_listing: false, an off switch reads On, and nothing is emitted.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ getOrgSettings: vi.fn(), updateOrgSettings: vi.fn() }))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: { getOrgSettings: h.getOrgSettings, updateOrgSettings: h.updateOrgSettings },
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }))

import OrgPolicySettings from './OrgPolicySettings.vue'

const catalog = [
  { key: 'public_listing', type: 'bool', label: 'List this organization publicly' },
  { key: 'public_transparency_opt_in', type: 'bool', label: 'Public work-record transparency' },
  { key: 'contract_offer_ttl_days', type: 'number', label: 'Contract offer expiry (days)', min: 1, max: 366 },
]
const registry = { liability_mode: 'off', presence_threshold_avt: 0 }

async function form(settings: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  h.getOrgSettings.mockResolvedValue({ org_id: 'org-1', settings, catalog, registry })
  const w = mount(OrgPolicySettings, { props: { orgId: 'org-1', canEdit: true, ...extra }, global: { stubs: { Icon: true } } })
  await flushPromises()
  return w
}
const stateOf = (w: Awaited<ReturnType<typeof form>>, key: string) =>
  w.find(`[data-testid="pol-bool-${key}"] .pol-bool-state`).text()

beforeEach(() => {
  h.getOrgSettings.mockReset()
  h.updateOrgSettings.mockReset()
  h.updateOrgSettings.mockImplementation(async (_id: string, patch: Record<string, unknown>) => ({ org_id: 'org-1', settings: patch }))
})

describe('the policy form keeps the listing as it is stored', () => {
  it('a listed organization stays listed when its policy is saved for another field', async () => {
    const w = await form({ public_listing: true, contract_offer_ttl_days: 30 })
    expect((w.find('#pol-public_listing').element as HTMLInputElement).checked).toBe(true)
    await w.find('#pol-contract_offer_ttl_days').setValue('45')
    await w.find('.pol-btn').trigger('click')
    await flushPromises()
    expect(h.updateOrgSettings).toHaveBeenCalledTimes(1)
    const [orgId, patch] = h.updateOrgSettings.mock.calls[0]
    expect(orgId).toBe('org-1')
    expect(patch.public_listing, 'the listing went out as it is stored').toBe(true)
    expect(patch.contract_offer_ttl_days).toBe(45)
    expect('public_transparency_opt_in' in patch, 'a switch never set is not written').toBe(false)
  })

  it('a switch that is off reads Off and stays off; one that is on reads On', async () => {
    const w = await form({ public_listing: false, public_transparency_opt_in: true })
    expect((w.find('#pol-public_listing').element as HTMLInputElement).checked).toBe(false)
    expect(stateOf(w, 'public_listing')).toBe('Off')
    expect(stateOf(w, 'public_transparency_opt_in')).toBe('On')
    await w.find('.pol-btn').trigger('click')
    await flushPromises()
    const [, patch] = h.updateOrgSettings.mock.calls[0]
    expect(patch.public_listing).toBe(false)
    expect(patch.public_transparency_opt_in).toBe(true)
  })

  it('a switch turned on by hand goes out on, and the page is told the form saved', async () => {
    const w = await form({})
    await w.find('#pol-public_listing').setValue(true)
    await w.find('.pol-btn').trigger('click')
    await flushPromises()
    expect(h.updateOrgSettings.mock.calls[0][1].public_listing).toBe(true)
    expect(w.emitted('saved'), 'the page re-reads the organization\'s public face').toEqual([[{ public_listing: true }]])
  })
})

// The review of V0658 (r): the page re-mounted this form to show a listing made from the notice above it, and a re-mount
// threw away whatever the person had typed and not saved. The form is told the listing instead: its switch follows it
// and nothing else in the form moves.
describe('a listing made elsewhere on the page shows in the switch, and the form keeps its unsaved edits', () => {
  it('the switch follows the page\'s listing; an unsaved expiry stays, and a save sends both', async () => {
    const w = await form({ public_listing: false, contract_offer_ttl_days: 30 }, { listed: false })
    await w.find('#pol-contract_offer_ttl_days').setValue('45')
    await w.setProps({ listed: true })
    expect((w.find('#pol-public_listing').element as HTMLInputElement).checked, 'the switch reads the listing').toBe(true)
    expect(stateOf(w, 'public_listing')).toBe('On')
    expect((w.find('#pol-contract_offer_ttl_days').element as HTMLInputElement).value, 'the unsaved edit stays').toBe('45')
    expect(h.getOrgSettings, 'nothing was read again').toHaveBeenCalledTimes(1)
    await w.find('.pol-btn').trigger('click')
    await flushPromises()
    const [, patch] = h.updateOrgSettings.mock.calls[0]
    expect(patch.public_listing, 'the listing goes out as it now is').toBe(true)
    expect(patch.contract_offer_ttl_days).toBe(45)
  })

  it('a listing that did not change leaves the form alone', async () => {
    const w = await form({ public_listing: true, contract_offer_ttl_days: 30 }, { listed: true })
    await w.find('#pol-contract_offer_ttl_days').setValue('60')
    await w.setProps({ listed: true, canEdit: true })
    expect((w.find('#pol-contract_offer_ttl_days').element as HTMLInputElement).value).toBe('60')
    expect((w.find('#pol-public_listing').element as HTMLInputElement).checked).toBe(true)
  })
})
