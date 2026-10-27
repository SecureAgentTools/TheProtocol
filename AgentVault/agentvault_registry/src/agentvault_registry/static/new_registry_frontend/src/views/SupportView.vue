<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { apiClient } from '@/services/api/client'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useSupportStream } from '@/composables/useSupportStream'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import { messageOf } from '@/utils/httpError'
import '@/components/settings/tp-settings.css'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const { t, tp } = useI18n()
const authStore = useAuthStore()

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Message {
  id: number
  ticket_id: number
  sender_type: 'user' | 'admin'
  sender_name: string | null
  message: string
  created_at: string
}

interface Ticket {
  id: number
  developer_id?: number
  subject: string
  category: string
  status: string
  priority: string
  created_at: string
  updated_at: string
  messages: Message[]
  message_count?: number
  last_message_preview?: string | null
  last_message_at?: string | null
  developer_email?: string | null
  developer_name?: string | null
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
type View = 'list' | 'detail' | 'create'
const currentView = ref<View>('list')
const loading = ref(false)
const error = ref('')

// Ticket list
const tickets = ref<Ticket[]>([])
// §FESUITE (the failing-reads census, 2026-10-04): with the tickets' read failed the page said "No tickets found"
const ticketsFailed = ref(false)
const filterStatus = ref<string>('all')
const isAdmin = computed(() => authStore.isAdmin)

/* §S7 — THE LIST IS A PAGE NOW, AND THE COUNTERS DESCRIBE THE QUEUE.
   It used to ask for `limit: 200` and filter the result in the browser, so a
   desk past 200 tickets was reading a silently truncated queue whose counters
   were computed from the truncation. Both halves are fixed, and they had to
   move together: paginating alone would have turned "the numbers are wrong
   past 200" into "the numbers describe page one", which is the same lie with
   better manners.
   ⚠ We ask for PAGE_SIZE + 1 and render PAGE_SIZE. The extra row is the
   has-more sentinel, so "is there another page" is a fact about the database
   rather than a guess, and no per-filter COUNT query is needed. The stats bar
   is deliberately NOT filtered: it answers "what is in the queue", which is a
   different question from "what am I looking at". */
const PAGE_SIZE = 50
const page = ref(0)
const hasMore = ref(false)
const stats = ref({ total: 0, open: 0, in_progress: 0, resolved: 0, closed: 0 })

// Ticket detail
const selectedTicket = ref<Ticket | null>(null)
const replyText = ref('')
const replying = ref(false)

/* §S5 — WHICH RAIL YOU SPEAK ON IS DECIDED BY OWNERSHIP, NOT BY ROLE.
   `sendReply` used to pick the admin endpoint whenever `isAdmin` was true, so
   an admin replying to their OWN ticket was recorded as `sender_type='admin'`
   and — since §OURSTATE-7 D — mirrored into their own OurState thread as the
   support desk. Measured on his ticket #15: he typed "test" and was answered by
   himself, as Support. On a single-operator registry every ticket he files
   behaves that way. On your own ticket you are the customer.
   ⚠ Declared AFTER `selectedTicket`, beside what it reads — a computed defined
   above its own dependency is one refactor away from a temporal-dead-zone throw. */
const myDeveloperId = computed(() => {
  const u: any = (authStore as any).user || {}
  return String(u.developer_id ?? u.id ?? '')
})
const iOwnSelected = computed(() =>
  !!selectedTicket.value && !!myDeveloperId.value &&
  String(selectedTicket.value.developer_id ?? '') === myDeveloperId.value)
/** True only when answering somebody ELSE — the desk voice. */
const replyAsDesk = computed(() => isAdmin.value && !iOwnSelected.value)
/** A non-admin owner gets the close/reopen control; an admin already has the
 *  full status row, so showing both would be two doors onto one act. */
const showOwnerStatus = computed(() => !isAdmin.value && iOwnSelected.value)
/** §S8 — is this ticket in a settled state at all? */
const ticketSettled = computed(() =>
  ['resolved', 'closed'].includes(String(selectedTicket.value?.status || '')))
/**
 * §S8 — THE TWO RAILS DO NOT AGREE, so the note may not either.
 *   developer reply (`support.py:383`): resolved|closed -> open. It reopens.
 *   admin reply     (`support.py:571`): open -> in_progress, and NOTHING else.
 *                                       A settled ticket stays settled.
 * My first cut of this note said "sending a reply reopens it" for both, which
 * would have put a false sentence under the desk's own reply box. A UI note is
 * a claim about what the button does; it has to be read off the branch the
 * button actually takes.
 */
const reopensOnReply  = computed(() => ticketSettled.value && !replyAsDesk.value)
const deskKeepsStatus = computed(() => ticketSettled.value && replyAsDesk.value)

// New ticket form
const newTicket = ref({
  subject: '',
  category: 'general',
  message: '',
  priority: 'normal',
})
const creating = ref(false)

// §CHATDESK C4 — review grants on the selected ticket (admin desk half).
const reviewGrants = ref<any[]>([])
const reviewOpen = ref<any | null>(null)
const reviewMsgs = ref<any[]>([])
const reviewErr = ref('')
// §FESUITE (V0575): "None. The customer grants access…" only after a read that answered: not while the read is in
// flight, and not after one that failed
const reviewGrantsRead = ref<'reading' | 'read' | 'unread'>('reading')
async function loadReviewGrants(ticketId: number) {
  reviewGrants.value = []; reviewOpen.value = null; reviewMsgs.value = []; reviewErr.value = ''
  reviewGrantsRead.value = 'reading'
  try {
    const res = await apiClient.get(`/admin/support/tickets/${ticketId}/review-grants`)
    reviewGrants.value = res.data?.grants || []
    reviewGrantsRead.value = 'read'
  } catch { reviewGrants.value = []; reviewGrantsRead.value = 'unread' }
}
async function openReviewTranscript(g: any) {
  reviewOpen.value = g; reviewMsgs.value = []; reviewErr.value = ''
  try {
    const res = await apiClient.get(`/admin/support/review/${g.grant_id}/messages`)
    reviewMsgs.value = res.data?.messages || []
  } catch (e: any) {
    reviewErr.value = e?.response?.data?.detail || 'refused'
  }
}

// Admin filters
const adminFilterPriority = ref<string>('all')
const adminFilterCategory = ref<string>('all')

const categories = [
  { value: 'general',  label: 'General' },
  { value: 'bug',      label: 'Bug Report' },
  { value: 'question', label: 'Question' },
  { value: 'feature',  label: 'Feature Request' },
  { value: 'account',  label: 'Account Issue' },
]

const priorities = [
  { value: 'low',    label: 'Low' },
  { value: 'normal', label: 'Normal' },
  { value: 'high',   label: 'High' },
  { value: 'urgent', label: 'Urgent' },
]

const statusColors: Record<string, string> = {
  open:        'sp-status-open',
  in_progress: 'sp-status-progress',
  resolved:    'sp-status-resolved',
  closed:      'sp-status-closed',
}

const priorityColors: Record<string, string> = {
  low:    'sp-pri-low',
  normal: 'sp-pri-normal',
  high:   'sp-pri-high',
  urgent: 'sp-pri-urgent',
}

const categoryIcons: Record<string, string> = {
  general:  'GENERAL',
  bug:      'BUG',
  question: 'QUESTION',
  feature:  'FEATURE',
  account:  'ACCOUNT',
}

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
/* §S7 — `filteredTickets` and the browser-side `ticketStats` are DELETED.
   The server filters and the server counts; a second copy of either would be
   the first bug of one. `tickets` is now exactly the page the API returned. */
const ticketStats = computed(() => stats.value)

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
/* §S6 — cues can arrive while a load is in flight. A refresh triggered by the
   second of two cues can resolve BEFORE the first and paint a staler list, so
   every response carries the sequence number of its own request and a late
   arrival is dropped rather than rendered. */
let listSeq = 0

async function loadTickets(opts: { quiet?: boolean } = {}) {
  const seq = ++listSeq
  if (!opts.quiet) loading.value = true
  error.value = ''
  try {
    const admin = isAdmin.value
    const endpoint = admin ? '/admin/support/tickets' : '/support/tickets'
    const params: Record<string, any> = {
      limit: PAGE_SIZE + 1,
      offset: page.value * PAGE_SIZE,
    }
    if (filterStatus.value !== 'all') params.status = filterStatus.value
    if (admin && adminFilterPriority.value !== 'all') params.priority = adminFilterPriority.value
    if (admin && adminFilterCategory.value !== 'all') params.category = adminFilterCategory.value
    const res = await apiClient.get(endpoint, { params })
    if (seq !== listSeq) return          // a newer request already answered
    const rows: Ticket[] = Array.isArray(res.data) ? res.data : []
    hasMore.value = rows.length > PAGE_SIZE
    tickets.value = rows.slice(0, PAGE_SIZE)
    ticketsFailed.value = false
  } catch (e: any) {
    if (seq === listSeq) {
      error.value = e?.response?.data?.detail || 'Failed to load tickets'
      ticketsFailed.value = !tickets.value.length
    }
  } finally {
    if (seq === listSeq && !opts.quiet) loading.value = false
  }
}

/** §S7 — queue-wide counts, grouped in the database. Never derived from the page. */
async function loadStats() {
  try {
    const endpoint = isAdmin.value ? '/admin/support/tickets/stats' : '/support/tickets/stats'
    const res = await apiClient.get(endpoint)
    if (res?.data && typeof res.data === 'object') stats.value = res.data
  } catch {
    /* The counters are a summary, not the list. A failed stats call must not
       blank a queue that loaded fine — it leaves the previous numbers up. */
  }
}

function goToPage(n: number) {
  const next = Math.max(0, n)
  if (next === page.value) return
  page.value = next
  loadTickets()
}

/* Any filter change is a NEW query, so it must start at page 0 — otherwise
   narrowing a filter while on page 3 lands on an empty page that reads as
   "no tickets match" when the truth is "not on this page". */
watch([filterStatus, adminFilterPriority, adminFilterCategory], () => {
  page.value = 0
  loadTickets()
  loadStats()
})

async function loadTicketDetail(ticketId: number) {
  loading.value = true
  error.value = ''
  try {
    // §S1 — the admin queue lists every ticket, so opening one has to use the
    // rail that can READ every ticket. This called the developer route
    // unconditionally, which filters `developer_id == me`, so an admin clicking
    // any customer's ticket got "Ticket not found" and stayed on the list —
    // and never reached the status buttons, which live in this view.
    const endpoint = isAdmin.value
      ? `/admin/support/tickets/${ticketId}`
      : `/support/tickets/${ticketId}`
    const res = await apiClient.get(endpoint)
    selectedTicket.value = res.data
    currentView.value = 'detail'
    if (isAdmin.value) loadReviewGrants(ticketId)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Failed to load ticket'
  } finally {
    loading.value = false
  }
}

async function createTicket() {
  if (creating.value || !newTicket.value.subject.trim() || !newTicket.value.message.trim()) return
  creating.value = true
  error.value = ''
  try {
    const res = await apiClient.post('/support/tickets', newTicket.value)
    selectedTicket.value = res.data
    currentView.value = 'detail'
    newTicket.value = { subject: '', category: 'general', message: '', priority: 'normal' }
    await loadTickets()
  } catch (e: any) {
    error.value = messageOf(e?.response?.data, 'Failed to create ticket')
  } finally {
    creating.value = false
  }
}

async function sendReply() {
  if (!replyText.value.trim() || !selectedTicket.value) return
  replying.value = true
  error.value = ''
  try {
    // §S5 — ownership, not role. Answering your OWN ticket is speaking as the
    // customer, whatever flags your account carries.
    const endpoint = replyAsDesk.value
      ? `/admin/support/tickets/${selectedTicket.value.id}/reply`
      : `/support/tickets/${selectedTicket.value.id}/reply`
    const res = await apiClient.post(endpoint, { message: replyText.value })
    // ⚠ the admin reply route returns a plain TicketOut with no
    // `developer_email` / `developer_name`, and the detail view renders those.
    // Merge rather than replace, or an admin's own reply blanks the header it
    // just loaded (the §EXCISION-10 field-by-field-rebuild class).
    selectedTicket.value = { ...selectedTicket.value, ...res.data }
    replyText.value = ''
    await loadTickets()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Failed to send reply'
  } finally {
    replying.value = false
  }
}

async function changeStatus(ticketId: number, newStatus: string) {
  if (!isAdmin.value) return
  try {
    const res = await apiClient.post(`/admin/support/tickets/${ticketId}/status`, { status: newStatus })
    if (selectedTicket.value && selectedTicket.value.id === ticketId) {
      selectedTicket.value = { ...selectedTicket.value, ...res.data }
    }
    await loadTickets()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Failed to update status'
  }
}

/* §S12 — HIS REPORT: "there is also no admin controls in the support admin
   view in the fe." The status row was the only thing a desk could do. `priority`
   and `category` were written once by the CUSTOMER at creation and by nobody
   ever again — while this very view has offered admin filters on both since it
   was written. A queue sortable by two values only its filer can set is a
   triage view with no triage. */
const triageBusy = ref(false)
async function setTriage(field: 'priority' | 'category', value: string) {
  if (!selectedTicket.value || !isAdmin.value || triageBusy.value) return
  if (String((selectedTicket.value as any)[field] || '') === value) return
  triageBusy.value = true
  error.value = ''
  const previous = (selectedTicket.value as any)[field]
  try {
    // PATCH-shaped: send only the field that moved, so re-categorising cannot
    // silently re-assert a priority nobody touched.
    const res = await apiClient.post(
      `/admin/support/tickets/${selectedTicket.value.id}/triage`, { [field]: value })
    selectedTicket.value = { ...selectedTicket.value, ...res.data }
    await Promise.all([loadTickets({ quiet: true }), loadStats()])
  } catch (e: any) {
    // Put the select back where it was: a control that keeps the value it
    // failed to save tells the operator the change stuck when it did not.
    if (selectedTicket.value) (selectedTicket.value as any)[field] = previous
    error.value = e?.response?.data?.detail || 'Failed to update ticket'
  } finally {
    triageBusy.value = false
  }
}

/** §S2 — the OWNER ends their own ticket. Two states only: `closed` ("I am done
 *  with this") and `open` ("no, I am not"). `resolved` stays the desk's verdict
 *  about the work, and the server refuses it BY NAME rather than by regex. */
const ownerStatusBusy = ref(false)
async function setMyStatus(newStatus: 'closed' | 'open') {
  if (!selectedTicket.value || ownerStatusBusy.value) return
  ownerStatusBusy.value = true
  error.value = ''
  try {
    const res = await apiClient.post(
      `/support/tickets/${selectedTicket.value.id}/status`, { status: newStatus })
    selectedTicket.value = { ...selectedTicket.value, ...res.data }
    await loadTickets()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Failed to update status'
  } finally {
    ownerStatusBusy.value = false
  }
}

function goToList() {
  currentView.value = 'list'
  selectedTicket.value = null
  replyText.value = ''
}

function goToCreate() {
  currentView.value = 'create'
  error.value = ''
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return ''
  return dayjs(ts).fromNow()
}

function formatDate(ts: string): string {
  return dayjs(ts).format('MMM D, YYYY h:mm A')
}

function statusLabel(s: string): string {
  if (s === 'open') return t('supportView.statOpen')
  if (s === 'in_progress') return t('supportView.statInProgress')
  if (s === 'resolved') return t('supportView.statResolved')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function categoryLabel(c: string): string {
  const found = categories.find(x => x.value === c)
  return found ? found.label : c
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  loadTickets()
  loadStats()
})

/* §S6 — NOTHING EVER TOLD THIS VIEW ANYTHING. It loaded once on mount and a
   reply from the other side sat invisible until somebody reloaded by hand.
   The cue is cross-worker (Redis) and reaches BOTH the ticket owner and the
   desk; see `useSupportStream` and `support.py::_emit_support_event` for why
   the pre-existing per-worker push would have been worse than silence.
   ⚠ The list refresh is `quiet` so a live cue never throws the spinner over a
   queue the operator is reading. The detail is re-pulled only when the cue is
   about the ticket that is actually open, and only `selectedTicket` is
   replaced, so a half-typed reply survives. */
useSupportStream({
  onChange: (cue) => {
    loadTickets({ quiet: true })
    loadStats()
    if (cue && selectedTicket.value && selectedTicket.value.id === cue.ticket_id) {
      refreshOpenTicket(cue.ticket_id)
    }
  },
  onPoll: () => {
    loadTickets({ quiet: true })
    loadStats()
    if (selectedTicket.value) refreshOpenTicket(selectedTicket.value.id)
  },
})

let detailSeq = 0
async function refreshOpenTicket(ticketId: number) {
  const seq = ++detailSeq
  try {
    const endpoint = isAdmin.value
      ? `/admin/support/tickets/${ticketId}`
      : `/support/tickets/${ticketId}`
    const res = await apiClient.get(endpoint)
    // Still the same ticket, and still the newest request for it.
    if (seq === detailSeq && selectedTicket.value && selectedTicket.value.id === ticketId) {
      selectedTicket.value = { ...selectedTicket.value, ...res.data }
    }
  } catch {
    /* Immediacy only — the thread on screen is still what the server last said. */
  }
}
</script>

<template>
  <div class="st-page sp-page">

