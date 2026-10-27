/**
 * §TOURWALK (2026-09-03) — the guided tour's keyboard rule, kept PURE so it is testable without
 * mounting the overlay. Escape ends the tour, ArrowRight/ArrowLeft step it — but never while the
 * tour is inactive, while a door the tour itself opened (the quick-agent modal) sits on top of the
 * hidden coach, or while the person is typing in a field. Measured: pressing Escape to close the
 * wallet sheet the walkthrough had opened ENDED the walkthrough (drive_phone.mjs leg 5e).
 */
export type TourKeyAction = 'end' | 'next' | 'back' | null
export interface TourKeyContext { active: boolean; modalOpen: boolean; editable: boolean }

export function tourKeyAction(key: string, ctx: TourKeyContext): TourKeyAction {
  if (!ctx.active || ctx.modalOpen || ctx.editable) return null
  if (key === 'Escape') return 'end'
  if (key === 'ArrowRight') return 'next'
  if (key === 'ArrowLeft') return 'back'
  return null
}

/** True when a key event landed in something a person types into. */
export function isEditableTarget(t: EventTarget | null | undefined): boolean {
  const el = t as (HTMLElement & { isContentEditable?: boolean }) | null
  if (!el || typeof el !== 'object') return false
  const tag = String(el.tagName || '').toUpperCase()
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return el.isContentEditable === true
}
