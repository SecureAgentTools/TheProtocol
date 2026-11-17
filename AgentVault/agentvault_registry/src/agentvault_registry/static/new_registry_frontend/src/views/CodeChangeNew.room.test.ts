/**
 * V0666 D3 (order gwo_542285271416c653ca39af3f): /change in an organization's room opens the proposal with the line, the room
 * and the title (#/code-changes/new?line=&room=&title=). The title is prefilled, the page says the change is announced in
 * that room (its live card and state lines), and the body names it (room_id); the registry checks the room is the line's
 * organization's. Red before D3: the page takes no room and no title.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ propose: null as any, push: vi.fn(), getLine: null as any, auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/codeChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/codeChanges')), proposeChange: (...a: any[]) => h.propose(...a) }))
vi.mock('@/services/api/codeDistributions', () => ({ getLine: (...a: any[]) => h.getLine(...a) }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => ({ codeDistributionsEnabled: ref(true), load: vi.fn().mockResolvedValue({}) }) }))
vi.mock('@/services/api/repoAccount', () => ({ getRepoAccount: () => Promise.resolve({ enabled: false }), linkRepoAccount: vi.fn() }))   // V0667: repository accounts off here: the form as before
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push, replace: vi.fn() }),
  useRoute: () => ({ params: {}, query: { line: 'lyceum', room: 'room-1', title: 'A seating chart' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChangeNew from './CodeChangeNew.vue'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const LINE = { slug: 'lyceum', organization_id: 'org-a', organization_name: 'Lyceum Labs', title: 'Lyceum', release_name: 'V0666_lyceum', open_paths: [CONSOLE_PREFIX + 'views'], state: 'active' }
const mountIt = () => mount(CodeChangeNew, { global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const next = async (w: any) => { await tid(w, 'ccn-next').trigger('click'); await flushPromises() }

describe('proposing from /change in a room', () => {
  beforeEach(() => { h.getLine = vi.fn().mockResolvedValue(LINE); h.propose = vi.fn().mockResolvedValue({ id: 'cc_9' }) })

  it('prefills the title, says where the change is announced, and names the room in the body', async () => {
    const w = mountIt(); await flushPromises()
    expect((tid(w, 'ccn-title').element as HTMLInputElement).value).toBe('A seating chart')
    expect(tid(w, 'ccn-room').text()).toMatch(/announced in the room you came from/)
    await tid(w, 'ccn-problem').setValue('Teachers cannot see who sits where on the class page.'); await next(w)
    await tid(w, 'ccn-path-input').setValue('views/Classroom.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
    await tid(w, 'ccn-bounty').setValue('5'); await next(w)
    await tid(w, 'ccn-submit').trigger('click'); await flushPromises()
    expect(h.propose).toHaveBeenCalledWith(expect.objectContaining({ code_distribution: 'lyceum', room_id: 'room-1', title: 'A seating chart' }))
  })
})
