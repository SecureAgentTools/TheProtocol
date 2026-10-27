/**
 * composables/usePressHold.ts — §POCKETDISC (2026-08-23).
 *
 * Long-press for touch surfaces: fires `onHold` after `ms` of steady contact,
 * cancels on lift or >12px drift (a scroll is not a hold), and SUPPRESSES the
 * click that the same lift would otherwise deliver — without that, a hold
 * would open the context sheet AND the row's tap action on release.
 *
 * A gesture must never be the only door (iOS long-press is temperamental and
 * discoverability is zero) — every consumer also renders a visible button for
 * the same action. This composable is the shortcut, not the entrance.
 */
import { ref } from 'vue'

export function usePressHold(onHold: () => void, ms = 500) {
  const held = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null
  let x0 = 0, y0 = 0

  function clear() { if (timer) { clearTimeout(timer); timer = null } }

  function onPointerdown(e: PointerEvent) {
    held.value = false
    x0 = e.clientX; y0 = e.clientY
    clear()
    timer = setTimeout(() => {
      held.value = true
      try { navigator.vibrate?.(15) } catch { /* no haptics */ }
      onHold()
    }, ms)
  }
  function onPointermove(e: PointerEvent) {
    if (!timer) return
    if (Math.abs(e.clientX - x0) > 12 || Math.abs(e.clientY - y0) > 12) clear()
  }
  function onPointerup() { clear() }
  function onPointercancel() { held.value = false; clear() }

  /** Wrap the row's tap handler: swallowed exactly once after a fired hold. */
  function guardClick(fn: (...a: any[]) => void) {
    return (...a: any[]) => {
      if (held.value) { held.value = false; return }
      fn(...a)
    }
  }

  return { onPointerdown, onPointermove, onPointerup, onPointercancel, guardClick, held }
}
