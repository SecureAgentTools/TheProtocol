import { ref, watch, onMounted, onUnmounted, type Ref } from 'vue'

/**
 * §COCKPITTILES T1 — how many rows fit in the tile I am actually in.
 *
 * 🔴 HIS REPORT: *"the agent pipeline/activity thing caps out so i cant fill up to the
 * maximum row tile height."* Exactly right, and it was true of eight panes: the row limits
 * were CONSTANTS (`PaneAgentOps maxPinned: 8`, `PaneAgentsAlive LIST_LIMIT 8`,
 * `PaneHeartbeat ROW_LIMIT 14`, …), so making a tile taller bought nothing but whitespace.
 * A constant cannot know how tall its tile is; a ResizeObserver can.
 *
 * ⚠ FILLING MUST NOT BECOME A SILENT SLICE. This returns how many rows FIT, never how many
 * exist — every caller keeps saying when the server holds more (`+N more`). A list that
 * quietly stops is the §RAT trap wearing a layout costume.
 *
 * ⚠ Row counts become viewport-dependent, so a battery asserting an EXACT count is now
 * asserting the size of the browser window it happened to run in. Assert ranges, or assert
 * the content marker.
 */
export function useFillCount(
  el: Ref<HTMLElement | null>,
  opts: { rowPx: number; min: number; max: number; reservePx?: number },
) {
  const { rowPx, min, max, reservePx = 0 } = opts
  /** Starts at `min`, not 0: a pane must render something before it has been measured. */
  const count = ref(min)
  /** False until a real measurement landed — so a caller can tell "small" from "unknown". */
  const measured = ref(false)
  let ro: ResizeObserver | null = null

  /**
   * ⚠ Measure the SCROLL CONTAINER, never the list itself. A list inside an
   * `overflow:auto` body reports its own CONTENT height, so "how many rows fit" computed
   * from it is circular — it grows to whatever it already rendered. `PaneShell`'s body is
   * the box with the real allocation, so resolve to it and fall back outward.
   */
  function target(node: HTMLElement): HTMLElement {
    return (node.closest('.ckd-pane-body') as HTMLElement | null) || node.parentElement || node
  }

  function measure() {
    const node = el.value
    if (!node) return
    const h = target(node).clientHeight - reservePx
    if (h <= 0) return                       // hidden or not laid out yet: keep the floor
    const fits = Math.floor(h / Math.max(1, rowPx))
    count.value = Math.min(max, Math.max(min, fits))
    measured.value = true
  }

  /** ResizeObserver is in every browser this app supports, but a missing one must degrade
   *  to "the floor still renders", never to a blank pane. */
  function attach(node: HTMLElement | null) {
    ro?.disconnect(); ro = null
    if (!node || typeof ResizeObserver === 'undefined') return
    ro = new ResizeObserver(() => measure())
    ro.observe(target(node))
    measure()
  }

  /**
   * 🔴 WATCH the ref; do not read it once at mount.
   *
   * The first cut attached in `onMounted`, and all six panes sat at their FLOOR forever:
   * the element carrying the ref lives behind the pane's loading / error / empty branches,
   * so at mount `el.value` was still null, nothing was observed, and nothing measured
   * again. MEASURED live — denials reported fit=2 inside a 509px body where six rows fit.
   * A feature that silently degrades to its minimum looks exactly like one working modestly.
   */
  watch(el, node => attach(node), { flush: 'post' })
  onMounted(() => attach(el.value))
  onUnmounted(() => { ro?.disconnect(); ro = null })

  return { count, measured, measure }
}
