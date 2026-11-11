import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import en from '@/i18n/locales/en.json'

/**
 * V0660 (e), fix 6: every quantumCard key the quantum card, its lattice and its filters ask resolves in en.json, and
 * the English there is the English the call site falls back to (so a wording fix lands in both, or this fails). The
 * stack's raw-key gate (scratchpad/i18n_gate_rawkeys.py) does not reach components/quantum yet; this is the console's
 * own check of the same question, for English.
 */
const dirs = [path.resolve(__dirname), path.resolve(__dirname, '../../services/quantum')]
const files = dirs.flatMap((d) => fs.readdirSync(d)
  .filter((f) => /\.(vue|ts)$/.test(f) && !/\.test\.ts$/.test(f))
  .map((f) => path.join(d, f)))
const CALL = /(?<![\w$.])(?:t|tp)\(\s*(['"])(quantumCard\.[A-Za-z0-9_.]+)\1\s*(?:,\s*(['"])((?:\\.|(?!\3)[^\\])*)\3)?/g

type Ask = { file: string; key: string; fallback: string | null }
const asks: Ask[] = []
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8')
  for (const m of src.matchAll(CALL)) {
    asks.push({ file: path.basename(f), key: m[2], fallback: m[4] === undefined ? null : m[4].replace(/\\(['"\\])/g, '$1') })
  }
}
const resolve = (key: string): unknown => key.split('.').reduce<any>((o, k) => (o && typeof o === 'object' ? o[k] : undefined), en)

describe('the quantum card\'s keys resolve in en.json', () => {
  it('the scan sees the population it is about (not zero keys from a broken pattern)', () => {
    expect(files.some((f) => f.endsWith('QuantumCard.vue'))).toBe(true)
    expect(new Set(asks.map((a) => a.key)).size).toBeGreaterThanOrEqual(100)
  })

  it('every asked quantumCard key is a string in en.json', () => {
    const missing = [...new Set(asks.filter((a) => typeof resolve(a.key) !== 'string').map((a) => `${a.file}: ${a.key}`))]
    expect(missing).toEqual([])
  })

  it('the English in en.json is the English the call site falls back to', () => {
    const differ = asks.filter((a) => a.fallback !== null && resolve(a.key) !== a.fallback)
      .map((a) => `${a.file}: ${a.key}: en.json "${String(resolve(a.key))}" vs "${a.fallback}"`)
    expect(differ).toEqual([])
  })
})
