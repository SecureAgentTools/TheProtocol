import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/** V0664 C4 (order gwo_85a6015257385f6bb010682e): the migration console's routes. The report page and the builder are fixed paths that must come
 *  BEFORE `migrate/:id`, or the id route takes "report" and "new" for template ids; the report page is public and asks nothing of the registry. */
const src = readFileSync(resolve(__dirname, 'index.ts'), 'utf8')
const block = (name: string) => { const i = src.indexOf(`name: '${name}'`); return src.slice(src.lastIndexOf('{', i), src.indexOf('}\n', i)) }

describe('the migration console routes', () => {
  it('the fixed paths come before the id route', () => {
    const id = src.indexOf("path: 'migrate/:id'")
    expect(id).toBeGreaterThan(-1)
    for (const p of ["path: 'migrate/report'", "path: 'migrate/new'"]) {
      const i = src.indexOf(p)
      expect(i, p).toBeGreaterThan(-1)
      expect(i, `${p} before migrate/:id`).toBeLessThan(id)
    }
  })
  it('the report page is public and lazy', () => {
    const b = block('migrate-report')
    expect(b).toContain("path: 'migrate/report'")
    expect(b).toContain("import('@/views/MigrateReportView.vue')")
    expect(b).toMatch(/requiresAuth: false/)
    expect(b).toMatch(/allowAnonymous: true/)
  })
})
