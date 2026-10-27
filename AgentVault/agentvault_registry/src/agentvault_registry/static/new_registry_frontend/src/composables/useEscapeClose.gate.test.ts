/**
 * §COCKPITDESK (2026-10-15) — a dialog listens for Escape through composables/useEscapeClose, never on its own overlay.
 *
 * An @keydown.esc on an overlay, backdrop, scrim or drawer hears an Escape only while the focus is inside it, and a dialog
 * opened by a button keeps the focus on that button, outside the teleported overlay: File a dispute, My Agents' Access and
 * about thirty more were deaf to Escape until they moved (V0616, V0617). A key handler on a field or a button (it holds its
 * own focus) is fine.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '..')
const OVERLAY = /class="[^"]*\b(overlay|backdrop|scrim|modal-bg|drawer)\b/

function vueFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : vueFiles(p)
    return e.name.endsWith('.vue') ? [p] : []
  })
}

/** The opening tags of a component's template that listen for Escape on an overlay. */
export function deafOverlays(source: string): string[] {
  const tpl = source.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '').replace(/<!--[\s\S]*?-->/g, '')
  return [...tpl.matchAll(/<[a-zA-Z][\w-]*\s[^>]*>/g)].map((m) => m[0])
    .filter((tag) => /@keydown\.esc(ape)?\b/.test(tag) && OVERLAY.test(tag))
    .map((tag) => tag.replace(/\s+/g, ' ').slice(0, 140))
}

describe('Escape on a dialog', () => {
  it('the detector sees the shape it exists for (a control that must fail)', () => {
    expect(deafOverlays('<template><div v-if="show" class="tp-overlay" @click.self="close" @keydown.esc="close"><p/></div></template>'))
      .toHaveLength(1)
    expect(deafOverlays('<template><input class="q" @keydown.esc="clear"/></template>')).toEqual([])
  })
  it('no overlay, backdrop, scrim or drawer listens for Escape on itself', () => {
    const bad = vueFiles(SRC).flatMap((f) => deafOverlays(fs.readFileSync(f, 'utf8')).map((t) => `${path.relative(SRC, f)}: ${t}`))
    expect(bad).toEqual([])
  })
})
