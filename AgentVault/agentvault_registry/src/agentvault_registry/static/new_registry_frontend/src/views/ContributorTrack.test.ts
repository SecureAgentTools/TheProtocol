/**
 * V0665 (order gwo_5e0701efdef9d3989491bc37): the Track tab (#/code-changes/track). The ten tiers in a row, the titles, the side quests and the items waiting for a condition;
 * an unlocked item as it is, with its condition and state; everything not yet unlocked BLACKED OUT (its outline only: no art, no name, no condition) except the one NEXT title;
 * an earned item can be worn (the registry's sentence answers a refusal where it was asked); the Commander plate only to the commander flare tier, worn by default;
 * a visitor reads the track with every item blacked out; a track that could not be read says so, never "nothing earned".
 * (His feedback on the Track tab, room seq 4404, through session-lead seq 4405.)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  signedIn: true, tier: null as string | null, mine: null as any, pub: null as any, flare: null as any, equip: null as any, wear: null as any,
}))
vi.mock('@/services/api/contributorTrack', () => ({
  getMyTrack: (...a: any[]) => h.mine(...a), getPublicTrack: (...a: any[]) => h.pub(...a), equipTitle: (...a: any[]) => h.equip(...a), wearEarned: (...a: any[]) => h.wear(...a),
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: (...a: any[]) => h.flare(...a) } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: h.signedIn, user: { name: 'Ada Lovelace', flare_tier: h.tier } }) }))

import ContributorTrack from './ContributorTrack.vue'

const item = (over: Record<string, any>) => ({ kind: 'corner', key: 'initiate', tier: 1, side: false, condition: 'Propose your first change.', unlocked: false, progress: { n: 0, of: 1 }, later: null, ...over })
const ITEMS = [
  item({ kind: 'corner', key: 'initiate', tier: 1, unlocked: true, progress: { n: 1, of: 1 } }),
  item({ kind: 'encirclement', key: 'lantern', tier: 2, condition: 'Review someone else\'s change.' }),
  item({ kind: 'corner', key: 'crown-of-the-commons', tier: 10 }),
  item({ kind: 'encirclement', key: 'supernova', tier: 10, unlocked: true }),
  item({ kind: 'title', key: 'first-light', tier: null, condition: 'Have your first change merged.', progress: { n: 0, of: 1 } }),
  item({ kind: 'title', key: 'bug-slayer', tier: null, condition: 'Have ten fixes merged.', later: 'nothing marks a change as the fix of a reported defect yet' }),
  item({ kind: 'title', key: 'off-by-one', tier: null, side: true, condition: 'Pass by one vote.' }),
  item({ kind: 'encirclement', key: 'ouroboros', tier: null, condition: 'A condition for this ring is not set yet.', later: 'its condition is not set yet' }),
]
const MINE = { items: ITEMS, equipped_title: null, season_wins: ['2026Q2'], counts: {} }
const stubs = { Icon: true, CodeChangesTabs: true, EarnedRing: true, EarnedBadge: true, TitleEmblem: true, CommanderPlate: { template: '<div data-testid="plate" />' }, RouterLink: { props: ['to'], template: '<a><slot /></a>' } }
const mountIt = () => mount(ContributorTrack, { global: { stubs } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the Track tab', () => {
  beforeEach(() => {
    h.signedIn = true; h.tier = null
    h.mine = vi.fn().mockResolvedValue(MINE); h.pub = vi.fn().mockResolvedValue({ items: ITEMS.map((i) => ({ ...i, unlocked: undefined, progress: undefined })) })
    h.flare = vi.fn().mockResolvedValue({ data: { flare_tier: h.tier, flare_encirclement_variant: null, flare_corner_variant: 'initiate' } })
    h.equip = vi.fn().mockImplementation(async (k: string | null) => ({ title: k })); h.wear = vi.fn().mockResolvedValue({ flare_corner_variant: null })
  })

  it('draws the tiers in order, two items on tier ten, with the total earned', async () => {
    const w = mountIt(); await flushPromises()
    const tiers = w.findAll('[data-testid^="track-tier-"]')
    expect(tiers.map((t) => t.attributes('data-testid'))).toEqual(['track-tier-1', 'track-tier-2', 'track-tier-10'])
    expect(tid(w, 'track-tier-10').findAll('[data-testid^="track-item-"]')).toHaveLength(2)
    expect(tid(w, 'track-tier-1').attributes('data-state')).toBe('done')
    expect(tid(w, 'track-tier-10').attributes('data-state')).toBe('partial')
    expect(tid(w, 'track-total').text()).toContain('2 of 6')
  })

  it('shows an unlocked item as it is (its condition and state) and the worn one as worn', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-item-encirclement-supernova').attributes('data-state')).toBe('earned')
    expect(tid(w, 'track-item-corner-initiate').text()).toContain('Propose your first change')
    expect(tid(w, 'track-state-supernova').text()).toBe('Unlocked')
    expect(tid(w, 'track-state-initiate').text()).toBe('Worn')                // the flare status says this badge is worn
  })

  it('blacks out everything not yet unlocked: its outline only, no art, no name, no condition, no progress, nothing in the page that names it', async () => {
    const w = mountIt(); await flushPromises()
    const crown = tid(w, 'track-item-corner-locked')                         // tier 10's badge, locked and not the next
    expect(crown.attributes('data-state')).toBe('blacked')
    expect(crown.find('[data-testid="track-outline"]').exists()).toBe(true)
    expect(crown.attributes('aria-label')).toBe('A locked badge')
    expect(crown.text()).toBe('')                                            // no name, no sentence, no n of m
    expect(crown.find('.tic-bar').exists()).toBe(false)
    for (const gone of ['crown-of-the-commons', 'bug-slayer', 'off-by-one', 'ouroboros', 'fix of a reported defect', 'Pass by one vote'])
      expect(w.html().toLowerCase()).not.toContain(gone.toLowerCase())
  })

  it('draws the outline of what each locked item will be: a ring, a badge or a plate', async () => {
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="track-item-encirclement-locked"]').attributes('data-shape')).toBe('ring')
    expect(w.find('[data-testid="track-item-corner-locked"]').attributes('data-shape')).toBe('badge')
    expect(w.find('[data-testid="track-item-title-locked"]').attributes('data-shape')).toBe('plate')
  })

  it('shows only the NEXT title, in full: its plate, its name and what unlocks it; every other title stays dark', async () => {
    const w = mountIt(); await flushPromises()
    const next = tid(w, 'track-item-title-first-light')
    expect(next.exists()).toBe(true)
    expect(next.text()).toContain('Have your first change merged')
    expect(tid(w, 'track-next-title').exists()).toBe(true)
    expect(tid(w, 'track-titles').findAll('[data-testid="track-item-title-locked"]')).toHaveLength(1)    // the one that waits for a signal
    expect(tid(w, 'track-side').findAll('[data-testid="track-item-title-locked"]')).toHaveLength(1)      // the side quest
  })

  it('shows the NEXT item of the pass track too, in full: its art, name, condition and progress, labelled; the rest of the pass stays dark', async () => {
    const w = mountIt(); await flushPromises()
    const next = tid(w, 'track-item-encirclement-lantern')                   // tier 1 is unlocked: tier 2 is the next of the pass
    expect(next.exists()).toBe(true)
    expect(next.attributes('data-state')).toBe('locked')
    expect(next.text()).toContain('Review someone else')
    expect(tid(w, 'track-state-lantern').text()).toBe('0 of 1')
    expect(tid(w, 'track-next-item').exists()).toBe(true)
    expect(tid(w, 'track-tier-10').find('[data-testid="track-item-corner-locked"]').exists()).toBe(true)   // a later tier is dark
  })

  it('moves the next pass-track item on when it is unlocked', async () => {
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: ITEMS.map((i) => (i.key === 'lantern' ? { ...i, unlocked: true } : i)) })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-item-encirclement-lantern').attributes('data-state')).toBe('earned')
    expect(tid(w, 'track-tier-10').find('[data-testid="track-item-corner-crown-of-the-commons"]').exists()).toBe(true)    // the crown is the next one: tier 10's badge, in full
    expect(tid(w, 'track-tier-10').find('[data-testid="track-item-corner-locked"]').exists()).toBe(false)
    expect(w.findAll('[data-testid="track-next-item"]')).toHaveLength(1)
  })

  it('moves the next title when another is closer to unlocking', async () => {
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: ITEMS.map((i) => (i.key === 'off-by-one' ? { ...i, progress: { n: 4, of: 5 } } : i)) })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-item-title-off-by-one').exists()).toBe(true)
    expect(tid(w, 'track-item-title-first-light').exists()).toBe(false)
  })

  it('draws a pass longer than ten tiers: tier 11 and on follow the ten, and a tier of two items is a pair side by side', async () => {
    const extra = [item({ kind: 'title', key: 'first-light', tier: 11 }), item({ kind: 'encirclement', key: 'ouroboros', tier: 12 })]
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: [...ITEMS.filter((i: any) => i.tier != null), ...extra] })
    const w = mountIt(); await flushPromises()
    expect(w.findAll('[data-testid^="track-tier-"]').map((t) => t.attributes('data-testid'))).toEqual(['track-tier-1', 'track-tier-2', 'track-tier-10', 'track-tier-11', 'track-tier-12'])
    expect(tid(w, 'track-tier-10').classes()).toContain('ct-tier--pair')              // the two of tier ten sit side by side: the row is one card tall
    expect(tid(w, 'track-tier-2').classes()).not.toContain('ct-tier--pair')
    expect(tid(w, 'track-tiers').find('h2').text()).toBe('The pass')
  })

  it('makes the scrolling row reachable by keyboard: it takes focus and is named (axe scrollable-region-focusable)', async () => {
    const w = mountIt(); await flushPromises()
    const row = w.find('.ct-row')
    expect(row.attributes('tabindex')).toBe('0')
    expect((row.attributes('aria-label') || '').length).toBeGreaterThan(3)
  })

  it('has a jump to the next tier: the first tier not done, with previous and next arrows for the long row', async () => {
    const scrolled: any[] = []
    ;(Element.prototype as any).scrollTo = function (arg: any) { scrolled.push({ el: this, arg }) }
    ;(Element.prototype as any).scrollBy = function (arg: any) { scrolled.push({ el: this, by: arg }) }
    const w = mountIt(); await flushPromises()
    const jump = tid(w, 'track-jump-next')
    expect(jump.exists()).toBe(true)
    expect(jump.text()).toContain('2')                                                // tier 1 is done, tier 2 is the next
    await jump.trigger('click')
    expect(scrolled.length).toBeGreaterThan(0)
    await tid(w, 'track-scroll-next').trigger('click')
    await tid(w, 'track-scroll-prev').trigger('click')
    expect(scrolled.filter((x) => x.by).length).toBe(2)
  })

  it('has no jump when the whole pass is unlocked, and none for a visitor', async () => {
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: ITEMS.map((i: any) => ({ ...i, unlocked: true })) })
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'track-jump-next').exists()).toBe(false)
    h.signedIn = false
    w = mountIt(); await flushPromises()
    expect(tid(w, 'track-jump-next').exists()).toBe(false)
  })

  it('keeps side quests apart from the titles', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-side').exists()).toBe(true)
    expect(tid(w, 'track-titles').find('[data-testid="track-side"]').exists()).toBe(false)
  })

  it('counts what is waiting for a condition without naming it', async () => {
    const w = mountIt(); await flushPromises()
    const group = tid(w, 'track-later-group')
    expect(group.text()).toContain('1')
    expect(group.findAll('[data-testid="track-item-encirclement-locked"]')).toHaveLength(1)
    expect(group.text().toLowerCase()).not.toContain('ouroboros')
  })

  it('wears an earned item: a title through the title route, a badge taken off through the flare selection', async () => {
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: ITEMS.map((i) => (i.key === 'first-light' ? { ...i, unlocked: true } : i)) })
    const w = mountIt(); await flushPromises()
    await tid(w, 'track-wear-first-light').trigger('click'); await flushPromises()
    expect(h.equip).toHaveBeenCalledWith('first-light')
    expect(tid(w, 'track-state-first-light').text()).toBe('Worn')
    await tid(w, 'track-wear-initiate').trigger('click'); await flushPromises()
    expect(h.wear).toHaveBeenCalledWith('corner', null)                        // it was worn: the press takes it off
  })

  it('shows the registry\'s sentence where a wear was refused', async () => {
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: ITEMS.map((i) => (i.key === 'first-light' ? { ...i, unlocked: true } : i)) })
    h.equip = vi.fn().mockRejectedValue({ response: { data: { detail: "You have not earned the 'first-light' title yet. Have your first change merged." } } })
    const w = mountIt(); await flushPromises()
    await tid(w, 'track-wear-first-light').trigger('click'); await flushPromises()
    expect(tid(w, 'track-err-first-light').text()).toContain('You have not earned')
  })

  it('shows the Commander plate to the commander flare tier alone', async () => {
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'track-commander').exists()).toBe(false)
    h.tier = 'commander'
    w = mountIt(); await flushPromises()
    expect(tid(w, 'track-commander').exists()).toBe(true)
    h.tier = 'founder'
    w = mountIt(); await flushPromises()
    expect(tid(w, 'track-commander').exists()).toBe(false)
  })

  it('has the Commander wear the COMMANDER title by default, and takes it off when he picks another', async () => {
    h.tier = 'commander'
    h.mine = vi.fn().mockResolvedValue({ ...MINE, items: ITEMS.map((i) => (i.key === 'first-light' ? { ...i, unlocked: true } : i)) })
    h.flare = vi.fn().mockResolvedValue({ data: { flare_tier: 'commander', flare_encirclement_variant: null, flare_corner_variant: null } })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-commander-worn').exists()).toBe(true)               // no title chosen: the plate is worn
    await tid(w, 'track-wear-first-light').trigger('click'); await flushPromises()
    expect(tid(w, 'track-commander-worn').exists()).toBe(false)              // he chose another
    await tid(w, 'track-wear-first-light').trigger('click'); await flushPromises()
    expect(tid(w, 'track-commander-worn').exists()).toBe(true)               // and took it off: back to the default
  })

  it('does not show the Commander worn line to anyone else', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-commander-worn').exists()).toBe(false)
  })

  it('gives a signed-out visitor the track with no progress, no wear buttons and a way in', async () => {
    h.signedIn = false
    const w = mountIt(); await flushPromises()
    expect(h.mine).not.toHaveBeenCalled()
    expect(tid(w, 'track-signin').exists()).toBe(true)
    expect(w.findAll('[data-testid^="track-wear-"]')).toHaveLength(0)
    expect(w.findAll('[data-state="blacked"]').length).toBe(ITEMS.length)       // no progress, so no unlocked item and no next title: every one is dark
    expect(tid(w, 'track-next-title').exists()).toBe(false)
  })

  it('says the track could not be read, with a retry, instead of an empty track', async () => {
    h.mine = vi.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValueOnce(MINE)
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-error').exists()).toBe(true)
    expect(tid(w, 'track-tiers').exists()).toBe(false)
    await tid(w, 'track-retry').trigger('click'); await flushPromises()
    expect(tid(w, 'track-tiers').exists()).toBe(true)
  })

  it('names the seasons the person won', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'track-seasons').text()).toContain('2026Q2')
  })
})
