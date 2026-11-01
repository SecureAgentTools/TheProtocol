import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ChatBurnConfirm from './ChatBurnConfirm.vue'
import ChatNotifySheet from './ChatNotifySheet.vue'
import ChatRoomSettings from './ChatRoomSettings.vue'
import { muteInEffect, muteUntil } from '@/services/chat/notifyLevel'

/**
 * V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): the sheets the settings menu opens, to session-lead's review (seq
 * 397): burn says what happens first, names the thread's real host (1), "any copy on this device" (2), and its hold
 * needs a fresh press, by pointer or by Space or Enter, with Cancel focused (4, 6); notifications with a mute that ends
 * by itself, its end with its day (9); the room's settings, read only for a member, and an unsaved edit asks before it
 * is discarded (13). BASE (V0651): none of these exist (a 0.9 s pointer-only hold with no sentence; a bare mute flip).
 */
const stubs = { global: { stubs: { Icon: true, RouterLink: true, 'router-link': true } }, attachTo: document.body }
afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

describe('burn for you', () => {
  it('names the thread\'s host and its copies, never a literal', () => {
    const w = mount(ChatBurnConfirm, { props: { hosting: { registry: 'ASIA', copies: ['EU'] } }, ...stubs })
    expect(w.find('[data-testid="cbc-kept"]').text()).toBe('The others keep theirs. ASIA keeps the thread until your account is deleted; EU keep their copies.')
    expect(w.text()).toContain('Any copy on this device is deleted now.')
    expect(w.find('[data-testid="cbc-yours"]').text()).toContain('your account, on every device')
    const unknown = mount(ChatBurnConfirm, { props: { hosting: null }, ...stubs })
    expect(unknown.find('[data-testid="cbc-kept"]').text()).toContain('The registry that hosts it keeps the thread')
  })

  it('Cancel has the focus; a pointer held 1.2 s burns, a shorter one does not', async () => {
    vi.useFakeTimers()
    const w = mount(ChatBurnConfirm, { props: { hosting: { registry: 'EU' } }, ...stubs })
    await flushPromises()
    expect((document.activeElement as HTMLElement).getAttribute('data-testid')).toBe('cbc-cancel')
    const hold = w.find('[data-testid="ost-burn-hold"]')
    await hold.trigger('pointerdown')
    vi.advanceTimersByTime(800)
    await hold.trigger('pointerup')
    vi.advanceTimersByTime(2000)
    expect(w.emitted('burn')).toBeUndefined()
    await hold.trigger('pointerdown')
    vi.advanceTimersByTime(1300)
    expect(w.emitted('burn')).toHaveLength(1)
  })

  it('a held key from the menu (a repeat) never starts it; a fresh Space held 1.2 s does', async () => {
    vi.useFakeTimers()
    const w = mount(ChatBurnConfirm, { props: { hosting: { registry: 'EU' } }, ...stubs })
    const hold = w.find('[data-testid="ost-burn-hold"]')
    await hold.trigger('keydown', { key: 'Enter', repeat: true })
    vi.advanceTimersByTime(3000)
    expect(w.emitted('burn')).toBeUndefined()
    await hold.trigger('keydown', { key: ' ' })
    vi.advanceTimersByTime(600)
    await hold.trigger('keyup', { key: ' ' })
    vi.advanceTimersByTime(2000)
    expect(w.emitted('burn')).toBeUndefined()
    await hold.trigger('keydown', { key: ' ' })
    vi.advanceTimersByTime(1300)
    expect(w.emitted('burn')).toHaveLength(1)
  })
})

describe('a hold whose key-up never comes stops (session-lead, seq 406)', () => {
  it.each([
    ['its button loses the focus', (hold: any) => hold.trigger('blur')],
    ['the window loses the focus', () => window.dispatchEvent(new Event('blur'))],
    ['the tab hides', () => {
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    }],
  ])('when %s', async (_why, leave) => {
    vi.useFakeTimers()
    const w = mount(ChatBurnConfirm, { props: { hosting: { registry: 'EU' } }, ...stubs })
    const hold = w.find('[data-testid="ost-burn-hold"]')
    await hold.trigger('keydown', { key: ' ' })
    vi.advanceTimersByTime(500)
    await leave(hold)
    vi.advanceTimersByTime(3000)
    expect(w.emitted('burn')).toBeUndefined()
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
  })
})

