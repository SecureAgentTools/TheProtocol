import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { createI18n } from 'vue-i18n'

/**
 * §FESUITE V0596 (2026-10-11): the fiat pages (/become-a-backer, its welcome page, /founders-wall) name the frame's own
 * unit. They said "AVT" on every frame, also where the unit is SBXA, ECU or ACU (51's one standing red on sbx-alpha).
 * Every string of the three namespaces carries {unit} where it named the unit, in all nine bundles, and every call site
 * passes the frame's unit; a bundle value that names AVT again, or a call that drops the unit, fails here.
 */
const NS = ['backerView', 'backerWelcomeView', 'founderWall']
const LOCALES = path.resolve(__dirname, '../i18n/locales') + '/'
const VIEWS = ['BecomeABacker.vue', 'BackerWelcome.vue', 'FoundersWall.vue']
const view = (name: string) => readFileSync(path.resolve(__dirname, name), 'utf-8')

type Tree = { [k: string]: string | Tree }
function walk(o: Tree, p = ''): Array<[string, string]> {
  return Object.entries(o).flatMap(([k, v]) =>
    typeof v === 'string' ? [[p ? `${p}.${k}` : k, v] as [string, string]] : walk(v, p ? `${p}.${k}` : k))
}
const bundle = (file: string): Tree => JSON.parse(readFileSync(LOCALES + file, 'utf-8'))
const strings = (file: string) => walk(bundle(file)).filter(([k]) => NS.includes(k.split('.')[0]))
const files = readdirSync(LOCALES).filter((f) => f.endsWith('.json'))
const unitKeys = strings('en.json').filter(([, v]) => v.includes('{unit}')).map(([k]) => k)

describe('the fiat pages name the frame\'s own unit', () => {
  it('has the nine bundles and the English unit strings to check', () => {
    expect(files.length).toBe(9)
    expect(unitKeys.length).toBe(26)
  })

  it.each(files)('%s names no AVT in the three namespaces', (file) => {
    expect(strings(file).filter(([, v]) => v.includes('AVT')).map(([k]) => k)).toEqual([])
  })

  it.each(files)('%s carries {unit} only where English does', (file) => {
    const extra = strings(file).filter(([k, v]) => v.includes('{unit}') && !unitKeys.includes(k)).map(([k]) => k)
    expect(extra).toEqual([])
  })

  it('every call of a unit string passes the unit', () => {
    const sources = VIEWS.map(view).join('\n')
    const dropped: string[] = []
    let calls = 0
    for (const key of unitKeys) {
      const re = new RegExp(`t\\('${key.replace(/\./g, '\\.')}'(.{0,24})`, 'g')
      for (const m of sources.matchAll(re)) {
        calls += 1
        if (!/^,\s*\{\s*unit:\s*localCurrency/.test(m[1])) dropped.push(key)
      }
    }
    expect(dropped).toEqual([])
    expect(calls).toBe(25) // backerView.form.rate has no call site
  })

  it('the founders feed and the minting tooltip follow the frame\'s unit', () => {
    expect(view('FoundersWall.vue')).not.toMatch(/\}\}\s*AVT</)
    expect(view('BecomeABacker.vue')).not.toMatch(/mint AVT|acquire AVT/)
  })

  it.each(['en', 'de'])('vue-i18n renders every unit string with the frame\'s unit (%s)', (locale) => {
    // the bundles are read at run time: no schema to type keys by, and vue-i18n's generics instantiate too deep (TS2589)
    type Loose = (o: Record<string, unknown>) => { global: { t: (key: string, params: Record<string, string>) => string } }
    const { t } = (createI18n as unknown as Loose)({ legacy: false, locale, fallbackLocale: 'en',
      messages: { en: bundle('en.json'), [locale]: bundle(`${locale}.json`) } }).global
    expect(unitKeys.length).toBeGreaterThan(0) // a loop over nothing passes; this one must render something
    for (const key of unitKeys) {
      const out = t(key, { unit: 'SBXA' })
      expect(out, key).toContain('SBXA')
      expect(out, key).not.toMatch(/\{unit\}|AVT/)
    }
  })
})
