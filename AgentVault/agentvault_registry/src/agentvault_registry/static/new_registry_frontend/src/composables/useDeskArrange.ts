/**
 * useDeskArrange — §DASHARRANGE (2026-09-02) — the ONE arrange brain for a board of panes.
 *
 * Extracted VERBATIM from `views/CockpitDesk.vue` so the dashboard's `DeskArea` can offer
 * "arrange your own panes" (his ask) without growing a second copy of the draft, the
 * sidecar sizes, the drag state and the four editing verbs. Two hosts, one brain: the
 * §ORGLEAK / §EXCISION second-copy class is how two surfaces come to disagree.
 *
 * The host supplies the SOURCE layout as a getter (the desk: its active named layout; the
 * dashboard: its one stored layout) and owns persistence. This composable owns everything
 * between "Arrange" and "Save": the draft the board renders while editing, the sizes the
 * user set (row units, a sidecar map — §COCKPITTILES T1), reorder by arrows (the keyboard
 * path, which STAYS) and by drag (mouse only — touch fires no HTML5 drag events), the
 * maximised pane, and the Escape key that restores it.
 *
 * Returned as `reactive(...)` on purpose: the host passes the whole object to `DeskBoard`
 * as a prop, and a ref nested in a PLAIN object is not unwrapped in a template — the desk
 * learned that with the agent door (`door.agentOpen` rendered `[object Object]`). Inside a
 * reactive object every ref and computed reads as its value.
 */
import { ref, computed, reactive, onMounted, onUnmounted } from 'vue'
import { ALL_PANE_IDS, rowsFor, MIN_ROWS, MAX_ROWS, type PaneId, type DeskLayout } from '@/components/cockpit/paneRegistry'

export interface DeskArrangeOptions {
  /** Panes the host is willing to offer in "Add pane". The desk offers every pane and
   *  renders the ones this registry cannot serve as an honest shell; the dashboard offers
   *  only what will actually render. */
  offer?: (id: PaneId) => boolean
}

export function useDeskArrange(source: () => DeskLayout, opts: DeskArrangeOptions = {}) {
  const editing = ref(false)
  const draft = ref<PaneId[]>([])
  const draftSizes = ref<Record<string, number>>({})
  const dragId = ref<PaneId | null>(null)    // the tile being carried
  const dragOver = ref<PaneId | null>(null)  // the tile it is currently over
  const dragArmed = ref<PaneId | null>(null) // ⚠ only the handle arms a drag — see armDrag
  const maxId = ref<PaneId | null>(null)

  /** The draft follows the SOURCE: on edit start, on cancel, and whenever the host says the
   *  source changed under it (the desk switching layouts, a delete). */
  function syncFromSource() {
    const s = source()
    draft.value = [...s.panes]
    draftSizes.value = { ...(s.sizes || {}) }
  }
  function beginEdit() { syncFromSource(); editing.value = true }
  function cancelEdit() { syncFromSource(); editing.value = false }
  /** After a SUCCESSFUL save the source now equals the draft; nothing to discard. */
  function finishEdit() { editing.value = false }

  const shown = computed<PaneId[]>(() => {
    const list = editing.value ? draft.value : source().panes
    // A maximised pane owns the board; leaving the others mounted underneath would keep
    // their polls running behind something nobody can see.
    return maxId.value && list.includes(maxId.value) ? [maxId.value] : list
  })
  const addable = computed<PaneId[]>(() =>
    ALL_PANE_IDS.filter(id => !draft.value.includes(id) && (opts.offer ? opts.offer(id) : true)))

  function addPane(id: PaneId) { if (!draft.value.includes(id)) draft.value = [...draft.value, id] }
  function dropPane(id: PaneId) { draft.value = draft.value.filter(p => p !== id) }
  function movePane(id: PaneId, dir: -1 | 1) {
    const i = draft.value.indexOf(id); const j = i + dir
    if (i < 0 || j < 0 || j >= draft.value.length) return
    const next = [...draft.value]; [next[i], next[j]] = [next[j], next[i]]; draft.value = next
  }

  /** The height this tile is rendered at, in row units: the draft while arranging, the
   *  source otherwise. Both fall back to the pane's declared natural size. */
  function rowsOf(id: PaneId): number {
    return editing.value
      ? rowsFor(id, { id: '', name: '', panes: [], sizes: draftSizes.value })
      : rowsFor(id, source())
  }
  function resizePane(id: PaneId, dir: -1 | 1) {
    const next = Math.min(MAX_ROWS, Math.max(MIN_ROWS, rowsOf(id) + dir))
    draftSizes.value = { ...draftSizes.value, [id]: next }
  }

  function toggleMax(id: PaneId) { maxId.value = maxId.value === id ? null : id }
  // §COCKPITDESK (2026-10-14): an Escape a dialog over the board already used (BaseModal marks
  // it), or one pressed inside a dialog, belongs to that dialog: closing the agent card must
  // not also hand back a maximised pane.
  function onKey(e: KeyboardEvent) {
    if (e.key !== 'Escape' || !maxId.value || e.defaultPrevented) return
    const t = e.target as Element | null
    if (t && typeof t.closest === 'function' && t.closest('[aria-modal="true"]')) return
    maxId.value = null
  }
  onMounted(() => window.addEventListener('keydown', onKey))
  onUnmounted(() => window.removeEventListener('keydown', onKey))

  /* §COCKPITTILES T2 — drag to reorder. Native HTML5 drag and drop, no library. Only the
   * HANDLE arms the drag: with `draggable` on the whole slot the panes underneath stop
   * being usable while arranging. The arrows stay as the keyboard path. */
  function armDrag(id: PaneId) { if (editing.value) dragArmed.value = id }
  function onDragStart(id: PaneId, e: DragEvent) {
    if (!editing.value || dragArmed.value !== id) { e.preventDefault(); return }
    dragId.value = id
    try {
      e.dataTransfer?.setData('text/plain', id)   // Firefox refuses a drag with no payload
      if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
    } catch { /* a browser that refuses the payload still drags within the page */ }
  }
  function onDragOver(id: PaneId, e: DragEvent) {
    if (!dragId.value || id === dragId.value) return
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
    dragOver.value = id
  }
  function onDrop(id: PaneId) {
    const from = dragId.value
    endDrag()
    if (!from || from === id) return
    const i = draft.value.indexOf(from); const j = draft.value.indexOf(id)
    if (i < 0 || j < 0) return
    // MOVE, not swap: dropping A onto D puts A where D was and shifts the rest along,
    // which is what dragging looks like. The arrows keep their swap semantics.
    const next = [...draft.value]
    next.splice(i, 1); next.splice(j, 0, from)
    draft.value = next
  }
  function endDrag() { dragId.value = null; dragOver.value = null; dragArmed.value = null }

  return reactive({
    editing, draft, draftSizes, dragId, dragOver, dragArmed, maxId, shown, addable,
    syncFromSource, beginEdit, cancelEdit, finishEdit,
    addPane, dropPane, movePane, rowsOf, resizePane, toggleMax,
    armDrag, onDragStart, onDragOver, onDrop, endDrag,
  })
}

export type DeskArrange = ReturnType<typeof useDeskArrange>
