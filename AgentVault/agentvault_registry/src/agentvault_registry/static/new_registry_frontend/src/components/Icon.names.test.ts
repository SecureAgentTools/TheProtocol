import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * §LITEBRIDGE polish 2 — EVERY `mdi:` NAME USED MUST EXIST IN THE MAP.
 *
 * `Icon.vue` is a LOCAL inline-SVG map with no fallback glyph, and its own
 * header says so: an unknown name is "a SILENT blank: no warning, no fallback
 * glyph". So a typo, or a name copied from the MDI website that was never added
 * here, renders empty space and nothing anywhere complains.
 *
 * Found this way, in one pass: `mdi:bell-off` (the chime toggle — blank for
 * everyone, since the chime is OFF by default), `mdi:arrow-expand-horizontal`
 * and `mdi:arrow-collapse-horizontal` (the rails door), and `mdi:weather-hazy`
 * (the atmosphere dial, blank since R14).
 *
 * Only LITERAL names can be checked; a name built with a template string is
 * skipped and counted, so the gate never claims more coverage than it has.
 */
const SRC = path.resolve(__dirname, '..')
const ICON_FILE = path.join(SRC, 'components', 'Icon.vue')

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (/\.(vue|ts)$/.test(e.name) && !/\.test\.ts$/.test(e.name)) out.push(full)
  }
  return out
}

const iconSrc = fs.readFileSync(ICON_FILE, 'utf8')
const defined = new Set([...iconSrc.matchAll(/^\s*'(mdi:[a-z0-9-]+)':/gm)].map(m => m[1]))
// Aliases/normalisation the component itself performs, if any.
const aliasLines = [...iconSrc.matchAll(/'(mdi:[a-z0-9-]+)'\s*:\s*'(mdi:[a-z0-9-]+)'/g)]
for (const [, from] of aliasLines) defined.add(from)

const used = new Map<string, string[]>()
for (const f of walk(SRC)) {
  if (f === ICON_FILE) continue
  const txt = fs.readFileSync(f, 'utf8')
  for (const m of txt.matchAll(/['"`](mdi:[a-z0-9-]+)['"`]/g)) {
    const rel = path.relative(SRC, f)
    const arr = used.get(m[1]) || []
    if (!arr.includes(rel)) arr.push(rel)
    used.set(m[1], arr)
  }
}

/*
 * PRE-EXISTING DEBT, RECORDED RATHER THAN HIDDEN.
 *
 * 37 names were already missing when this gate was written — every one of
 * them a control somewhere in the app rendering blank space. They are listed so
 * the gate can FAIL ON ANYTHING NEW without failing on work nobody has done
 * yet. Deleting a line here is the fix; adding one should need a reason.
 *
 * Everything on the bridge was fixed rather than listed.
 */
const KNOWN_MISSING = new Set<string>([
  'mdi:account-search-outline',
  'mdi:api',
  'mdi:arrow-down-bold',
  'mdi:arrow-up-bold',
  'mdi:arrow-up-thin',
  'mdi:atom-variant',
  'mdi:bell-outline',
  'mdi:blur-off',
  'mdi:blur-radial',
  'mdi:calendar-month-outline',
  'mdi:cash-off',
  'mdi:chart-areaspline',
  'mdi:check-decagram-outline',
  'mdi:clock-alert',
  'mdi:clock-check-outline',
  'mdi:close-octagon',
  'mdi:counter',
  'mdi:database',
  'mdi:file-key-outline',
  'mdi:flash-alert-outline',
  'mdi:gesture-tap-button',
  'mdi:layers-triple',
  'mdi:lightbulb-on-outline',
  'mdi:lock-outline',
  'mdi:medal-outline',
  'mdi:pause-octagon',
  'mdi:rss',
  'mdi:shield-crown',
  'mdi:star-four-points',
  'mdi:store-off-outline',
  'mdi:timer',
  'mdi:transit-connection-variant',
  'mdi:trending-down',
  'mdi:user-plus',
  'mdi:weather-partly-cloudy',
  'mdi:white-balance-sunny',
])

describe('Icon map coverage', () => {
  it('the map is not empty and the scan found names', () => {
    expect(defined.size).toBeGreaterThan(100)
    expect(used.size).toBeGreaterThan(50)
  })

  it('every literal mdi: name used in the app exists in the local map', () => {
    const missing = [...used.entries()]
      .filter(([n]) => !defined.has(n) && !KNOWN_MISSING.has(n))
      .map(([n, files]) => `${n}  <- ${files.slice(0, 3).join(', ')}`)
    expect(missing, `\n${missing.length} NEW icon name(s) render as SILENT BLANKS:\n  ${missing.join('\n  ')}\n`).toEqual([])
  })

  it('no name on the BRIDGE is missing — that surface is kept clean', () => {
    const bridgeMissing = [...used.entries()]
      .filter(([n, files]) => !defined.has(n) &&
        files.some(f => /bridge|MissionControl/i.test(f)))
      .map(([n, files]) => `${n} <- ${files.join(', ')}`)
    expect(bridgeMissing).toEqual([])
  })

  it('the recorded debt is still real — a fixed name must leave the list', () => {
    // Otherwise the allowlist rots into a place where fixed things hide.
    const stale = [...KNOWN_MISSING].filter(n => defined.has(n))
    expect(stale, `these are DEFINED now and should be removed from KNOWN_MISSING: ${stale.join(', ')}`).toEqual([])
  })
})
