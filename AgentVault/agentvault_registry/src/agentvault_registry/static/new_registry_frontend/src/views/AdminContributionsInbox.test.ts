/**
 * V0666 D2 (order gwo_f565ebd0575703f199dd9200): the Contributions inbox (#/admin/contributions, admin_platform). Off, one sentence and no read; on, every line's
 * changes across all organizations in one queue, newest first; the filters (organization, line, state, sensitive); the checker's record per change; a pause
 * that needs its reason and a resume; the platform maintainer's veto (with its reason) and go; a line whose changes could not be read is said, never hidden.
 * Red before D2: views/AdminContributionsInbox.vue does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ upstream: null as any, cfg: null as any, lines: null as any, changes: null as any, pause: null as any, resume: null as any, go: null as any, veto: null as any }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => h.cfg }))
vi.mock('@/services/api/codeDistributions', () => ({
  adminListLines: (...a: any[]) => h.lines(...a), listLineChanges: (...a: any[]) => h.changes(...a), adminPauseLine: (...a: any[]) => h.pause(...a),
  adminResumeLine: (...a: any[]) => h.resume(...a), maintainerGo: (...a: any[]) => h.go(...a), maintainerVeto: (...a: any[]) => h.veto(...a) }))

vi.mock('@/services/api/codeChanges', async () => {
  const real = await vi.importActual<any>('@/services/api/codeChanges')
  return { ...real, listUpstream: (...a: any[]) => h.upstream(...a) }
})

import Inbox from './AdminContributionsInbox.vue'

const LINES = [
  { slug: 'lyceum', title: 'Lyceum', organization_id: 'org-a', organization_name: 'Lyceum Labs', release_name: 'V0666_lyceum', state: 'active' },
  { slug: 'harbor', title: 'Harbor', organization_id: 'org-b', organization_name: null, release_name: 'V0666_harbor', state: 'paused', paused_reason: 'under review' },
]
const ch = (id: string, slug: string, at: string, over: Record<string, any> = {}) => ({ id, title: `Change ${id}`, state: 'proposed', created_at: at, reviews: [], sensitive: false,
  code_distribution: { slug, state: 'active' }, ...over })
const BY: Record<string, any[]> = {
  lyceum: [ch('cc_1', 'lyceum', '2026-11-14T10:00:00Z', { acceptance: { ok: false, reasons: ['secret_found'] } }),
    ch('cc_3', 'lyceum', '2026-11-15T10:00:00Z', { state: 'passed', sensitive: true, veto_window_closes_at: '2099-01-01T00:00:00Z' })],
  harbor: [ch('cc_2', 'harbor', '2026-11-14T12:00:00Z', { state: 'failed', line_ballot: { result: { status: 'FAILED', sentence: 'the line has no deciders at the close, so nobody decided: the change fails' } } })],
}
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const ids = (w: any) => w.findAll('[data-testid^="cti-row-"]').map((x: any) => x.attributes('data-testid').replace('cti-row-', ''))
const mountIt = () => mount(Inbox, { global: { stubs: { RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
const setCfg = (on: boolean) => { h.cfg = { codeDistributionsEnabled: ref(on), loaded: ref(true), readFailed: ref(false), reload: vi.fn(), load: vi.fn().mockResolvedValue({}) } }

describe('the Contributions inbox', () => {
  beforeEach(() => {
    setCfg(true)
    h.lines = vi.fn().mockResolvedValue(LINES.map((l) => ({ ...l })))
    h.changes = vi.fn().mockImplementation(async (slug: string) => BY[slug] || [])
    h.pause = vi.fn(); h.resume = vi.fn(); h.go = vi.fn(); h.veto = vi.fn(); h.upstream = vi.fn().mockResolvedValue([])
  })

  it('says in one sentence that code distributions are off, and reads nothing', async () => {
    setCfg(false)
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cti-off').text()).toBe('Code distributions are off on this registry.')
    expect(h.lines).not.toHaveBeenCalled()
  })

  it('puts every line\'s changes in one queue, newest first, with the checker\'s record; the failed one is kept and said as failed', async () => {
    const w = mountIt(); await flushPromises()
    expect(ids(w)).toEqual(['cc_3', 'cc_2', 'cc_1'])
    expect(tid(w, 'cti-row-cc_1').find('[data-testid="cti-checker"]').text()).toContain('secret_found')
    expect(tid(w, 'cti-row-cc_2').find('[data-testid="cti-ballot"]').text()).toMatch(/^Failed: the line has no deciders/)
    expect(tid(w, 'cti-line-harbor').find('[data-testid="cti-paused"]').exists()).toBe(true)
    const html = w.html()
    expect(html.indexOf('data-testid="cti-queue"')).toBeLessThan(html.indexOf('data-testid="cti-lines"'))   // the queue is what arrives: it comes first
    expect(tid(w, 'cti-row-cc_3').find('.cti-tag').text()).toBe('Passed')
    expect(tid(w, 'cti-row-cc_2').find('[data-testid="cti-line-paused-tag"]').text()).toBe('Line paused')     // pass 2: a row on a paused line says so
    expect(tid(w, 'cti-row-cc_3').find('[data-testid="cti-line-paused-tag"]').exists()).toBe(false)
  })

  it('filters by organization, line, state and sensitive', async () => {
    const w = mountIt(); await flushPromises()
    await tid(w, 'cti-f-org').setValue('org-b'); expect(ids(w)).toEqual(['cc_2'])
    await tid(w, 'cti-f-org').setValue(''); await tid(w, 'cti-f-line').setValue('lyceum'); expect(ids(w)).toEqual(['cc_3', 'cc_1'])
    await tid(w, 'cti-f-state').setValue('passed'); expect(ids(w)).toEqual(['cc_3'])
    await tid(w, 'cti-f-state').setValue(''); await tid(w, 'cti-f-sensitive').setValue('no'); expect(ids(w)).toEqual(['cc_1'])
    await tid(w, 'cti-f-line').setValue('harbor'); await tid(w, 'cti-f-sensitive').setValue('yes')
    expect(tid(w, 'cti-none-here').exists()).toBe(true)
  })

  it('pauses a line only with a reason, and resumes a paused one', async () => {
    h.pause = vi.fn().mockResolvedValue({ ...LINES[0], state: 'paused', paused_reason: 'a vote is being bought' })
    h.resume = vi.fn().mockResolvedValue({ ...LINES[1], state: 'active', paused_reason: null })
    const w = mountIt(); await flushPromises()
    await tid(w, 'cti-line-lyceum').find('[data-testid="cti-pause"]').trigger('click')
    await tid(w, 'cti-pause-confirm').trigger('click'); await flushPromises()
    expect(h.pause).not.toHaveBeenCalled()
    expect(tid(w, 'cti-pause-problem').text()).toMatch(/Say why/)
    await tid(w, 'cti-pause-reason').setValue('a vote is being bought')
    await tid(w, 'cti-pause-confirm').trigger('click'); await flushPromises()
    expect(h.pause).toHaveBeenCalledWith('lyceum', 'a vote is being bought')
    expect(tid(w, 'cti-line-lyceum').attributes('data-state')).toBe('paused')
    await tid(w, 'cti-line-harbor').find('[data-testid="cti-resume"]').trigger('click'); await flushPromises()
    expect(h.resume).toHaveBeenCalledWith('harbor')
    expect(tid(w, 'cti-line-harbor').attributes('data-state')).toBe('active')
  })

  it('offers the maintainer\'s veto and go on a passed change in its window only; the veto needs its reason; a refusal is shown in place', async () => {
    h.veto = vi.fn().mockRejectedValue({ response: { data: { code: 'not_maintainer', detail: 'the maintainer\'s account vetoes here' } } })
    h.go = vi.fn().mockResolvedValue({ ...BY.lyceum[1], go: { by: 1 } })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cti-row-cc_1').find('[data-testid="cti-maintainer"]').exists()).toBe(false)
    const row = () => tid(w, 'cti-row-cc_3')
    await row().find('[data-testid="cti-veto"]').trigger('click')
    expect(row().find('[data-testid="cti-veto-confirm"]').attributes('disabled')).toBeDefined()
    await row().find('[data-testid="cti-veto-reason"]').setValue('not before the release')
    await row().find('[data-testid="cti-veto-confirm"]').trigger('click'); await flushPromises()
    expect(h.veto).toHaveBeenCalledWith('cc_3', 'not before the release')
    expect(tid(w, 'cti-refusal-cc_3').text()).toBe('the maintainer\'s account vetoes here')
    await row().find('button:not([data-testid])').trigger('click')                 // cancel the veto
    await row().find('[data-testid="cti-go"]').trigger('click'); await flushPromises()
    expect(h.go).toHaveBeenCalledWith('cc_3')
  })

  it('says when a line\'s changes could not be read: the queue is incomplete, never quietly short', async () => {
    h.changes = vi.fn().mockImplementation(async (slug: string) => { if (slug === 'harbor') throw new Error('502'); return BY[slug] })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cti-partial').text()).toBe('The changes of 1 of 2 release lines could not be read: the queue is incomplete.')
    expect(ids(w)).toEqual(['cc_3', 'cc_1'])
  })

  it('names each organization, never a bare id: the name where the registry gives one, a sentence where it cannot (session-lead seq 4803)', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cti-row-cc_3').text()).toContain('Lyceum Labs')
    expect(tid(w, 'cti-row-cc_2').text()).toContain('An organization whose name could not be read')
    expect(w.find('[data-testid="cti-queue"]').text()).not.toMatch(/org-[ab]\b/)
    expect(w.find('[data-testid="cti-lines"]').text()).not.toMatch(/org-[ab]\b/)
    const opts = tid(w, 'cti-f-org').findAll('option').map((o: any) => [o.attributes('value'), o.text()])
    expect(opts).toEqual([['', 'All'], ['org-a', 'Lyceum Labs'], ['org-b', 'An organization whose name could not be read']])
  })
})

// --- V0667 D4: the upstream proposals and their fate -----------------------------------------------------------------------------------------------------------------------------
describe('the upstream proposals (V0667 D4)', () => {
  const up = (id: string, state: string, over: Record<string, any> = {}) => ({ id, title: `Upstream ${id}`, state, created_at: '2026-11-18T10:00:00Z', upstream_of: `cc_line_${id}`,
    provenance: { line: { title: 'Lyceum', slug: 'lyceum', organization_name: 'Lyceum Labs', base_release: 'V0666' }, line_change: { id: `cc_line_${id}`, title: 'A clearer page' } }, ...over })
  beforeEach(() => {
    setCfg(true)
    h.lines = vi.fn().mockResolvedValue(LINES.map((l) => ({ ...l })))
    h.changes = vi.fn().mockImplementation(async (slug: string) => BY[slug] || [])
    h.pause = vi.fn(); h.resume = vi.fn(); h.go = vi.fn(); h.veto = vi.fn()
  })

  it('lists each proposal with its line, its organization and where it stands, linked to the change on the main code', async () => {
    h.upstream = vi.fn().mockResolvedValue([up('cc_u1', 'balloting'), up('cc_u2', 'merged'), up('cc_u3', 'withdrawn')])
    const w = mountIt(); await flushPromises()
    const section = tid(w, 'cti-upstream')
    expect(section.exists()).toBe(true)
    expect(section.find('h2').text()).toContain('3')
    for (const id of ['cc_u1', 'cc_u2', 'cc_u3']) expect(tid(w, `cti-up-${id}`).exists()).toBe(true)
    const first = tid(w, 'cti-up-cc_u1')
    expect(first.text()).toContain('Lyceum')
    expect(first.text()).toContain('Lyceum Labs')
    expect(first.text()).toContain('Members voting')
    expect(tid(w, 'cti-up-cc_u2').text()).toContain('Merged')
    expect(tid(w, 'cti-up-cc_u3').attributes('data-fate')).toBe('ended')
    expect(tid(w, 'cti-up-cc_u2').attributes('data-fate')).toBe('landed')
    expect(tid(w, 'cti-up-cc_u1').attributes('data-fate')).toBe('open')
  })

  it('says so when no line change has gone upstream yet', async () => {
    h.upstream = vi.fn().mockResolvedValue([])
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cti-upstream-none').exists()).toBe(true)
  })

  it('says it could not read them, rather than showing none, and keeps the queue', async () => {
    h.upstream = vi.fn().mockRejectedValue(new Error('503'))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cti-upstream-error').exists()).toBe(true)
    expect(tid(w, 'cti-upstream-none').exists()).toBe(false)
    expect(ids(w).length).toBeGreaterThan(0)
  })
})

