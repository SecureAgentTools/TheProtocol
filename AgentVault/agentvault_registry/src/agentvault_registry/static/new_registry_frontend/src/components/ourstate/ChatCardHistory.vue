<!--
  V0652 (aa) (order gwo_840aa2b590306f7eba147758): a card's history. A card updated in place (a progress card, a Guild
  order card, an approval card's use) keeps every update: who made it, when, and what changed (GET .../card/history).
  Oldest first, as the card grew; a failed read says so, never an empty history.
-->
<template>
  <div class="ost-sheet-veil" @click.self="emit('close')">
    <div class="ost-sheet cch" role="dialog" aria-modal="true" :aria-label="t('ourstate.cardHistory.title', 'History of this card')"
         data-testid="ost-card-history">
      <h3>{{ t('ourstate.cardHistory.title', 'History of this card') }}<small v-if="title">{{ title }}</small></h3>
      <ReadFailedNotice v-if="failed" dense :retry="load" data-testid="cch-failed"
                        :text="t('ourstate.cardHistory.failed', 'The history of this card could not be read just now.')" />
      <p v-else-if="!history" class="cch-muted">{{ t('common.loading', 'Loading…') }}</p>
      <p v-else-if="!history.updates.length" class="cch-muted" data-testid="cch-none">
        {{ t('ourstate.cardHistory.none', 'This card has not changed since it was posted.') }}</p>
      <ol v-else class="cch-list">
        <li class="cch-item cch-posted" data-testid="cch-posted">
          <span class="cch-when">{{ when(history.posted_at) }}</span>
          <span class="cch-what">{{ t('ourstate.cardHistory.posted', 'Posted') }}</span>
        </li>
        <li v-for="u in history.updates" :key="u.rev" class="cch-item" :data-testid="`cch-rev-${u.rev}`">
          <span class="cch-when">{{ when(u.at) }}</span>
          <span class="cch-what">
            <span class="cch-who">{{ u.by?.name || u.by?.id || '' }}</span>
            <span v-for="(c, i) in u.changes" :key="i" class="cch-change">{{ changeText(c) }}</span>
          </span>
        </li>
      </ol>
      <div class="ost-sheet-btns">
        <button class="ost-btn" data-testid="cch-close" @click="emit('close')">{{ t('common.close', 'Close') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { chatApi } from '@/services/api/chat'
import { appLocale } from '@/services/appLocale'
import { useI18n } from '@/composables/useI18n'

interface Change { path: string; from: unknown; to: unknown }
interface History {
  card_rev: number
  posted_at: string | null
  updates: Array<{ rev: number; at: string | null; by: { ptype: string; id: string; name: string | null } | null; changes: Change[] }>
}

const props = withDefaults(defineProps<{
  token: string
  conversationId: string
  messageId: string
  title?: string
}>(), { title: '' })
const emit = defineEmits<{ (e: 'close'): void }>()
const { t, tp } = useI18n()

const history = ref<History | null>(null)
const failed = ref(false)
async function load() {
  failed.value = false
  try {
    history.value = await chatApi.cardHistory(props.token, props.conversationId, props.messageId)
  } catch { failed.value = true }
}
onMounted(load)

function when(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
const show = (v: unknown) => (v == null ? '' : String(v))
/** One change as a line: "state: running → passed"; a step added ("new") or dropped ("removed"); "and N more". */
function changeText(c: Change): string {
  if (c.from == null && c.to == null) return c.path
  if (c.from == null) return tp('ourstate.cardHistory.added', '{path}: {to} (new)', { path: c.path, to: show(c.to) })
  if (c.to == null) return tp('ourstate.cardHistory.removed', '{path}: removed', { path: c.path })
  return tp('ourstate.cardHistory.changed', '{path}: {from} → {to}', { path: c.path, from: show(c.from), to: show(c.to) })
}
</script>

<style scoped>
/* the chat's sheet, as the thread draws its own (its scoped rules do not reach a child component) */
.ost-sheet-veil { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: flex-end; justify-content: center; z-index: 60; }
.ost-sheet { width: 100%; max-width: 480px; max-height: 82vh; overflow-y: auto; background: var(--surface-1, #16181d); border-radius: 16px 16px 0 0;
  padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 10px; }
@media (min-width: 900px) {
  .ost-sheet-veil { align-items: center; padding: 32px; z-index: 10500; }
  .ost-sheet { max-height: min(80vh, 760px); border-radius: 16px; padding-bottom: 18px;
               border: 1px solid var(--border-color, rgba(128,128,128,.25)); box-shadow: 0 24px 64px rgba(0,0,0,.55); }
}
.ost-sheet-btns { display: flex; gap: 8px; justify-content: flex-end; }
.ost-btn { min-height: 44px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none;
  color: inherit; font-weight: 600; cursor: pointer; }
.cch h3 { margin: 0; font-weight: 400; }
.cch h3 small { display: block; margin-top: 3px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem;
  letter-spacing: .15em; text-transform: uppercase; color: #8b96a5; }
.cch-muted { margin: 0; font-size: .85rem; color: #8b96a5; }
.cch-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.cch-item { display: grid; grid-template-columns: 7.5rem minmax(0, 1fr); column-gap: 12px; padding: 8px 0;
  border-bottom: 1px solid var(--nc-border-subtle, #232833); }
.cch-item:last-child { border-bottom: 0; }
.cch-when { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; color: #8b96a5; padding-top: 2px;
  font-variant-numeric: tabular-nums; }
.cch-what { display: flex; flex-direction: column; gap: 2px; min-width: 0; font-size: .86rem; }
.cch-who { font-weight: 600; }
.cch-change { color: #c4ccd6; overflow-wrap: anywhere; }
</style>
