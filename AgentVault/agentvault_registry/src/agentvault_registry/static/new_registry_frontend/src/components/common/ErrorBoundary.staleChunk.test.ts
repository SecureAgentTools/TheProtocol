/**
 * §FESUITE (2026-10-10): a component whose chunk cannot load. V0590's deployed proof (the console suite's recovery sweep)
 * saw the quick-create sheet's import fail and the console's error boundary keep its panel ("Failed to fetch dynamically
 * imported module") until a reload, while the router reloads by itself for a view's stale chunk. The boundary gives a
 * component's the same answer (services/staleChunk.ts): reload, and the panel only once the reloads are spent.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import ErrorBoundary from './ErrorBoundary.vue'
import { RELOAD_GUARD_KEY } from '@/services/staleChunk'

let reload: ReturnType<typeof vi.fn>
const realLocation = window.location
beforeEach(() => {
  sessionStorage.clear()
  document.getElementById('cc-update-banner')?.remove()
  reload = vi.fn()
  Object.defineProperty(window, 'location', { configurable: true, value: { ...realLocation, reload } })
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation })
  vi.restoreAllMocks()
})

const STALE = 'Failed to fetch dynamically imported module: https://sandbox-b.theprotocol.cloud/assets/QuickAgentModal-CEQ_O0fK.js'
function boundaryAround(message: string) {
  const Boom = defineComponent({ setup() { throw new TypeError(message) } })
  return mount(defineComponent({ render: () => h(ErrorBoundary, null, { default: () => h(Boom) }) }))
}

describe('the error boundary and a chunk that cannot load', () => {
  it('reloads for a fresh bundle instead of showing its panel', async () => {
    const w = boundaryAround(STALE)
    await flushPromises()
    expect(w.find('[data-testid="error-boundary"]').exists(), 'the panel over a stale chunk').toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(RELOAD_GUARD_KEY)).toBe('1')
  })

  it('once the reloads are spent: the panel and the reload banner', async () => {
    sessionStorage.setItem(RELOAD_GUARD_KEY, '2')
    const w = boundaryAround(STALE)
    await flushPromises()
    expect(w.find('[data-testid="error-boundary"]').exists()).toBe(true)
    expect(document.getElementById('cc-update-banner')).not.toBeNull()
    expect(reload).not.toHaveBeenCalled()
  })

  it('any other error is the panel, as before (no reload)', async () => {
    const w = boundaryAround('Request failed with status code 502')
    await flushPromises()
    expect(w.find('[data-testid="error-boundary"]').exists()).toBe(true)
    expect(reload).not.toHaveBeenCalled()
  })
})
