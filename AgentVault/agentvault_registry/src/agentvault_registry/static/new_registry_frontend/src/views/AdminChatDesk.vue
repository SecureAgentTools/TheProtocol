<script setup lang="ts">
/**
 * §ADMINDESK (2026-08-29) — the operator's chat desk: OurChat-style two-pane
 * surface for the registry admin, approved with two constraints that shape
 * everything here:
 *
 *   TWO LANES ONLY.  The desk reads (1) support threads, where it is a
 *   legitimate party, and (2) conversations the customer explicitly granted
 *   for review from their own thread (§CHATDESK C4) — read-only, ticket-bound,
 *   dead the moment the ticket settles. There is NO third lane: this view has
 *   no way to open an arbitrary conversation, and the backend refuses one.
 *
 *   FULLY AUDITABLE.  Every transcript this view opens writes a row to
 *   security_audit_logs: `admin.chatdesk.thread_read` for the participant lane
 *   (added with this view) and `admin.chatdesk.review_read` for the consent
 *   lane (since §CHATDESK C4). To keep those rows MEANING something, the open
 *   thread is never re-fetched by the 20s poll floor — the transcript reloads
 *   only on an explicit open, on our own reply (which returns the fresh
 *   thread anyway), or on a live cue naming this ticket. The idle timer
 *   refreshes the queue, not the transcript.
 *
 * Deliberately self-contained rather than refactoring SupportView: that view
 * serves customers and is battery-proven; the desk is a different surface on
 * the same endpoints. Org rooms are org-admin moderated and never appear here.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { apiClient } from '@/services/api/client'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useSupportStream } from '@/composables/useSupportStream'
import { useAuthStore } from '@/stores/auth'
import '@/components/settings/tp-settings.css'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const authStore = useAuthStore()

/* ── queue state ─────────────────────────────────────────────────────────── */
const PAGE_SIZE = 30
const stats = ref<Record<string, number>>({})
/** §FESUITE V0577: the chips counted "Open · 0" and the rest over a failed first stats read */
const statsRead = ref(false)
const tickets = ref<any[]>([])
const page = ref(0)
const hasMore = ref(false)
const loadingList = ref(false)
// §FESUITE (the failing-reads census, V0569 at sbx-beta, 2026-10-04): with every read failed the queue said "No tickets
// match." while the frame had tickets. A failed read keeps the page it had; with none read it says the read failed.
const ticketsFailed = ref(false)
const filterStatus = ref('all')
const filterPriority = ref('all')
const filterCategory = ref('all')

/* ── thread state ────────────────────────────────────────────────────────── */
const selected = ref<any | null>(null)
const loadingThread = ref(false)
const threadErr = ref('')
const replyText = ref('')
const sending = ref(false)
const statusBusy = ref(false)
const triageBusy = ref(false)
/* Interleave guard: only the newest open wins the right pane. */
let openSeq = 0

/* ── consent lane ────────────────────────────────────────────────────────── */
const grants = ref<any[]>([])
/** §FESUITE V0577: a failed grants read said "No review grants on this ticket." (the consent lane) */
const grantsFailed = ref(false)
const reviewOpen = ref<any | null>(null)
const reviewMsgs = ref<any[]>([])
const reviewErr = ref('')

