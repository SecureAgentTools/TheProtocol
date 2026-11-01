<!--
  V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): an organization room's settings in one place. An owner or an admin
  edits the topic and the room's rules (its genesis) and chooses who may post; a member reads the same, set by an
  operator (inventory items 9 and 10). The name is the organization's: read here, changed on the organization's page.
  @assistant is switched from the room's menu and only shown here (review item 12). Closing with an edit not saved asks
  first (review item 13). Changing who may post silences people, so the thread asks for a hold (its existing confirm).
-->
<template>
  <div class="ost-sheet-veil" @click.self="tryClose">
    <div class="ost-sheet crs" role="dialog" aria-modal="true" :aria-label="t('ourstate.rooms.settings', 'Room settings')"
         data-testid="ost-room-dialog">
      <h3>{{ t('ourstate.rooms.settings', 'Room settings') }}<small>{{ title }} · {{ isOperator
        ? t('ourstate.roomSettings.youOperator', 'you are an owner or an admin') : t('ourstate.roomSettings.youMember', 'read only') }}</small></h3>

      <div class="crs-field">
        <span class="crs-lbl">{{ t('ourstate.roomSettings.name', 'Name') }}</span>
        <span class="crs-val" data-testid="crs-name">{{ title }}</span>
        <span class="crs-note">{{ t('ourstate.roomSettings.nameNote', "The organization's name; it changes on the organization's page.") }}
          <router-link to="/organization" class="crs-door" data-testid="crs-org" @click="emit('close')">{{ t('ourstate.roomSettings.org', 'Organization') }} ›</router-link></span>
      </div>

      <div class="crs-field">
        <label class="crs-lbl" for="crs-topic">{{ t('ourstate.roomSettings.topic', 'Topic') }}</label>
        <input v-if="isOperator" id="crs-topic" v-model="topicDraft" class="ost-sheet-input" maxlength="200" data-testid="crs-topic" />
        <span v-else class="crs-val" data-testid="crs-topic-ro">{{ topic || t('ourstate.roomSettings.none', 'none') }}</span>
        <span class="crs-note">{{ t('ourstate.roomSettings.topicNote', "Shown under the room's name. A change posts a line in the room.") }}</span>
      </div>

      <div class="crs-field">
        <span class="crs-lbl">{{ t('ourstate.roomSettings.whoPosts', 'Who may post') }}</span>
        <template v-if="isOperator">
          <button class="crs-opt" role="radio" :aria-checked="mode !== 'announce' ? 'true' : 'false'" :class="{ on: mode !== 'announce' }"
                  data-testid="crs-mode-open" @click="mode === 'announce' && emit('mode', 'open')">
            <span class="crs-dot" aria-hidden="true" />
            <span class="crs-tx">{{ t('ourstate.roomSettings.everyone', 'Everyone in the organization') }}<small>{{ t('ourstate.settings.modeOpen', 'Open') }}</small></span>
          </button>
          <button class="crs-opt" role="radio" :aria-checked="mode === 'announce' ? 'true' : 'false'" :class="{ on: mode === 'announce' }"
                  data-testid="crs-mode-announce" @click="mode !== 'announce' && emit('mode', 'announce')">
            <span class="crs-dot" aria-hidden="true" />
            <span class="crs-tx">{{ t('ourstate.roomSettings.operators', 'Owners and admins only') }}<small>{{ t('ourstate.roomSettings.announceSub', 'Announce only: the others read, they do not post') }}</small></span>
          </button>
          <span class="crs-note">{{ t('ourstate.roomSettings.modeNote', 'Changing it silences people, so it asks for a hold first, and posts a line in the room.') }}</span>
        </template>
        <span v-else class="crs-val" data-testid="crs-mode-ro">{{ mode === 'announce'
          ? t('ourstate.roomSettings.operators', 'Owners and admins only') : t('ourstate.roomSettings.everyone', 'Everyone in the organization') }}</span>
      </div>

      <div class="crs-field">
        <label class="crs-lbl" for="crs-rules">{{ t('ourstate.roomSettings.rules', "The room's rules") }}</label>
        <textarea v-if="isOperator" id="crs-rules" v-model="rulesDraft" class="ost-sheet-input" rows="3" maxlength="2000" data-testid="crs-rules" />
        <span v-else class="crs-val crs-pre" data-testid="crs-rules-ro">{{ rules || t('ourstate.roomSettings.none', 'none') }}</span>
        <span class="crs-note">{{ t('ourstate.roomSettings.rulesNote', 'Shown at the top of the room to everyone who joins. Burning the thread does not hide it.') }}</span>
      </div>

      <div class="crs-field crs-row">
        <span class="crs-tx">@assistant<small>{{ t('ourstate.roomSettings.assistantNote', "Reads the organization's records only (receipts, the roster, the treasury) and answers when addressed. Switched from the room's menu.") }}</small></span>
        <span class="crs-val" data-testid="crs-assistant">{{ assistantPresent ? t('ourstate.settings.on', 'On') : t('ourstate.settings.off', 'Off') }}</span>
      </div>

      <p v-if="error" class="crs-err" data-testid="crs-err">{{ error }}</p>
      <div v-if="asking" class="crs-discard" data-testid="crs-discard">
        <span>{{ t('ourstate.roomSettings.discardAsk', 'Discard your changes to the topic and the rules?') }}</span>
        <button class="ost-btn" data-testid="crs-keep" @click="asking = false">{{ t('ourstate.roomSettings.keep', 'Keep editing') }}</button>
        <button class="ost-btn ost-danger" data-testid="crs-discard-go" @click="emit('close')">{{ t('ourstate.roomSettings.discard', 'Discard') }}</button>
      </div>
      <div v-else class="ost-sheet-btns">
        <button class="ost-btn" data-testid="crs-close" @click="tryClose">{{ t('common.close', 'Close') }}</button>
        <button v-if="isOperator" class="ost-btn ost-accept" data-testid="crs-save" :disabled="!dirty || busy"
                @click="emit('save', { topic: topicDraft.trim(), rules: rulesDraft.trim(), topicChanged, rulesChanged })">
          {{ busy ? '…' : t('ourstate.roomSettings.save', 'Save topic and rules') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'

const props = withDefaults(defineProps<{
  title: string
  topic?: string | null
  rules?: string | null
  mode?: string | null
  isOperator: boolean
  assistantPresent?: boolean
  busy?: boolean
  error?: string
}>(), { topic: '', rules: '', mode: 'open', assistantPresent: false, busy: false, error: '' })
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'mode', v: 'open' | 'announce'): void
  (e: 'save', v: { topic: string; rules: string; topicChanged: boolean; rulesChanged: boolean }): void
}>()
const { t } = useI18n()

