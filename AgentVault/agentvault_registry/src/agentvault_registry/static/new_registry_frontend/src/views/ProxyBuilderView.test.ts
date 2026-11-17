// V0664 C3 (order gwo_4110e12c11a69a93de878829): #/proxy/new, driven as a person builds a spec: nothing goes to a server; every
// problem tp-proxy validate would name shows as it is made and goes when it is fixed; a credential only by reference; a live
// preview of a mapping on a pasted row; proxy.yaml, compose and the commands to copy or download.
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: api }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({
  t: (_k: string, f?: string) => f ?? _k,
  tp: (_k: string, f: string, p: Record<string, unknown> = {}) => f.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? '')),
}) }))

import ProxyBuilderView from './ProxyBuilderView.vue'

const stubs = { RouterLink: { props: ['to'], template: '<a><slot /></a>' } }
const problems = (w: any) => w.find('[data-testid=pb-problems]').text()

async function addPart(w: any, role: string, type: string, name: string) {
  await w.find(`[data-testid=pb-add-${role}-type]`).setValue(type)
  await w.find(`[data-testid=pb-add-${role}-name]`).setValue(name)
  await w.find(`[data-testid=pb-add-${role}]`).trigger('submit')
}


// V0664 console proof (axe scrollable-region-focusable, session-lead seq 4206): a code box that can scroll is reachable by
// keyboard and named: tabindex 0, role region, an aria-label
function codeBoxesReachable(w: any) {
  const pres = w.findAll('pre')
  expect(pres.length).toBeGreaterThan(0)
  for (const p of pres) {
    expect(p.attributes('tabindex'), p.html().slice(0, 60)).toBe('0')
    expect(p.attributes('role')).toBe('region')
    expect((p.attributes('aria-label') || '').trim().length).toBeGreaterThan(3)
  }
}

