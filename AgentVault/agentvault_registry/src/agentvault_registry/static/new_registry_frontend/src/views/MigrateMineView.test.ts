import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/** V0664 C4: My templates. Reads GET /workflow-templates/mine; says so when the registry lacks the route; the listing and a publish are the acting agent's. */
const h = vi.hoisted(() => ({ auth: { token: 't', agentToken: 'a', activeAgent: { did: 'did:a:me' } } as any, mine: null as any, certs: null as any, patch: null as any, publish: null as any }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/api/workflowTemplates', () => ({
  listMyTemplates: (...a: any[]) => h.mine(...a), listMyCertificates: (...a: any[]) => h.certs(...a),
  patchTemplate: (...a: any[]) => h.patch(...a), publishVersion: (...a: any[]) => h.publish(...a),
}))
import MigrateMineView from './MigrateMineView.vue'
import { normalizeMineList, normalizeCertificates } from '@/services/migrate/mine'

const RAW = { items: [{
  id: 'wt_1', slug: 'crm-to-pg', title: 'CRM to Postgres', visibility: 'public', pricing_model: 'purchase', price: '5.0000000000', price_currency: 'ECU', fork_share_bps: 1000,
  versions: [{ version: 1, published: true, content_hash: 'a'.repeat(64), changelog: 'first' }, { version: 2, published: false, content_hash: 'b'.repeat(64), changelog: 'wip' }],
  counts: { kit_downloads: 12, instantiations: 4, certified: 1, forks: 1 }, buyers: { count: 3, items: [{ agent_did: 'did:a:buyer', at: '2026-11-14T10:00:00Z' }] },
}] }
const cert = (target: string) => ({ attestation_id: 'att_' + target, attestation_type: 'migration.certificate', target_agent_did: target, attestation_data: { record: 'x', claim: { template: { name: 'crm-to-pg', version: 1, content_hash: 'a'.repeat(64) }, moved: 1, rejected: 0, verdict: 'pass' } } })
const mountIt = () => mount(MigrateMineView, { global: { stubs: { Icon: true, MigrateTabs: true, RouterLink: { template: '<a><slot /></a>' } } } })

describe('My templates', () => {
  beforeEach(() => {
    h.auth = { token: 't', agentToken: 'a', activeAgent: { did: 'did:a:me' } }
    h.mine = vi.fn().mockResolvedValue(normalizeMineList(RAW))
    h.certs = vi.fn().mockResolvedValue(normalizeCertificates([cert('did:a:1'), cert('did:a:2'), cert('did:a:2')]))
    h.patch = vi.fn().mockResolvedValue({ ok: true })
    h.publish = vi.fn().mockResolvedValue({ published: true })
  })
  it('lists a template with its state, versions, counts, buyers and the certified count (distinct developers, not certificates)', async () => {
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mm-title"]').text()).toBe('CRM to Postgres')
    expect(w.find('[data-testid="mm-state"]').text()).toContain('published')
    expect(w.find('[data-testid="mm-state"]').text()).toContain('a newer draft')
    expect(w.find('[data-testid="mm-version-2"]').text()).toContain('draft')
    expect(w.find('[data-testid="mm-buyers"]').text()).toBe('3')
    expect(w.find('[data-testid="mm-certified"]').text()).toBe('certified by 2 developers')
    expect(w.find('[data-testid="mm-buyer-rows"]').text()).toContain('did:a:buyer')
    expect(w.find('[data-testid="mm-buyer-rows"] li').attributes('title')).toBe('did:a:buyer')   // the full DID on hover
  })
  it('publishes a draft version and shows it published', async () => {
    const w = mountIt(); await flushPromises()
    await w.find('[data-testid="mm-publish-2"]').trigger('click'); await flushPromises()
    expect(h.publish).toHaveBeenCalledWith('wt_1', 2)
    expect(w.find('[data-testid="mm-version-2"]').text()).toContain('published')
    expect(w.find('[data-testid="mm-publish-2"]').exists()).toBe(false)
  })
  it('saves the listing: a share in percent goes as basis points, the price only when it is a paid one; the button waits for a change', async () => {
    const w = mountIt(); await flushPromises()
    expect((w.find('[data-testid="mm-save"]').element as HTMLButtonElement).disabled).toBe(true)
    await w.find('[data-testid="mm-share"]').setValue('12.5')
    await w.find('[data-testid="mm-price"]').setValue('7')
    await w.find('[data-testid="mm-save"]').trigger('click'); await flushPromises()
    expect(h.patch).toHaveBeenCalledWith('wt_1', { visibility: 'public', pricing_model: 'purchase', fork_share_bps: 1250, price: '7' })
    expect(w.find('[data-testid="mm-saved"]').exists()).toBe(true)
    await w.find('[data-testid="mm-pricing"]').setValue('free'); await w.find('[data-testid="mm-save"]').trigger('click'); await flushPromises()
    expect(h.patch).toHaveBeenLastCalledWith('wt_1', { visibility: 'public', pricing_model: 'free', fork_share_bps: 1250 })
  })
  it('refuses a share above 50 without a request, and shows the registry\'s own sentence when it refuses', async () => {
    const w = mountIt(); await flushPromises()
    await w.find('[data-testid="mm-share"]').setValue('80'); await w.find('[data-testid="mm-save"]').trigger('click'); await flushPromises()
    expect(h.patch).not.toHaveBeenCalled()
    expect(w.find('[data-testid="mm-row-error"]').text()).toContain('0 to 50')
    h.publish = vi.fn().mockRejectedValue({ response: { data: { code: 'bond_required', detail: 'a reputation bond is needed to publish' } } })
    await w.find('[data-testid="mm-publish-2"]').trigger('click'); await flushPromises()
    expect(w.find('[data-testid="mm-row-error"]').text()).toBe('a reputation bond is needed to publish')
  })
  it('says so when the registry has no such route, when nobody is signed in, and when there are none', async () => {
    h.mine = vi.fn().mockRejectedValue({ response: { status: 404 } })
    let w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mm-unavailable"]').exists()).toBe(true)
    h.auth = { token: '', agentToken: '', activeAgent: null }; h.mine.mockClear()
    w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mm-signin"]').exists()).toBe(true)
    expect(h.mine).not.toHaveBeenCalled()
    h.auth = { token: 't', agentToken: 'a', activeAgent: { did: 'x' } }; h.mine = vi.fn().mockResolvedValue([])
    w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mm-empty"]').exists()).toBe(true)
  })
  it('a failed certificate read leaves the counts to the library', async () => {
    h.certs = vi.fn().mockRejectedValue(new Error('x'))
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mm-certified"]').text()).toBe('certified by 1 developer')
  })
})
