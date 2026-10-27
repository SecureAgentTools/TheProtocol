// Guided Tour — Pinia store. Owns tour lifecycle, step navigation, route orchestration,
// the active-agent gate, and anchor-availability waiting. The overlay component reads
// `currentStep` + state flags and handles all DOM measurement/positioning itself.
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'
import { getTour } from './tourRegistry'
import type { GuidedTour, TourStep } from './tour.types'

const RESUME_KEY = 'theprotocol_guided_tour_resume'

function sleep(ms: number) { return new Promise((r) => setTimeout(r, ms)) }

/**
 * Resolve one anchor token to a selector. A bare token is a `data-tour` name;
 * anything starting with [ . or # is used as a raw CSS selector.
 */
function anchorSelector(tok: string): string {
  const t = tok.trim()
  return t.startsWith('[') || t.startsWith('.') || t.startsWith('#') ? t : `[data-tour="${t}"]`
}

/**
 * First currently-visible element among comma-separated anchor alternatives, or null.
 *
 * §TOURFIX (2026-08-14): exported because EVERY consumer of a step's `anchor` must
 * resolve it through this — the overlay's measure() used to build a raw
 * `[data-tour="a,b"]` selector, which matches nothing, so all 46 chained-anchor
 * steps (10 of them in the organizations tour) rendered full-dim with no spotlight
 * no matter how healthy the page was.
 */
export function findAnchor(sel: string): HTMLElement | null {
  for (const tok of sel.split(',')) {
    if (!tok.trim()) continue
    const el = document.querySelector(anchorSelector(tok)) as HTMLElement | null
    // offsetParent is null for display:none AND for position:fixed elements, so fall
    // back to a box check — a fixed toolbar/bottom-bar anchor is perfectly spotlightable.
    if (el && (el.offsetParent !== null || el.getBoundingClientRect().width > 0)) return el
  }
  return null
}

/**
 * Poll for an anchor. `sel` may list alternatives separated by commas, tried in order —
 * lets a step point at its ideal element but still land on a sensible one when the ideal
 * is data-dependent (e.g. mission-control's "Create Agent" CTA only exists for a user
 * with zero agents).
 */
async function waitForAnchor(sel: string, budgetMs = 5000): Promise<HTMLElement | null> {
  const deadline = Date.now() + budgetMs
  while (Date.now() < deadline) {
    const el = findAnchor(sel)
    if (el) return el
    await sleep(120)
  }
  return null
}

/**
 * Would the router's `requiresAgent` guard block/redirect a push to `path`?
 *
 * Mirrors router/index.ts: the guard fires when the TARGET route carries
 * `meta.requiresAgent` and the user is a developer/admin without both an
 * `activeAgent` and an `agentToken`. Kept deliberately conservative — if the route
 * cannot be resolved we return false and let the real guard decide, because a tour
 * refusing to navigate is worse than one that tries and reports honestly.
 */
function _routeNeedsAgentButNoneActive(path: string): boolean {
  try {
    const resolved = router.resolve(path)
    const needs = resolved.matched.some((r) => r.meta?.requiresAgent)
    if (!needs) return false
    const auth = useAuthStore()
    if (!(auth.isDeveloper || auth.isAdmin)) return false
    return !(auth.activeAgent && auth.agentToken)
  } catch {
    return false
  }
}