describe('notifications here', () => {
  it('the levels say what reaches you, per kind', () => {
    const room = mount(ChatNotifySheet, { props: { kind: 'room', muted: false }, ...stubs })
    expect(room.find('[data-testid="cns-level-needs"]').text()).toContain('Mentions and asks')
    expect(room.find('[data-testid="cns-level-muted"]').text()).toContain('Only asks for me')
    expect(mount(ChatNotifySheet, { props: { kind: 'dm', muted: false }, ...stubs }).find('[data-testid="cns-level-needs"]').text())
      .toContain('Every message')
    expect(mount(ChatNotifySheet, { props: { kind: 'support', muted: false }, ...stubs }).find('[data-testid="cns-level-muted"]').text())
      .toContain('Nothing from this thread')
  })

  it('a mute for 8 hours ends then, and says so with its day when that is not today', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-31T23:35:00Z'))
    const w = mount(ChatNotifySheet, { props: { kind: 'room', muted: false }, ...stubs })
    await w.find('[data-testid="cns-level-muted"]').trigger('click')
    await w.find('[data-testid="cns-for-8h"]').trigger('click')
    const line = w.find('[data-testid="cns-until"]').text()
    expect(line).toMatch(/Muted until .*\d{1,2}[:.]\d{2}( ?[AP]M)?, then mentions and asks again\./)
    expect(line).toMatch(/1 Nov|Nov 1/)                                   // tomorrow: the day is named
    await w.find('[data-testid="cns-done"]').trigger('click')
    const [[v]] = w.emitted('save') as any
    expect(v.muted).toBe(true)
    expect(v.until).toBe('2026-11-01T07:35:00.000Z')
    expect(v.keep).toBe(false)
  })

  it('done without a change changes nothing', async () => {
    const w = mount(ChatNotifySheet, { props: { kind: 'dm', muted: true, mutedUntil: '2099-01-01T00:00:00Z' }, ...stubs })
    await w.find('[data-testid="cns-done"]').trigger('click')
    expect((w.emitted('save') as any)[0][0].keep).toBe(true)
  })
})

describe('the room\'s settings', () => {
  const props = { title: 'TheProtocol Sessions', topic: 'the sessions coordinate here', rules: 'One point per message.',
    mode: 'open', assistantPresent: true }

  it('an owner or an admin edits the topic and the rules; Save says what changed', async () => {
    const w = mount(ChatRoomSettings, { props: { ...props, isOperator: true }, ...stubs })
    expect(w.find('[data-testid="crs-save"]').attributes('disabled')).toBeDefined()
    await w.find('[data-testid="crs-topic"]').setValue('the sessions coordinate here, one point a message')
    await w.find('[data-testid="crs-save"]').trigger('click')
    expect(w.emitted('save')).toEqual([[{ topic: 'the sessions coordinate here, one point a message', rules: 'One point per message.',
      topicChanged: true, rulesChanged: false }]])
    expect(w.find('[data-testid="crs-assistant"]').text()).toBe('On')                // shown here, switched from the menu
  })

  it('closing with an edit not saved asks first', async () => {
    const w = mount(ChatRoomSettings, { props: { ...props, isOperator: true }, ...stubs })
    await w.find('[data-testid="crs-rules"]').setValue('new rules')
    await w.find('[data-testid="crs-close"]').trigger('click')
    expect(w.emitted('close')).toBeUndefined()
    expect(w.find('[data-testid="crs-discard"]').exists()).toBe(true)
    await w.find('[data-testid="crs-keep"]').trigger('click')
    expect(w.find('[data-testid="crs-rules"]').element as HTMLTextAreaElement).toBeTruthy()
    await w.find('[data-testid="crs-close"]').trigger('click')
    await w.find('[data-testid="crs-discard-go"]').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('who may post asks the thread for its held confirm', async () => {
    const w = mount(ChatRoomSettings, { props: { ...props, isOperator: true }, ...stubs })
    await w.find('[data-testid="crs-mode-announce"]').trigger('click')
    expect(w.emitted('mode')).toEqual([['announce']])
  })

  it('a member reads the same settings and edits none', () => {
    const w = mount(ChatRoomSettings, { props: { ...props, isOperator: false }, ...stubs })
    expect(w.find('[data-testid="crs-topic-ro"]').text()).toBe('the sessions coordinate here')
    expect(w.find('[data-testid="crs-rules-ro"]').text()).toBe('One point per message.')
    expect(w.find('[data-testid="crs-mode-ro"]').text()).toBe('Everyone in the organization')
    expect(w.find('input, textarea').exists()).toBe(false)
    expect(w.find('[data-testid="crs-save"]').exists()).toBe(false)
  })
})

describe('a mute that ends by itself (the server\'s rule)', () => {
  it('lengths, and whether a mute is on now', () => {
    const now = Date.parse('2026-10-31T23:35:00Z')
    expect(muteUntil('1h', now)).toBe('2026-11-01T00:35:00.000Z')
    expect(muteUntil('1d', now)).toBe('2026-11-01T23:35:00.000Z')
    expect(muteUntil('forever', now)).toBe(null)
    expect(muteInEffect(true, null, now)).toBe(true)
    expect(muteInEffect(true, '2026-11-01T00:00:00Z', now)).toBe(true)
    expect(muteInEffect(true, '2026-10-31T23:00:00Z', now)).toBe(false)
    expect(muteInEffect(false, '2026-11-01T00:00:00Z', now)).toBe(false)
  })
})
