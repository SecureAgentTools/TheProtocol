// V0666 the bearers rail: you first, every agent with what it wears, a search at a fleet's scale, one press to choose; a failed read says so.
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import FlareBearerRail from './FlareBearerRail.vue'
import { bearersOf, wornBy, type AgentFlareRow, type DeveloperFlare } from '@/services/flareBearers'

const dev: DeveloperFlare = { name: 'Ada', flare_encirclement_variant: 'ember', flare_corner_variant: null, selected_corner_flare: 'founder', selected_encirclement_flare: null, title: 'patchwright' }
const mkAgents = (n: number): AgentFlareRow[] => Array.from({ length: n }, (_, i) => ({ did: `did:${i}`, name: `Agent ${String(i).padStart(2, '0')}`, flare_corner_variant: i === 1 ? 'initiate' : null, bears_corner_flare: i === 2 }))
const mountIt = (n: number, state: 'loading' | 'ready' | 'failed' = 'ready', selected = 'me') => {
  const agents = mkAgents(n)
  const bearers = bearersOf(dev, agents)
  return mount(FlareBearerRail, { props: { bearers, selected, state, worn: (b: any) => wornBy(b, dev, agents), boughtName: (k: string) => `bought:${k}` }, global: { stubs: { Icon: true, RouterLink: { template: '<a><slot /></a>' } } } })
}
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the bearers rail', () => {
  it('lists you first and then the agents, with what each wears', () => {
    const w = mountIt(3)
    const rows = w.findAll('[data-testid^="bearer-"][aria-pressed]')
    expect(rows.length).toBe(4)
    expect(rows[0].attributes('data-testid')).toBe('bearer-me')
    expect(tid(w, 'bearer-me-ring').text()).toBe('Ring Ember')                              // earned: the art's name
    expect(tid(w, 'bearer-me-badge').text()).toBe('Badge bought:founder')                    // bought: the shop's name
    expect(tid(w, 'bearer-me-title').text()).toBe('Title Patchwright')
    expect(tid(w, 'bearer-did:1-badge').text()).toBe('Badge Initiate')
    expect(tid(w, 'bearer-did:0-worn').text()).toBe('Wears nothing yet')
  })

  it('marks the chosen bearer and emits the key on a press', async () => {
    const w = mountIt(3, 'ready', 'did:1')
    expect(tid(w, 'bearer-did:1').attributes('aria-pressed')).toBe('true')
    expect(tid(w, 'bearer-me').attributes('aria-pressed')).toBe('false')
    await tid(w, 'bearer-did:2').trigger('click')
    expect(w.emitted('select')![0]).toEqual(['did:2'])
  })

  it('shows a search only for a long list, and the developer stays in every answer', async () => {
    expect(tid(mountIt(3), 'rail-search').exists()).toBe(false)
    const w = mountIt(30)
    await tid(w, 'rail-search').setValue('agent 07')
    const rows = w.findAll('[data-testid^="bearer-"][aria-pressed]')
    expect(rows.map((r) => r.attributes('data-testid'))).toEqual(['bearer-me', 'bearer-did:7'])
  })

  it('says there are no agents with the way to make one, and says a failed read failed', async () => {
    expect(tid(mountIt(0), 'rail-no-agents').exists()).toBe(true)
    const w = mountIt(0, 'failed')
    expect(w.find('[data-read-failed]').exists()).toBe(true)
    expect(tid(w, 'rail-no-agents').exists()).toBe(false)
    expect(w.find('[data-testid="bearer-me"]').exists()).toBe(false)
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    expect(w.emitted('retry')).toBeTruthy()
  })

  it('reads the agents while loading and keeps the developer usable', () => {
    const w = mountIt(0, 'loading')
    expect(w.text()).toContain('Reading your agents')
    expect(tid(w, 'bearer-me').exists()).toBe(true)
    expect(tid(w, 'rail-no-agents').exists()).toBe(false)
  })
})
