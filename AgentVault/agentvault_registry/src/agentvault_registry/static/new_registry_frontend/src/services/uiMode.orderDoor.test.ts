/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), item 1: a Guild order's door follows the landing decision.
 *
 * The maintainer's report (sessions' room seq 2105): in the desktop chat, a Guild order card opened Pocket's order sheet
 * (/pocket/payments?order=), the door every mode got. Like the quick-create modal's doors (§PHONESTART), the order's
 * door is decided as the landing is: a saved choice, else the viewport's width. Pocket opens its order sheet, a desktop
 * the order on the Guild board. BASE: resolveDoor('guild') falls through to the agents door, resolveOrderDoor and
 * orderDoor do not exist.
 */
import { describe, it, expect, afterEach } from 'vitest'
import * as uiMode from './uiMode'
import { UI_MODE_KEY, resolveDoor } from './uiMode'

const resolveOrderDoor = (uiMode as any).resolveOrderDoor as (id: string, saved: string | null, w: number) => string
const orderDoor = (uiMode as any).orderDoor as (id: string) => string

describe('the Guild door follows the landing decision', () => {
  it('a phone goes to Pocket\'s Payments, a desktop to the Guild board', () => {
    expect(resolveDoor('guild' as any, null, 390)).toBe('/pocket/payments')
    expect(resolveDoor('guild' as any, null, 1440)).toBe('/guild')
  })
  it('a saved choice beats the width, both ways', () => {
    expect(resolveDoor('guild' as any, 'advanced', 390)).toBe('/guild')
    expect(resolveDoor('guild' as any, 'pocket', 1440)).toBe('/pocket/payments')
  })
  it('one order opens on the surface the landing picks, its id carried as ?order=', () => {
    expect(typeof resolveOrderDoor).toBe('function')
    expect(resolveOrderDoor('gwo_c3eacb96b7ca74510052c55c', null, 1440)).toBe('/guild?order=gwo_c3eacb96b7ca74510052c55c')
    expect(resolveOrderDoor('gwo_1', null, 390)).toBe('/pocket/payments?order=gwo_1')
    expect(resolveOrderDoor('a b&c', 'advanced', 390)).toBe('/guild?order=a%20b%26c')
  })
  it('control: the funding and agents doors are unchanged', () => {
    expect(resolveDoor('funding', null, 1440)).toBe('/my-agents?fund=1')
    expect(resolveDoor('agents', null, 390)).toBe('/pocket/agents')
  })
})

describe('orderDoor reads the saved mode and the window, as the landing does', () => {
  const width = window.innerWidth
  afterEach(() => {
    localStorage.removeItem(UI_MODE_KEY)
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
  })
  it('a desktop window with no saved choice opens the order on the Guild board', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
    expect(typeof orderDoor).toBe('function')
    expect(orderDoor('gwo_9')).toBe('/guild?order=gwo_9')
  })
  it('a saved Pocket choice opens the order sheet even on a wide window', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    expect(orderDoor('gwo_9')).toBe('/pocket/payments?order=gwo_9')
  })
})
