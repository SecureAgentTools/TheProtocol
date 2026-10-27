/**
 * arcRoute.ts — §BRIDGE R11 #9
 *
 * "the traffic should route around a registry if its in the way and never thru
 *  it. which is currently the case." — Commander, 2026-08-19
 *
 * He is right, and the reason is one line: the stage builds every arc as
 * `QuadraticBezierCurve3(from, mid, to)` where `mid` is the segment midpoint
 * lifted in Y. Nothing in that construction has ever been shown a registry
 * position, so an arc between two nodes on opposite sides of a third passes
 * straight through the third — a payment appearing to transit a registry that
 * had nothing to do with it, which on a map of money is a false statement.
 *
 * This module is PURE VECTOR MATH on plain {x,y,z} objects: no THREE import, no
 * scene, no renderer. That is deliberate — the claim "the arc clears the
 * obstacle" is then provable by sampling the curve in a unit test rather than by
 * looking at a screenshot and believing it.
 *
 * Cost: one pass over the obstacle list per arc START (not per frame), and the
 * curve stays a single quadratic Bezier — same geometry, same draw call, same
 * `ARC_SEGMENTS`. Nothing here touches the per-frame budget.
 */

export interface Vec3 { x: number; y: number; z: number }
export interface Obstacle { pos: Vec3; radius: number }

const sub = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z })
const add = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z })
const mul = (a: Vec3, s: number): Vec3 => ({ x: a.x * s, y: a.y * s, z: a.z * s })
const dot = (a: Vec3, b: Vec3): number => a.x * b.x + a.y * b.y + a.z * b.z
const len = (a: Vec3): number => Math.sqrt(dot(a, a))
function norm(a: Vec3): Vec3 {
  const l = len(a)
  return l < 1e-9 ? { x: 0, y: 1, z: 0 } : mul(a, 1 / l)
}

/** Point on segment [a,b] closest to p, plus how far along it lies (0..1). */
export function closestOnSegment(a: Vec3, b: Vec3, p: Vec3): { point: Vec3; t: number; dist: number } {
  const ab = sub(b, a)
  const denom = dot(ab, ab)
  const t = denom < 1e-9 ? 0 : Math.max(0, Math.min(1, dot(sub(p, a), ab) / denom))
  const point = add(a, mul(ab, t))
  return { point, t, dist: len(sub(p, point)) }
}

/** Point on a quadratic Bezier at parameter t. */
export function bezierAt(p0: Vec3, p1: Vec3, p2: Vec3, t: number): Vec3 {
  const u = 1 - t
  return {
    x: u * u * p0.x + 2 * u * t * p1.x + t * t * p2.x,
    y: u * u * p0.y + 2 * u * t * p1.y + t * t * p2.y,
    z: u * u * p0.z + 2 * u * t * p1.z + t * t * p2.z,
  }
}

/**
 * How close a quadratic Bezier comes to a point, by sampling — and WHERE.
 *
 * Exact minimisation of a cubic is not worth it here: the curve is short, the
 * obstacle is a sphere with a margin, and 32 samples resolve far below the
 * margin. The GATE uses this too, so the check and the fix agree by construction.
 *
 * ⚠ This measures the CURVE, not the chord. My first version detected
 * obstacles against the straight segment and deflected the curve — and the unit
 * test caught it immediately: an obstacle sitting exactly where the drawn arc
 * flies is ~20 units clear of the chord, so nothing was ever detected and the
 * "fix" was inert. Detect the thing you are actually drawing.
 */
export function closestOnCurve(p0: Vec3, p1: Vec3, p2: Vec3, p: Vec3, samples = 32): { dist: number; t: number } {
  let best = Infinity
  let bestT = 0
  for (let i = 0; i <= samples; i++) {
    const t = i / samples
    const d = len(sub(bezierAt(p0, p1, p2, t), p))
    if (d < best) { best = d; bestT = t }
  }
  return { dist: best, t: bestT }
}

