import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import v from '@/services/migrate/report.vectors.c4.json'
import MigrateReportView from './MigrateReportView.vue'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): #/migrate/report. A report or a certificate is dropped, chosen or pasted and read as a
 * page; its hash is recomputed here and matched to the certificate. NOTHING LEAVES THE BROWSER: no request is made at all (the test
 * fails on any fetch or XHR), and the page says so.
 */
const V: any = v
const text = (o: any) => JSON.stringify(o)
let fetchSpy: ReturnType<typeof vi.fn>

const mountIt = () => mount(MigrateReportView, { global: { stubs: { Icon: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
/** the page reads and hashes asynchronously (WebCrypto): wait until it says it is not busy, which it says with aria-busy */
async function idle(w: any) {
  await flushPromises()
  await vi.waitFor(() => expect(w.find('[data-testid="rp-root"]').attributes('aria-busy')).toBe('false'))
  await flushPromises()
}
async function paste(w: any, ...docs: any[]) {
  for (const d of docs) {
    await w.find('[data-testid="rp-paste"]').setValue(typeof d === 'string' ? d : text(d))
    await w.find('[data-testid="rp-read"]').trigger('click')
    await idle(w)
  }
}
function file(name: string, body: string) {
  const f = new File([body], name, { type: 'application/json' })
  if (!(f as any).text) (f as any).text = () => Promise.resolve(body)
  return f
}

beforeEach(() => { fetchSpy = vi.fn(); ;(globalThis as any).fetch = fetchSpy })
afterEach(() => { expect(fetchSpy).not.toHaveBeenCalled() })           // nothing left the browser, in any test

describe('the report page', () => {
  it('says what it does and that nothing leaves the browser, before anything is dropped', () => {
    const w = mountIt()
    expect(w.find('[data-testid="rp-privacy"]').text()).toMatch(/nothing leaves your browser/i)
    expect(w.find('[data-testid="rp-empty"]').exists()).toBe(true)
    expect(w.find('[data-testid="rp-read"]').attributes('disabled')).toBeDefined()    // nothing pasted yet
  })

  it('reads a pasted report as a page: verdict in words, counts, rejected rows by reason, fill per field, and that its hash holds', async () => {
    const w = mountIt()
    await paste(w, V.load)
    const card = w.find('[data-testid="rp-card-load"]')
    expect(card.exists()).toBe(true)
    expect(card.find('[data-testid="rp-verdict"]').text()).toContain('Passed')
    expect(card.find('[data-testid="rp-hash"]').attributes('data-state')).toBe('ok')
    expect(card.find('[data-testid="rp-hash"]').text()).toMatch(/hash holds/i)
    expect(card.text()).toContain('12,034')                                             // the source rows
    expect(card.find('[data-testid="rp-reasons"]').text()).toContain('30')
    expect(card.find('[data-testid="rp-fill"]').text()).toContain('email')
    expect(card.find('[data-testid="rp-targets"]').text()).toContain('11,990')
    expect(w.find('[data-testid="rp-empty"]').exists()).toBe(false)
  })

  it('marks a report whose hash does not hold, in words and by state', async () => {
    const t = JSON.parse(text(V.load)); t.targets.pg.written = 1
    const w = mountIt()
    await paste(w, t)
    expect(w.find('[data-testid="rp-hash"]').attributes('data-state')).toBe('bad')
    expect(w.find('[data-testid="rp-hash"]').text()).toMatch(/does not hold/i)
  })

  it('shows a reconcile as a table with a verdict per mapping and the reason where it could not compare', async () => {
    const w = mountIt()
    await paste(w, V.reconcile_not_measured)
    const rec = w.find('[data-testid="rp-reconcile"]')
    expect(rec.text()).toContain('customers')
    expect(rec.text()).toContain('Not measured')
    expect(rec.text()).toContain('the source has no key')
  })

  it('reads a certificate with its reports: every check in words, the matched hashes, nothing failed', async () => {
    const w = mountIt()
    await paste(w, V.certificate, V.dry_run, V.load, V.reconcile_pass)
    const cert = w.find('[data-testid="rp-cert"]')
    expect(cert.exists()).toBe(true)
    expect(cert.find('[data-testid="rp-check-record"]').attributes('data-state')).toBe('ok')
    expect(cert.find('[data-testid="rp-check-report:load"]').attributes('data-state')).toBe('ok')
    expect(cert.find('[data-testid="rp-check-moved"]').attributes('data-state')).toBe('ok')
    expect(cert.findAll('[data-state="bad"]')).toHaveLength(0)
    expect(cert.text()).toContain(V.claim_sha256.slice(0, 12))
    // the order: the certificate first, then the reports by step
    const ids = w.findAll('[data-testid^="rp-card-"],[data-testid="rp-cert"]').map((e) => e.attributes('data-testid'))
    expect(ids).toEqual(['rp-cert', 'rp-card-dry_run', 'rp-card-load', 'rp-card-reconcile'])
  })

  it('says what could not be checked when a report is missing, and fails nothing for it', async () => {
    const w = mountIt()
    await paste(w, V.certificate, V.load)
    const cert = w.find('[data-testid="rp-cert"]')
    expect(cert.find('[data-testid="rp-check-report:reconcile"]').attributes('data-state')).toBe('unknown')
    expect(cert.findAll('[data-state="bad"]')).toHaveLength(0)
  })

  it('a certificate with a changed claim fails its record key', async () => {
    const c = JSON.parse(text(V.certificate)); c.attestation_data.claim.moved = 7
    const w = mountIt()
    await paste(w, c, V.load)
    expect(w.find('[data-testid="rp-check-record"]').attributes('data-state')).toBe('bad')
  })

  it('reads chosen files, several at once, and says why a file is not readable', async () => {
    const w = mountIt()
    const input = w.find('[data-testid="rp-file"]')
    Object.defineProperty(input.element, 'files', { value: [file('load.json', text(V.load)), file('x.txt', 'nope'), file('y.json', '{"a":1}')], configurable: true })
    await input.trigger('change')
    await idle(w)
    expect(w.find('[data-testid="rp-card-load"]').exists()).toBe(true)
    const errs = w.findAll('[data-testid="rp-error"]')
    expect(errs).toHaveLength(2)
    expect(errs[0].text()).toContain('x.txt')
    expect(errs[0].text()).toMatch(/not JSON/i)
    expect(errs[1].text()).toMatch(/not a migration report or certificate/i)
  })

  it('takes a dropped file the same way', async () => {
    const w = mountIt()
    await w.find('[data-testid="rp-drop"]').trigger('drop', { dataTransfer: { files: [file('dry.json', text(V.dry_run))] } })
    await idle(w)
    expect(w.find('[data-testid="rp-card-dry_run"]').exists()).toBe(true)
  })

  it('removes one item, and clears them all', async () => {
    const w = mountIt()
    await paste(w, V.load, V.dry_run)
    await w.find('[data-testid="rp-remove-load"]').trigger('click')
    expect(w.find('[data-testid="rp-card-load"]').exists()).toBe(false)
    expect(w.find('[data-testid="rp-card-dry_run"]').exists()).toBe(true)
    await w.find('[data-testid="rp-clear"]').trigger('click')
    expect(w.find('[data-testid="rp-empty"]').exists()).toBe(true)
  })

  it('the same report dropped twice is shown once', async () => {
    const w = mountIt()
    await paste(w, V.load, V.load)
    expect(w.findAll('[data-testid="rp-card-load"]')).toHaveLength(1)
  })
})
