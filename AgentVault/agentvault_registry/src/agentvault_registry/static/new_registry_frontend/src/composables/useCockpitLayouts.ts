/**
 * §COCKPIT P1 (2026-08-31) — saved desk layouts, over the EXISTING prefs rail.
 *
 * Backend delta for this whole feature is ONE literal on `_PREF_KEYS`
 * (`cockpit.layouts`). No table, no route: a layout is a preference — it decides
 * what a human SEES and never what anything may DO, so it belongs in the same
 * place the watchlist lives, under the same 16 KB cap and the same whole-value
 * replace semantics.
 *
 * ⚠ The prefs PUT replaces the value wholesale, so there is no in-place JSONB
 * mutation here and the `flag_modified` trap does not apply. The battery still
 * asserts after a RE-READ rather than after the write, because a write that
 * returns 200 and stores nothing is a class this project has met more than once.
 */
import { ref, computed } from 'vue'
import { apiClient } from '@/services/api/client'
import { STARTER_LAYOUTS, isKnownPane, MIN_ROWS, MAX_ROWS, type DeskLayout, type PaneId } from '@/components/cockpit/paneRegistry'

const PREF_KEY = 'cockpit.layouts'
const MAX_LAYOUTS = 12

interface StoredPrefs {
  layouts?: DeskLayout[]
  activeId?: string
}

const saved = ref<DeskLayout[]>([])
const activeId = ref<string>('triage')
const loading = ref(false)
const error = ref<string>('')
const loadedOnce = ref(false)
// 🔴 A LATE READ MUST NOT OVERWRITE A CHOICE THE HUMAN ALREADY MADE.
// `load()` used to apply the stored `activeId` unconditionally. The desk renders
// the default layout immediately and fetches the saved one after mount, so a user
// who picked a layout inside that window was silently bounced back to the stored
// one — no gesture, no message, the selection just undone. Caught by a battery leg
// that clicked a layout and then found the desk showing a different one.
const userChose = ref(false)

/** Drop unknown pane ids on READ, not on write: a layout saved by a newer build
 *  must not break an older one, and an id we cannot render is not a pane. */
function sanitize(l: any): DeskLayout | null {
  if (!l || typeof l.id !== 'string' || !Array.isArray(l.panes)) return null
  const panes = l.panes.filter((p: any) => typeof p === 'string' && isKnownPane(p)) as PaneId[]
  // §COCKPITTILES T1 — per-pane heights. ABSENT on every layout saved before today, which
  // is the whole point of a sidecar map: an old layout reads back unchanged, and a size for
  // a pane this build cannot render is dropped exactly like the pane id itself.
  const sizes: Record<string, number> = {}
  if (l.sizes && typeof l.sizes === 'object') {
    for (const [k, v] of Object.entries(l.sizes as Record<string, unknown>)) {
      const n = Number(v)
      if (isKnownPane(k) && Number.isFinite(n) && n >= MIN_ROWS && n <= MAX_ROWS) sizes[k] = Math.round(n)
    }
  }
  return { id: l.id, name: String(l.name || l.id).slice(0, 40), panes, sizes }
}

