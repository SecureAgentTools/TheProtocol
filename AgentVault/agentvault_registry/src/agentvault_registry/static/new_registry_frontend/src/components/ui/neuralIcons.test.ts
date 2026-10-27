import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { mount } from '@vue/test-utils'
import NeuralIcon from './NeuralIcon.vue'
import { NEURAL_ICON_NAMES, NEURAL_ICON_FALLBACK, resolveNeuralIcon } from './neuralIcons'

/**
 * §DEPS FE 3f (2026-09-29): EVERY NAME <NeuralIcon> CAN BE GIVEN MUST DRAW ITS OWN ICON.
 *
 * The component used to look names up in `import * as LucideIcons` after PascalCasing only HYPHENATED names, so a
 * one-word name that its map did not list ('plus', 'check', 'x', 'home', 'terminal', 'webhook', 'activity',
 * 'clipboard', 'coins', 'crown', 'flask', 'landmark', 'plug', 'scale', 'shuffle') stayed lowercase, missed, and
 * rendered the help-circle fallback: 15 of the 58 names the templates passed, with no warning anywhere. The table
 * now imports each icon by name, so a name outside it falls back just as silently; these tests are the warning.
 *
 * The names a template passes are read from the sources here, so a new call site is covered without editing this
 * file: every static name="..." and every quoted name inside a :name="..." binding, plus the names the API tester
 * builds in code (ApiTesterDisplay.vue: the `icon:` fields its getGroupIcon reads, and every quoted name in
 * getGroupIcon, getTestIconName and getAuthIconName).
 */

const SRC = path.resolve(__dirname, '../..')
const UNKNOWN = '__no_such_icon__'
// The one name whose intended icon IS the help circle the fallback draws.
const HELP_ICON_NAMES = new Set(['support'])

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (e.name.endsWith('.vue')) out.push(p)
  }
  return out
}

function templateNames(): Set<string> {
  const names = new Set<string>()
  for (const file of walk(SRC)) {
    const text = fs.readFileSync(file, 'utf8')
    for (const tag of text.matchAll(/<NeuralIcon\b([\s\S]*?)\/?>/g)) {
      const attrs = tag[1]
      const fixed = attrs.match(/(?<![:\w-])name="([^"]*)"/)
      if (fixed) names.add(fixed[1])
      const bound = attrs.match(/:name="([^"]*)"/)
      if (bound) for (const lit of bound[1].matchAll(/'([^']+)'/g)) names.add(lit[1])
    }
  }
  const tester = fs.readFileSync(path.join(SRC, 'components', 'ApiTesterDisplay.vue'), 'utf8')
  for (const m of tester.matchAll(/\bicon:\s*'([^']+)'/g)) names.add(m[1])
  for (const fn of ['getGroupIcon', 'getTestIconName', 'getAuthIconName']) {
    const at = tester.indexOf(`function ${fn}(`)
    expect(at, `ApiTesterDisplay.vue no longer defines ${fn}: update this scan`).toBeGreaterThanOrEqual(0)
    const body = tester.slice(at, tester.indexOf('\n}\n', at))
    for (const lit of body.matchAll(/'([a-z0-9-]+)'/g)) names.add(lit[1])
  }
  return names
}

/** Names that resolve to the fallback although they mean something else. */
function fallsBack(names: Iterable<string>): string[] {
  return [...names].filter(
    (n) => !resolveNeuralIcon(n) || (resolveNeuralIcon(n) === NEURAL_ICON_FALLBACK) !== HELP_ICON_NAMES.has(n),
  )
}

function svgBody(name: string): string | null {
  const svg = mount(NeuralIcon, { props: { name } }).find('svg')
  return svg.exists() ? svg.element.innerHTML : null
}

describe('NeuralIcon names', () => {
  it('falls back for a name it does not know (so the checks below can tell)', () => {
    expect(NEURAL_ICON_FALLBACK).toBeTruthy()
    expect(resolveNeuralIcon(UNKNOWN)).toBe(NEURAL_ICON_FALLBACK)
    expect(svgBody(UNKNOWN)).toBeTruthy()
  })

  it('draws a real icon for every name its table maps', () => {
    expect(NEURAL_ICON_NAMES.length).toBeGreaterThan(100)
    expect(fallsBack(NEURAL_ICON_NAMES)).toEqual([])
  })

  it('draws a real icon for every name a template passes', () => {
    const names = templateNames()
    // measured 58 when this was written; a scan that finds a handful is a broken scan, not a clean bill
    expect(names.size).toBeGreaterThanOrEqual(40)
    expect(fallsBack(names)).toEqual([])
  })

  it('renders each of those names as an svg that is not the fallback, through the component', () => {
    const fallback = svgBody(UNKNOWN)
    const all = new Set<string>([...NEURAL_ICON_NAMES, ...templateNames()])
    const bad = [...all].filter((n) => {
      const body = svgBody(n)
      return !body || (body === fallback) !== HELP_ICON_NAMES.has(n)
    })
    expect(bad).toEqual([])
  })
})
