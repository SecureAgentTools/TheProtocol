// V0664 C3 (order gwo_4110e12c11a69a93de878829): #/proxy, the overview. Public and makes no request: everything is the SDK's,
// generated into the console.
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: api }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({
  t: (_k: string, f?: string) => f ?? _k,
  tp: (_k: string, f: string, p: Record<string, unknown> = {}) => f.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? '')),
}) }))

import ProxyView from './ProxyView.vue'

const stubs = { Icon: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
const mountIt = () => mount(ProxyView, { global: { stubs } })


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

describe('the proxy overview', () => {
  it('offers both paths: build a spec, or migrate off the system', () => {
    const w = mountIt()
    expect(JSON.parse(w.find('[data-testid=px-to-builder]').attributes('data-to')!)).toEqual({ name: 'proxy-new' })
    expect(JSON.parse(w.find('[data-testid=px-to-migrate]').attributes('data-to')!)).toEqual({ name: 'migrate' })
    expect(api.get).not.toHaveBeenCalled()
  })

  it('installs the SDK from PyPI and names the three commands', () => {
    const code = mountIt().find('[data-testid=px-install-code]').text()
    expect(code).toContain('pip install "theprotocol-sdk[proxy]"')          // pass 2: 0.8.0 on PyPI carries the proxy
    expect(code).not.toContain('./theprotocol-sdk')
    expect(code).toContain('tp-proxy validate proxy.yaml')
    expect(code).toContain('tp-proxy run proxy.yaml --dry-run --once')
  })

  it('lists the connectors by role, each with its fields, and marks a credential field', async () => {
    const w = mountIt()
    expect(w.find('[data-testid=px-plugin-source-filedrop]').exists()).toBe(true)
    expect(w.find('[data-testid=px-plugin-source-migrate_sample]').exists()).toBe(false)     // internal: never offered
    await w.find('[data-testid=px-role-sink]').trigger('click')
    const rest = w.find('[data-testid=px-plugin-sink-rest]')
    expect(rest.exists()).toBe(true)
    expect(rest.text()).toContain('bearer')
    expect(rest.find('.px-tag-secret').exists()).toBe(true)
    await w.find('[data-testid=px-role-action]').trigger('click')
    expect(w.find('[data-testid=px-plugin-action-attestation]').exists()).toBe(true)
  })

  it('shows the eight recipes, each with its blueprint, its commands and its spec', () => {
    const w = mountIt()
    for (const id of ['bazaar', 'dynamo', 'hansa', 'keystone', 'lyceum', 'meridian', 'scrivener', 'trunk']) {
      expect(w.find(`[data-testid=px-recipe-${id}]`).exists(), id).toBe(true)
      expect(JSON.parse(w.find(`[data-testid=px-recipe-bp-${id}]`).attributes('data-to')!)).toEqual({ name: 'blueprint-detail', params: { id } })
      expect(w.find(`[data-testid=px-recipe-cmds-${id}]`).text()).toMatch(/^tp-proxy validate/)
      expect(w.find(`[data-testid=px-recipe-yaml-${id}]`).text()).toContain('version: 1')
    }
  })

  it('shows a recipe\'s inline code as code, never as HTML', () => {
    const lyceum = mountIt().find('[data-testid=px-recipe-lyceum]')
    expect(lyceum.findAll('code').some((c) => c.text() === 'attestor')).toBe(true)
    expect(lyceum.html()).not.toContain('`attestor`')
  })

  it('every code box is reachable by keyboard and named: the install, each recipe\'s commands and spec (proof seq 4206)', () => {
    codeBoxesReachable(mountIt())
  })
})
