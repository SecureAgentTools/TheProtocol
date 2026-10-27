import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * §ALERTS (2026-10-06): the one alert read the header strips share. It asks GET /admin/alerts/active (vmalert's state),
 * never the api client (a header read raises no global toast: the old ticker's 404 toasted "Not Found" every loop), and
 * keeps four states apart.
 */
const h = vi.hoisted(() => ({ token: 'tok' as string | null }))
vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => h.token } }))

import {
  ALERTS_PATH, ALERTS_POLL_MS, acquireActiveAlerts, activeAlerts, refreshActiveAlerts, __resetActiveAlertsForTests,
} from './activeAlerts'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('the shared alert read', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  beforeEach(() => {
    __resetActiveAlertsForTests()
    h.token = 'tok'
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); __resetActiveAlertsForTests() })

  it('asks the alerts route with the session, never Prometheus', async () => {
    fetchMock.mockResolvedValue(json(200, { configured: true, readable: true, alerts: [], counts: { firing: 0 }, withheld: { sandbox: 2, inhibited: 1 } }))
    await refreshActiveAlerts()
    expect(fetchMock).toHaveBeenCalledWith(ALERTS_PATH, { headers: { Authorization: 'Bearer tok' } })
    expect(ALERTS_PATH).toBe('/api/v1/admin/alerts/active')
    expect(activeAlerts.state).toBe('ok')
    expect(activeAlerts.withheldSandbox).toBe(2)
    expect(activeAlerts.withheldInhibited).toBe(1)
  })

  it('a refusal means no alerts mode (not an admin with the platform flag); so does no session', async () => {
    fetchMock.mockResolvedValue(json(403, { detail: 'nope' }))
    await refreshActiveAlerts()
    expect(activeAlerts.state).toBe('hidden')
    h.token = null
    await refreshActiveAlerts()
    expect(activeAlerts.state).toBe('hidden')
  })

  it('a failed read is unreadable, with the reason; never an all-clear', async () => {
    fetchMock.mockResolvedValueOnce(json(502, {}))
    await refreshActiveAlerts()
    expect(activeAlerts.state).toBe('unreadable')
    expect(activeAlerts.reason).toBe('http:502')

    fetchMock.mockResolvedValueOnce(json(200, { configured: true, readable: false, reason: 'transport:ConnectError', alerts: [] }))
    await refreshActiveAlerts()
    expect(activeAlerts.state).toBe('unreadable')
    expect(activeAlerts.reason).toBe('transport:ConnectError')

    fetchMock.mockRejectedValueOnce(new TypeError('network'))
    await refreshActiveAlerts()
    expect(activeAlerts.state).toBe('unreadable')
  })

  it('a registry without a metrics store says so', async () => {
    fetchMock.mockResolvedValue(json(200, { configured: false, readable: false, reason: 'not_configured', alerts: [] }))
    await refreshActiveAlerts()
    expect(activeAlerts.state).toBe('not_configured')
  })

  it('keeps the alerts and counts of an answered read', async () => {
    const alerts = [{ alertname: 'DiskSpaceCritical', title: 'Disk space critical', severity: 'critical', state: 'firing', labels: { device: '/dev/md2' }, active_since: null }]
    fetchMock.mockResolvedValue(json(200, { configured: true, readable: true, alerts, counts: { firing: 1, critical: 1 } }))
    await refreshActiveAlerts()
    expect(activeAlerts.alerts).toHaveLength(1)
    expect(activeAlerts.counts.firing).toBe(1)
    expect(activeAlerts.counts.critical).toBe(1)
    expect(activeAlerts.counts.warning).toBe(0)
  })

  it('one poll however many surfaces show it; the last to leave stops it', async () => {
    vi.useFakeTimers()
    fetchMock.mockResolvedValue(json(200, { configured: true, readable: true, alerts: [], counts: {} }))
    const releaseA = acquireActiveAlerts()
    const releaseB = acquireActiveAlerts()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(ALERTS_POLL_MS)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    releaseA()
    await vi.advanceTimersByTimeAsync(ALERTS_POLL_MS)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    releaseB()
    releaseB()                       // a second release of the same handle changes nothing
    await vi.advanceTimersByTimeAsync(ALERTS_POLL_MS * 3)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('two reads at once are one request', async () => {
    let resolve!: (r: Response) => void
    fetchMock.mockReturnValue(new Promise<Response>((r) => { resolve = r }))
    const a = refreshActiveAlerts()
    const b = refreshActiveAlerts()
    resolve(json(200, { configured: true, readable: true, alerts: [], counts: {} }))
    await Promise.all([a, b])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
