/**
 * useAlive: whether the component is still mounted, for the code after an await in onMounted (§FESUITE, 2026-10-03).
 *
 * Vue does not wait for an async onMounted. A page that awaits its first read and then starts a timer starts it after
 * the page is gone if the person left during that await: onUnmounted has already run (and cleared nothing), so the timer
 * runs for as long as the tab stays open, asking the registry from every page the person opens next. The console
 * suite's leave sweep (e2e/suite/sweeps/leaving.spec.ts) holds every API answer for 2 s and leaves after 300 ms to find
 * such pages. Check after each await, before anything that starts a timer, opens a socket or adds a listener:
 *
 *   const alive = useAlive()
 *   onMounted(async () => {
 *     await load()
 *     if (!alive()) return
 *     timer = setInterval(load, 30_000)
 *   })
 *
 * Call it in setup: it registers its own onUnmounted.
 */
import { onUnmounted } from 'vue'

export function useAlive(): () => boolean {
  let alive = true
  onUnmounted(() => { alive = false })
  return () => alive
}
