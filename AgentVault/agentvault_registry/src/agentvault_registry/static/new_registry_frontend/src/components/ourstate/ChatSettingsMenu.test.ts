import { describe, it, expect, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ChatSettingsMenu from './ChatSettingsMenu.vue'

/**
 * V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): the thread's settings menu. The rows each kind of thread has (a room,
 * a direct chat, a support ticket), each with its state; the testids the suites drive; the keyboard (arrows, Home, End,
 * Escape); the menu under its button on a wide screen and a sheet on a phone; a click outside closes it. BASE (V0651):
 * no component (an inline list in the thread, 835 px from its button at 1440, transparent).
 */
const ROOM = { opened: 6, isOperator: true, mode: 'open', assistantPresent: false }
const base = { title: 'TheProtocol Sessions', subline: 'Org room · 6 opened it · hosted by EU', retention: 'Off',
  notify: 'Mentions and asks', readers: "The members, and EU's operator" }
const opts = { global: { stubs: { Icon: true } }, attachTo: document.body }
/** the rows' testids, in order (the value spans and the grab handle are not rows) */
const ids = () => [...document.querySelectorAll('[data-testid="ost-menu-sheet"] [data-testid^="ost-"]')].map((e) => e.getAttribute('data-testid'))
afterEach(() => { document.body.innerHTML = '' })

describe('the rows of each kind of thread', () => {
  it('a room, as an owner or an admin', async () => {
    mount(ChatSettingsMenu, { props: { ...base, surface: 'popover', kind: 'room', room: ROOM }, ...opts })
    await flushPromises()
    expect(ids()).toEqual(['ost-room-members', 'ost-room-settings', 'ost-assistant-toggle', 'ost-timer-open',
      'ost-privacy-open', 'ost-notify', 'ost-you-settings', 'ost-leave', 'ost-burn'])
    expect(document.querySelector('[data-testid="ost-room-members"]')!.textContent).toContain('6')
    expect(document.querySelector('[data-testid="ost-assistant-toggle"]')!.getAttribute('aria-checked')).toBe('false')
    expect(document.querySelector('[data-testid="csm-notify-val"]')!.textContent).toBe('Mentions and asks')
  })

  it('a room, as a member: the settings read only, @assistant a state', async () => {
    mount(ChatSettingsMenu, { props: { ...base, surface: 'popover', kind: 'room', room: { ...ROOM, isOperator: false },
      timerEditable: false }, ...opts })
    await flushPromises()
    expect(document.querySelector('[data-testid="csm-assistant-state"]')!.textContent).toContain('Off')
    expect(ids()).not.toContain('ost-assistant-toggle')
    expect(document.querySelector('[data-testid="ost-room-settings"]')!.textContent).toContain('Read only')
    expect(document.querySelector('[data-testid="ost-timer-open"]')!.textContent).toContain('Read only')
  })

  it('a direct chat: no room rows; block, the stand-in while away is on, leave', async () => {
    mount(ChatSettingsMenu, { props: { ...base, surface: 'sheet', kind: 'dm', canBlock: true, counterpartyName: 'Kestrel',
      away: { enabled: true, silencedHere: false }, readers: "You two, and EU's operator" }, ...opts })
    await flushPromises()
    expect(ids()).toEqual(['ost-timer-open', 'ost-privacy-open', 'ost-notify', 'ost-away-here', 'ost-you-settings',
      'ost-block', 'ost-leave', 'ost-burn'])
    expect(document.querySelector('[data-testid="ost-block"]')!.textContent).toContain('Block Kestrel')
    expect(document.querySelector('[data-testid="ost-block"]')!.textContent).toContain('they are not told')
  })

  it('a support ticket: its status; no timer, no block, no stand-in, no leave', async () => {
    mount(ChatSettingsMenu, { props: { ...base, surface: 'sheet', kind: 'support', ticket: { id: 1, status: 'open' },
      canBlock: false }, ...opts })
    await flushPromises()
    const got = ids()
    expect(got).toContain('ost-ticket')
    for (const absent of ['ost-timer-open', 'ost-block', 'ost-away-here', 'ost-leave', 'ost-room-members']) expect(got).not.toContain(absent)
    for (const present of ['ost-privacy-open', 'ost-notify', 'ost-you-settings', 'ost-burn']) expect(got).toContain(present)
  })
})

describe('a menu under its button, a sheet on a phone', () => {
  it('sits under the button, right edges aligned, never taller than the window under it', async () => {
    const anchor = document.createElement('button')
    document.body.appendChild(anchor)
    anchor.getBoundingClientRect = () => ({ top: 60, bottom: 104, left: 1300, right: 1420, width: 120, height: 44, x: 1300, y: 60, toJSON() {} }) as DOMRect
    Object.defineProperty(window, 'innerWidth', { value: 1440, configurable: true })
    Object.defineProperty(window, 'innerHeight', { value: 768, configurable: true })
    mount(ChatSettingsMenu, { props: { ...base, surface: 'popover', kind: 'room', room: ROOM, anchor }, ...opts })
    await flushPromises()
    const el = document.querySelector('[data-testid="ost-menu-sheet"]') as HTMLElement
    expect(el.dataset.surface).toBe('popover')
    expect(el.style.top).toBe('112px')
    expect(el.style.right).toBe('20px')
    expect(el.style.maxHeight).toBe(`${768 - 112 - 12}px`)
  })

  it('a click outside closes the menu; a click on its button does not (the button toggles it)', async () => {
    const anchor = document.createElement('button')
    document.body.appendChild(anchor)
    const w = mount(ChatSettingsMenu, { props: { ...base, surface: 'popover', kind: 'room', room: ROOM, anchor }, ...opts })
    await flushPromises()
    anchor.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(w.emitted('close')).toBeUndefined()
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('the phone sheet closes on its scrim', async () => {
    const w = mount(ChatSettingsMenu, { props: { ...base, surface: 'sheet', kind: 'dm' }, ...opts })
    await flushPromises()
    ;(document.querySelector('[data-testid="csm-scrim"]') as HTMLElement).click()
    expect(w.emitted('close')).toHaveLength(1)
  })
})

describe('the keyboard', () => {
  it('opens on the first row; arrows, Home and End move; Enter picks; Escape closes', async () => {
    const w = mount(ChatSettingsMenu, { props: { ...base, surface: 'popover', kind: 'room', room: ROOM }, ...opts })
    await flushPromises()
    const root = document.querySelector('[data-testid="ost-menu-sheet"]') as HTMLElement
    const at = () => (document.activeElement as HTMLElement)?.getAttribute('data-testid')
    expect(at()).toBe('ost-room-members')
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(at()).toBe('ost-room-settings')
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }))
    expect(at()).toBe('ost-burn')
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(at()).toBe('ost-room-members')                       // wraps
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
    expect(at()).toBe('ost-burn')
    ;(document.activeElement as HTMLElement).click()
    expect(w.emitted('pick')).toEqual([['burn']])
    root.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
  })
})
