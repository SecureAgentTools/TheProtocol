/**
 * composables/usePullToRefresh.ts — §POCKETBRIDGE2 W3.3.
 *
 * ONE pull-to-refresh for every Pocket tab. Batch 1 shipped it on Home only,
 * while PocketEarn's empty state told the user to "pull down" — a promise the
 * other tabs could not keep. Extracted verbatim from PocketHome's proven
 * implementation (top-of-scroll only, 0.5 drag ratio, 64px arm threshold) so
 * every tab behaves identically.
 *
 * Usage:
 *   const ptr = usePullToRefresh(scrollEl, () => reload())
 *   <div ref="scrollEl" @touchstart="ptr.onTouchStart" @touchmove="ptr.onTouchMove" @touchend="ptr.onTouchEnd">
 *     <div class="pk-ptr" :style="{ height: ptr.ptrH.value + 'px', opacity: ptr.ptrH.value ? 1 : 0 }">…</div>
 */
import { ref, type Ref } from 'vue'

export function usePullToRefresh(scrollEl: Ref<HTMLElement | null>, onRefresh: () => void) {
  const ptrH = ref(0)
  const ptrArmed = ref(false)
  let startY = 0
  let pulling = false
  const THRESH = 64

  function onTouchStart(e: TouchEvent) {
    const el = scrollEl.value
    if (!el) return
    // The view wrapper is usually NOT the scroller — .pk-main is (the shell's
    // overflow container). A wrapper's scrollTop is 0 forever, which would arm
    // the pull from anywhere in a long list. Gate on the REAL scroller.
    const sc = (el.closest('.pk-main') as HTMLElement | null) || el
    if (sc.scrollTop <= 0) { startY = e.touches[0].clientY; pulling = true }
  }
  function onTouchMove(e: TouchEvent) {
    if (!pulling) return
    const dy = e.touches[0].clientY - startY
    if (dy > 0) { ptrH.value = Math.min(dy * 0.5, 80); ptrArmed.value = ptrH.value >= THRESH }
    else { ptrH.value = 0 }
  }
  function onTouchEnd() {
    if (pulling && ptrArmed.value) onRefresh()
    pulling = false; ptrH.value = 0; ptrArmed.value = false
  }

  return { ptrH, ptrArmed, onTouchStart, onTouchMove, onTouchEnd }
}