export const useGuidedTourStore = defineStore('guidedTour', () => {
  const tour = ref<GuidedTour | null>(null)
  const stepIndex = ref(0)
  const isActive = ref(false)
  /** True while routing / waiting for an anchor to appear (overlay shows a soft loader). */
  const isPreparing = ref(false)
  /** Set when a requireAgent step can't proceed because no agent is active. */
  const needsAgent = ref(false)
  /** Set when an anchored step's element never appeared (overlay falls back to a centered card). */
  const anchorMissing = ref(false)
  /** Bumped whenever the step is (re)entered — lets the overlay re-measure. */
  const tick = ref(0)

  const currentStep = computed<TourStep | null>(() =>
    tour.value && isActive.value ? tour.value.steps[stepIndex.value] ?? null : null,
  )
  const totalSteps = computed(() => tour.value?.steps.length ?? 0)
  const progressPct = computed(() =>
    totalSteps.value ? Math.round(((stepIndex.value + 1) / totalSteps.value) * 100) : 0,
  )
  const isFirst = computed(() => stepIndex.value === 0)
  const isLast = computed(() => stepIndex.value === totalSteps.value - 1)

  // Monotonic guard: if the user advances (Next/Back/Skip) while a step is still routing or
  // waiting for its anchor, a newer _enterStep supersedes this one. The stale call must NOT
  // mutate shared state afterwards (else a slow, never-found anchor would stamp `anchorMissing`
  // onto the step the user already moved to — e.g. a centered outro showing "isn't on screen").
  let _enterSeq = 0
  /* §DASHARRANGE — the direction of travel, so an OPTIONAL step whose anchor is absent is
   * skipped the way the person was going (Next → the step after it, Back → the one before). */
  let _dir: 1 | -1 = 1
  function _skipOptional(i: number): boolean {
    if (!tour.value) return false
    const j = i + _dir
    if (j < 0 || j >= tour.value.steps.length) return false
    isPreparing.value = false
    void _enterStep(j)
    return true
  }
  async function _enterStep(i: number) {
    if (!tour.value) return
    const step = tour.value.steps[i]
    if (!step) return
    const seq = ++_enterSeq
    stepIndex.value = i
    needsAgent.value = false
    anchorMissing.value = false
    isPreparing.value = true

    // 1. Route if needed.
    if (step.route && router.currentRoute.value.path !== step.route) {
      // §OPGUIDE-7 — ASK THE ROUTE, NOT THE STEP.
      //
      // Five tours (staking, disputes, attestations, governance, token-economics) point at
      // routes carrying `meta.requiresAgent` but never set `requireAgent` on the step. The
      // router guard therefore either aborted the navigation (`next(false)` — agents exist
      // but none selected) or redirected to /onboarding (no usable agent). Nothing here
      // noticed: the old code only checked when the STEP declared requireAgent, so the tour
      // carried on narrating the staking page while sitting on mission-control or, worse,
      // on /onboarding — which is OUTSIDE DashboardLayout, where <GuidedTour/> is mounted,
      // so the overlay unmounted and the tour simply died mid-way. That is the reported
      // "tutorials don't always change page correctly".
      //
      // Derive the requirement from the route's own meta and gate BEFORE navigating, so we
      // never hand the user a redirect that kills the tour. The needs-agent coachmark
      // already exists and has an "I picked one →" button.
      if (_routeNeedsAgentButNoneActive(step.route)) {
        needsAgent.value = true
        isPreparing.value = false
        tick.value++
        _persist()
        return
      }

      try { await router.push(step.route) } catch { /* guard may still block */ }
      await sleep(320)  // settle for the new route's lazy chunk + first paint
      if (seq !== _enterSeq) return  // superseded by a newer step → bail without touching state

      // Verify we actually landed. `router.push` RESOLVES (it does not throw) on an
      // aborted or redirected navigation, so the only trustworthy signal is the current
      // route. Never continue as though we arrived.
      if (router.currentRoute.value.path !== step.route) {
        if (_routeNeedsAgentButNoneActive(step.route) || step.requireAgent) {
          needsAgent.value = true
        } else {
          // Blocked for some other reason (permission, redirect). Show the explanation
          // centred rather than spotlighting an element on a page we never reached.
          if (step.optional && _skipOptional(i)) return
          anchorMissing.value = true
        }
        isPreparing.value = false
        tick.value++
        _persist()
        return
      }
    }

    // 2. Wait for the anchor (if any) to materialise.
    if (step.anchor || step.waitFor) {
      const sel = step.waitFor || step.anchor!
      // §OPGUIDE-7 — two-phase wait. Previously this blocked for a flat 12s on
      // route-changing steps, so ANY anchor that never appears (a collapsed nav group,
      // a data-dependent CTA) parked the user on a loader for twelve seconds before
      // admitting defeat. Now: block only briefly, then show the step's explanation
      // immediately and keep looking in the background — if the element turns up late
      // the spotlight snaps onto it. Nothing is ever worse than before; the slow cases
      // are just no longer silent dead air.
      const quick = step.route ? 2500 : 1200
      // §TOURFIX (2026-08-14): the background watcher must outlive slow-hydrating
      // views. The org dashboard needs ~9s to paint its tab bar on a loaded frame;
      // the old 5s total meant the free late-watcher below expired before the
      // anchors could exist, stranding the step centered. The BLOCKING phase stays
      // short — only the background phase (seq-guarded, 120ms polls) got patient.
      const total = step.waitMs ?? 25000
      const el = await waitForAnchor(sel, quick)
      if (seq !== _enterSeq) return  // superseded mid-wait → don't stamp stale anchorMissing
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        await sleep(220) // let scroll settle before measuring
        if (seq !== _enterSeq) return
      } else {
        if (step.optional && _skipOptional(i)) return
        anchorMissing.value = true
        void (async () => {
          const late = await waitForAnchor(sel, total - quick)
          if (seq !== _enterSeq || !late) return   // user moved on, or it truly isn't there
          late.scrollIntoView({ behavior: 'smooth', block: 'center' })
          await sleep(220)
          if (seq !== _enterSeq) return
          anchorMissing.value = false              // re-anchor: spotlight it after all
          tick.value++
        })()
      }
    }

    if (seq !== _enterSeq) return
    isPreparing.value = false
    tick.value++
    _persist()
  }

  function _persist() {
    try {
      if (isActive.value && tour.value)
        localStorage.setItem(RESUME_KEY, JSON.stringify({ id: tour.value.id, step: stepIndex.value }))
      else localStorage.removeItem(RESUME_KEY)
    } catch { /* ignore */ }
  }

  /** Access-control LOCK guard. Mirrors TutorialHub.isLocked so the `?tour=`
   *  deep link and the globally-mounted contextual pill can't bypass the UI
   *  lock. `is_admin` is a superuser bypass; `requireFlag` is an RBAC flag
   *  string (e.g. 'admin_enforcement'). Server enforces independently — UX. */
  function _isLockedForUser(t: GuidedTour): boolean {
    const u = useAuthStore().user as unknown as Record<string, unknown> | null
    const isAdmin = u?.is_admin === true
    if (t.requireAdmin && !isAdmin) return true
    if (t.requireFlag && !isAdmin) {
      const bare = t.requireFlag.replace(/^admin_/, '')
      if (!u?.[`admin_${bare}`]) return true
    }
    return false
  }

  async function start(tourId: string, fromStep = 0) {
    const t = getTour(tourId)
    if (!t) return
    // §TOURGAP (2026-08-05) — a refusal must be a decision about the USER, never about
    // TIMING. The auth profile hydrates asynchronously and `user` is null until it lands,
    // which _isLockedForUser() reads as "not an admin" and refuses. The `?tour=` deep link
    // evaluates with immediate:true on mount, so opening an admin-locked tour right after
    // login silently refused users who were fully entitled to it.
    //
    // Holding a token but no profile yet means "not known yet", not "not allowed". Resolve
    // it before judging. Fixed in start() rather than in the deep-link watcher so every
    // caller benefits: deep link, contextual pill, and the hub cards.
    if (t.requireAdmin || t.requireFlag) {
      const auth = useAuthStore()
      if (!auth.user && auth.isAuthenticated) {
        await auth.refreshProfile().catch(() => { /* fall through to the guard below */ })
      }
    }
    // HARD GUARD: refuse to start a tour this user can't access (closes the
    // `?tour=` deep-link + contextual-pill bypass — the overlay is global).
    if (_isLockedForUser(t)) {
      console.warn(`[guidedTour] "${tourId}" is locked for the current user — not starting.`)
      return
    }
    tour.value = t
    isActive.value = true
    await _enterStep(Math.min(Math.max(fromStep, 0), t.steps.length - 1))
  }

  async function next() {
    if (!tour.value) return
    if (stepIndex.value >= totalSteps.value - 1) { end(); return }
    _dir = 1
    await _enterStep(stepIndex.value + 1)
  }
  async function back() {
    if (stepIndex.value <= 0) return
    _dir = -1
    await _enterStep(stepIndex.value - 1)
  }
  async function goToStep(i: number) { await _enterStep(i) }

  /**
   * Re-enter the CURRENT step.
   *
   * §OPGUIDE-8 — this is what the needs-agent coachmark's "I picked one" button must do.
   * It used to call `next()`, which advanced past the step whose route had never been
   * applied: the user picked an agent and then walked the remainder of the tour still
   * sitting on the previous page, so every later anchor was missing. Retrying re-runs the
   * gate, and now that an agent is active the navigation actually happens.
   */
  async function retryStep() { await _enterStep(stepIndex.value) }

  function end() {
    isActive.value = false
    tour.value = null
    stepIndex.value = 0
    needsAgent.value = false
    anchorMissing.value = false
    isPreparing.value = false
    _persist()
  }

  /** Click the currently-anchored element (for cta.do === 'click-anchor'), then advance. */
  async function clickAnchorThenNext() {
    const step = currentStep.value
    if (step?.anchor) {
      // findAnchor, not a raw querySelector — a comma-chained anchor is a list of
      // alternatives, and the raw string matches no element at all (§TOURFIX).
      const el = findAnchor(step.anchor)
      el?.click()
      await sleep(250)
    }
    await next()
  }

  /** Re-measure trigger for the overlay (resize/scroll). */
  function remeasure() { tick.value++ }

  function hasResumable(): { id: string; step: number } | null {
    try { return JSON.parse(localStorage.getItem(RESUME_KEY) || 'null') } catch { return null }
  }

  return {
    tour, stepIndex, isActive, isPreparing, needsAgent, anchorMissing, tick,
    currentStep, totalSteps, progressPct, isFirst, isLast,
    start, next, back, goToStep, retryStep, end, clickAnchorThenNext, remeasure, hasResumable,
  }
})
