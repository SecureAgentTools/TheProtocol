import { describe, it, expect } from 'vitest'
import { PZ_IDENTITY, PZ_MAX, PZ_MIN, clampScale, zoomAt, panBy, wheelFactor, distance, midpoint, transformCss } from './panZoom'

// Where a content point lands on screen under a transform (transform-origin 0 0).
const onScreen = (pz: { scale: number; x: number; y: number }, c: { x: number; y: number }) => ({
  x: pz.x + c.x * pz.scale,
  y: pz.y + c.y * pz.scale,
})
const toContent = (pz: { scale: number; x: number; y: number }, s: { x: number; y: number }) => ({
  x: (s.x - pz.x) / pz.scale,
  y: (s.y - pz.y) / pz.scale,
})

describe('zoomAt', () => {
  it('keeps the point under the cursor where it was', () => {
    let pz = { scale: 1.3, x: -40, y: 25 }
    const cursor = { x: 310, y: 190 }
    const c = toContent(pz, cursor)
    for (const f of [1.25, 1.25, 0.8, 3, 0.1]) {
      pz = zoomAt(pz, f, cursor.x, cursor.y)
      const s = onScreen(pz, c)
      expect(s.x).toBeCloseTo(cursor.x, 6)
      expect(s.y).toBeCloseTo(cursor.y, 6)
    }
  })

  it('stops at the limits and still keeps the anchor', () => {
    const big = zoomAt(PZ_IDENTITY, 1000, 100, 100)
    expect(big.scale).toBe(PZ_MAX)
    expect(onScreen(big, toContent(PZ_IDENTITY, { x: 100, y: 100 })).x).toBeCloseTo(100, 6)
    expect(zoomAt(PZ_IDENTITY, 0.0001, 0, 0).scale).toBe(PZ_MIN)
  })

  it('is undone by the inverse factor at the same point', () => {
    const a = { scale: 1, x: 12, y: -8 }
    const back = zoomAt(zoomAt(a, 2, 50, 60), 0.5, 50, 60)
    expect(back.scale).toBeCloseTo(1, 9)
    expect(back.x).toBeCloseTo(12, 9)
    expect(back.y).toBeCloseTo(-8, 9)
  })
})

describe('the rest', () => {
  it('pans by the pointer delta without touching the scale', () => {
    expect(panBy({ scale: 2, x: 1, y: 1 }, 5, -3)).toEqual({ scale: 2, x: 6, y: -2 })
  })

  it('clamps a bad scale to something drawable', () => {
    expect(clampScale(Number.NaN)).toBe(1)
    expect(clampScale(Infinity)).toBe(1)
    expect(clampScale(0.01)).toBe(PZ_MIN)
  })

  it('zooms in on wheel up, out on wheel down, and caps a violent flick', () => {
    expect(wheelFactor(-100)).toBeGreaterThan(1)
    expect(wheelFactor(100)).toBeLessThan(1)
    expect(wheelFactor(-3, 1)).toBeCloseTo(wheelFactor(-48, 0), 9) // lines are 16 px
    expect(wheelFactor(-100000)).toBeCloseTo(wheelFactor(-240), 9)
  })

  it('measures pinches', () => {
    expect(distance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5)
    expect(midpoint({ x: 0, y: 2 }, { x: 4, y: 6 })).toEqual({ x: 2, y: 4 })
  })

  it('writes a transform the browser accepts', () => {
    expect(transformCss({ scale: 1.5, x: 10, y: -4.25 })).toBe('translate(10.0px, -4.3px) scale(1.5000)')
  })
})
