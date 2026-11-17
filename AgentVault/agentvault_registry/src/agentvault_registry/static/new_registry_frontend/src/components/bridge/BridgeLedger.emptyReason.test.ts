/**
 * V0663 (his yes seq 3068, "empty lists that say why"), the bridge ledger: with no row it says WHY under its "Awaiting events"
 * line, through the shared reason line: the stream is not up yet, or it is up and nothing has moved (for MINE: nothing of
 * the viewer's agents, or the honest note about the list of agents). The stream is a double; the component is the real one.
 * BASE: only the bare "Awaiting events" / "Connecting" line is there.
 */
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ connected: null as any }))
vi.mock('@/composables/useLedgerStream', () => ({
  useLedgerStream: () => ({
    anyConnected: h.connected, frames: { value: [] }, totalEvents: { value: 0 }, onRaw: () => () => {},
  }),
}))

import BridgeLedger from './BridgeLedger.vue'

function ledger(connected: boolean, props: Record<string, any> = {}) {
  h.connected = ref(connected)
  return mount(BridgeLedger, { props, global: { stubs: { BridgePayloadModal: true, Icon: true } } })
}

describe('the bridge ledger with no row', () => {
  it('not connected: says it is waiting for the stream', () => {
    const w = ledger(false, { mineAvailable: false })
    const why = w.get('[data-testid="blg-empty-reason"]')
    expect(why.attributes('data-kind')).toBe('waiting')
    expect(why.text()).toContain('Connecting to the ledger stream')
  })

  it('connected, everyone\'s events: the ledger is quiet', () => {
    const w = ledger(true, { mineAvailable: false })
    const why = w.get('[data-testid="blg-empty-reason"]')
    expect(why.attributes('data-kind')).toBe('quiet')
    expect(why.text()).toBe('The ledger is quiet: no event has moved since this page opened.')
  })

  it('connected, MINE: nothing of the viewer\'s agents, or the honest note about the agent list', () => {
    expect(ledger(true, { mineAvailable: true, mineDids: ['did:x:1'] }).get('[data-testid="blg-empty-reason"]').text())
      .toContain('None of your agents')
    expect(ledger(true, { mineAvailable: true, mineDids: ['did:x:1'], scopeNote: 'Only 3 of your agents are known here.' })
      .get('[data-testid="blg-empty-reason"]').text()).toBe('Only 3 of your agents are known here.')
  })

  it('keeps the existing "Awaiting events" line above the reason', () => {
    const w = ledger(true, { mineAvailable: false })
    expect(w.get('.blg-empty').text()).toBe('Awaiting events')
  })
})
