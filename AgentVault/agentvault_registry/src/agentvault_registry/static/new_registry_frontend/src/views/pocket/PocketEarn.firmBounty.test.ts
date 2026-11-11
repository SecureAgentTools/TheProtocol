/**
 * V0658 (v), item 3: the firm bounty door follows the landing decision, so on a phone (or a saved Pocket choice) it
 * opens Pocket's post sheet: /pocket/payments?post=1&title=For <firm>: &for_org=<id>. The sheet must carry the firm's
 * reservation the way the Guild board's post form does (a `for-org:<id>` tag in required_skills, and the line that says
 * only that organization's agents can bid); without it a firm bounty would be posted to anyone, silently.
 * A post with no firm named stays an open post (the control).
 * RED on 553347408 (origin/v0657/cut): the sheet ignores for_org and posts without the tag.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({
  route: { query: {} as Record<string, any> }, replace: vi.fn(async () => {}), push: vi.fn(async () => {}),
  post: vi.fn(async () => ({ order_id: 'gwo_1' })),
}))
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ replace: h.replace, push: h.push }) }))
vi.mock('@/services/api/guild', () => ({
  guildApi: {
    post: h.post, networkBoard: vi.fn(async () => ({ orders: [], peers_polled: 0 })), mine: vi.fn(async () => ({ orders: [] })),
    myCredentials: vi.fn(async () => ({ credentials: [] })), detail: vi.fn(), crossRegistryAct: vi.fn(),
    award: vi.fn(), submitWork: vi.fn(), verify: vi.fn(), cancel: vi.fn(),
  },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:eu.test:a1' } }) }))
vi.mock('@/composables/usePocketAgent', () => ({
  usePocketAgent: () => ({ credAgents: ref([{ did: 'did:theprotocol:eu.test:a1', name: 'a1' }]), noAgentReason: ref(''),
    ensureAgentFor: vi.fn(async () => true) }),
}))
vi.mock('@/composables/usePullToRefresh', () => ({
  usePullToRefresh: () => ({ ptrH: ref(0), ptrArmed: ref(false), onTouchStart: () => {}, onTouchMove: () => {}, onTouchEnd: () => {} }),
}))
vi.mock('@/composables/useActingContext', () => ({ useActingContext: () => ({ actingCurrencyLabel: ref('ECU') }) }))
vi.mock('@/composables/usePocketLock', () => ({ usePocketLock: () => ({ enabled: ref(false), verify: vi.fn(async () => true) }) }))
vi.mock('@/components/common/ActingContextNotice.vue', () => ({ default: { name: 'ActingContextNotice', render: () => null } }))

import PocketEarn from './PocketEarn.vue'

async function open(query: Record<string, string>) {
  h.route = reactive({ query })
  const w = mount(PocketEarn, { attachTo: document.body })
  await flushPromises()
  return w
}

describe("Pocket's post sheet, opened by the firm bounty door", () => {
  beforeEach(() => { h.post.mockClear(); h.replace.mockClear() })

  it('keeps the firm reserved: the line on the sheet and the for-org tag on the post', async () => {
    const w = await open({ post: '1', title: 'For Reach Limited: ', for_org: 'org-7' })
    const sheet = w.find('[data-testid="pe-post-sheet"]')
    expect(sheet.exists()).toBe(true)
    expect((w.find('[data-testid="pe-post-title"]').element as HTMLInputElement).value.trim()).toBe('For Reach Limited:')
    const reserved = sheet.find('[data-testid="pe-post-fororg"]')
    expect(reserved.exists(), 'the sheet says the bounty is reserved for a firm').toBe(true)
    expect(reserved.text()).toMatch(/only that organization's agents can bid/i)
    expect(h.replace, 'the door is consumed from the address').toHaveBeenCalled()
    const calls = h.replace.mock.calls as any[]
    const left = calls[calls.length - 1][0].query
    expect(left.for_org).toBeUndefined()

    await w.find('[data-testid="pe-post-title"]').setValue('For Reach Limited: audit the rate card')
    await w.find('[data-testid="pe-post-bounty"]').setValue('5')
    await w.find('[data-testid="pe-post-go"]').trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledTimes(1)
    expect((h.post.mock.calls[0] as any)[0]).toMatchObject({ title: 'For Reach Limited: audit the rate card', bounty: 5,
      required_skills: ['for-org:org-7'] })
    w.unmount()
  })

  it('a post with no firm named stays an open post', async () => {
    const w = await open({ post: '1', title: 'Summarise a note' })
    expect(w.find('[data-testid="pe-post-fororg"]').exists()).toBe(false)
    await w.find('[data-testid="pe-post-bounty"]').setValue('5')
    await w.find('[data-testid="pe-post-go"]').trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledTimes(1)
    expect((h.post.mock.calls[0] as any)[0].required_skills).toBeUndefined()
    w.unmount()
  })
})
