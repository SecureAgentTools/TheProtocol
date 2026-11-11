/**
 * services/settlementStates.ts: what a cross-registry settlement's state means, in plain words, and whether the
 * registry closes it (V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf).
 *
 * Three end states mean that no peer holds the settlement's slash request and nothing moved:
 *   NOT_DELIVERED  no request went out (CROSS_REGISTRY_SETTLEMENT_DELIVERY is off on this registry, or it publishes no
 *                  address a peer can dial)
 *   REFUSED        every peer registry refused the request
 *   CLOSED         an administrator closed it
 * An administrator closes a settlement no peer holds (no defendant registry recorded) that has not moved and is not
 * moving money (routers/federation_disputes.close_settlement); the registry sends `closable` on each row, and this
 * module derives the same rule for a row that does not carry it.
 */
import { i18n } from '@/i18n'

export const ENDED_STATES: ReadonlySet<string> = new Set(['NOT_DELIVERED', 'REFUSED', 'CLOSED'])
const NOT_CLOSABLE = new Set(['SETTLED', 'COMPENSATING', 'SLASHED', 'SLASHING', 'CLOSED'])

const LABELS: Record<string, string> = {
  PENDING_SLASH: 'Waiting for the slash',
  PENDING_ADMIN_APPROVAL: 'Waiting for an administrator',
  SLASHING: 'Slashing',
  SLASHED: 'Slashed',
  COMPENSATING: 'Paying the complainant',
  SETTLED: 'Settled',
  FAILED: 'Failed',
  REJECTED: 'Rejected',
  EXPIRED: 'Expired',
  NOT_DELIVERED: 'Not delivered',
  REFUSED: 'Refused by every peer',
  CLOSED: 'Closed',
}
const NOTES: Record<string, string> = {
  NOT_DELIVERED: 'No slash request was sent: delivery is off on this registry, or it has no address a peer can dial. Nothing moved, and the complainant is not paid through this settlement.',
  REFUSED: 'Every peer registry refused the slash request, so no peer holds it. Nothing moved, and the complainant is not paid through this settlement.',
  CLOSED: 'Closed by an administrator. Nothing moved, and the complainant is not paid through this settlement.',
}

/** The English bundle's words for a key, else the fallback (the other locales fall back to English). */
function words(key: string, fallback: string): string {
  try {
    const got = (i18n.global as any).t(key)
    if (typeof got === 'string' && got && got !== key) return got
  } catch { /* the fallback below */ }
  return fallback
}

/** A state in plain words; an unknown state reads as itself. */
export function stateLabel(status: string | null | undefined): string {
  const s = String(status || '')
  return LABELS[s] ? words(`settlementStates.label.${s}`, LABELS[s]) : s
}

/** What an end state means for the people in the dispute; empty for any other state. */
export function stateNote(status: string | null | undefined): string {
  const s = String(status || '')
  return NOTES[s] ? words(`settlementStates.note.${s}`, NOTES[s]) : ''
}

export interface ClosableRow {
  status: string
  defendant_registry_url?: string | null
  closable?: boolean
}

/** Whether the registry closes this settlement: its own answer when it sent one, else the same rule derived. */
export function canClose(s: ClosableRow): boolean {
  if (typeof s.closable === 'boolean') return s.closable
  return !NOT_CLOSABLE.has(String(s.status || '')) && !String(s.defendant_registry_url || '').trim()
}

/** A refusal in the registry's own words (its `detail`), else the request's error. */
export function refusalWords(e: any): string {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  return String(e?.message || 'The registry did not answer')
}