export function useCockpitLayouts() {
  async function load() {
    loading.value = true; error.value = ''
    try {
      const { data } = await apiClient.get(`/developers/me/prefs/${PREF_KEY}`)
      const v: StoredPrefs = (data && data.value) || {}
      saved.value = Array.isArray(v.layouts) ? v.layouts.map(sanitize).filter(Boolean) as DeskLayout[] : []
      if (v.activeId && !userChose.value) activeId.value = v.activeId
      loadedOnce.value = true
    } catch (e: any) {
      // An unreadable preference is not a broken desk: the starters still work.
      error.value = e?.response?.data?.detail || e?.message || 'could not read saved layouts'
    } finally {
      loading.value = false
    }
  }

  async function persist() {
    const body = { layouts: saved.value.slice(0, MAX_LAYOUTS), activeId: activeId.value }
    await apiClient.put(`/developers/me/prefs/${PREF_KEY}`, { value: body })
  }

  /**
   * 🔴 §COCKPITPOLISH — WRITE, THEN COMMIT LOCALLY. NEVER THE OTHER WAY ROUND.
   *
   * Every mutator here used to mutate `saved.value` and THEN persist, which means a failed
   * PUT left the screen showing a rename, a save or a deletion the server never accepted —
   * the §AGENTCOCKPIT lie exactly ("Saved." over a write that landed nothing), and it is
   * how the first battery run produced an unexplained timeout: the save had failed, the
   * chip appeared anyway from the local mutation, and `editing` stayed true.
   *
   * So: compute the next list, send it, and only adopt it if the server took it. On
   * failure the previous state is restored and the error is re-thrown for the caller to
   * show. `activeId` is snapshotted too — a rollback that leaves the selection pointing at
   * a layout the server does not have would be a subtler version of the same bug.
   */
  async function commit(next: DeskLayout[], nextActive?: string) {
    const prevLayouts = saved.value
    const prevActive = activeId.value
    saved.value = next
    if (nextActive !== undefined) activeId.value = nextActive
    try {
      await persist()
    } catch (e) {
      saved.value = prevLayouts
      activeId.value = prevActive
      throw e
    }
  }

  async function saveLayout(name: string, panes: PaneId[], sizes?: Record<string, number>) {
    const id = `u_${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 24)}_${Date.now().toString(36)}`
    const next = [...saved.value.filter(l => l.name !== name),
                  { id, name: name.slice(0, 40), panes: [...panes], sizes: { ...(sizes || {}) } }]
      .slice(-MAX_LAYOUTS)
    await commit(next, id)
    return id
  }

  /**
   * §COCKPITPOLISH (2026-08-31) — HIS REPORT: *"i cannot edit a saved builds name, nor
   * delete it."* Exactly right, and `deleteLayout` is why it stings: it has existed since
   * P1 and NOTHING EVER CALLED IT. A rail with no door is the class this project keeps
   * finding — the capability is written, tested by nobody, reachable by no one.
   *
   * ⚠ Only SAVED layouts are removable. The four starters are built into the image, so
   * "deleting" one would delete it until the next page load and then it would be back —
   * a control that appears to work and silently does not. The UI does not offer it and
   * this function refuses it, rather than leaving the two to disagree.
   */
  async function deleteLayout(id: string) {
    if (STARTER_LAYOUTS.some(l => l.id === id)) {
      throw new Error('Starter layouts are built in and cannot be deleted.')
    }
    const next = saved.value.filter(l => l.id !== id)
    if (next.length === saved.value.length) throw new Error('That layout is not saved on this account.')
    await commit(next, activeId.value === id ? STARTER_LAYOUTS[0].id : undefined)
  }

  /**
   * Rename in place. The ID is deliberately UNCHANGED: it is what `activeId` and every
   * stored selection point at, so minting a new one on a rename would silently orphan the
   * user's current choice — the same shape as the late-read bug above, one field over.
   *
   * ⚠ `saveLayout` de-dupes by NAME, which is why renaming could not be done by saving
   * again under a new name: that path creates a second layout and leaves the first. The
   * two operations are genuinely different and now say so.
   */
  async function renameLayout(id: string, name: string) {
    const clean = String(name || '').trim().slice(0, 40)
    if (!clean) throw new Error('A layout needs a name.')
    if (STARTER_LAYOUTS.some(l => l.id === id)) {
      throw new Error('Starter layouts are built in and cannot be renamed. Save it as your own first.')
    }
    const target = saved.value.find(l => l.id === id)
    if (!target) throw new Error('That layout is not saved on this account.')
    await commit(saved.value.map(l => (l.id === id ? { ...l, name: clean } : l)))
  }

  async function setActive(id: string) {
    userChose.value = true
    activeId.value = id
    if (loadedOnce.value) { try { await persist() } catch { /* selection is not worth an error toast */ } }
  }

  const all = computed<DeskLayout[]>(() => [...STARTER_LAYOUTS, ...saved.value])
  const active = computed<DeskLayout>(() =>
    all.value.find(l => l.id === activeId.value) || STARTER_LAYOUTS[0])

  /** Built-in vs the user's own — the UI needs it to decide which controls to offer,
   *  and asking it HERE keeps that decision in one place rather than in a template. */
  const isBuiltin = (id: string) => STARTER_LAYOUTS.some(l => l.id === id)

  return { all, active, activeId, saved, loading, error, load, saveLayout, deleteLayout, renameLayout, setActive, isBuiltin }
}

/* ────────────────────────────────────────────────────────────────────────────────────────
 * §DASHARRANGE (2026-09-02) — the DASHBOARD's one layout. His ask: "if you add arrange for
 * cockpit desk on mission-control users could add their own panes."
 *
 * Deliberately a SEPARATE pref key from the desk's named layouts: the dashboard holds one
 * board per person, with no name, no chips, no "which Build did I mean". Same sanitiser,
 * same whole-value PUT, same snapshot → write → roll back the screen on failure (the
 * §COCKPITPOLISH rule: the screen must never show a write the server refused).
 *
 * Three states, never folded: UNSET (`value: null` from the rail) ⇒ the default four;
 * EMPTY (a stored `panes: []`) ⇒ an empty board — the person removed every pane and that
 * is their choice; SET ⇒ theirs.
 * ─────────────────────────────────────────────────────────────────────────────────────── */
