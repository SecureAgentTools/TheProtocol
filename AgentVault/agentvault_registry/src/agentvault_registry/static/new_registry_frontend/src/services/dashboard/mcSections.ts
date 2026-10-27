/**
 * services/dashboard/mcSections.ts — §MCFOLD (2026-09-02)
 *
 * Which of Mission Control's folded strips (the AGORA live ticker, the AGORA listings,
 * the live ledger) a person has opened. Per browser, in ONE localStorage key, so a
 * strip that was opened once stays open on this machine and nowhere else.
 *
 * The default is FOLDED for every strip (his word: "collapsed from the start so it
 * doesn't lock up the user when the network is really active"). A folded strip mounts
 * nothing, so a person who never opens the ledger never opens its sockets.
 */
export const MC_SECTIONS_KEY = 'mc.sections'
export type McSectionId = 'tape' | 'listings' | 'ledger'
type SectionMap = Record<string, '0' | '1'>

export function readSections(): SectionMap {
  try {
    const raw = localStorage.getItem(MC_SECTIONS_KEY)
    const j = raw ? JSON.parse(raw) : {}
    return j && typeof j === 'object' && !Array.isArray(j) ? (j as SectionMap) : {}
  } catch { return {} }
}

/** The saved state, else `fallback` (false = folded). */
export function isSectionOpen(id: string, fallback = false): boolean {
  const v = readSections()[id]
  return v === '1' ? true : v === '0' ? false : fallback
}

export function setSectionOpen(id: string, open: boolean): void {
  try {
    const m = readSections()
    m[id] = open ? '1' : '0'
    localStorage.setItem(MC_SECTIONS_KEY, JSON.stringify(m))
  } catch { /* storage unavailable: the choice lives for this page only */ }
}
