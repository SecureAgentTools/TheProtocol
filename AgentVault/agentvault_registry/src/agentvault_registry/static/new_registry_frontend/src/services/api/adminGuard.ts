// V0662, the admin guard (order gwo_c406296cb118596aa7c5c1c2; sessionlogs2026/PLAN_2026-11-13_NO_ADMIN_CALLS_FOR_NON_ADMINS.md,
// layer 2; his suggestion 1: one admin rule, from the server).
//
// CrowdSec bans a person whose console page fires refused calls (http-probing counts every 403 and 404 on a
// non-static path: ten in ten seconds), and a member's page that asks an admin route a few times on each load does
// exactly that. So the console decides first: a call whose route needs an admin flag the session does not hold is not
// sent. Which route needs which flag is the registry's own answer (adminRoutes.generated.json, generated from its
// served routes by scripts/gen_admin_routes.py; tests/test_admin_route_rule_v0662.py keeps the copy equal), read as
// the server reads it: the first route that matches decides, so a literal member route served before an admin route
// with a path parameter is a member's call here too. A call the rule does not know is never judged.
import ruleFile from './adminRoutes.generated.json'
import type { AdminAction } from '@/composables/usePermissions'

type RuleRow = [string, string, string[]]
interface RuleFile { routes: RuleRow[] }
interface Compiled { method: string; re: RegExp; flags: AdminAction[] }

export function compileRule(file: RuleFile): Compiled[] {
  return (file.routes || []).map(([method, path, flags]) => {
    let rx = ''
    let i = 0
    for (const m of path.matchAll(/\{(\w+)(:path)?\}/g)) {
      rx += path.slice(i, m.index).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + (m[2] ? '.+' : '[^/]+')
      i = m.index! + m[0].length
    }
    rx += path.slice(i).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return { method: method.toUpperCase(), re: new RegExp(`^${rx}$`), flags: flags as AdminAction[] }
  })
}

// JSON imports type rows as arrays of unions; the registry's test guarantees the [method, path, flags] shape
export const ADMIN_RULE: Compiled[] = compileRule(ruleFile as unknown as RuleFile)

/** The flags the first route matching this call needs ([] for a member route); null when the rule does not know it. */
export function adminFlagsFor(method: string | undefined, url: string, rule: Compiled[] = ADMIN_RULE): AdminAction[] | null {
  const m = (method || 'get').toUpperCase()
  let p = url.split('#')[0].split('?')[0]
  if (!p.startsWith('/api/v1/')) p = `/api/v1${p.startsWith('/') ? '' : '/'}${p}`
  for (const r of rule) {
    if (r.method === m && r.re.test(p)) return r.flags
  }
  return null
}

/** Legacy is_admin holds every flag (security.require_admin_flag); otherwise every named flag must be held. */
export function mayCall(user: unknown, flags: readonly AdminAction[]): boolean {
  if (!flags.length) return true
  const u = user as Record<string, unknown> | null | undefined
  if (!u) return false
  if (u.is_admin === true) return true
  return flags.every((f) => Boolean(u[`admin_${f}`]))
}

let refused = 0
const warned = new Set<string>()
export function adminRefusedCount(): number { return refused }
export function _resetAdminGuard(): void { refused = 0; warned.clear() }

/** Count a refusal; warn once per route in the console (a developer reading it finds the call site). */
export function noteRefusal(method: string | undefined, url: string, flags: readonly AdminAction[]): void {
  refused++
  const key = `${(method || 'get').toUpperCase()} ${url.split('?')[0]}`
  if (warned.has(key)) return
  warned.add(key)
  console.warn(`[admin guard] not sent: ${key} needs ${flags.map((f) => `admin_${f}`).join(' and ')}, which this session `
    + 'does not hold. The page should not ask (services/api/adminCallSites.test.ts).')
}
