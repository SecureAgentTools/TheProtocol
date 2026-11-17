<!--
  V0663 (order 418) and V0664 (his report, room seq 4032, order gwo_a29c2690f3f0f098eb0134c4): the side panel's Mentions section.
  The UNREAD mentions of you in this room, newest first, each with who wrote it, the line drawn the way the thread draws it (the
  mention in the mention colour, yours marked), the time on the right and a Jump. The read ones fold under "Earlier mentions (N)",
  closed. "Mark all read" asks the thread to move this room's read mark to its newest message (the thread's own read route, so the
  bell, the room's @ mark and every device follow). It draws what the thread hands it; the thread reads them (the registry's
  mentions=me) and keeps them current.
-->
<template>
  <div class="cml" data-testid="cml">
    <p v-if="failed" class="cml-note" role="status" data-testid="cml-failed">
      {{ t('ourstate.mentions.failed', 'Mentions of you could not be read just now.') }}</p>
    <p v-else-if="!rows.length" class="cml-note" data-testid="cml-none">
      {{ t('ourstate.mentions.none', 'Nobody has mentioned you in this room.') }}</p>
    <template v-else>
      <div class="cml-head">
        <span class="cml-title" data-testid="cml-unread-count">{{ unread.length ? tp('ourstate.mentions.unreadN', 'Unread ({n})', { n: unread.length }) : t('ourstate.mentions.unread0', 'Unread') }}</span>
        <button v-if="unread.length" type="button" class="cml-markall" data-testid="cml-markall" :disabled="busy" @click="emit('markAllRead')">
          {{ t('ourstate.mentions.markAll', 'Mark all read') }}</button>
      </div>
      <p v-if="markFailed" class="cml-note cml-err" role="status" data-testid="cml-mark-failed">{{ t('ourstate.mentions.markFailed', 'Could not mark them read just now. Try again.') }}</p>
      <p v-if="!unread.length" class="cml-note" data-testid="cml-allread">{{ t('ourstate.mentions.allRead', 'No unread mentions.') }}</p>
      <ul v-else class="cml-list" data-testid="cml-unread-list">
        <li v-for="m in unreadShown" :key="m.id" class="cml-row cml-row-unread" :data-testid="`cml-row-${m.seq}`">
          <span class="cml-dot" :data-testid="`cml-unread-${m.seq}`" :title="t('ourstate.mentions.unreadTitle', 'Not read yet')" aria-hidden="true"></span>
          <div class="cml-main">
            <div class="cml-top">
              <span class="cml-who">{{ m.sender_name || '' }}</span>
              <time v-if="m.created_at" class="cml-time" :datetime="m.created_at">{{ timeLabel(String(m.created_at), Date.now(), appLocale()) }}</time>
            </div>
            <ChatMessageBody class="cml-text" :body="String(m.body || '')" :mentions="(m.mentions as any)" :my-key="myKey" :my-names="myNames" />
          </div>
          <button type="button" class="cml-jump" :data-testid="`cml-jump-${m.seq}`" :aria-label="t('ourstate.mentions.jumpTo', 'Jump to this message')" @click="emit('jump', m)">
            {{ t('ourstate.mentions.jump', 'Jump') }}</button>
        </li>
      </ul>

      <details v-if="earlier.length" class="cml-earlier" data-testid="cml-earlier">
        <summary class="cml-earlier-sum" data-testid="cml-earlier-sum">{{ tp('ourstate.mentions.earlier', 'Earlier mentions ({n})', { n: earlier.length }) }}</summary>
        <ul class="cml-list">
          <li v-for="m in earlierShown" :key="m.id" class="cml-row" :data-testid="`cml-row-${m.seq}`">
            <div class="cml-main">
              <div class="cml-top">
                <span class="cml-who">{{ m.sender_name || '' }}</span>
                <time v-if="m.created_at" class="cml-time" :datetime="m.created_at">{{ timeLabel(String(m.created_at), Date.now(), appLocale()) }}</time>
              </div>
              <ChatMessageBody class="cml-text" :body="String(m.body || '')" :mentions="(m.mentions as any)" :my-key="myKey" :my-names="myNames" />
            </div>
            <button type="button" class="cml-jump" :data-testid="`cml-jump-${m.seq}`" :aria-label="t('ourstate.mentions.jumpTo', 'Jump to this message')" @click="emit('jump', m)">
              {{ t('ourstate.mentions.jump', 'Jump') }}</button>
          </li>
        </ul>
      </details>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ChatMessageBody from '@/components/ourstate/ChatMessageBody.vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { timeLabel } from '@/services/chat/messageText'
