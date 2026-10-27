/**
 * composables/usePrivacy.ts — §BRIDGE R16.3, THE HIDE-AMOUNTS EYE.
 *
 * His ask (2026-08): amounts on the bridge can leak what you do not want leaked, so the screen
 * needs a way to hide them, the eye icon that phone apps showing private figures carry.
 *
 * The bridge is the surface he screenshots. Balances, bounties, ledger amounts
 * and exchange holdings are all on it at once, so a toggle that only covered
 * the card he pointed at would leave the leak intact one panel over. This is
 * therefore ONE switch for every figure the bridge renders.
 *
 * ── DESIGN NOTES ────────────────────────────────────────────────────────────
 * · Module-level state, not per-component: two panels disagreeing about whether
 *   money is hidden is worse than not having the feature.
 * · The mask replaces the TEXT rather than blurring it. A CSS blur leaves the
 *   real number in the DOM and in the accessibility tree — fine against a
 *   camera, useless against anything that reads the page, and this is meant to
 *   be the safe default when a screenshot leaves the building.
 * · Default OFF, by his choice. Nothing changes for anyone who never touches it.
 * · The toggle is not a security boundary and does not pretend to be: the data
 *   is still fetched, and anyone with the session can read it from the API. It
 *   hides a screen, which is exactly what such an eye icon does.
 */
import { ref, watch } from 'vue'

const KEY = 'bridge.privacy'

function initial(): boolean {
  try { return localStorage.getItem(KEY) === '1' } catch { return false }
}

/** Module-level: one answer for the whole bridge. */
const hidden = ref<boolean>(initial())

watch(hidden, (v) => {
  try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* private mode: the session still holds */ }
})

/** What a hidden figure reads as. Fixed width so a row does not jump on toggle. */
export const MASK = '••••'

export function usePrivacy() {
  /**
   * Mask a rendered amount. Pass the ALREADY-FORMATTED string, so every call
   * site keeps its own formatting rules (compact, tabular, currency suffix)
   * and this only decides whether the reader is allowed to see them.
   */
  function money(formatted: unknown): string {
    if (hidden.value) return MASK
    return formatted === null || formatted === undefined ? '' : String(formatted)
  }

  /** For a figure that carries its unit: hide the number, keep the currency. */
  function moneyWithUnit(formatted: unknown, unit?: string | null): string {
    const u = unit ? ` ${unit}` : ''
    return hidden.value ? `${MASK}${u}` : `${formatted ?? ''}${u}`
  }

  function toggle(): void { hidden.value = !hidden.value }

  return { hidden, money, moneyWithUnit, toggle, MASK }
}
