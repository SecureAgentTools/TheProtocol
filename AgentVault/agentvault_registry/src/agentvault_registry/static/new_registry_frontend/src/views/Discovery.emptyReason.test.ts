import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0663 (his yes seq 3068, "empty lists that say why"), Discovery: a search that finds nothing says WHICH filters narrowed it,
 * through the shared reason line, in place of the one generic hint ("Try a broader term, clear the registry/frame filters").
 * The view is too large to mount here (see Discovery.quantum.test.ts), so this reads the SFC; the sentences themselves are
 * tested in services/emptyReasons.test.ts. BASE: the generic hint is there and no reason line is.
 */
const src = fs.readFileSync(path.resolve(__dirname, 'Discovery.vue'), 'utf8')
const template = src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>'))

describe('Discovery says why a search is empty', () => {
  it('the empty state carries the reason line, from the filters that are on', () => {
    const empty = template.slice(template.indexOf('<!-- Empty State -->'), template.indexOf('<!-- Grid View -->'))
    expect(empty).toMatch(/<EmptyReason\b[^>]*:kind="emptyWhy\.kind"[^>]*:reason="emptyWhy\.reason"/)
    expect(empty).not.toContain('Try a broader term, clear the registry/frame filters')
    expect(empty).toContain('@click="clearAllFilters"')       // the button stays: the reason names the filters, it clears none
  })

  it('emptyWhy is built from every filter clearAllFilters resets', () => {
    const why = src.slice(src.indexOf('const emptyWhy = computed'), src.indexOf('function clearAllFilters()'))
    for (const part of ['searchQuery.value', 'registryFilter.value', 'selectedFrames.value.size', 'filters.tag', 'filters.tags',
      'filters.pricing_model', 'filters.is_certified', 'filters.is_online', 'quantumQuery(quantumFilters.value)']) {
      expect(why, part).toContain(part)
    }
  })

  it('emptyWhy is declared after the refs it reads (a computed above its refs is a TDZ error on first render)', () => {
    const at = src.indexOf('const emptyWhy = computed')
    for (const decl of ['const searchQuery = ref', 'const registryFilter = ref', 'const selectedFrames = ref', 'const quantumFilters = ref']) {
      const d = src.indexOf(decl)
      expect(d, decl).toBeGreaterThan(-1)
      expect(d, `${decl} comes before emptyWhy`).toBeLessThan(at)
    }
  })
})
