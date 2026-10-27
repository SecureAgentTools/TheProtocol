/**
 * mainframeOnlyPaths — §pass66 (2026-05-22) — sidebar mainframe-only gate.
 *
 * Single source of truth for which sidebar routes are gated to sovereign-
 * mainframe registries. Cloud-operators see these items in the sidebar
 * (so they know the feature exists) but they're rendered LOCKED with a
 * "Mainframe-only feature" tooltip + redirect to mission-control on click.
 *
 * The previous mechanism was a per-item `mainframeOnly: true` flag scattered
 * across the sidebar items list — it had drifted over time to gate too many
 * things (Agent Roster, Treasury, Health Monitor, etc.) that cloud-op admins
 * legitimately need on their own registry. This set is the curated truth.
 *
 * Adding a new mainframe-only feature: add ONE LINE to this Set. The router
 * guard (`meta.requiresMainframe: true`) is the backend half of the same
 * policy — keep both in sync when a new gate is added.
 *
 * Things in the set should be features that genuinely never make sense on a
 * cloud-op: cross-frame bridge configuration, sub-operator provisioning,
 * federation license issuance, fiat ops (mainframe-only via FIAT_GENESIS_REGISTRY),
 * federation conformance tests, the "request operator slot" / "request frame"
 * marketing pitch pages, etc.
 *
 * Things NOT in the set: anything per-registry — treasury (with mint button
 * separately gated by `canMintAvt`), agent roster, registry card editor,
 * health monitor, reactors, events, audit logs, etc. Cloud-ops have their
 * own + need to manage them.
 */

export const MAINFRAME_ONLY_PATHS: ReadonlySet<string> = new Set([
  // ── Truly mainframe-tier admin surfaces ───────────────────────────────
  '/frame-management',         // sovereign-frame federation + SF-4/5 data planes
  '/operator-management',      // sub-operator onboarding + lifecycle (a cloud-op
                               // CANNOT provision sub-operators — the federation
                               // root of trust is the mainframe)
  '/federation-test',          // federation conformance testing (initiated by mainframe)
  '/admin/compliance',         // CONSUL — federation compliance monitor + kill switch
  '/admin/fiat-ops',           // Stripe/fiat onramp — FIAT_GENESIS_REGISTRY only
  '/admin/settlements',        // cross-registry dispute compensation slash + MINT flows
                               // (settlement compensation mints AVT — mainframe-only)
  // §pass66 follow-up (Commander 2026-05-22): command-center + api-tester
  // can't function on cloud-ops (operator has no shadow registry / sandbox).
  '/command-center',           // operator diagnostics — needs sandbox not present on cloud-ops
  '/api-tester',               // API test harness — needs shadow registry not present on cloud-ops

  // §pass66.4 (Commander 2026-05-23): cross-frame + fleet-wide command surfaces —
  // cloud-ops are leaves of the federation graph, not command roots. These
  // surface mainframe-side authority (EigenTrust fleet topology + bridge flow
  // control) that doesn't apply on a cloud-op.
  '/eigentrust-command',       // fleet-wide EigenTrust trust topology + recompute trigger
  '/admin/bridge',             // cross-frame bridge health — bridges only between mainframes

  // ── Mainframe-side pitch + marketing surfaces ─────────────────────────
  // These exist to onboard NEW operators / frame requesters — they only make
  // sense on the mainframe's frontend; cloud-ops are already ops.
  '/operator',                 // "run your own registry" pitch page
  // §pass66.11 (2026-05-23) — REMOVED '/operator-portal' from the set.
  // OperatorPortal.vue is the cloud-op admin's command center for their OWN
  // stack (self-restart + self-logs + license rotation + registry card edits
  // all live here). Locking it on cloud-ops makes those features unreachable.
  // Frame A's version of the same route adapts via OperatorPortal.vue's
  // internal isMainframe-aware logic — same path, context-sensitive content.
  // (The mainframe-side "manage all operators" view is /operator-management,
  // which is still mainframe-gated above.)
  '/frame-commander',          // "request a sovereign frame" pitch page
  '/frame-kit',                // §HELLOFRAME: the applicant's frame page + kit download (the mainframe that reviews it)

  // §pass66 follow-up (Commander 2026-05-22) — items REMOVED from this set:
  //   - /settlements         (end-user AVT settlements — operators need these)
  //   - /become-a-backer     (wired to mainframe fiat ops, unlocks microtransactions
  //                            via tiered spend — operators benefit too; must be
  //                            available so their backers can purchase from the op's
  //                            portal). The page itself routes the fiat flow to the
  //                            mainframe; nothing operator-side breaks.
] as const)


/**
 * Test if a given route path is gated to mainframes.
 *
 * Usage:
 *   if (isMainframeOnlyPath(item.path) && !isMainframe.value) { ... }
 */
export function isMainframeOnlyPath(path: string): boolean {
  // Strip query string + hash for matching (e.g. /federation?tab=operations
  // shouldn't be treated as a mainframe-only path just because of a tab arg).
  const cleanPath = path.split('?')[0].split('#')[0]
  return MAINFRAME_ONLY_PATHS.has(cleanPath)
}
