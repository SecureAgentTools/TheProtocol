/**
 * composables/useVoice.ts — §POCKETBRIDGE3 WS-B2/B4: ears + mouth.
 *
 * Web Speech API only — no model, no key, no cloud beyond the browser's own
 * speech service. `supported` is a FEATURE DETECT and the UI must explain
 * absence instead of hiding (iOS Safari/PWA SpeechRecognition is
 * version-dependent — B4). The brain lives in services/voice/intentGrammar
 * (pure); this composable only listens and speaks.
 */
import { ref, onBeforeUnmount } from 'vue'

const SR: any =
  (globalThis as any).SpeechRecognition || (globalThis as any).webkitSpeechRecognition || null

export const speechSupported = !!SR
export const ttsSupported = typeof globalThis.speechSynthesis !== 'undefined'

const REPLIES_KEY = 'tp_voice_replies'

/** §COOKIES (2026-10-02, his word "voice replies default off"): an answer is read aloud only after the person switches
 *  voice replies on, in Pocket or in the desktop dock (one stored choice). A reply read aloud can leave the device
 *  (Chrome may speak it with an online Google voice), so it is never a default: a browser that never chose starts
 *  silent, and storage that refuses to answer reads as off. */
function storedReplies(): boolean {
  try { return localStorage.getItem(REPLIES_KEY) === 'on' } catch { return false }
}

export function useVoice() {
  const listening = ref(false)
  const interim = ref('')
  const error = ref('')
  const voiceReplies = ref(storedReplies())
  let rec: any = null

  function setReplies(on: boolean) {
    voiceReplies.value = on
    try { localStorage.setItem(REPLIES_KEY, on ? 'on' : 'off') } catch { /* private mode */ }
    if (!on) stopSpeaking()
  }

  /** Hold-to-talk: start on press; resolve the final transcript via onFinal. */
  function start(onFinal: (utterance: string) => void) {
    if (!SR || listening.value) return
    error.value = ''
    interim.value = ''
    rec = new SR()
    rec.lang = navigator.language || 'en-US'
    rec.interimResults = true
    rec.continuous = false
    let finalText = ''
    rec.onresult = (ev: any) => {
      let txt = ''
      for (let i = 0; i < ev.results.length; i++) txt += ev.results[i][0].transcript
      interim.value = txt
      if (ev.results[ev.results.length - 1].isFinal) finalText = txt
    }
    rec.onerror = (ev: any) => {
      // 'no-speech' on release is normal silence, not a failure worth alarming
      if (ev?.error && ev.error !== 'no-speech' && ev.error !== 'aborted') {
        error.value = ev.error === 'not-allowed'
          ? 'Microphone permission denied — allow it in your browser settings.'
          : `Speech error: ${ev.error}`
      }
      listening.value = false
    }
    rec.onend = () => {
      listening.value = false
      const heard = (finalText || interim.value).trim()
      interim.value = ''
      if (heard) onFinal(heard)
    }
    try {
      rec.start()
      listening.value = true
    } catch {
      error.value = 'Could not start the microphone.'
      listening.value = false
    }
  }

  /** Release of hold-to-talk: stop capturing; onend delivers what was heard. */
  function stop() {
    try { rec?.stop() } catch { /* already stopped */ }
  }

  function speak(text: string) {
    if (!ttsSupported || !voiceReplies.value || !text) return
    try {
      const u = new SpeechSynthesisUtterance(text)
      u.lang = navigator.language || 'en-US'
      u.rate = 1.05
      speechSynthesis.cancel()
      speechSynthesis.speak(u)
    } catch { /* tts best-effort */ }
  }

  function stopSpeaking() {
    try { speechSynthesis.cancel() } catch { /* ok */ }
  }

  onBeforeUnmount(() => { stop(); stopSpeaking() })

  return { supported: speechSupported, tts: ttsSupported, listening, interim, error, voiceReplies, setReplies, start, stop, speak, stopSpeaking }
}
