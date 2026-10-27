/**
 * §COCKPITUP U2 (2026-09-01) — ONE map from a desk pane to the record it is about.
 *
 * HIS ASK: *"routes to the whole records/views/actions."*
 *
 * MEASURED BEFORE BUILDING: of 25 panes, exactly ONE navigated anywhere (`PaneChats`).
 * Ten were pure dead ends — book, bookmini, conservation, decisions, instructions, latency,
 * market, receipts, telemetry, work — each rendering a record the app already has a view
 * for. The desk was a place you looked at things and then had to go find them again.
 *
 * 🔴 NO PANE HAND-ROLLS A PATH. A path assembled in a template is a string nothing checks,
 * and a typo'd one is a link that navigates to the SPA's 404 — §DISCREFINE's blank promise
 * with a nicer coat. Every href in this module is built from a route NAME, resolved by the
 * router, so a name that stops existing fails a battery instead of a Commander's click.
 *
 * 🔴 A DOOR THAT CANNOT OPEN IS NOT RENDERED AS A DOOR. `admin-audit-logs` declares
 * `requiresRole: 'admin'` AND `requiresAdminFlag: 'platform'`; linking a non-admin there
 * sends them to a toast and a redirect. So the admin targets ask the SAME predicate the
 * router's own guard asks — `usePermissions().can(flag)` — rather than a second copy of
 * "is this person an admin", which is exactly the shape §ORGLEAK had.
 *
 * ⚠ THE TWO AGENT ROUTES TAKE DIFFERENT PARAM NAMES. `agent-details` is `agent/:agentId`
 * and `agent-cicd` is `agent/:did/ci-cd`. Passing `{ did }` to the first silently produces
 * `/agent/` with an empty segment. They are separate entries here for that reason.
 */
import { useRouter, type RouteLocationRaw } from 'vue-router'
import { usePermissions, type AdminAction } from '@/composables/usePermissions'

/** The record families a desk pane can be about. */
export type RecordKind =
  | 'contract' | 'dispute' | 'guild' | 'consent' | 'exchange'
  | 'agent' | 'agentCicd' | 'staking' | 'myAgents' | 'conservation' | 'senate'
  | 'webhooks' | 'forex' | 'organization' | 'release' | 'settlements'

interface Target {
  /** Route NAME — never a path. */
  name: string
  /** Builds params from the caller's id, when the route takes one. */
  params?: (id: string) => Record<string, string>
  /** Admin sub-flag the route's own meta declares; when set, the link is gated on it. */
  requiresAdminFlag?: AdminAction
}

/**
 * ⚠ Every `name` here is asserted against the live router by the §COCKPITUP battery
 * (`router.resolve({name}).name !== undefined`). Adding a row without a route is caught
 * there, not in production.
 */
const TARGETS: Record<RecordKind, Target> = {
  contract:     { name: 'contracts' },
  dispute:      { name: 'disputes' },
  guild:        { name: 'guild' },
  // The Cockpit CARD (`#/cockpit`) owns the consent record: mandates, the evidence chain,
  // the decision trail. The desk shows the live queue; the card holds the history.
  consent:      { name: 'cockpit' },
  exchange:     { name: 'exchange' },
  agent:        { name: 'agent-details', params: (id) => ({ agentId: id }) },
  agentCicd:    { name: 'agent-cicd',    params: (id) => ({ did: id }) },
  staking:      { name: 'staking' },
  myAgents:     { name: 'my-agents' },
  senate:       { name: 'senate' },
  conservation: { name: 'admin-audit-logs', requiresAdminFlag: 'platform' },
  webhooks:     { name: 'webhooks' },
  forex:        { name: 'forex' },
  organization: { name: 'organization' },
  release:      { name: 'admin-release-channel', requiresAdminFlag: 'platform' },
  settlements:  { name: 'settlements', requiresAdminFlag: 'enforcement' },
}

/** The route object for a record, or null when this viewer must not be offered it. */
export function recordTarget(kind: RecordKind, id?: string | null): RouteLocationRaw | null {
  const t = TARGETS[kind]
  if (!t) return null
  if (t.requiresAdminFlag && !usePermissions().can(t.requiresAdminFlag)) return null
  if (t.params) {
    const key = String(id || '')
    // A parameterised route with no id would resolve to a path with an empty segment —
    // a link that goes to the 404. No id, no door.
    if (!key) return null
    return { name: t.name, params: t.params(key) }
  }
  return { name: t.name }
}

/**
 * The `href` for a record, or '' when there is no door for this viewer.
 * Returns a real resolved href so the link is a real `<a>` — middle-click and
 * "open in new tab" work, which they do not for a click handler on a span.
 */
export function useRecordDoor() {
  const router = useRouter()
  function recordHref(kind: RecordKind, id?: string | null): string {
    const to = recordTarget(kind, id)
    if (!to) return ''
    try {
      const r = router.resolve(to)
      // ⚠ `resolve` on an unknown NAME throws; on an unknown PATH it returns a match with
      // `name === undefined`. Both are "no door" and both are caught here rather than
      // rendering an anchor to nowhere.
      return r.name ? r.href : ''
    } catch { return '' }
  }
  return { recordHref, recordTarget }
}
