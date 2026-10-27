/**
 * §ALERTS (2026-10-06, agentvault2-09): the firing alerts, read once for every surface that shows them (the LED strip's
 * alerts mode and the announcement bar's chip), from GET /admin/alerts/active: vmalert's state, read where it lives.
 *
 * The old ticker asked the alerts route with an extra 'health' path segment, which does not exist: a 404 on every scroll
 * loop, each one
 * a global "Not Found" toast, under a strip that said "NO ALERTS // MONITORING ACTIVE". So:
 *  - fetch(), not the api client: a header read never raises a global toast; the strip says what happened itself;
 *  - one poll (every 60 s, and on returning to the tab) however many surfaces show it;
 *  - four states that are never collapsed: not_configured, unreadable, ok (alerts or none), and hidden for a person the
 *    route refuses (not an admin with the platform flag): they never see an alerts mode at all.
 */
import { reactive, readonly } from 'vue'
import { authService } from '@/services/auth'
import { NO_COUNTS, type ActiveAlert, type AlertCounts, type AlertsState } from './headerStrip'

export const ALERTS_PATH = '/api/v1/admin/alerts/active'
export const ALERTS_POLL_MS = 60_000

interface ActiveAlertsState {
  state: AlertsState
  alerts: ActiveAlert[]
  counts: AlertCounts
  withheldSandbox: number
  /** warnings held back by a firing critical of their family (the alert e-mails' inhibit rule, applied by the reader) */
  withheldInhibited: number
  reason: string | null
  readAt: number
}

const s = reactive<ActiveAlertsState>({
  state: 'loading',
  alerts: [],
  counts: { ...NO_COUNTS },
  withheldSandbox: 0,
  withheldInhibited: 0,
  reason: null,
  readAt: 0,
})

let consumers = 0
let timer: ReturnType<typeof setInterval> | null = null
let inflight: Promise<void> | null = null

/** Read the alerts now (one read at a time; a second caller shares the first one's answer). */
export function refreshActiveAlerts(): Promise<void> {
  if (inflight) return inflight
  inflight = (async () => {
    const token = authService.getAccessToken()
    if (!token) { s.state = 'hidden'; return }
    try {
      const res = await fetch(ALERTS_PATH, { headers: { Authorization: `Bearer ${token}` } })
      if (res.status === 401 || res.status === 403) {
        // not an admin with the platform flag (or no session): there is no alerts mode for them
        s.state = 'hidden'; s.alerts = []; s.counts = { ...NO_COUNTS }
        return
      }
      if (!res.ok) {
        s.state = 'unreadable'; s.reason = `http:${res.status}`
        return
      }
      const body = await res.json()
      if (!body || typeof body !== 'object') { s.state = 'unreadable'; s.reason = 'body:unexpected'; return }
      if (body.configured === false) { s.state = 'not_configured'; s.reason = body.reason ?? 'not_configured'; s.alerts = []; return }
      if (body.readable !== true) { s.state = 'unreadable'; s.reason = body.reason ?? null; return }
      s.alerts = Array.isArray(body.alerts) ? body.alerts : []
      s.counts = { ...NO_COUNTS, ...(body.counts || {}) }
      s.withheldSandbox = Number(body.withheld?.sandbox) || 0
      s.withheldInhibited = Number(body.withheld?.inhibited) || 0
      s.reason = null
      s.readAt = Date.now()
      s.state = 'ok'
    } catch {
      // the network never answered: an earlier answer is not this one
      s.state = 'unreadable'; s.reason = 'transport'
    }
  })().finally(() => { inflight = null })
  return inflight
}

function onVisible() {
  if (typeof document !== 'undefined' && !document.hidden) void refreshActiveAlerts()
}

/** A surface that shows the alerts calls this while mounted; the last one to leave stops the poll. */
export function acquireActiveAlerts(): () => void {
  consumers += 1
  if (consumers === 1) {
    void refreshActiveAlerts()
    timer = setInterval(() => {
      if (typeof document === 'undefined' || !document.hidden) void refreshActiveAlerts()
    }, ALERTS_POLL_MS)
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)
  }
  let released = false
  return () => {
    if (released) return
    released = true
    consumers = Math.max(0, consumers - 1)
    if (consumers === 0) {
      if (timer) { clearInterval(timer); timer = null }
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
    }
  }
}

export const activeAlerts = readonly(s)

/** Tests only: back to the first state, no poll running. */
export function __resetActiveAlertsForTests(): void {
  if (timer) { clearInterval(timer); timer = null }
  consumers = 0
  inflight = null
  Object.assign(s, { state: 'loading', alerts: [], counts: { ...NO_COUNTS }, withheldSandbox: 0, withheldInhibited: 0, reason: null, readAt: 0 })
}
