import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { withUnit } from './tourUnit'
import { TOURS } from './tourRegistry'

/**
 * §FESUITE V0597 (2026-10-11): the guided tours name the frame's own unit. Before: 27 "AVT" in six tours, the retired
 * JDAY/BVT named as the other frames' units, and the fiat tour's claim that "a non-AVT registry shows a notice" (the page
 * gates on the registry's fiat_onramp_enabled alone). A tour that names a unit again, or a renderer that shows a tour's
 * text without filling {unit}, fails here.
 */
const texts = TOURS.flatMap((tr) => [
  [`${tr.id}.title`, tr.title], [`${tr.id}.subtitle`, tr.subtitle ?? ''],
  ...tr.steps.flatMap((s) => [[`${tr.id}.${s.id}.title`, s.title], [`${tr.id}.${s.id}.body`, s.body ?? '']]),
] as Array<[string, string]>)
const read = (rel: string) => readFileSync(path.resolve(__dirname, rel), 'utf-8')

describe('the guided tours name the frame\'s own unit', () => {
  it('reads every tour (a loop over nothing passes)', () => {
    expect(TOURS.length).toBeGreaterThan(10)
    // fiat 9, token economy 5, the fleet 2, treasury, staking and disputes 1 each
    expect(texts.filter(([, v]) => v.includes('{unit}')).length).toBe(19)
  })

  it('no tour names AVT, JDAY or BVT', () => {
    expect(texts.filter(([, v]) => /\b(AVT|JDAY|BVT)\b/.test(v)).map(([k]) => k)).toEqual([])
  })

  it('the fiat tour says what the page gates on', () => {
    const fiat = TOURS.find((tr) => tr.id === 'fiat-onramp')!
    const all = fiat.steps.map((s) => s.body).join(' ')
    expect(all).not.toMatch(/non-AVT registry/)
    expect(all).toMatch(/has not opened the euro lane/)
  })

  it('fills the token with the frame\'s unit, and with words while the frame has not answered', () => {
    expect(withUnit('Buy {unit} (Fiat Onramp)', 'SBXA')).toBe('Buy SBXA (Fiat Onramp)')
    expect(withUnit('hold {unit} → send it; {unit}-per-€', 'ECU')).toBe('hold ECU → send it; ECU-per-€')
    expect(withUnit('Where {unit} comes from', '')).toBe("Where the frame's unit comes from")
    expect(withUnit(undefined, 'ACU')).toBe('')
  })

  it('every place that shows a tour\'s words fills the token', () => {
    const coach = read('./GuidedTour.vue')
    expect(coach).toContain('withUnit(tour.tour?.title, localCurrency)')
    expect(coach).toContain('withUnit(tour.currentStep.title, localCurrency)')
    expect(coach).toContain('md(withUnit(tour.currentStep.body, localCurrency))')
    expect(coach).toContain('withUnit(suggested.title, localCurrency)')
    expect(coach).not.toMatch(/\{\{\s*tour\.currentStep\.title\s*\}\}|md\(tour\.currentStep\.body\)/)
    const hub = read('../TutorialHub.vue')
    expect(hub.match(/withUnit\(tr\.title, localCurrency\)/g)?.length).toBe(2)
    expect(hub.match(/withUnit\(tr\.subtitle, localCurrency\)/g)?.length).toBe(2)
    expect(hub).not.toMatch(/\{\{\s*tr\.(title|subtitle)\s*\}\}/)
  })
})
