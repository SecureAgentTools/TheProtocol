// V0660 (f): the quantum chambers, and the marks that keep them honest.
//
// The existing blueprints.test.ts already holds every chamber to the shared rules (unique rank, a
// majority-live ratio derived from its own primitives table, a loom that draws clean, no em dash, no
// moat, no would/could/imagine, no selling cover, a permit called a permit). This file adds only what is
// specific to quantum, where the temptation to overclaim is strongest and the honest line is one I
// measured in V0660 (c) rather than guessed:
//
//   * A simulator flow runs end to end today, so the money, identity, evidence and metering rails are
//     LIVE or LIVE (gated) and may say so.
//   * A real QPU is not ours and not on our side, so every step that needs one is DESIGNED.
//   * No chamber claims quantum advantage, in any of the words the literature uses for it. V0660's
//     ground rules forbid it, and a blueprint is a public text.
import { describe, expect, it } from 'vitest'

import { BLUEPRINTS } from './index'
import { ARCH_LOADERS } from './arch/index'
import type { Blueprint, PrimitiveRow } from './types'

const QUANTUM_IDS = ['collegium', 'lattice', 'lodestar', 'alea', 'ancilla'] as const

/** The chambers, AND the assertion that there are any.
 *
 *  Written first without that assertion, which was the oldest trap in this project wearing a new coat:
 *  ten of these eleven tests passed against an empty list, because a loop over nothing satisfies every
 *  expectation inside it. A guard that cannot fail is worse than no guard, so the population is checked
 *  here, once, and every test below therefore measures something real. */
function quantum(): Blueprint[] {
  const found = BLUEPRINTS.filter((b) => (QUANTUM_IDS as readonly string[]).includes(b.id))
  expect(found.map((b) => b.id).sort(), 'the quantum chambers are not all registered, so every check below would pass over an empty list')
    .toEqual([...QUANTUM_IDS].sort())
  return found
}

/** Every string in a blueprint, so a guard reads the whole chamber and not the fields we remembered. */
function strings(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') out.push(value)
  else if (Array.isArray(value)) for (const v of value) strings(v, out)
  else if (value && typeof value === 'object') for (const v of Object.values(value)) strings(v, out)
  return out
}

/** The words the field uses for an advantage claim. A quantum page that says any of these is selling a
 *  result nobody here has measured. "quantum advantage" and "speedup" are the obvious two; the rest are
 *  how the same claim arrives dressed differently. */
const ADVANTAGE = /\b(quantum advantage|quantum supremacy|speed-?ups?|exponentially faster|faster than (any |a )?classical|outperforms? (any )?classical|beyond classical|intractable for classical)\b/i

/** A step needs real hardware when it is about the device doing the computing, not about who paid for it
 *  or what signed it. Named here so the rule is readable rather than implied by a status column. */
const NEEDS_REAL_HARDWARE = /\b(on a real (QPU|device)|real quantum hardware|physical qubits execute|hardware run|QPU execution|on the hardware itself)\b/i

describe('the quantum chambers exist and are frontier', () => {
  it('all five are registered', () => {
    expect(quantum().map((b) => b.id).sort()).toEqual([...QUANTUM_IDS].sort())
    expect(quantum()).toHaveLength(5)
  })

  it('each is marked frontier and has a deep architecture', () => {
    for (const bp of quantum()) {
      expect(bp.frontier, `${bp.id} is a frontier chamber`).toBe(true)
      expect(ARCH_LOADERS[bp.id], `${bp.id} has a deep architecture`).toBeTypeOf('function')
    }
  })

  it('their ranks continue the frontier wave without colliding', () => {
    const ranks = quantum().map((b) => b.rank)
    expect(new Set(ranks).size).toBe(ranks.length)
    for (const r of ranks) expect(r).toBeGreaterThan(28)
  })
})

describe('no quantum chamber claims an advantage', () => {
  it('the guard sees the words it is for', () => {
    expect('a quantum advantage of ten').toMatch(ADVANTAGE)
    expect('exponentially faster than classical methods').toMatch(ADVANTAGE)
    expect('a speedup over the old solver').toMatch(ADVANTAGE)
    expect('the run finished and the counts were signed').not.toMatch(ADVANTAGE)
  })

  it('and no chamber says any of them', () => {
    for (const bp of quantum()) {
      expect(strings(bp).filter((t) => ADVANTAGE.test(t)), bp.id).toEqual([])
    }
  })

  it('nor does any deep architecture', async () => {
    for (const bp of quantum()) {
      const { deep } = await ARCH_LOADERS[bp.id]()
      expect(strings(deep).filter((t) => ADVANTAGE.test(t)), bp.id).toEqual([])
    }
  })
})

describe('the marks match what runs', () => {
  it('every step that needs real hardware is DESIGNED, never LIVE', () => {
    for (const bp of quantum()) {
      const wrong = bp.primitives
        .filter((p: PrimitiveRow) => NEEDS_REAL_HARDWARE.test(`${p.step} ${p.primitive}`))
        .filter((p: PrimitiveRow) => p.railStatus !== 'DESIGNED')
      expect(wrong.map((p) => p.step), `${bp.id} marks hardware steps as built`).toEqual([])
    }
  })

  it('each chamber really has at least one DESIGNED step, so the honesty is visible', () => {
    for (const bp of quantum()) {
      const designed = bp.primitives.filter((p: PrimitiveRow) => p.railStatus === 'DESIGNED')
      expect(designed.length, `${bp.id} shows nothing as DESIGNED, which no quantum chamber can honestly do`)
        .toBeGreaterThan(0)
    }
  })

  it('and is still majority live by capability, from its own table', () => {
    for (const bp of quantum()) {
      const [live, total] = bp.liveRatio
      expect(live * 2, `${bp.id} is not majority live`).toBeGreaterThan(total)
    }
  })
})

describe('what the chambers say about the protocol is true of the protocol', () => {
  it('a chamber citing S19 says the proof is of a published circuit', () => {
    /** V0660 (h) and (c) measured this: four v2.0.0 circuits are published with their verification keys,
     *  so S19 is honest here. What is NOT ours is producing the proof, which needs nargo and bb on the
     *  provider's machine. A chamber may cite S19; it may not imply we prove it for them. */
      for (const bp of quantum().filter((b) => b.rails.includes('S19'))) {
      const text = strings(bp).join('\n')
      expect(text, `${bp.id} cites S19 without naming the circuit`).toMatch(/accurateResourceUsagePolicy|published circuit/i)
      expect(text, `${bp.id} implies we run the prover`).not.toMatch(/we prove|the protocol proves|we generate the proof/i)
    }
  })

  it('no chamber says the protocol hosts the model or the agent', () => {
    /** His own addendum, seq 2572 and 2574: the protocol never hosts the model or the agent. A page that
     *  implies otherwise would promise a service we do not run. */
    for (const bp of quantum()) {
      const text = strings(bp).join('\n')
      expect(text, bp.id).not.toMatch(/we host (the|your) (model|agent)|hosted (model|inference) (service|here)/i)
    }
  })
})
