<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — the one line above a board that says what on it needs a look (services/cockpit/attention).
 * Pressing an entry gives that pane the board (maximise); Escape or its own control gives the board back.
 */
import { useI18n } from '@/composables/useI18n'
import { attentionList } from '@/services/cockpit/attention'
import type { DeskArrange } from '@/composables/useDeskArrange'
import type { PaneId } from './paneRegistry'

const props = defineProps<{ arrange: DeskArrange }>()
const { t } = useI18n()

function open(id: PaneId) {
  if (props.arrange.maxId !== id) props.arrange.toggleMax(id)
}
</script>

<template>
  <div v-if="attentionList.length" class="ckd-attn" data-testid="ckd-attention"
       :aria-label="t('cockpit.attn.aria', 'What on this board needs a look')">
    <span class="ckd-attn-label">{{ t('cockpit.attn.label', 'Needs a look') }}</span>
    <button v-for="a in attentionList" :key="a.id" type="button" class="ckd-attn-chip" :class="`is-${a.tone}`"
            :data-attn="a.id" :title="t('cockpit.attn.open', 'Give this pane the board; Escape gives the board back')"
            @click="open(a.id)">{{ a.text }}</button>
  </div>
</template>

<style scoped>
.ckd-attn { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; margin: 0 0 .5rem; }
.ckd-attn-label { font-size: .6rem; letter-spacing: .1em; text-transform: uppercase; color: var(--nc-text-muted, #8f9399); margin-right: .15rem; }
.ckd-attn-chip { font-size: .68rem; line-height: 1; padding: .3rem .6rem; border-radius: 999px; cursor: pointer; background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 229, 255), .3); color: var(--nc-primary, #00e5ff); }
.ckd-attn-chip.is-warn { border-color: rgba(245, 158, 11, .5); color: #f59e0b; }
.ckd-attn-chip:hover { background: rgba(var(--nc-primary-rgb, 0, 229, 255), .08); }
.ckd-attn-chip.is-warn:hover { background: rgba(245, 158, 11, .08); }
.ckd-attn-chip:focus-visible { outline: 2px solid var(--nc-primary, #00e5ff); outline-offset: 1px; }
</style>