const DASHBOARD_PREF_KEY = 'cockpit.dashboard'
export const DASHBOARD_DEFAULT: DeskLayout = Object.freeze({
  id: 'dashboard', name: 'Dashboard',
  panes: ['quickactions', 'agents', 'earnings', 'decisions'] as PaneId[],
  sizes: {},
}) as DeskLayout

const dashLayout = ref<DeskLayout>({ ...DASHBOARD_DEFAULT, panes: [...DASHBOARD_DEFAULT.panes], sizes: {} })
/** §COCKPITDESK (2026-10-15) — the desk layout this board shows instead of its own arrangement (a starter id or a
 *  saved `u_` id), or null for its own. Stored beside `panes` in the same value, so the one whole-value PUT keeps
 *  both: the board's own arrangement survives a while it follows a desk layout, and comes back when it stops. */
const dashFollow = ref<string | null>(null)
const dashLoading = ref(false)
const dashError = ref('')
const dashLoadedOnce = ref(false)

export function useDashboardLayout() {
  async function load() {
    dashLoading.value = true; dashError.value = ''
    try {
      const { data } = await apiClient.get(`/developers/me/prefs/${DASHBOARD_PREF_KEY}`)
      const v = data && data.value
      if (v && typeof v === 'object' && Array.isArray((v as any).panes)) {
        const clean = sanitize({ id: 'dashboard', name: 'Dashboard', panes: (v as any).panes, sizes: (v as any).sizes })
        if (clean) dashLayout.value = clean
      } else {
        dashLayout.value = { ...DASHBOARD_DEFAULT, panes: [...DASHBOARD_DEFAULT.panes], sizes: {} }
      }
      dashFollow.value = cleanFollow(v && typeof v === 'object' ? (v as any).follow : null)
      dashLoadedOnce.value = true
    } catch (e: any) {
      dashError.value = e?.response?.data?.detail || e?.message || 'could not read the dashboard layout'
    } finally {
      dashLoading.value = false
    }
  }
  /** Saving the board's own arrangement is a choice to see it: it stops following a desk layout. */
  async function save(panes: PaneId[], sizes?: Record<string, number>) {
    const prev = dashLayout.value
    const prevFollow = dashFollow.value
    const next = sanitize({ id: 'dashboard', name: 'Dashboard', panes: [...panes], sizes: { ...(sizes || {}) } })
    if (!next) throw new Error('That board could not be saved.')
    dashLayout.value = next
    dashFollow.value = null
    try {
      await apiClient.put(`/developers/me/prefs/${DASHBOARD_PREF_KEY}`, { value: { panes: next.panes, sizes: next.sizes } })
    } catch (e) {
      dashLayout.value = prev   // the screen goes back to what the server still holds
      dashFollow.value = prevFollow
      throw e
    }
  }
  /**
   * §COCKPITDESK (2026-10-15) — show a desk layout here instead of this board's own arrangement (null: its own
   * again). Sent first, adopted only when the server took it; the board's own panes and sizes ride along unchanged.
   */
  async function setFollow(id: string | null) {
    const next = cleanFollow(id)
    const prev = dashFollow.value
    if (next === prev) return
    dashFollow.value = next
    const value: Record<string, unknown> = { panes: [...dashLayout.value.panes], sizes: { ...(dashLayout.value.sizes || {}) } }
    if (next) value.follow = next
    try {
      await apiClient.put(`/developers/me/prefs/${DASHBOARD_PREF_KEY}`, { value })
    } catch (e) {
      dashFollow.value = prev
      throw e
    }
  }
  /** An explicit choice, written as one: the default is STORED, not merely re-shown. */
  async function reset() { await save([...DASHBOARD_DEFAULT.panes], {}) }
  const isDefault = computed(() =>
    dashLayout.value.panes.join(',') === DASHBOARD_DEFAULT.panes.join(',') &&
    Object.keys(dashLayout.value.sizes || {}).length === 0)
  return { layout: dashLayout, follow: dashFollow, loading: dashLoading, error: dashError, loadedOnce: dashLoadedOnce,
           load, save, reset, setFollow, isDefault }
}

/** A followed layout id as stored: a short plain string, or nothing. */
function cleanFollow(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 && v.length <= 64 && /^[A-Za-z0-9_.-]+$/.test(v) ? v : null
}
