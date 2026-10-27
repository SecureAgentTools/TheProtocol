import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * §FEFRAME (2026-10-01, his words "make the hover-only copy buttons visible on touch too"): NO CONTROL THAT ONLY A
 * HOVER CAN REVEAL.
 *
 * A phone has no hover. A control that rests at opacity 0 and appears on hover is still tappable there, but nobody
 * can see it: the copy buttons on every docs code block, Discovery's "view details" buttons, the tutorial inspector's
 * copy button, IRONHAND's copy hint and the Senate tier card's call to action all did this. Two shapes are read:
 *   - a class list with `opacity-0` and a hover reveal (`hover:`/`group-hover:`/`peer-hover:opacity-100`) must also
 *     carry `touch:opacity-100` (main.css: @media (hover: none));
 *   - a style block whose `X:hover Y { opacity: 1 }` reveals a selector that rests at `opacity: 0` must also show Y
 *     inside `@media (hover: none)`.
 */
const SRC = path.resolve(__dirname, '..')

// Reveals that are not controls, each with the reason it may stay hover-only.
const NOT_A_CONTROL: Record<string, string> = {
  'components/ui/NeuralCard.vue: .nc-card-has-glow:hover .nc-card-glow': 'a decorative glow',
  'views/MyAgents.vue: .card-flare-collapse-btn:hover .card-flare-collapse-label':
    'the button is visible (its icon); the label is an expansion, also shown on focus',
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (/\.(vue|ts|css)$/.test(e.name) && !/\.test\.ts$/.test(e.name)) out.push(full)
  }
  return out
}

function classOffences(text: string): string[] {
  const out: string[] = []
  for (const m of text.matchAll(/(?:\bclass\s*=\s*"([^"]*)"|'([^'\n]*)'|`([^`\n]*)`)/g)) {
    const words = (m[1] ?? m[2] ?? m[3]).split(/\s+/)
    const hidden = words.includes('opacity-0')
    const revealed = words.some((w) => /^(?:[a-z-]+:)*(?:group-|peer-)?hover:opacity-100$/.test(w))
    if (hidden && revealed && !words.includes('touch:opacity-100')) out.push(words.join(' ').slice(0, 120))
  }
  return out
}

function cssOffences(text: string): string[] {
  const out: string[] = []
  const css = [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join('\n') || text
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const rules = [...clean.matchAll(/([^{}@]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }))
  const atRest = new Set(rules.filter((r) => /(^|;)\s*opacity\s*:\s*0\s*(;|$)/.test(r.body)).flatMap((r) => r.sel.split(',').map((s) => s.trim())))
  const touch = [...clean.matchAll(/@media\s*\(\s*hover\s*:\s*none\s*\)\s*\{([\s\S]*?\})\s*\}/g)].map((m) => m[1]).join('\n')
  for (const r of rules) {
    if (!/opacity\s*:\s*1\b/.test(r.body)) continue
    for (const part of r.sel.split(',').map((s) => s.trim())) {
      const m = part.match(/^(.*):hover\s+(.+?)\)?$/)
      if (!m) continue
      const revealed = m[2].replace(/\)$/, '')
      const resting = [...atRest].find((s) => s.replace(/:deep\(|\)/g, '').trim().endsWith(revealed.replace(/:deep\(|\)/g, '').trim()))
      if (resting && !touch.includes(revealed.replace(/:deep\(|\)/g, '').trim().split(/\s+/).pop() as string)) out.push(part.slice(0, 120))
    }
  }
  return out
}

describe('no control that only a hover reveals', () => {
  it('the gate sees both shapes (controls)', () => {
    expect(classOffences('<button class="p-1 opacity-0 group-hover:opacity-100">')).toHaveLength(1)
    expect(classOffences('<button class="p-1 opacity-0 group-hover:opacity-100 touch:opacity-100">')).toEqual([])
    expect(classOffences('<span class="opacity-0 transition-opacity">')).toEqual([])
    const hidden = '<style scoped>\n.cell .ico { opacity: 0; }\n.cell:hover .ico { opacity: 1; }\n</style>'
    expect(cssOffences(hidden)).toHaveLength(1)
    expect(cssOffences(hidden.replace('</style>', '@media (hover: none) { .ico { opacity: 1; } }\n</style>'))).toEqual([])
    expect(cssOffences('<style>\n.card::before { opacity: 0; }\n.card:hover::before { opacity: 1; }\n</style>')).toEqual([])
  })

  it('no file carries one', () => {
    const files = walk(SRC)
    expect(files.length).toBeGreaterThan(300)
    const bad: string[] = []
    for (const f of files) {
      const text = fs.readFileSync(f, 'utf8')
      for (const o of [...classOffences(text), ...cssOffences(text)]) {
        const key = `${path.relative(SRC, f)}: ${o}`
        if (!(key in NOT_A_CONTROL)) bad.push(key)
      }
    }
    expect(bad).toEqual([])
  })

  it('every exemption still names a reveal that exists (no stale entry)', () => {
    for (const key of Object.keys(NOT_A_CONTROL)) {
      const [file, sel] = key.split(': ')
      expect(fs.readFileSync(path.join(SRC, file), 'utf8')).toContain(sel.split(' ').pop() as string)
    }
  })
})
