/**
 * services/api/tier.ts — §TRUSTCHAIN P4.6 (2026-09-12): the endpoint-tier classifier, moved out of
 * client.ts unchanged so it can be unit-tested. It answers ONE question: does this request act AS the
 * selected agent (agent JWT) or as the developer? Every carve-out below was earned by a 401 that
 * tore a session down; keep the comments with the rules.
 */
/**
 * §AGORAWORDS Phase 5 (2026-09-22): the AGORA market answers at /agora/… (the documented name since V0419; every caller
 * uses it since V0421) and at /exchange/… (kept live until a later release drops it). The rules below were written
 * against /exchange/…; this maps a leading /agora/ onto it so both names classify identically, in ONE place: this file
 * and client.ts's acting-venue rule both ask it (§FANOUTFIX: one predicate, never two that agree today).
 */
export function marketPath(url: string): string {
  return url.startsWith('/agora/') ? '/exchange/' + url.slice('/agora/'.length) : url
}

// Helper function to determine if endpoint requires agent token
export function isAgentEndpoint(url?: string, method?: string): boolean {
  if (!url) return false

  // B5 (RBAC plan, 2026-08-14) — IRONKEY self-service rails that act AS the selected
  // agent: spawn (require_agent_permission), attenuate + act-token (get_current_agent).
  // Without these carve-outs the interceptor stamps the DEVELOPER token over any
  // per-call header, the rail 401s, and the 401 handler tears the whole session down —
  // the same class the §FEPARITY R3 /teg/ carve-outs fixed.
  if (url.includes('/agents/spawn')) return true
  if (url.includes('/agents/capabilities/') && url.includes('/attenuate')) return true
  if (url.includes('/agents/act-token')) return true
  // §FESUITE V0595: cross-registry delegation (issue, list what this agent issued, revoke) acts AS the selected agent
  // (require_agent_permission("authz.delegate")); with the developer token stamped over it the rail 401s
  if (url.includes('/agents/delegate-cross-registry')) return true

  // §VCSIGN-2 + §CTRFIX (2026-08-15) — the WHOLE /contracts/ family acts AS the
  // selected agent on every mutation. Route-verified across all three routers
  // (contracts.py, contracts_v2.py, contract_templates.py): every FE-callable
  // POST/PATCH under /api/v1/contracts is agent-tier (legacy mutations =
  // require_agent_permission("contracts.engage"); spine + templates =
  // get_current_agent) and reads are developer/public (get_current_actor_for_read).
  // The two *-federated POSTs are peer-mTLS and never called from the FE. The ONE
  // dev-tier POST in the family is /admin/contracts/{cid}/resolve — excluded by the
  // /admin/ guard. Without this carve-out the interceptor stamps the DEVELOPER token
  // over the per-call agent header, the rail 401s, and the 401 handler tears the
  // whole session down (the B5 + §FEPARITY R3 class) — which is why every
  // Contracts-view action modal (accept/submit/approve/malpractice) was dead.
  if (url.includes('/contracts/') && !url.includes('/admin/')) {
    if (url.includes('/mine')) return true
    if (method === 'post' || method === 'patch') return true
    return false
  }

  // AGORA exchange (2026-06-12) — agent-JWT surfaces: orders, portfolio, IPO buy.
  // Listing creation + dividends are DEVELOPER endpoints; reads are public.
  // NB: apiClient baseURL already carries /api/v1, so urls arrive as /exchange/…
  // 🔴 §COCKPITBOOK — DEVELOPER-TIER ROUTES ARE NEVER AGENT-TIER, AND THIS GUARD EXISTS
  // BECAUSE SUBSTRING CLASSIFICATION SILENTLY MIS-TIERED ONE. `/developers/me/exchange/portfolio`
  // matched `url.includes('/exchange/portfolio')` below, so the browser sent an AGENT token
  // to a developer endpoint and got 401 — while the identical call with a developer token
  // from a script returned 200, which is the shape that makes this look like a server bug.
  // Everything under /developers/ is developer-tier by construction.
  if (url.startsWith('/developers/')) return false
  const mu = marketPath(url)
  if (mu.includes('/exchange/')) {
    if (mu.includes('/exchange/passport/')) return true // §V0064 P2: passport relay = AGENT JWT (home-side)
    if (mu.includes('/exchange/orders')) return true
    if (mu.includes('/exchange/portfolio')) return true
    if (mu.includes('/ipo/buy') || mu.includes('/launch/buy')) return true   // V0419 named the launch purchase
    // §P3.1 governance: casting a share-weighted vote is an AGENT-JWT call (shareholder agent).
    // create-proposal + tally stay DEVELOPER (org admin) → they fall through to return false.
    if (mu.includes('/exchange/proposals/') && mu.includes('/vote')) return true
    return false
  }

  // PHONE FABRIC (§POCKETBRIDGE #PK4) — the agent-side session rails
  // (routers/phone_fabric.py: /phone/sessions/mine + /{sid}/end are
  // get_current_agent). The ADMIN oversight surface stays developer-tier and is
  // excluded by its /admin/ prefix. Without this carve-out the interceptor
  // stamps the DEVELOPER token and the owner rail 401s — the B5/§FEPARITY class.
  if (url.includes('/phone/') && !url.includes('/admin/')) return true

  // THE GUILD (2026-07-07) — agent labor market. Post/bid/award/submit/verify/cancel + /mine act
  // AS the selected agent (agent JWT). Discovery (GET /guild/orders, /guild/orders/{id}) is public;
  // /admin/guild/* is developer/admin. Mirrors the AGORA /exchange/orders agent-JWT pattern.
  if (url.includes('/guild/')) {
    if (url.includes('/admin/guild')) return false
    if (url.includes('/guild/mine') || url.includes('/guild/my-firm') || url.includes('/guild/my-credentials')) return true
    if (method === 'post') return true          // orders, bids, award, submit, verify, cancel
    return false                                 // GET discovery is public
  }

  // Most staking endpoints require agent token, but admin endpoints need developer token
  if (url.includes('/staking/')) {
    // These staking sub-endpoints use developer JWT (get_current_developer), not agent JWT
    if (url.includes('/distribute/manual')) return false
    if (url.includes('/rewards/apy-tiers')) return false
    if (url.includes('/rewards/distributions') && !url.includes('/agents/')) return false
    if (url.includes('/rewards/stats/')) return false
    // Auto-compound PUT needs developer auth for ownership check
    if (url.includes('/auto-compound') && method === 'put') return false
    return true
  }
  
  // Governance endpoints - only specific ones need agent token
  if (url.includes('/governance/')) {
    // POST to /proposals requires agent (create proposal)
    if (method === 'post' && url.endsWith('/proposals')) return true
    // Voting endpoints require agent
    if (url.includes('/vote')) return true
    if (url.includes('/my-vote')) return true  // P3/D2: check-if-voted endpoint
    if (url.includes('/tally')) return true
    if (url.includes('/voting-power')) return true
    // 2026-05-07 — Federation governance LIST + vote + veto require agent JWT
    // (Depends(get_current_agent) on backend router/governance.py:796/821/856).
    // Pre-fix the federation tab in SenateFloor silently 401'd because
    // apiClient was injecting dev JWT here.
    if (url.includes('/governance/federation/proposals')) return true
    // All other governance endpoints are PUBLIC:
    // - GET /governance/proposals (list)
    // - GET /governance/proposals/{id} (details)
    // - GET /governance/stats (statistics)
    // - GET /governance/lock-options (veToken info)
    return false
  }
  
  // TEG endpoints — most require agent auth, but analytics/admin are developer-facing
  if (url.includes('/teg/')) {
    // Dashboard / analytics endpoints use developer token
    if (url.includes('/transactions/analytics')) return false
    if (url.includes('/transactions/history/')) return false
    if (url.includes('/teg/admin')) return false
    // §2026-06-03 — the FX Desk pool snapshot is admin-treasury-gated (developer
    // JWT), but its path doesn't contain `/teg/admin`, so without this carve-out
    // the interceptor injected the (absent) AGENT token → 401 → blank spot/reserves.
    if (url.includes('/teg/fx/pool/admin')) return false
    // §2026-06-03 — op→op FX route ops (status + residue sweep) are admin-treasury
    // (developer JWT), same carve-out rationale as pool/admin. Matches /teg/fx/route/
    // (status, sweep) but NOT /teg/fx/route-hop (federation-authed; never FE-called).
    if (url.includes('/teg/fx/route/')) return false
    // §FEPARITY-R3 (2026-08-04) — the two FX KEEPERS and the parked-route queue are
    // admin-treasury (developer JWT) with paths that match none of the carve-outs
    // above, so the interceptor injected the (absent) AGENT token and the request
    // went out with NO Authorization header at all → 401. Measured on frame-c:
    // /teg/fx/route/status returned 200 while /teg/fx/router-keeper returned 401 on
    // the SAME page, same session — identical backend auth, different client path
    // rule. This is why the keepers were never wired to the FX Desk: the endpoints
    // were unreachable from the app regardless of who was signed in.
    if (url.includes('/teg/fx/router-keeper')) return false
    if (url.includes('/teg/fx/reserve-keeper')) return false
    if (url.includes('/teg/fx/dead-letters')) return false
    if (url.includes('/teg/supply')) return false
    // §pass71.1 (2026-05-25) — /teg/treasury/* is admin-tier (gated by
    // require_admin_flag("admin_treasury") on the backend). Without this
    // carve-out the request interceptor injected the AGENT token instead of
    // the developer JWT, get_current_developer rejected -> 401, the spam-click
    // -> CrowdSec LePresidente/http-generic-401-bf auto-ban. Covers
    // /treasury/mint, /treasury/fund-agent, /treasury/receive, etc.
    if (url.includes('/teg/treasury/')) return false
    // Agent-specific TEG endpoints
    return true
  }
  
  if (url.includes('/agent-builder/generate-template')) return false  // developer auth — bundle download
  if (url.includes('/agent-builder/templates')) return false           // developer auth — template list
  if (url.includes('/agent-builder/')) return true
  // /disputes/* is agent-tier (filing/responding) but /federation/disputes/* is
  // admin-tier (slash settlement orchestration) — must NOT match the broad
  // /disputes/ rule. Build #12 (2026-05-07).
  if (url.includes('/federation/disputes/')) return false
  if (url.includes('/disputes/')) return true

  // Funding endpoints — /funding/request and /funding/my-requests need agent JWT
  // /admin/funding/* uses developer JWT (handled by default path below)
  if (url.includes('/funding/') && !url.includes('/admin/funding/')) return true

  // A2A Payment endpoints (Build #2, 2026-05-07) — most require agent JWT.
  // /verify is the exception (public, no auth) but POST is the only verb so
  // when called from frontend it's still routed; the backend just doesn't
  // check auth, so injecting an agent JWT is harmless.
  if (url.includes('/a2a-payment/')) return true

  return false
}
