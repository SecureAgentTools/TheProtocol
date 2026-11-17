/**
 * V0662 console polish, item 7 (order gwo_0aa7b875cbf65b6347f5f775): the track record's probe line tells "no live
 * service declared" apart from "service not answering". The registry's liveness block now says whether the card
 * declares a live service (service_declared: a card URL that is not loopback and not a special-use TLD); the health
 * checker's raw outcome stays on the hover. An older registry that does not say keeps today's neutral line.
 * Red on f569f6a6e: the module does not exist.
 */
import { describe, it, expect } from 'vitest'
import { serviceLine } from './serviceLine'

const t = (_k: string, fallback: string) => fallback
const lv = (probe: string | null, service_declared?: boolean) => ({ probe, last_seen: null, live_24h: false, service_declared })

describe('the probe line', () => {
  it('a card that declares no live service says so, whatever the checker found at its placeholder', () => {
    expect(serviceLine(lv('unreachable', false), t)).toMatchObject({ kind: 'none', text: 'no live service declared' })
    expect(serviceLine(lv(null, false), t)).toMatchObject({ kind: 'none', text: 'no live service declared' })
    expect(serviceLine(lv('unreachable', false), t)!.title).toContain('unreachable')
  })
  it('a declared service that does not answer is "not answering", the outcome on the hover', () => {
    for (const p of ['unreachable', 'unhealthy']) {
      const s = serviceLine(lv(p, true), t)!
      expect(s).toMatchObject({ kind: 'down', text: 'service not answering' })
      expect(s.title).toContain(p)
    }
  })
  it('a declared service that answers, and one not probed yet', () => {
    expect(serviceLine(lv('healthy', true), t)).toMatchObject({ kind: 'up', text: 'service answering' })
    expect(serviceLine(lv(null, true), t)).toMatchObject({ kind: 'unknown', text: 'service not probed yet' })
  })
  it('an older registry that does not say whether a service is declared keeps the neutral line, or none', () => {
    expect(serviceLine(lv('unreachable'), t)).toMatchObject({ kind: 'probe', text: 'endpoint probe: unreachable' })
    expect(serviceLine(lv(null), t)).toBeNull()
    expect(serviceLine(null, t)).toBeNull()
  })
})
