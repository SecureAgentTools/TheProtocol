/**
 * §COOKIES (2026-10-02, his words "voice replies default off, add the switch to desktop too"): the desktop assistant
 * dock carries the same voice-replies switch as Pocket. It starts off and reads nothing aloud; one press turns it on,
 * stores the one choice Pocket reads too, and only then does an answer reach the speech engine (the control).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

const h = vi.hoisted(() => {
  const speak = vi.fn()
  const cancel = vi.fn()
  ;(globalThis as any).speechSynthesis = { speak, cancel }
  ;(globalThis as any).SpeechSynthesisUtterance = class { lang = ''; rate = 1; constructor(public text: string) {} }
  return { speak, cancel, opts: null as null | { speak: (say: string) => void } }
})

vi.mock('@/composables/useAssistantBrains', async () => {
  const { ref } = await import('vue')
  return {
    useAssistantBrains: (opts: { speak: (say: string) => void }) => {
      h.opts = opts
      return {
        brain: ref('grammar'), status: ref(null), busy: ref(false), msgs: ref([]), brainNote: ref(''), byoKey: ref(''),
        saveByoKey: () => {}, openDoor: () => {}, handle: async () => {}, loadCtx: async () => {}, loadStatus: async () => {},
      }
    },
  }
})

import AssistantDock from './AssistantDock.vue'

beforeEach(() => { localStorage.clear(); h.speak.mockClear(); h.opts = null })

describe('the desktop assistant dock', () => {
  it('shows the voice-replies switch, off by default, and reads nothing aloud', () => {
    const w = mount(AssistantDock)
    const sw = w.find('[data-testid="ad-tts"]')
    expect(sw.exists()).toBe(true)
    expect(sw.attributes('aria-pressed')).toBe('false')
    h.opts!.speak('Your balance is 12 ECU')
    expect(h.speak).not.toHaveBeenCalled()
  })

  it('turns voice replies on with one press, stores the choice Pocket reads, and then speaks', async () => {
    const w = mount(AssistantDock)
    await w.find('[data-testid="ad-tts"]').trigger('click')
    expect(w.find('[data-testid="ad-tts"]').attributes('aria-pressed')).toBe('true')
    expect(localStorage.getItem('tp_voice_replies')).toBe('on')
    h.opts!.speak('Your balance is 12 ECU')
    expect(h.speak).toHaveBeenCalledTimes(1)
    await w.find('[data-testid="ad-tts"]').trigger('click')
    expect(localStorage.getItem('tp_voice_replies')).toBe('off')
  })
})
