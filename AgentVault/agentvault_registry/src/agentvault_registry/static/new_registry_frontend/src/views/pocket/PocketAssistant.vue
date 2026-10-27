<!-- POCKET · Assistant (§POCKETBRIDGE3 WS-D, 2026-08-22) — one panel, three brains, and every
     message NAMES ITS BRAIN (S1): the deterministic grammar (default, free, private), the
     PERSONAL Claude Code bridge (admin-only, flag-gated server-side), and a BYO Anthropic API
     key (client-side only, never server-persisted). Money rule (D5 = the voice iron rule):
     any brain may PREFILL and OPEN a door — only the human confirms, on the app's own screens. -->
<template>
  <div class="pa-wrap">
    <div class="pa-head">
      <h1 class="pa-title"><Icon name="mdi:robot-outline" /> {{ t('pocket.assistant.title', 'Assistant') }}</h1>
      <button class="pa-tts" :class="{ off: !voice.voiceReplies.value }" data-testid="pa-tts" :aria-pressed="voice.voiceReplies.value ? 'true' : 'false'" @click="voice.setReplies(!voice.voiceReplies.value)" :aria-label="voice.voiceReplies.value ? t('pocket.assistant.ttsOn', 'Voice replies on') : t('pocket.assistant.ttsOff', 'Voice replies off')">
        <Icon :name="voice.voiceReplies.value ? 'mdi:volume-high' : 'mdi:volume-off'" />
      </button>
    </div>

    <!-- brain selector — S1: the active brain is always visible -->
    <div class="pa-brains" data-testid="pa-brains" data-tour="pk-assistant">
      <button class="pa-brain" :class="{ active: brain === 'grammar' }" @click="brain = 'grammar'">
        <Icon name="mdi:cog" /> {{ t('pocket.assistant.brainCommands', 'Commands') }}
      </button>
      <button v-if="status?.bridge?.enabled" class="pa-brain" :class="{ active: brain === 'bridge' }" data-testid="pa-brain-bridge" @click="brain = 'bridge'">
        <Icon name="mdi:robot-outline" /> {{ t('pocket.assistant.claudePersonal', 'Claude (personal)') }}
      </button>
      <button class="pa-brain" :class="{ active: brain === 'byo' }" data-testid="pa-brain-byo" @click="brain = 'byo'">
        <Icon name="mdi:key-outline" /> {{ t('pocket.assistant.claudeApiKey', 'Claude (API key)') }}
      </button>
    </div>
    <p class="pa-brain-note" data-testid="pa-brain-note">{{ brainNote }}</p>

    <!-- BYO key row (client-side only) -->
    <div v-if="brain === 'byo'" class="pa-byo">
      <input v-model="byoKey" class="pa-in" type="password" :placeholder="t('pocket.assistant.keyPlaceholder', 'sk-ant-… (stays in this browser)')" :aria-label="t('pocket.assistant.keyLabel', 'Anthropic API key')" @change="saveByoKey" />
      <p class="pa-note">{{ t('pocket.assistant.keyNote', "Your key is stored ONLY in this browser (localStorage) and calls Anthropic directly — it never touches this registry's servers.") }}</p>
    </div>

    <!-- transcript -->
    <div ref="feedEl" class="pa-feed" data-testid="pa-feed">
      <div v-if="!msgs.length" class="pa-empty">
        <Icon name="mdi:microphone" class="pa-empty-ico" />
        <p>{{ voice.supported ? t('pocket.assistant.askVoice', 'Ask by typing or hold the mic. Try:') : t('pocket.assistant.askType', 'Ask by typing. Try:') }}</p>
        <ul class="pa-caps">
          <li v-for="c in caps" :key="c">{{ c }}</li>
        </ul>
        <p v-if="!voice.supported" class="pa-note" data-testid="pa-novoice">
          {{ t('pocket.assistant.noVoice', "Voice input isn't available in this browser (iOS Safari/PWA support varies) — typing works everywhere, and voice replies still speak when supported.") }}
        </p>
      </div>
      <div v-for="m in msgs" :key="m.id" class="pa-msg" :class="m.role">
        <div class="pa-bubble">
          <span v-if="m.role === 'assistant'" class="pa-brain-tag">{{ m.brain }}</span>
          <p class="pa-txt">{{ m.text }}</p>
          <p v-if="m.unresolved" class="pa-unres">{{ m.unresolved }}</p>
          <button v-if="m.door" class="pa-door" data-testid="pa-door" @click="openDoor(m.door)">
            <Icon name="mdi:arrow-right" /> {{ m.doorLabel || t('pocket.assistant.open', 'Open') }}
          </button>
        </div>
      </div>
      <div v-if="busy" class="pa-msg assistant"><div class="pa-bubble"><span class="pa-brain-tag">{{ brainLabel }}</span><p class="pa-txt pa-thinking">…</p></div></div>
    </div>

    <p v-if="voice.error.value" class="pa-err" data-testid="pa-voice-err">{{ voice.error.value }}</p>
    <p v-if="voice.listening.value" class="pa-listening" data-testid="pa-listening"><Icon name="mdi:microphone" /> {{ voice.interim.value || t('pocket.assistant.listeningRelease', 'Listening… release to send') }}</p>

    <!-- composer -->
    <form class="pa-compose" @submit.prevent="submit">
      <button
        v-if="voice.supported"
        type="button"
        class="pa-mic"
        :class="{ live: voice.listening.value }"
        data-testid="pa-mic"
        :aria-label="t('pocket.shell.holdToTalk', 'Hold to talk')"
        @pointerdown.prevent="micDown"
        @pointerup.prevent="micUp"
        @pointerleave="micUp"
        @pointercancel="micUp"
      ><Icon name="mdi:microphone" /></button>
      <input v-model="draft" class="pa-in" data-testid="pa-input" type="text" :placeholder="t('pocket.assistant.composePlaceholder', 'Ask or command…')" :aria-label="t('pocket.assistant.message', 'Message')" />
      <button type="submit" class="pa-send" data-testid="pa-send" :disabled="!draft.trim() || busy" :aria-label="t('pocket.assistant.send', 'Send')"><Icon name="mdi:send" /></button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import Icon from '@/components/Icon.vue'
