<!-- ASSISTANT DOCK (§POCKETBRIDGE4 WS-P) — the same three-brain assistant, docked in the
     bridge terminal on the EXISTING rails discipline (§R3: docked in view, FULL VIEW one
     click away). One machine with Pocket (useAssistantBrains); on desktop, doors RENDER
     instead of auto-opening — a grammar hit shows its Open button and the human chooses,
     because a dock must never yank the bridge into another shell uninvited. -->
<template>
  <div class="ad-wrap" data-testid="assistant-dock">
    <div class="ad-brains">
      <button class="ad-brain" :class="{ on: brain === 'grammar' }" @click="brain = 'grammar'"><Icon name="mdi:cog" /> {{ t('pocket.assistant.brainCommands', 'Commands') }}</button>
      <button v-if="status?.bridge?.enabled" class="ad-brain" :class="{ on: brain === 'bridge' }" data-testid="ad-brain-bridge" @click="brain = 'bridge'"><Icon name="mdi:robot-outline" /> {{ t('pocket.assistant.claude', 'Claude') }}</button>
      <button class="ad-brain" :class="{ on: brain === 'byo' }" @click="brain = 'byo'"><Icon name="mdi:key-outline" /> {{ t('pocket.assistant.apiKey', 'API key') }}</button>
      <!-- §COOKIES: the same voice-replies switch as Pocket (one stored choice, off until switched on) -->
      <button v-if="voice.tts" class="ad-tts" :class="{ off: !voice.voiceReplies.value }" data-testid="ad-tts"
        :aria-pressed="voice.voiceReplies.value ? 'true' : 'false'"
        :aria-label="voice.voiceReplies.value ? t('pocket.assistant.ttsOn', 'Voice replies on') : t('pocket.assistant.ttsOff', 'Voice replies off')"
        :title="voice.voiceReplies.value ? t('pocket.assistant.ttsOn', 'Voice replies on') : t('pocket.assistant.ttsOff', 'Voice replies off')"
        @click="voice.setReplies(!voice.voiceReplies.value)">
        <Icon :name="voice.voiceReplies.value ? 'mdi:volume-high' : 'mdi:volume-off'" />
      </button>
      <button v-if="voice.supported" class="ad-mic" :class="{ live: voice.listening.value }" data-testid="ad-mic"
        :aria-label="t('pocket.shell.holdToTalk', 'Hold to talk')" @pointerdown.prevent="micDown" @pointerup.prevent="micUp" @pointerleave="micUp" @pointercancel="micUp">
        <Icon name="mdi:microphone" />
      </button>
    </div>
    <p class="ad-note">{{ brainNote }}</p>
    <div v-if="brain === 'byo'" class="ad-byo">
      <input v-model="byoKey" class="ad-in" type="password" :placeholder="t('pocket.assistant.keyPlaceholder', 'sk-ant-… (stays in this browser)')" :aria-label="t('pocket.assistant.keyLabel', 'Anthropic API key')" @change="saveByoKey" />
    </div>

    <div ref="feedEl" class="ad-feed" data-testid="ad-feed">
      <!-- The quoted commands stay English: this grammar only matches English. -->
      <p v-if="!msgs.length" class="ad-empty">{{ t('pocket.dock.emptyLead', 'Ask or command') }} — "what needs me" · "balance" · "buy 2 QCC at 120" {{ t('pocket.dock.emptyTail', '(doors open only when you tap them here).') }}</p>
      <div v-for="m in msgs" :key="m.id" class="ad-msg" :class="m.role">
        <span v-if="m.role === 'assistant'" class="ad-tag">{{ m.brain }}</span>
        <p class="ad-txt">{{ m.text }}</p>
        <p v-if="m.unresolved" class="ad-unres">{{ m.unresolved }}</p>
        <button v-if="m.door" class="ad-door" @click="openDoor(m.door)"><Icon name="mdi:arrow-right" /> {{ t('pocket.dock.openInPocket', 'Open in Pocket') }}</button>
      </div>
      <p v-if="busy" class="ad-txt ad-thinking">…</p>
    </div>
    <p v-if="voice.listening.value" class="ad-listening"><Icon name="mdi:microphone" /> {{ voice.interim.value || t('pocket.assistant.listening', 'Listening…') }}</p>

    <form class="ad-compose" @submit.prevent="submit">
      <input v-model="draft" class="ad-in" data-testid="ad-input" type="text" :placeholder="t('pocket.assistant.composePlaceholder', 'Ask or command…')" :aria-label="t('pocket.assistant.message', 'Message')" />
      <button type="submit" class="ad-send" data-testid="ad-send" :disabled="!draft.trim() || busy" :aria-label="t('pocket.assistant.send', 'Send')"><Icon name="mdi:send" /></button>
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
const brains = useAssistantBrains({
  speak: (say: string) => voice.speak(say),   // param is `say`, not `t` (shadowing)
  onPush: () => { void nextTick(() => { feedEl.value?.scrollTo({ top: feedEl.value.scrollHeight }) }) },
  autoOpenDoors: false, // desktop: render the door, never yank the shell
})
const { brain, status, busy, msgs, brainNote, byoKey, saveByoKey, openDoor } = brains
function submit() { const u = draft.value; draft.value = ''; void brains.handle(u) }
let held = false
function micDown() { if (held) return; held = true; voice.start((heard) => { void brains.handle(heard) }) }
function micUp() { if (!held) return; held = false; voice.stop() }
onMounted(() => { void brains.loadCtx(); void brains.loadStatus() })
</script>

