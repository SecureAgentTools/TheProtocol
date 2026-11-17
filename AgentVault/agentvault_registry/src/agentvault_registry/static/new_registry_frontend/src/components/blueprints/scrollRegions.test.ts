import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0662 console polish, item 12 (order gwo_0aa7b875cbf65b6347f5f775): every blueprint page's scroll container is
 * reachable by keyboard. V0660 (m) fixed one chamber's data so its sizing table fit a 412 px phone, and backlogged the
 * view-side fix (axe scrollable-region-focusable: a scroll container no keyboard can reach). This is that fix, for
 * every table and wiring block the blueprint pages share: each element whose class scrolls (overflow auto in the
 * file's own style block) is focusable, a region, and named, the pattern GovernanceDocs.vue and ExchangeDesk.vue use.
 * Red on f569f6a6e: the table wraps, the wiring bodies and the safety index scroll with no tabindex.
 */
const SRC = path.resolve(__dirname, '../..')
const FILES = ['views/BlueprintDetailView.vue', 'views/BlueprintsView.vue',
  ...fs.readdirSync(path.join(SRC, 'components/blueprints')).filter((f) => f.endsWith('.vue')).map((f) => `components/blueprints/${f}`)]

function scrollers(file: string): { cls: string; tags: string[] }[] {
  const src = fs.readFileSync(path.join(SRC, file), 'utf8')
  const style = src.slice(src.lastIndexOf('<style'))
  const template = src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>'))
  const classes = new Set<string>()
  for (const m of style.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (!/overflow(?:-x|-y)?\s*:\s*(?:auto|scroll)/.test(m[2])) continue
    for (const sel of m[1].split(',')) {
      const last = sel.trim().split(/\s+/).pop() || ''
      const c = last.match(/^\.([\w-]+)$/)
      if (c) classes.add(c[1])
    }
  }
  return [...classes].map((cls) => ({
    cls,
    tags: [...template.matchAll(new RegExp(`<[a-zA-Z][\\w-]*\\b[^>]*class="[^"]*\\b${cls}\\b[^"]*"[^>]*>`, 'g'))].map((m) => m[0]),
  }))
}

describe('the blueprint pages\' scroll containers take the keyboard', () => {
  const all = FILES.flatMap((f) => scrollers(f).map((s) => ({ file: f, ...s })))

  it('the scan sees the population it is about', () => {
    const tags = all.flatMap((s) => s.tags)
    expect(tags.length, 'the sizing table, the cast and primitives tables, the wiring blocks, the safety index').toBeGreaterThanOrEqual(6)
  })

  it('each one is focusable, a region, and named', () => {
    const bad: string[] = []
    for (const s of all) {
      for (const tag of s.tags) {
        if (!/\stabindex="0"/.test(tag) || !/\srole="region"/.test(tag) || !/\s:?aria-label(?:ledby)?="/.test(tag)) bad.push(`${s.file}: ${tag}`)
      }
    }
    expect(bad).toEqual([])
  })

  it('each shows where the focus is', () => {
    for (const f of FILES) {
      const src = fs.readFileSync(path.join(SRC, f), 'utf8')
      const style = src.slice(src.lastIndexOf('<style'))
      for (const s of scrollers(f).filter((x) => x.tags.length)) {
        expect(style, `${f}: .${s.cls}:focus-visible`).toMatch(new RegExp(`\\.${s.cls}:focus-visible`))
      }
    }
  })
})
