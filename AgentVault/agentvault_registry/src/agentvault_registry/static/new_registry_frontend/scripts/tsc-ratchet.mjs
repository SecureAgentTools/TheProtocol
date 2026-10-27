#!/usr/bin/env node
/**
 * scripts/tsc-ratchet.mjs — §POCKETBRIDGE2 W7.3.
 *
 * The type-error RATCHET: the project error count may shrink, never grow.
 * F13's 350-error grind is its own session; this guard makes sure nobody adds
 * to the pile meanwhile. Run: `npm run typecheck:ratchet`.
 *
 * Exit 0: count <= baseline (and REWRITES the baseline downward when lower,
 * so improvement locks in). Exit 1: count grew — the output names the files
 * that regressed vs the recorded per-file baseline. Exit 2: DID NOT RUN (the
 * compiler failed without a single diagnostic, or its output held a
 * configuration-class diagnostic); the baseline is never touched on that path.
 */
import { execSync } from 'node:child_process'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const BASELINE = resolve(root, '.tsc-baseline.json')

let out = ''
let crashed = null
let failed = false
try {
  execSync('npx vue-tsc --noEmit -p tsconfig.app.json', {
    cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    maxBuffer: 64 * 1024 * 1024,
    // MEASURED 2026-08-30 (§COCKPIT P4): this project now needs >5 GB — a run at
    // --max-old-space-size=5120 aborts with an allocation failure at 5065 MB. The
    // old 6144 was one refactor away from the same fate, and see `crashed` below
    // for what that used to cost.
    env: { ...process.env, NODE_OPTIONS: '--max-old-space-size=8192' },
  })
} catch (e) {
  out = String(e.stdout || '') + String(e.stderr || '')
  // 🔴 A CRASH IS NOT A CLEAN BILL OF HEALTH. vue-tsc exits 1 when it finds type
  // errors and 134 (SIGABRT) when V8 runs out of heap. Both landed here, and the
  // parser below finds ZERO `error TS` lines in an OOM dump — so the old code read
  // `total = 0`, took the `total < base.total` branch, printed "improved 357 -> 0"
  // and OVERWROTE THE BASELINE WITH ZERO. One crash reported a perfect score and
  // destroyed the reference it needed to ever be useful again.
  // ⚠ THE EXIT CODE IS NOT THE DISCRIMINATOR, and guessing that it was cost a run:
  // vue-tsc exits **2** when it reports diagnostics (TypeScript's
  // DiagnosticsPresent_OutputsGenerated), so "status !== 1 means it crashed" called a
  // perfectly good measurement a crash. The honest question is whether the compiler
  // SPOKE: a run that produced no diagnostics at all and still failed did not measure.
  // That is decided below, once the output has been parsed.
  crashed = e.signal ? `signal ${e.signal}` : (e.status ? `exit ${e.status}` : 'unknown failure')
  failed = true
}

// 🔴 A CONFIGURATION DIAGNOSTIC IS NOT A MEASUREMENT (§DEPS FE 3b, 2026-09-29). Under TypeScript 6 a deprecated
// option in tsconfig.app.json (`baseUrl`, TS5101) makes vue-tsc print that ONE diagnostic and stop before it checks
// a single file. The parser below matched `tsconfig.app.json(7,5): error TS5101`, counted it as one error, printed
// "improved 350 -> 1", exited 0 and rewrote the baseline to {"total": 1}: a green that type-checked nothing
// (measured on TS 6.0.3). The guard below could not see it, because one diagnostic counts as "the compiler spoke".
// So a run that reports any diagnostic located in a tsconfig*.json, or carrying a TS5xxx/TS6xxx code (the
// compiler-option and project-setup ranges), is not a measurement: those lines are never counted, and the run
// refuses as DID NOT RUN with the baseline untouched. The refusal names what it saw, not why the compiler said it.
// ⚠ The "declared but never used" family (TS6133, TS6138, TS6192, TS6196, TS6198, TS6205) also sits in the 6xxx
// range. Those are errors only under noUnusedLocals/noUnusedParameters, which tsconfig.app.json turns off; turning
// them on makes this refuse loudly (measured: 279 x TS6133 -> DID NOT RUN, never a false count), so narrow the rule
// in that same change.
const CONFIG_DIAGNOSTIC = /\berror TS[56]\d{3}\b|^(?:.*[\\/])?tsconfig[^\\/]*\.json\(\d+,\d+\): error TS\d+/
const configDiagnostics = out.split('\n').filter((line) => CONFIG_DIAGNOSTIC.test(line))
if (configDiagnostics.length > 0) {
  console.error(`ratchet: DID NOT RUN: ${configDiagnostics.length} configuration-class diagnostic(s) (located in a tsconfig*.json, or a TS5xxx/TS6xxx code); a run that reports them is not counted as a measurement (${crashed || 'exit 0'}).`)
  console.error('The baseline is deliberately left untouched. The first of them:')
  console.error(configDiagnostics.slice(0, 6).join('\n'))
  process.exit(2)
}

const perFile = {}
let total = 0
for (const line of out.split('\n')) {
  const m = line.match(/^(.+?)\(\d+,\d+\): error TS\d+/)
  if (!m) continue
  total++
  perFile[m[1]] = (perFile[m[1]] || 0) + 1
}

// DID THE COMPILER SPEAK? Exit 0 = it ran and found nothing. Non-zero WITH parsed
// diagnostics = it ran and found them. Non-zero with NOTHING parsed = it never
// measured (OOM, a broken tsconfig, a missing binary) and must not be allowed to
// report — least of all to report zero.
if (failed && total === 0) {
  console.error(`ratchet: DID NOT RUN — the compiler produced no diagnostics and still failed (${crashed}).`)
  console.error('The baseline is deliberately left untouched: a gate that cannot measure must')
  console.error('not report, and must never lower its own bar on the strength of a crash.')
  console.error(out.split('\n').slice(0, 6).join('\n'))
  process.exit(2)
}

if (!existsSync(BASELINE)) {
  writeFileSync(BASELINE, JSON.stringify({ total, perFile }, null, 2))
  console.log(`ratchet: baseline recorded — ${total} errors`)
  process.exit(0)
}

const base = JSON.parse(readFileSync(BASELINE, 'utf8'))
if (total > base.total) {
  console.error(`ratchet: FAIL — ${total} errors > baseline ${base.total}. Regressed files:`)
  for (const [f, c] of Object.entries(perFile)) {
    if (c > (base.perFile[f] || 0)) console.error(`  ${f}: ${base.perFile[f] || 0} -> ${c}`)
  }
  process.exit(1)
}
if (total < base.total) {
  writeFileSync(BASELINE, JSON.stringify({ total, perFile }, null, 2))
  console.log(`ratchet: improved ${base.total} -> ${total}; baseline lowered.`)
} else {
  console.log(`ratchet: OK — ${total} errors (= baseline).`)
}
