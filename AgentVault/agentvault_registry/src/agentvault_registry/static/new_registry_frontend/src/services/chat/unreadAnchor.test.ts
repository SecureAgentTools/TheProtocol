import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ANCHOR_MS, keepAnchored } from './unreadAnchor'

/**
 * V0654 (session-lead, the sessions' room seq 937-949; check 140 of V0653's console proof): the open's scroll to the NEW
 * line is held while the thread settles. A size change of the scroll area or of a message in it re-runs the scroll; the
 * reader's own move (anywhere in the thread) or ANCHOR_MS ends it, and then nothing re-runs.
 */
class FakeRO {
  static all: FakeRO[] = []
  observed: Element[] = []
  disconnected = false
  constructor(public cb: ResizeObserverCallback) { FakeRO.all.push(this) }
  observe(el: Element) { this.observed.push(el) }
  unobserve() {}
  disconnect() { this.disconnected = true }
  /** what the browser does when an observed box changes size */
  fire() { if (!this.disconnected) this.cb([], this as unknown as ResizeObserver) }
}

function thread() {
  const root = document.createElement('div')
  const scroller = document.createElement('div')
  const a = document.createElement('div')
  const b = document.createElement('div')
  scroller.append(a, b)
  const composer = document.createElement('textarea')
  root.append(scroller, composer)
  document.body.append(root)
  return { root, scroller, composer, a, b }
}

describe('the NEW line is held while the thread settles', () => {
  beforeEach(() => { FakeRO.all = []; vi.stubGlobal('ResizeObserver', FakeRO); vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); document.body.innerHTML = '' })

  it('a size change of the scroll area or of a message in it re-runs the scroll', () => {
    const { scroller, a, b } = thread()
    const reanchor = vi.fn()
    const anchor = keepAnchored(scroller, reanchor)
    expect(anchor.active()).toBe(true)
    const ro = FakeRO.all[0]
    expect(ro.observed, 'the scroll area and what is in it at the open').toEqual([scroller, a, b])
    ro.fire(); ro.fire()
    expect(reanchor).toHaveBeenCalledTimes(2)
  })

  it('ends after ANCHOR_MS: nothing re-runs, the observer is gone', () => {
    const { scroller } = thread()
    const reanchor = vi.fn()
    const anchor = keepAnchored(scroller, reanchor)
    vi.advanceTimersByTime(ANCHOR_MS - 1)
    expect(anchor.active()).toBe(true)
    vi.advanceTimersByTime(1)
    expect(anchor.active()).toBe(false)
    expect(FakeRO.all[0].disconnected).toBe(true)
    FakeRO.all[0].fire()
    expect(reanchor).not.toHaveBeenCalled()
  })

  for (const ev of ['wheel', 'touchstart', 'keydown', 'pointerdown']) {
    it(`the reader's ${ev} anywhere in the thread ends it at once (the composer too)`, () => {
      const { root, scroller, composer } = thread()
      const reanchor = vi.fn()
      const anchor = keepAnchored(scroller, reanchor, ANCHOR_MS, root)
      composer.dispatchEvent(new Event(ev, { bubbles: true }))
      expect(anchor.active()).toBe(false)
      FakeRO.all[0].fire()
      expect(reanchor).not.toHaveBeenCalled()
    })
  }

  it('a move outside the thread does not end it; without a root given, the scroll area is the thread', () => {
    const { root, scroller, composer } = thread()
    const outside = document.createElement('nav')
    document.body.append(outside)
    const held = keepAnchored(scroller, vi.fn(), ANCHOR_MS, root)
    outside.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(held.active(), 'a press on the list beside the thread').toBe(true)
    const own = keepAnchored(scroller, vi.fn())
    composer.dispatchEvent(new Event('keydown', { bubbles: true }))
    expect(own.active(), 'a key outside the scroll area, no root given').toBe(true)
    scroller.dispatchEvent(new Event('wheel', { bubbles: true }))
    expect(own.active()).toBe(false)
    held.stop()
  })

  it('stop is safe twice, removes its listeners and its timer', () => {
    const { root, scroller } = thread()
    const remove = vi.spyOn(root, 'removeEventListener')
    const anchor = keepAnchored(scroller, vi.fn(), ANCHOR_MS, root)
    anchor.stop(); anchor.stop()
    expect(remove).toHaveBeenCalledTimes(4)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('no ResizeObserver: nothing is held (the open scrolls once, as before)', () => {
    vi.stubGlobal('ResizeObserver', undefined)
    const { scroller } = thread()
    const anchor = keepAnchored(scroller, vi.fn())
    expect(anchor.active()).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
})