import type { MentionRow } from '@/services/chat/mentions'

const props = withDefaults(defineProps<{
  /** this room's mentions of the viewer, oldest first (services/chat/mentions.mentionsOfYou) */
  rows: MentionRow[]
  readFloor?: number
  seen?: ReadonlySet<number>
  failed?: boolean
  /** how many to draw in each part (the counts are the whole) */
  max?: number
  /** the viewer's principal key and own names: the preview marks a mention of the viewer the way the thread does */
  myKey?: string | null
  myNames?: readonly string[]
  /** a read mark is being moved */
  busy?: boolean
  /** the last attempt to move it failed */
  markFailed?: boolean
}>(), { readFloor: 0, seen: () => new Set<number>(), failed: false, max: 30, myKey: null, myNames: () => [], busy: false, markFailed: false })
const emit = defineEmits<{ (e: 'jump', m: MentionRow): void; (e: 'markAllRead'): void }>()
const { t, tp } = useI18n()

const isUnread = (m: MentionRow) => Number(m.seq) > Number(props.readFloor || 0) && !props.seen.has(Number(m.seq))
const newestFirst = (list: MentionRow[]) => [...list].sort((a, b) => Number(b.seq) - Number(a.seq))
const unread = computed(() => newestFirst(props.rows.filter(isUnread)))
const earlier = computed(() => newestFirst(props.rows.filter((m) => !isUnread(m))))
const unreadShown = computed(() => unread.value.slice(0, props.max))
const earlierShown = computed(() => earlier.value.slice(0, props.max))
</script>

<style scoped>
.cml { display: grid; gap: 0.5rem; }
.cml-note { margin: 0; font-size: 0.78rem; opacity: 0.7; }
.cml-err { opacity: 1; color: #fca5a5; }
.cml-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.cml-title { font: 700 0.68rem 'IBM Plex Mono', monospace; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.75; }
.cml-markall { background: none; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; color: var(--primary-color, #4fd8c4); cursor: pointer; font-size: 0.72rem; min-height: 28px; padding: 0 0.6rem; }
.cml-markall:hover:not(:disabled), .cml-markall:focus-visible { background: rgba(79, 216, 196, 0.12); }
.cml-markall:disabled { opacity: 0.5; cursor: default; }
.cml-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
.cml-row { display: flex; align-items: flex-start; gap: 0.45rem; font-size: 0.8rem; }
.cml-dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: var(--primary-color, #4fd8c4); margin-top: 0.4rem; flex: none; }
.cml-main { display: grid; gap: 0.15rem; min-width: 0; flex: 1; }
.cml-top { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
.cml-who { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cml-time { flex: none; font-size: 0.7rem; opacity: 0.55; font-variant-numeric: tabular-nums; }
/* the preview is two lines of the message as the thread draws it; a long one is clipped, the Jump opens the whole */
.cml-text { opacity: 0.9; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.cml-text :deep(p) { margin: 0; }
.cml-jump { flex: none; background: none; border: 1px solid rgba(255,255,255,0.18); border-radius: 6px; color: inherit; cursor: pointer; font-size: 0.72rem; min-height: 28px; padding: 0 0.5rem; }
.cml-earlier { border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.4rem; }
.cml-earlier-sum { cursor: pointer; font-size: 0.74rem; opacity: 0.75; margin-bottom: 0.4rem; }
.cml-earlier .cml-row { opacity: 0.8; }
</style>