import { useAssistantBrains } from '@/composables/useAssistantBrains'
import { useVoice } from '@/composables/useVoice'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const voice = useVoice()
const feedEl = ref<HTMLElement | null>(null)
const draft = ref('')

// §POCKETBRIDGE4 WS-P — the brains moved to ONE composable shared with the
// bridge dock; this view keeps the phone shell: mic, TTS, auto-opening doors.
const brains = useAssistantBrains({
  speak: (say: string) => voice.speak(say),   // param is `say`, not `t` (shadowing)
  onPush: () => { void nextTick(() => { feedEl.value?.scrollTo({ top: feedEl.value.scrollHeight }) }) },
  autoOpenDoors: true,
})
const { brain, status, busy, msgs, caps, brainLabel, brainNote, byoKey, saveByoKey, openDoor } = brains
const handle = brains.handle

function submit() { const u = draft.value; draft.value = ''; void handle(u) }

/* hold-to-talk */
let micHeld = false
function micDown() {
  if (micHeld) return
  micHeld = true
  voice.start((heard) => { void handle(heard) })
}
function micUp() {
  if (!micHeld) return
  micHeld = false
  voice.stop()
}

onMounted(async () => {
  void brains.loadCtx()
  await brains.loadStatus()
  // handoff from the shell mic (PocketShell captures, this panel answers)
  try {
    const pending = sessionStorage.getItem('tp_assistant_heard')
    if (pending) { sessionStorage.removeItem('tp_assistant_heard'); void handle(pending) }
  } catch { /* ok */ }
  // §POCKETBRIDGE4 WS-H — a Web Share lands as a DRAFT in the composer, never
  // auto-submitted: shared text is data, not a command.
  try {
    const shared = sessionStorage.getItem('tp_assistant_draft')
    if (shared) { sessionStorage.removeItem('tp_assistant_draft'); draft.value = shared }
  } catch { /* ok */ }
})
</script>

