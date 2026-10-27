import { describe, it, expect } from 'vitest'
import { routeAround, minDistanceToCurve, closestOnSegment, bezierAt, type Obstacle } from './arcRoute'

const V = (x: number, y: number, z: number) => ({ x, y, z })
/** What the stage builds today: midpoint lifted in Y by 28% of the span + 4. */
function naiveControl(from: any, to: any) {
  const mid = V((from.x + to.x) / 2, (from.y + to.y) / 2, (from.z + to.z) / 2)
  const span = Math.hypot(to.x - from.x, to.y - from.y, to.z - from.z)
  mid.y += span * 0.28 + 4
  return mid
}

describe('arcRoute', () => {
  it('proves the DEFECT first: the naive arc passes through a registry in the way', () => {
    const from = V(-100, 0, 0), to = V(100, 0, 0)
    const b: Obstacle = { pos: V(0, 30, 0), radius: 8 }   // sits on the lifted apex
    const naive = naiveControl(from, to)
    // The apex of the naive curve is at y = (0 + 2*32 + 0)/4 = 16... place the
    // obstacle where the curve actually goes, so the test is about the curve.
    const apex = bezierAt(from, naive, to, 0.5)
    const onPath: Obstacle = { pos: apex, radius: 8 }
    expect(minDistanceToCurve(from, naive, to, onPath.pos)).toBeLessThan(onPath.radius)
    expect(b.radius).toBe(8)
  })

  it('a synthetic A -> C arc crossing B clears B at EVERY sampled point', () => {
    const A = V(-120, 0, 0), C = V(120, 0, 0)
    const base = naiveControl(A, C)
    // Put B exactly where the naive curve flies.
    const B: Obstacle = { pos: bezierAt(A, base, C, 0.5), radius: 10 }
    expect(minDistanceToCurve(A, base, C, B.pos)).toBeLessThan(B.radius) // defect confirmed

    const r = routeAround(A, C, base, [B], 3)
    expect(r.deflectedAround).toBe(B)
    // The gate: 200 samples, none inside the sphere + margin.
    for (let i = 0; i <= 200; i++) {
      const p = bezierAt(A, r.control, C, i / 200)
      const d = Math.hypot(p.x - B.pos.x, p.y - B.pos.y, p.z - B.pos.z)
      expect(d).toBeGreaterThanOrEqual(B.radius)
    }
  })

  it('leaves a clear path COMPLETELY unchanged', () => {
    const from = V(-50, 0, 0), to = V(50, 0, 0)
    const base = naiveControl(from, to)
    const far: Obstacle = { pos: V(0, -400, 0), radius: 8 }
    const r = routeAround(from, to, base, [far], 3)
    expect(r.control).toBe(base)          // identity, not a copy that happens to match
    expect(r.deflectedAround).toBeNull()
    expect(r.pushed).toBe(0)
  })

  it('never tries to avoid the registry it is arriving at', () => {
    const from = V(-80, 0, 0), to = V(0, 0, 0)
    const base = naiveControl(from, to)
    const dest: Obstacle = { pos: V(0, 0, 0), radius: 8 }
    const r = routeAround(from, to, base, [dest], 3)
    expect(r.deflectedAround).toBeNull()
  })

  it('ignores obstacles beyond the ends of the path', () => {
    const from = V(0, 0, 0), to = V(60, 0, 0)
    const base = naiveControl(from, to)
    const behind: Obstacle = { pos: V(-40, 0, 0), radius: 9 }
    const beyond: Obstacle = { pos: V(140, 0, 0), radius: 9 }
    expect(routeAround(from, to, base, [behind, beyond], 3).deflectedAround).toBeNull()
  })

  it('handles an obstacle dead centre on the line (no unique escape direction)', () => {
    const from = V(-100, 0, 0), to = V(100, 0, 0)
    // Control point straight along the chord => a degenerate, perfectly flat arc.
    const flat = V(0, 0, 0)
    const B: Obstacle = { pos: V(0, 0, 0), radius: 12 }
    const r = routeAround(from, to, flat, [B], 2)
    expect(r.deflectedAround).toBe(B)
    for (let i = 0; i <= 100; i++) {
      const p = bezierAt(from, r.control, to, i / 100)
      expect(Math.hypot(p.x - B.pos.x, p.y - B.pos.y, p.z - B.pos.z)).toBeGreaterThanOrEqual(B.radius)
    }
  })

  it('deflects around the DEEPEST offender when several are near', () => {
    const from = V(-150, 0, 0), to = V(150, 0, 0)
    const base = naiveControl(from, to)
    const apex = bezierAt(from, base, to, 0.5)
    const shallow: Obstacle = { pos: { ...apex, y: apex.y + 14 }, radius: 8 }
    const deep: Obstacle = { pos: apex, radius: 14 }
    const r = routeAround(from, to, base, [shallow, deep], 3)
    expect(r.deflectedAround).toBe(deep)
  })

  it('empty / zero-radius obstacle lists are a no-op, never a throw', () => {
    const from = V(0, 0, 0), to = V(10, 0, 0)
    const base = naiveControl(from, to)
    expect(routeAround(from, to, base, [], 3).control).toBe(base)
    expect(routeAround(from, to, base, [{ pos: V(5, 0, 0), radius: 0 }], 3).deflectedAround).toBeNull()
  })

  it('closestOnSegment clamps to the segment, it does not extend the line', () => {
    const a = V(0, 0, 0), b = V(10, 0, 0)
    expect(closestOnSegment(a, b, V(-5, 0, 0)).t).toBe(0)
    expect(closestOnSegment(a, b, V(50, 0, 0)).t).toBe(1)
    expect(closestOnSegment(a, b, V(5, 3, 0)).dist).toBeCloseTo(3, 6)
  })
})
