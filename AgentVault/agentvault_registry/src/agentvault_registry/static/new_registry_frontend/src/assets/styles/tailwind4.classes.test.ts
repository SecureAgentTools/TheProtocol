import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * §FEFRAME Tailwind 4 (2026-10-01): NO v3 CLASS THAT TAILWIND 4 DROPS OR DRAWS DIFFERENTLY.
 *
 * Tailwind 4 builds an unknown utility into nothing, without a warning. After the upgrade tool and a hand pass,
 * `bg-gray-500 bg-opacity-75` was still in BaseModal: the build was green and every BaseModal backdrop would have
 * turned SOLID grey (the hand pass had fixed four of the five siblings). The upgrade tool leaves every `*-opacity-*`
 * alone. A few other v3 names still build and look different in 4.3.3:
 *   - bare `ring` is 1px (v3: 3px)                               -> write ring-3
 *   - `outline-none` drops the forced-colours outline v3 kept     -> write outline-hidden
 *   - `bg-gradient-to-*` / `bg-linear-to-*` blend in oklab        -> write bg-linear-to-*\/srgb (v3's sRGB blend)
 * Code written from v3 habit (or a branch rebased onto this one) brings exactly these, so the gate reads every class
 * context: class="..." and :class="..." attributes, @apply, and quoted strings that are class lists.
 *
 * Not gated, because the name is valid in both versions with a different value (v3 name -> v4 name):
 * shadow-sm -> shadow-xs, rounded-sm -> rounded-xs, blur-sm -> blur-xs, drop-shadow-sm -> drop-shadow-xs
 * (and bare shadow/rounded/blur/drop-shadow -> the -sm names, which 4.3.3 still builds with v3's values). Review a
 * v3-habit hunk against this list by hand.
 *
 * Choosing v4's own look later (oklab gradients, the 1px ring) is a design decision: change the rule here with it.
 */
const SRC = path.resolve(__dirname, '..', '..')

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (/\.(vue|ts|css)$/.test(e.name) && !/\.test\.ts$/.test(e.name)) out.push(full)
  }
  return out
}

// A word that looks like a utility class (variant prefixes allowed); a quoted string counts as a class list only when
// most of its words look like this, so prose, i18n keys and data ids ('ring', 'shadow') are never read.
const UTIL = /^!?(?:[a-z0-9-]+:)*!?-?(?:bg|text|border|rounded|shadow|ring|outline|p[xytblr]?|m[xytblr]?|w|h|min-w|min-h|max-w|max-h|flex|grid|gap|items|justify|self|font|leading|tracking|from|to|via|shrink|grow|absolute|relative|fixed|sticky|top|bottom|left|right|inset|overflow|truncate|whitespace|cursor|select|pointer|opacity|transition|duration|ease|animate|transform|scale|rotate|translate|space|divide|z|block|inline|hidden|underline|uppercase|italic|sr|object|backdrop|drop|blur)(?:-[\w./%[\]()#:-]+)?$/

const RULES: Array<[RegExp, string]> = [
  [/^(?:bg|text|border|divide|ring|ring-offset|placeholder)-opacity-\d+$/, 'removed in Tailwind 4 (builds to nothing): use the colour modifier, e.g. bg-black/75'],
  [/^ring$/, 'bare ring is 1px in Tailwind 4 (v3: 3px): write ring-3'],
  [/^outline-none$/, 'outline-none drops the forced-colours outline in Tailwind 4: write outline-hidden (v3\'s outline-none)'],
  [/^bg-gradient-to-[a-z]+$/, 'blends in oklab in Tailwind 4: write bg-linear-to-<dir>/srgb (v3\'s sRGB blend)'],
  [/^bg-linear-to-[a-z]+$/, 'blends in oklab: write bg-linear-to-<dir>/srgb (v3\'s sRGB blend), or change this gate with the design'],
]

function classLists(text: string): string[] {
  const out: string[] = []
  for (const m of text.matchAll(/(?:\bclass\s*=\s*"([^"]*)"|:class\s*=\s*"([^"]*)"|@apply\s+([^;}\n]*))/g)) {
    const v = m[1] ?? m[2] ?? m[3]
    if (m[2] !== undefined) {
      // a binding: the class words live in its string literals
      for (const s of v.matchAll(/'([^'\n]*)'|`([^`\n]*)`/g)) out.push(s[1] ?? s[2])
    } else out.push(v)
  }
  for (const s of text.matchAll(/'([^'\n]{3,})'|"([^"\n]{3,})"|`([^`\n]{3,})`/g)) {
    const v = s[1] ?? s[2] ?? s[3]
    const words = v.trim().split(/\s+/)
    if (words.length >= 2 && words.filter((w) => UTIL.test(w)).length >= Math.max(2, Math.ceil(words.length * 0.8))) out.push(v)
  }
  return out
}

function offences(text: string): string[] {
  const found = new Set<string>()
  for (const list of classLists(text)) {
    for (const word of list.split(/\s+/)) {
      const bare = word.replace(/^!?(?:[a-z0-9-]+:)*!?/, '')
      for (const [rx, why] of RULES) if (rx.test(bare)) found.add(`${word}: ${why}`)
    }
  }
  return [...found]
}

describe('Tailwind 4: no v3 class that v4 drops or draws differently', () => {
  it('the gate sees each case (controls)', () => {
    expect(offences('<div class="fixed inset-0 bg-gray-500 bg-opacity-75" />')).toHaveLength(1)
    expect(offences('<input :class="[ok ? \'focus:ring\' : \'\']" class="p-2">')).toHaveLength(1)
    expect(offences('const c = \'px-2 py-1 outline-none focus:ring-2\'')).toHaveLength(1)
    expect(offences('@apply bg-linear-to-r from-primary-600 to-sovereign-purple;')).toHaveLength(1)
    expect(offences('<span class="bg-gradient-to-r from-cyan-300 to-violet-400">')).toHaveLength(1)
    // and stays quiet on what is fine, and on words that are not classes
    expect(offences('<div class="bg-gray-500/75 ring-3 outline-hidden bg-linear-to-r/srgb from-a to-b">')).toEqual([])
    expect(offences("const mode = 'shadow'; const id = 'ring'; const msg = 'Ring the outline'")).toEqual([])
  })

  it('no file carries one', () => {
    const files = walk(SRC)
    expect(files.length).toBeGreaterThan(300)
    const bad: string[] = []
    for (const f of files) for (const o of offences(fs.readFileSync(f, 'utf8'))) bad.push(`${path.relative(SRC, f)}: ${o}`)
    expect(bad).toEqual([])
  })
})