const priorities = [
  { value: 'low', label: 'Low' }, { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' }, { value: 'urgent', label: 'Urgent' },
]
// Values are the backend enum in routers/support.py (TicketCreate/TriageBody):
// any other value 422s at the triage route and renders a blank select.
const categories = [
  { value: 'bug', label: 'Bug' }, { value: 'question', label: 'Question' },
  { value: 'feature', label: 'Feature' }, { value: 'account', label: 'Account' },
  { value: 'general', label: 'General' },
]
const statusColors: Record<string, string> = {
  open: 'acd-b-open', in_progress: 'acd-b-progress',
  resolved: 'acd-b-resolved', closed: 'acd-b-closed',
}
const priorityColors: Record<string, string> = {
  low: 'acd-b-low', normal: 'acd-b-normal', high: 'acd-b-high', urgent: 'acd-b-urgent',
}
const statusLabel = (s: string) =>
  ({ open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' }[s] || s)

const ticketSettled = computed(() =>
  !!selected.value && ['resolved', 'closed'].includes(selected.value.status))

const formatTime = (t: string) => dayjs(t).fromNow()
const formatDate = (t: string) => dayjs(t).format('YYYY-MM-DD HH:mm')

/* ── queue loads (unaudited metadata; transcripts are the audited reads) ─── */
async function loadStats() {
  try {
    const res = await apiClient.get('/admin/support/tickets/stats')
    stats.value = res.data || {}
    statsRead.value = true
  } catch { /* a failed refresh keeps the last counts; never read, they show "—" */ }
}

async function loadTickets(toPage = page.value) {
  loadingList.value = true
  try {
    const params: Record<string, any> = {
      limit: PAGE_SIZE + 1, offset: toPage * PAGE_SIZE,
    }
    if (filterStatus.value !== 'all') params.status = filterStatus.value
    if (filterPriority.value !== 'all') params.priority = filterPriority.value
    if (filterCategory.value !== 'all') params.category = filterCategory.value
    const res = await apiClient.get('/admin/support/tickets', { params })
    const rows = res.data || []
    hasMore.value = rows.length > PAGE_SIZE
    tickets.value = rows.slice(0, PAGE_SIZE)
    page.value = toPage
    ticketsFailed.value = false
  } catch { ticketsFailed.value = !tickets.value.length /* keep the previous page rather than blank the queue */ }
  finally { loadingList.value = false }
}

/* ── the audited open ────────────────────────────────────────────────────── */
async function openTicket(id: number) {
  const seq = ++openSeq
  loadingThread.value = true
  threadErr.value = ''
  reviewOpen.value = null
  reviewMsgs.value = []
  try {
    const res = await apiClient.get(`/admin/support/tickets/${id}`)
    if (seq !== openSeq) return
    // another ticket's grants are not this one's (they stayed until this ticket's read answered); a live cue that
    // re-opens the same ticket keeps them while it reads again
    if (selected.value?.id !== id) { grants.value = []; grantsFailed.value = false }
    selected.value = res.data
    loadGrants(id)
  } catch (e: any) {
    if (seq !== openSeq) return
    selected.value = null
    threadErr.value = e?.response?.data?.detail || 'Could not open this ticket.'
  } finally {
    if (seq === openSeq) loadingThread.value = false
  }
}

async function loadGrants(ticketId: number) {
  try {
    const res = await apiClient.get(`/admin/support/tickets/${ticketId}/review-grants`)
    if (selected.value?.id === ticketId) { grants.value = res.data?.grants || []; grantsFailed.value = false }
  } catch {
    if (selected.value?.id === ticketId) { grants.value = []; grantsFailed.value = true }
  }
}

async function sendReply() {
  if (!selected.value || !replyText.value.trim() || sending.value) return
  sending.value = true
  try {
    const res = await apiClient.post(
      `/admin/support/tickets/${selected.value.id}/reply`,
      { message: replyText.value.trim() })
    /* The reply response IS the fresh thread — no second (audited) read. */
    if (res.data?.messages) selected.value = { ...selected.value, ...res.data }
    replyText.value = ''
    loadStats(); loadTickets()
  } catch (e: any) {
    threadErr.value = e?.response?.data?.detail || 'Reply failed.'
  } finally { sending.value = false }
}

async function setStatus(s: string) {
  if (!selected.value || statusBusy.value || selected.value.status === s) return
  statusBusy.value = true
  try {
    const res = await apiClient.post(
      `/admin/support/tickets/${selected.value.id}/status`, { status: s })
    if (res.data) selected.value = { ...selected.value, ...res.data }
    loadStats(); loadTickets()
  } catch (e: any) {
    threadErr.value = e?.response?.data?.detail || 'Status change failed.'
  } finally { statusBusy.value = false }
}

async function setTriage(field: 'priority' | 'category', value: string) {
  if (!selected.value || triageBusy.value) return
  triageBusy.value = true
  try {
    const res = await apiClient.post(
      `/admin/support/tickets/${selected.value.id}/triage`, { [field]: value })
    if (res.data) selected.value = { ...selected.value, ...res.data }
    loadTickets()
  } catch (e: any) {
    threadErr.value = e?.response?.data?.detail || 'Triage failed.'
  } finally { triageBusy.value = false }
}

/* ── consent-lane transcript (audited server-side per read) ──────────────── */
async function openReview(g: any) {
  reviewErr.value = ''
  reviewOpen.value = g
  reviewMsgs.value = []
  try {
    const res = await apiClient.get(`/admin/support/review/${g.grant_id}/messages`)
    reviewMsgs.value = res.data?.messages || []
  } catch (e: any) {
    reviewErr.value = e?.response?.data?.detail ||
      'The grant refused: it is revoked, expired, or the ticket has settled.'
  }
}

/* ── live cues: queue always, transcript only when the cue names it ──────── */
useSupportStream({
  onChange: (cue) => {
    loadStats(); loadTickets()
    if (cue && selected.value && cue.ticket_id === selected.value.id) {
      openTicket(selected.value.id)
    }
  },
  onPoll: () => { loadStats(); loadTickets() },
})

watch([filterStatus, filterPriority, filterCategory], () => { loadTickets(0) })

onMounted(() => { loadStats(); loadTickets(0) })
</script>

<template>
  <div class="acd-root" data-testid="acd-root">
    <div v-if="!authStore.isAdmin" class="st-card acd-denied">
      This is the operator's desk. Your account does not carry the support flag.
    </div>

    <div v-else class="acd-grid">
      <!-- ══ LEFT: the queue (participant lane) ══ -->
      <aside class="acd-queue st-card" data-testid="acd-queue">
        <div class="acd-lane-head">
          <span class="acd-lane-title">Chat Desk</span>
          <span class="acd-lane-sub">Participant lane — tickets filed with the desk</span>
        </div>

        <div class="acd-stats">
          <button v-for="s in ['open', 'in_progress', 'resolved', 'closed']" :key="s"
                  :class="['acd-chip', statusColors[s], filterStatus === s ? 'acd-chip--on' : '']"
                  :data-testid="'acd-stat-' + s"
                  @click="filterStatus = filterStatus === s ? 'all' : s">
            {{ statusLabel(s) }} · {{ statsRead ? (stats[s] ?? 0) : '—' }}
          </button>
        </div>

        <div class="acd-filters">
          <select v-model="filterPriority" class="st-select acd-select" data-testid="acd-f-priority" aria-label="Filter by priority">
            <option value="all">All priorities</option>
            <option v-for="p in priorities" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
          <select v-model="filterCategory" class="st-select acd-select" data-testid="acd-f-category" aria-label="Filter by category">
            <option value="all">All categories</option>
            <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
          </select>
        </div>

        <!-- a scrolling list a keyboard can reach and scroll (§FESUITE: axe scrollable-region-focusable) -->
        <div class="acd-list" data-testid="acd-list" role="region" aria-label="Tickets" tabindex="0">
          <ReadFailedNotice v-if="ticketsFailed && !tickets.length && !loadingList" dense text="The tickets could not be read just now." :retry="() => loadTickets()" />
          <div v-else-if="!tickets.length && !loadingList" class="acd-empty-q">No tickets match.</div>
          <!-- §FESUITE: a ticket opens from the keyboard too (the rows were divs only a mouse could press) -->
          <div v-for="tk in tickets" :key="tk.id"
               :class="['acd-row', selected?.id === tk.id ? 'acd-row--open' : '']"
               :data-testid="'acd-row-' + tk.id"
               role="button" tabindex="0" :aria-current="selected?.id === tk.id ? 'true' : undefined"
               @click="openTicket(tk.id)"
               @keydown.enter.prevent="openTicket(tk.id)" @keydown.space.prevent="openTicket(tk.id)">
            <div class="acd-row-top">
              <span class="acd-row-id">#{{ tk.id }}</span>
              <span :class="['acd-badge', statusColors[tk.status]]">{{ statusLabel(tk.status) }}</span>
              <span :class="['acd-badge', priorityColors[tk.priority]]">{{ tk.priority }}</span>
              <span class="acd-row-time">{{ formatTime(tk.updated_at) }}</span>
            </div>
            <div class="acd-row-subject">{{ tk.subject }}</div>
            <div class="acd-row-meta">
              <span class="acd-row-dev">{{ tk.developer_name || tk.developer_email || ('dev #' + tk.developer_id) }}</span>
              <span v-if="tk.message_count" class="acd-row-count">{{ tk.message_count }} msg</span>
            </div>
          </div>
        </div>

        <div v-if="page > 0 || hasMore" class="acd-pager">
          <button class="acd-btn" :disabled="page === 0 || loadingList" @click="loadTickets(page - 1)">Prev</button>
          <span class="acd-pager-pos">Page {{ page + 1 }}</span>
          <button class="acd-btn" :disabled="!hasMore || loadingList" @click="loadTickets(page + 1)">Next</button>
        </div>

        <p class="acd-audit-note" data-testid="acd-audit-note">
          Two lanes only. Every transcript you open here is written to the audit log.
        </p>
      </aside>

      <!-- ══ RIGHT: the thread ══ -->
      <section class="acd-thread-pane st-card" data-testid="acd-thread-pane">
        <div v-if="!selected && !loadingThread" class="acd-empty" data-testid="acd-empty">
          <div class="acd-empty-mark">◫</div>
          <p>Pick a ticket from the queue.</p>
          <p class="acd-empty-sub">The desk reads support threads and customer-granted reviews — nothing else opens from here.</p>
        </div>
        <div v-else-if="loadingThread && !selected" class="acd-empty">Opening…</div>

        <template v-else-if="selected">
          <header class="acd-head">
            <div class="acd-head-row">
              <h2 class="acd-subject">{{ selected.subject }}</h2>
              <span :class="['acd-badge acd-badge-lg', statusColors[selected.status]]">{{ statusLabel(selected.status) }}</span>
            </div>
            <div class="acd-head-meta">
              <span class="acd-head-dev">{{ selected.developer_name || selected.developer_email }}</span>
              <span>Ticket #{{ selected.id }}</span>
              <span>{{ formatDate(selected.created_at) }}</span>
            </div>
            <div class="acd-controls">
              <div class="acd-status-btns">
                <button v-for="s in ['open', 'in_progress', 'resolved', 'closed']" :key="s"
                        :class="['acd-btn', selected.status === s ? 'acd-btn--on' : '']"
                        :disabled="statusBusy" :data-testid="'acd-status-' + s"
                        @click="setStatus(s)">{{ statusLabel(s) }}</button>
              </div>
              <div class="acd-triage">
                <select class="st-select acd-select" :disabled="triageBusy" :value="selected.priority"
                        data-testid="acd-triage-priority"
                        @change="setTriage('priority', ($event.target as HTMLSelectElement).value)">
                  <option v-for="p in priorities" :key="p.value" :value="p.value">{{ p.label }}</option>
                </select>
                <select class="st-select acd-select" :disabled="triageBusy" :value="selected.category"
                        data-testid="acd-triage-category"
                        @change="setTriage('category', ($event.target as HTMLSelectElement).value)">
                  <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
                </select>
              </div>
            </div>
          </header>

          <div class="acd-msgs" data-testid="acd-msgs">
            <div v-for="m in selected.messages" :key="m.id"
                 :class="['acd-msg', m.sender_type === 'admin' ? 'acd-msg--desk' : 'acd-msg--customer']">
              <div class="acd-msg-head">
                <span :class="['acd-msg-badge', m.sender_type === 'admin' ? 'acd-mb-desk' : 'acd-mb-cust']">
                  {{ m.sender_type === 'admin' ? 'DESK' : 'CUSTOMER' }}
                </span>
                <span class="acd-msg-who">{{ m.sender_name || (m.sender_type === 'admin' ? 'Support' : 'Customer') }}</span>
                <span class="acd-msg-time" :title="formatDate(m.created_at)">{{ formatTime(m.created_at) }}</span>
              </div>
              <div class="acd-msg-body">{{ m.message }}</div>
            </div>
          </div>

          <!-- ══ Consent lane ══ -->
          <div class="acd-review st-card" data-testid="acd-review">
            <div class="acd-lane-head acd-lane-head--review">
              <span class="acd-lane-title">Review</span>
              <span class="acd-lane-sub">Consent lane — read-only, granted by the customer, ends with the ticket</span>
            </div>
            <ReadFailedNotice v-if="grantsFailed" dense text="The review grants could not be read just now." :retry="() => selected && loadGrants(selected.id)" data-testid="acd-review-unread" />
            <p v-else-if="!grants.length" class="acd-review-empty" data-testid="acd-review-empty">
              No review grants on this ticket. The customer grants access from their own thread.
            </p>
            <div v-for="g in grants" :key="g.grant_id" class="acd-review-row" :data-testid="'acd-grant-' + g.grant_id">
              <span class="acd-review-title">{{ g.conversation_title || g.conversation_kind }}</span>
              <span :class="['acd-badge', g.live ? 'acd-b-open' : 'acd-b-closed']">
                {{ g.live ? 'live' : (g.revoked_at ? 'revoked' : 'ended') }}
              </span>
              <button v-if="g.live" class="acd-btn" :data-testid="'acd-review-open-' + g.grant_id"
                      @click="openReview(g)">Read</button>
            </div>
            <div v-if="reviewOpen" class="acd-review-transcript" data-testid="acd-review-transcript">
              <div class="acd-review-thead">
                Read-only transcript · {{ reviewOpen.conversation_title || reviewOpen.conversation_kind }}
                <button class="acd-review-close" @click="reviewOpen = null; reviewMsgs = []">×</button>
              </div>
              <p v-if="reviewErr" class="acd-review-err" data-testid="acd-review-err">{{ reviewErr }}</p>
              <div v-for="m2 in reviewMsgs" :key="m2.id" class="acd-review-msg">
                <span class="acd-review-who">{{ m2.sender_name || m2.sender_ptype }}</span>
                <span class="acd-review-body">{{ m2.body }}</span>
              </div>
            </div>
          </div>

          <div :class="['acd-reply', ticketSettled ? 'acd-reply--settled' : '']" data-testid="acd-reply">
            <p v-if="threadErr" class="acd-err" data-testid="acd-err">{{ threadErr }}</p>
            <textarea v-model="replyText" class="st-textarea acd-reply-input" data-testid="acd-reply-input"
                      :placeholder="ticketSettled
                        ? 'Reply without changing the settled status…'
                        : 'Reply as the desk…'"></textarea>
            <div class="acd-reply-row">
              <span class="acd-reply-note">Signed as your display name, or "Support" if you have none set.</span>
              <button class="st-btn-primary" :disabled="sending || !replyText.trim()"
                      data-testid="acd-reply-send" @click="sendReply">
                {{ sending ? 'Sending…' : 'Send reply' }}
              </button>
            </div>
          </div>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.acd-root { padding: 16px; height: 100%; box-sizing: border-box; }
.acd-denied { padding: 24px; text-align: center; }
.acd-grid {
  display: grid; grid-template-columns: 360px minmax(0, 1fr); gap: 14px;
  align-items: start;
}
@media (max-width: 980px) { .acd-grid { grid-template-columns: 1fr; } }

/* lanes */
.acd-lane-head { display: flex; flex-direction: column; gap: 2px; margin-bottom: 10px; }
.acd-lane-title { font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; font-size: 0.85rem; }
.acd-lane-sub { font-size: 0.72rem; opacity: 0.65; }
.acd-lane-head--review { margin-bottom: 6px; }

/* queue */
.acd-queue { padding: 14px; position: sticky; top: 12px; display: flex; flex-direction: column;
  max-height: calc(100vh - 120px); }
.acd-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.acd-chip { border: 1px solid rgba(148, 163, 184, 0.25); background: transparent; color: inherit;
  border-radius: 999px; padding: 3px 10px; font-size: 0.72rem; cursor: pointer; }
.acd-chip--on { outline: 1px solid rgba(52, 211, 153, 0.8); }
.acd-filters { display: flex; gap: 6px; margin-bottom: 8px; }
.acd-select { font-size: 0.78rem; padding: 4px 6px; }
.acd-list { overflow-y: auto; flex: 1; min-height: 120px; display: flex; flex-direction: column; gap: 6px; }
.acd-list:focus-visible { outline: 1px solid rgba(var(--nc-primary-rgb), 0.55); outline-offset: 2px; border-radius: 6px; }
.acd-empty-q { opacity: 0.6; font-size: 0.8rem; padding: 12px 4px; }
.acd-row { border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 8px; padding: 8px 10px; cursor: pointer; }
.acd-row:hover { border-color: rgba(52, 211, 153, 0.5); }
.acd-row:focus-visible { outline: 2px solid rgba(52, 211, 153, 0.9); outline-offset: 1px; }
.acd-row--open { border-color: rgba(52, 211, 153, 0.9); background: rgba(52, 211, 153, 0.06); }
.acd-row-top { display: flex; align-items: center; gap: 6px; font-size: 0.72rem; }
.acd-row-id { opacity: 0.6; }
.acd-row-time { margin-left: auto; opacity: 0.55; }
.acd-row-subject { font-size: 0.85rem; font-weight: 600; margin: 3px 0 2px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.acd-row-meta { display: flex; gap: 8px; font-size: 0.72rem; opacity: 0.7; }
/* §CHATPOLISH — three classes with markup and no rule. The queue row's two meta
   spans read as one run at identical weight, and the ticket header had no
   separation from the transcript below it. */
.acd-row-dev { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acd-row-count { margin-left: auto; opacity: 0.8; font-variant-numeric: tabular-nums; white-space: nowrap; }
.acd-head { padding: 10px 12px; border-bottom: 1px solid rgba(148, 163, 184, 0.16); }
.acd-pager { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.acd-pager-pos { font-size: 0.75rem; opacity: 0.7; }
.acd-audit-note { margin: 10px 0 0; font-size: 0.7rem; opacity: 0.6; line-height: 1.4; }

/* badges */
.acd-badge { border-radius: 4px; padding: 1px 6px; font-size: 0.66rem; text-transform: uppercase;
  letter-spacing: 0.04em; border: 1px solid transparent; }
.acd-badge-lg { font-size: 0.75rem; padding: 3px 9px; }
.acd-b-open { background: rgba(52, 211, 153, 0.14); color: #34d399; }
.acd-b-progress { background: rgba(96, 165, 250, 0.14); color: #60a5fa; }
.acd-b-resolved { background: rgba(167, 139, 250, 0.14); color: #a78bfa; }
.acd-b-closed { background: rgba(148, 163, 184, 0.16); color: #94a3b8; }
.acd-b-low { background: rgba(148, 163, 184, 0.14); color: #94a3b8; }
.acd-b-normal { background: rgba(96, 165, 250, 0.12); color: #93c5fd; }
.acd-b-high { background: rgba(251, 191, 36, 0.14); color: #fbbf24; }
.acd-b-urgent { background: rgba(248, 113, 113, 0.16); color: #f87171; }

/* thread pane */
.acd-thread-pane { padding: 14px; display: flex; flex-direction: column; gap: 12px;
  min-height: calc(100vh - 140px); }
.acd-empty { text-align: center; opacity: 0.65; padding: 60px 20px; }
.acd-empty-mark { font-size: 2rem; margin-bottom: 8px; }
.acd-empty-sub { font-size: 0.75rem; opacity: 0.8; }
.acd-head-row { display: flex; align-items: center; gap: 10px; }
.acd-subject { font-size: 1.05rem; margin: 0; flex: 1; min-width: 0; }
.acd-head-meta { display: flex; gap: 12px; font-size: 0.75rem; opacity: 0.7; margin-top: 4px; }
.acd-head-dev { font-weight: 600; }
.acd-controls { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; align-items: center; }
.acd-status-btns { display: flex; gap: 6px; }
.acd-btn { border: 1px solid rgba(148, 163, 184, 0.3); background: transparent; color: inherit;
  border-radius: 6px; padding: 4px 10px; font-size: 0.74rem; cursor: pointer; }
.acd-btn:disabled { opacity: 0.4; cursor: default; }
.acd-btn--on { border-color: rgba(52, 211, 153, 0.9); color: #34d399; }
.acd-triage { display: flex; gap: 6px; margin-left: auto; }

/* messages, chat-styled */
.acd-msgs { display: flex; flex-direction: column; gap: 8px; flex: 1; overflow-y: auto; padding: 4px 2px; }
.acd-msg { max-width: 78%; border-radius: 10px; padding: 8px 12px;
  border: 1px solid rgba(148, 163, 184, 0.16); }
.acd-msg--customer { align-self: flex-start; background: rgba(148, 163, 184, 0.07); }
.acd-msg--desk { align-self: flex-end; background: rgba(52, 211, 153, 0.08);
  border-color: rgba(52, 211, 153, 0.25); }
.acd-msg-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 0.72rem; }
.acd-msg-badge { border-radius: 3px; padding: 0 5px; font-size: 0.62rem; letter-spacing: 0.06em; }
.acd-mb-desk { background: rgba(52, 211, 153, 0.2); color: #34d399; }
.acd-mb-cust { background: rgba(96, 165, 250, 0.18); color: #93c5fd; }
.acd-msg-who { font-weight: 600; }
.acd-msg-time { margin-left: auto; opacity: 0.55; }
.acd-msg-body { font-size: 0.85rem; white-space: pre-wrap; word-break: break-word; }

/* consent lane */
.acd-review { padding: 12px; }
.acd-review-empty { font-size: 0.76rem; opacity: 0.6; margin: 0; }
.acd-review-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 0.8rem; }
.acd-review-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.acd-review-transcript { margin-top: 8px; border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px; padding: 10px; max-height: 260px; overflow-y: auto; }
.acd-review-thead { display: flex; align-items: center; gap: 8px; font-size: 0.76rem; font-weight: 600;
  margin-bottom: 6px; }
.acd-review-close { margin-left: auto; background: none; border: none; color: inherit;
  cursor: pointer; font-size: 1rem; }
.acd-review-err { color: #f87171; font-size: 0.76rem; }
.acd-review-msg { display: flex; gap: 8px; font-size: 0.78rem; padding: 2px 0; }
.acd-review-who { opacity: 0.65; flex: 0 0 auto; }
.acd-review-body { white-space: pre-wrap; word-break: break-word; }

/* reply */
.acd-reply { border-top: 1px solid rgba(148, 163, 184, 0.18); padding-top: 10px; }
.acd-reply--settled { opacity: 0.85; border-top-style: dashed; }
.acd-reply-input { width: 100%; min-height: 70px; box-sizing: border-box; }
.acd-reply-row { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
.acd-reply-note { font-size: 0.7rem; opacity: 0.6; flex: 1; }
.acd-err { color: #f87171; font-size: 0.78rem; margin: 0 0 6px; }
</style>
