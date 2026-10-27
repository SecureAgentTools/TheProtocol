/**
 * §FESUITE (2026-10-10): one answer to a chunk the console cannot load, for the router (a view) and the error boundary
 * (a component imported later): clear the asset cache and reload, at most twice in a row this session, then the visible
 * reload banner. Moved from router/index.ts unchanged; these pin the decision.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RELOAD_GUARD_KEY, isStaleChunkError, recoverFromStaleChunk, staleChunkRecovered } from './staleChunk'

let reload: ReturnType<typeof vi.fn>
const realLocation = window.location
beforeEach(() => {
  sessionStorage.clear()
  document.getElementById('cc-update-banner')?.remove()
  reload = vi.fn()
  Object.defineProperty(window, 'location', { configurable: true, value: { ...realLocation, reload } })
})
afterEach(() => { Object.defineProperty(window, 'location', { configurable: true, value: realLocation }) })

describe('a chunk the console cannot load', () => {
  it('is told by any browser\'s words, and nothing else', () => {
    for (const m of ['TypeError: Failed to fetch dynamically imported module: https://x/assets/QuickAgentModal-CEQ_O0fK.js',
      'Loading chunk 42 failed.', 'error loading dynamically imported module', 'Importing a module script failed.',
      'Loading module from "https://x/a.js" was blocked because of a disallowed MIME type ("text/html").']) {
      expect(isStaleChunkError(new TypeError(m)), m).toBe(true)
    }
    expect(isStaleChunkError('Failed to fetch dynamically imported module: y'), 'a string error too').toBe(true)
    for (const m of ['Request failed with status code 502', 'x is not a function', 'Failed to fetch']) {
      expect(isStaleChunkError(new TypeError(m)), m).toBe(false)
    }
    expect(isStaleChunkError(null)).toBe(false)
  })

  it('reloads twice in a row at most, then shows the reload banner; a clean navigation resets the count', async () => {
    expect(recoverFromStaleChunk()).toBe('reloading')
    await Promise.resolve(); await Promise.resolve()
    expect(reload).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(RELOAD_GUARD_KEY)).toBe('1')
    expect(recoverFromStaleChunk()).toBe('reloading')
    expect(sessionStorage.getItem(RELOAD_GUARD_KEY)).toBe('2')
    expect(recoverFromStaleChunk(), 'the third in a row').toBe('banner')
    expect(document.getElementById('cc-update-banner'), 'never a blank screen').not.toBeNull()
    staleChunkRecovered()
    expect(sessionStorage.getItem(RELOAD_GUARD_KEY)).toBeNull()
    expect(recoverFromStaleChunk()).toBe('reloading')
  })
})
