/**
 * V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the sidebar's Pinned block, shared with the command palette.
 * Pins follow the account under their own developer-prefs key (console.nav_pins, whole-value PUT): a change reads the
 * server's value first, changes it, and writes it back, so a pin added on another device is kept; a write the server
 * refuses is rolled back and reported, never shown as saved. Nothing pinned yet shows the defaults (Mission Control,
 * OurChat, Pocket mode). Red on f569f6a6e: the module does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ server: null as unknown, putOk: true, gets: 0, puts: [] as unknown[] }))
vi.mock('@/services/api/pocketPrefs', () => ({
  getPref: vi.fn(async () => { h.gets++; return { value: h.server, fromCache: false } }),
  putPref: vi.fn(async (_k: string, v: unknown) => { h.puts.push(v); if (h.putOk) h.server = v; return h.putOk }),
}))

import { DEFAULT_PINS, MAX_PINS, pinsOf, togglePin, useNavPins, _resetNavPins } from './navPins'

describe('the stored value', () => {
  it('reads the paths, once each, only paths, capped; anything else is unset', () => {
    expect(pinsOf({ paths: ['/guild', '/guild', 'nope', 7, '/ourchat'] })).toEqual(['/guild', '/ourchat'])
    expect(pinsOf({ paths: Array.from({ length: 30 }, (_, i) => `/p${i}`) })!.length).toBe(MAX_PINS)
    expect(pinsOf({ paths: [] })).toEqual([])
    for (const v of [null, undefined, 'x', { other: 1 }, { paths: 'x' }]) expect(pinsOf(v)).toBeNull()
  })
  it('a toggle adds at the end or takes out', () => {
    expect(togglePin(['/a'], '/b')).toEqual(['/a', '/b'])
    expect(togglePin(['/a', '/b'], '/a')).toEqual(['/b'])
  })
})

describe('the pins a person sees', () => {
  beforeEach(() => { _resetNavPins(); h.server = null; h.putOk = true; h.gets = 0; h.puts = [] })

  it('nothing pinned yet: the defaults', async () => {
    const p = useNavPins()
    await p.load()
    expect(p.pins.value).toEqual(DEFAULT_PINS)
    expect(DEFAULT_PINS).toEqual(['/mission-control', '/ourchat', '/pocket/home'])
  })

  it('a change reads the server first and writes the whole value back (a pin from another device stays)', async () => {
    const p = useNavPins()
    await p.load()                                                   // sees the defaults
    h.server = { paths: ['/mission-control', '/firms'] }             // another device pinned /firms meanwhile
    expect(await p.toggle('/guild')).toBe('saved')
    expect(h.puts[h.puts.length - 1]).toEqual({ paths: ['/mission-control', '/firms', '/guild'] })
    expect(p.pins.value).toEqual(['/mission-control', '/firms', '/guild'])
    expect(p.isPinned('/firms')).toBe(true)
  })

  it('the first change starts from the defaults it showed', async () => {
    const p = useNavPins()
    await p.load()
    expect(await p.toggle('/ourchat')).toBe('saved')
    expect(h.puts[h.puts.length - 1]).toEqual({ paths: ['/mission-control', '/pocket/home'] })
  })

  it('a refused write is rolled back and reported', async () => {
    const p = useNavPins()
    h.server = { paths: ['/guild'] }
    await p.load()
    h.putOk = false
    expect(await p.toggle('/firms')).toBe('failed')
    expect(p.pins.value).toEqual(['/guild'])
  })

  it('one load for every caller (the sidebar and the palette share it)', async () => {
    await Promise.all([useNavPins().load(), useNavPins().load()])
    expect(h.gets).toBe(1)
  })
})
