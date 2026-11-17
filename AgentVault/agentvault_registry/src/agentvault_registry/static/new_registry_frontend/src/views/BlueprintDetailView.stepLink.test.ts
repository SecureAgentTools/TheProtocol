/**
 * V0662 (order gwo_16d8fb21303f269406eb772f, his suggestion 4): a link to a blueprint step. Each step of a blueprint's
 * plan has its own address (#/blueprints/<id>?step=<n>) and a button that copies it; a link followed brings that step
 * into view and marks it, on arrival and when the step changes while the page is open (vue-router keeps the view on a
 * query-only change: CLAUDE.md, the second arrival). Red on f569f6a6e: no step address, no copy, no mark.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ route: null as any }))
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ params: { id: 'meridian' }, query: {} as Record<string, string> })
  return { useRoute: () => h.route, useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }
})

import BlueprintDetailView from './BlueprintDetailView.vue'

const CopyStub = { name: 'CopyButton', props: ['value', 'what'], template: '<button type="button" class="copy-stub" />' }
const opts = { global: { stubs: { BlueprintSection: true, ArchLoom: true, 'router-link': true, RouterLink: true, CopyButton: CopyStub } } }
/** Wait for the outcome, not for a number of ticks: the view loads its blueprint through a dynamic import, which takes
 *  more than six ticks on a busy machine (it read 0 steps in a full console run under load). Gives up after `ms`, and
 *  the assertions after it then fail as before. */
const until = async (ok: () => boolean, ms = 10_000) => {
  const end = Date.now() + ms
  while (!ok() && Date.now() < end) { await new Promise((r) => setTimeout(r, 10)); await flushPromises() }
}

describe('a link to a blueprint step', () => {
  beforeEach(() => {
    h.route.query = {}
    ;(Element.prototype as any).scrollIntoView = vi.fn()
    ;(window as any).scrollTo = vi.fn()
  })

  it('each step has its address and a button that copies it', async () => {
    const w = mount(BlueprintDetailView, opts)
    try {
      await until(() => w.findAll('article.bpd-phase').length >= 3)
      const steps = w.findAll('article.bpd-phase')
      expect(steps.length).toBeGreaterThanOrEqual(3)
      steps.forEach((s, i) => expect(s.attributes('id')).toBe(`bp-step-${i}`))
      const copies = w.findAllComponents({ name: 'CopyButton' }).filter((c) => String(c.attributes('data-testid') || '').startsWith('bpd-copy-step-'))
      expect(copies.length).toBe(steps.length)
      expect(copies[1].props('value')).toBe(`${window.location.origin}${window.location.pathname}#/blueprints/meridian?step=1`)
    } finally { w.unmount() }
  })

  it('a followed link brings its step into view and marks it, on arrival and on a later step', async () => {
    h.route.query = { step: '2' }
    const w = mount(BlueprintDetailView, opts)
    try {
      const marked = () => w.findAll('article.bpd-phase').map((s) => s.attributes('aria-current') === 'step')
      await until(() => marked()[2] === true && (Element.prototype as any).scrollIntoView.mock.calls.length > 0)
      expect(marked()[2]).toBe(true)
      expect(marked().filter(Boolean).length).toBe(1)
      expect((Element.prototype as any).scrollIntoView).toHaveBeenCalled()
      h.route.query = { step: '1' }
      await until(() => marked()[1] === true)
      expect(marked()[1]).toBe(true)
      expect(marked()[2]).toBe(false)
    } finally { w.unmount() }
  })
})
