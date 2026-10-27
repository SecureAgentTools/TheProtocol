/**
 * §FESUITE (V0578): a template's detail drawer reads the template (GET /contracts/templates/{id}) for its versions; a
 * failed read fell back to the list row, which carries no versions, so the Versions table read empty: a template with
 * published versions drawn as one without (and after a new version or a publish whose re-read failed, the version just
 * made was not there). The drawer now says the versions could not be read, with Try again.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ listTemplates: vi.fn(), getTemplate: vi.fn() }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: { listTemplates: h.listTemplates, getTemplate: h.getTemplate } }))

import TemplatesTab from './TemplatesTab.vue'

const ROW = {
  id: 'tpl-1', slug: 'escrow-basic', title: 'Escrow Basic', summary: 'Two milestones.', owner_agent_did: 'did:theprotocol:owner',
  visibility: 'public', pricing_model: 'free', price: null, price_currency: null, royalty_bps: 0, contract_type: 'service',
  usage_count: 3, settle_rate: null, maintained_by_org_id: null, verified: false,
}
const FULL = { ...ROW, versions: [
  { id: 'v1', version: 1, changelog: 'first', published_at: '2026-10-01T00:00:00Z', content_hash: 'a'.repeat(64) },
  { id: 'v2', version: 2, changelog: 'second', published_at: null, content_hash: 'b'.repeat(64) },
] }
const badGateway = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const modal = { template: '<div class="modal-stub"><slot /></div>' }

async function tabWithRow() {
  h.listTemplates.mockResolvedValue({ items: [ROW], next_cursor: null })
  const w = mount(TemplatesTab, { global: { stubs: { BaseModal: modal, Icon: true } } })
  await flushPromises()
  return w
}
async function details(w: ReturnType<typeof mount>) {
  await w.findAll('.tpl-actions .tpl-btn--ghost')[0].trigger('click')
  await flushPromises()
}

describe("a contract template's detail drawer", () => {
  beforeEach(() => { setActivePinia(createPinia()); h.listTemplates.mockReset(); h.getTemplate.mockReset() })

  it('a failed template read says the versions could not be read, never an empty Versions table', async () => {
    const w = await tabWithRow()
    h.getTemplate.mockRejectedValueOnce(badGateway())
    await details(w)
    expect(w.find('.tpl-detail').exists(), 'the drawer should open').toBe(true)
    expect(w.find('.tpl-vtable').exists(), 'drew an empty Versions table over a read that failed').toBe(false)
    expect(w.find('[data-testid="tpl-detail-unread"]').exists()).toBe(true)
    h.getTemplate.mockResolvedValueOnce(FULL)
    await w.find('[data-testid="tpl-detail-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.findAll('.tpl-vtable tbody tr')).toHaveLength(2)
  })

  it('an answered template shows its versions', async () => {
    const w = await tabWithRow()
    h.getTemplate.mockResolvedValueOnce(FULL)
    await details(w)
    expect(w.findAll('.tpl-vtable tbody tr')).toHaveLength(2)
    expect(w.find('[data-testid="tpl-detail-unread"]').exists()).toBe(false)
  })
})
