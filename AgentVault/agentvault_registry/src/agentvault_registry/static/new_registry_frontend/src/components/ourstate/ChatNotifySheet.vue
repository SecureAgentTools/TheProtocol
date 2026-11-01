<!--
  V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): what this thread pushes to you. Two levels: what needs you (a room's
  mentions and the asks that wait on you; every message of a direct chat; every reply of a ticket) or muted. A mute can
  last an hour, 8 hours or a day and then ends by itself (the server's muted_until), or holds until changed. Asks that
  wait on you (approvals and choices) reach you even here muted (the server lets them through). The end of a mute shows
  its day when it is not today (session-lead's review item 9). Quiet hours and channels live in Settings: one door.
-->
<template>
  <div class="ost-sheet-veil" @click.self="emit('cancel')">
    <div class="ost-sheet cns" role="dialog" aria-modal="true" :aria-label="t('ourstate.notify.title', 'Notifications here')"
         data-testid="ost-notify-sheet">
      <h3>{{ t('ourstate.notify.title', 'Notifications here') }}<small v-if="title">{{ title }}</small></h3>
      <div class="cns-opts" role="radiogroup">
        <button class="cns-opt" role="radio" :aria-checked="!pickMuted ? 'true' : 'false'" :class="{ on: !pickMuted }"
                data-testid="cns-level-needs" @click="pickMuted = false">
          <span class="cns-dot" aria-hidden="true" />
          <span class="cns-tx">{{ needsLabel }}<small>{{ needsSub }}</small></span>
        </button>
        <button class="cns-opt" role="radio" :aria-checked="pickMuted ? 'true' : 'false'" :class="{ on: pickMuted }"
                data-testid="cns-level-muted" @click="pickMuted = true">
          <span class="cns-dot" aria-hidden="true" />
          <span class="cns-tx">{{ kind === 'support' ? t('ourstate.notify.muted', 'Muted') : t('ourstate.notify.asksOnly', 'Only asks for me') }}<small>{{ kind === 'support'
            ? t('ourstate.notify.mutedSubSupport', 'Nothing from this thread.')
            : t('ourstate.notify.asksOnlySub', 'Muted: nothing from here but the approvals and choices that wait on you.') }}</small></span>
        </button>
      </div>
      <div v-if="pickMuted" class="cns-for" role="radiogroup" :aria-label="t('ourstate.notify.forHow', 'For how long')">
        <button v-for="d in DURATIONS" :key="d.key" class="cns-chip" role="radio" :aria-checked="pickFor === d.key ? 'true' : 'false'"
                :class="{ on: pickFor === d.key }" :data-testid="`cns-for-${d.key}`" @click="pickFor = d.key">{{ t(d.i18n, d.text) }}</button>
      </div>
      <p v-if="pickMuted && untilLine" class="cns-until" data-testid="cns-until">{{ untilLine }}</p>
      <p class="cns-note">{{ t('ourstate.notify.note', 'Your quiet hours apply on top, except to asks that wait on you. A muted thread keeps no unread count.') }}
        <router-link class="cns-door" to="/settings?tab=notifications" data-testid="cns-quiet" @click="emit('cancel')">{{ t('ourstate.notify.quiet', 'Quiet hours and channels') }} ›</router-link></p>
      <p v-if="error" class="cns-err" data-testid="cns-err">{{ error }}</p>
      <div class="ost-sheet-btns">
        <button class="ost-btn" data-testid="cns-cancel" @click="emit('cancel')">{{ t('common.cancel', 'Cancel') }}</button>
        <button class="ost-btn ost-accept" data-testid="cns-done" :disabled="busy" @click="done">{{ t('ourstate.notify.done', 'Done') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { timeLabel } from '@/services/chat/messageText'
import { muteUntil, type MuteFor } from '@/services/chat/notifyLevel'

const props = withDefaults(defineProps<{
  kind: 'room' | 'dm' | 'support'
  title?: string
  muted: boolean
  mutedUntil?: string | null
  busy?: boolean
  error?: string
}>(), { title: '', mutedUntil: null, busy: false, error: '' })
const emit = defineEmits<{ (e: 'cancel'): void; (e: 'save', v: { muted: boolean; until: string | null; keep: boolean }): void }>()
const { t, tp } = useI18n()

const DURATIONS: Array<{ key: MuteFor; i18n: string; text: string }> = [
  { key: '1h', i18n: 'ourstate.notify.for1h', text: '1 hour' },
  { key: '8h', i18n: 'ourstate.notify.for8h', text: '8 hours' },
  { key: '1d', i18n: 'ourstate.notify.for1d', text: '1 day' },
  { key: 'forever', i18n: 'ourstate.notify.forever', text: 'Until I change it' },
]

const pickMuted = ref(props.muted)
/* a mute already running keeps its end unless another length is picked */
const pickFor = ref<MuteFor | null>(props.muted ? (props.mutedUntil ? null : 'forever') : '8h')

const needsLabel = computed(() => props.kind === 'room' ? t('ourstate.notify.needs', 'Mentions and asks')
  : props.kind === 'dm' ? t('ourstate.notify.every', 'Every message') : t('ourstate.notify.everyReply', 'Every reply'))
const needsSub = computed(() => props.kind === 'room'
  ? t('ourstate.notify.needsSub', "When someone names you, and every approval or choice that waits on you. The room's other messages show when you open it.")
  : props.kind === 'dm' ? t('ourstate.notify.everySub', 'Each message in this chat.') : t('ourstate.notify.everyReplySub', 'Each reply from the support desk.'))

const nowMs = Date.now()
const untilIso = computed<string | null>(() => {
  if (!pickMuted.value) return null
  if (pickFor.value == null) return props.mutedUntil
  return muteUntil(pickFor.value, nowMs)
})
const untilLine = computed(() => {
  if (!untilIso.value) return ''
  return tp('ourstate.notify.until', 'Muted until {when}, then {level} again.',
            { when: timeLabel(untilIso.value, nowMs, appLocale()), level: needsLabel.value.toLowerCase() })
})

function done() {
  const keep = pickMuted.value === props.muted && (pickFor.value == null || (!props.muted && !pickMuted.value))
  emit('save', { muted: pickMuted.value, until: untilIso.value, keep })
}
</script>

<style scoped>
/* the chat's sheet, as the thread draws its own (its scoped rules do not reach a child component) */
.ost-sheet-veil { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: flex-end; justify-content: center; z-index: 60; }
.ost-sheet { width: 100%; max-width: 480px; max-height: 82vh; overflow-y: auto; background: var(--surface-1, #16181d); border-radius: 16px 16px 0 0;
  padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 10px; }
.ost-sheet-btns { display: flex; gap: 8px; justify-content: flex-end; }
.ost-sheet-input { width: 100%; min-height: 44px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3));
  background: none; color: inherit; font: inherit; font-size: 16px; box-sizing: border-box; }
.ost-btn { min-height: 44px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none;
  color: inherit; font-weight: 600; cursor: pointer; }
.ost-accept { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
.ost-danger { background: var(--warning-color, #f59e0b); color: #1a1206; border-color: transparent; }
.ost-btn:disabled { opacity: .4; cursor: not-allowed; filter: saturate(.4); }
.cns h3 { margin: 0; font-weight: 400; }
.cns h3 small { display: block; margin-top: 3px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem;
  letter-spacing: .15em; text-transform: uppercase; color: #8b96a5; }
.cns-opts { display: flex; flex-direction: column; }
.cns-opt { display: flex; gap: 12px; padding: 12px 2px; border: 0; border-bottom: 1px solid var(--nc-border-subtle, #232833);
  background: none; color: inherit; text-align: left; font: inherit; cursor: pointer; }
.cns-dot { flex: none; width: 16px; height: 16px; margin-top: 2px; border-radius: 50%; border: 1px solid #6b7685; position: relative; }
.cns-opt.on .cns-dot { border-color: var(--nc-primary, #00d2d2); }
.cns-opt.on .cns-dot::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: var(--nc-primary, #00d2d2); }
.cns-tx { display: flex; flex-direction: column; font-size: .95rem; }
.cns-tx small { margin-top: 2px; font-size: .78rem; line-height: 1.4; color: #8b96a5; }
.cns-for { display: flex; flex-wrap: wrap; gap: 6px; }
.cns-chip { min-height: 36px; padding: 0 12px; border: 1px solid var(--nc-border-strong, #343a4d); border-radius: 18px; background: none;
  color: #c4ccd6; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .68rem; letter-spacing: .05em; cursor: pointer; }
.cns-chip.on { border-color: var(--nc-primary, #00d2d2); color: var(--nc-primary, #00d2d2); background: rgba(var(--nc-primary-rgb, 0, 210, 210), .1); }
.cns-until, .cns-note { margin: 0; font-size: .8rem; line-height: 1.45; color: #8b96a5; }
.cns-door { color: var(--nc-primary, #00d2d2); text-decoration: none; white-space: nowrap; }
.cns-err { margin: 0; font-size: .82rem; color: var(--warning-color, #f59e0b); }
</style>
