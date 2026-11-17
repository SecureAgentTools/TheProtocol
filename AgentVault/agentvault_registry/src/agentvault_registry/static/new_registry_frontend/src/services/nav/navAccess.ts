// V0662 sidebar (order gwo_0feb166a01e2ff611e154361): ONE rule for who sees a nav entry, read from the route the entry
// opens, the meta the router's guard already enforces (requiresAuth / allowAnonymous, requiresRole 'admin',
// requiresAdminFlag), so the sidebar, its search and the palette cannot disagree with the guard or with each other.
//  - a visitor sees only what a visitor can open; the rest is hidden (one sign-in line stands for it), not locked;
//  - an admin entry shows only to an admin holding its flag (legacy is_admin holds every flag, as
//    composables/usePermissions.hasAdminFlag and security.require_admin_flag say);
//  - a member's entry that needs an acting agent, the mainframe or the euro lane stays LOCKED, and says why;
//  - an entry for a feature this registry does not run is hidden.
import type { AdminAction } from '@/composables/usePermissions'
import { isMainframeOnlyPath } from '@/composables/mainframeOnlyPaths'
import type { NavItem } from './navTable'

export interface RouteRule {
  /** a visitor may open it (requiresAuth false, or allowAnonymous) */
  public: boolean
  /** admin-gated (requiresRole 'admin', or an admin flag named) */
  admin: boolean
  /** the admin flag the route names; null for an admin route that names none (is_admin only) */
  adminFlag: AdminAction | null
}

export interface RouteResolver {
  resolve: (path: string) => { meta?: Record<string, unknown>; matched?: unknown[] }
}

const FLAGS: readonly AdminAction[] = ['platform', 'federation', 'enforcement', 'treasury', 'support']

export function routeRule(router: RouteResolver, path: string): RouteRule {
  let meta: Record<string, unknown> = {}
  try { meta = (router.resolve(path)?.meta || {}) as Record<string, unknown> } catch { /* an unknown path: no rule */ }
  const flag = typeof meta.requiresAdminFlag === 'string' && (FLAGS as readonly string[]).includes(meta.requiresAdminFlag)
    ? meta.requiresAdminFlag as AdminAction : null
  return {
    public: meta.requiresAuth === false || meta.allowAnonymous === true,
    admin: meta.requiresRole === 'admin' || flag !== null,
    adminFlag: flag,
  }
}

export interface NavCtx {
  signedIn: boolean
  /** legacy is_admin: every flag */
  legacyAdmin: boolean
  /** the admin_<area> flags the person holds */
  flags: readonly AdminAction[]
  hasAgent: boolean
  isMainframe: boolean
  fiatEnabled: boolean
  registryCfg: Record<string, unknown>
  flareTier: string | null
}

export type NavState = 'show' | 'lock' | 'hide'

/** The admin flag an entry needs: its route's, or (for a tab inside a member page) the one the entry names. */
export function entryAdmin(item: Pick<NavItem, 'adminFlag'>, rule: RouteRule): { admin: boolean; flag: AdminAction | null } {
  if (item.adminFlag) return { admin: true, flag: item.adminFlag }
  return { admin: rule.admin, flag: rule.adminFlag }
}

function holds(ctx: NavCtx, flag: AdminAction | null): boolean {
  if (ctx.legacyAdmin) return true
  return flag !== null && ctx.flags.includes(flag)
}

export function navItemState(item: NavItem, rule: RouteRule, ctx: NavCtx): NavState {
  if (item.requiresFlare && !ctx.flareTier) return 'hide'
  if (item.requiresRegistryFlag && !ctx.registryCfg[item.requiresRegistryFlag]) return 'hide'
  if (item.hiddenWhenRegistryFlagFalse && ctx.registryCfg[item.hiddenWhenRegistryFlagFalse] === false) return 'hide'
  const adm = entryAdmin(item, rule)
  if (adm.admin && !(ctx.signedIn && holds(ctx, adm.flag))) return 'hide'
  if (!ctx.signedIn && !rule.public) return 'hide'
  // the central set (composables/mainframeOnlyPaths) decides, as the guard does; the entry's own mark is kept with it
  if ((item.mainframeOnly || isMainframeOnlyPath(item.path)) && !ctx.isMainframe) return 'lock'
  if (item.requiresFiat && !ctx.fiatEnabled) return 'lock'
  if (item.requiresAgent && !ctx.hasAgent) return 'lock'
  return 'show'
}

export interface AdminSubgroup { flag: AdminAction; items: NavItem[] }

/** The administration entries, one sub-group per flag in a fixed order (an admin route that names no flag sits with
 *  platform's), only the sub-groups with an entry this person sees. */
export function adminSubgroups(items: readonly NavItem[], rule: (path: string) => RouteRule, ctx: NavCtx): AdminSubgroup[] {
  const by = new Map<AdminAction, NavItem[]>(FLAGS.map((f) => [f, []]))
  for (const it of items) {
    const r = rule(it.path)
    if (navItemState(it, r, ctx) === 'hide') continue
    by.get(entryAdmin(it, r).flag ?? 'platform')!.push(it)
  }
  return FLAGS.filter((f) => by.get(f)!.length).map((f) => ({ flag: f, items: by.get(f)! }))
}
