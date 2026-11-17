<!--
  V0652 (x) (order gwo_cedd900e6d50be18ce4eecf1): one chat message's text, readable at a glance: a status chip when it
  opens with one (DONE, FAIL, REQ, INFO, ORDER, ACK, BID), markdown on the docs viewer's terms (raw HTML is text,
  never markup) sanitized again on a short allowlist, mentions marked (the viewer's own stands out), ids and hashes small
  and grey, and a long message folded after its first lines with "show more". services/chat/messageText.ts holds the
  rules; this only draws them.
-->
<template>
  <div class="cm" :class="{ 'cm-folded': folded }" data-testid="cm">
    <span v-if="r.tag" class="cm-chip" :class="`cm-chip-${r.tag.toLowerCase()}`" :data-chip="r.tag"
          data-testid="cm-chip">{{ r.tag }}</span>
    <!-- eslint-disable-next-line vue/no-v-html -- sanitized: markdown-it html:false, then DOMPurify (messageText.ts) -->
    <!-- V0662: one listener for every code block's copy button (the sanitized HTML carries no handler) -->
    <div class="cm-md" data-testid="cm-md" v-html="r.html" @click="onBodyClick" />
    <button v-if="r.foldable" type="button" class="cm-more" data-testid="cm-more" @click="open = !open">
      {{ open ? t('ourstate.thread.showLess', 'show less') : t('ourstate.thread.showMore', 'show more') }}</button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { renderMessage } from '@/services/chat/messageText'
import { handleCopyClick } from '@/services/chat/codeCopy'

/* Stable inputs only (session-lead's review, the sessions' room seq 378): the message's own mentions array, the
   viewer's key and a names array the thread holds in a computed. Labels built by the thread on every render were new
   arrays each time, so a keystroke in the composer (same component as the thread) re-rendered every message's
   markdown; the lists are built here, in this component's computed, from inputs that do not change while one types. */
const props = withDefaults(defineProps<{
  body: string
  /** The mentions the server resolved for this message, as services/chat_mentions.py stores and ships them:
      { key, ptype, developer_id, agent_did, token }, the token being the name as typed after its "@" (the sessions'
      room seq 596: this read `label`, which nothing sends, so no resolved mention was marked). */
  mentions?: Array<{ key?: string; ptype?: string; developer_id?: number | null; agent_did?: string | null;
                     token?: string }> | null
  /** The viewer's principal key ("dev:6"): a mention with it names the viewer. */
  myKey?: string | null
  /** The viewer's own names (handle, name), from a computed in the thread. */
  myNames?: readonly string[]
}>(), { mentions: null, myKey: null, myNames: () => [] })

const { t } = useI18n()
const open = ref(false)
const labels = computed(() => {
  const ms = Array.isArray(props.mentions) ? props.mentions : []
  const token = (x: { token?: string } | null | undefined) => String(x?.token || '')
  return {
    mentionLabels: ms.map(token).filter(Boolean),
    meLabels: [...ms.filter((x) => !!props.myKey && x?.key === props.myKey).map(token).filter(Boolean),
               ...(props.myNames || []).filter((x) => typeof x === 'string' && x.length > 0)],
  }
})
// V0662: a code block gets a copy button, labelled in the viewer's language, and onBodyClick is what it does
const r = computed(() => renderMessage(props.body, { ...labels.value, copyLabel: t('ourstate.thread.copy', 'Copy') }))
function onBodyClick(e: MouseEvent) {
  void handleCopyClick(e, t('ourstate.thread.copied', 'Copied'), t('ourstate.thread.copyFailed', 'Copy failed'))
}
const folded = computed(() => r.value.foldable && !open.value)
</script>

<style scoped>
.cm { min-width: 0; }
.cm-chip {
  display: inline-block; margin: 0 6px 2px 0; padding: 1px 7px; border-radius: 4px; vertical-align: baseline;
  font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .72rem; font-weight: 600; letter-spacing: .06em;
  border: 1px solid currentColor;
}
/* the chips' colours carry on both themes; each holds AA against the bubble (4.5:1 at this size) */
.cm-chip-done { color: #3fbf7f; }
.cm-chip-fail { color: #ff6b6b; }
.cm-chip-req { color: #f2b544; }
.cm-chip-info { color: #79b8ff; }
.cm-chip-order { color: #c39bff; }
.cm-chip-ack { color: #a9b4c2; }
.cm-chip-bid { color: #4fd8c4; }
.cm-md { display: inline; }
.cm-md :deep(p) { margin: 0 0 .45em; }
.cm-md :deep(p:last-child) { margin-bottom: 0; }
.cm-md :deep(p:first-child) { display: inline; }
.cm-md :deep(ul), .cm-md :deep(ol) { margin: .3em 0 .45em; padding-left: 1.3em; }
.cm-md :deep(li) { margin: .1em 0; }
.cm-md :deep(code) {
  font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .86em; padding: 0 4px; border-radius: 3px;
  background: rgba(128, 128, 128, .18);
}
.cm-md :deep(pre) { margin: .4em 0; padding: 8px 10px; border-radius: 6px; background: rgba(128, 128, 128, .14); overflow-x: auto; }
.cm-md :deep(pre code) { padding: 0; background: none; }
.cm-md :deep(h1), .cm-md :deep(h2), .cm-md :deep(h3), .cm-md :deep(h4), .cm-md :deep(h5), .cm-md :deep(h6) {
  margin: .3em 0 .2em; font-size: 1em; font-weight: 600;
}
.cm-md :deep(a) { color: var(--primary-color, #4fd8c4); text-decoration: underline; text-underline-offset: 2px; }
.cm-md :deep(blockquote) { margin: .3em 0; padding-left: 10px; border-left: 2px solid rgba(128, 128, 128, .45); opacity: .9; }
.cm-md :deep(.cm-mention) { color: var(--primary-color, #4fd8c4); font-weight: 500; }
.cm-md :deep(.cm-me) { padding: 0 3px; border-radius: 3px; background: rgba(79, 216, 196, .2); font-weight: 600; }
/* ids and hashes: small, grey, whole on hover; #8b96a5 holds 4.5:1 on the dark bubble at this size */
.cm-md :deep(.cm-id) { font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .78em; color: #8b96a5; }
/* V0662: tables (scroll sideways inside the bubble rather than widening it), drawn task boxes, collapsible sections, and a
   code block with its language and copy button. Hairlines, no stock icons. */
.cm-md :deep(table) { display: block; max-width: 100%; overflow-x: auto; margin: .4em 0; border-collapse: collapse; font-size: .92em; }
.cm-md :deep(th), .cm-md :deep(td) { padding: 3px 9px; border: 1px solid rgba(128, 128, 128, .3); text-align: left; vertical-align: top; }
.cm-md :deep(th) { font-weight: 600; background: rgba(128, 128, 128, .12); }
.cm-md :deep(.cm-task-item) { list-style: none; margin-left: -1.15em; }
.cm-md :deep(.cm-task) {
  position: relative; display: inline-block; width: .95em; height: .95em; margin-right: .45em; vertical-align: -.12em;
  border: 1px solid currentColor; border-radius: 3px; opacity: .8;
}
.cm-md :deep(.cm-task-done) { background: var(--primary-color, #4fd8c4); border-color: var(--primary-color, #4fd8c4); opacity: 1; }
.cm-md :deep(.cm-task-done)::after {
  content: ''; position: absolute; left: 27%; top: 5%; width: 26%; height: 54%; border: solid #06211d; border-width: 0 1.5px 1.5px 0;
  transform: rotate(42deg);
}
.cm-md :deep(.cm-sr) { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.cm-md :deep(details.cm-details) { margin: .35em 0; padding: 1px 0 1px 10px; border-left: 2px solid rgba(128, 128, 128, .45); }
.cm-md :deep(details.cm-details > summary) { cursor: pointer; font-weight: 500; }
.cm-md :deep(.cm-code) { position: relative; margin: .4em 0; }
.cm-md :deep(.cm-code pre) { margin: 0; padding-top: 18px; }
.cm-md :deep(.cm-code-lang) {
  position: absolute; left: 10px; top: 4px; font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .66rem;
  letter-spacing: .08em; text-transform: uppercase; opacity: .55;
}
.cm-md :deep(.cm-copy) {
  position: absolute; top: 3px; right: 4px; padding: 1px 8px; border: 1px solid rgba(128, 128, 128, .35); border-radius: 4px;
  background: none; color: inherit; font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .66rem; letter-spacing: .06em;
  text-transform: uppercase; opacity: 0; cursor: pointer;
}
.cm-md :deep(.cm-code:hover .cm-copy), .cm-md :deep(.cm-copy:focus-visible), .cm-md :deep(.cm-copy[data-state]) { opacity: .9; }
.cm-md :deep(.cm-copy[data-state="copied"]) { color: var(--primary-color, #4fd8c4); border-color: currentColor; }
.cm-md :deep(.cm-copy[data-state="failed"]) { color: #ff6b6b; border-color: currentColor; }
@media (hover: none) { .cm-md :deep(.cm-copy) { opacity: .75; } }
.cm-folded .cm-md {
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 6; line-clamp: 6; overflow: hidden;
}
.cm-more {
  display: block; margin-top: 4px; padding: 0; border: 0; background: none; cursor: pointer;
  color: var(--primary-color, #4fd8c4); font-family: var(--font-mono, 'IBM Plex Mono', monospace);
  font-size: .72rem; letter-spacing: .08em; text-transform: uppercase;
}
</style>
