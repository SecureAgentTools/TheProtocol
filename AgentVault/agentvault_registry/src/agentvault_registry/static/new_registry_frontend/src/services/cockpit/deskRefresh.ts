/**
 * §COCKPITDESK (2026-10-14) — "Refresh" on a desk host: one tick every pane's frame listens to.
 *
 * Every pane already hands its frame (`PaneShell`) its own read as `reload`, for Try again and the chip, so a host that
 * wants the whole board read again has nothing to know about any pane: it bumps this tick, and each frame that holds a
 * `reload` and is not already reading calls it. A pane with no `reload` (a LIVE pane, a pane with nothing to ask for) is
 * untouched. No timer, no listener, nothing a page keeps after it is left: a ref and a counter.
 */
import { ref } from 'vue'

export const deskRefreshTick = ref(0)

/** Ask every pane on the board to read again now. */
export function refreshDesk(): void {
  deskRefreshTick.value += 1
}
