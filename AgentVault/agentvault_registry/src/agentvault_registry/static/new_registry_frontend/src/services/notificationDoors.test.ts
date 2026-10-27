/** notificationDoors.test.ts — §POCKETBRIDGE5 W-B. The type→door table, pinned. */
import { describe, it, expect } from 'vitest'
import { pocketClick, doorForNotification } from './notificationDoors'

describe('pocketClick', () => {
  it('parses a pocket-native click with its query intact', () => {
    expect(pocketClick('https://x.example/ui#/pocket/trade?sym=QCC'))
      .toEqual({ path: '/pocket/trade', query: { sym: 'QCC' } })
  })
  it('parses the /ui/# spelling too (push-login emits it)', () => {
    expect(pocketClick('/ui/#/pocket/approve-login?id=ap_1'))
      .toEqual({ path: '/pocket/approve-login', query: { id: 'ap_1' } })
  })
  it('returns null for desktop clicks and empties', () => {
    expect(pocketClick('/ui/#/guild')).toBeNull()
    expect(pocketClick('')).toBeNull()
    expect(pocketClick(null)).toBeNull()
    expect(pocketClick(undefined)).toBeNull()
  })
  it('omits the query key entirely when there is none', () => {
    expect(pocketClick('/ui#/pocket/earn')).toEqual({ path: '/pocket/earn' })
  })
})

describe('doorForNotification', () => {
  it('a pocket-native click wins over any type mapping', () => {
    expect(doorForNotification({ type_key: 'guild.awarded', click: '/ui#/pocket/trade?sym=Z' }))
      .toEqual({ path: '/pocket/trade', query: { sym: 'Z' } })
  })
  it('guild types land on Payments even with a desktop click', () => {
    expect(doorForNotification({ type_key: 'guild.bid_received', click: '/ui/#/guild' }))
      .toEqual({ path: '/pocket/payments' })
  })
  it('dispute types open the WORK modal on the disputes lane', () => {
    expect(doorForNotification({ type_key: 'dispute.filed_against_you', click: '/ui/#/disputes' }))
      .toEqual({ path: '/pocket/home', query: { work: 'disputes' } })
  })
  it('contract types (and the countersign alarm) open the contracts lane', () => {
    expect(doorForNotification({ type_key: 'contract.milestone_submitted' }))
      .toEqual({ path: '/pocket/home', query: { work: 'contracts' } })
    expect(doorForNotification({ type_key: 'jurisdiction.countersign_broken' }))
      .toEqual({ path: '/pocket/home', query: { work: 'contracts' } })
  })
  it('security and account types land on approvals; login approval on its own page', () => {
    expect(doorForNotification({ type_key: 'security.login_approval' }))
      .toEqual({ path: '/pocket/approve-login' })
    expect(doorForNotification({ type_key: 'security.spend_approval' }))
      .toEqual({ path: '/pocket/approvals' })
    expect(doorForNotification({ type_key: 'account.suspended' }))
      .toEqual({ path: '/pocket/approvals' })
  })
  it('agent lifecycle and authority land on Agents', () => {
    for (const t of ['agent.slashed', 'capability.revoked', 'delegation.breaker_tripped']) {
      expect(doorForNotification({ type_key: t })).toEqual({ path: '/pocket/agents' })
    }
  })
  it('the agent-owner notifications land on Agents with the desktop click they carry (D6-781)', () => {
    // their click is the desktop agent list (#/my-agents, which the desktop bell opens as given); Pocket goes by the type
    for (const t of ['agent.mtls_revoked', 'agent.suspended', 'agent.reinstated', 'agent.health_changed', 'agent.slashed']) {
      expect(doorForNotification({ type_key: t, click: '/ui/#/my-agents' })).toEqual({ path: '/pocket/agents' })
    }
  })
  it('money that landed goes home', () => {
    for (const t of ['money.received', 'staking.rewards', 'funding.decided', 'fiat.purchase_completed', 'forge.royalty_received']) {
      expect(doorForNotification({ type_key: t })).toEqual({ path: '/pocket/home' })
    }
  })
  it('exchange types land on Trade (price alerts usually arrive with a native click)', () => {
    expect(doorForNotification({ type_key: 'exchange.order_filled' })).toEqual({ path: '/pocket/trade' })
  })
  it('broadcast and ops types honestly have NO door', () => {
    for (const t of ['broadcast.critical', 'federation.peer_deactivated', 'operator.provisioned', 'cicd.deploy_failed', 'evals.completed']) {
      expect(doorForNotification({ type_key: t })).toBeNull()
    }
    expect(doorForNotification({})).toBeNull()
  })
})
