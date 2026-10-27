<!--
  ReadFailedNotice.vue: what a page says where its list or its verdict would be when the read behind it failed
  (§FESUITE, 2026-10-04). "Could not read" is not "none": an empty state drawn after a failed read tells a person they
  have nothing, and an all-clear drawn after one ("No stuck-funds signals detected.") tells an operator nothing is wrong.
  The failing-reads sweep found 27 pages saying "none" with every read failed (the census on V0569, sbx-beta). This says
  the read failed, to a screen reader too (role alert), and offers it again when the page passes `retry`.

  Usage:
    <ReadFailedNotice v-if="readFailed" :retry="load" />
    <div v-else-if="!items.length">No items yet</div>

  It names itself twice: data-testid="read-failed", which a caller's own data-testid REPLACES (Vue attribute
  fallthrough: the inherited value wins), and data-read-failed, which no caller passes, so every notice on a page can be
  counted (lifecycle 59, the suite's retryAll) whatever name its page gave it (§FESUITE, 2026-10-05, agentvault2-b2).
-->
<template>
  <div class="rfn" :class="{ 'rfn--dense': dense }" role="alert" data-testid="read-failed" data-read-failed>
    <Icon name="mdi:cloud-off-outline" class="rfn-ico" />
    <span class="rfn-txt">{{ text || t('common.readFailed.text', 'This could not be read just now.') }}</span>
    <button v-if="retry" type="button" class="rfn-retry" data-testid="read-failed-retry" @click="onRetry">
      {{ t('common.readFailed.retry', 'Try again') }}
    </button>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'

const props = withDefaults(defineProps<{
  /** the page's own sentence, when it names what could not be read */
  text?: string
  /** read again; the button shows only when the page gives one */
  retry?: () => unknown
  dense?: boolean
}>(), { text: '', retry: undefined, dense: false })

const { t } = useI18n()

function onRetry() {
  try {
    const r = props.retry?.()
    // a retry that fails says so through the page's own read state; nothing to do with its promise here
    if (r && typeof (r as Promise<unknown>).catch === 'function') (r as Promise<unknown>).catch(() => {})
  } catch { /* the same: the page's read state speaks */ }
}
</script>

<style scoped>
.rfn {
  display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 0.6rem;
  padding: 1.5rem 1rem; text-align: center;
  color: var(--nc-text-secondary, rgba(255, 255, 255, 0.78));
}
.rfn--dense { padding: 0.6rem 0.5rem; }
.rfn-ico { width: 1.1rem; height: 1.1rem; color: var(--nc-warning, #f59e0b); flex: 0 0 auto; }
.rfn-txt { font-size: 0.85rem; }
.rfn-retry {
  font-size: 0.8rem; padding: 0.3rem 0.75rem; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.18)); background: transparent;
  color: var(--nc-text-primary, #fff);
}
.rfn-retry:hover { border-color: var(--nc-primary, #00e5ff); }
.rfn-retry:focus-visible { outline: 2px solid var(--nc-primary, #00e5ff); outline-offset: 2px; }
</style>
