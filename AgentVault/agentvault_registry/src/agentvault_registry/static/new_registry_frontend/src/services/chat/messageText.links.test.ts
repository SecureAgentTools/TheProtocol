import { afterEach, describe, expect, it, vi } from 'vitest'
import DOMPurify from 'dompurify'
import { renderMarkdown, URI_SAFE_ATTR } from './messageText'

/**
 * V0652 (x) (order gwo_cedd900e6d50be18ce4eecf1; session-tester's check 142, the sessions' room seq 616-619): a link in a
 * message opens beside the console. The link rule writes target="_blank" and rel="noopener ...", and DOMPurify, in a real
 * browser, also tested those two values against the module's URI rule (they are not on its URI-safe list): both failed it
 * and were dropped, so a link opened over the console. jsdom keeps them, which is why messageText.test.ts's link case
 * passed and could not see it; the behaviour is checked in Chromium (scratchpad v0652 link drive, and check 142). Here: the
 * renderer hands DOMPurify both names as URI-safe, and still the URI rule for href. BASE (5ee11040b): no such option.
 */
describe('a link keeps target and rel through the sanitizer', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('the sanitizer is told target and rel are not URIs, and href still answers the URI rule', () => {
    const spy = vi.spyOn(DOMPurify, 'sanitize')
    renderMarkdown('see [the docs](https://docs.theprotocol.cloud/x)')
    const cfg = spy.mock.calls[0][1] as Record<string, unknown>
    expect(cfg.ADD_URI_SAFE_ATTR).toEqual(['target', 'rel'])
    expect(URI_SAFE_ATTR).toEqual(['target', 'rel'])
    expect(String(cfg.ALLOWED_URI_REGEXP)).toBe('/^(?:https?:|mailto:|#|\\/)/i')
    expect(cfg.ADD_URI_SAFE_ATTR).not.toContain('href')
  })

  it('control: a javascript: link is still no link (its words stay text)', () => {
    for (const body of ['[x](javascript:alert(1))', '<javascript:alert(1)>', '[x](JaVaScRiPt:alert(1))']) {
      const h = renderMarkdown(body)
      expect(h).not.toMatch(/href\s*=\s*["']?\s*javascript:/i)
      expect(h).not.toMatch(/<a\b/)
    }
  })
})
