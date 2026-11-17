import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0664 M5 (order gwo_5a4ea8476b97147f3056405e): one template's page. A free one shows its files (the README through the sanitizing
 * renderer, never raw markup); a paid one shows its structure and the buy door, never its files, and a visitor sees "Sign in to buy".
 * Buying and forking are the acting agent's, so a signed-in person without an agent is told to pick one.
 */
const h = vi.hoisted(() => ({
  detail: null as any, version: null as any, auth: { token: '', agentToken: '', activeAgent: null } as any,
  purchase: null as any, fork: null as any, instantiate: null as any, push: null as any,
}))
vi.mock('@/services/api/workflowTemplates', () => ({
  getTemplate: (...a: any[]) => h.detail(...a), getVersion: (...a: any[]) => h.version(...a),
  purchaseTemplate: (...a: any[]) => h.purchase(...a), forkTemplate: (...a: any[]) => h.fork(...a),
  instantiateTemplate: (...a: any[]) => h.instantiate(...a),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/chat/codeCopy', () => ({ copyText: vi.fn().mockResolvedValue(true) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { id: 'wtpl_a93a91a8d6c64f2c76aa' } }), useRouter: () => ({ push: (...a: any[]) => h.push(...a) }) }))

import MigrateTemplateView from './MigrateTemplateView.vue'
import { normalizeDetail } from '@/services/migrate/templates'
import { DETAIL, FREE_LISTING, LISTING, VERSION } from '@/services/migrate/m4Shapes.fixture'

const ID = LISTING.id
const detail = (over: Record<string, any> = {}) => normalizeDetail({ ...DETAIL, ...over })
const mountIt = () => mount(MigrateTemplateView, { global: { stubs: { Icon: true, RouterLink: { template: '<a><slot /></a>' } } } })
const locked = () => Object.assign(new Error('402'), { response: { status: 402, data: { code: 'payment_required', detail: 'buy it first' } } })
const asAgent = (did = 'did:a:buyer') => { h.auth = { token: 't', agentToken: 'a', activeAgent: { did } } }


// V0664 console proof (axe scrollable-region-focusable, session-lead seq 4206): a code box that can scroll is reachable by
// keyboard and named: tabindex 0, role region, an aria-label
function codeBoxesReachable(w: any) {
  const pres = w.findAll('pre')
  expect(pres.length).toBeGreaterThan(0)
  for (const p of pres) {
    expect(p.attributes('tabindex'), p.html().slice(0, 60)).toBe('0')
    expect(p.attributes('role')).toBe('region')
    expect((p.attributes('aria-label') || '').trim().length).toBeGreaterThan(3)
  }
}

describe('a migration template page', () => {
  beforeEach(() => {
    h.auth = { token: '', agentToken: '', activeAgent: null }
    h.detail = vi.fn().mockResolvedValue(detail({ pricing_model: 'free', price: '0.0000000000' }))
    h.version = vi.fn().mockResolvedValue({ files: { ...VERSION.files, 'README.md': '# Plan\n\n<script>alert(1)</script>\n\n**ship**' }, content_hash: VERSION.content_hash, manifest: {} })
    h.purchase = vi.fn().mockResolvedValue({ ok: true })
    h.fork = vi.fn().mockResolvedValue({ id: 'wtpl_forked' })
    h.instantiate = vi.fn().mockResolvedValue({ workflow_id: 'wf_1' })
    h.push = vi.fn()
  })

  it('a free template shows its files, the README through the sanitizing renderer, and the commands to try it', async () => {
    const w = mountIt()
    await flushPromises()
    expect(w.find('[data-testid="mgt-title"]').text()).toBe('CRM to Postgres')
    expect(w.find('[data-testid="mgt-price"]').text()).toBe('Free')
    const readme = w.find('[data-testid="mgt-readme"]')
    expect(readme.find('strong').text()).toBe('ship')
    expect(readme.find('script').exists()).toBe(false)                        // raw markup is text, never a script
    expect(w.find('[data-testid="mgt-spec"]').text()).toContain('sources')
    expect([0, 1, 2, 3].map((i) => w.find(`[data-testid="mgt-cmd-${i}"]`).exists())).toEqual([true, true, true, true])
    expect(w.find('[data-testid="mgt-cmd-0"]').text()).toContain('theprotocol-sdk[proxy]')
    expect(h.version).toHaveBeenCalledWith(ID, 1)                              // the version route (uncounted), not the kit route
  })

  it('shows the structure of any template: connectors, mappings with their field counts, parameters (a secret named as one), steps, counts', async () => {
    const w = mountIt()
    await flushPromises()
    expect(w.find('[data-testid="mgt-connectors"]').text()).toContain('a SQL database')
    expect(w.find('[data-testid="mgt-fields"]').text()).toContain('customers: 3 fields')
    expect(w.find('[data-testid="mgt-params"]').text()).toContain('TARGET_TABLE')
    expect(w.find('[data-testid="mgt-params"]').text()).toContain('SOURCE_PASSWORD')
    expect(w.find('[data-testid="mgt-steps"]').text()).toContain('dry-run')
    expect(w.find('[data-testid="mgt-certified"]').text()).toBe('certified by 2 developers')
  })

  it('a paid template shows its structure and no files; a visitor is told to sign in to buy', async () => {
    h.detail = vi.fn().mockResolvedValue(detail())
    h.version = vi.fn().mockRejectedValue(locked())
    const w = mountIt()
    await flushPromises()
    expect(w.find('[data-testid="mgt-price"]').text()).toBe('5 AVT')            // the decimal without the column's zeros
    expect(w.find('[data-testid="mgt-structure"]').exists()).toBe(true)
    expect(w.find('[data-testid="mgt-locked"]').exists()).toBe(true)
    expect(w.find('[data-testid="mgt-readme"]').exists()).toBe(false)
    expect(w.find('[data-testid="mgt-spec"]').exists()).toBe(false)
    expect(w.find('[data-testid="mgt-buy"]').exists()).toBe(false)
    expect(w.find('[data-testid="mgt-signin"]').text()).toContain('Sign in to buy')
    expect(w.find('[data-testid="mgt-error"]').exists()).toBe(false)           // a 402 is the lock, not a failure
  })

  it('a signed-in person without an agent is told to pick one; with an agent the buy door asks to confirm, then buys and reads the files', async () => {
    h.detail = vi.fn().mockResolvedValue(detail())
    h.version = vi.fn().mockRejectedValue(locked())
    h.auth = { token: 't', agentToken: '', activeAgent: null }
    let w = mountIt()
    await flushPromises()
    expect(w.find('[data-testid="mgt-pick"]').exists()).toBe(true)
    expect(w.find('[data-testid="mgt-buy"]').exists()).toBe(false)
    asAgent()
    w = mountIt()
    await flushPromises()
    await w.find('[data-testid="mgt-buy"]').trigger('click')
    expect(h.purchase).not.toHaveBeenCalled()                                  // a press asks; it does not spend
    expect(w.find('[data-testid="mgt-buy-confirm"]').text()).toContain('5 AVT')
    h.version = vi.fn().mockResolvedValue({ files: VERSION.files, content_hash: 'x', manifest: {} })
    await w.find('[data-testid="mgt-buy-go"]').trigger('click')
    await flushPromises()
    expect(h.purchase).toHaveBeenCalledWith(ID)
    expect(w.find('[data-testid="mgt-spec"]').exists()).toBe(true)             // bought: the mapping reads now
    expect(w.find('[data-testid="mgt-buy"]').exists()).toBe(false)
  })

  it('the owner reads the files and is offered no Buy; a declined purchase says so in plain words and nothing else changes', async () => {
    h.detail = vi.fn().mockResolvedValue(detail())
    asAgent('did:a:owner')
    let w = mountIt()
    await flushPromises()
    expect(w.find('[data-testid="mgt-spec"]').exists()).toBe(true)
    expect(w.find('[data-testid="mgt-buy"]').exists()).toBe(false)
    expect(w.find('[data-testid="mgt-fork"]').exists()).toBe(true)
    h.version = vi.fn().mockRejectedValue(locked())
    h.purchase = vi.fn().mockRejectedValue({ response: { status: 402, data: { code: 'payment_declined', detail: 'the deposit was declined' } } })
    asAgent()
    w = mountIt()
    await flushPromises()
    await w.find('[data-testid="mgt-buy"]').trigger('click')
    await w.find('[data-testid="mgt-buy-go"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="mgt-error"]').text()).toContain('Nothing was charged')
  })

  it('runs it as a workflow only with a budget above zero, and sends that budget', async () => {
    asAgent()
    const w = mountIt()
    await flushPromises()
    const go = w.find('[data-testid="mgt-instantiate"]')
    expect(go.attributes('disabled')).toBeDefined()                            // no budget yet
    await w.find('[data-testid="mgt-budget"]').setValue('30')
    expect(go.attributes('disabled')).toBeUndefined()
    await go.trigger('click')
    await flushPromises()
    expect(h.instantiate).toHaveBeenCalledWith(ID, { total_budget: 30 })
    expect(h.push).toHaveBeenCalledWith({ name: 'workflows' })
  })

  it('forks a free template and opens the fork (the answer\'s template_id)', async () => {
    h.detail = vi.fn().mockResolvedValue(normalizeDetail({ ...DETAIL, ...FREE_LISTING }))
    asAgent()
    const w = mountIt()
    await flushPromises()
    await w.find('[data-testid="mgt-fork"]').trigger('click')
    await flushPromises()
    expect(h.fork).toHaveBeenCalledTimes(1)
    expect(h.push).toHaveBeenCalledWith({ name: 'migrate-template', params: { id: 'wtpl_forked' } })
  })

  it('names the parent of a fork and the share its author gets', async () => {
    h.detail = vi.fn().mockResolvedValue(detail({ pricing_model: 'free', forked_from_template_id: 'wtpl_parent', fork_share_bps: 2000 }))
    const w = mountIt()
    await flushPromises()
    const p = w.find('[data-testid="mgt-parent"]').text()
    expect(p).toContain('wtpl_parent')
    expect(p).toContain('20 percent')
    expect(p).toContain('the platform takes nothing')
  })

  it('a template with no published version has no files to read, and says so, without asking for them', async () => {
    h.detail = vi.fn().mockResolvedValue(detail({ pricing_model: 'free', current_version: null, current_content_hash: null, versions: [], structure: null }))
    const w = mountIt()
    await flushPromises()
    expect(h.version).not.toHaveBeenCalled()
    expect(w.find('[data-testid="mgt-noversion"]').exists()).toBe(true)
  })

  it('every code box is reachable by keyboard and named: the spec and each command (proof seq 4206)', async () => {
    const w = mountIt()
    await flushPromises()
    expect(w.findAll('pre').length).toBe(5)
    codeBoxesReachable(w)
  })
})
