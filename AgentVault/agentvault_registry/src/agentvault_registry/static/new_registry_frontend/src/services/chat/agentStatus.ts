/**
 * V0662 (OurChat lane, the batch's item 11): the session board, the console's pure rules (the registry's: services/
 * chat_agent_status.py, GET /chat/conversations/{id}/agent-status).
 *
 * The organization's owners and admins see, per session of the room, what the room's desk last reported: its state, wake mode,
 * the last wake and the wakes in the last 24 hours (who spends). The registry never guesses (a row not refreshed for 5 minutes reads
 * `unknown` and carries no mode or count), and neither does this: it draws what it is given, in words, and never turns "unknown"
 * into "active" or a missing count into zero.
 */
export type SessionState = 'active' | 'paused' | 'unreachable' | 'unknown'

export interface SessionRow {
  key: string
  name: string
  state: SessionState
  wake_mode: string | null
  last_wake_at: string | null
  wakes_24h: number | null
  reported_at: string | null
  age_s: number | null
}

const STATES: SessionState[] = ['active', 'paused', 'unreachable', 'unknown']

/** The rows as the registry gave them, cleaned: a state this console does not know reads `unknown`, never something it was not. */
export function cleanSessions(list: any): SessionRow[] {
  const out: SessionRow[] = []
  for (const r of Array.isArray(list) ? list : []) {
    if (!r || typeof r.key !== 'string') continue
    out.push({
      key: r.key,
      name: String(r.name || r.key),
      state: (STATES as string[]).includes(r.state) ? r.state : 'unknown',
      wake_mode: typeof r.wake_mode === 'string' ? r.wake_mode : null,
      last_wake_at: typeof r.last_wake_at === 'string' ? r.last_wake_at : null,
      wakes_24h: Number.isFinite(Number(r.wakes_24h)) && r.wakes_24h !== null ? Number(r.wakes_24h) : null,
      reported_at: typeof r.reported_at === 'string' ? r.reported_at : null,
      age_s: Number.isFinite(Number(r.age_s)) && r.age_s !== null ? Number(r.age_s) : null,
    })
  }
  return out
}

/** "3 min", "2 h", "45 s": how long ago, for a count of seconds (null for none). */
export function agoWord(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h`
  return `${Math.round(seconds / 86400)} d`
}

/** Seconds from an ISO time to now, or null when it does not parse. */
export function secondsSince(iso: string | null | undefined, nowMs: number): number | null {
  const t = Date.parse(String(iso || ''))
  return Number.isFinite(t) ? Math.max(0, Math.round((nowMs - t) / 1000)) : null
}
