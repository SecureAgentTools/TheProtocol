import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import en from '@/i18n/locales/en.json'

/**
 * V0666 D2 (order gwo_f565ebd0575703f199dd9200): every contributions.* key the Contributions area, its admin inbox, the proposal into a line and the pure
 * helpers ask resolves in en.json, and the English there is the English the call site falls back to (a wording fix lands in both, or this fails). The stack's
 * raw-key gate (scratchpad/i18n_gate_rawkeys.py) scans the phone surface and does not reach these files; this is the console's own check of the same
 * question, for English. And the words: a code distribution is a release line, never anything that reads like a payout (AGORA's distributions pay holders).
 */
const root = path.resolve(__dirname, '../..')
const files = ['views/Contributions.vue', 'views/AdminContributionsInbox.vue', 'views/CodeChangeNew.vue', 'services/codeDistributions/lines.ts', 'services/codeChanges/propose.ts',
  // V0666 D3: the change in OurChat
  'components/ourstate/CodeChangeLive.vue', 'services/chat/changeDoor.ts', 'views/pocket/PocketOurStateThread.vue']
  .map((f) => path.join(root, f))
const CALL = /(?<![\w$.])(?:t|tp|tr)\(\s*(['"])(contributions\.[A-Za-z0-9_.]+)\1\s*(?:,\s*(['"])((?:\\.|(?!\3)[^\\])*)\3)?/g

type Ask = { file: string; key: string; fallback: string | null }
const asks: Ask[] = []
for (const f of files) {
  for (const m of fs.readFileSync(f, 'utf8').matchAll(CALL)) {
    asks.push({ file: path.basename(f), key: m[2], fallback: m[4] === undefined ? null : m[4].replace(/\\(['"\\])/g, '$1') })
  }
}
const resolve = (key: string): unknown => key.split('.').reduce<any>((o, k) => (o && typeof o === 'object' ? o[k] : undefined), en)
const strings = (o: unknown): string[] => (typeof o === 'string' ? [o] : o && typeof o === 'object' ? Object.values(o).flatMap(strings) : [])

describe('the Contributions keys resolve in en.json', () => {
  it('the scan sees the population it is about (not zero keys from a broken pattern)', () => {
    expect(new Set(asks.map((a) => a.file))).toEqual(new Set(files.map((f) => path.basename(f))))
    expect(new Set(asks.map((a) => a.key)).size).toBeGreaterThanOrEqual(100)
  })
  it('every asked key is a string in en.json', () => {
    expect([...new Set(asks.filter((a) => typeof resolve(a.key) !== 'string').map((a) => `${a.file}: ${a.key}`))]).toEqual([])
  })
  it('the English in en.json is the English the call site falls back to', () => {
    expect(asks.filter((a) => a.fallback !== null && resolve(a.key) !== a.fallback).map((a) => `${a.file}: ${a.key}: "${String(resolve(a.key))}" vs "${a.fallback}"`)).toEqual([])
  })
  it('no string says a word that reads like a payout: a code distribution is a release line', () => {
    const all = strings((en as any).contributions).concat([(en as any).nav.items.contributions, (en as any).nav.items.contributionsInbox])
    expect(all.length).toBeGreaterThanOrEqual(100)
    expect(all.filter((s) => /\b(payout|dividend|reward|yield|stake|staking|token|earn|profit|interest|APY)\b/i.test(s))).toEqual([])
    expect(all.filter((s) => /distribution/i.test(s) && !/code distributions?/i.test(s))).toEqual([])
  })
})
