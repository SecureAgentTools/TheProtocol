// V0658 (f), polish 20 of the disputes discovery: a dispute has two states on the server, OPEN and CLOSED (closed read as
// resolved or dismissed by its ruling). The console also had "investigating", a filter for it and a "high priority"
// guess built on it and on age and evidence count; the server never sends "investigating", so the filter always read
// empty and the guess flagged disputes for being old. They are gone; these hold the console to the server's states.
import { describe, expect, it } from 'vitest'
import { disputesApi } from './disputes'
import disputesView from '../../views/Disputes.vue?raw'
import analytics from '../../components/DisputeAnalytics.vue?raw'
import workView from '../../components/bridge/BridgeWorkView.vue?raw'
import store from '../../stores/disputes.ts?raw'
import attention from '../bridge/attention.ts?raw'
import api from './disputes.ts?raw'

const transform = (raw: any) => (disputesApi as any).transformDispute({ id: 1, complainant_did: 'a', defendant_did: 'b', ...raw })

describe("the server's dispute states", () => {
  it('OPEN reads open; CLOSED reads resolved, or dismissed by its ruling', () => {
    expect(transform({ status: 'OPEN' }).status).toBe('open')
    expect(transform({ status: 'CLOSED', ruling: 'IN_FAVOR_OF_COMPLAINANT' }).status).toBe('resolved')
    expect(transform({ status: 'CLOSED', ruling: 'DISMISSED' }).status).toBe('dismissed')
  })

  it('a state the server does not have reads open, never a state of its own', () => {
    expect(transform({ status: 'INVESTIGATING' }).status).toBe('open')
  })
})

describe('no console surface names a state the server does not have', () => {
  for (const [name, src] of Object.entries({ disputesView, analytics, workView, store, attention, api })) {
    it(`${name}: no "investigating"`, () => {
      expect(src).not.toMatch(/investigating/i)
    })
  }

  it('the Disputes view makes no "high priority" guess', () => {
    expect(disputesView).not.toMatch(/isPriority|highPriority|high-priority|drc-priority-badge/)
  })
})