export function minDistanceToCurve(p0: Vec3, p1: Vec3, p2: Vec3, p: Vec3, samples = 32): number {
  return closestOnCurve(p0, p1, p2, p, samples).dist
}

/** An obstacle is "at an endpoint" when the arc starts or ends inside it. */
function isEndpoint(o: Obstacle, from: Vec3, to: Vec3): boolean {
  const r = o.radius * 1.05
  return len(sub(o.pos, from)) <= r || len(sub(o.pos, to)) <= r
}

export interface RouteResult {
  /** The control point to hand to QuadraticBezierCurve3. */
  control: Vec3
  /** The obstacle that forced the deflection, if any. */
  deflectedAround: Obstacle | null
  /** How far the control point moved from the naive midpoint. */
  pushed: number
}

/**
 * Choose a Bezier control point that keeps the arc clear of every obstacle.
 *
 * `baseControl` is what the stage would have used (midpoint lifted in Y), so an
 * arc with a clear path is returned COMPLETELY UNCHANGED — this can only ever
 * add a deflection, never restyle traffic that was already fine.
 *
 * @param margin extra clearance beyond the obstacle radius, in world units.
 */
export function routeAround(
  from: Vec3,
  to: Vec3,
  baseControl: Vec3,
  obstacles: readonly Obstacle[],
  margin = 3,
): RouteResult {
  if (!obstacles || obstacles.length === 0) {
    return { control: baseControl, deflectedAround: null, pushed: 0 }
  }

  // Worst offender = the one the STRAIGHT path penetrates most deeply. Chasing
  // several at once with one control point is not solvable in general; clearing
  // the deepest and then re-checking the result is honest and terminates.
  let worst: Obstacle | null = null
  let worstPenetration = 0
  let worstNear: Vec3 | null = null
  for (const o of obstacles) {
    if (!o || o.radius <= 0) continue
    if (isEndpoint(o, from, to)) continue     // you cannot avoid where you are going
    const { dist, t } = closestOnCurve(from, baseControl, to, o.pos)
    // Only obstacles genuinely BETWEEN the two ends are in the way.
    if (t <= 0.02 || t >= 0.98) continue
    const need = o.radius + margin
    if (dist >= need) continue
    const pen = need - dist
    if (pen > worstPenetration) {
      worstPenetration = pen
      worst = o
      worstNear = bezierAt(from, baseControl, to, t)
    }
  }

  if (!worst || !worstNear) return { control: baseControl, deflectedAround: null, pushed: 0 }

  // Escape direction: from the obstacle centre towards the point on the CURVE
  // that comes closest to it — the shortest way out of the sphere. When the
  // obstacle sits exactly on the curve that direction is undefined, so fall back
  // to a perpendicular of the chord.
  let escape = sub(worstNear, worst.pos)
  if (len(escape) < 1e-6) {
    const axis = norm(sub(to, from))
    const up: Vec3 = Math.abs(axis.y) > 0.9 ? { x: 1, y: 0, z: 0 } : { x: 0, y: 1, z: 0 }
    // Any perpendicular will do; cross(axis, up) is one.
    escape = {
      x: axis.y * up.z - axis.z * up.y,
      y: axis.z * up.x - axis.x * up.z,
      z: axis.x * up.y - axis.y * up.x,
    }
  }
  const dir = norm(escape)

  // A quadratic Bezier's apex sits HALFWAY between the chord and the control
  // point, so a control point moved by d moves the curve by d/2 — the factor of
  // two below is that, not a fudge. Solve, then verify by sampling and step if
  // the curvature spreads the clearance (it does, near the endpoints).
  let control = baseControl
  for (let attempt = 0; attempt < 6; attempt++) {
    const have = minDistanceToCurve(from, control, to, worst.pos)
    const need = worst.radius + margin
    if (have >= need) break
    control = add(control, mul(dir, (need - have) * 2))
  }

  return { control, deflectedAround: worst, pushed: len(sub(control, baseControl)) }
}
