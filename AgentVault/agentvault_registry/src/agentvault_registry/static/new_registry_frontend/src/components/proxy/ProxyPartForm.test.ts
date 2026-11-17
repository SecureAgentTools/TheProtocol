// V0664 C3 (order gwo_4110e12c11a69a93de878829), pass 1 D7: a connector's settings, the ones that matter first. Required fields
// and credentials are always shown; every other setting folds behind one button that says how many there are, and a setting
// that already holds a value is never hidden.
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({
  t: (_k: string, f?: string) => f ?? _k,
  tp: (_k: string, f: string, p: Record<string, unknown> = {}) => f.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? '')),
}) }))

import ProxyPartForm from './ProxyPartForm.vue'

const SCHEMA = {
  type: 'object', required: ['url'],
  properties: {
    url: { type: 'string', description: 'Where it posts.' },
    bearer: { type: 'string', 'x-secret': true },
    method: { enum: ['POST', 'PUT'] },
    timeout_s: { type: 'number' },
    headers: { type: 'object' },
  },
}
const shown = (w: any, key: string) => w.find(`[data-testid=ppf-sink-erp-${key}]`).exists()

describe('a connector\'s settings', () => {
  it('shows the required fields and the credentials, and folds the rest behind a count', async () => {
    const w = mount(ProxyPartForm, { props: { schema: SCHEMA, config: {}, prefix: 'sink-erp' } })
    expect(shown(w, 'url')).toBe(true)
    expect(shown(w, 'bearer')).toBe(true)
    expect(shown(w, 'method')).toBe(false)
    expect(shown(w, 'timeout_s')).toBe(false)
    const more = w.find('[data-testid=ppf-sink-erp-more]')
    expect(more.text()).toBe('3 more settings')
    expect(more.attributes('aria-expanded')).toBe('false')
    await more.trigger('click')
    expect(shown(w, 'method')).toBe(true)
    expect(shown(w, 'headers')).toBe(true)
    expect(w.find('[data-testid=ppf-sink-erp-more]').text()).toBe('Fewer settings')
  })

  it('never hides a setting that holds a value', () => {
    const w = mount(ProxyPartForm, { props: { schema: SCHEMA, config: { timeout_s: 5 }, prefix: 'sink-erp' } })
    expect(shown(w, 'timeout_s')).toBe(true)
    expect(shown(w, 'method')).toBe(false)
    expect(w.find('[data-testid=ppf-sink-erp-more]').text()).toBe('2 more settings')
  })

  it('has no fold when there is nothing to fold', () => {
    const w = mount(ProxyPartForm, { props: { schema: { type: 'object', required: ['a'], properties: { a: { type: 'string' } } }, config: {}, prefix: 'x' } })
    expect(w.find('[data-testid=ppf-x-more]').exists()).toBe(false)
  })
})

// pass 2 (session-lead seq 4069)
const IDENTITY = {
  type: 'object', required: ['agent_did'],
  properties: { agent_did: { type: 'string' }, mtls: { type: 'object', additionalProperties: false, properties: { dir: { type: 'string' }, enabled: { type: 'boolean' } } } },
}
describe('a connector\'s settings, pass 2', () => {
  it('a label in words with the key beside it, small', () => {
    const w = mount(ProxyPartForm, { props: { schema: IDENTITY, config: {}, prefix: 'identity' } })
    const label = w.find('label[for=ppf-identity-agent_did]')
    expect(label.find('.ppf-words').text()).toBe('Agent DID')
    expect(label.find('code').text()).toBe('agent_did')
  })

  it('mTLS is a switch, and its folder asked only once it is on; nothing is written while both are empty', async () => {
    const config: Record<string, any> = {}
    const w = mount(ProxyPartForm, { props: { schema: IDENTITY, config, prefix: 'identity' } })
    await w.find('[data-testid=ppf-identity-more]').trigger('click')
    expect(w.find('textarea').exists()).toBe(false)
    expect(w.find('[data-testid=ppf-identity-mtls-dir]').exists()).toBe(false)
    await w.find('[data-testid=ppf-identity-mtls-enabled]').setValue(true)
    expect(config.mtls).toEqual({ enabled: true })
    await w.find('[data-testid=ppf-identity-mtls-dir]').setValue('/certs')
    expect(config.mtls).toEqual({ enabled: true, dir: '/certs' })
    await w.find('[data-testid=ppf-identity-mtls-dir]').setValue('')
    await w.find('[data-testid=ppf-identity-mtls-enabled]').setValue(false)
    expect('mtls' in config).toBe(false)
  })

  it('a list of text is one item a line', async () => {
    const config: Record<string, any> = {}
    const w = mount(ProxyPartForm, { props: { schema: { type: 'object', required: ['to'], properties: { to: { type: 'array', items: { type: 'string' } } } }, config, prefix: 'sink-mail' } })
    await w.find('[data-testid=ppf-sink-mail-to]').setValue('ops@example.org\n  \nfinance@example.org ')
    expect(config.to).toEqual(['ops@example.org', 'finance@example.org'])
    await w.find('[data-testid=ppf-sink-mail-to]').setValue('')
    expect('to' in config).toBe(false)
  })

  it('a map of text is a name: value line each, and a line without a colon is named', async () => {
    const config: Record<string, any> = {}
    const w = mount(ProxyPartForm, { props: { schema: { type: 'object', required: ['headers'], properties: { headers: { type: 'object', additionalProperties: { type: 'string' } } } }, config, prefix: 'sink-erp' } })
    await w.find('[data-testid=ppf-sink-erp-headers]').setValue('X-Tenant: acme\nAuthorization: env:ERP_AUTH')
    expect(config.headers).toEqual({ 'X-Tenant': 'acme', Authorization: 'env:ERP_AUTH' })
    await w.find('[data-testid=ppf-sink-erp-headers]').setValue('X-Tenant acme')
    expect(w.find('[data-testid=ppf-sink-erp-headers-bad]').text()).toContain('Name: value')
  })

  it('JSON only for a setting with no fixed shape, and it says so', () => {
    const w = mount(ProxyPartForm, { props: { schema: { type: 'object', required: ['backend'], properties: { backend: { type: 'object' } } }, config: {}, prefix: 'sink-q' } })
    expect(w.find('[data-testid=ppf-sink-q-backend-json]').text()).toContain('JSON')
  })
})

describe('a connector\'s settings, pass 2 shots', () => {
  it('a choice nobody made reads not set, not an empty box', async () => {
    const config: Record<string, any> = {}
    const w = mount(ProxyPartForm, { props: { schema: { type: 'object', required: ['method'], properties: { method: { enum: ['POST', 'PUT'] } } }, config, prefix: 's' } })
    const sel = w.find('[data-testid=ppf-s-method]').element as HTMLSelectElement
    expect(sel.selectedIndex).toBe(0)
    expect(sel.options[0]!.text).toBe('not set')
    // a browser selects the option whose value is the select's value ('' when nothing is set); an option bound to undefined
    // takes its text as its value, so no option matched and the box showed empty (pass 2's Method and Format)
    expect(sel.options[0]!.value).toBe('')
    expect(sel.value).toBe('')
    await w.find('[data-testid=ppf-s-method]').setValue('PUT')
    expect(config.method).toBe('PUT')
  })
})
