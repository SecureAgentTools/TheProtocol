/**
 * §BATCH8 item 9 (2026-09-06) — read a JWT's `exp` without verifying it (the server verifies; the client only
 * needs to know whether sending this token is pointless). Pure, so the interceptor's pre-flight decision is testable.
 *
 * Why: his console session expired at 23:32Z and the SPA fired 83 parallel balance batches with the dead token,
 * then one refresh (also dead). Six 401s inside a second read as a bruteforce to CrowdSec and banned his VPN exit.
 * Knowing the token is expired BEFORE firing avoids the burst entirely.
 */
export function jwtExpiresAt(token: string | null | undefined): number | null {
  if (!token || typeof token !== 'string') return null
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
    const exp = Number(payload?.exp)
    return Number.isFinite(exp) ? exp * 1000 : null
  } catch {
    return null
  }
}

/** True when the token carries an `exp` that is already past (with `skewMs` of tolerance). An unreadable
 *  token is NOT "expired" — the server decides that; we only pre-empt the certain case. */
export function isJwtExpired(token: string | null | undefined, nowMs: number = Date.now(), skewMs = 5_000): boolean {
  const exp = jwtExpiresAt(token)
  return exp !== null && exp - skewMs <= nowMs
}
