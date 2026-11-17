/**
 * V0666 (session-lead, room seq 4954 item 4): the console suite dismisses an unlock celebration when one appears, so a REAL unlock can never block a
 * proof again (V0665's sandbox pass met one on his Sandbox Beta Admin account, whose Track holds 44 unlocks). The guard is a self-contained script the
 * suite injects into every page (e2e/suite/support/overlays.ts): it presses the celebration's own Close the moment the overlay appears, whatever the
 * lifecycle is doing (an action, an assertion, a read), and says so (a binding the suite turns into a test annotation and a word in the page-clean row),
 * never silently. A lifecycle ABOUT the celebration opts out by its title tag. Run here against the real component in the same DOM the script sees.
 * Red before: e2e/suite/support/overlays.ts does not exist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ track: null as any, push: vi.fn() }))
vi.mock('@/services/api/contributorTrack', () => ({ getMyTrack: (...a: any[]) => h.track(...a) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: true, user: { id: 7, name: 'Ada Lovelace' } }) }))

import UnlockCelebration from './UnlockCelebration.vue'
import { resetChecked } from '@/services/contributorTrackView'      // V0665 keeps "the track was read this page load" in memory, not in sessionStorage
import { BINDING, OPT_OUT_TAG, overlayGuardScript, overlayNote } from '../../../e2e/suite/support/overlays'

const it_ = (o: Record<string, any>) => ({ kind: 'corner', key: 'initiate', tier: 1, side: false, condition: 'Propose your first change.', unlocked: true, progress: { n: 1, of: 1 }, later: null, ...o })
const stubs = { EarnedRing: true, EarnedBadge: true, TitleEmblem: true }
const q = (id: string) => document.body.querySelector(`[data-testid="${id}"]`) as HTMLElement | null

describe('the suite\'s overlay guard', () => {
  let said: string[]
  let stop: (() => void) | void
  beforeEach(() => {
    document.body.innerHTML = ''; localStorage.clear(); sessionStorage.clear(); resetChecked(); h.push.mockClear()
    said = []
    ;(window as any)[BINDING] = (what: string) => { said.push(what) }
    h.track = vi.fn().mockResolvedValue({ items: [it_({}), it_({ kind: 'encirclement', key: 'lantern', tier: 2 })], equipped_title: null, season_wins: [], counts: {} })
  })
  afterEach(() => { if (typeof stop === 'function') stop(); stop = undefined; delete (window as any)[BINDING] })

  it('closes the celebration the moment it opens, as a person presses Close: what it showed is remembered, the track is not opened, and it says so', async () => {
    stop = overlayGuardScript(BINDING)
    const w = mount(UnlockCelebration, { attachTo: document.body, global: { stubs } }); await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    expect(JSON.parse(localStorage.getItem('ct_seen_7')!).sort()).toEqual(['corner:initiate', 'encirclement:lantern'])
    expect(h.push).not.toHaveBeenCalled()
    expect(said).toEqual(['unlock-celebration'])
    w.unmount()
  })

  it('without the guard the same celebration stays up (the control: this is the overlay that blocked a proof)', async () => {
    const w = mount(UnlockCelebration, { attachTo: document.body, global: { stubs } }); await flushPromises()
    expect(q('unlock-celebration')).not.toBeNull()
    expect(said).toEqual([])
    w.unmount()
  })

  it('closes one that is already on the page when the guard starts, and one that opens later', async () => {
    const w = mount(UnlockCelebration, { attachTo: document.body, global: { stubs } }); await flushPromises()
    expect(q('unlock-celebration')).not.toBeNull()
    stop = overlayGuardScript(BINDING)
    await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    w.unmount(); sessionStorage.clear(); resetChecked(); localStorage.clear(); document.body.innerHTML = ''
    h.track = vi.fn().mockResolvedValue({ items: [it_({ key: 'second', condition: 'a later one' })], equipped_title: null, season_wins: [], counts: {} })
    const w2 = mount(UnlockCelebration, { attachTo: document.body, global: { stubs } }); await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    expect(said).toEqual(['unlock-celebration', 'unlock-celebration'])
    w2.unmount()
  })

  it('does nothing, and says nothing, when no celebration appears; and leaves any other overlay alone', async () => {
    stop = overlayGuardScript(BINDING)
    h.track = vi.fn().mockResolvedValue({ items: [it_({ unlocked: false })], equipped_title: null, season_wins: [], counts: {} })
    const other = document.createElement('div'); other.setAttribute('data-testid', 'some-other-dialog'); other.innerHTML = '<button data-testid="unlock-close">not ours</button>'
    document.body.appendChild(other)
    const w = mount(UnlockCelebration, { attachTo: document.body, global: { stubs } }); await flushPromises()
    expect(said).toEqual([])
    expect(q('some-other-dialog')).not.toBeNull()
    w.unmount()
  })

  it('stops when told to (a lifecycle that is about the celebration opts out and never installs it)', async () => {
    const off = overlayGuardScript(BINDING) as () => void
    off()
    const w = mount(UnlockCelebration, { attachTo: document.body, global: { stubs } }); await flushPromises()
    expect(q('unlock-celebration')).not.toBeNull()
    expect(said).toEqual([])
    w.unmount()
  })

  it('names the opt-out tag and words each dismissal for the run\'s record', () => {
    expect(OPT_OUT_TAG).toBe('@unlock-celebration')
    expect(overlayNote([])).toBe('')
    expect(overlayNote(['unlock-celebration'])).toBe(', 1 overlay dismissed (unlock-celebration)')
    expect(overlayNote(['unlock-celebration', 'unlock-celebration'])).toBe(', 2 overlays dismissed (unlock-celebration x2)')
  })
})
