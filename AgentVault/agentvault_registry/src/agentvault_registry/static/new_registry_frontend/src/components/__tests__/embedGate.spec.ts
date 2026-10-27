/**
 * §EMBEDGATE-3 — the landing globe must hand its modal a DID, and the modal must never render an
 * unnamed empty state.
 *
 * WHY THIS FILE EXISTS. `embedded` gated behaviour in FOUR places. I fixed the three inside
 * `AgentDetailModal`, verified on `/explore` — which passes a real DID and therefore never
 * exercised the fourth — and reported the globe as fixed. His answer: "i clicked it it doesnt open.
 * shows modal but empty with close button." A control drawn from a sibling that was already working
 * proves nothing about the path that was broken.
 *
 * These are SOURCE assertions on purpose: the globe is a Cesium view on the do-not-Playwright list
 * (headless falls back to swiftshader and hangs), so the behavioural half can only be driven by a
 * person. What can be pinned mechanically is the shape of the rules — and every one of these failed
 * before the fix.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
/** ⚠ STRIP COMMENTS FIRST. A SOURCE-READING GATE FINDS ITS OWN DOCUMENTATION.
 *  The first run of this file failed on `v-else-if="embedded"` — matching the sentence in
 *  `AgentDetailModal` that QUOTES the removed branch to explain why it went. Fourth instance of
 *  this class in the tree (§JSONCAST-3, §EMITKEY, and the mTLS census earlier today): prose next
 *  to a rule names the CLASS, and a gate that reads prose is measuring the explanation. */
const code = (t: string) =>
  t.replace(/<!--[\s\S]*?-->/g, '')      // template comments
   .replace(/\/\*[\s\S]*?\*\//g, '')      // block comments
   .replace(/^\s*\/\/.*$/gm, '')         // line comments
   .replace(/^\s*\*.*$/gm, '')            // jsdoc continuation lines

const globe = code(readFileSync(resolve(SRC, 'views/AgentWorldCesium.vue'), 'utf8'))
const modal = code(readFileSync(resolve(SRC, 'components/AgentDetailModal.vue'), 'utf8'))

describe('§EMBEDGATE-3 — the embedded globe opens a real card', () => {
  it('does not blank the modal DID when embedded', () => {
    const line = globe.split('\n').find(l => l.includes('const agentModalDid'))
    expect(line, 'agentModalDid computed must exist').toBeTruthy()
    // THE DEFECT, exactly: `props.embedded ? '' : (selectedAgent.value?.did || '')`
    expect(line).not.toMatch(/embedded\s*\?/)
    expect(line).toContain('selectedAgent')
  })

  it('opens the modal on click for every viewer, embedded or not', () => {
    const open = globe.split('\n').find(l => l.includes('showAgentModal.value = true'))
    expect(open).toBeTruthy()
    expect(open).not.toMatch(/embedded/)
  })
})

describe('§EMBEDGATE — the modal gates on the viewer, not the surface', () => {
  it('has no branch keyed on `embedded`', () => {
    expect(modal).not.toMatch(/v-else-if="embedded"/)
    expect(modal).not.toMatch(/v-if="embedded"/)
  })

  it('fetches whatever DID it is given, without asking which surface it is on', () => {
    expect(modal.split('\n').some(l => l.includes('await loadAgent(newDid)'))).toBe(true)
    const cond = modal.split('\n').find(l => /if \(newDid/.test(l))
    expect(cond).not.toMatch(/props\.embedded/)
  })

  it('hides the requiresAuth door by SESSION, never by surface', () => {
    const i = modal.indexOf('const fullAgentHref')
    const body = modal.slice(i, i + 260)
    expect(body).toContain('hasSession')
    expect(body).not.toContain('props.embedded')
  })

  it('names the fourth state instead of rendering a blank shell', () => {
    expect(modal).toMatch(/v-else class="adm-empty"/)
    expect(modal).toContain('data-testid="adm-empty"')
  })
})

describe('§EMBEDGATE-2 — a public page asks no member questions', () => {
  it('skips the agent-metadata merge without a session, BEFORE the request', () => {
    const svc = code(readFileSync(resolve(SRC, 'services/api/discovery.ts'), 'utf8'))
    const i = svc.indexOf('async fetchAgentMetadata')
    const body = svc.slice(i, i + 2200)
    expect(body).toContain('authService.getAccessToken()')
    expect(body.indexOf('authService.getAccessToken()'))
      .toBeLessThan(body.indexOf("apiClient.get('/developers/me/agents')"))
  })
})
