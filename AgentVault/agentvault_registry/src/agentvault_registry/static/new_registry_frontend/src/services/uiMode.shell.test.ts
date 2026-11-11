/**
 * V0658 (v), item 3, session-lead's decision (the sessions' room, seq 2389): a press inside a shell stays in that shell.
 *
 * His saved Pocket choice (tp_ui_mode) decides where he ARRIVES from outside (homeRoute: the root address, a login, a
 * notification, a mailed link). It never moves him out of the shell he is working in, and that move is what he
 * reported: in the desktop console's Agent Discovery, "Post a bounty to this firm" opened Pocket's Payments. This is
 * §PHONESTART's rule seen from the other side (a door leads to a view the current shell renders), so it lives in
 * resolveDoor itself: inside a shell (a /pocket route is Pocket, a route inside DashboardLayout the desktop console) the
 * door follows that shell; the saved choice, else the width, decides only where no shell is mounted (the public pages).
 * The shell is read from the route on screen, through the router the app hands over, so no caller passes it by hand.
 * homeRoute, where a person arrives from outside, is unchanged.
 * RED on e0fe8732c: resolveDoor takes no shell (the desktop console with Pocket saved got Pocket's routes, Pocket on a
 * wide window the desktop's), it has no Guild door, and no door reads the route on screen.
 */
import { afterEach, describe, expect, it } from 'vitest'
import * as uiMode from './uiMode'
import { agentsDoor, fundingDoor, isPocketMode, resolveDoor, resolveHomeRoute, UI_MODE_KEY } from './uiMode'

// read off the module, so a part of this change that does not exist yet fails as an assertion rather than at import
const m = uiMode as unknown as Record<string, any>
const bindIfThere = (router: unknown) => { if (typeof m.bindDoorRouter === 'function') m.bindDoorRouter(router) }
const onScreen = (path: string, meta: Record<string, unknown>) => ({ currentRoute: { value: { path, meta } } })
const atWidth = (px: number) => Object.defineProperty(window, 'innerWidth', { configurable: true, value: px })

describe('a door follows the shell it is pressed in', () => {
  it('in the desktop console with Pocket saved, the door stays in the desktop console, at any width', () => {
    for (const width of [390, 1440]) {
      expect(resolveDoor('agents', 'pocket', width, 'desktop'), `My Agents at ${width}`).toBe('/my-agents')
      expect(resolveDoor('funding', 'pocket', width, 'desktop'), `the funding door at ${width}`).toBe('/my-agents?fund=1')
      expect(resolveDoor('guild', 'pocket', width, 'desktop'), `the Guild at ${width}`).toBe('/guild')
    }
  })

  it('in Pocket at a desktop width, the door stays in Pocket, a saved desktop choice too', () => {
    for (const saved of [null, 'advanced']) {
      expect(resolveDoor('agents', saved, 1440, 'pocket'), `the agents tab, saved ${saved}`).toBe('/pocket/agents')
      expect(resolveDoor('funding', saved, 1440, 'pocket'), `the funding door, saved ${saved}`).toBe('/pocket/home?fund=1')
      expect(resolveDoor('guild', saved, 1440, 'pocket'), `the Guild, saved ${saved}`).toBe('/pocket/payments')
    }
  })

  it('with no shell (the public pages), the saved choice decides, else the width: the landing decision', () => {
    expect(resolveDoor('agents', 'pocket', 1440, 'none')).toBe('/pocket/agents')
    expect(resolveDoor('funding', 'advanced', 390, 'none')).toBe('/my-agents?fund=1')
    expect(resolveDoor('agents', null, 390, 'none')).toBe('/pocket/agents')
    expect(resolveDoor('funding', null, 1440, 'none')).toBe('/my-agents?fund=1')
    // the same decision as where a person arrives, for every saved value (unknown ones ignored) and either side of 768
    for (const saved of [null, 'pocket', 'advanced', 'bridge', '']) {
      for (const width of [390, 767, 768, 1440]) {
        expect(resolveDoor('agents', saved, width, 'none') === '/pocket/agents', `saved ${saved} at ${width}`)
          .toBe(resolveHomeRoute(saved, width) === '/pocket/home')
      }
    }
  })

  it('the Guild door (where a firm bounty is posted) follows the same rule where no shell is mounted', () => {
    expect(resolveDoor('guild', null, 390, 'none')).toBe('/pocket/payments')
    expect(resolveDoor('guild', null, 1440, 'none')).toBe('/guild')
    expect(resolveDoor('guild', 'pocket', 1440, 'none')).toBe('/pocket/payments')
    expect(resolveDoor('guild', 'advanced', 390, 'none')).toBe('/guild')
  })
})

