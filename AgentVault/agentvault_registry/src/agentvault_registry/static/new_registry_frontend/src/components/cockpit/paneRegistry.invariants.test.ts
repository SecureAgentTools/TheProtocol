/**
 * §COCKPITDESK (2026-10-14) — the pane registry's own rules, checked instead of trusted.
 *
 * The registry says a new pane lives in two places (the PaneId union and PANES); NATURAL_ROWS makes it three. Its starter
 * layouts carry doctrine ("STOP rides with DECISIONS"), the header counts the panes that declare `acts`, and every title
 * reaches the screen through `t(titleKey, fallback)`, where a missing key renders English in every language for good.
 * Icons are left to Icon.names.test.ts, which already reads every literal `mdi:` name in this file.
 */
import { describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import en from '@/i18n/locales/en.json'

vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }))

import {
  PANES, ALL_PANE_IDS, NATURAL_ROWS, STARTER_LAYOUTS, MIN_ROWS, MAX_ROWS, rowsFor, isKnownPane,
  type PaneContext, type PaneId,
} from './paneRegistry'
import { DASHBOARD_DEFAULT } from '@/composables/useCockpitLayouts'

function hasKey(bundle: unknown, key: string): boolean {
  let node: unknown = bundle
  for (const part of key.split('.')) {
    if (!node || typeof node !== 'object' || !(part in (node as Record<string, unknown>))) return false
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string' && node.length > 0
}

const CONTEXTS: PaneContext[] = [
  { config: {} as PaneContext['config'], isAdmin: false },
  { config: {} as PaneContext['config'], isAdmin: true },
]

describe('the pane registry', () => {
  it('defines every pane once, under its own id', () => {
    expect(ALL_PANE_IDS.length).toBeGreaterThan(0)
    for (const id of ALL_PANE_IDS) {
      expect(PANES[id].id, `PANES.${id} carries the id ${PANES[id].id}`).toBe(id)
      expect(isKnownPane(id)).toBe(true)
    }
    expect(isKnownPane('not-a-pane')).toBe(false)
    expect(isKnownPane('toString'), 'an inherited object key is not a pane').toBe(false)
  })

  it('gives every pane a natural height inside the bounds, and no height to a pane that does not exist', () => {
    for (const id of ALL_PANE_IDS) {
      const n = NATURAL_ROWS[id]
      expect(Number.isInteger(n), `${id} has no natural height`).toBe(true)
      expect(n).toBeGreaterThanOrEqual(MIN_ROWS)
      expect(n).toBeLessThanOrEqual(MAX_ROWS)
    }
    expect(Object.keys(NATURAL_ROWS).sort()).toEqual([...ALL_PANE_IDS].sort())
  })

  it("uses the person's own height when it is a usable number, the pane's natural one otherwise", () => {
    const layout = (sizes: Record<string, unknown>) => ({ id: 'x', name: 'x', panes: [] as PaneId[], sizes: sizes as Record<string, number> })
    expect(rowsFor('book')).toBe(NATURAL_ROWS.book)
    expect(rowsFor('book', layout({ book: 2 }))).toBe(2)
    expect(rowsFor('book', layout({ book: 99 })), 'clamped to the ceiling').toBe(MAX_ROWS)
    expect(rowsFor('book', layout({ book: -3 })), 'clamped to the floor').toBe(MIN_ROWS)
    expect(rowsFor('book', layout({ book: 2.6 })), 'rounded').toBe(3)
    expect(rowsFor('book', layout({ book: Number.NaN })), 'NaN falls back').toBe(NATURAL_ROWS.book)
    expect(rowsFor('book', layout({ book: '2' })), 'a string is not a size').toBe(NATURAL_ROWS.book)
    expect(rowsFor('book', layout({ market: 1 })), "another pane's size does not leak").toBe(NATURAL_ROWS.book)
  })

  it('states a poll interval for every polling pane', () => {
    for (const id of ALL_PANE_IDS) {
      const p = PANES[id]
      if (p.refreshMode === 'poll') expect(p.pollSeconds ?? 0, `${id} polls with no stated interval`).toBeGreaterThanOrEqual(10)
    }
  })

  // §COCKPITDESK: Decision latency said "60s" and Consent telemetry "90s" while both read once at open and then only on a
  // socket cue. A chip that names an interval the code does not keep is the freshness lie the chip exists to prevent.
  it('keeps the interval every polling pane names on its chip', () => {
    const dir = path.resolve(__dirname)
    const reg = fs.readFileSync(path.join(dir, 'paneRegistry.ts'), 'utf8')
    const lies: string[] = []
    for (const id of ALL_PANE_IDS) {
      if (PANES[id].refreshMode !== 'poll') continue
      const m = reg.match(new RegExp(`id: '${id}'[\\s\\S]*?import\\('@/components/cockpit/(\\w+)\\.vue'\\)`))
      expect(m, `the registry names no component for ${id}`).toBeTruthy()
      const src = fs.readFileSync(path.join(dir, `${m![1]}.vue`), 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/<!--[\s\S]*?-->/g, '')
      if (!/\bset(Jittered)?Interval\(/.test(src)) lies.push(`${id} (${m![1]}) names ${PANES[id].pollSeconds}s and never re-reads`)
    }
    expect(lies).toEqual([])
  })

  it('gives a reason wherever a pane can be unavailable', () => {
    for (const id of ALL_PANE_IDS) {
      for (const ctx of CONTEXTS) {
        if (!PANES[id].available(ctx)) {
          expect(PANES[id].unavailableReason.trim().length, `${id} can be unavailable and says nothing`).toBeGreaterThan(10)
        }
      }
    }
  })

  // §COCKPITDESK (2026-10-15): an admin pane follows the admin sub-flag its route and its read demand.
  it('offers the admin panes by their own admin flag', () => {
    const ctx = (flags: string[]): PaneContext => ({ config: {} as PaneContext['config'], isAdmin: true,
      adminCan: (a) => flags.includes(a) })
    expect(PANES.release.available(ctx(['platform']))).toBe(true)
    expect(PANES.release.available(ctx(['enforcement'])), 'an admin without the platform flag').toBe(false)
    expect(PANES.settlements.available(ctx(['enforcement']))).toBe(true)
    expect(PANES.settlements.available(ctx(['platform'])), 'an admin without the enforcement flag').toBe(false)
    expect(PANES.settlements.available({ config: {} as PaneContext['config'], isAdmin: false }), 'no rule given: a non-admin').toBe(false)
  })

  it('resolves every pane title in the English bundle', () => {
    const missing = ALL_PANE_IDS.filter(id => !hasKey(en, PANES[id].titleKey))
    expect(missing, `title keys missing from en.json: ${missing.join(', ')}`).toEqual([])
  })

  // agentvault2-69's gallery pass, 2026-10-25 (his word "only compliant ones"): the income half of `book` is titled Income,
  // not Earnings; nothing is paid for a lock or for membership. The id and the key stay; the fallback and English agree.
  it('titles the income pane Income, in its fallback and in English', () => {
    expect(PANES.earnings.titleFallback).toBe('Income')
    expect(en.cockpit.pane.earnings).toBe('Income')
  })

  // A decision record, not a measurement: the header's "can act" count reads `acts`, so moving a pane in or out of this
  // list changes what the desk tells a person about the board. Change it here on purpose, never by accident.
  it('declares exactly the panes that can change something', () => {
    const acting = ALL_PANE_IDS.filter(id => PANES[id].acts).sort()
    expect(acting).toEqual(['channels', 'decisions', 'quickactions', 'stop'])
  })
})

describe('the starter layouts and the dashboard default', () => {
  it('name only known panes, each once', () => {
    for (const l of [...STARTER_LAYOUTS, DASHBOARD_DEFAULT]) {
      for (const p of l.panes) expect(isKnownPane(p), `${l.id} names unknown pane ${p}`).toBe(true)
      expect(new Set(l.panes).size, `${l.id} names a pane twice`).toBe(l.panes.length)
      expect(l.panes.length, `${l.id} is empty`).toBeGreaterThan(0)
    }
  })

  it('have distinct ids and names, and none looks like a saved layout', () => {
    const ids = STARTER_LAYOUTS.map(l => l.id)
    const names = STARTER_LAYOUTS.map(l => l.name)
    expect(new Set(ids).size).toBe(ids.length)
    expect(new Set(names).size).toBe(names.length)
    for (const l of STARTER_LAYOUTS) {
      expect(l.builtin, `${l.id} is not marked built in`).toBe(true)
      expect(l.id.startsWith('u_'), `${l.id} uses the saved-layout prefix`).toBe(false)
    }
  })

  it('carry STOP wherever they can ask for a decision', () => {
    for (const l of STARTER_LAYOUTS) {
      if (l.panes.includes('decisions')) expect(l.panes, `${l.id} asks for decisions with no way to stop`).toContain('stop')
    }
  })

  it('offer on the dashboard only panes every registry with the desk can serve', () => {
    for (const p of DASHBOARD_DEFAULT.panes) {
      for (const ctx of CONTEXTS) expect(PANES[p].available(ctx), `${p} on the dashboard default`).toBe(true)
    }
  })
})
