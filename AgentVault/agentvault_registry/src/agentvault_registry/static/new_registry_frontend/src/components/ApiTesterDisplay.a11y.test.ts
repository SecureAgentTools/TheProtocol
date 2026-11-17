/**
 * V0662 (the API tester page, gwo_25a14d9bcd1faa0d28260073): the fixed admin sweep found 145 buttons with no accessible
 * name on /api-tester (critical; every endpoint's test button holds only an icon), a heading level skipped (h1 straight to
 * h3), and the console's value word "token" in the page's own text. Mounted for real here: every button has a name that
 * says what it does, the headings step one level at a time, and the page calls its credentials access keys.
 * BASE: the test buttons answer with no name, the first section heading is an h3, and the labels read "Developer Token".
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ApiTesterDisplay from './ApiTesterDisplay.vue'

const ENDPOINTS = {
  agents: [
    { method: 'GET', path: '/agents/{agent_did}', auth: 'agent', description: 'One agent' },
    { method: 'POST', path: '/agents/spawn', auth: 'agent', description: 'Spawn a sub-agent' },
  ],
}

async function mounted() {
  const w = mount(ApiTesterDisplay, {
    props: {
      endpoints: ENDPOINTS as any, selectedCategory: 'agents', testingCategory: false, runningAllTests: false,
      developerToken: 'dev-credential-0000000000000000', agentToken: 'agent-credential-000000000000', agentStatus: ' (active)',
    },
  })
  await w.vm.$nextTick()
  return w
}

const accessibleName = (el: Element) =>
  (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim()

describe('the API tester page, mounted', () => {
  it('names every button by what it does, the endpoint test buttons by the call they run', async () => {
    const w = await mounted()
    const tests = w.findAll('button.test-button')
    expect(tests.length).toBe(2)
    expect(tests.map((b) => b.attributes('aria-label'))).toEqual(['Test GET /agents/{agent_did}', 'Test POST /agents/spawn'])
    for (const b of w.findAll('button')) expect(accessibleName(b.element), b.html().slice(0, 120)).not.toBe('')
  })

  it('steps the headings one level at a time, from the page title', async () => {
    const w = await mounted()
    const levels = w.findAll('h1, h2, h3, h4, h5, h6').map((h) => Number(h.element.tagName[1]))
    expect(levels[0]).toBe(1)
    for (let i = 1; i < levels.length; i++) expect(levels[i] - levels[i - 1], `heading ${i} (levels ${levels.join('')})`).toBeLessThanOrEqual(1)
  })

  it('says access key for the credentials, and shows no "token" word of its own', async () => {
    const w = await mounted()
    const labels = w.findAll('.field-label').map((l) => l.text())
    expect(labels).toEqual(['Developer access key', 'Agent access key (active)'])
    const own = w.findAll('button').map((b) => (b.attributes('title') || '') + ' ' + (b.attributes('aria-label') || ''))
      .concat(w.findAll('.field-label, .arch-value').map((e) => e.text()))
    expect(own.join(' ')).not.toMatch(/\btokens?\b/i)
  })
})
