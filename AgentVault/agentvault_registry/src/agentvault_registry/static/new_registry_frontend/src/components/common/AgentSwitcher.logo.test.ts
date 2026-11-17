/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), item 3: the desktop agent selector shows each agent's own logo.
 *
 * The maintainer's report (sessions' room seq 2105): Shadowban Sheldon's vanity item, the black hole, stood where its
 * logo should be, and the sessions' agents, which have logos (their cards' iconUrl), showed none: the selector never
 * handed UserAvatar a picture, so a plain agent drew its initials and a full-cover vanity drew itself in the center.
 * Now the trigger and every row draw the agent's own logo inside its vanity ring, with the rank (the earned collar) as
 * before; an agent with no logo keeps its initials, never the vanity's core. Mounted with the real UserAvatar and
 * FlareEncirclement. BASE: no picture anywhere in the selector, and the black hole's core drawn over the face.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, ui: {
  showError: vi.fn(), showWarning: vi.fn(), showInfo: vi.fn(), showSuccess: vi.fn(), openQuickAgentModal: vi.fn(),
  pulseAgentSwitcher: vi.fn(), agentSwitcherAttention: false, agentSwitcherPulseAutoOpen: false, agentSwitcherPulseToken: 0,
} }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/', path: '/' }), useRouter: () => ({ push: vi.fn() }) }))

import AgentSwitcher from './AgentSwitcher.vue'
import { cardIconSrc } from '@/services/agentAvatar'

const SHELDON_LOGO = 'https://docs.theprotocol.cloud/agents/shadowban-sheldon.png'
const LEAD_LOGO = 'https://docs.theprotocol.cloud/agents/session-lead.png'
const verified = { jobs: 52, stars: 4.9, five_star: 40, on_time_met: 50, on_time_of: 52, traveled: 0, cross_registry: 0,
  disputes: 0, last_verified_at: '2026-11-07T19:00:00Z' }
const sheldon = { did: 'did:theprotocol:eu.test:shadowban-sheldon', name: 'Shadowban Sheldon', status: 'active', owned: true,
  flare_tier: 'shadow_chancellor', flare_encirclement_variant: 'blackhole', track_record: verified,
  card_data: { name: 'Shadowban Sheldon', iconUrl: SHELDON_LOGO } }
const lead = { did: 'did:theprotocol:eu.test:session-lead', name: 'session-lead', status: 'active', owned: true,
  card_data: { name: 'session-lead', iconUrl: LEAD_LOGO } }
const noLogo = { did: 'did:theprotocol:eu.test:void-without-logo', name: 'Quiet Quinn', status: 'active', owned: true,
  flare_tier: 'shadow_chancellor', flare_encirclement_variant: 'blackhole', card_data: { name: 'Quiet Quinn' } }

function store(agents: any[], active: any) {
  h.auth = reactive({
    activeAgent: active, availableAgents: agents, agentLoading: false, agentFetchFailed: false, showAgentSelector: false,
    isDeveloper: true, isAdmin: false, isAgentRequired: () => false,
    fetchAvailableAgents: vi.fn(async () => true), hydrateForeignFlares: vi.fn(async () => {}),
    searchAgents: vi.fn(async () => []), switchAgent: vi.fn(async () => true),
    canActAs: (a: any) => !!a && !!a.owned,
  })
}

async function open(agents: any[], active: any) {
  store(agents, active)
  const w = mount(AgentSwitcher, {
    attachTo: document.body,
    global: { stubs: { teleport: true, RouterLink: true, 'router-link': true },
              mocks: { $route: { path: '/', fullPath: '/' } } },
  })
  await w.find('.as-trigger').trigger('click')
  await flushPromises()
  return w
}

const row = (w: any, name: string) => w.findAll('.as-agent-row').find((r: any) => r.text().includes(name))

describe("the agent selector draws each agent's own logo", () => {
  beforeEach(() => { h.auth = null; vi.clearAllMocks(); document.body.innerHTML = '' })

  it('the trigger: the logo inside the vanity ring, the rank around it, no black hole over the face', async () => {
    const w = await open([sheldon, lead], sheldon)
    const trig = w.find('.as-trigger')
    // V0662 item 14: drawn from the registry's icon route for that card, never the address the card names
    expect(trig.find(`img[src="${cardIconSrc(sheldon.did, SHELDON_LOGO)}"]`).exists(), 'the agent\'s logo').toBe(true)
    expect(trig.find('.fc-encircle-blackhole').exists(), 'the vanity ring stays').toBe(true)
    expect(trig.find('.fc-blackhole-core').exists(), 'the vanity does not stand in for the logo').toBe(false)
    expect(trig.find('[data-testid^="earned-collar-"]').exists(), 'the rank, as before').toBe(true)
    w.unmount()
  })

  it("each row: a plain agent's logo, and the vanity agent's logo in its ring", async () => {
    const w = await open([sheldon, lead], sheldon)
    expect(row(w, 'session-lead').find(`img[src="${cardIconSrc(lead.did, LEAD_LOGO)}"]`).exists(), 'the session agent\'s logo').toBe(true)
    const s = row(w, 'Shadowban Sheldon')
    expect(s.find(`img[src="${cardIconSrc(sheldon.did, SHELDON_LOGO)}"]`).exists()).toBe(true)
    expect(s.find('.fc-blackhole-core').exists()).toBe(false)
    expect(s.find('.fc-encircle-blackhole').exists()).toBe(true)
    w.unmount()
  })

  it('an agent with no logo keeps its initials inside its ring, not the vanity core', async () => {
    const w = await open([noLogo], noLogo)
    const trig = w.find('.as-trigger')
    expect(trig.find('img').exists()).toBe(false)
    expect(trig.find('.fc-blackhole-core').exists()).toBe(false)
    expect(trig.find('.fc-encircle-initials').text()).toBe('QQ')
    w.unmount()
  })
})
