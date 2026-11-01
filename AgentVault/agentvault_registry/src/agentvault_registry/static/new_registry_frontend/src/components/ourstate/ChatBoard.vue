<!--
  V0652 (ac) (order gwo_2ae43c7789db1e808ea1417f): an organization's room's status board. One board, kept fresh by the
  room's owner or the members the owner names (the current release, the open orders, what waits on the owner), pinned
  beside the approvals: in the console's side panel on a wide screen, above the history otherwise (a strip that folds
  to its first line, the fold kept per person). Markdown, rendered and sanitized as a message is. Edit (the owner and
  the named), History (every edit, who, when, the text), and for the owner who keeps it with them. An edit made while
  someone else's landed is refused by the registry, and this says so and shows the board as it now is.
-->
<template>
  <div class="cbd" :class="{ 'cbd--strip': strip }" data-testid="ost-board">
    <button v-if="strip" type="button" class="cbd-strip-head" :aria-expanded="open ? 'true' : 'false'"
            data-testid="ost-board-toggle" @click="toggle">
      <span class="cbd-lbl">{{ t('ourstate.board.title', 'Status board') }}</span>
      <span v-if="!open" class="cbd-first">{{ firstLine }}</span>
      <Icon name="mdi:chevron-right" class="cbd-caret" :class="{ open }" aria-hidden="true" />
    </button>
    <div v-show="!strip || open" class="cbd-body">
      <div v-if="text" class="cbd-text ost-md" data-testid="ost-board-text" v-html="html" />
      <p v-else class="cbd-muted" data-testid="ost-board-empty">{{ canEdit
        ? t('ourstate.board.emptyEditor', 'Nothing on the board yet: write what the room should see first (the release, the open orders, what waits on the owner).')
        : t('ourstate.board.empty', 'Nothing on the board yet.') }}</p>
      <div class="cbd-meta">
        <span v-if="board?.updated_by" class="cbd-by" data-testid="ost-board-by">{{ tp('ourstate.board.by', 'Updated by {who}, {when}', {
          who: board.updated_by.name || board.updated_by.id, when: when(board.updated_at) }) }}</span>
        <button v-if="canEdit" type="button" class="cbd-btn" data-testid="ost-board-edit" @click="startEdit">
          {{ t('ourstate.board.edit', 'Edit') }}</button>
        <button v-if="(board?.rev || 0) > 0" type="button" class="cbd-btn" data-testid="ost-board-history" @click="openHistory">
          {{ t('ourstate.board.history', 'History') }}</button>
        <button v-if="isOwner" type="button" class="cbd-btn" data-testid="ost-board-editors" @click="openEditors">
          {{ t('ourstate.board.editors', 'Who keeps it') }}</button>
      </div>
    </div>

    <!-- edit: the whole text, against the revision read -->
    <div v-if="editing" class="ost-sheet-veil" @click.self="editing = false">
      <div class="ost-sheet cbd-sheet" role="dialog" aria-modal="true" :aria-label="t('ourstate.board.editTitle', 'Edit the status board')"
           data-testid="ost-board-editor">
        <h3>{{ t('ourstate.board.editTitle', 'Edit the status board') }}<small>{{ t('ourstate.board.editSub', 'Markdown; the room sees it at once, nobody is notified') }}</small></h3>
        <textarea v-model="draft" class="ost-sheet-input cbd-area" rows="10" maxlength="4000" data-testid="ost-board-draft" />
        <p class="cbd-count">{{ draft.length }} / 4000</p>
        <p v-if="error" class="cbd-err" data-testid="ost-board-err">{{ error }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" data-testid="ost-board-cancel" @click="editing = false">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-accept" data-testid="ost-board-save" :disabled="busy || draft.trim() === text" @click="save">
            {{ busy ? '…' : t('ourstate.board.save', 'Save the board') }}</button>
        </div>
      </div>
    </div>

    <!-- history: every edit, oldest first -->
    <div v-if="historyOpen" class="ost-sheet-veil" @click.self="historyOpen = false">
      <div class="ost-sheet cbd-sheet" role="dialog" aria-modal="true" :aria-label="t('ourstate.board.historyTitle', 'History of the status board')"
           data-testid="ost-board-history-sheet">
        <h3>{{ t('ourstate.board.historyTitle', 'History of the status board') }}</h3>
        <ReadFailedNotice v-if="historyFailed" dense :retry="openHistory"
                          :text="t('ourstate.board.historyFailed', 'The board\'s history could not be read just now.')" />
        <p v-else-if="!history" class="cbd-muted">{{ t('common.loading', 'Loading…') }}</p>
        <ol v-else class="cbd-revs">
          <li v-for="r in [...history].reverse()" :key="r.rev" class="cbd-rev" :data-testid="`ost-board-rev-${r.rev}`">
            <span class="cbd-rev-head">{{ tp('ourstate.board.rev', 'Edit {n} · {who} · {when}', {
              n: r.rev, who: r.by?.name || r.by?.id || '', when: when(r.at) }) }}</span>
            <pre class="cbd-rev-text">{{ r.text || t('ourstate.board.cleared', '(cleared)') }}</pre>
          </li>
        </ol>
        <div class="ost-sheet-btns"><button class="ost-btn" @click="historyOpen = false">{{ t('common.close', 'Close') }}</button></div>
      </div>
    </div>

    <!-- the owner names who keeps it with them -->
    <div v-if="editorsOpen" class="ost-sheet-veil" @click.self="editorsOpen = false">
      <div class="ost-sheet cbd-sheet" role="dialog" aria-modal="true" :aria-label="t('ourstate.board.editorsTitle', 'Who keeps the status board')"
           data-testid="ost-board-editors-sheet">
        <h3>{{ t('ourstate.board.editorsTitle', 'Who keeps the status board') }}<small>{{ t('ourstate.board.editorsSub', 'You always do; these keep it with you while they belong to the organization') }}</small></h3>
        <ReadFailedNotice v-if="candidatesFailed" dense :retry="openEditors"
                          :text="t('ourstate.board.candidatesFailed', 'The organization\'s members could not be read just now.')" />
        <p v-else-if="!candidates" class="cbd-muted">{{ t('common.loading', 'Loading…') }}</p>
        <div v-else class="cbd-cands">
          <label v-for="c in candidates" :key="c.key" class="cbd-cand" :data-testid="`ost-board-cand-${c.key}`">
            <input v-model="picked" type="checkbox" :value="c.key" />
            <span class="cbd-cand-name">{{ c.name }}<small>{{ c.kind === 'agent' ? t('ourstate.board.agent', 'agent') : t('ourstate.board.member', 'member') }}</small></span>
          </label>
          <p v-if="!candidates.length" class="cbd-muted">{{ t('ourstate.board.noCandidates', 'Nobody else is in the room yet.') }}</p>
        </div>
        <p v-if="error" class="cbd-err">{{ error }}</p>
        <div class="ost-sheet-btns">
          <button class="ost-btn" @click="editorsOpen = false">{{ t('common.cancel', 'Cancel') }}</button>
          <button class="ost-btn ost-accept" data-testid="ost-board-editors-save" :disabled="busy || !candidates" @click="saveEditors">
            {{ busy ? '…' : t('ourstate.board.editorsSave', 'Save') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { chatApi } from '@/services/api/chat'
import { organizationService } from '@/services/api/organizationService'
import { appLocale } from '@/services/appLocale'
import { renderMarkdown } from '@/services/chat/messageText'
import { useEscapeClose } from '@/composables/useEscapeClose'
import { useI18n } from '@/composables/useI18n'

interface RoomBoard {
  text: string
  rev: number
  updated_at: string | null
  updated_by: { ptype: string; id: string; name: string | null } | null
  can_edit: boolean
  editors?: Array<{ key: string; name: string | null }>
}

const props = withDefaults(defineProps<{
  board: RoomBoard | null
  token: string
  conversationId: string
  orgId?: string
  /** above the history (a strip that folds to its first line), not in the side panel */
  strip?: boolean
  /** whose fold state the strip keeps (per person on this device) */
  viewerKey?: string
}>(), { orgId: '', strip: false, viewerKey: 'me' })
const emit = defineEmits<{ (e: 'update', board: RoomBoard): void }>()
const { t, tp } = useI18n()

const text = computed(() => String(props.board?.text || ''))
const canEdit = computed(() => !!props.board?.can_edit)
const isOwner = computed(() => Array.isArray(props.board?.editors))
const html = computed(() => (text.value ? renderMarkdown(text.value) : ''))
/* the strip's folded line: the board's first line as plain text (no heading, list, emphasis or link syntax) */
const plain = (l: string) => l.replace(/^\s*(?:#{1,6}|>|[-*+]|\d+\.)\s+/, '').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  .replace(/[*_`~]+/g, '').trim()
const firstLine = computed(() => text.value.split('\n').map(plain).find(Boolean) || '')

const FOLD_KEY = () => `ourchat.board.v1.${props.viewerKey || 'me'}`
/* the strip starts folded to its first line (beside the pinned approvals a phone has little height left); opened, it
   stays open for that person */
const open = ref((() => { try { return localStorage.getItem(FOLD_KEY()) === '1' } catch { return false } })())
function toggle() {
  open.value = !open.value
  try { localStorage.setItem(FOLD_KEY(), open.value ? '1' : '0') } catch { /* full or blocked */ }
}

function when(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const busy = ref(false)
const error = ref('')
const editing = ref(false)
const draft = ref('')
function startEdit() { draft.value = text.value; error.value = ''; editing.value = true }
async function save() {
  busy.value = true
  error.value = ''
  try {
    const r = await chatApi.putBoard(props.token, props.conversationId, draft.value, Number(props.board?.rev || 0))
    if (r?.board) emit('update', r.board)
    editing.value = false
  } catch (e: any) {
    if (e?.status === 409) {
      // someone else's edit landed first: show the board as it now is, keep the draft to merge by hand
      error.value = t('ourstate.board.conflict', 'Someone else changed the board while you edited. It shows their version now; your text is still here to merge.')
      try { const b = await chatApi.getBoard(props.token, props.conversationId); if (b) emit('update', b) } catch { /* the error says enough */ }
    } else error.value = e?.detail || String(e?.message || e)
  } finally { busy.value = false }
}

const historyOpen = ref(false)
const history = ref<any[] | null>(null)
const historyFailed = ref(false)
async function openHistory() {
  historyOpen.value = true
  historyFailed.value = false
  history.value = null
  try { history.value = (await chatApi.boardHistory(props.token, props.conversationId))?.revisions || [] }
  catch { historyFailed.value = true }
}

const editorsOpen = ref(false)
const candidates = ref<Array<{ key: string; name: string; kind: 'agent' | 'member' }> | null>(null)
const candidatesFailed = ref(false)
const picked = ref<string[]>([])
async function openEditors() {
  editorsOpen.value = true
  candidatesFailed.value = false
  candidates.value = null
  error.value = ''
  picked.value = (props.board?.editors || []).map((e) => e.key)
  try {
    const [pres, mem] = await Promise.all([
      props.orgId ? organizationService.getOrgPresence(props.orgId) : Promise.resolve({ agents: [] } as any),
      chatApi.roomMembers(props.token, props.conversationId),
    ])
    const out: Array<{ key: string; name: string; kind: 'agent' | 'member' }> = []
    for (const m of mem?.members || []) {
      if (m.ptype === 'developer' && m.developer_id != null && m.org_role !== 'owner')
        out.push({ key: `dev:${m.developer_id}`, name: m.name || `dev ${m.developer_id}`, kind: 'member' })
    }
    for (const a of pres?.agents || []) out.push({ key: `agt:${String(a.did).toLowerCase()}`, name: a.name || a.did, kind: 'agent' })
    candidates.value = out
  } catch { candidatesFailed.value = true }
}
async function saveEditors() {
  busy.value = true
  error.value = ''
  try {
    const b = await chatApi.putBoardEditors(props.token, props.conversationId, picked.value)
    if (b) emit('update', b)
    editorsOpen.value = false
  } catch (e: any) { error.value = e?.detail || String(e?.message || e) }
  finally { busy.value = false }
}

useEscapeClose(editing, () => { editing.value = false })
useEscapeClose(historyOpen, () => { historyOpen.value = false })
useEscapeClose(editorsOpen, () => { editorsOpen.value = false })
defineExpose({ startEdit })
</script>

<style scoped>
.cbd { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
/* the strip may shrink (min-height 0): however tall the pinned panels are, the composer stays in view */
.cbd--strip { flex: 0 1 auto; min-height: 0; overflow-y: auto; margin: 0 12px 8px; padding: 6px 10px;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, .14)); border-radius: 10px; background: var(--nc-surface, rgba(255, 255, 255, .04)); }
.cbd--strip .cbd-body { max-height: min(28vh, 240px); overflow-y: auto; }
.cbd-strip-head { display: flex; align-items: center; gap: 10px; min-height: 36px; padding: 0; border: 0; background: none;
  color: inherit; cursor: pointer; text-align: left; }
.cbd-lbl { flex: none; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .62rem; letter-spacing: .17em;
  text-transform: uppercase; color: #8b96a5; }
.cbd-first { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .84rem; color: #c4ccd6; }
.cbd-caret { flex: none; width: 14px; height: 14px; margin-left: auto; opacity: .55; transition: transform .15s; }
.cbd-caret.open { transform: rotate(90deg); }
.cbd-body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.cbd-text { font-size: .86rem; line-height: 1.5; overflow-wrap: anywhere; }
.cbd-text :deep(p) { margin: 0 0 6px; }
.cbd-text :deep(ul), .cbd-text :deep(ol) { margin: 0 0 6px; padding-left: 1.2em; }
.cbd-text :deep(h1), .cbd-text :deep(h2), .cbd-text :deep(h3) { margin: 4px 0; font-size: .9rem; }
.cbd-muted { margin: 0; font-size: .8rem; color: #8b96a5; }
.cbd-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; }
.cbd-by { flex: 1 1 auto; min-width: 0; font-size: .7rem; color: #8b96a5; }
.cbd-btn { min-height: 32px; padding: 0 10px; border-radius: 8px; border: 1px solid var(--nc-border-strong, #343a4d); background: none;
  color: inherit; font-size: .74rem; cursor: pointer; }
@media (pointer: coarse) { .cbd-btn, .cbd-strip-head { min-height: 44px; } }
/* the chat's sheet, as the thread draws its own (its scoped rules do not reach a child component) */
.ost-sheet-veil { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: flex-end; justify-content: center; z-index: 60; }
.ost-sheet { width: 100%; max-width: 560px; max-height: 82vh; overflow-y: auto; background: var(--surface-1, #16181d); border-radius: 16px 16px 0 0;
  padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 10px; }
@media (min-width: 900px) {
  .ost-sheet-veil { align-items: center; padding: 32px; z-index: 10500; }
  .ost-sheet { max-height: min(80vh, 760px); border-radius: 16px; padding-bottom: 18px;
               border: 1px solid var(--border-color, rgba(128,128,128,.25)); box-shadow: 0 24px 64px rgba(0,0,0,.55); }
}
.ost-sheet-btns { display: flex; gap: 8px; justify-content: flex-end; }
.ost-sheet-input { width: 100%; min-height: 44px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3));
  background: none; color: inherit; font: inherit; font-size: 16px; box-sizing: border-box; }
.ost-btn { min-height: 44px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none;
  color: inherit; font-weight: 600; cursor: pointer; }
.ost-accept { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
.ost-btn:disabled { opacity: .4; cursor: not-allowed; filter: saturate(.4); }
.cbd-sheet h3 { margin: 0; font-weight: 400; }
.cbd-sheet h3 small { display: block; margin-top: 3px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem;
  letter-spacing: .12em; text-transform: uppercase; color: #8b96a5; }
.cbd-area { min-height: 220px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 14px; line-height: 1.5; resize: vertical; }
.cbd-count { margin: 0; font-size: .7rem; color: #8b96a5; text-align: right; font-variant-numeric: tabular-nums; }
.cbd-err { margin: 0; font-size: .82rem; color: var(--warning-color, #f59e0b); }
.cbd-revs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.cbd-rev { padding: 8px 0; border-bottom: 1px solid var(--nc-border-subtle, #232833); }
.cbd-rev:last-child { border-bottom: 0; }
.cbd-rev-head { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .66rem; color: #8b96a5; }
.cbd-rev-text { margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: .8rem; color: #c4ccd6; font-family: inherit; }
.cbd-cands { display: flex; flex-direction: column; }
.cbd-cand { display: flex; align-items: center; gap: 10px; min-height: 44px; border-bottom: 1px solid var(--nc-border-subtle, #232833); cursor: pointer; }
.cbd-cand-name { display: flex; flex-direction: column; font-size: .9rem; }
.cbd-cand-name small { font-size: .7rem; color: #8b96a5; }
</style>
