#!/usr/bin/env node
/**
 * Writes dist/THIRD_PARTY_NOTICES.txt: the licence notices of the npm packages this web application ships
 * (REVIEW_2026-09-30_LICENSING.md, A5). A minified bundle keeps no licence comment, and MIT, ISC, BSD and Apache-2.0
 * all ask that their notice travel with every copy, so the build writes the notices beside the bundle, where the
 * registry serves them with the application.
 *
 * Which packages: every package-lock entry that is not development-only (the runtime closure), read from node_modules
 * at the locked version. A runtime package that is missing, or installed at a version other than the locked one, stops
 * the build: the notices must describe what was bundled. An optional package that is not installed (a platform binary
 * for another system) is skipped. Packages aliased away in vite.config.ts are listed as not shipped and carry no text.
 *
 * Usage, after `vite build`:  node scripts/gen_third_party_notices.mjs [--out <file>]
 */
import { readFileSync, writeFileSync, existsSync, readdirSync, statSync, mkdirSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const NOT_SHIPPED = {
  elkjs: 'EPL-2.0; aliased to src/vendor-stubs/elkjs.ts in vite.config.ts, so none of its code is in this build',
}
const LICENCE_FILE = /^(licen[cs]e|copying|notice)([.\-_]|$)/i
const MAX_TEXT = 200_000
const RULE = '='.repeat(100)

const outArg = process.argv.indexOf('--out')
const out = outArg > -1 ? resolve(process.argv[outArg + 1]) : join(ROOT, 'dist', 'THIRD_PARTY_NOTICES.txt')

const lock = JSON.parse(readFileSync(join(ROOT, 'package-lock.json'), 'utf8'))
const problems = []
const blocks = []
const notShipped = []
let skippedOptional = 0

function licenceOf(pkg) {
  if (typeof pkg.license === 'string') return pkg.license
  if (pkg.license && typeof pkg.license.type === 'string') return pkg.license.type
  if (Array.isArray(pkg.licenses)) return pkg.licenses.map((l) => (typeof l === 'string' ? l : l && l.type)).filter(Boolean).join(' OR ')
  return ''
}

function sourceOf(pkg) {
  const r = pkg.repository
  const url = typeof r === 'string' ? r : r && r.url
  return (url || pkg.homepage || '').replace(/^git\+/, '')
}

const keys = Object.keys(lock.packages || {})
  .filter((k) => k.startsWith('node_modules/') || k.includes('/node_modules/'))
  .sort()

for (const key of keys) {
  const entry = lock.packages[key]
  if (entry.dev || entry.devOptional) continue
  const name = key.slice(key.lastIndexOf('node_modules/') + 'node_modules/'.length)
  if (NOT_SHIPPED[name]) {
    notShipped.push(`${name} ${entry.version || ''}: ${NOT_SHIPPED[name]}`)
    continue
  }
  const dir = join(ROOT, key)
  const manifest = join(dir, 'package.json')
  if (!existsSync(manifest)) {
    if (entry.optional) { skippedOptional += 1; continue }
    problems.push(`${key}: not installed`)
    continue
  }
  const pkg = JSON.parse(readFileSync(manifest, 'utf8'))
  if (entry.version && pkg.version !== entry.version) {
    problems.push(`${key}: installed ${pkg.version}, locked ${entry.version}`)
    continue
  }
  const licence = licenceOf(pkg) || entry.license || '(none declared)'
  const files = readdirSync(dir).filter((f) => LICENCE_FILE.test(f) && statSync(join(dir, f)).isFile()).sort()
  const texts = files.map((f) => {
    const t = readFileSync(join(dir, f), 'utf8')
    return `--- ${f}\n${t.length > MAX_TEXT ? t.slice(0, MAX_TEXT) + '\n[truncated]' : t}`.trimEnd()
  })
  const body = texts.length ? texts.join('\n\n') : `(The package ships no licence file; its package.json declares: ${licence}.)`
  const src = sourceOf(pkg)
  const lines = [RULE, `${pkg.name || name} ${pkg.version}`, `Licence: ${licence}`]
  if (src) lines.push(`Source: ${src}`)
  lines.push('', body, '')
  blocks.push(lines.join('\n'))
}

// Third-party material that reaches the application without npm: embedded in the source or vendored under public/.
// Each entry names where it is and reproduces the licence file kept beside it (a missing file stops the build).
const EMBEDDED = [
  { name: 'Material Design Icons (Pictogrammers), icon shapes in src/components/Icon.vue', licence: 'Apache-2.0 (Pictogrammers Free License)',
    source: 'https://github.com/Templarian/MaterialDesign', files: ['scripts/licenses/material-design-icons.LICENSE.txt'] },
  { name: 'Swagger UI 5.9.0 (swagger-ui-dist), vendored as public/vendor/swagger-ui-bundle.js and swagger-ui.css', licence: 'Apache-2.0',
    source: 'https://github.com/swagger-api/swagger-ui', files: ['public/vendor/LICENSE.swagger-ui', 'public/vendor/NOTICE.swagger-ui'] },
  { name: 'ReDoc 2.5.0, vendored as public/vendor/redoc.standalone.js', licence: 'MIT',
    source: 'https://github.com/Redocly/redoc', files: ['public/vendor/LICENSE.redoc', 'public/vendor/redoc.standalone.js.LICENSE.txt'] },
  { name: 'Fonts: Inter, IBM Plex Sans, IBM Plex Mono, Orbitron, served from public/fonts', licence: 'OFL-1.1',
    source: 'the copyright lines are in the licence file', files: ['public/fonts/OFL.txt'] },
  { name: 'Night-light tiles for the globe (NASA GIBS, VIIRS Black Marble 2016), public/assets/nightlights', licence: 'public domain (US Government work)',
    source: 'https://gibs.earthdata.nasa.gov', files: ['public/assets/nightlights/SOURCE.txt'] },
  { name: 'Base map tiles for the globe, public/assets/basemap', licence: 'rendered from Natural Earth data (public domain)',
    source: 'https://www.naturalearthdata.com', files: [] },
]
const npmCount = blocks.length
for (const e of EMBEDDED) {
  const texts = e.files.map((f) => {
    const path = join(ROOT, f)
    if (!existsSync(path)) { problems.push(`${f}: the licence file of ${e.name} is missing`); return '' }
    return `--- ${f}\n${readFileSync(path, 'utf8')}`.trimEnd()
  })
  blocks.push([RULE, e.name, `Licence: ${e.licence}`, `Source: ${e.source}`, '', texts.length ? texts.join('\n\n') : '(No licence file: the data is in the public domain.)', ''].join('\n'))
}

if (problems.length) {
  console.error(`[notices] REFUSED: ${problems.length} runtime package(s) do not match the lockfile:\n  ${problems.join('\n  ')}`)
  process.exit(2)
}
if (npmCount < 50) {
  console.error(`[notices] REFUSED: only ${npmCount} runtime packages found; the lockfile closure is much larger`)
  process.exit(3)
}

const header = [
  'THIRD-PARTY NOTICES',
  '',
  'This web application is TheProtocol (AGPL-3.0-or-later; see LICENSE and LICENSING.md in the source). It includes the',
  `third-party packages below, taken from its package-lock.json at build time (${npmCount} packages), followed by the`,
  `${EMBEDDED.length} items that reach it without npm (embedded icon shapes, vendored files, fonts, map imagery). Each block`,
  'names the item, its licence and its source, and reproduces the licence and notice files that come with it.',
  '',
  notShipped.length ? `Not shipped although the lockfile lists them:\n  ${notShipped.join('\n  ')}` : '',
  skippedOptional ? `Optional platform packages not installed on the build system and therefore not included: ${skippedOptional}.` : '',
  '',
].filter((l, i, a) => !(l === '' && a[i - 1] === '')).join('\n')

mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, `${header}\n${blocks.join('\n')}\n${RULE}\n`)
console.log(`[notices] ${out}: ${npmCount} packages, ${EMBEDDED.length} embedded items, ${notShipped.length} not shipped, ${skippedOptional} optional skipped`)