describe('the proxy spec builder', () => {
  it('starts from a spec that names its agent by reference and asks nothing of a server', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    expect(w.find('[data-testid=pb-out-text]').text()).toContain('client_secret: "env:CLIENT_SECRET"')
    expect(api.get).not.toHaveBeenCalled()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('the add buttons read as English: a source, an action, a sink (pass 3)', () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    expect(['source', 'action', 'sink'].map((r) => w.find(`[data-testid=pb-add-${r}]`).text())).toEqual(['Add a source', 'Add an action', 'Add a sink'])
  })

  it('a valid spec that reads nothing says so, not Ready; with a source and a mapping it is Ready (pass 3)', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    expect(problems(w)).toContain('Valid, but it reads nothing yet')
    expect(problems(w)).toContain('Add a source, then a mapping to an action or a sink.')
    expect(problems(w)).not.toContain('Ready')
    await addPart(w, 'source', 'filedrop', 'sis')
    await w.find('[data-testid=ppf-source-sis-path]').setValue('/data/sis-out')
    expect(problems(w)).toContain('Valid, but it reads nothing yet')
    await addPart(w, 'action', 'attestation', 'issue')
    await w.find('[data-testid=ppf-action-issue-attestation_type]').setValue('lyceum.credential_awarded')
    await w.find('[data-testid=pb-add-mapping]').trigger('submit')
    expect(problems(w)).toContain('Ready')
  })

  it('a problem is a button that takes you to its field (pass 4)', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs }, attachTo: document.body })
    await addPart(w, 'source', 'filedrop', 'sis')
    const go = w.find('[data-testid=pb-problems] button')
    expect(go.find('code').text()).toBe('sources.sis.config')
    expect(go.text()).toContain('Path is required')              // V0665: in the field's own words, not jsonschema's
    Element.prototype.scrollIntoView = vi.fn()
    await go.trigger('click')
    expect(document.activeElement?.id).toBe('ppf-source-sis-path')
    w.unmount()
  })

  it('a source\'s required field is named until it is filled', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'source', 'filedrop', 'sis')
    expect(w.find('[data-testid=pb-part-source-sis]').exists()).toBe(true)
    expect(problems(w)).toContain('sources.sis.config: Path is required')
    await w.find('[data-testid=ppf-source-sis-path]').setValue('/data/sis-out')
    expect(problems(w)).not.toContain('sources.sis.config: Path is required')
  })

  // V0665 (order gwo_1533f427, session-lead's note on C3): the list read jsonschema's "'listen' is a required property"
  it('says the four missing settings of a webhook source and a payment action in the fields\' own words, the place kept', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'source', 'webhook', 'in')
    await addPart(w, 'action', 'payment', 'pay')
    const text = problems(w)
    expect(text).toContain('4 to fix before it runs')
    for (const s of ['sources.in.config: Listen is required', 'sources.in.config: Path is required',
      'actions.pay.config: Mandate is required', 'actions.pay.config: Max amount is required']) expect(text).toContain(s)
    expect(text).not.toMatch(/required property|'listen'|'mandate'/)
  })

  it('a wrong value reads in words too ("Listen must be written host:port") and the problem still goes to its field', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs }, attachTo: document.body })
    await addPart(w, 'source', 'webhook', 'in')
    await w.find('[data-testid=ppf-source-in-listen]').setValue('8080')
    expect(problems(w)).toContain('sources.in.config.listen: Listen must be written host:port, for example 0.0.0.0:8080')   // the place names the key, as tp-proxy validate does
    const go = w.findAll('[data-testid=pb-problems] button').find((b: any) => b.text().includes('Listen must be'))
    Element.prototype.scrollIntoView = vi.fn()
    await go!.trigger('click')
    expect(document.activeElement?.id).toBe('ppf-source-in-listen')
    w.unmount()
  })

  it('a credential written out is refused beside its field and in the list, and passes as a reference', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'sink', 'rest', 'erp')
    await w.find('[data-testid=ppf-sink-erp-url]').setValue('https://erp.example.org/in')
    await w.find('[data-testid=ppf-sink-erp-bearer]').setValue('plain-token')
    expect(w.find('[data-testid=ppf-sink-erp-bearer-secret]').text()).toMatch(/env:NAME or file:\/path/)
    expect(problems(w)).toContain('sinks.erp.config.bearer: a credential is written out')
    expect(problems(w)).not.toContain('plain-token')
    await w.find('[data-testid=ppf-sink-erp-bearer]').setValue('env:ERP_TOKEN')
    expect(w.find('[data-testid=ppf-sink-erp-bearer-secret]').exists()).toBe(false)
    expect(problems(w)).not.toContain('bearer')
  })

  it('a name an action already has cannot be a sink\'s too', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'action', 'attestation', 'issue')
    await w.find('[data-testid=pb-add-sink-name]').setValue('issue')
    expect(w.find('[data-testid=pb-add-sink]').attributes('disabled')).toBeDefined()
  })

  it('a mapping from a source to an action, its fields, and its live preview on a pasted row', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'source', 'filedrop', 'sis')
    await w.find('[data-testid=ppf-source-sis-path]').setValue('/data/sis-out')
    await addPart(w, 'action', 'attestation', 'issue')
    await w.find('[data-testid=ppf-action-issue-attestation_type]').setValue('lyceum.credential_awarded')
    await w.find('[data-testid=pb-add-mapping]').trigger('submit')
    await w.find('[data-testid=pb-mapping-0-target-0]').setValue('award')
    await w.find('[data-testid=pb-mapping-0-value-0]').setValue('$.payload.data.award_id')
    await w.find('[data-testid=pb-mapping-0-addfield]').trigger('click')
    await w.find('[data-testid=pb-mapping-0-target-1]').setValue('ects')
    await w.find('[data-testid=pb-mapping-0-value-1]').setValue('{"path": "$.payload.data.ects", "as": "int"}')
    await w.find('[data-testid=pb-mapping-0-sample]').setValue('{"award_id": "A-1", "ects": "30"}')
    await flushPromises()
    expect(JSON.parse(w.find('[data-testid=pb-mapping-0-preview]').text())).toEqual({ award: 'A-1', ects: 30 })
    expect(w.find('[data-testid=pb-mapping-0-preview-label]').text()).toBe('What issue gets from this row')   // pass 1 D9
    expect(w.find('[data-testid=pb-problems]').text()).toContain('Ready')
    await w.find('[data-testid=pb-mapping-0-sample]').setValue('{"ects": "30"}')
    expect(w.find('[data-testid=pb-mapping-0-preview-refused]').text()).toContain('award')
    await w.find('[data-testid=pb-mapping-0-when-path]').setValue('$.payload.data.status')
    await w.find('[data-testid=pb-mapping-0-when-equals]').setValue('AWARDED')
    expect(w.find('[data-testid=pb-mapping-0-preview-skip]').exists()).toBe(true)
    const yaml = w.find('[data-testid=pb-out-text]').text()
    expect(yaml).toContain('to: issue')
    expect(yaml).toContain('award: "$.payload.data.award_id"')
  })

  it('removing a source removes its mappings with it', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'source', 'filedrop', 'sis')
    await addPart(w, 'action', 'attestation', 'issue')
    await w.find('[data-testid=pb-add-mapping]').trigger('submit')
    expect(w.find('[data-testid=pb-mapping-0]').exists()).toBe(true)
    await w.find('[data-testid=pb-remove-source-sis]').trigger('click')
    expect(w.find('[data-testid=pb-mapping-0]').exists()).toBe(false)
  })

  it('keeps the outputs in view: while it is open the page clips its overflow instead of hiding it, and puts the shell back (pass 1 D6)', () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    expect(document.documentElement.classList.contains('pb-page')).toBe(true)
    expect(document.body.classList.contains('pb-page')).toBe(true)
    w.unmount()
    expect(document.documentElement.classList.contains('pb-page')).toBe(false)
    expect(document.body.classList.contains('pb-page')).toBe(false)
  })

  it('its outputs column sits below the sticky beta banner, at the banner\'s own height (pass 2)', async () => {
    const banner = document.createElement('div')
    banner.className = 'beta-banner'
    banner.getBoundingClientRect = () => ({ top: 0, bottom: 61, height: 61, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => ({}) })
    document.body.appendChild(banner)
    const w = mount(ProxyBuilderView, { global: { stubs }, attachTo: document.body })
    await flushPromises()
    expect((w.find('[data-testid=pb-root]').element as HTMLElement).style.getPropertyValue('--pb-top')).toBe('61px')
    banner.remove()
    window.dispatchEvent(new Event('scroll'))
    await new Promise((r) => setTimeout(r, 40))
    expect((w.find('[data-testid=pb-root]').element as HTMLElement).style.getPropertyValue('--pb-top')).toBe('0px')
    w.unmount()
  })

  it('on a phone a bar says whether the spec is ready and goes to the outputs (pass 1 D8)', async () => {
    const into = vi.fn()
    Element.prototype.scrollIntoView = into
    const w = mount(ProxyBuilderView, { global: { stubs }, attachTo: document.body })
    expect(w.find('[data-testid=pb-bar]').text()).toContain('Nothing to run yet')
    await addPart(w, 'source', 'filedrop', 'sis')
    expect(w.find('[data-testid=pb-bar]').text()).toContain('1 to fix')
    await w.find('[data-testid=pb-bar-go]').trigger('click')
    expect(into).toHaveBeenCalled()
    expect((into.mock.contexts[0] as HTMLElement).id).toBe('pb-out')
    w.unmount()
  })

  it('the outputs: compose and the run commands, copied and downloaded', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    const created = vi.fn(() => 'blob:x')
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() })
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await w.find('[data-testid=pb-out-compose]').trigger('click')
    expect(w.find('[data-testid=pb-out-text]').text()).toContain('./proxy.yaml:/app/proxy.yaml:ro')
    await w.find('[data-testid=pb-download]').trigger('click')
    expect(created).toHaveBeenCalled()
    await w.find('[data-testid=pb-out-run]').trigger('click')
    expect(w.find('[data-testid=pb-out-text]').text()).toBe('tp-proxy validate proxy.yaml\ntp-proxy run proxy.yaml --dry-run\ntp-proxy run proxy.yaml')
    expect(w.find('[data-testid=pb-download]').exists()).toBe(false)
    await w.find('[data-testid=pb-copy]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('tp-proxy validate'))
    expect(w.find('[data-testid=pb-copy]').text()).toBe('Copied')
  })

  it('every code box is reachable by keyboard and named: the outputs and a mapping\'s preview (proof seq 4206)', async () => {
    const w = mount(ProxyBuilderView, { global: { stubs } })
    await addPart(w, 'source', 'filedrop', 'sis')
    await addPart(w, 'action', 'attestation', 'issue')
    await w.find('[data-testid=pb-add-mapping]').trigger('submit')
    await w.find('[data-testid=pb-mapping-0-target-0]').setValue('award')
    await w.find('[data-testid=pb-mapping-0-value-0]').setValue('$.payload.data.award_id')
    await w.find('[data-testid=pb-mapping-0-sample]').setValue('{"award_id": "A-1"}')
    await flushPromises()
    expect(w.findAll('pre')).toHaveLength(2)
    codeBoxesReachable(w)
  })
})
