// V0666 the Earned category: rings, badges and titles by what the person unlocked, locked ones dark, wearing for the chosen bearer, one copy moving between bearers,
// a bought ring or corner on an agent said before the registry has to say it, a title the developer's only.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EarnedWearPanel from './EarnedWearPanel.vue'

const it_ = (o: Record<string, any>) => ({ kind: 'corner', key: 'initiate', tier: 1, side: false, condition: 'Propose your first change.', unlocked: false, progress: { n: 0, of: 1 }, later: null, ...o })
const ITEMS = [
  it_({ kind: 'corner', key: 'initiate', tier: 1, unlocked: true, progress: { n: 1, of: 1 } }),
  it_({ kind: 'encirclement', key: 'lantern', tier: 2, unlocked: true, progress: { n: 1, of: 1 } }),
  it_({ kind: 'encirclement', key: 'ember', tier: 4, progress: { n: 2, of: 3 } }),
  it_({ kind: 'corner', key: 'keystone', tier: 7 }),
  it_({ kind: 'title', key: 'first-light', tier: 3, unlocked: true, progress: { n: 1, of: 1 } }),
  it_({ kind: 'title', key: 'patchwright', tier: 7, progress: { n: 3, of: 5 } }),
  it_({ kind: 'title', key: 'quorum-maker', tier: 27, progress: { n: 0, of: 25 } }),
]
const ME = { key: 'me', kind: 'developer', did: null, name: 'Ada' } as const
const AG = { key: 'did:a', kind: 'agent', did: 'did:a', name: 'Agent A' } as const
const none = { ring: null, badge: null, title: null }
const stubs = { Icon: true, EarnedRing: true, EarnedBadge: true, TitleEmblem: true, CommanderPlate: true, RouterLink: { template: '<a><slot /></a>' } }
const mountIt = (over: Record<string, any> = {}) => mount(EarnedWearPanel, {
  props: { items: ITEMS, state: 'ready', bearer: ME, wornNow: none, holderName: () => '', busyKey: '', errors: {}, initials: 'AL', still: true, isCommander: false, ...over } as any,
  global: { stubs },
})
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the earned category', () => {
  it('says it is earned by contributing and not for sale, and separate from the bought flares', () => {
    const w = mountIt()
    expect(w.text()).toContain('Unlocked by contributing')
    expect(w.text()).toContain('Never for sale and never given')
    expect(w.text()).toContain('separate from the flares you bought')
  })

  it('groups rings, badges and titles for you, in tier order, with how many are unlocked', () => {
    const w = mountIt()
    expect(tid(w, 'earned-rings').text()).toContain('1 / 2')
    expect(tid(w, 'earned-badges').text()).toContain('1 / 2')
    expect(tid(w, 'earned-titles').exists()).toBe(true)
    const keys = tid(w, 'earned-titles').findAll('article').map((a) => a.attributes('data-testid'))
    expect(keys.indexOf('track-item-title-first-light')).toBeLessThan(keys.length)           // unlocked: in full
  })

  it('draws a locked item as an outline only, except the next title and the next item of the pass', () => {
    const w = mountIt()
    expect(tid(w, 'track-item-corner-keystone').exists()).toBe(false)                        // dark: no name, no testid of its key
    expect(tid(w, 'track-item-corner-locked').exists()).toBe(true)
    expect(tid(w, 'track-item-title-patchwright').exists()).toBe(true)                      // the next title: shown in full
    expect(tid(w, 'track-item-title-quorum-maker').exists()).toBe(false)                    // another locked title: dark
    expect(tid(w, 'track-next-item').exists()).toBe(true)                                   // the next item of the pass: ember
  })

  it('keeps the dark outlines in a compact strip after the items shown in full, with how many are still dark', () => {
    const w = mountIt()
    const rings = tid(w, 'earned-rings')
    expect(rings.find('[data-testid="earned-rings-dark"]').exists()).toBe(false)           // a ring that is next is shown in full: nothing dark in the rings here
    const badges = tid(w, 'earned-badges')
    const dark = badges.find('[data-testid="earned-badges-dark"]')
    expect(dark.exists()).toBe(true)
    expect(dark.findAll('[data-state="blacked"]').length).toBe(1)                           // keystone
    expect(badges.find('.ewp-grid').findAll('[data-state="blacked"]').length).toBe(0)        // never among the cards in full
    expect(tid(w, 'earned-badges-dark-count').text()).toContain('1')
  })

  it('wears on the chosen bearer: a press on an unlocked item asks to wear it, a press on what is worn asks to take it off', async () => {
    const w = mountIt({ wornNow: { ring: { key: 'lantern', source: 'earned' }, badge: null, title: null } })
    await tid(w, 'track-wear-initiate').trigger('click')
    await tid(w, 'track-wear-lantern').trigger('click')
    expect(w.emitted('wear')![0][0].key).toBe('initiate'); expect(w.emitted('wear')![0][1]).toBe(false)
    expect(w.emitted('wear')![1][0].key).toBe('lantern'); expect(w.emitted('wear')![1][1]).toBe(true)
  })

  it('says another bearer wears an earned copy and that wearing it here moves it', () => {
    const w = mountIt({ holderName: (k: string, key: string) => (key === 'lantern' ? 'Agent B' : '') })
    expect(tid(w, 'earned-held-lantern').text()).toBe('Worn by Agent B. Wearing it here moves it.')
    expect(tid(w, 'earned-held-initiate').exists()).toBe(false)
  })

  it('offers no title to an agent and says why', () => {
    const w = mountIt({ bearer: AG })
    expect(tid(w, 'earned-titles').exists()).toBe(false)
    expect(tid(w, 'earned-no-titles').text()).toContain('stays yours')
    expect(tid(w, 'earned-for').text()).toBe('Choosing for Agent A')
  })

  it('tells an agent that wears a bought ring to take it off first, and offers no wear on the rings', () => {
    const w = mountIt({ bearer: AG, wornNow: { ring: { key: 'shadow_chancellor', source: 'bought' }, badge: null, title: null } })
    expect(tid(w, 'earned-rings-blocked').text()).toContain('wears a bought ring')
    expect(tid(w, 'track-wear-lantern').exists()).toBe(false)
    expect(tid(w, 'track-wear-initiate').exists()).toBe(true)                               // the badge slot is free
    expect(tid(w, 'earned-badges-blocked').exists()).toBe(false)
  })

  it("shows the registry's sentence under the item it was asked about", () => {
    const w = mountIt({ errors: { 'encirclement:lantern': 'You have not earned the lantern ring yet.' } })
    expect(tid(w, 'track-err-lantern').text()).toContain('not earned')
  })

  it('shows the COMMANDER plate to the commander tier in the titles, worn by default, and offers it back when another title is worn', async () => {
    const w = mountIt({ isCommander: true })
    expect(tid(w, 'earned-commander').exists()).toBe(true)
    expect(tid(w, 'earned-commander-worn').exists()).toBe(true)
    expect(tid(w, 'earned-commander-wear').exists()).toBe(false)
    const w2 = mountIt({ isCommander: true, wornNow: { ring: null, badge: null, title: 'patchwright' } })
    expect(tid(w2, 'earned-commander-worn').exists()).toBe(false)
    await tid(w2, 'earned-commander-wear').trigger('click')
    expect(w2.emitted('commander')).toHaveLength(1)
  })

  it('shows the COMMANDER plate to no one else and never to an agent', () => {
    expect(tid(mountIt({ isCommander: false }), 'earned-commander').exists()).toBe(false)
    expect(tid(mountIt({ isCommander: true, bearer: AG }), 'earned-commander').exists()).toBe(false)
  })

  it('says nothing unlocked yet with the way to the track, and a failed read says it failed', () => {
    expect(tid(mountIt({ items: ITEMS.map((i) => ({ ...i, unlocked: false })) }), 'earned-none').exists()).toBe(true)
    const f = mountIt({ state: 'failed' })
    expect(tid(f, 'earned-failed').exists()).toBe(true)
    expect(tid(f, 'earned-none').exists()).toBe(false)
  })
})
