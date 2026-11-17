/**
 * V0665: the contributor track's celebration. It opens once for what is newly earned and not yet shown on this device (never for a signed-out visitor, never twice in a
 * page load, never for an item already shown), remembers what it showed, opens the track or closes, and never raises an error when the track cannot be read.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ signedIn: true, userId: 7, track: null as any, push: vi.fn() }))
vi.mock('@/services/api/contributorTrack', () => ({ getMyTrack: (...a: any[]) => h.track(...a) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: h.signedIn, user: { id: h.userId, name: 'Ada Lovelace' } }) }))

import UnlockCelebration from './UnlockCelebration.vue'
import { resetChecked } from '@/services/contributorTrackView'

const it_ = (o: Record<string, any>) => ({ kind: 'corner', key: 'initiate', tier: 1, side: false, condition: 'Propose your first change.', unlocked: false, progress: { n: 0, of: 1 }, later: null, ...o })
const stubs = { EarnedRing: true, EarnedBadge: true, TitleEmblem: true }
const mountIt = () => mount(UnlockCelebration, { attachTo: document.body, global: { stubs } })
const q = (id: string) => document.body.querySelector(`[data-testid="${id}"]`) as HTMLElement | null

describe('the unlock celebration', () => {
  beforeEach(() => {
    document.body.innerHTML = ''; localStorage.clear(); sessionStorage.clear(); resetChecked(); h.signedIn = true; h.userId = 7; h.push.mockClear()
    h.track = vi.fn().mockResolvedValue({ items: [it_({ unlocked: true }), it_({ kind: 'encirclement', key: 'lantern', tier: 2, unlocked: true }), it_({ kind: 'title', key: 'first-light', tier: null })], equipped_title: null, season_wins: [], counts: {} })
  })

  it('opens for what is earned and not yet shown, and lists each earned item (not the locked one)', async () => {
    const w = mountIt(); await flushPromises()
    expect(q('unlock-celebration')).not.toBeNull()
    expect(q('unlock-item-initiate')).not.toBeNull(); expect(q('unlock-item-lantern')).not.toBeNull(); expect(q('unlock-item-first-light')).toBeNull()
    expect(document.body.textContent).toContain('2 new items unlocked')
    w.unmount()
  })

  it('remembers what it showed: closing writes the seen set, and the next session shows nothing new', async () => {
    let w = mountIt(); await flushPromises()
    q('unlock-close')!.click(); await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    expect(JSON.parse(localStorage.getItem('ct_seen_7')!).sort()).toEqual(['corner:initiate', 'encirclement:lantern'])
    w.unmount(); resetChecked(); sessionStorage.clear(); document.body.innerHTML = ''
    w = mountIt(); await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    w.unmount()
  })

  it('opens the track from the button and remembers too', async () => {
    const w = mountIt(); await flushPromises()
    q('unlock-open')!.click(); await flushPromises()
    expect(h.push).toHaveBeenCalledWith({ name: 'code-changes-track' })
    expect(localStorage.getItem('ct_seen_7')).toContain('corner:initiate')
    w.unmount()
  })

  it('reads the track once per page load, and writes nothing to session storage for it (the cookie policy lists no such key)', async () => {
    let w = mountIt(); await flushPromises(); w.unmount(); document.body.innerHTML = ''
    w = mountIt(); await flushPromises()
    expect(h.track).toHaveBeenCalledTimes(1)
    expect(sessionStorage.length).toBe(0)
    w.unmount()
  })

  it('reads again for another signed-in developer on the same page load', async () => {
    let w = mountIt(); await flushPromises(); w.unmount(); document.body.innerHTML = ''
    h.userId = 8
    w = mountIt(); await flushPromises()
    expect(h.track).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('does nothing for a visitor and nothing visible when the track cannot be read', async () => {
    h.signedIn = false
    let w = mountIt(); await flushPromises()
    expect(h.track).not.toHaveBeenCalled(); expect(q('unlock-celebration')).toBeNull(); w.unmount()
    h.signedIn = true; resetChecked(); sessionStorage.clear(); h.track = vi.fn().mockRejectedValue(new Error('503'))
    w = mountIt(); await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    w.unmount()
  })

  it('closes on Escape', async () => {
    const w = mountIt(); await flushPromises()
    q('unlock-celebration')!.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await flushPromises()
    expect(q('unlock-celebration')).toBeNull()
    w.unmount()
  })
})
