/**
 * §FESUITE (V0577): the agent switcher's fleet search. The switcher filters the agents loaded here and asks the registry
 * for the rest of the fleet by name or DID (/developers/me/agents?q=). A search that got no answer was an answer of none:
 * the store returned [], and the switcher said 'No agents match "x". Searched your whole fleet by name and DID.' over a
 * search that never answered (an operator's loaded list is capped; the agent they look for is usually outside it). A late
 * reply for an earlier term cleared "Searching…", so that sentence showed for the new term before its own search
 * answered, and rows answered for the earlier term were listed under the new one. The store's search now returns null
 * when it got no answer; the switcher says the fleet could not be searched and offers the search again, and only the
 * newest search clears "Searching…" or lists rows. The real store and the real switcher, the registry answered per test.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const ui = vi.hoisted(() => ({
  showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn(),
  openQuickAgentModal: vi.fn(), pulseAgentSwitcher: vi.fn(),
  agentSwitcherAttention: false, agentSwitcherPulseAutoOpen: false, agentSwitcherPulseToken: 0,
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ui }))
vi.mock('@/stores/globalReset', () => ({ globalReset: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/', path: '/' }), useRouter: () => ({ push: vi.fn() }) }))

import { apiClient } from '@/services/api/client'
import { authService } from '@/services/auth'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentDidsCache } from '@/services/agentDidsCache'
import { useAuthStore } from '@/stores/auth'
import AgentSwitcher from './AgentSwitcher.vue'

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const LOCAL = Array.from({ length: 6 }, (_, i) => ({ did: `did:theprotocol:local-${i}`, name: `Local ${i}`, is_active: true }))

/** each fleet search the registry was asked, in order, answered when the test says (rows, or an error) */
let searches: Array<{ q: string; answer: (r: any[] | Error) => void }> = []

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  localStorage.clear()
  searches = []
  vi.spyOn(authService, 'getAccessToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'getRefreshToken').mockReturnValue(null as any)
  vi.spyOn(authService, 'isAuthenticated').mockReturnValue(true)
  vi.spyOn(agentCredentialsStore, 'getAllCredentials').mockReturnValue({} as any)
  vi.spyOn(agentCredentialsStore, 'mergeWithStoredCredentials').mockImplementation((a: any) => a)
  vi.spyOn(agentDidsCache, 'getCachedAgents').mockReturnValue(null)
  vi.spyOn(apiClient, 'get').mockImplementation(((url: string) => {
    const m = /^\/developers\/me\/agents\?q=([^&]*)/.exec(url)
    if (!m) return Promise.resolve({ data: [] })
    return new Promise((resolve, reject) => {
      searches.push({ q: decodeURIComponent(m[1]), answer: (r) => (r instanceof Error ? reject(r) : resolve({ data: r })) })
    })
  }) as any)
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

/** a signed-in developer with six agents loaded here (the switcher shows its search box above five) */
function developerWithSixAgents() {
  const store = useAuthStore()
  store.token = 'dev.jwt'
  store.user = { id: 7, role: 'developer', email: 'd@x' } as any
  store.availableAgents = LOCAL.map(a => ({ ...a }))
  return store
}

async function openSwitcher(): Promise<VueWrapper> {
  developerWithSixAgents()
  const w = mount(AgentSwitcher, {
    attachTo: document.body,
    global: {
      stubs: { teleport: true, UserAvatar: true, RouterLink: true, 'router-link': true },
      mocks: { $route: { path: '/', fullPath: '/' } },
    },
  })
  await w.find('.as-trigger').trigger('click')
  await flushPromises()
  return w
}

/** type a filter and let the switcher's 250 ms pause pass, so its fleet search is asked */
async function type(w: VueWrapper, term: string) {
  await w.find('.as-search-input').setValue(term)
  vi.advanceTimersByTime(260)
  await flushPromises()
}

describe("the store's fleet search", () => {
  it('a search that got no answer is null; an answer of none is []', async () => {
    const store = developerWithSixAgents()
    const failed = store.searchAgents('zz')
    searches[0].answer(noAnswer())
    expect(await failed).toBeNull()
    const none = store.searchAgents('zz')
    searches[1].answer([])
    expect(await none).toEqual([])
  })
})

describe('the agent switcher when its fleet search gets no answer', () => {
  it('says the fleet could not be searched, never "No agents match… Searched your whole fleet", and asks again', async () => {
    const w = await openSwitcher()
    await type(w, 'zz-remote')
    expect(searches.map(s => s.q)).toEqual(['zz-remote'])
    searches[0].answer(noAnswer())
    await flushPromises()
    expect(w.text()).not.toContain('Searched your whole fleet')
    expect(w.text()).not.toContain('No agents match')
    const notice = w.find('[data-testid="as-search-failed"]')
    expect(notice.exists(), 'the switcher says the fleet search failed').toBe(true)
    expect(notice.text()).toContain('could not be searched')

    await w.find('[data-testid="as-search-failed"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(searches.map(s => s.q)).toEqual(['zz-remote', 'zz-remote'])
    searches[1].answer([])
    await flushPromises()
    expect(w.find('[data-testid="as-search-failed"]').exists()).toBe(false)
    expect(w.text()).toContain('No agents match "zz-remote"')
    w.unmount()
  })

  it('with local matches, it names the rows as only the agents loaded here', async () => {
    const w = await openSwitcher()
    await type(w, 'Local 1')
    searches[0].answer(noAnswer())
    await flushPromises()
    expect(w.findAll('.as-agent-row')).toHaveLength(1)
    const notice = w.find('[data-testid="as-search-failed"]')
    expect(notice.exists(), 'the switcher says the rows are only the agents loaded here').toBe(true)
    expect(notice.text()).toContain('only the agents loaded here')
    w.unmount()
  })

  it('a late reply for an earlier term does not end "Searching…" for the newer one', async () => {
    const w = await openSwitcher()
    await type(w, 'zz')
    await w.find('.as-search-input').setValue('zzz')   // the person keeps typing; this search waits its 250 ms
    searches[0].answer([])                             // the earlier term's reply arrives late
    await flushPromises()
    expect(w.text()).toContain('Searching all agents')
    expect(w.text()).not.toContain('No agents match')

    vi.advanceTimersByTime(260)
    await flushPromises()
    expect(searches.map(s => s.q)).toEqual(['zz', 'zzz'])
    searches[1].answer([])
    await flushPromises()
    expect(w.text()).toContain('No agents match "zzz"')
    w.unmount()
  })

  it('rows the registry answered for an earlier term are not listed under a new one', async () => {
    const w = await openSwitcher()
    await type(w, 'far')
    searches[0].answer([{ did: 'did:theprotocol:far-away', name: 'Far Away', is_active: true }])
    await flushPromises()
    expect(w.text()).toContain('Far Away')
    await w.find('.as-search-input').setValue('fax')   // nothing loaded matches "fax"; its search has not answered
    await flushPromises()
    expect(w.text()).not.toContain('Far Away')
    w.unmount()
  })
})
