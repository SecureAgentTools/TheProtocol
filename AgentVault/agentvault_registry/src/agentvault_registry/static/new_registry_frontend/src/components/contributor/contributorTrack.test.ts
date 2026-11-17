/**
 * V0665 art (gwo_0915581a208ca772961c96c9; his idea, room seq 4063, 4070, 4081): the contributor track's NEW badges, rings and titles.
 *
 * Held here:
 * - the catalog is what the design says: 14 rings, 10 corner badges, 16 titles of the design plus the proposed ones, every key unique;
 * - every item has its English name and unlock line in the bundle (a raw key on screen is the defect the i18n gate exists for);
 * - every ring renders at 22, 32 and 96 px (cover logo keeps a face, cover full has none), every badge at 16, 22 and 48 px, every
 *   title with one span per letter and its text as the label, and the Commander plate;
 * - the motion rules: no backdrop-filter, no canvas, no timer, the only script on the pointer is the Eye of the Senate's event handler
 *   (one requestAnimationFrame, in EarnedRing), and every component has a prefers-reduced-motion rule and a `still` switch;
 * - the old catalogs are NOT touched: the registry's frozensets are pinned by tests/test_flare_catalog_pinned_v0665.py, and none of the old
 *   components (FlareEncirclement, FlareBadge) is edited by this branch (their source does not mention a new key).
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import EarnedRing from './EarnedRing.vue'
import EarnedBadge from './EarnedBadge.vue'
import TitleEmblem from './TitleEmblem.vue'
import CommanderPlate from './CommanderPlate.vue'
import en from '@/i18n/locales/en.json'
import { BADGE_KEYS, COMMANDER_TITLE_KEY, GALLERY_SIZES, NEW_BADGES, NEW_RINGS, NEW_TITLES, PROPOSED_TITLE_KEYS, RING_KEYS, TITLE_KEYS, TITLE_MATERIAL } from '@/services/contributorTrack'

const here = (f: string) => readFileSync(fileURLToPath(new URL(f, import.meta.url)), 'utf-8')
const bundle = (en as any).contributorTrack

describe('the catalog', () => {
  it('has the design\'s items', () => {
    expect(NEW_RINGS).toHaveLength(14)
    expect(NEW_BADGES).toHaveLength(10)
    expect(NEW_TITLES.filter((t) => !t.proposed)).toHaveLength(16)
    expect(PROPOSED_TITLE_KEYS.length).toBeGreaterThanOrEqual(1)
    for (const keys of [RING_KEYS, BADGE_KEYS, TITLE_KEYS]) expect(new Set(keys).size).toBe(keys.length)
  })
  it('names the lineage of each ring and badge it grew from (his favourites are the bases)', () => {
    const byKey = Object.fromEntries(NEW_RINGS.map((r) => [r.key, r]))
    expect(byKey['eye-of-the-senate'].lineage).toBe('sauron')
    expect(byKey['watcher'].lineage).toBe('sauron')
    expect(byKey['event-horizon'].lineage).toBe('blackhole')
    expect(byKey['abyss'].lineage).toBe('void')
    expect(byKey['ember'].lineage).toBe('phoenix')
    expect(byKey['solar-flare'].lineage).toBe('inferno')
    expect(NEW_BADGES.filter((b) => b.lineage === 'architect').length).toBeGreaterThanOrEqual(3)
    expect(NEW_BADGES.filter((b) => b.lineage === 'founder').length).toBeGreaterThanOrEqual(2)
  })
  it('has an English name and an unlock line for every item (and the Commander plate)', () => {
    for (const k of RING_KEYS) expect(bundle.rings[k]?.name && bundle.rings[k]?.unlock, `ring ${k}`).toBeTruthy()
    for (const k of BADGE_KEYS) expect(bundle.badges[k]?.name && bundle.badges[k]?.unlock, `badge ${k}`).toBeTruthy()
    for (const k of [...TITLE_KEYS, COMMANDER_TITLE_KEY]) expect(bundle.titles[k]?.name && bundle.titles[k]?.unlock, `title ${k}`).toBeTruthy()
  })
})

describe('the rings', () => {
  for (const r of NEW_RINGS) {
    for (const px of GALLERY_SIZES) {
      it(`${r.key} renders at ${px} px`, () => {
        const w = mount(EarnedRing, { props: { ringKey: r.key, size: px, initials: 'SB' } })
        const root = w.find('.er')
        expect(root.exists()).toBe(true)
        expect(root.attributes('role')).toBe('img')
        expect(root.attributes('aria-label')).toBe(bundle.rings[r.key].name)
        expect(w.find('svg.er-art').exists()).toBe(true)
        expect(w.find('svg.er-art g').exists()).toBe(true)                       // the ring's own art is in it
        expect(root.attributes('style')).toContain(`--er-s: ${px}px`)
        expect(root.classes()).toContain(px < 28 ? 'er-d-s' : px < 64 ? 'er-d-m' : 'er-d-l')
        if (r.cover === 'logo') expect(w.find('.er-frame').exists()).toBe(true)      // the avatar stays visible
        else expect(w.find('.er-frame').exists()).toBe(false)                         // the art IS the face
      })
    }
  }
  it('an unknown key draws nothing and does not crash', () => {
    const w = mount(EarnedRing, { props: { ringKey: 'no-such-ring', size: 32 } })
    expect(w.find('svg.er-art g').exists()).toBe(false)
  })
  it('the still view stops every animation (the class the stylesheet keys on)', () => {
    const w = mount(EarnedRing, { props: { ringKey: 'lantern', size: 32, still: true } })
    expect(w.find('.er').classes()).toContain('er-still')
  })
})

describe('the badges', () => {
  for (const b of NEW_BADGES) {
    for (const px of [16, 22, 48]) {
      it(`${b.key} renders at ${px} px`, () => {
        const w = mount(EarnedBadge, { props: { badgeKey: b.key, size: px } })
        expect(w.find('.eb').attributes('role')).toBe('img')
        expect(w.find('.eb').attributes('aria-label')).toBe(bundle.badges[b.key].name)
        // a glyph: at least one drawn shape beyond the shared gradients
        expect(w.findAll('svg.eb-glyph g > *').length).toBeGreaterThan(1)
        expect(w.find('.eb').attributes('style')).toContain(`--eb-s: ${px}px`)
      })
    }
  }
})

describe('the titles', () => {
  for (const k of TITLE_KEYS) {
    for (const size of ['sidebar', 'card', 'large'] as const) {
      it(`${k} renders at ${size}`, () => {
        const w = mount(TitleEmblem, { props: { titleKey: k, size } })
        const text = bundle.titles[k].name as string
        expect(w.find('.te').attributes('aria-label')).toBe(text)
        expect(w.findAll('.te-ch')).toHaveLength(Array.from(text).filter((c) => c !== ' ').length)   // one span per letter, in words (an effect can reach one)
        expect(w.find('.te').classes()).toContain(`te-${k}`)
      })
    }
  }
  it('Off By One puts exactly one letter a pixel off', () => {
    const w = mount(TitleEmblem, { props: { titleKey: 'off-by-one' } })
    expect(w.findAll('.te-off')).toHaveLength(1)
  })
  it('The Eye Sees All has no O: ONE slit pupil, in the E of "Eye", the other letters plain (session-lead seq 4132)', () => {
    const w = mount(TitleEmblem, { props: { titleKey: 'the-eye-sees-all' } })
    const marked = w.findAll('.te-o')
    expect(marked).toHaveLength(1)
    expect(marked[0].text()).toBe('E')
    const name = bundle.titles['the-eye-sees-all'].name as string
    expect(name.split(' ')[1][0]).toBe('E')                                           // it is the first letter of the second word
  })
  it('any other title marks only its O letters', () => {
    const w = mount(TitleEmblem, { props: { titleKey: 'event-horizon' } })
    const os = (bundle.titles['event-horizon'].name.match(/o/gi) ?? []).length
    expect(w.findAll('.te-o')).toHaveLength(os)
  })
  it('a still frame shows a key moment of an animated title (the typed half, the shifted slices)', () => {
    const w = mount(TitleEmblem, { props: { titleKey: 'exactly-once', still: true } })
    const typed = w.findAll('.te-typed').length
    expect(typed).toBeGreaterThan(0)
    expect(typed).toBeLessThan(w.findAll('.te-ch').length)                          // half-typed, not all and not none
    const src = here('./TitleEmblem.vue')
    for (const k of ['bug-slayer', 'it-works-on-my-frame']) expect(src).toMatch(new RegExp(`\\.te-still\\.te-${k} \\.te-t::before \\{ opacity: 1;`))
  })
})

describe('the plates (one system, each title in its own material)', () => {
  it('every title has a material, and wears it as a class on the plate', () => {
    for (const k of TITLE_KEYS) {
      expect(TITLE_MATERIAL[k], k).toBeTruthy()
      const w = mount(TitleEmblem, { props: { titleKey: k, size: 'sidebar' } })
      expect(w.find('.te').classes()).toContain(`te-m-${TITLE_MATERIAL[k]}`)
      expect(w.find('.te-face').exists()).toBe(true)                                // the plate: a bevel (.te) round a face
    }
    expect(new Set(TITLE_KEYS.map((k) => TITLE_MATERIAL[k])).size).toBeGreaterThanOrEqual(8)   // a family, not one colour
  })
})

describe('the Commander plate', () => {
  it('renders the word and is one plate for every size', () => {
    for (const size of ['sidebar', 'card', 'large'] as const) {
      const w = mount(CommanderPlate, { props: { size } })
      expect(w.find('.cp').attributes('aria-label')).toBe('COMMANDER')
      expect(w.find('svg.cp-svg').exists()).toBe(true)
      expect(w.find('.cp-glow').exists()).toBe(true)                                 // the black glow behind it
      expect(w.findAll('.cp-svg text')).toHaveLength(2)                              // bare metal under, paint on top
    }
  })
})

describe('the motion rules (cheap motion only; a still frame for reduced motion)', () => {
  const files = ['EarnedRing.vue', 'EarnedBadge.vue', 'TitleEmblem.vue', 'CommanderPlate.vue']
  for (const f of files) {
    const src = here(`./${f}`)
    it(`${f}: no backdrop-filter, no canvas, no timer, a reduced-motion rule and a still switch`, () => {
      const code = src.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
      expect(code).not.toMatch(/backdrop-filter/)
      expect(code).not.toMatch(/<canvas/)
      expect(code).not.toMatch(/setInterval|setTimeout/)
      expect(code).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
      expect(code).toMatch(/-still\b/)
    })
  }
  it('the only per-frame script is the Eye of the Senate\'s pointer handler, one rAF in one file', () => {
    const counts = files.map((f) => (here(`./${f}`).match(/requestAnimationFrame/g) ?? []).length)
    expect(counts).toEqual([1, 0, 0, 0].map((n, i) => (files[i] === 'EarnedRing.vue' ? 1 : n)))
    const ring = here('./EarnedRing.vue')
    expect(ring).toMatch(/function onMove[\s\S]*eye-of-the-senate/)
  })
  it('colours in the drawings are real values: no var() inside an SVG gradient stop', () => {
    for (const f of files) {
      const stops = here(`./${f}`).match(/<stop [^>]*>/g) ?? []
      for (const s of stops) expect(s).not.toContain('var(')
    }
  })
})

describe('the old items are not touched', () => {
  it('neither old component mentions a new key', () => {
    const old = here('../common/FlareEncirclement.vue') + here('../common/FlareBadge.vue')
    for (const k of [...RING_KEYS, ...BADGE_KEYS]) {
      if (['void', 'blackhole', 'sauron', 'phoenix', 'inferno'].includes(k)) continue
      expect(old.includes(`'${k}'`) || old.includes(`"${k}"`), k).toBe(false)
    }
  })
})
