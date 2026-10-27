import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * §FESUITE (2026-10-01): EVERY <select> HAS A NAME. A select a screen reader cannot name is announced as "combo box",
 * nothing more (axe `select-name`, critical). The console lifecycle suite found them one page at a time; this ratchet
 * counts them all, statically, so the number can only go down.
 *
 * A select is named when it carries aria-label / aria-labelledby / title (static or bound), when a <label for> in the
 * same file names its id, or when it sits inside a <label>. The count may not rise above CEILING; when it falls, lower
 * CEILING to the new count in the same change.
 */
const CEILING = 14 // measured 2026-10-01 (§FESUITE): 14 left of the 93 first counted (28 at worker C's pass); lower it as names are added

const SRC = path.resolve(__dirname, '..')

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else if (e.name.endsWith('.vue')) out.push(full)
  }
  return out
}

function templateOf(text: string): { body: string; offset: number } {
  const start = text.indexOf('<template')
  const end = text.lastIndexOf('</template>')
  if (start < 0 || end < 0) return { body: '', offset: 0 }
  return { body: text.slice(start, end), offset: start }
}

/** Every <select> in a file that nothing names, as "file:line". */
export function unnamedSelects(file: string, text: string): string[] {
  const { body, offset } = templateOf(text)
  const out: string[] = []
  const forIds = new Set([...body.matchAll(/<label\b[^>]*\bfor="([^"]+)"/g)].map((m) => m[1]))
  const boundFors = new Set([...body.matchAll(/<label\b[^>]*:for="([^"]+)"/g)].map((m) => m[1].trim()))
  // an attribute value may hold a ">" (v-if="n > 1"): read the tag to its first unquoted ">"
  for (const m of body.matchAll(/<select\b((?:[^>"']|"[^"]*"|'[^']*')*)>/g)) {
    const attrs = m[1]
    if (/(?:^|\s)(?::|v-bind:)?(?:aria-label|aria-labelledby|title)\s*=/.test(attrs)) continue
    const id = attrs.match(/(?:^|\s)id="([^"]+)"/)?.[1]
    if (id && forIds.has(id)) continue
    const boundId = attrs.match(/(?:^|\s):id="([^"]+)"/)?.[1]?.trim()
    if (boundId && boundFors.has(boundId)) continue
    const before = body.slice(0, m.index)
    if (before.lastIndexOf('<label') > before.lastIndexOf('</label>')) continue
    const line = text.slice(0, offset + (m.index ?? 0)).split('\n').length
    out.push(`${path.relative(SRC, file)}:${line}`)
  }
  return out
}

describe('every <select> has a name', () => {
  it('the rule reads the shapes it claims to', () => {
    const named = [
      '<template><select aria-label="Status"></select></template>',
      '<template><select :aria-label="t(\'x\')"></select></template>',
      '<template><label for="s1">Status</label><select id="s1"></select></template>',
      '<template><label>Status <select></select></label></template>',
      '<template><select title="Status"></select></template>',
    ]
    for (const t of named) expect(unnamedSelects('x.vue', t), t).toEqual([])
    expect(unnamedSelects('x.vue', '<template><label>Status</label><select class="a"></select></template>')).toHaveLength(1)
    expect(unnamedSelects('x.vue', '<template><select id="s2"></select><label for="s3">x</label></template>')).toHaveLength(1)
    // a ">" inside an attribute value does not end the tag
    expect(unnamedSelects('x.vue', '<template><select v-if="n > 1" aria-label="Agent"></select></template>')).toEqual([])
  })

  it(`no more unnamed selects than the ceiling`, () => {
    const all = walk(SRC).flatMap((f) => unnamedSelects(f, fs.readFileSync(f, 'utf8')))
    if (all.length < CEILING) console.info(`unnamed selects: ${all.length} (ceiling ${CEILING}): lower CEILING`)
    expect(all.length, `unnamed selects above the ceiling:\n${all.join('\n')}`).toBeLessThanOrEqual(CEILING)
  })
})
