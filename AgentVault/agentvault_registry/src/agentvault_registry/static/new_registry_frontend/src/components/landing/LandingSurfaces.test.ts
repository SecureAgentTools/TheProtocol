// V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4404: "landingpage updates. we need migration proxy and code changes on
// there"): three tiles on the landing page, each one sentence of what it is and one door; the migration library only where
// the registry says it is on (workflow_templates_enabled), as the nav and the route do.
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const cfg = vi.hoisted(() => ({ on: true }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ workflowTemplatesEnabled: ref(cfg.on) }) }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (_k: string, f?: string) => f ?? _k }) }))

import LandingSurfaces from './LandingSurfaces.vue'

const stubs = { Icon: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
const mountIt = () => mount(LandingSurfaces, { global: { stubs } })
// the console's value words and the wording sweep's critical words (fesuite route sweeps): none in these tiles
const VALUE_WORDS = /\b(?:un)?stak(?:e|ed|es|er|ers|ing)?\b|\btokens?\b|\byield|\bearn|\bbank|\bfloats?\b|\bprofit|\binvest|\binterest\b|\bdividend|\breward|\bapy\b|\breturns?\b/i

describe('the landing page: the systems you already run', () => {
  it('three tiles, each one sentence and one door: Migrate a system, the Proxy, Code changes', () => {
    const w = mountIt()
    const doors = ['migrate', 'proxy', 'code-changes'].map((n) => {
      const tile = w.find(`[data-testid=lp-surface-${n}]`)
      expect(tile.exists(), n).toBe(true)
      expect(tile.find('h3').text().length).toBeGreaterThan(3)
      const said = tile.find('p').text()
      expect(said.split(/[.!?](\s|$)/).filter((x) => x && x.trim()).length, n).toBe(1)
      const door = tile.findAll('a')
      expect(door, n).toHaveLength(1)
      return JSON.parse(door[0]!.attributes('data-to')!)
    })
    expect(doors).toEqual([{ name: 'migrate' }, { name: 'proxy' }, { name: 'code-changes' }])
  })

  it('the migration library only where the registry has it on; the other two always', () => {
    cfg.on = false
    const w = mountIt()
    expect(w.find('[data-testid=lp-surface-migrate]').exists()).toBe(false)
    expect(w.find('[data-testid=lp-surface-proxy]').exists()).toBe(true)
    expect(w.find('[data-testid=lp-surface-code-changes]').exists()).toBe(true)
    cfg.on = true
  })

  it('says no value word', () => {
    expect(mountIt().text()).not.toMatch(VALUE_WORDS)
  })
})
