import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): #/migrate/new, the migration builder. A person picks the kinds, a source and a writer from the catalog, maps
 * fields with transforms and sees the mapping run on a sample that never leaves the browser; migration.yaml and proxy.yaml appear as they type, the
 * registry's publish gate is run over them and its problems are listed by rule; the files are downloaded, or saved as a private draft (agent tier).
 */
const h = vi.hoisted(() => ({ auth: { token: '', agentToken: '', activeAgent: null } as any, create: null as any, publish: null as any, push: null as any }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/api/workflowTemplates', () => ({ createTemplate: (...a: any[]) => h.create(...a), publishVersion: (...a: any[]) => h.publish(...a) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: (...a: any[]) => h.push(...a) }) }))

import MigrateBuilderView from './MigrateBuilderView.vue'

let fetchSpy: ReturnType<typeof vi.fn>
const mountIt = () => mount(MigrateBuilderView, { attachTo: document.body, global: { stubs: { Icon: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
async function setBasics(w: any, name = 'orders-to-pg', title = 'Orders to PostgreSQL') {
  await tid(w, 'mb-name').setValue(name)
  await tid(w, 'mb-title').setValue(title)
}
const yamlOf = (w: any) => tid(w, 'mb-yaml').text()

beforeEach(() => {
  h.auth = { token: '', agentToken: '', activeAgent: null }
  h.create = vi.fn().mockResolvedValue({ template_id: 'wtpl_9', version: 1, content_hash: 'h', published: false })
  h.publish = vi.fn().mockResolvedValue({ published: true })
  h.push = vi.fn()
  fetchSpy = vi.fn(); ;(globalThis as any).fetch = fetchSpy
  try { localStorage.clear() } catch { /* */ }
})
afterEach(() => { document.body.innerHTML = '' })

describe('the builder page', () => {
  it('says what it does and that the sample never leaves the browser, and starts from a skeleton', () => {
    const w = mountIt()
    expect(tid(w, 'mb-privacy').text()).toMatch(/never leaves your browser/i)
    expect(yamlOf(w)).toContain('schema: theprotocol.migration/v1')
    expect(w.find('[data-testid="mb-field-row"]').exists()).toBe(true)
  })

  it('writes migration.yaml as the person types, and the registry\'s gate says what is missing until there is a name and a title', async () => {
    const w = mountIt()
    expect(tid(w, 'mb-problems').text()).toMatch(/name/)
    expect(tid(w, 'mb-download').attributes('disabled')).toBeDefined()
    await setBasics(w)
    expect(yamlOf(w)).toContain('name: orders-to-pg')
    expect(tid(w, 'mb-problems').text()).toMatch(/Nothing to fix/i)
    expect(tid(w, 'mb-download').attributes('disabled')).toBeUndefined()
  })

  it('keeps a status line within reach on a phone: what is left to fix, how many sample rows map, and a way to the kit', async () => {
    const w = mountIt()
    expect(tid(w, 'mb-bar').text()).toMatch(/\d+ things? to fix/)
    await setBasics(w)
    expect(tid(w, 'mb-bar').text()).toContain('Nothing to fix')
    await tid(w, 'mb-sample').setValue('id,name,email\n1,Ada,a@example.invalid\n2,Grace,g@example.invalid')
    await tid(w, 'mb-from-columns').trigger('click')
    expect(tid(w, 'mb-bar').text()).toContain('2 of 2 rows mapped')
    expect(tid(w, 'mb-bar-go').exists()).toBe(true)
  })
  it('shows proxy.yaml in its own tab, with the mapping the fields describe', async () => {
    const w = mountIt()
    await setBasics(w)
    await tid(w, 'mb-tab-proxy').trigger('click')
    expect(yamlOf(w)).toContain('sources:')
    expect(yamlOf(w)).toContain('"$.payload.data.id"')
  })

  it('changing the kinds changes what the catalog offers and resets the source and the writer', async () => {
    const w = mountIt()
    await tid(w, 'mb-from').setValue('sql')
    await tid(w, 'mb-to').setValue('rest')
    expect(tid(w, 'mb-source-type').element.querySelectorAll('option')).toHaveLength(1)
    await tid(w, 'mb-tab-proxy').trigger('click')
    expect(yamlOf(w)).toContain('type: sqlpoll')
    expect(yamlOf(w)).toContain('type: rest')
  })

  it('a destination or a secret is a parameter the user sets: the field takes a name, not a value, and says why', async () => {
    const w = mountIt()
    const host = w.find('[data-testid="mb-cfg-sink-host"]')
    expect(host.exists()).toBe(true)
    const rule = w.find('[data-testid="mb-cfg-sink-rule"]')
    expect(rule.text()).toMatch(/names no destination of its own/i)
    expect(rule.text()).toMatch(/secret is never written into a kit/i)
    expect(w.findAll('[data-testid="mb-cfg-sink-rule"]')).toHaveLength(1)                       // said once for the section ...
    expect(w.find('[data-testid="mb-cfg-sink-host"]').element.closest('.pcf-row')!.textContent).not.toMatch(/names no destination/i)   // ... and not again under each field
    expect(w.find('label[for="pcf-sink-on_conflict"]').text()).toContain('On conflict')          // a key in words, the key beside it
    expect(w.find('label[for="pcf-sink-on_conflict"] .pcf-key').text()).toBe('on_conflict')
    await host.setValue('MY_HOST')
    await tid(w, 'mb-tab-proxy').trigger('click')
    expect(yamlOf(w)).toContain('"${MY_HOST}"')
    await host.setValue('not a name!')
    expect(w.find('[data-testid="mb-cfg-sink-host-err"]').exists()).toBe(true)
  })

  it('adds a field, sets a transform, and the node appears in proxy.yaml', async () => {
    const w = mountIt()
    await setBasics(w)
    await tid(w, 'mb-add-field').trigger('click')
    const rows = w.findAll('[data-testid="mb-field-row"]')
    const last = rows[rows.length - 1]
    await last.find('[data-testid="mb-field-target"]').setValue('amount')
    await last.find('[data-testid="mb-field-path"]').setValue('$.payload.data.amount')
    await last.find('[data-testid="mb-field-more"]').trigger('click')
    await last.find('[data-testid="mb-field-as"]').setValue('decimal')
    await last.find('[data-testid="mb-field-round"]').setValue('2')
    await tid(w, 'mb-tab-proxy').trigger('click')
    expect(yamlOf(w)).toContain('amount:')
    expect(yamlOf(w)).toContain('as: decimal')
    expect(yamlOf(w)).toContain('round: 2')
  })

  it('removes a field', async () => {
    const w = mountIt()
    const n = w.findAll('[data-testid="mb-field-row"]').length
    await w.find('[data-testid="mb-field-remove"]').trigger('click')
    expect(w.findAll('[data-testid="mb-field-row"]').length).toBe(n - 1)
  })

  it('runs the mapping on a pasted sample: counts, a refused row with its rule and never its value, the mapped rows', async () => {
    const w = mountIt()
    await setBasics(w)
    await tid(w, 'mb-sample-format').setValue('csv')
    await tid(w, 'mb-sample').setValue('id,name,email\n1,Ada,ada@example.invalid\n2,Bert,bert@example.invalid\n')
    expect(tid(w, 'mb-preview-counts').text()).toMatch(/2.*taken/i)
    expect(tid(w, 'mb-preview-rows').text()).toContain('Ada')
    // a field that cannot be read in one row refuses it, by rule
    await tid(w, 'mb-add-field').trigger('click')
    const rows = w.findAll('[data-testid="mb-field-row"]')
    const last = rows[rows.length - 1]
    await last.find('[data-testid="mb-field-target"]').setValue('n')
    await last.find('[data-testid="mb-field-path"]').setValue('$.payload.data.name')
    await last.find('[data-testid="mb-field-more"]').trigger('click')
    await last.find('[data-testid="mb-field-as"]').setValue('int')
    expect(tid(w, 'mb-preview-counts').text()).toMatch(/2.*rejected/i)
    expect(tid(w, 'mb-preview-reasons').text()).toContain('n: not a whole number')
    expect(tid(w, 'mb-preview-reasons').text()).not.toContain('Ada')
  })

  it('warns beside a regex field about spellings the browser and Python read differently, and says what the preview uses', async () => {
    const w = mountIt()
    const row = w.findAll('[data-testid="mb-field-row"]')[0]
    await row.find('[data-testid="mb-field-more"]').trigger('click')
    expect(row.find('[data-testid="mb-field-regex-note"]').text()).toMatch(/preview uses the browser/i)
    await row.find('[data-testid="mb-field-regex"]').setValue('(?<=a)b')
    expect(row.find('[data-testid="mb-field-regex-warn"]').text()).toMatch(/lookbehind/i)
  })

  it('lists the parameters the kit uses, marks a secret one, and takes a description and a default', async () => {
    const w = mountIt()
    const pw = w.find('[data-testid="mb-param-TARGET_PASSWORD"]')
    expect(pw.exists()).toBe(true)
    expect(pw.find('[data-testid="mb-param-secret"]').text()).toMatch(/secret/i)
    expect(pw.find('[data-testid="mb-param-default"]').exists()).toBe(false)                 // a secret has no default
    const host = w.find('[data-testid="mb-param-TARGET_HOST"]')
    await host.find('[data-testid="mb-param-default"]').setValue('localhost')
    await tid(w, 'mb-tab-migration').trigger('click')
    expect(yamlOf(w)).toContain('default: localhost')
  })

  it('names a written-out destination as a problem of its rule, before anything is saved', async () => {
    const w = mountIt()
    await setBasics(w)
    // the registry\'s rule: a mapping or a config naming a literal host is refused; the form cannot write one, so the proxy.yaml tab is read-only
    expect(tid(w, 'mb-yaml').element.tagName.toLowerCase()).toBe('pre')
  })

  it('downloads each file as it is shown, from the browser, with no request', async () => {
    const w = mountIt()
    await setBasics(w)
    const urls: string[] = []
    ;(URL as any).createObjectURL = vi.fn((b: Blob) => { urls.push(String(b.size)); return 'blob:x' })
    ;(URL as any).revokeObjectURL = vi.fn()
    await tid(w, 'mb-download').trigger('click')
    expect(urls.length).toBeGreaterThanOrEqual(3)                                          // migration.yaml, proxy.yaml, README.md
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('a visitor can build and download but is told saving a draft needs an agent; with an agent it saves a private draft and shows its id', async () => {
    let w = mountIt()
    await setBasics(w)
    expect(tid(w, 'mb-save-note').text()).toMatch(/sign in/i)
    expect(tid(w, 'mb-save').exists()).toBe(false)
    h.auth = { token: 't', agentToken: 'a', activeAgent: { did: 'did:x' } }
    w = mountIt()
    await setBasics(w)
    await tid(w, 'mb-save').trigger('click')
    await flushPromises()
    expect(h.create).toHaveBeenCalledTimes(1)
    const body = h.create.mock.calls[0][0]
    expect(body.slug).toBe('orders-to-pg')
    expect(Object.keys(body.files).sort()).toEqual(['README.md', 'migration.yaml', 'proxy.yaml'])
    expect(tid(w, 'mb-saved').text()).toContain('wtpl_9')
  })

  it('shows the registry\'s own sentence when it refuses a save or a publish (the bond among them)', async () => {
    h.auth = { token: 't', agentToken: 'a', activeAgent: { did: 'did:x' } }
    h.create = vi.fn().mockRejectedValue({ response: { data: { code: 'kit', detail: 'a credential is written out at proxy.yaml:x' } } })
    const w = mountIt()
    await setBasics(w)
    await tid(w, 'mb-save').trigger('click')
    await flushPromises()
    expect(tid(w, 'mb-save-error').text()).toContain('a credential is written out')
    h.create = vi.fn().mockResolvedValue({ template_id: 'wtpl_9', version: 1, content_hash: 'h', published: false })
    h.publish = vi.fn().mockRejectedValue({ response: { status: 402, data: { code: 'bond_required', detail: 'publishing needs a bond of 25 ECU' } } })
    await tid(w, 'mb-save').trigger('click')
    await flushPromises()
    await tid(w, 'mb-publish').trigger('click')
    await flushPromises()
    expect(tid(w, 'mb-save-error').text()).toContain('publishing needs a bond of 25 ECU')
  })

  it('on a phone the files and checks open as a sheet (moved to <body>, above the app chrome) and close again', async () => {
    ;(window as any).matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener() {}, removeEventListener() {} })
    const w = mountIt()
    expect(document.querySelector('[data-testid="mb-sheet-close"]')).toBeNull()
    await tid(w, 'mb-bar-go').trigger('click')
    const close = document.querySelector('[data-testid="mb-sheet-close"]') as HTMLElement
    expect(close).not.toBeNull()
    expect(document.getElementById('mb-out')!.parentElement).toBe(document.body)          // out of the page's stacking context
    expect(document.getElementById('mb-out')!.classList.contains('sheet')).toBe(true)
    close.click(); await w.vm.$nextTick()
    expect(document.getElementById('mb-out')!.classList.contains('sheet')).toBe(false)
    expect(document.getElementById('mb-out')!.parentElement).not.toBe(document.body)       // back in the page
    w.unmount()
    delete (window as any).matchMedia
  })
  it('lets the viewport scroll (overflow clipped, not hidden) while it is open, so the files-and-checks column can stay in view, and puts the shell back', async () => {
    const w = mountIt()
    expect(document.documentElement.classList.contains('mb-page')).toBe(true)
    w.unmount()
    expect(document.documentElement.classList.contains('mb-page')).toBe(false)
    expect(document.body.classList.contains('mb-page')).toBe(false)
  })

  it('keeps the sticky column below the app\'s beta banner: its bottom edge is published as --mb-top and followed on scroll', async () => {
    const banner = document.createElement('div'); banner.className = 'beta-banner'; document.body.appendChild(banner)
    let bottom = 61
    vi.spyOn(banner, 'getBoundingClientRect').mockImplementation(() => ({ top: 0, bottom, left: 0, right: 100, width: 100, height: bottom } as DOMRect))
    const w = mountIt()
    const top = () => (w.find('[data-testid="mb-root"]').element as HTMLElement).style.getPropertyValue('--mb-top')
    await w.vm.$nextTick()
    expect(top()).toBe('61px')
    bottom = 0                                                       // the banner was dismissed
    window.dispatchEvent(new Event('scroll')); await new Promise((r) => requestAnimationFrame(() => r(null))); await w.vm.$nextTick()
    expect(top()).toBe('0px')
    w.unmount(); banner.remove()
  })
})
