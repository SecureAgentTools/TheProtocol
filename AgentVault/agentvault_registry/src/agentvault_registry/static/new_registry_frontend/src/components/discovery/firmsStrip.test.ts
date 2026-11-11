/**
 * V0658 (v), item 2 (the maintainer's review, sessions' room seq 2181: "you cant filter out firms"): Discovery's filters
 * get a control that hides the Firms strip, remembered like the frame filter (in the address, so a reload and a shared
 * link agree) and kept in this browser (a strip a person hides stays hidden on the next visit). A visit is not a choice:
 * arriving on a link that says firms=hide hides the strip for that view without changing what this browser keeps.
 * Hidden, the page says what it withheld and carries the switch back (a removed strip must not read as "no firms");
 * Clear All Filters brings the strip back. The composable is tested here; Discovery.vue's wiring is read from its
 * source (the view is too large to mount here, like the sidebar).
 * RED on 553347408 (origin/v0657/cut): the module does not exist and Discovery mounts the strip unconditionally.
 *
 * The review of 4914af776 added three cases (RED there):
 *  - the landing page mounts Discovery embedded (LandingDiscovery): there the kept choice is read and the address is
 *    never touched (on '/', a rewritten query turned the address into '/?firms=hide' and the router's scroll-to-top
 *    jumped the landing page when the preview mounted);
 *  - an ask for one firm (the voice door "hire the firm X" lands on /discover?firm=X) shows the strip for that view,
 *    since the lane it opens is the strip; the lane consuming the ask leaves it shown; nothing is kept;
 *  - hiding the strip drops a pending ask from the address, or the next arrival would show it again.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h as render, nextTick, reactive } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import fs from 'node:fs'
import path from 'node:path'

const r = vi.hoisted(() => ({ route: { query: {} as Record<string, any> }, replace: vi.fn(async (_: any) => {}) }))
vi.mock('vue-router', () => ({ useRoute: () => r.route, useRouter: () => ({ replace: r.replace }) }))

import { FIRMS_HIDDEN_KEY, firmsHiddenOnArrival, useFirmsStrip } from './firmsStrip'

function host(opts?: Parameters<typeof useFirmsStrip>[0]) {
  let api: ReturnType<typeof useFirmsStrip> | null = null
  const C = defineComponent({ setup() { api = useFirmsStrip(opts); return () => render('div') } })
  const w = mount(C)
  return { w, api: api! }
}

describe('the Firms strip control', () => {
  beforeEach(() => { localStorage.clear(); r.replace.mockClear(); r.route = reactive({ query: {} }) })
  afterEach(() => { localStorage.clear() })

  it('on arrival: the address first (hide or show), else what this browser kept', () => {
    expect(firmsHiddenOnArrival(undefined, null)).toBe(false)
    expect(firmsHiddenOnArrival(undefined, '1')).toBe(true)
    expect(firmsHiddenOnArrival('hide', null)).toBe(true)
    expect(firmsHiddenOnArrival('show', '1')).toBe(false)
    expect(firmsHiddenOnArrival('anything', null)).toBe(false)
  })

  it('hiding remembers the choice in this browser and in the address; showing forgets both', async () => {
    r.route = reactive({ query: { frames: 'EU' } })
    const { api } = host()
    expect(api.hidden.value).toBe(false)
    api.setHidden(true)
    expect(api.hidden.value).toBe(true)
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY)).toBe('1')
    expect(r.replace).toHaveBeenLastCalledWith({ query: { frames: 'EU', firms: 'hide' } })
    r.route.query = { frames: 'EU', firms: 'hide' }
    api.setHidden(false)
    expect(api.hidden.value).toBe(false)
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY)).toBeNull()
    expect(r.replace).toHaveBeenLastCalledWith({ query: { frames: 'EU' } })
  })

  it('a kept choice hides the strip on the next visit, and the address says so', async () => {
    localStorage.setItem(FIRMS_HIDDEN_KEY, '1')
    const { api } = host()
    expect(api.hidden.value).toBe(true)
    await flushPromises(); await nextTick()
    expect(r.replace).toHaveBeenCalledWith({ query: { firms: 'hide' } })
  })

  it('an address that changes under the same view decides again, like an arrival', async () => {
    localStorage.setItem(FIRMS_HIDDEN_KEY, '1')
    r.route = reactive({ query: { firms: 'hide' } })
    const { api } = host()
    r.route.query = { firms: 'show' }
    await nextTick()
    expect(api.hidden.value, 'a link that says show shows it').toBe(false)
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY), 'and changes nothing kept').toBe('1')
    r.replace.mockClear()
    r.route.query = {}
    await nextTick()
    expect(api.hidden.value, 'an address that says nothing: the kept choice').toBe(true)
    expect(r.replace).toHaveBeenLastCalledWith({ query: { firms: 'hide' } })
  })

  it('an ask for one firm shows the strip for that view, and the kept choice is left alone', async () => {
    expect(firmsHiddenOnArrival(undefined, '1', 'reach')).toBe(false)
    expect(firmsHiddenOnArrival('hide', '1', 'Reach Limited')).toBe(false)
    expect(firmsHiddenOnArrival(undefined, '1', '')).toBe(true)
    expect(firmsHiddenOnArrival(undefined, '1', ['reach'])).toBe(true)
    localStorage.setItem(FIRMS_HIDDEN_KEY, '1')
    r.route = reactive({ query: { firm: 'reach' } })
    const { api } = host()
    expect(api.hidden.value, 'the lane the ask opens is the strip').toBe(false)
    await flushPromises(); await nextTick()
    expect(r.replace, 'the address is not rewritten to hide what the ask shows').not.toHaveBeenCalled()
    r.route.query = {}
    await nextTick()
    expect(api.hidden.value, 'the lane consuming the ask leaves the strip shown in this view').toBe(false)
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY), 'and nothing kept changes').toBe('1')
  })

  it('an ask that arrives under the same view shows a hidden strip', async () => {
    localStorage.setItem(FIRMS_HIDDEN_KEY, '1')
    r.route = reactive({ query: { firms: 'hide' } })
    const { api } = host()
    expect(api.hidden.value).toBe(true)
    r.route.query = { firm: 'reach' }
    await nextTick()
    expect(api.hidden.value).toBe(false)
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY)).toBe('1')
  })

  it('hiding the strip drops a pending ask from the address', async () => {
    r.route = reactive({ query: { frames: 'EU', firm: 'reach' } })
    const { api } = host()
    api.setHidden(true)
    expect(r.replace).toHaveBeenLastCalledWith({ query: { frames: 'EU', firms: 'hide' } })
    r.replace.mockClear()
    r.route = reactive({ query: { firms: 'hide', firm: 'reach' } })
    const second = host().api
    second.setHidden(true)
    expect(r.replace, 'the address says hide already; the ask still goes').toHaveBeenLastCalledWith({ query: { firms: 'hide' } })
  })

  it('embedded (the landing page\'s preview): the kept choice is read and the address is never touched', async () => {
    localStorage.setItem(FIRMS_HIDDEN_KEY, '1')
    r.route = reactive({ query: { firms: 'show', ref: 'x' } })
    const { api } = host({ address: false })
    expect(api.hidden.value, 'the kept choice, not the address').toBe(true)
    await flushPromises(); await nextTick()
    r.route.query = { ref: 'y' }
    await nextTick()
    r.route.query = { firm: 'reach' }
    await nextTick()
    api.setHidden(false)
    expect(api.hidden.value).toBe(false)
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY)).toBeNull()
    expect(r.replace, 'never on mount, on a route change or on a choice').not.toHaveBeenCalled()
  })

  it('a link that says hide is not a choice this browser keeps', async () => {
    r.route = reactive({ query: { firms: 'hide' } })
    const { api } = host()
    expect(api.hidden.value).toBe(true)
    await flushPromises()
    expect(localStorage.getItem(FIRMS_HIDDEN_KEY)).toBeNull()
    expect(r.replace, 'the address already says it').not.toHaveBeenCalled()
  })
})

describe("Discovery's wiring of the control (read from the view's source)", () => {
  const src = fs.readFileSync(path.resolve(__dirname, '../../views/Discovery.vue'), 'utf8')

  it('the strip mounts only while it is not hidden, and a hidden strip says so with the way back', () => {
    expect(src).toMatch(/<FirmsLane v-if="!firmsHidden" @engage="viewAgentByDID" \/>/)
    const note = src.match(/<p v-else-if="!embedded"[^>]*data-testid="disc-firms-hidden"[^>]*>([\s\S]*?)<\/p>/)
    expect(note, 'the hidden note').not.toBeNull()
    expect(note![1]).toMatch(/@click="setFirmsHidden\(false\)"/)
  })

  it('the filters carry the control, and Clear All Filters brings the strip back', () => {
    const box = src.match(/<label[^>]*data-testid="disc-firms-filter"[^>]*>([\s\S]*?)<\/label>/)
    expect(box, 'the control in the filter panel').not.toBeNull()
    expect(box![1]).toMatch(/type="checkbox"/)
    expect(box![1]).toMatch(/:checked="firmsHidden"/)
    expect(box![1]).toMatch(/@change="onFirmsFilter"/)
    const clear = src.match(/function clearAllFilters\(\) \{([\s\S]*?)\n\}/)
    expect(clear, 'clearAllFilters').not.toBeNull()
    expect(clear![1]).toContain('setFirmsHidden(false)')
    // the landing page mounts this view embedded: there the strip reads the kept choice and never writes the address
    expect(src).toMatch(/useFirmsStrip\(\{ address: !props\.embedded \}\)/)
  })
})
