/**
 * V0662 console polish, item 6 (order gwo_0aa7b875cbf65b6347f5f775): the quantum card renders a backend's availability
 * windows (the extension's params.backends[].availability: days, start_utc, end_utc, schema quantum_workload v1.0),
 * which the fixture and the card already carry and the card never showed. A window may run past midnight (the
 * registry refuses only one that starts when it ends). Red on f569f6a6e: availabilityWindows does not exist.
 */
import { describe, it, expect } from 'vitest'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'
import { availabilityWindows } from './quantumCard'

describe('a backend\'s availability windows', () => {
  it('the fixture\'s window: every day, all day', () => {
    const b = (fx.extension.params as any).backends[0]
    expect(availabilityWindows(b)).toEqual([{ days: 'everyday', start: '00:00', end: '23:59', overnight: false }])
  })
  it('a window that ends before it starts runs into the next day', () => {
    const w = availabilityWindows({ availability: { as_of: 'x', windows: [{ days: 'weekdays', start_utc: '22:00', end_utc: '06:00' }] } })
    expect(w).toEqual([{ days: 'weekdays', start: '22:00', end: '06:00', overnight: true }])
  })
  it('no availability, or a window it cannot read, is no window (never a made-up one)', () => {
    expect(availabilityWindows({})).toEqual([])
    expect(availabilityWindows(null)).toEqual([])
    expect(availabilityWindows({ availability: { windows: [{ days: 'friday', start_utc: '9', end_utc: '17:00' }, 'x', null] } })).toEqual([])
  })
})
