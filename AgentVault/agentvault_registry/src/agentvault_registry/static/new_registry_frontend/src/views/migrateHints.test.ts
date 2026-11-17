import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

/**
 * V0664 M5 (order gwo_5a4ea8476b97147f3056405e): the hints that point at Migrate, each shown only where the registry says the template
 * library is on (workflow_templates_enabled): the blueprint's proxy line, the public templates page, the Workflows view (its header and
 * its empty state). Nothing appears while the flag is false or unread: a hint to a page that does not exist is a dead door.
 */
const h = vi.hoisted(() => ({ on: null as any }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ workflowTemplatesEnabled: h.on }) }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (_k: string, f?: string) => f ?? _k, tp: (_k: string, f?: string) => f ?? _k }) }))
vi.mock('@/services/api/workflows', () => ({ workflowsApi: { mine: vi.fn().mockResolvedValue({ workflows: [] }), get: vi.fn(), create: vi.fn(), advance: vi.fn(), cancel: vi.fn(), candidates: vi.fn() } }))
vi.mock('axios', async (orig) => {              // the featured read of the public page only; the client keeps its own axios
  const real: any = await orig()
  real.default.get = vi.fn().mockResolvedValue({ data: { featured: [] } })
  return real
})

import BlueprintSection from '@/components/blueprints/BlueprintSection.vue'
import PublicTemplatesView from './PublicTemplatesView.vue'
import WorkflowsView from './WorkflowsView.vue'
import { BLUEPRINTS } from '@/data/blueprints'
import { useAuthStore } from '@/stores/auth'

const RouterLinkStub = { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' }
const stubs = { Icon: true, FlowLoom: true, RouterLink: RouterLinkStub, 'router-link': RouterLinkStub }

describe('the hints that point at Migrate', () => {
  beforeEach(() => { setActivePinia(createPinia()); h.on = ref(true) })

  it('the blueprint\'s proxy line carries one more sentence and a link to the library, only when the library is on', async () => {
    const mountIt = () => mount(BlueprintSection, { props: { bp: BLUEPRINTS[0] }, global: { stubs } })
    const on = mountIt()
    expect(on.find('[data-testid="bp-proxy-line"]').find('[data-testid="bp-migrate-link"]').exists()).toBe(true)
    expect(on.find('[data-testid="bp-migrate-link"]').attributes('data-to')).toContain('migrate')
    h.on = ref(false)
    const off = mountIt()
    expect(off.find('[data-testid="bp-proxy-line"]').exists()).toBe(true)        // the proxy line itself stays
    expect(off.find('[data-testid="bp-migrate-link"]').exists()).toBe(false)
  })

  it('the public templates page links to the library, only when the library is on', async () => {
    let w = mount(PublicTemplatesView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="pt-migrate-link"]').exists()).toBe(true)
    h.on = ref(false)
    w = mount(PublicTemplatesView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="pt-migrate-link"]').exists()).toBe(false)
  })

  it('the Workflows view offers Start from a template in its header and again in its empty state, only when the library is on', async () => {
    const auth: any = useAuthStore()
    auth.token = 'dev-token'; auth.agentToken = 'agent-token'; auth.activeAgent = { did: 'did:x', name: 'Owner' }
    let w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="wfl-from-template"]').exists()).toBe(true)
    expect(w.find('[data-testid="wfl-empty"]').find('[data-testid="wfl-empty-template"]').exists()).toBe(true)
    h.on = ref(false)
    w = mount(WorkflowsView, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="wfl-from-template"]').exists()).toBe(false)
    expect(w.find('[data-testid="wfl-empty-template"]').exists()).toBe(false)
    expect(w.find('[data-testid="wfl-empty"]').exists()).toBe(true)              // the empty state itself stays
  })
})
