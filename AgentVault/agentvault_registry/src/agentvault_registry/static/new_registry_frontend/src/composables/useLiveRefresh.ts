/**
 * useLiveRefresh — the "Refreshed 8s ago · Next 52s" clock, in one place.
 *
 * ── WHY THIS EXISTS (§FEDCLOCK, 2026-09-09) ────────────────────────────────────────────────
 * His report: *"we had a timer for it /compliance also from /federation."* Both halves were true
 * and neither was a regression: `Federation.vue` has carried this readout inline since the 2026-05
 * T1 audit, and `ComplianceMonitor.vue` never had one — measured, `git log -S "setInterval"` on
 * that path is empty. Its numbers could be arbitrarily old with nothing on screen to say so.
 *
 * Rather than write a second copy, the working one is lifted here VERBATIM: the same thresholds,
 * the same strings ("just now" / "Ns ago" / "Nm ago" / "Nh ago"), the same 60 s default. A reader
 * comparing the two pages should not be able to tell which one was moved.
 *
 * Four hand-rolled copies of this logic exist today (Federation.vue, Discovery.vue,
 * DirectoryStrip.vue, DirectoryLane.vue). This replaces two of them; the discovery pair is left
 * alone deliberately, as scope, and is the obvious next adopter.
 *
 * ── WHAT IS NEW HERE, AND WHY ──────────────────────────────────────────────────────────────
 * `pauseWhenHidden`. Federation.vue's inline version has no `visibilitychange` handling at all, so
 * a background tab kept polling a topology endpoint every 60 s for as long as the tab lived. The
 * house composable `usePolledData` already treats that as the default, and its own docstring notes
 * that 12 of the 81 hand-rolled blocks it replaced were missing the guard. This one keeps the 1 Hz
 * display tick running (so the label is correct the instant you look back) and only suspends the
 * FETCH — a paused clock that lies about its own age would be worse than the polling it saved.
 *
 * ⚠ `markFetched()` is called by the CALLER, after a successful load, not by this composable. The
 * clock must measure when data actually arrived; a composable that stamped the time it *asked*
 * would read "just now" over a failed refresh, which is the exact shape of a probe that cannot
 * distinguish its own failure from success.
 */
import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'

export interface LiveRefreshOptions {
  /** Poll period in ms. 60_000 matches Federation.vue's long-standing cycle. */
  intervalMs?: number
  /** Suspend the FETCH while the tab is hidden (the display tick keeps running). */
  pauseWhenHidden?: boolean
  /** Return true to skip one tick — used by Federation.vue's sticky-hover gate. */
  shouldSkip?: () => boolean
}

export interface LiveRefresh {
  /** When the last SUCCESSFUL load landed. Null until the first `markFetched()`. */
  lastFetchedAt: Ref<Date | null>
  /** 1 Hz clock, exposed so a caller can drive other relative-time labels off one timer. */
  nowTick: Ref<number>
  /** "just now" | "12s ago" | "3m ago" | "2h ago" — empty string before the first load. */
  lastRefreshedLabel: Ref<string>
  /** Seconds until the next poll; 0 before the first load. */
  nextRefreshInSeconds: Ref<number>
  /** True while the tab is hidden and polling is suspended. */
  paused: Ref<boolean>
  /** Call after a successful load. */
  markFetched: () => void
}

export function useLiveRefresh(
  load: () => void | Promise<void>,
  options: LiveRefreshOptions = {},
): LiveRefresh {
  const intervalMs = options.intervalMs ?? 60_000
  const pauseWhenHidden = options.pauseWhenHidden ?? true

  const lastFetchedAt = ref<Date | null>(null)
  const nowTick = ref(Date.now())
  const paused = ref(false)

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let tickTimer: ReturnType<typeof setInterval> | null = null

  const markFetched = () => { lastFetchedAt.value = new Date() }

  // lifted verbatim from Federation.vue's T1 helpers so both pages read identically
  const lastRefreshedLabel = computed(() => {
    if (!lastFetchedAt.value) return ''
    const secs = Math.max(0, Math.floor((nowTick.value - lastFetchedAt.value.getTime()) / 1000))
    if (secs < 5) return 'just now'
    if (secs < 60) return `${secs}s ago`
    const mins = Math.floor(secs / 60)
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    return `${hrs}h ago`
  })

  const nextRefreshInSeconds = computed(() => {
    if (!lastFetchedAt.value) return 0
    const elapsed = Math.floor((nowTick.value - lastFetchedAt.value.getTime()) / 1000)
    return Math.max(0, Math.floor(intervalMs / 1000) - elapsed)
  })

  const onVisibility = () => {
    if (!pauseWhenHidden) return
    const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden'
    paused.value = hidden
    // Coming back from a long hide: the countdown has already run to 0 and the data on screen is
    // as old as the label says. Refresh once immediately rather than making the reader wait out a
    // fresh interval in front of a number they can see is stale.
    if (!hidden && nextRefreshInSeconds.value === 0 && lastFetchedAt.value) void load()
  }

  onMounted(() => {
    pollTimer = setInterval(() => {
      if (paused.value) return
      if (options.shouldSkip?.()) return
      void load()
    }, intervalMs)
    tickTimer = setInterval(() => { nowTick.value = Date.now() }, 1_000)
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibility)
      onVisibility()
    }
  })

  onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
    if (tickTimer) clearInterval(tickTimer)
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibility)
    }
  })

  return { lastFetchedAt, nowTick, lastRefreshedLabel, nextRefreshInSeconds, paused, markFetched }
}
