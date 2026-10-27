// Guided Tour — type definitions.
// A "guided tour" walks a new dev through the REAL frontend UI: it spotlights and
// explains actual elements (anchored via `data-tour="…"` attributes), steps along the
// real click-path, and is educational/safe (it guides + explains; it does not auto-fire
// destructive prod mutations). Complements the API-runner tracks (which teach the API).

export type TourPlacement = 'top' | 'bottom' | 'left' | 'right' | 'auto' | 'center'

export interface TourCta {
  /** Button label, e.g. "Open the API tutorial". */
  label: string
  /** next = advance; click-anchor = programmatically click the anchored element then advance;
   *  open-runner = jump to the matching API-runner track. */
  do: 'next' | 'click-anchor' | 'open-runner' | 'create-wallet'
  /** §WALLETAGENT — `create-wallet`: opens the quick-create modal (wallet mode) when no agent is
   *  active; advances when one is. The tour resumes by itself once the modal creates the agent. */
  runnerTrackId?: string
}

export interface TourLiveAction {
  /** A safe, read-only sandbox call surfaced as a "Try it live" button. Fired through the
   *  tutorial proxy (`/admin/tutorial/execute`), which ALWAYS targets the sandbox — so it
   *  never touches prod. Keep these GET/read-only; the response is shown inline. */
  method: 'GET' | 'POST'
  /** Path under /api/v1, e.g. '/agora/index'. */
  path: string
  body?: Record<string, unknown> | null
  /** Sandbox-side auth tier (default 'none' — most live demos hit public reads). */
  authType?: 'none' | 'developer'
  /** Button label (default "Try it live ▸"). */
  label?: string
}

export interface TourStep {
  id: string
  title: string
  /** Markdown-ish body (supports **bold**, `code`, and paragraph breaks). */
  body: string
  /** `data-tour` value to spotlight. Absent => a centered card (intros/outros/section breaks). */
  anchor?: string
  /** Hash route to navigate to before showing this step (e.g. '/exchange'). */
  route?: string
  /** Where to float the coachmark relative to the anchor. */
  placement?: TourPlacement
  /** After a route change, wait for this `data-tour` to appear before showing (defaults to `anchor`). */
  waitFor?: string
  /** Max ms to keep hunting the anchor in the BACKGROUND before giving up (default
   *  12000 on route steps, 5000 otherwise). Raise it for views that are genuinely slow to
   *  become ready — Cesium, or a deep federation crawl — so the spotlight still lands
   *  once the view settles. The explanation card is shown immediately either way. */
  waitMs?: number
  /** Step needs an active agent (Exchange/Forex Desks). If none is selected the tour pauses with a hint. */
  requireAgent?: boolean
  /** §DASHARRANGE (2026-09-02) — an OPTIONAL step is skipped (in the direction of travel)
   *  when its anchor is not on the page, instead of degrading to a centred card that
   *  describes furniture the person cannot see. For steps anchored on flag-gated or
   *  per-registry elements (the dashboard's desk area exists only where the cockpit desk
   *  is enabled). A step without this flag keeps today's honest fallback. */
  optional?: boolean
  /** Optional extra call-to-action button beside Back/Next. */
  cta?: TourCta
  /** Optional "Try it live" — fires a safe read-only sandbox call and shows the response inline. */
  live?: TourLiveAction
}

export interface GuidedTour {
  id: string
  title: string
  subtitle: string
  /** Icon name from components/Icon.vue registry (mdi:…). */
  icon: string
  /** Accent colour (css var or hex) for the card + spotlight ring. */
  accent: string
  estMinutes: number
  /** Access-control LOCK (optional). When set, the tour is shown LOCKED on the
   *  TutorialHub and refuses to start for users who don't qualify. `is_admin`
   *  superusers bypass both. Leave BOTH unset for open tours (the default). */
  requireAdmin?: boolean
  /** RBAC flag the user must hold to launch, e.g. 'admin_enforcement'. */
  requireFlag?: string
  /** §BAFIN (2026-10-01) — the registry-config switch the tour's surface lives behind. The hub does not OFFER a
   *  tour whose surface this registry switched off (a lock would read as "ask for access"; this is "not here"). */
  requiresRegistryFlag?: 'fiat_onramp_enabled' | 'staking_enabled' | 'cockpit_desk_enabled'
  steps: TourStep[]
}