    <!-- Page header -->
    <div class="st-page-header">
      <div class="st-page-header-inner sp-header-flex">
        <div>
          <h1 class="st-page-title">{{ t('supportView.title') }}</h1>
          <p class="st-page-sub">{{ t('supportView.subtitle') }}</p>
        </div>
        <div class="sp-header-actions">
          <button
            v-if="currentView !== 'list'"
            class="sp-btn-ghost"
            @click="goToList"
          >
            {{ t('supportView.back') }}
          </button>
          <button
            v-if="currentView === 'list'"
            class="st-btn-primary"
            data-testid="sp-new"
            @click="goToCreate"
          >
            {{ t('supportView.newTicket') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Stats bar — §S7: these are QUEUE-WIDE counts from the database, not a
         tally of the rows on screen. They deliberately ignore the filters: the
         bar answers "what is in the queue", the list answers "what am I looking
         at", and collapsing those two questions is what made the old counters
         wrong the moment the list was truncated. -->
    <div v-if="currentView === 'list'" class="sp-stats-bar" data-testid="sp-stats-bar">
      <div class="sp-stat">
        <span class="sp-stat-value">{{ ticketStats.total }}</span>
        <span class="sp-stat-label">{{ t('supportView.statTotal') }}</span>
      </div>
      <div class="sp-stat">
        <span class="sp-stat-value sp-color-open">{{ ticketStats.open }}</span>
        <span class="sp-stat-label">{{ t('supportView.statOpen') }}</span>
      </div>
      <div class="sp-stat">
        <span class="sp-stat-value sp-color-progress">{{ ticketStats.in_progress }}</span>
        <span class="sp-stat-label">{{ t('supportView.statInProgress') }}</span>
      </div>
      <div class="sp-stat">
        <span class="sp-stat-value sp-color-resolved">{{ ticketStats.resolved }}</span>
        <span class="sp-stat-label">{{ t('supportView.statResolved') }}</span>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="error" class="sp-error-banner">
      <span>{{ error }}</span>
      <button @click="error = ''" class="sp-error-dismiss">{{ t('supportView.dismiss') }}</button>
    </div>

    <!-- Loading -->
    <div v-if="loading && currentView !== 'detail'" class="sp-loading">
      <div class="sp-spinner"></div>
      <span>{{ t('supportView.loading') }}</span>
    </div>

    <!-- ═══════════════════════════════════════ -->
    <!-- TICKET LIST VIEW                        -->
    <!-- ═══════════════════════════════════════ -->
    <div v-if="currentView === 'list' && !loading">

      <!-- Filters -->
      <div class="sp-filters">
        <div class="sp-filter-group">
          <label class="st-label">{{ t('supportView.filterStatus') }}</label>
          <select v-model="filterStatus" class="st-select sp-filter-select" :aria-label="t('supportView.filterStatus')">
            <option value="all">{{ t('supportView.allStatuses') }}</option>
            <option value="open">{{ t('supportView.statOpen') }}</option>
            <option value="in_progress">{{ t('supportView.statInProgress') }}</option>
            <option value="resolved">{{ t('supportView.statResolved') }}</option>
            <option value="closed">Closed</option>
          </select>
        </div>
        <div v-if="isAdmin" class="sp-filter-group">
          <label for="supportview-sel-556" class="st-label">{{ t('supportView.filterPriority') }}</label>
          <select id="supportview-sel-556" v-model="adminFilterPriority" class="st-select sp-filter-select">
            <option value="all">{{ t('supportView.allPriorities') }}</option>
            <option v-for="p in priorities" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
        </div>
        <div v-if="isAdmin" class="sp-filter-group">
          <label for="supportview-sel-563" class="st-label">{{ t('supportView.filterCategory') }}</label>
          <select id="supportview-sel-563" v-model="adminFilterCategory" class="st-select sp-filter-select">
            <option value="all">{{ t('supportView.allCategories') }}</option>
            <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
          </select>
        </div>
      </div>

      <!-- Empty state -->
      <ReadFailedNotice v-if="ticketsFailed && tickets.length === 0" :retry="() => loadTickets()" />
      <div v-else-if="tickets.length === 0" class="sp-empty">
        <div class="sp-empty-icon">&#128172;</div>
        <h3>{{ t('supportView.noTickets') }}</h3>
        <p>{{ filterStatus !== 'all' ? t('supportView.tryFilter') : t('supportView.createFirst') }}</p>
        <button v-if="filterStatus === 'all'" class="st-btn-primary" @click="goToCreate">{{ t('supportView.createTicketBtn') }}</button>
      </div>

      <!-- Ticket list -->
      <div v-else class="sp-ticket-list">
        <div
          v-for="ticket in tickets"
          :key="ticket.id"
          class="sp-ticket-card"
          @click="loadTicketDetail(ticket.id)"
        >
          <div class="sp-ticket-top">
            <div class="sp-ticket-id">#{{ ticket.id }}</div>
            <span :class="['sp-badge', statusColors[ticket.status]]">{{ statusLabel(ticket.status) }}</span>
            <span :class="['sp-badge', priorityColors[ticket.priority]]">{{ ticket.priority }}</span>
            <span class="sp-badge sp-cat-badge">{{ categoryIcons[ticket.category] }}</span>
          </div>
          <h3 class="sp-ticket-subject">{{ ticket.subject }}</h3>
          <div class="sp-ticket-meta">
            <span v-if="isAdmin && ticket.developer_email" class="sp-ticket-dev">
              {{ ticket.developer_name || ticket.developer_email }}
            </span>
            <span class="sp-ticket-time">{{ formatTime(ticket.updated_at) }}</span>
            <span v-if="ticket.message_count" class="sp-ticket-msgs">
              {{ ticket.message_count }} message{{ ticket.message_count !== 1 ? 's' : '' }}
            </span>
          </div>
          <p v-if="ticket.last_message_preview" class="sp-ticket-preview">{{ ticket.last_message_preview }}</p>
        </div>
      </div>

      <!-- §S7 — a real pager. "Is there another page" is answered by asking for
           one row more than we render, so it is a fact about the database
           rather than a guess. We deliberately do NOT print a page count: that
           would need a COUNT per filter combination, and inventing a total is
           how the old counters started lying. -->
      <div v-if="page > 0 || hasMore" class="sp-pager" data-testid="sp-pager">
        <button class="sp-status-btn" :disabled="page === 0 || loading"
                data-testid="sp-pager-prev" @click="goToPage(page - 1)">
          {{ t('supportView.pagerPrev', 'Previous') }}
        </button>
        <!-- ⚠ `tp`, not a concatenation. "Page 2" is "第 2 页" in Chinese and
             "2 ページ目" in Japanese: the number does not sit at the same end of
             the phrase in every language, so the ordinal has to ride INSIDE the
             translated string. `t(key, text, params)` would return the fallback
             verbatim with a literal {n} on screen. -->
        <span class="sp-pager-pos" data-testid="sp-pager-pos">
          {{ tp('supportView.pagerPage', 'Page {n}', { n: page + 1 }) }}
        </span>
        <button class="sp-status-btn" :disabled="!hasMore || loading"
                data-testid="sp-pager-next" @click="goToPage(page + 1)">
          {{ t('supportView.pagerNext', 'Next') }}
        </button>
      </div>
    </div>

    <!-- ═══════════════════════════════════════ -->
    <!-- CREATE TICKET VIEW                      -->
    <!-- ═══════════════════════════════════════ -->
    <div v-if="currentView === 'create'" class="sp-create">
      <div class="st-card st-card-accent">
        <div class="st-card-title">{{ t('supportView.newTicketTitle') }}</div>

        <div class="sp-form-row">
          <label class="st-label" for="sp-subject">{{ t('supportView.subjectLabel') }}</label>
          <input
            id="sp-subject"
            v-model="newTicket.subject"
            class="st-input"
            :placeholder="t('supportView.subjectPlaceholder')"
            maxlength="200"
          />
        </div>

        <div class="sp-form-row sp-form-row-2col">
          <div>
            <label class="st-label" for="sp-category">{{ t('supportView.categoryLbl') }}</label>
            <select id="sp-category" v-model="newTicket.category" class="st-select">
              <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </div>
          <div>
            <label class="st-label" for="sp-priority">{{ t('supportView.priorityLbl') }}</label>
            <select id="sp-priority" v-model="newTicket.priority" class="st-select">
              <option v-for="p in priorities" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <div class="sp-form-row">
          <label class="st-label" for="sp-message">{{ t('supportView.messageLabel') }}</label>
          <textarea
            id="sp-message"
            v-model="newTicket.message"
            class="st-textarea sp-textarea-large"
            :placeholder="t('supportView.messagePlaceholder')"
          ></textarea>
        </div>

        <div class="sp-form-actions">
          <button class="sp-btn-ghost" @click="goToList">{{ t('supportView.cancel') }}</button>
          <button
            class="st-btn-primary"
            :disabled="creating || !newTicket.subject.trim() || !newTicket.message.trim()"
            data-testid="sp-submit"
            @click="createTicket"
          >
            {{ creating ? t('supportView.submitting') : t('supportView.submitTicket') }}
          </button>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════ -->
    <!-- TICKET DETAIL VIEW                      -->
    <!-- ═══════════════════════════════════════ -->
    <div v-if="currentView === 'detail' && selectedTicket" class="sp-detail">

      <!-- Ticket header card -->
      <div class="st-card st-card-accent sp-detail-header">
        <div class="sp-detail-title-row">
          <h2 class="sp-detail-subject">{{ selectedTicket.subject }}</h2>
          <span :class="['sp-badge sp-badge-lg', statusColors[selectedTicket.status]]">
            {{ statusLabel(selectedTicket.status) }}
          </span>
        </div>
        <div class="sp-detail-meta">
          <span class="sp-badge sp-cat-badge">{{ categoryLabel(selectedTicket.category) }}</span>
          <span :class="['sp-badge', priorityColors[selectedTicket.priority]]">{{ selectedTicket.priority }}</span>
          <span class="sp-detail-time">{{ t('supportView.createdAt', { time: formatTime(selectedTicket.created_at) }) }}</span>
          <span class="sp-detail-time">Ticket #{{ selectedTicket.id }}</span>
        </div>

        <!-- Admin status controls -->
        <div v-if="isAdmin" class="sp-admin-controls">
          <label class="st-label">{{ t('supportView.changeStatus') }}</label>
          <div class="sp-status-buttons">
            <button
              v-for="s in ['open', 'in_progress', 'resolved', 'closed']"
              :key="s"
              :class="['sp-status-btn', selectedTicket.status === s ? 'sp-status-btn-active' : '']"
              data-testid="sp-admin-status"
              @click="changeStatus(selectedTicket.id, s)"
            >
              {{ statusLabel(s) }}
            </button>
          </div>

          <!-- §CHATDESK C4 — what the customer allowed the desk to READ, and the
               read-only transcript behind a LIVE grant. Every open is audited;
               a closed ticket refuses at read time even if a revocation write
               was missed (fail closed, both halves). -->
          <div v-if="isAdmin" class="sp-review-pane" data-testid="sp-review-pane">
            <div class="sp-review-head">{{ t('cdr.deskTitle', 'Conversations the customer allowed you to review') }}</div>
            <p v-if="reviewGrantsRead === 'reading'" class="sp-review-empty" role="status">{{ t('common.loading', 'Loading…') }}</p>
            <ReadFailedNotice v-else-if="reviewGrantsRead === 'unread'" dense
                              :retry="() => selectedTicket && loadReviewGrants(selectedTicket.id)" />
            <p v-else-if="!reviewGrants.length" class="sp-review-empty" data-testid="sp-review-empty">
              {{ t('cdr.deskEmpty', 'None. The customer grants access from their ticket thread; access is read-only and ends with the ticket.') }}</p>
            <div v-for="g in reviewGrants" :key="g.grant_id" class="sp-review-row" :data-testid="'sp-review-' + g.grant_id">
              <span class="sp-review-title">{{ g.conversation_title || g.conversation_kind }}</span>
              <span :class="['sp-review-chip', g.live ? 'sp-review-chip--live' : 'sp-review-chip--dead']">
                {{ g.live ? t('cdr.live', 'live') : (g.revoked_at ? t('cdr.revoked', 'revoked') : t('cdr.ended', 'ended')) }}</span>
              <button v-if="g.live" class="sp-review-openbtn" :data-testid="'sp-review-open-' + g.grant_id"
                      @click="openReviewTranscript(g)">{{ t('cdr.open', 'Read') }}</button>
            </div>
            <div v-if="reviewOpen" class="sp-review-transcript" data-testid="sp-review-transcript">
              <div class="sp-review-thead">{{ t('cdr.readOnly', 'Read-only transcript') }} · {{ reviewOpen.conversation_title || reviewOpen.conversation_kind }}
                <button class="sp-review-close" @click="reviewOpen = null; reviewMsgs = []">×</button></div>
              <p v-if="reviewErr" class="sp-review-err" data-testid="sp-review-err">{{ reviewErr }}</p>
              <div v-for="m2 in reviewMsgs" :key="m2.id" class="sp-review-msg">
                <span class="sp-review-who">{{ m2.sender_name || m2.sender_ptype }}</span>
                <span class="sp-review-body">{{ m2.body }}</span>
              </div>
            </div>
          </div>

          <!-- §S12 — HIS REPORT: "there is also no admin controls in the support
               admin view in the fe." Priority and category were set once by the
               customer and by nobody ever again, while THIS view has offered
               admin filters on both since it was written: a queue sortable by
               two values only its filer could choose.
               These do not speak in the customer's thread and do not notify —
               a status change is a statement TO the customer, re-prioritising
               is the desk ordering its own work. It lands in the admin audit
               log instead. See `support.py::admin_triage_ticket`. -->
          <div class="sp-triage-row" data-testid="sp-admin-triage">
            <div class="sp-triage-field">
              <label for="supportview-sel-761" class="st-label">{{ t('supportView.priorityLbl') }}</label>
              <select id="supportview-sel-761"
                class="st-select sp-filter-select"
                data-testid="sp-triage-priority"
                :disabled="triageBusy"
                :value="selectedTicket.priority"
                @change="setTriage('priority', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="p in priorities" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </div>
            <div class="sp-triage-field">
              <label for="supportview-sel-773" class="st-label">{{ t('supportView.categoryLbl') }}</label>
              <select id="supportview-sel-773"
                class="st-select sp-filter-select"
                data-testid="sp-triage-category"
                :disabled="triageBusy"
                :value="selectedTicket.category"
                @change="setTriage('category', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="c in categories" :key="c.value" :value="c.value">{{ c.label }}</option>
              </select>
            </div>
          </div>
          <p class="sp-owner-note" data-testid="sp-triage-note">
            {{ t('supportView.triageNote',
                  'Priority and category are desk triage. The customer is not notified, and it is not written into their thread.') }}
          </p>
        </div>

        <!-- §S2 — the owner's own two states. `resolved` is deliberately not
             here: it is the desk's verdict about the work, not the customer's. -->
        <div v-else-if="showOwnerStatus" class="sp-admin-controls" data-testid="sp-owner-status">
          <div class="sp-status-buttons">
            <button
              v-if="selectedTicket.status !== 'closed'"
              class="sp-status-btn" data-testid="sp-owner-close"
              :disabled="ownerStatusBusy"
              @click="setMyStatus('closed')"
            >{{ t('supportView.closeTicket', 'Close ticket') }}</button>
            <button
              v-else
              class="sp-status-btn" data-testid="sp-owner-reopen"
              :disabled="ownerStatusBusy"
              @click="setMyStatus('open')"
            >{{ t('supportView.reopenTicket', 'Reopen ticket') }}</button>
          </div>
          <p class="sp-owner-note">{{ t('supportView.ownerStatusNote',
            'You can close this ticket or reopen it. Marking it resolved is the support team’s call.') }}</p>
        </div>
      </div>

      <!-- Message thread -->
      <div class="sp-thread">
        <div
          v-for="msg in selectedTicket.messages"
          :key="msg.id"
          :class="['sp-msg', msg.sender_type === 'admin' ? 'sp-msg-admin' : 'sp-msg-user']"
        >
          <div class="sp-msg-header">
            <span class="sp-msg-sender">
              <!-- §S8/S3 (2026-08-25) — "YOU" is a claim about the READER, and
                   this view was written for one role and later handed a second.
                   An admin opening a customer's ticket was told the customer's
                   own words were theirs. The badge now asks who is reading:
                   `user` messages are YOU only on a ticket you own, and are the
                   CUSTOMER's otherwise. -->
              <span class="sp-msg-sender-badge" data-testid="sp-msg-badge"
                    :class="msg.sender_type === 'admin' ? 'sp-badge-admin' : 'sp-badge-user'">
                {{ msg.sender_type === 'admin'
                     ? t('supportView.msgAdmin')
                     : (iOwnSelected ? t('supportView.msgYou') : t('supportView.msgCustomer', 'CUSTOMER')) }}
              </span>
              {{ msg.sender_name || (msg.sender_type === 'admin' ? t('supportView.msgAdminName') : t('supportView.msgUserName')) }}
            </span>
            <span class="sp-msg-time" :title="formatDate(msg.created_at)">{{ formatTime(msg.created_at) }}</span>
          </div>
          <div class="sp-msg-body">{{ msg.message }}</div>
        </div>
      </div>

      <!-- Reply box — §S9: on a settled ticket the box itself now carries the
           state. S8 put a sentence ABOVE it explaining what sending would do,
           but the control stayed visually identical to the one on a live
           ticket, so a closed ticket still LOOKED like an open conversation.
           A note that has to be read to know the state of the thing under it
           is doing the work a state should do. -->
      <div :class="['sp-reply-box', 'st-card', ticketSettled ? 'sp-reply-box--settled' : '']"
           data-testid="sp-reply-box">
        <!-- §S5 — the label follows the RAIL this reply will actually take, so
             an admin answering their own ticket is not told they are the desk. -->
        <div class="st-card-title sp-reply-title-row" data-testid="sp-reply-title">
          <span>{{ replyAsDesk ? t('supportView.adminReply') : t('supportView.yourReply') }}</span>
          <span v-if="ticketSettled" class="sp-reply-state" data-testid="sp-reply-state">
            {{ statusLabel(selectedTicket.status) }}
          </span>
        </div>
        <textarea
          v-model="replyText"
          data-testid="sp-reply"
          :aria-label="t('supportView.sendReply')"
          class="st-textarea sp-textarea-reply"
          :placeholder="ticketSettled
            ? (reopensOnReply
                ? t('supportView.replyPlaceholderReopen', 'Reply and reopen this ticket…')
                : t('supportView.replyPlaceholderSettled', 'Reply without changing the status…'))
            : (replyAsDesk ? t('supportView.adminReplyPlaceholder') : t('supportView.replyPlaceholder'))"
        ></textarea>
        <!-- §S8 (2026-08-25) — a customer's reply reopens a settled ticket, and
             it is right to: a reply IS the customer saying the matter is not
             finished. What was wrong is that only Pocket said so, which made the
             older surface the less honest of the two. Stated only when it is
             true of THIS ticket, so it reads as what the button is about to do
             rather than as a standing disclaimer nobody reads. -->
        <p v-if="reopensOnReply" class="sp-reply-note" data-testid="sp-reply-reopen-note">
          {{ selectedTicket.status === 'closed'
               ? t('supportView.replyReopensClosed', 'This ticket is closed — sending a reply reopens it.')
               : t('supportView.replyReopensResolved', 'This ticket is marked resolved — sending a reply reopens it.') }}
        </p>
        <!-- The desk's reply does NOT move a settled ticket (support.py:571 only
             lifts open -> in_progress). Saying so stops an admin from reading an
             unchanged status as a failed send. -->
        <p v-else-if="deskKeepsStatus" class="sp-reply-note" data-testid="sp-reply-desk-note">
          {{ t('supportView.replyKeepsStatus',
                'Answering does not change the status — set it explicitly above if this is not finished.') }}
        </p>
        <div class="sp-reply-actions">
          <button
            class="st-btn-primary"
            :disabled="replying || !replyText.trim()"
            data-testid="sp-reply-send"
            @click="sendReply"
          >
            {{ replying ? t('supportView.sending') : t('supportView.sendReply') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════
   Support View — Neural Command Design System
   ═══════════════════════════════════════════════════════════ */

.sp-page {
  position: relative;
  z-index: 1;
}

/* ── Header ─── */
.sp-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sp-header-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

/* ── §S7 pager ─── */
.sp-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 18px;
}
.sp-pager-pos {
  font-family: var(--st-mono, monospace);
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
}

/* ── §S12 triage ─── */
.sp-triage-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 14px;
}
.sp-triage-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 160px;
}

/* ── §S9 a settled ticket's reply box looks settled ─── */
.sp-reply-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.sp-reply-state {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 999px;
  color: var(--st-text-muted, #8696b8);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
}
.sp-reply-box--settled {
  border-style: dashed;
  opacity: 0.92;
}

/* ── Ghost button ─── */
.sp-btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  background: transparent;
  color: var(--st-text-muted, #8696b8);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
  border-radius: var(--st-radius, 8px);
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.sp-btn-ghost:hover {
  border-color: var(--st-cyan, var(--nc-primary));
  color: var(--st-cyan, var(--nc-primary));
  background: rgba(var(--nc-primary-rgb), 0.06);
}

/* ── Stats bar ─── */
.sp-stats-bar {
  display: flex;
  gap: 16px;
  padding: 0 32px;
  margin-bottom: 24px;
}
.sp-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 24px;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
  border-radius: var(--st-radius-lg, 12px);
  min-width: 100px;
}
.sp-stat-value {
  font-family: var(--st-mono, monospace);
  font-size: 24px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
}
.sp-stat-label {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
  margin-top: 4px;
}
.sp-color-open     { color: #60a5fa !important; }
.sp-color-progress { color: #fbbf24 !important; }
.sp-color-resolved { color: #34d399 !important; }

/* ── Error banner ─── */
.sp-error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 77, 106, 0.12);
  border: 1px solid rgba(255, 77, 106, 0.3);
  border-radius: var(--st-radius, 8px);
  padding: 12px 20px;
  margin: 0 32px 20px;
  color: #ff4d6a;
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
}
.sp-error-dismiss {
  background: none;
  border: none;
  color: #ff4d6a;
  cursor: pointer;
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

/* ── Loading ─── */
.sp-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 60px 0;
  color: var(--st-text-muted, #8696b8);
  font-family: var(--st-mono, monospace);
  font-size: 13px;
}
.sp-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
  border-top-color: var(--st-cyan, var(--nc-primary));
  border-radius: 50%;
  animation: sp-spin 0.7s linear infinite;
}
@keyframes sp-spin {
  to { transform: rotate(360deg); }
}

/* ── Filters ─── */
.sp-filters {
  display: flex;
  gap: 16px;
  padding: 0 32px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}
.sp-filter-group {
  min-width: 160px;
}
.sp-filter-select {
  max-width: 200px;
}

/* ── Empty state ─── */
.sp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 80px 32px;
  text-align: center;
}
.sp-empty-icon {
  font-size: 48px;
  opacity: 0.4;
}
.sp-empty h3 {
  font-family: var(--st-mono, monospace);
  font-size: 16px;
  color: var(--st-text, #c8d8f0);
  margin: 0;
}
.sp-empty p {
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
}

/* ── Badges ─── */
.sp-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 9999px;
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  white-space: nowrap;
}
.sp-badge-lg {
  padding: 5px 14px;
  font-size: 11px;
}
.sp-status-open     { background: rgba(96, 165, 250, 0.15); color: #60a5fa; border: 1px solid rgba(96, 165, 250, 0.25); }
.sp-status-progress { background: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.25); }
.sp-status-resolved { background: rgba(52, 211, 153, 0.15); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.25); }
.sp-status-closed   { background: rgba(107, 127, 163, 0.15); color: #8696b8; border: 1px solid rgba(107, 127, 163, 0.25); }
.sp-pri-low    { background: rgba(107, 127, 163, 0.12); color: #8696b8; }
.sp-pri-normal { background: rgba(96, 165, 250, 0.12); color: #60a5fa; }
.sp-pri-high   { background: rgba(251, 146, 60, 0.15); color: #fb923c; }
.sp-pri-urgent { background: rgba(255, 77, 106, 0.15); color: #ff4d6a; }
.sp-cat-badge  { background: rgba(var(--nc-primary-rgb), 0.10); color: var(--st-cyan, var(--nc-primary)); font-size: 9px; letter-spacing: 0.12em; }

/* ── Ticket list ─── */
.sp-ticket-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0 32px;
  padding-bottom: 40px;
}
.sp-ticket-card {
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
  border-radius: var(--st-radius-lg, 12px);
  padding: 20px 24px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.15s;
}
.sp-ticket-card:hover {
  border-color: var(--st-border-hover, rgba(var(--nc-primary-rgb),0.28));
  box-shadow: 0 4px 24px rgba(var(--nc-primary-rgb), 0.06);
  transform: translateY(-1px);
}
.sp-ticket-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.sp-ticket-id {
  font-family: var(--st-mono, monospace);
  font-size: 12px;
  font-weight: 600;
  color: var(--st-text-muted, #8696b8);
}
.sp-ticket-subject {
  font-family: var(--st-sans, sans-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 8px;
  line-height: 1.4;
}
.sp-ticket-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  color: var(--st-text-muted, #8696b8);
  flex-wrap: wrap;
}
.sp-ticket-dev {
  color: var(--st-cyan, var(--nc-primary));
}
.sp-ticket-time {
  color: var(--st-text-dim, #6882ad);
}
.sp-ticket-msgs {
  color: var(--st-text-muted, #8696b8);
}
.sp-ticket-preview {
  font-family: var(--st-sans, sans-serif);
  font-size: 12px;
  color: var(--st-text-dim, #6882ad);
  margin: 10px 0 0;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Create form ─── */
.sp-create {
  padding: 0 32px;
}
.sp-form-row {
  margin-bottom: 20px;
}
.sp-form-row-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.sp-textarea-large {
  min-height: 180px;
}
.sp-form-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

/* ── Detail view ─── */
.sp-detail {
  padding: 0 32px;
  padding-bottom: 40px;
}
.sp-detail-header {
  margin-bottom: 24px;
}
.sp-detail-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.sp-detail-subject {
  font-family: var(--st-sans, sans-serif);
  font-size: 20px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  margin: 0;
  line-height: 1.3;
}
.sp-detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.sp-detail-time {
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  color: var(--st-text-dim, #6882ad);
}

/* ── Admin controls ─── */
.sp-admin-controls {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
}
.sp-owner-note {
  margin: 8px 0 0;
  font-size: 0.78rem;
  opacity: 0.6;
}
/* §S8 — sits between the textarea and the send button, i.e. on the path the
   eye takes to the click. A consequence stated after the button would be an
   apology; stated before it, it is information. */
.sp-reply-note {
  margin: 8px 0 0;
  font-size: 0.78rem;
  opacity: 0.72;
}
.sp-status-buttons {
  display: flex;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.sp-status-btn {
  padding: 6px 16px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb),0.12));
  border-radius: var(--st-radius, 8px);
  color: var(--st-text-muted, #8696b8);
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.15s;
}
.sp-status-btn:hover {
  border-color: var(--st-cyan, var(--nc-primary));
  color: var(--st-text, #c8d8f0);
}
.sp-status-btn-active {
  background: var(--st-cyan-dim, rgba(var(--nc-primary-rgb),0.15));
  border-color: var(--st-cyan, var(--nc-primary));
  color: var(--st-cyan, var(--nc-primary));
}

/* ── Message thread ─── */
.sp-thread {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}
.sp-msg {
  padding: 16px 20px;
  border-radius: var(--st-radius-lg, 12px);
  max-width: 85%;
}
.sp-msg-user {
  align-self: flex-end;
  background: rgba(52, 211, 153, 0.08);
  border: 1px solid rgba(52, 211, 153, 0.18);
  border-left: 3px solid #34d399;
}
.sp-msg-admin {
  align-self: flex-start;
  background: rgba(96, 165, 250, 0.08);
  border: 1px solid rgba(96, 165, 250, 0.18);
  border-left: 3px solid #60a5fa;
}
.sp-msg-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.sp-msg-sender {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
}
.sp-msg-sender-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
}
.sp-badge-user {
  background: rgba(52, 211, 153, 0.2);
  color: #34d399;
}
.sp-badge-admin {
  background: rgba(96, 165, 250, 0.2);
  color: #60a5fa;
}
.sp-msg-time {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
  white-space: nowrap;
}
.sp-msg-body {
  font-family: var(--st-sans, sans-serif);
  font-size: 14px;
  line-height: 1.6;
  color: var(--st-text, #c8d8f0);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Reply box ─── */
.sp-reply-box {
  border-left: 3px solid var(--st-cyan, var(--nc-primary));
}
.sp-textarea-reply {
  min-height: 100px;
  margin-bottom: 12px;
}
.sp-reply-actions {
  display: flex;
  justify-content: flex-end;
}

/* ── Page header overrides (from st-page-header) ─── */
.st-page-header {
  padding: 32px 32px 24px;
}
.st-page-header-inner {
  max-width: 100%;
}
.st-page-title {
  font-family: var(--st-mono, monospace);
  font-size: 22px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  margin: 0;
}
.st-page-sub {
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 6px 0 0;
}

/* ── Responsive ─── */
@media (max-width: 768px) {
  .sp-stats-bar { flex-wrap: wrap; padding: 0 16px; }
  .sp-filters { padding: 0 16px; }
  .sp-ticket-list { padding: 0 16px; }
  .sp-create { padding: 0 16px; }
  .sp-detail { padding: 0 16px; }
  .sp-form-row-2col { grid-template-columns: 1fr; }
  .sp-msg { max-width: 95%; }
  .st-page-header { padding: 24px 16px 16px; }
}

/* §CHATDESK C4 — the desk's review pane */
.sp-review-pane { margin: 12px 0; padding: 10px 12px; border: 1px dashed var(--border-color, rgba(128,128,128,.3)); border-radius: 8px; font-size: .82rem; }
.sp-review-head { font-weight: 600; font-size: .74rem; letter-spacing: .05em; text-transform: uppercase; opacity: .65; margin-bottom: 6px; }
.sp-review-empty { opacity: .55; margin: 0; }
.sp-review-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.sp-review-title { font-weight: 600; }
.sp-review-chip { font-size: .68rem; border: 1px solid currentColor; border-radius: 9px; padding: 0 8px; }
.sp-review-chip--live { color: var(--success-color, #30a46c); }
.sp-review-chip--dead { color: var(--text-secondary, #999); }
.sp-review-openbtn, .sp-review-close { font-size: .72rem; padding: 2px 10px; border-radius: 7px; border: 1px solid var(--border-color, rgba(128,128,128,.35)); background: transparent; color: inherit; cursor: pointer; }
.sp-review-transcript { margin-top: 8px; border-top: 1px solid var(--border-color, rgba(128,128,128,.2)); padding-top: 8px; max-height: 320px; overflow-y: auto; }
.sp-review-thead { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 6px; }
.sp-review-close { margin-left: auto; }
.sp-review-msg { padding: 3px 0; }
.sp-review-who { opacity: .6; margin-right: 8px; font-size: .74rem; }
.sp-review-err { color: var(--danger-color, #e5484d); }
</style>
