/**
 * §COOKIES (2026-10-02, his word "voice replies default off"): an answer is read aloud only after the person switches
 * voice replies on. A browser that never stored a choice starts silent (it used to start speaking), an explicit choice
 * survives the next visit, and storage that refuses to answer reads as off. The second test is the control: the same
 * speak() call does reach the speech engine once replies are on, so the silence in the first is the default at work.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

const tts = vi.hoisted(() => {
  const speak = vi.fn()
  const cancel = vi.fn()
  ;(globalThis as any).speechSynthesis = { speak, cancel }
  ;(globalThis as any).SpeechSynthesisUtterance = class { lang = ''; rate = 1; constructor(public text: string) {} }
  return { speak, cancel }
})

import { useVoice } from './useVoice'

function withVoice() {
  let voice!: ReturnType<typeof useVoice>
  mount(defineComponent({ setup() { voice = useVoice(); return () => h('div') } }))
  return voice
}

beforeEach(() => { localStorage.clear(); tts.speak.mockClear() })
afterEach(() => { vi.unstubAllGlobals() })

describe('voice replies', () => {
  it('are off in a browser that never chose, and nothing is read aloud', () => {
    const voice = withVoice()
    expect(voice.voiceReplies.value).toBe(false)
    voice.speak('Your balance is 12 ECU')
    expect(tts.speak).not.toHaveBeenCalled()
  })

  it('speak once switched on, and the choice is kept for the next visit', () => {
    const voice = withVoice()
    voice.setReplies(true)
    expect(localStorage.getItem('tp_voice_replies')).toBe('on')
    voice.speak('Your balance is 12 ECU')
    expect(tts.speak).toHaveBeenCalledTimes(1)
    expect(withVoice().voiceReplies.value).toBe(true)
  })

  it('stay off after an explicit off, and read as off when storage refuses', () => {
    localStorage.setItem('tp_voice_replies', 'off')
    expect(withVoice().voiceReplies.value).toBe(false)
    localStorage.setItem('tp_voice_replies', 'on')
    // a browser that blocks site data throws on every storage call (happy-dom's storage ignores a prototype spy)
    const refuse = () => { throw new Error('SecurityError') }
    vi.stubGlobal('localStorage', { getItem: refuse, setItem: refuse, removeItem: refuse })
    expect(withVoice().voiceReplies.value).toBe(false)
  })
})