describe('the sentence about where things are agrees with the doors (§PHONEWORDS)', () => {
  it('follows the shell first, like the doors', () => {
    expect(isPocketMode('pocket', 1440, 'desktop')).toBe(false)
    expect(isPocketMode('pocket', 390, 'desktop')).toBe(false)
    expect(isPocketMode('advanced', 1440, 'pocket')).toBe(true)
    expect(isPocketMode(null, 1440, 'pocket')).toBe(true)
  })

  it('with no shell, the saved choice, else the width', () => {
    expect(isPocketMode('pocket', 1440, 'none')).toBe(true)
    expect(isPocketMode('advanced', 390, 'none')).toBe(false)
    expect(isPocketMode(null, 390, 'none')).toBe(true)
    expect(isPocketMode(null, 1440, 'none')).toBe(false)
  })
})

describe('the shell is read from the route on screen, so no caller passes it', () => {
  const width = window.innerWidth
  afterEach(() => {
    bindIfThere(null)
    localStorage.removeItem(UI_MODE_KEY)
    atWidth(width)
  })

  it('a route renders in the shell its shell record declares, and in none otherwise', () => {
    expect(typeof m.shellOf, 'shellOf(route)').toBe('function')
    expect(m.shellOf({ meta: { shell: 'pocket' } })).toBe('pocket')
    expect(m.shellOf({ meta: { shell: 'desktop' } })).toBe('desktop')
    expect(m.shellOf({ meta: {} }), 'a public page').toBe('none')
    expect(m.shellOf({ meta: { shell: 'bridge' } }), 'an unknown value is ignored, never guessed at').toBe('none')
    expect(m.shellOf(undefined), 'no route at all').toBe('none')
  })

  it('every door named without a shell follows the route on screen', () => {
    // his report's conditions: the desktop console, Pocket saved, a narrow window
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    atWidth(390)
    bindIfThere(onScreen('/discover', { shell: 'desktop' }))
    expect(resolveDoor('guild', 'pocket', 390), 'a three-argument call, as every door makes it').toBe('/guild')
    expect(agentsDoor()).toBe('/my-agents')
    expect(fundingDoor()).toBe('/my-agents?fund=1')
    expect(isPocketMode(), 'the sentence beside the doors').toBe(false)

    // Pocket on a wide window, a desktop choice saved
    localStorage.setItem(UI_MODE_KEY, 'advanced')
    atWidth(1440)
    bindIfThere(onScreen('/pocket/home', { shell: 'pocket' }))
    expect(resolveDoor('guild', 'advanced', 1440)).toBe('/pocket/payments')
    expect(agentsDoor()).toBe('/pocket/agents')
    expect(fundingDoor()).toBe('/pocket/home?fund=1')
    expect(isPocketMode()).toBe(true)

    // a public page: the saved choice decides again
    bindIfThere(onScreen('/explore', {}))
    expect(agentsDoor(), 'the saved desktop choice').toBe('/my-agents')
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    expect(agentsDoor(), 'the saved Pocket choice').toBe('/pocket/agents')
  })

  it('the route is read at the press, not when the router was handed over', () => {
    const currentRoute = { value: { path: '/my-agents', meta: { shell: 'desktop' } as Record<string, unknown> } }
    bindIfThere({ currentRoute })
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    atWidth(390)
    expect(agentsDoor(), 'on a desktop page').toBe('/my-agents')
    currentRoute.value = { path: '/pocket/home', meta: { shell: 'pocket' } }
    localStorage.setItem(UI_MODE_KEY, 'advanced')
    atWidth(1440)
    expect(agentsDoor(), 'after a move into Pocket').toBe('/pocket/agents')
  })

  it('before a router is handed over there is no shell, and the saved choice decides', () => {
    expect(typeof m.bindDoorRouter, 'bindDoorRouter(router)').toBe('function')
    expect(typeof m.currentShell, 'currentShell()').toBe('function')
    m.bindDoorRouter(null)
    expect(m.currentShell()).toBe('none')
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    atWidth(1440)
    expect(agentsDoor()).toBe('/pocket/agents')
    m.bindDoorRouter(onScreen('/mission-control', { shell: 'desktop' }))
    expect(m.currentShell()).toBe('desktop')
  })
})
