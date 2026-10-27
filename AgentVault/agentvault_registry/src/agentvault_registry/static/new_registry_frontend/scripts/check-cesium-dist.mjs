// The built Cesium tree must be Cesium's own: every file under node_modules/cesium/Build/Cesium/{Workers,Assets,Widgets}
// at the same relative path under dist/cesium/, and nothing else there. vite.config.ts points the engine at
// CESIUM_BASE_URL=/static/cesium/, and the engine asks for Build/Cesium's own layout below it.
//
// Why this exists (2026-09-28): vite-plugin-static-copy 4 always keeps the source's directory structure under `dest`
// (1.x flattened each match to its basename), so from V0481 to V0485 every Cesium file shipped at
// dist/cesium/Workers/node_modules/cesium/Build/Cesium/Workers/... The paths the engine asks for answered 404 and the
// landing page's globe did not load. The build's own gate only counted dist/assets, so nothing noticed.
// The trees are compared as SETS, never as counts, and an empty source refuses: a gate must not pass on nothing.
//
// Run from the frontend root after `npm run build-only`, while node_modules is still there (CI, the image build).
import { existsSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = 'node_modules/cesium/Build/Cesium'
const OUT = 'dist/cesium'
const DIRS = ['Assets', 'Widgets', 'Workers']

function files(root) {
  const out = []
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else out.push(relative(root, p).split('\\').join('/'))
    }
  }
  if (existsSync(root)) walk(root)
  return out
}

let bad = 0
for (const d of DIRS) {
  const want = new Set(files(join(SRC, d)))
  const got = new Set(files(join(OUT, d)))
  const missing = [...want].filter((f) => !got.has(f)).sort()
  const extra = [...got].filter((f) => !want.has(f)).sort()
  const ok = want.size > 0 && missing.length === 0 && extra.length === 0
  console.log(
    `cesium ${d}: ${got.size} in dist, ${want.size} in Build/Cesium, ` +
      `missing ${missing.length}, extra ${extra.length}: ${ok ? 'OK' : 'MISMATCH'}`,
  )
  if (!ok) {
    bad += 1
    if (want.size === 0) console.log(`  nothing under ${SRC}/${d}: run this where node_modules is installed`)
    for (const f of missing.slice(0, 3)) console.log(`  missing: ${d}/${f}`)
    for (const f of extra.slice(0, 3)) console.log(`  extra:   ${d}/${f}`)
  }
}
// Beside the three asset trees, Cesium's own LICENSE.md (its licence and third-party list) must travel with them
// (REVIEW_2026-09-30_LICENSING.md); vite.config.ts copies it.
const WANT_TOP = [...DIRS, 'LICENSE.md'].sort()
const top = existsSync(OUT) ? readdirSync(OUT).sort() : []
if (top.join(',') !== WANT_TOP.join(',')) {
  console.log(`cesium: dist/cesium holds [${top.join(', ')}], want [${WANT_TOP.join(', ')}]`)
  bad += 1
}
console.log(bad ? 'cesium dist: FAIL' : 'cesium dist: PASS')
process.exit(bad ? 1 : 0)
