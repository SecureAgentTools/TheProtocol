/**
 * D6-257: a callout written with either renderer's name shows as a callout. The console knew tip / warn / info / note,
 * the docs site (VitePress) knows info / tip / warning / danger, and a `::: warning` page printed its literal line here.
 */
import { describe, it, expect } from 'vitest'
import { renderDocsMarkdown } from './useDocsMarkdown'

describe('callouts', () => {
  it.each([
    ['tip', 'tip', 'Tip'],
    ['warn', 'warn', 'Warning'],
    ['info', 'info', 'Info'],
    ['note', 'note', 'Note'],
    ['warning', 'warn', 'Warning'],
    ['danger', 'warn', 'Danger'],
  ])('::: %s renders as a %s callout', (kind, cls, label) => {
    const html = renderDocsMarkdown(`::: ${kind}\nBody text.\n:::\n`, { classPrefix: 'orc' })
    expect(html).toContain(`orc-callout orc-callout-${cls}"`)
    expect(html).toContain(`>${label}</span>`)
    expect(html).toContain('Body text.')
    expect(html).not.toContain(':::')
  })

  it('keeps an inline title', () => {
    const html = renderDocsMarkdown('::: warning Never bypass the ledger\nBody.\n:::\n', { classPrefix: 'opd' })
    expect(html).toContain('opd-callout opd-callout-warn"')
    expect(html).toContain('>Never bypass the ledger</span>')
  })
})
