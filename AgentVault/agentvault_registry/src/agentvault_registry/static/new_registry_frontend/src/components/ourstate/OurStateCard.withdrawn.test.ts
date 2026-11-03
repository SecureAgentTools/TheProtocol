import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OurStateCard from './OurStateCard.vue'

/** V0654 (aq), item 18: a request its asker withdrew says so on its card. BASE (V0653): "waiting for a decision". */
const card = { v: 1, type: 'approval.request', data: { approval_id: 'apr_w1', title: 'V0653 production roll',
  expires_at: '2026-11-02T18:00:00Z', withdrawn: { at: '2026-11-02T16:00:00Z', by_agent_did: 'did:x' } },
  refs: { approval_id: 'apr_w1' } }

describe('a withdrawn approval request', () => {
  it('reads withdrawn beside its head, dimmed like an expired one', () => {
    const w = mount(OurStateCard, { props: { card, liveApproval: 'withdrawn' }, global: { stubs: { Icon: true } } })
    const st = w.find('[data-testid="osc-approval-status"]')
    expect(st.text()).toContain('withdrawn by the agent that asked')
    expect(st.attributes('data-status')).toBe('withdrawn')
  })
})
