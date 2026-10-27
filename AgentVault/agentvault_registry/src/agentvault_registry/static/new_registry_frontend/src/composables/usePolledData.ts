/**
 * usePolledData — visibility-guarded polling composable (2026-05-08).
 *
 * Replaces the 81 hand-rolled `setInterval + visibilityState` blocks
 * scattered across views. 12 of those blocks were missing the visibility
 * guard entirely; this composable makes the correct behaviour the default
 * so future polling views can't accidentally skip it.
 *
 * Usage:
 *   const { data, loading, error, refetch, pause, resume } = usePolledData(
 *     () => apiClient.get('/admin/foo').then(r => r.data),
 *     { interval: 30_000 }
 *   )
 *
 *   // Reactive interval — pass a Ref<number> to support user-adjustable cadence:
 *   const intervalSec = ref(10)
 *   const polled = usePolledData(fetcher, { interval: computed(() => intervalSec.value * 1000) })
 *
 * Behaviour:
 * - Calls `fetcher()` immediately on mount (unless `immediate: false`).
 * - Re-calls every `interval` ms unless paused, hidden tab, or unmounted.
 * - On hidden-tab return: calls fetcher once if last call was > interval
 *   ago, so the user sees fresh data without waiting up to a full interval.
 * - If `interval` is a Ref<number>, the timer is automatically restarted
 *   when the ref changes (mid-session cadence change is transparent).
 * - Auto-cleanup on `onBeforeUnmount`.
 *
 * Options:
 *   interval (required)        — ms between calls; number or Ref<number>
 *   immediate? (default true)  — fire fetcher on mount
 *   pauseWhenHidden? (default true) — skip when document.visibilityState='hidden'
 *   autoStart? (default true)  — start polling on mount; false → caller invokes resume()
 *   onError? (cb)              — invoked when fetcher rejects (no auto-stop)
 *
 * Returned methods:
 *   refetch()  — fire fetcher immediately (e.g. manual ↻ button)
 *   pause()    — stop the interval (data + state preserved)
 *   resume()   — restart the interval
 *
 * Returned state (refs):
 *   data       — latest successful result, or null
 *   loading    — true while a fetch is in flight (any source)
 *   error      — last fetcher rejection, or null after a success
 *   lastFetchAt — Date of last fetcher call (success or fail)
 */

import { ref, isRef, watch, onMounted, onBeforeUnmount, type Ref } from 'vue'
import { useLogger } from './useLogger'

export interface UsePolledDataOptions {
  interval: number | Ref<number>
  immediate?: boolean
  pauseWhenHidden?: boolean
  autoStart?: boolean
  onError?: (err: unknown) => void
}

export interface UsePolledDataReturn<T> {
  data: Ref<T | null>
  loading: Ref<boolean>
  error: Ref<unknown>
  lastFetchAt: Ref<Date | null>
  refetch: () => Promise<void>
  pause: () => void
  resume: () => void
  isPolling: Ref<boolean>
}

export function usePolledData<T>(
  fetcher: () => Promise<T>,
  options: UsePolledDataOptions,
): UsePolledDataReturn<T> {
  const log = useLogger('usePolledData')
  const data: Ref<T | null> = ref(null)
  const loading = ref(false)
  const error: Ref<unknown> = ref(null)
  const lastFetchAt: Ref<Date | null> = ref(null)
  const isPolling = ref(false)

  let intervalHandle: ReturnType<typeof setInterval> | null = null
  let visibilityHandler: (() => void) | null = null

  const opts = {
    immediate: options.immediate ?? true,
    pauseWhenHidden: options.pauseWhenHidden ?? true,
    autoStart: options.autoStart ?? true,
    onError: options.onError,
  }

  const getIntervalMs = (): number =>
    isRef(options.interval) ? options.interval.value : options.interval

  async function runFetcher() {
    if (loading.value) return  // dedupe overlapping calls
    loading.value = true
    try {
      data.value = await fetcher()
      error.value = null
    } catch (err) {
      error.value = err
      log.warn('fetcher rejected', err)
      opts.onError?.(err)
    } finally {
      loading.value = false
      lastFetchAt.value = new Date()
    }
  }

  function tick() {
    if (!isPolling.value) return
    if (opts.pauseWhenHidden && typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    void runFetcher()
  }

  function pause() {
    isPolling.value = false
    if (intervalHandle) {
      clearInterval(intervalHandle)
      intervalHandle = null
    }
  }

  function resume() {
    if (intervalHandle) return  // already polling
    isPolling.value = true
    intervalHandle = setInterval(tick, getIntervalMs())
  }

  async function refetch() {
    await runFetcher()
  }

  // Run-once on visibility-return if last call is stale.
  function onVisibilityChange() {
    if (!opts.pauseWhenHidden) return
    if (document.visibilityState !== 'visible') return
    if (!isPolling.value) return
    if (!lastFetchAt.value || Date.now() - lastFetchAt.value.getTime() > getIntervalMs()) {
      void runFetcher()
    }
  }

  // Reactive interval — restart timer when the ref changes mid-session
  // (e.g. user picks a new cadence from a dropdown).
  if (isRef(options.interval)) {
    watch(options.interval, () => {
      if (intervalHandle) {
        clearInterval(intervalHandle)
        intervalHandle = setInterval(tick, getIntervalMs())
      }
    })
  }

  onMounted(() => {
    if (opts.autoStart) resume()
    if (opts.immediate) void runFetcher()
    if (typeof document !== 'undefined' && opts.pauseWhenHidden) {
      visibilityHandler = onVisibilityChange
      document.addEventListener('visibilitychange', visibilityHandler)
    }
  })

  onBeforeUnmount(() => {
    pause()
    if (visibilityHandler && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', visibilityHandler)
      visibilityHandler = null
    }
  })

  return { data, loading, error, lastFetchAt, refetch, pause, resume, isPolling }
}
