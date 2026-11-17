// V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the Pinned block at the top of the sidebar, shared with the
// sidebar's search and the command palette.
//
// Pins follow the account under their own developer-prefs key (console.nav_pins: {"paths": [...]}, a whole-value
// PUT like every key). A change reads the server's value first, changes it and writes it back, so a pin made on another
// device is kept; a write the server refuses is rolled back and reported, never shown as saved. Nothing pinned yet
// shows the defaults his approval named (Mission Control, OurChat, Pocket mode). A visitor has no account and no pins.
import { computed, ref } from 'vue'
import { getPref, putPref } from '@/services/api/pocketPrefs'

export const PINS_KEY = 'console.nav_pins' as const
export const DEFAULT_PINS: readonly string[] = ['/mission-control', '/ourchat', '/pocket/home']
export const MAX_PINS = 12

/** The stored value's paths: once each, only paths, capped. Null when unset or not this shape. */
export function pinsOf(value: unknown): string[] | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const paths = (value as Record<string, unknown>).paths
  if (!Array.isArray(paths)) return null
  const out: string[] = []
  for (const p of paths) {
    if (typeof p === 'string' && p.startsWith('/') && !out.includes(p)) out.push(p)
    if (out.length >= MAX_PINS) break
  }
  return out
}

export function togglePin(paths: readonly string[], path: string): string[] {
  return paths.includes(path) ? paths.filter((p) => p !== path) : [...paths, path].slice(0, MAX_PINS)
}

/** Move `path` to `to` (0-based) within the list; anything else unchanged. */
export function movePin(paths: readonly string[], path: string, to: number): string[] {
  const from = paths.indexOf(path)
  if (from === -1) return [...paths]
  const next = paths.filter((p) => p !== path)
  next.splice(Math.max(0, Math.min(to, next.length)), 0, path)
  return next
}

// one state for every caller: the sidebar, its search and the palette
const stored = ref<string[] | null>(null)
let loading: Promise<void> | null = null

export function _resetNavPins(): void { stored.value = null; loading = null }

export type PinWrite = 'saved' | 'failed'

export function useNavPins() {
  const pins = computed<string[]>(() => stored.value ?? [...DEFAULT_PINS])

  /** One read for every caller; `force` reads again (after a sign-in: a visitor's read had no account behind it). */
  function load(force = false): Promise<void> {
    if (force || !loading) {
      loading = getPref<unknown>(PINS_KEY).then((r) => { stored.value = pinsOf(r.value) }).catch(() => { /* the defaults stand */ })
    }
    return loading
  }

  /** Read the server's list, change it, write it back; the screen follows at once and rolls back on a refusal. */
  async function write(change: (base: string[]) => string[]): Promise<PinWrite> {
    const before = stored.value
    let base: string[]
    try {
      const fresh = await getPref<unknown>(PINS_KEY)
      base = pinsOf(fresh.value) ?? (before ?? [...DEFAULT_PINS])
    } catch {
      base = before ?? [...DEFAULT_PINS]
    }
    const next = change(base)
    stored.value = next
    const ok = await putPref(PINS_KEY, { paths: next })
    if (!ok) { stored.value = before; return 'failed' }
    return 'saved'
  }

  return {
    pins,
    load,
    isPinned: (path: string) => pins.value.includes(path),
    toggle: (path: string) => write((base) => togglePin(base, path)),
    move: (path: string, to: number) => write((base) => movePin(base, path, to)),
  }
}
