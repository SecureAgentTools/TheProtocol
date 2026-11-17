// V0666 the Bought category for one agent: wear or take off the corner flare and the ring you picked, which agent bears it now, the overlay on a borne ring, and the earned item
// on the agent that has to come off first.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BoughtOnAgent from './BoughtOnAgent.vue'

const base = { agent: { did: 'did:a', name: 'Agent A', bears_corner_flare: false, bears_encirclement_flare: false, flare_encirclement_overlay: null }, cornerName: 'Founder', ringName: 'Shadow Chancellor', cornerHolder: '', ringHolder: '',
  overlays: [{ id: 'glitch', label: 'Glitch' }, { id: 'static', label: 'Static' }], busy: false, error: '', ok: '', earnedRing: false, earnedBadge: false }
const mountIt = (over: Record<string, any> = {}) => mount(BoughtOnAgent, { props: { ...base, ...over, agent: { ...base.agent, ...(over.agent || {}) } } as any })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the bought category for an agent', () => {
  it('names the flares you picked and offers to wear each here', async () => {
    const w = mountIt()
    expect(tid(w, 'bought-corner-what').text()).toBe('Founder')
    expect(tid(w, 'bought-encirclement-what').text()).toBe('Shadow Chancellor')
    await tid(w, 'bought-corner-on').trigger('click')
    await tid(w, 'bought-encirclement-on').trigger('click')
    expect(w.emitted('equip')).toEqual([['corner'], ['encirclement']])
  })

  it('offers to take off the slot this agent bears, and only a borne ring has overlays', async () => {
    const w = mountIt({ agent: { bears_encirclement_flare: true } })
    expect(tid(w, 'bought-overlays').exists()).toBe(true)
    await tid(w, 'bought-encirclement-off').trigger('click')
    await tid(w, 'overlay-glitch').trigger('click')
    await tid(w, 'overlay-none').trigger('click')
    expect(w.emitted('unequip')![0]).toEqual(['encirclement'])
    expect(w.emitted('overlay')).toEqual([['glitch'], [null]])
    expect(tid(mountIt(), 'bought-overlays').exists()).toBe(false)
  })

  it('marks the active overlay and says which agent bears the slot now', () => {
    const w = mountIt({ agent: { bears_encirclement_flare: true, flare_encirclement_overlay: 'static' }, cornerHolder: 'Agent B' })
    expect(tid(w, 'overlay-static').attributes('aria-pressed')).toBe('true')
    expect(tid(w, 'overlay-none').attributes('aria-pressed')).toBe('false')
    expect(tid(w, 'bought-corner-held').text()).toBe('Worn by Agent B. Wearing it here moves it.')
  })

  it('says to pick a flare under You when none is picked and offers no wear', () => {
    const w = mountIt({ cornerName: '', ringName: '' })
    expect(tid(w, 'bought-corner-what').text()).toContain('Pick one under "You"')
    expect(tid(w, 'bought-corner-on').exists()).toBe(false)
  })

  it('tells an agent that wears an earned ring or badge to take it off first, with no wear offered for that slot', () => {
    const w = mountIt({ earnedRing: true })
    expect(tid(w, 'bought-encirclement-blocked').text()).toContain('unlocked ring')
    expect(tid(w, 'bought-encirclement-on').exists()).toBe(false)
    expect(tid(w, 'bought-corner-on').exists()).toBe(true)
  })

  it('disables the buttons while the registry answers and shows its sentence or a done line', () => {
    const w = mountIt({ busy: true, error: 'You have no corner flare to equip.', ok: 'Done.' })
    expect(tid(w, 'bought-corner-on').attributes('disabled')).toBeDefined()
    expect(tid(w, 'bought-error').text()).toContain('no corner flare')
    expect(tid(w, 'bought-ok').text()).toBe('Done.')
  })
})
