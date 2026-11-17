import { describe, it, expect } from 'vitest'
import {
  DRAG_MAX_FRACTION, FALLBACK_PANE_PX, FULL_FRACTION, GROW_FRACTION, MIN_PX, NUDGE_PX, STORED_MAX_PX,
  composerSize, dragHeight, nudgeHeight, parseStoredHeight,
} from './composerSize'

/** V0662 (OurChat lane): the composer's height. BASE (f569f6a6e): composerSize.ts does not exist; the textarea is one line
 *  with a fixed 120 px ceiling, whatever the pane. */

describe('growing with the text', () => {
  it('is one line for a line of text', () => {
    expect(composerSize({ contentPx: 30, panePx: 800, mode: 'auto' })).toEqual({ heightPx: MIN_PX, scrolls: false })
    expect(composerSize({ contentPx: 0, panePx: 800, mode: 'auto' }).heightPx).toBe(MIN_PX)
  })

  it('follows the text up to 40% of the pane', () => {
    expect(composerSize({ contentPx: 200, panePx: 800, mode: 'auto' })).toEqual({ heightPx: 200, scrolls: false })
    const cap = Math.floor(800 * GROW_FRACTION)
    expect(composerSize({ contentPx: cap, panePx: 800, mode: 'auto' })).toEqual({ heightPx: cap, scrolls: false })
  })

  it('stops at 40% and scrolls inside itself past it', () => {
    const cap = Math.floor(800 * GROW_FRACTION)
    expect(composerSize({ contentPx: cap + 1, panePx: 800, mode: 'auto' })).toEqual({ heightPx: cap, scrolls: true })
    expect(composerSize({ contentPx: 5000, panePx: 800, mode: 'auto' })).toEqual({ heightPx: cap, scrolls: true })
  })

  it('takes the 40% of THIS pane: a short pane caps lower, a tall one higher', () => {
    expect(composerSize({ contentPx: 5000, panePx: 500, mode: 'auto' }).heightPx).toBe(200)
    expect(composerSize({ contentPx: 5000, panePx: 1000, mode: 'auto' }).heightPx).toBe(400)
  })

  it('never goes under one line, even in a pane too small to hold 40% of it', () => {
    expect(composerSize({ contentPx: 5000, panePx: 60, mode: 'auto' }).heightPx).toBe(MIN_PX)
  })

  it('takes an unmeasured pane as a fallback height, not as zero', () => {
    const cap = Math.floor(FALLBACK_PANE_PX * GROW_FRACTION)
    expect(composerSize({ contentPx: 5000, panePx: 0, mode: 'auto' }).heightPx).toBe(cap)
    expect(composerSize({ contentPx: 5000, panePx: NaN, mode: 'auto' }).heightPx).toBe(cap)
  })
})

describe('the height a hand chose', () => {
  it('holds the dragged height whatever the text', () => {
    expect(composerSize({ contentPx: 30, panePx: 800, mode: 'manual', manualPx: 300 })).toEqual({ heightPx: 300, scrolls: false })
    expect(composerSize({ contentPx: 900, panePx: 800, mode: 'manual', manualPx: 300 })).toEqual({ heightPx: 300, scrolls: true })
  })

  it('cannot be dragged past 70% of the pane, nor under one line', () => {
    expect(composerSize({ contentPx: 30, panePx: 800, mode: 'manual', manualPx: 9999 }).heightPx).toBe(Math.floor(800 * DRAG_MAX_FRACTION))
    expect(composerSize({ contentPx: 30, panePx: 800, mode: 'manual', manualPx: 3 }).heightPx).toBe(MIN_PX)
  })

  it('falls back to growing when manual mode has no height', () => {
    expect(composerSize({ contentPx: 200, panePx: 800, mode: 'manual', manualPx: null }).heightPx).toBe(200)
  })

  it('shrinks with a smaller pane, so a stored height cannot swallow a short window', () => {
    expect(composerSize({ contentPx: 30, panePx: 400, mode: 'manual', manualPx: 500 }).heightPx).toBe(Math.floor(400 * DRAG_MAX_FRACTION))
  })
})

describe('the full-height editor', () => {
  it('takes 85% of the pane whatever the text', () => {
    expect(composerSize({ contentPx: 30, panePx: 800, mode: 'full' })).toEqual({ heightPx: Math.floor(800 * FULL_FRACTION), scrolls: false })
    expect(composerSize({ contentPx: 5000, panePx: 800, mode: 'full' }).scrolls).toBe(true)
  })

  it('beats a dragged height while it is on', () => {
    expect(composerSize({ contentPx: 30, panePx: 800, mode: 'full', manualPx: 200 }).heightPx).toBe(Math.floor(800 * FULL_FRACTION))
  })
})

describe('the drag', () => {
  it('makes it taller as the pointer moves up, shorter as it moves down', () => {
    expect(dragHeight(100, 500, 450, 800)).toBe(150)
    expect(dragHeight(100, 500, 540, 800)).toBe(60)
  })

  it('is held between one line and 70% of the pane', () => {
    expect(dragHeight(100, 500, 0, 800)).toBe(Math.floor(800 * DRAG_MAX_FRACTION))
    expect(dragHeight(100, 500, 900, 800)).toBe(MIN_PX)
  })

  it('does not move without the pointer moving', () => {
    expect(dragHeight(123, 500, 500, 800)).toBe(123)
  })
})

describe('the keyboard on the handle', () => {
  it('steps up and down by a fixed amount, inside the same bounds', () => {
    expect(nudgeHeight(100, 'up', 800)).toBe(100 + NUDGE_PX)
    expect(nudgeHeight(100, 'down', 800)).toBe(100 - NUDGE_PX)
    expect(nudgeHeight(MIN_PX, 'down', 800)).toBe(MIN_PX)
    expect(nudgeHeight(Math.floor(800 * DRAG_MAX_FRACTION), 'up', 800)).toBe(Math.floor(800 * DRAG_MAX_FRACTION))
  })
})

describe('the stored height', () => {
  it('reads a plausible whole number', () => {
    expect(parseStoredHeight('260')).toBe(260)
    expect(parseStoredHeight(' 260 ')).toBe(260)
    expect(parseStoredHeight(String(MIN_PX))).toBe(MIN_PX)
    expect(parseStoredHeight(String(STORED_MAX_PX))).toBe(STORED_MAX_PX)
  })

  it('ignores anything else, so a damaged value cannot pin a strange size', () => {
    for (const bad of [null, undefined, '', 'abc', '12.5', '-80', '43', '4001', '99999', '1e3', '0x40']) {
      expect(parseStoredHeight(bad as string | null | undefined)).toBeNull()
    }
  })
})
