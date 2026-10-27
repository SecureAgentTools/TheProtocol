/**
 * §LEDGERGATE (V0599): the ledger gate's refusal is said ONCE, as the sentence. V0598's AGORA desk said it twice, the
 * client's "Ledger busy" and its own "Order rejected" carrying the raw detail, so the gate's code word reached the screen.
 * RED on fe/batch-v0598 (no showLedgerRefusal, no wholeLedgerMessage: the second toast is shown as it came).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUIStore } from './ui'
import { LEDGER_SENTENCE, wholeLedgerMessage } from '@/services/api/ledgerRefusal'

const RAW = `ledger_unavailable: ${LEDGER_SENTENCE}`

describe('the ledger refusal is said once', () => {
  let shown: Array<{ type: string, title: string, message?: string }>
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-11T18:00:00Z'))
    shown = []
    useUIStore().setNotificationSystem({ addNotification: (n: any) => { shown.push(n) } })
  })
  afterEach(() => { vi.useRealTimers() })

  it("drops a component's raw-detail toast while the client's is fresh", () => {
    const ui = useUIStore()
    ui.showLedgerRefusal(LEDGER_SENTENCE)
    ui.showError('Order rejected', RAW)
    expect(shown).toEqual([{ type: 'warning', title: 'Ledger busy', message: LEDGER_SENTENCE }])
  })

  it('says the sentence alone when the client said nothing (or long ago)', () => {
    const ui = useUIStore()
    ui.showLedgerRefusal(LEDGER_SENTENCE)
    vi.advanceTimersByTime(6_000)
    ui.showError('Order rejected', RAW)
    expect(shown[1]).toEqual({ type: 'error', title: 'Order rejected', message: LEDGER_SENTENCE })
    expect(shown.some((n) => (n.message || '').includes('ledger_unavailable'))).toBe(false)
  })

  it("leaves a route's own words and every other message alone", () => {
    const ui = useUIStore()
    ui.showLedgerRefusal(LEDGER_SENTENCE)
    ui.showError('Settlement failed', `leg 2: ${RAW}`)
    ui.showError('Order rejected', 'insufficient balance')
    expect(shown.map((n) => n.message)).toEqual([LEDGER_SENTENCE, `leg 2: ${RAW}`, 'insufficient balance'])
  })

  it('reads only a message that IS the refusal as it came', () => {
    expect(wholeLedgerMessage(RAW)).toBe(LEDGER_SENTENCE)
    expect(wholeLedgerMessage(`  ${RAW}"}`)).toBe(LEDGER_SENTENCE)
    expect(wholeLedgerMessage('ledger_unavailable:')).toBe(LEDGER_SENTENCE)
    expect(wholeLedgerMessage(`leg 2: ${RAW}`)).toBeNull()
    expect(wholeLedgerMessage(undefined)).toBeNull()
    expect(wholeLedgerMessage(503)).toBeNull()
  })
})
