// V0666 (gwo_dc5050837e93b0a64d1fdae7, room seq 4404: "pypi update on landing"): the SDK's install line on the landing page
// with the version the console's catalog was made from (never a pinned literal: it moves with each release), PyPI and the
// docs' proxy chapter.
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({
  t: (_k: string, f?: string) => f ?? _k,
  tp: (_k: string, f: string, p: Record<string, unknown> = {}) => f.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? '')),
}) }))

import catalog from '@/data/proxy/catalog.generated.json'
import LandingSdkLine from './LandingSdkLine.vue'

describe('the landing page: the SDK on PyPI', () => {
  it('pip install theprotocol-sdk, the catalog\'s version (read after the page is up), PyPI and the proxy chapter', async () => {
    const w = mount(LandingSdkLine)
    // the version arrives with the catalog's own chunk: wait for it, not for a number of ticks
    await vi.waitFor(() => expect(w.find('[data-testid=lp-sdk-version]').exists()).toBe(true), { timeout: 10000 })
    expect(w.find('[data-testid=lp-sdk-pip]').text()).toBe('pip install theprotocol-sdk')
    const v = (catalog as { sdk_version: string }).sdk_version
    expect(v).toMatch(/^\d+\.\d+\.\d+$/)
    expect(w.find('[data-testid=lp-sdk-version]').text()).toBe(`v${v}`)
    expect(w.find('[data-testid=lp-sdk-pypi]').attributes('href')).toBe('https://pypi.org/project/theprotocol-sdk/')
    expect(w.find('[data-testid=lp-sdk-docs]').attributes('href')).toBe('https://docs.theprotocol.cloud/build/proxy')
  })

  it('carries no version literal of its own: the version moves with each release', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'LandingSdkLine.vue'), 'utf8')
    expect(src).not.toMatch(/\b\d+\.\d+\.\d+\b/)
  })

  it('the landing page reads its SDK badge from the catalog too, never a literal', () => {
    const page = fs.readFileSync(path.resolve(__dirname, '../../views/LandingPage.vue'), 'utf8')
    const sdk = page.slice(page.indexOf('<section class="sdk">'), page.indexOf('</section>', page.indexOf('<section class="sdk">')))
    expect(sdk).not.toMatch(/\bv\d+\.\d+\.\d+\b/)
    expect(sdk).toContain('<LandingSdkLine')
    // the catalog is read after the page is up (useSdkVersion), never in the landing chunk's first load
    expect(page).not.toMatch(/from '@\/data\/proxy\/catalog\.generated\.json'/)
  })
})
