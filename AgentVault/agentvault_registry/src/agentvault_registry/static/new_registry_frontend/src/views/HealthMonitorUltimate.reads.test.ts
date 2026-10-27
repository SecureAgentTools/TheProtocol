/**
 * §FESUITE (V0578): the Health Monitor drew its figures from zeros whatever its reads did. Before the first check
 * answered (and after it failed) the header read a red "0%" score, "0/0" services and the donut "Critical"; a failed
 * network read drew a green "0.00%" error rate; a failed Prometheus read drew "All Clear" and "No alerts firing"; a failed
 * resources read "0%" CPU, memory and disk; failed docker and activity reads "No container data" and "No events"; the
 * Predictions tab "No anomalies detected" and a "normal" next-hour load with no check answered. The uptime tile was the
 * literal "99.9%". Now each read keeps its own state: "—" until it answered, a ReadFailedNotice when it failed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ get: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: (...a: unknown[]) => h.get(...a) } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ agentToken: null, isAdmin: true }) }))
vi.mock('@/stores/realtime', () => ({ useRealtimeStore: () => ({}) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError }) }))
vi.mock('chart.js', () => ({ Chart: class { static register() {} destroy() {} }, registerables: [] }))

import HealthMonitorUltimate from './HealthMonitorUltimate.vue'

const CHECK = '/admin/combined-health'
const NETWORK = '/metrics/network-health'
const RESOURCES = '/admin/system-resources'
const DOCKER = '/admin/docker-stats'
const ACTIVITY = '/admin/system-activity'
const PROM = '/admin/prometheus-metrics'
const ANSWERS: Record<string, unknown> = {
  [CHECK]: { health: { results: { auth: [
    { method: 'GET', path: '/auth/registration-config', healthy: true, authRequired: 'public', responseTime: 20, statusCode: 200 },
    { method: 'GET', path: '/developers/me', healthy: true, authRequired: 'developer', responseTime: 40, statusCode: 200 },
  ] } } },
  [NETWORK]: { total_agents: 12, active_agents: 5, response_time_p50: 30, response_time_p95: 90, error_rate: 0.002 },
  [RESOURCES]: { cpu: { percent: 37, count: 24 }, memory: { percent: 61, used_gb: 78, total_gb: 128 }, disk: { percent: 44, used_gb: 800, total_gb: 1800 } },
  [DOCKER]: { containers: {}, host: null },
  [ACTIVITY]: { events: [] },
  [PROM]: { targets: [{ instance: 'reg:8000', job: 'registry', health: 'up', tier: 'core' }], alerts: [], summary: { up_count: 1, total_targets: 1 } },
}
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

/** every read answers from ANSWERS except the ones named as failing */
function reads(failing: string[] | 'all') {
  h.get.mockImplementation(async (url: string) => {
    if (failing === 'all' || failing.includes(url)) throw badGateway()
    return { data: ANSWERS[url] }
  })
}
let w: VueWrapper | null = null
async function monitor() {
  w = mount(HealthMonitorUltimate, { global: { stubs: { Icon: true, Teleport: true } }, attachTo: document.body })
  for (let i = 0; i < 6; i++) await flushPromises()
  return w
}
async function tab(label: string) {
  const b = w!.findAll('.hm-tab').find(x => x.text().startsWith(label))
  expect(b, `no ${label} tab`).toBeTruthy()
  await b!.trigger('click')
  for (let i = 0; i < 6; i++) await flushPromises()
}
const header = () => w!.find('.hm-header').text()
const content = () => w!.find('.hm-content').text()

