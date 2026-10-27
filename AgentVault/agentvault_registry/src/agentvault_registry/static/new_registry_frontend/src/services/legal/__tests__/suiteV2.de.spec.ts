/**
 * §LEGALKIT B8: the German set is a TRANSLATION of the English source, never a different document. This gate
 * compares the two structurally (pages, section numbers, anchors, the presence of every field, subsection and item
 * counts) and by TOKEN multiset per section (a translation that drops {LOCAL_UNIT} or invents {PROVIDER_NAME} is
 * refused), and it proves itself on a planted defect: a copy with one token removed must be reported.
 */
import { describe, it, expect } from 'vitest'
import { LEGAL_SUITE_V2, type LegalPageV2, type LegalSectionV2 } from '@/content/legal/suiteV2'
import { LEGAL_SUITE_V2_DE } from '@/content/legal/suiteV2.de'

const TOKEN = /\{[A-Z_]+\}/g
/** A section label that is a WORD is translated; the letter it carries is not. Nothing else in `number` may change. */
const NUMBER_EQUIV: Record<string, string> = { 'Annex A': 'Anlage A' }

function tokensOf(section: LegalSectionV2): string[] {
  const parts: string[] = [section.title, section.plain ?? '', section.content ?? '', section.important ?? '', section.critical ?? '',
    ...(section.items ?? []), ...(section.subsections ?? []).flatMap((s) => [s.title, s.content, ...(s.items ?? [])])]
  return parts.join('\n').match(TOKEN)?.sort() ?? []
}

/** Every structural difference between an English page and its translation, as sentences. Empty = a translation. */
export function structuralDiff(key: string, en: LegalPageV2, de: LegalPageV2): string[] {
  const out: string[] = []
  for (const f of ['version', 'owner', 'icon'] as const) if (en[f] !== de[f]) out.push(`${key}: ${f} differs (${en[f]} vs ${de[f]})`)
  if (en.sections.length !== de.sections.length) { out.push(`${key}: ${en.sections.length} sections vs ${de.sections.length}`); return out }
  en.sections.forEach((s, i) => {
    const d = de.sections[i]
    const at = `${key} section ${i} (${s.number ?? s.title})`
    if ((s.number ? NUMBER_EQUIV[s.number] ?? s.number : null) !== (d.number ?? null)) out.push(`${at}: number ${s.number} vs ${d.number}`)
    if ((s.anchor ?? null) !== (d.anchor ?? null)) out.push(`${at}: anchor differs`)
    for (const f of ['plain', 'content', 'important', 'critical', 'items', 'subsections'] as const) {
      if (Boolean(s[f]) !== Boolean(d[f])) out.push(`${at}: ${f} present on one side only`)
    }
    if ((s.items?.length ?? 0) !== (d.items?.length ?? 0)) out.push(`${at}: ${s.items?.length ?? 0} items vs ${d.items?.length ?? 0}`)
    if ((s.subsections?.length ?? 0) !== (d.subsections?.length ?? 0)) out.push(`${at}: ${s.subsections?.length ?? 0} subsections vs ${d.subsections?.length ?? 0}`)
    ;(s.subsections ?? []).forEach((sub, j) => {
      const dsub = d.subsections?.[j]
      if (dsub && (sub.items?.length ?? 0) !== (dsub.items?.length ?? 0)) out.push(`${at} subsection ${j}: item count differs`)
      // the numbering of a subsection title ("13.3 ...") must survive translation
      const num = sub.title.match(/^[0-9]+(\.[0-9]+)*/)?.[0]
      if (num && dsub && !dsub.title.startsWith(num)) out.push(`${at} subsection ${j}: numbering ${num} lost`)
    })
    const te = tokensOf(s), td = tokensOf(d)
    if (te.join(',') !== td.join(',')) out.push(`${at}: tokens ${te.join(',') || '(none)'} vs ${td.join(',') || '(none)'}`)
  })
  return out
}

describe('the German legal set', () => {
  it('covers the consumer-facing core and nothing that has no English source', () => {
    const keys = Object.keys(LEGAL_SUITE_V2_DE).sort()
    // §COOKIES (2026-10-02): the Cookie and Browser Storage Policy joined Terms, Privacy Policy and Risk Notice
    expect(keys).toEqual(['cookies', 'disclaimer', 'privacy', 'terms'])
    for (const k of keys) expect(LEGAL_SUITE_V2[k], `no English page ${k}`).toBeTruthy()
  })

  it('is structurally the English document, token for token', () => {
    const problems = Object.entries(LEGAL_SUITE_V2_DE).flatMap(([k, de]) => structuralDiff(k, LEGAL_SUITE_V2[k], de!))
    expect(problems).toEqual([])
  })

  it('says it is a translation and names the language clause on the pages a consumer accepts', () => {
    expect(LEGAL_SUITE_V2_DE.terms!.sections[0].subsections![6].content).toMatch(/Übersetzung/)
    expect(LEGAL_SUITE_V2_DE.terms!.subtitle).toMatch(/§ 1\.7/)
    expect(LEGAL_SUITE_V2_DE.privacy!.subtitle).toMatch(/englische Fassung/)
    expect(LEGAL_SUITE_V2_DE.disclaimer!.subtitle).toMatch(/englische Fassung/)
    expect(LEGAL_SUITE_V2_DE.cookies!.subtitle).toMatch(/englische Fassung/)
  })

  it('control: a translation with one token dropped, one item lost or a number changed is refused', () => {
    const en = LEGAL_SUITE_V2.terms
    const clone = (): LegalPageV2 => JSON.parse(JSON.stringify(LEGAL_SUITE_V2_DE.terms))
    const dropped = clone()
    dropped.sections[3].subsections![0].content = dropped.sections[3].subsections![0].content.replace('{LOCAL_UNIT}', 'ECU')
    expect(structuralDiff('terms', en, dropped).some((p) => p.includes('tokens'))).toBe(true)
    const lost = clone()
    // § 3.3 carries the list of prohibited uses since 2026-09-30 (it rendered after § 3.6 while it sat on the section)
    lost.sections[2].subsections![2].items!.pop()
    expect(structuralDiff('terms', en, lost).some((p) => p.includes('item count differs'))).toBe(true)
    const renumbered = clone()
    renumbered.sections[12].subsections![2].title = '13.4 ' + renumbered.sections[12].subsections![2].title.slice(5)
    expect(structuralDiff('terms', en, renumbered).some((p) => p.includes('numbering'))).toBe(true)
    // and the real translation passes the same comparator (the control is not a different instrument)
    expect(structuralDiff('terms', en, clone())).toEqual([])
  })
})