<style scoped>
.ad-wrap { display: flex; flex-direction: column; gap: 0.4rem; min-height: 14rem; max-height: 24rem; }
.ad-brains { display: flex; align-items: center; gap: 0.3rem; }
.ad-brain { display: inline-flex; align-items: center; gap: 0.25rem; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); color: rgba(230,237,243,0.7); border-radius: 999px; padding: 0.25rem 0.55rem; font-size: 0.68rem; font-weight: 700; cursor: pointer; }
.ad-brain.on { background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.35); color: var(--nc-primary, #00d4ff); }
.ad-brain :deep(svg) { width: 0.8rem; height: 0.8rem; }
.ad-tts { margin-left: auto; width: 30px; height: 30px; border-radius: 8px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); color: #e6edf3; display: grid; place-items: center; cursor: pointer; }
.ad-tts.off { opacity: 0.45; }
.ad-tts :deep(svg) { width: 0.9rem; height: 0.9rem; }
.ad-tts + .ad-mic { margin-left: 0; }
.ad-mic { margin-left: auto; width: 30px; height: 30px; border-radius: 8px; background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.3); color: var(--nc-primary, #00d4ff); display: grid; place-items: center; cursor: pointer; touch-action: none; }
.ad-mic.live { color: #ff8a8a; border-color: rgba(255,138,138,0.5); }
.ad-mic :deep(svg) { width: 0.9rem; height: 0.9rem; }
.ad-note { font-size: 0.62rem; opacity: 0.5; margin: 0; }
.ad-feed { flex: 1 1 auto; overflow-y: auto; display: flex; flex-direction: column; gap: 0.35rem; padding: 0.2rem 0; }
.ad-empty { font-size: 0.7rem; opacity: 0.55; margin: 0; }
.ad-msg { border-left: 2px solid rgba(255,255,255,0.1); padding-left: 0.5rem; }
.ad-msg.user { border-color: rgba(0,212,255,0.4); }
.ad-tag { font-size: 0.55rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 800; }
.ad-txt { margin: 0.1rem 0 0; font-size: 0.76rem; white-space: pre-wrap; word-break: break-word; }
.ad-thinking { letter-spacing: 0.2em; animation: ad-blink 1s infinite; }
@keyframes ad-blink { 50% { opacity: 0.35; } }
.ad-unres { margin: 0.15rem 0 0; font-size: 0.64rem; color: #fbbf24; }
.ad-door { display: inline-flex; align-items: center; gap: 0.25rem; margin-top: 0.25rem; background: rgba(52,211,153,0.1); border: 1px solid rgba(52,211,153,0.35); color: #34d399; border-radius: 8px; padding: 0.2rem 0.5rem; font-size: 0.66rem; font-weight: 800; cursor: pointer; }
.ad-door :deep(svg) { width: 0.75rem; height: 0.75rem; }
.ad-listening { display: flex; align-items: center; gap: 0.3rem; font-size: 0.7rem; color: var(--nc-primary, #00d4ff); margin: 0; }
.ad-listening :deep(svg) { width: 0.85rem; height: 0.85rem; animation: ad-blink 0.9s infinite; }
.ad-compose { display: flex; gap: 0.3rem; }
.ad-in { flex: 1 1 auto; min-width: 0; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 9px; padding: 0.4rem 0.55rem; color: #e6edf3; font-size: 16px; outline: none; }
.ad-in:focus { border-color: rgba(0,212,255,0.45); }
.ad-send { width: 38px; border-radius: 9px; border: none; background: linear-gradient(135deg, #0891b2, #00d4ff); color: #04121a; display: grid; place-items: center; cursor: pointer; }
.ad-send:disabled { opacity: 0.4; }
.ad-send :deep(svg) { width: 0.9rem; height: 0.9rem; }
</style>
