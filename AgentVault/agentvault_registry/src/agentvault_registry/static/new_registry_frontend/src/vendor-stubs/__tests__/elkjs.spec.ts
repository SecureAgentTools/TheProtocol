/**
 * F10 of REVIEW_2026-09-30_LICENSING.md: elkjs (EPL-2.0) must not ship in the AGPL frontend. The build gate greps the
 * dist for the ELK code itself; this file pins the two halves a reader can break by hand: the alias and the refusal.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import ELK from '../elkjs'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')

describe('the elkjs stand-in', () => {
  it('refuses a layout with a message that names the reason', async () => {
    await expect(new ELK().layout()).rejects.toThrow(/elk layout is not part of this build.*EPL-2\.0/)
  })

  it('is what both elkjs specifiers resolve to', () => {
    const cfg = readFileSync(resolve(ROOT, 'vite.config.ts'), 'utf8')
    expect(cfg).toMatch(/'elkjs\/lib\/elk\.bundled\.js':\s*fileURLToPath\(new URL\('\.\/src\/vendor-stubs\/elkjs\.ts'/)
    expect(cfg).toMatch(/'elkjs':\s*fileURLToPath\(new URL\('\.\/src\/vendor-stubs\/elkjs\.ts'/)
  })

  it('leaves no diagram in the tree asking for the elk layout', () => {
    // the one renderer; a diagram that sets layout elk would break with the stub, so it must not exist
    const renderer = readFileSync(resolve(ROOT, 'src/composables/docs/useMermaidRenderer.ts'), 'utf8')
    expect(renderer).not.toMatch(/layout\s*:\s*['"]elk['"]/)
  })
})