describe('the Health Monitor over failed reads', () => {
  beforeEach(() => { h.get.mockReset(); h.showError.mockReset(); vi.spyOn(console, 'error').mockImplementation(() => {}) })
  afterEach(() => { w?.unmount(); w = null })

  it('the header and overview draw no score, no zero and no invented uptime when every read failed', async () => {
    reads('all')
    await monitor()
    expect(header(), 'the header drew a score or a count over a failed check').not.toMatch(/\b0%|0\/0/)
    expect(header(), 'the uptime is a literal, not a read').not.toContain('99.9%')
    expect(content(), 'the donut said "Critical" about a check that never answered').not.toContain('Critical')
    expect(content(), 'a failed network read drew a 0.00% error rate').not.toContain('0.00%')
    expect(w!.find('[data-testid="hm-check-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="hm-network-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="hm-matrix-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="hm-alerts"]').text()).toBe('—')
  })

  it('the Prometheus tab never says "All Clear" over a failed alerts read, and does once the read answers', async () => {
    reads([PROM])
    await monitor()
    await tab('Prometheus')
    expect(content(), 'said all clear over a Prometheus read that failed').not.toContain('All Clear')
    expect(content()).not.toContain('No alerts firing')
    expect(w!.find('[data-testid="hm-alerts-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="hm-prom-failed"]').exists()).toBe(true)
    reads([])
    await w!.find('[data-testid="hm-alerts-failed"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 6; i++) await flushPromises()
    expect(content()).toContain('All Clear')
    expect(w!.find('[data-testid="hm-alerts"]').text()).toBe('0')
  })

  it('the Infrastructure tab draws no 0% resources and says its reads failed', async () => {
    reads('all')
    await monitor()
    await tab('Infrastructure')
    const values = w!.findAll('.hm-resource-value').map(v => v.text())
    expect(values.some(v => /^0%$|^0\/0$/.test(v)), `drew zeros over failed reads: ${values.join(' | ')}`).toBe(false)
    expect(content(), 'said no container data over a docker read that failed').not.toContain('No container data')
    expect(w!.find('[data-testid="hm-resources-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="hm-docker-failed"]').exists()).toBe(true)
  })

  it('the Activity tab says its read failed, never "No events"', async () => {
    reads('all')
    await monitor()
    await tab('Activity')
    expect(content(), 'said no events over an activity read that failed').not.toContain('No events')
    expect(w!.find('[data-testid="hm-activity-failed"]').exists()).toBe(true)
  })

  it('the Predictions tab claims no clean bill and no forecast over a check that never answered', async () => {
    reads('all')
    await monitor()
    await tab('Predictions')
    expect(content(), 'said no anomalies with no check answered').not.toContain('No anomalies detected')
    expect(content(), 'forecast a "normal" load from unread resources').not.toContain('normal')
    expect(content(), 'drew 0GB capacity from unread resources').not.toContain('0GB / 0GB')
    expect(w!.find('[data-testid="hm-anomalies-failed"]').exists()).toBe(true)
  })

  it('answered reads draw their figures (the gates hide nothing that was read)', async () => {
    reads([])
    await monitor()
    expect(w!.find('[data-testid="hm-score"]').text()).toBe('100%')
    expect(w!.find('[data-testid="hm-error-rate"]').text()).toBe('0.20%')
    expect(w!.find('[data-testid="hm-active-agents"]').text()).toBe('5')
    expect(w!.find('[data-testid="read-failed"]').exists()).toBe(false)
    await tab('Infrastructure')
    expect(w!.find('[data-testid="hm-cpu"]').text()).toBe('37%')
    await tab('Predictions')
    expect(content()).toContain('No anomalies detected')
    expect(w!.find('[data-testid="hm-next-hour-load"]').text()).toBe('normal')
  })
})


/**
 * §ALERTS (2026-10-06): the alerts are vmalert's, read from the metrics store inside /admin/prometheus-metrics. The page's
 * call can answer while that read did not (or while no store is configured): neither is an all-clear.
 */
describe("the Health Monitor's alerts, read from vmalert's state", () => {
  const prom = (over: Record<string, unknown>) => ({ ...(ANSWERS[PROM] as object), ...over })
  function answer(promBody: unknown) {
    h.get.mockImplementation(async (url: string) => ({ data: url === PROM ? promBody : ANSWERS[url] }))
  }
  beforeEach(() => { h.get.mockReset(); vi.spyOn(console, 'error').mockImplementation(() => {}) })
  afterEach(() => { w?.unmount(); w = null })

  it('the call answered but the alert read inside it did not: said, with the reason, no "All Clear"', async () => {
    answer(prom({ alerts_configured: true, alerts_readable: false, alerts_reason: 'transport:ConnectError' }))
    await monitor()
    await tab('Prometheus')
    expect(content()).not.toContain('All Clear')
    expect(content()).not.toContain('No alerts firing')
    expect(w!.find('[data-testid="hm-alerts-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="hm-alerts-failed"]').attributes('text') || content()).toContain('transport:ConnectError')
    expect(w!.find('[data-testid="hm-alerts"]').text()).toBe('—')
  })

  it('a registry with no metrics store says so (and is not an all-clear)', async () => {
    answer(prom({ alerts_configured: false, alerts_readable: false, alerts_reason: 'not_configured' }))
    await monitor()
    await tab('Prometheus')
    expect(w!.find('[data-testid="hm-alerts-not-configured"]').exists()).toBe(true)
    expect(content()).not.toContain('All Clear')
  })

  it("an answered read lists vmalert's alerts, counts the firing, and says how many sandbox alerts it left out", async () => {
    answer(prom({
      alerts_configured: true, alerts_readable: true, alerts_withheld: { sandbox: 2 },
      alerts: [{ alertname: 'DiskSpaceCritical', state: 'firing', severity: 'critical', instance: '', instance_name: '/dev/md2',
                 job: '', service: '', tier: '', labels: { device: '/dev/md2' }, annotations: { summary: 'Disk space critical' },
                 active_at: '2026-10-06T09:00:00+00:00' }],
    }))
    await monitor()
    await tab('Prometheus')
    expect(content()).toContain('DiskSpaceCritical')
    expect(content()).toContain('Disk space critical')
    expect(w!.find('[data-testid="hm-alerts"]').text()).toBe('1')
    expect(w!.find('[data-testid="hm-alerts-withheld"]').text()).toContain('2 sandbox alert(s)')
    expect(w!.find('[data-testid="hm-alerts-inhibited"]').exists()).toBe(false)   // nothing held back: no line
  })

  it('says how many warnings a firing critical held back (the alert e-mails\' rule), and does not count them', async () => {
    answer(prom({
      alerts_configured: true, alerts_readable: true, alerts_withheld: { sandbox: 0, inhibited: 1 },
      alerts: [{ alertname: 'DiskSpaceCritical', state: 'firing', severity: 'critical', instance: '', instance_name: '/dev/md2',
                 job: '', service: '', tier: '', labels: { device: '/dev/md2', family: 'host_disk' },
                 annotations: { summary: 'Disk space critical' }, active_at: '2026-10-06T09:00:00+00:00' }],
    }))
    await monitor()
    await tab('Prometheus')
    expect(w!.find('[data-testid="hm-alerts"]').text()).toBe('1')
    expect(w!.find('[data-testid="hm-alerts-inhibited"]').text()).toContain('1 warning(s) held back by a firing critical')
  })
})