<style scoped>
.pa-wrap { max-width: 560px; margin: 0 auto; padding: 1rem 1rem 5.5rem; box-sizing: border-box; display: flex; flex-direction: column; min-height: calc(100dvh - 140px); }
.pa-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.6rem; }
.pa-title { font-size: 1.15rem; margin: 0; display: flex; align-items: center; gap: 0.4rem; flex: 1 1 auto; }
.pa-title :deep(svg) { width: 1.1rem; height: 1.1rem; color: var(--nc-primary, #00d4ff); }
.pa-tts { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #e6edf3; width: 44px; height: 44px; display: grid; place-items: center; cursor: pointer; }
.pa-tts.off { opacity: 0.45; }
.pa-tts :deep(svg) { width: 1.05rem; height: 1.05rem; }

.pa-brains { display: flex; gap: 0.35rem; }
.pa-brain { display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); color: rgba(230,237,243,0.7); border-radius: 999px; padding: 0.3rem 0.65rem; min-height: 44px; font-size: 0.72rem; font-weight: 700; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pa-brain.active { background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.35); color: var(--nc-primary, #00d4ff); }
.pa-brain :deep(svg) { width: 0.9rem; height: 0.9rem; }
.pa-brain-note { font-size: 0.68rem; opacity: 0.55; margin: 0.35rem 0 0.5rem; }
.pa-byo { margin-bottom: 0.5rem; }

.pa-feed { flex: 1 1 auto; overflow-y: auto; display: flex; flex-direction: column; gap: 0.45rem; padding: 0.2rem 0; min-height: 8rem; }
.pa-empty { text-align: center; opacity: 0.75; font-size: 0.8rem; padding: 1rem 0.5rem; }
.pa-empty-ico { width: 2rem; height: 2rem; opacity: 0.35; display: block; margin: 0 auto 0.4rem; }
.pa-caps { list-style: none; margin: 0.5rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.7rem; opacity: 0.8; text-align: left; }
.pa-msg { display: flex; }
.pa-msg.user { justify-content: flex-end; }
.pa-bubble { max-width: 86%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); border-radius: 14px; padding: 0.5rem 0.7rem; }
.pa-msg.user .pa-bubble { background: rgba(0,212,255,0.08); border-color: rgba(0,212,255,0.25); }
.pa-brain-tag { display: inline-block; font-size: 0.58rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 800; margin-bottom: 0.2rem; }
.pa-txt { margin: 0; font-size: 0.82rem; white-space: pre-wrap; word-break: break-word; }
.pa-thinking { letter-spacing: 0.2em; animation: pa-blink 1s infinite; }
@keyframes pa-blink { 50% { opacity: 0.35; } }
.pa-unres { margin: 0.25rem 0 0; font-size: 0.7rem; color: #fbbf24; }
.pa-door { display: inline-flex; align-items: center; gap: 0.3rem; margin-top: 0.4rem; background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.35); color: #34d399; border-radius: 10px; padding: 0.3rem 0.6rem; min-height: 40px; font-size: 0.72rem; font-weight: 800; cursor: pointer; }
.pa-door :deep(svg) { width: 0.9rem; height: 0.9rem; }

.pa-err { font-size: 0.72rem; color: #ff9a9a; margin: 0.3rem 0 0; }
.pa-listening { display: flex; align-items: center; gap: 0.35rem; font-size: 0.76rem; color: var(--nc-primary, #00d4ff); margin: 0.3rem 0 0; }
.pa-listening :deep(svg) { width: 0.95rem; height: 0.95rem; animation: pa-blink 0.9s infinite; }

.pa-compose { display: flex; gap: 0.4rem; margin-top: 0.55rem; }
.pa-in { flex: 1 1 auto; min-width: 0; box-sizing: border-box; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 0.7rem 0.85rem; min-height: 44px; color: #e6edf3; font-size: 16px; outline: none; width: 100%; }
.pa-in:focus { border-color: rgba(0,212,255,0.45); }
.pa-mic { flex: 0 0 auto; width: 48px; min-height: 44px; border-radius: 12px; background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.3); color: var(--nc-primary, #00d4ff); display: grid; place-items: center; cursor: pointer; -webkit-tap-highlight-color: transparent; touch-action: none; }
.pa-mic.live { background: rgba(255,138,138,0.15); border-color: rgba(255,138,138,0.5); color: #ff8a8a; }
.pa-mic :deep(svg) { width: 1.15rem; height: 1.15rem; }
.pa-send { flex: 0 0 auto; width: 48px; min-height: 44px; border-radius: 12px; border: none; background: linear-gradient(135deg, #0891b2, #00d4ff); color: #04121a; display: grid; place-items: center; cursor: pointer; }
.pa-send:disabled { opacity: 0.4; }
.pa-send :deep(svg) { width: 1.05rem; height: 1.05rem; }
</style>
