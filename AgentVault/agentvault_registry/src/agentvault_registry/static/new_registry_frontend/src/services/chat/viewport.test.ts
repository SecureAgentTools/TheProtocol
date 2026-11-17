import { describe, it, expect } from 'vitest'
import { KEYBOARD_MIN_PX, keyboardInset, pinnedBounds } from './viewport'

/** V0662 (OurChat lane): the thread stays above the phone's keyboard. BASE (bca169627): the module does not exist. */

describe('how much the keyboard hides', () => {
  it('is the layout viewport less the visible one and its offset', () => {
    expect(keyboardInset(800, 500, 0)).toBe(300)
    expect(keyboardInset(800, 500, 40)).toBe(260)
  })
  it('is zero with nothing hidden, with a larger visible viewport, or with missing facts', () => {
    expect(keyboardInset(800, 800, 0)).toBe(0)
    expect(keyboardInset(800, 900, 0)).toBe(0)
    expect(keyboardInset(800, null, null)).toBe(0)
    expect(keyboardInset(NaN, 500, 0)).toBe(0)
    expect(keyboardInset(800, NaN, 0)).toBe(0)
  })
})

describe('bounding the thread', () => {
  const base = { innerH: 800, topPx: 88, bottomPx: 83 }
  it('with no keyboard is what it was: the top and the bottom space the page keeps', () => {
    expect(pinnedBounds({ ...base, vvH: 800, vvTop: 0 })).toEqual({ keyboard: false, visibleBottomPx: null, offsetPx: 171 })
    expect(pinnedBounds({ ...base, vvH: null, vvTop: null })).toEqual({ keyboard: false, visibleBottomPx: null, offsetPx: 171 })
  })
  it('a collapsing address bar is not a keyboard', () => {
    expect(pinnedBounds({ ...base, vvH: 800 - (KEYBOARD_MIN_PX - 1), vvTop: 0 }).keyboard).toBe(false)
  })
  it('with a keyboard it is the visible area: its bottom edge, the top only taken off, the tab bar\'s space not kept', () => {
    expect(pinnedBounds({ ...base, vvH: 480, vvTop: 0 })).toEqual({ keyboard: true, visibleBottomPx: 480, offsetPx: 88 })
  })
  it('follows the visible area when the browser scrolled the page to the caret', () => {
    expect(pinnedBounds({ ...base, vvH: 480, vvTop: 60 })).toEqual({ keyboard: true, visibleBottomPx: 540, offsetPx: 88 })
  })
  it('is exactly the keyboard threshold at the edge', () => {
    expect(pinnedBounds({ ...base, vvH: 800 - KEYBOARD_MIN_PX, vvTop: 0 }).keyboard).toBe(true)
  })
})