const topicDraft = ref(String(props.topic || ''))
const rulesDraft = ref(String(props.rules || ''))
/* a save brings the room back with its new values: they become the drafts' baseline */
watch(() => props.topic, (v) => { topicDraft.value = String(v || '') })
watch(() => props.rules, (v) => { rulesDraft.value = String(v || '') })
const topicChanged = computed(() => topicDraft.value.trim() !== String(props.topic || '').trim())
const rulesChanged = computed(() => rulesDraft.value.trim() !== String(props.rules || '').trim())
const dirty = computed(() => props.isOperator && (topicChanged.value || rulesChanged.value))
const asking = ref(false)
function tryClose() {
  if (dirty.value) { asking.value = true; return }
  emit('close')
}
defineExpose({ tryClose })
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
.crs h3 { margin: 0; font-weight: 400; }
.crs h3 small { display: block; margin-top: 3px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem;
  letter-spacing: .15em; text-transform: uppercase; color: #8b96a5; }
.crs-field { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; border-bottom: 1px solid var(--nc-border-subtle, #232833); }
.crs-row { flex-direction: row; align-items: flex-start; gap: 12px; }
.crs-lbl { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem; letter-spacing: .16em; text-transform: uppercase; color: #8b96a5; }
.crs-val { font-size: .95rem; }
.crs-pre { white-space: pre-wrap; }
.crs-note { font-size: .76rem; line-height: 1.4; color: #8b96a5; }
.crs-door { color: var(--nc-primary, #00d2d2); text-decoration: none; white-space: nowrap; margin-left: 4px; }
.crs-opt { display: flex; gap: 12px; padding: 8px 2px; border: 0; background: none; color: inherit; text-align: left; font: inherit; cursor: pointer; }
.crs-dot { flex: none; width: 16px; height: 16px; margin-top: 2px; border-radius: 50%; border: 1px solid #6b7685; position: relative; }
.crs-opt.on .crs-dot { border-color: var(--nc-primary, #00d2d2); }
.crs-opt.on .crs-dot::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: var(--nc-primary, #00d2d2); }
.crs-tx { flex: 1; display: flex; flex-direction: column; font-size: .95rem; }
.crs-tx small { margin-top: 2px; font-size: .76rem; line-height: 1.4; color: #8b96a5; }
.crs-err { margin: 0; font-size: .82rem; color: var(--warning-color, #f59e0b); }
.crs-discard { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: .88rem; }
</style>
