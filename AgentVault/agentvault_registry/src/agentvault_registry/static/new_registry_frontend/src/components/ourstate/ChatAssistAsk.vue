<template>
  <!-- V0654 (ap): what you asked your assistant, shown to you alone (it is never posted to the room); the answer the
       registry posts comes below it in the room. While it writes it says so; a refusal says why, in words. -->
  <div class="caa" :class="ask.state" role="status" aria-live="polite" :data-testid="`ost-assist-ask-${ask.ref}`"
       :data-state="ask.state">
    <div class="caa-head">
      <Icon name="mdi:creation" class="caa-mark" />
      <span class="caa-who">{{ ask.who ? tp('ourstate.assist.askHead', 'You asked your assistant, as {who}', { who: ask.who })
        : t('ourstate.assist.askHeadYou', 'You asked your assistant') }}</span>
      <span class="caa-only">{{ t('ourstate.assist.onlyYou', 'only you see this') }}</span>
    </div>
    <p class="caa-prompt" data-testid="ost-assist-prompt">{{ ask.prompt }}</p>
    <p v-if="ask.state === 'waiting'" class="caa-wait" data-testid="ost-assist-waiting">
      <Icon name="mdi:refresh" class="caa-spin" />
      {{ t('ourstate.assist.waiting', 'Writing. The answer appears below when it is posted.') }}</p>
    <p v-else-if="ask.state === 'failed'" class="caa-error" data-testid="ost-assist-error">
      {{ ask.error || t('ourstate.assist.failed', 'The assistant did not answer; nothing was posted.') }}</p>
    <div v-if="ask.state === 'failed'" class="caa-acts">
      <button type="button" class="caa-btn" data-testid="ost-assist-retry" @click="emit('retry', ask)">
        {{ t('ourstate.assist.retry', 'Ask again') }}</button>
      <button type="button" class="caa-btn" data-testid="ost-assist-edit" @click="emit('edit', ask)">
        {{ t('ourstate.assist.edit', 'Edit') }}</button>
      <button type="button" class="caa-btn" data-testid="ost-assist-dismiss" @click="emit('dismiss', ask)">
        {{ t('ourstate.assist.dismiss', 'Remove') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import type { AssistAsk } from '@/services/chat/assistOn'

defineProps<{ ask: AssistAsk }>()
const emit = defineEmits<{ (e: 'retry', a: AssistAsk): void; (e: 'edit', a: AssistAsk): void; (e: 'dismiss', a: AssistAsk): void }>()
const { t, tp } = useI18n()
</script>

<style scoped>
/* the amber the speaker chip wears while the assistant is on: one colour for "the assistant is in this" */
.caa { align-self: flex-end; max-width: min(86%, 578px); margin: 2px 0; padding: 8px 10px; border-radius: 12px;
  border: 1px dashed var(--warning-color, #f59e0b); background: rgba(245, 158, 11, .07); font-size: .82rem; }
.caa-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: .7rem; }
.caa-mark { width: 14px; height: 14px; color: var(--warning-color, #f59e0b); }
.caa-who { font-weight: 600; color: var(--warning-color, #f59e0b); }
.caa-only { opacity: .7; font-style: italic; }
.caa-prompt { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.caa-wait, .caa-error { margin: 6px 0 0; font-size: .74rem; display: flex; align-items: center; gap: 6px; }
.caa-wait { opacity: .8; }
.caa-error { color: var(--error-color, #f87171); }
.caa-spin { width: 13px; height: 13px; animation: caa-spin 1.2s linear infinite; }
@keyframes caa-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .caa-spin { animation: none; } }
.caa-acts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.caa-btn { min-height: 32px; padding: 0 10px; border-radius: 999px; border: 1px solid var(--border-color, rgba(128,128,128,.3));
  background: none; color: inherit; font-size: .74rem; cursor: pointer; }
.caa.answered { opacity: .8; }
</style>
