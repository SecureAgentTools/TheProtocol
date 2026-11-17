/**
 * V0662, the admin guard, layer 3 (order gwo_c406296cb118596aa7c5c1c2; PLAN_2026-11-13_NO_ADMIN_CALLS_FOR_NON_ADMINS.md):
 * the rule in the source. Every call a view, a component or a composable makes to a route the registry's own rule
 * (adminRoutes.generated.json) gates behind an admin flag must stand behind an admin check, so a member's page never
 * even asks (the client guard of layer 2 is the net; this is the rule):
 *  - the file is an admin page (its route requires the admin role or a flag), or an admin component (components/admin/),
 *  - or the function making the call checks the session's admin rights before it (isAdmin, hasAdminFlag, can(...),
 *    canPlatform/canFederation/..., is_admin),
 *  - or the line above names the guard that keeps a member from reaching it: `// admin-guarded: <why>`.
 * The call sites are found from the generated rule, so a new admin route a member view calls is held to it at once.
 * Red on f569f6a6e: the rule file does not exist, and the plan's suspects call admin routes with no check.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { ADMIN_RULE, adminFlagsFor } from './adminGuard'

const SRC = path.resolve(__dirname, '../..')
const router = fs.readFileSync(path.join(SRC, 'router/index.ts'), 'utf8')

/** the view files whose own route needs the admin role or a flag */
const ADMIN_VIEWS = new Set<string>()
for (const m of router.matchAll(/import\('@\/(views\/[^']+\.vue)'\)/g)) {
  const rest = router.slice(m.index! + m[0].length, m.index! + m[0].length + 1500)   // the record, past a long comment
  const own = rest.split(/\n {6}\}/)[0]
  if (/requiresRole: 'admin'|requiresAdminFlag/.test(own)) ADMIN_VIEWS.add(m[1])
}

const CALL = /\b(?:apiClient|api|client|http|axios)\.(get|post|put|patch|delete)(?:<[^>]*>)?\(\s*([`'"])(\/[^`'"]*)\2/g
const CHECK = /\b(isAdmin|hasAdminFlag\(|\.can\(|can(?:Platform|Federation|Treasury|Enforcement|Support)\b|is_admin|mayCall\()/
const FUNC_START = /^\s*(?:export\s+)?(?:async\s+)?function\s+\w+|^\s*(?:const|let)\s+\w+\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>|^\s*watch\(|^\s*onMounted\(/

function files(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : files(p)
    return /\.(vue|ts)$/.test(e.name) && !/\.test\.ts$/.test(e.name) ? [p] : []
  })
}

function sites() {
  const out: { file: string; line: number; call: string; flags: string[]; guarded: boolean }[] = []
  for (const dir of ['views', 'components', 'composables']) {
    for (const f of files(path.join(SRC, dir))) {
      const rel = path.relative(SRC, f)
      const src = fs.readFileSync(f, 'utf8')
      const lines = src.split('\n')
      for (const m of src.matchAll(CALL)) {
        const p = m[3].replace(/\$\{[^}]*\}/g, 'x')
        const flags = adminFlagsFor(m[1], p, ADMIN_RULE)
        if (!flags || !flags.length) continue
        const line = src.slice(0, m.index).split('\n').length
        let start = line - 1
        while (start > 0 && !FUNC_START.test(lines[start])) start--
        const before = lines.slice(start, line).join('\n')
        const marked = /\/\/ admin-guarded: \S/.test(lines[line - 2] || '')
        const guarded = ADMIN_VIEWS.has(rel) || rel.startsWith('components/admin/') || CHECK.test(before) || marked
        out.push({ file: rel, line, call: `${m[1].toUpperCase()} ${m[3]}`, flags, guarded })
      }
    }
  }
  return out
}

describe('no admin call from a member\'s page without an admin check', () => {
  const all = sites()
  it('the scan sees the population (the plan\'s suspects among it)', () => {
    expect(all.length).toBeGreaterThanOrEqual(30)
    const files = new Set(all.map((s) => s.file))
    for (const f of ['views/Federation.vue', 'views/FederationDiscovery.vue', 'views/ComplianceMonitor.vue',
      'components/federation/PeerDetailDrawer.vue']) expect(files.has(f), f).toBe(true)
  })
  it('every one stands behind an admin check', () => {
    expect(all.filter((s) => !s.guarded).map((s) => `${s.file}:${s.line} ${s.call} (${s.flags.join('+')})`)).toEqual([])
  })
})
