/** §FESUITE (2026-10-10): what a coordinated bulk suspend or reinstate says, by its outcome. Every outcome was a SUCCESS
 *  toast, so "0 suspended (skipped 0, failed 1 of 1)" read as done on an enforcement action. Skipped is not failed: an
 *  agent already suspended is skipped by design. */
export function bulkOutcome(data: { succeeded?: number, failed?: number } | null | undefined): 'error' | 'warning' | 'success' {
  const ok = Number(data?.succeeded || 0)
  const bad = Number(data?.failed || 0)
  if (bad > 0 && ok === 0) return 'error'
  if (bad > 0) return 'warning'
  return 'success'
}
