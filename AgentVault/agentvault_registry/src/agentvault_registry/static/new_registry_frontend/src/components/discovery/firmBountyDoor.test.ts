/**
 * V0658 (v), item 3 (the maintainer's review, sessions' room seq 2181): where "Post a bounty to this firm" in Discovery's
 * Firms strip goes. Desktop: the Guild board's post form with the firm reserved. Pocket: Pocket's post sheet, carrying
 * the same reservation, so a firm bounty never becomes an open one.
 * Which of the two: the shell the press happens in (session-lead's decision, the sessions' room seq 2389: a press inside
 * the desktop console stays in the desktop console, his saved Pocket choice notwithstanding; that move is what he
 * reported). Only where no shell is mounted (the public Explore page) does the landing decision pick: a saved choice
 * first, else the width (services/uiMode.ts resolveDoor, the rule the quick-create modal's doors follow).
 * RED on 553347408 (origin/v0657/cut): the module does not exist (the strip pushed /guild on every width).
 * RED on e0fe8732c: the shell is not read; pressed in the desktop console with Pocket saved, the door opened Pocket.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { firmBountyDoor, resolveFirmBountyDoor } from './firmBountyDoor'
import * as uiMode from '@/services/uiMode'
import { UI_MODE_KEY } from '@/services/uiMode'

const FIRM = { org_id: 'org-7', name: 'Reach Limited' }
const DESK = { path: '/guild', query: { post: '1', for_org: 'org-7', title: 'For Reach Limited: ' } }
const POCKET = { path: '/pocket/payments', query: { post: '1', for_org: 'org-7', title: 'For Reach Limited: ' } }

// read off the module, so the binding this change adds fails as an assertion where it is missing
const m = uiMode as unknown as Record<string, any>
const bindIfThere = (router: unknown) => { if (typeof m.bindDoorRouter === 'function') m.bindDoorRouter(router) }
const onScreen = (path: string, meta: Record<string, unknown>) => ({ currentRoute: { value: { path, meta } } })
const atWidth = (px: number) => Object.defineProperty(window, 'innerWidth', { configurable: true, value: px })
const width = window.innerWidth

afterEach(() => { bindIfThere(null); localStorage.clear(); atWidth(width) })

describe('the firm bounty door stays in the shell it is pressed in', () => {
  it("pressed in the desktop console, it opens the Guild board, a saved Pocket choice and a phone's width notwithstanding", () => {
    expect(resolveFirmBountyDoor(FIRM, 'pocket', 1440, 'desktop')).toEqual(DESK)
    expect(resolveFirmBountyDoor(FIRM, 'pocket', 390, 'desktop')).toEqual(DESK)
    expect(resolveFirmBountyDoor(FIRM, null, 390, 'desktop')).toEqual(DESK)
  })

  it('pressed in Pocket, it opens the post sheet, on a wide window and with a desktop choice saved too', () => {
    expect(resolveFirmBountyDoor(FIRM, null, 1440, 'pocket')).toEqual(POCKET)
    expect(resolveFirmBountyDoor(FIRM, 'advanced', 1440, 'pocket')).toEqual(POCKET)
  })

  it('the browser binding reads the shell from the route on screen (his report: Discovery, Pocket saved)', () => {
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    atWidth(390)
    bindIfThere(onScreen('/discover', { shell: 'desktop' }))
    expect(firmBountyDoor(FIRM)).toEqual(DESK)
  })
})

describe('where no shell is mounted (the public Explore page), the door follows the landing decision', () => {
  it('a desktop with no saved choice opens the Guild board with the firm reserved', () => {
    expect(resolveFirmBountyDoor(FIRM, null, 1440, 'none')).toEqual(DESK)
  })

  it('a phone opens Pocket, the firm still reserved', () => {
    expect(resolveFirmBountyDoor(FIRM, null, 390, 'none')).toEqual(POCKET)
  })

  it('a saved choice beats the width, both ways; an unknown saved value is ignored', () => {
    expect(resolveFirmBountyDoor(FIRM, 'pocket', 1440, 'none')).toEqual(POCKET)
    expect(resolveFirmBountyDoor(FIRM, 'advanced', 390, 'none')).toEqual(DESK)
    expect(resolveFirmBountyDoor(FIRM, 'bridge', 1440, 'none')).toEqual(DESK)
  })

  it('the browser binding reads the saved choice and the window', () => {
    bindIfThere(onScreen('/explore', {}))
    atWidth(1440)
    expect(firmBountyDoor(FIRM)).toEqual(DESK)
    localStorage.setItem(UI_MODE_KEY, 'pocket')
    expect(firmBountyDoor(FIRM)).toEqual(POCKET)
  })
})
