<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITMODULES M1 — "WHAT DIDN'T HAPPEN". Built 2026-08-31.
 *
 * 🔴 THE MIRROR OF DENIALS, AND THE REASON IT EXISTS. That pane shows what the gates
 * REFUSED — a system working. This one shows what the system TRIED AND FAILED — a system
 * that owes someone something. Every surface in this project renders successes, which is
 * how **66,326 AVT of earned staking rewards sat undelivered for three months**: the
 * distributor wrote an `error_message` and nothing, anywhere, ever read that column again.
 *
 * 🔴 EVERY SOURCE SAYS WHEN, NOT ONLY HOW MANY (§CARDPULLTICK). Three of these four are
 * historical — May 2026, before §FABRICVERIFY fixed the TEG SSL errors in their own error
 * text. A pane that showed "11 webhook failures" without the date would be reporting a
 * fossil as an emergency, and the reader would learn to ignore it.
 *
 * 🔴 A HEALTHY SOURCE RENDERS AS HEALTHY (§RAT). "Nothing failed" and "we did not look" are
 * different facts, so a source with zero open items still appears, with the date it last
 * failed. A pane that hides its healthy sources cannot be distinguished from one that is
 * broken.
 *
 * ⚠ THE DISABLED-WEBHOOK DISTINCTION IS LOAD-BEARING. 11 of this account's webhook failures
 * belong to ONE `.invalid.local` fixture the retry worker correctly switched off in May,
 * while the real webhook ran 83/83. I first reported those 11 to the Commander as
 * "notifications you think you're receiving and aren't" — which was wrong, and wrong in the
 * alarming direction. A muted endpoint is drawn muted and says so.
 *
 * ⚠ ONLY REWARDS CARRY AN ACTION, because re-driving is only safe where TEG dedups on the
 * original idempotency key. A "retry" button on the other three would be a button that
 * either does nothing or does something unrepeatable.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import AgentLink from './AgentLink.vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'
import { usePrivacy } from '@/composables/usePrivacy'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.failures

interface FRow {
  id: string; agent_did?: string | null; agent_name?: string | null
  amount?: string | null; currency?: string | null; at?: string | null
  label?: string | null; detail?: string | null; count?: number | null
  muted?: boolean | null
}
interface FSource {
  key: string; title: string; redrivable: boolean; open: number
  amount?: string | null; currency?: string | null
  last_open_at?: string | null; last_ever_at?: string | null
  sentence: string; rows: FRow[]
}

const sources = ref<FSource[]>([])
const openTotal = ref(0)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
const busy = ref<Record<string, boolean>>({})
const flash = ref('')
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const { data } = await apiClient.get('/developers/me/failures', { params: { limit: 12 } })
    sources.value = Array.isArray(data?.sources) ? data.sources : []
    openTotal.value = Number(data?.open_total ?? 0)
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

/** §COCKPITPOLISH: write, then commit locally — never the other way round. A redrive that
 *  the server refused must not leave a row looking paid. Here the whole list is re-read
 *  from the server on success, so the screen can only ever show what the server holds. */
async function redrive(s: FSource, r: FRow) {
  if (!s.redrivable || busy.value[r.id]) return
  busy.value = { ...busy.value, [r.id]: true }
  flash.value = ''
  try {
    const { data } = await apiClient.post(`/developers/me/failures/rewards/${r.id}/redrive`)
    flash.value = data?.paid
      ? tp('cockpit.failures.paid', 'Paid {amt} {ccy}.',
           { amt: String(data.funded_amount), ccy: String(data.currency || '') })
      : tp('cockpit.failures.partial', 'Partly funded {amt} {ccy} — {short} still owed.',
           { amt: String(data?.funded_amount ?? '0'), ccy: String(data?.currency || ''),
             short: String(data?.shortfall ?? '0') })
    await load()
  } catch (e: any) {
    flash.value = e?.response?.data?.detail || e?.message || 'the payment rail refused'
  } finally {
    const next = { ...busy.value }; delete next[r.id]; busy.value = next
  }
}

const empty = computed(() => !loading.value && sources.value.length === 0)

function ageOf(iso?: string | null): string {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

/** The one sentence a source gets when it has nothing open. It must still carry the age,
 *  or "clear" is indistinguishable from "never ran". */
function clearLine(s: FSource): string {
  return s.last_ever_at
    ? tp('cockpit.failures.clearSince', 'Nothing open. Last failed {age} ago.',
         { age: ageOf(s.last_ever_at) })
    : t('cockpit.failures.clearEver', 'Nothing open, and none on record.')
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.failures.empty', 'No failure sources could be read.')"
             data-testid="ckd-failures">
    <p v-if="flash" class="ckd-f-flash" data-testid="ckd-f-flash">{{ flash }}</p>

    <p class="ckd-f-head" data-testid="ckd-f-head">
      {{ openTotal > 0
          ? tp('cockpit.failures.openN', '{n} things this account tried and did not finish.', { n: openTotal })
          : t('cockpit.failures.openNone', 'Nothing is currently failing. Each source below says when it last did.') }}
    </p>

    <section v-for="s in sources" :key="s.key" class="ckd-f-src" :data-src="s.key"
             :data-open="s.open" data-testid="ckd-f-source">
      <header class="ckd-f-srch">
        <Icon :name="s.open > 0 ? 'mdi:alert-circle-outline' : 'mdi:check-circle-outline'"
              class="ckd-f-ic" :class="s.open > 0 ? 'is-bad' : 'is-ok'" />
        <span class="ckd-f-title">{{ s.title }}</span>
        <span class="ckd-f-count" :class="{ 'is-bad': s.open > 0 }">{{ s.open }}</span>
      </header>

      <!-- The sentence that says what the source MEANS, not what it is called. -->
      <p class="ckd-f-sent">{{ s.sentence }}</p>

      <p v-if="s.open === 0 && !s.rows.length" class="ckd-f-clear" data-testid="ckd-f-clear">
        {{ clearLine(s) }}
      </p>

      <ul v-else class="ckd-f-rows">
        <li v-for="r in s.rows" :key="r.id" class="ckd-f-row"
            :class="{ 'is-muted': r.muted }" data-testid="ckd-f-row">
          <div class="ckd-f-rmain">
            <!-- §COCKPITFRAME F5 — the identity opens the agent card that already existed (`AgentDetailModal`); the desk owns the one dialog. -->
            <!-- ⚠ Not every failure row HAS an agent (a webhook row carries a label), and
                 `AgentLink` renders those as plain text rather than as a dead link. -->
            <AgentLink class="ckd-f-who" :did="r.agent_did"
                       :label="r.agent_name || r.label || r.agent_did || '—'" />
            <span v-if="r.amount" class="ckd-f-amt">
              {{ money(nFmt(r.amount, 2)) }}
              {{ r.currency }}
            </span>
            <span v-else-if="r.count" class="ckd-f-amt">×{{ r.count }}</span>
            <span class="ckd-f-age" :title="r.at || ''">{{ ageOf(r.at) }}</span>
          </div>
          <p v-if="r.detail" class="ckd-f-det">{{ r.detail }}</p>
          <!-- A human presses this. It is deliberately not a background worker: a loop that
               moves money unattended is what this project gates everywhere else. -->
          <button v-if="s.redrivable" class="ckd-f-btn" type="button"
                  :disabled="!!busy[r.id]" data-testid="ckd-f-redrive"
                  @click="redrive(s, r)">
            <Icon name="mdi:restart" />
            {{ busy[r.id] ? t('cockpit.failures.paying', 'Paying…')
                          : tp('cockpit.failures.redrive', 'Pay {who}',
                               { who: r.agent_name || 'this agent' }) }}
          </button>
        </li>
      </ul>

      <p v-if="s.open === 0 && s.rows.length" class="ckd-f-clear" data-testid="ckd-f-clear">
        {{ clearLine(s) }}
      </p>
    </section>
    <p class="ckd-f-foot">
      <RecordLink kind="myAgents" :label="t('cockpit.door.myAgents', 'My agents')" />
    </p>
  </PaneShell>
</template>

<style scoped>
.ckd-f-head { margin: 0 0 .5rem; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.ckd-f-flash { margin: 0 0 .45rem; font-size: .7rem; color: var(--nc-success, #3fb950);
  background: rgba(63,185,80,.09); border-left: 2px solid var(--nc-success, #3fb950);
  padding: .3rem .45rem; border-radius: 3px; }
.ckd-f-src { margin: 0 0 .7rem; }
.ckd-f-srch { display: flex; align-items: center; gap: .35rem; }
.ckd-f-ic { font-size: .85rem; flex: 0 0 auto; }
.ckd-f-ic.is-bad { color: var(--nc-warning, #d29922); }
.ckd-f-ic.is-ok  { color: var(--nc-success, #3fb950); }
.ckd-f-title { flex: 1; font-size: .74rem; font-weight: 600;
  color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ckd-f-count { font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; font-size: .72rem; color: var(--nc-text-muted, #6e7681);
  flex: 0 0 2.2rem; width: 2.2rem; text-align: right; }
.ckd-f-count.is-bad { color: var(--nc-warning, #d29922); font-weight: 600; }
.ckd-f-sent { margin: .1rem 0 .3rem 1.2rem; font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
.ckd-f-clear { margin: .1rem 0 0 1.2rem; font-size: .66rem; color: var(--nc-text-dim, #8b949e); }
.ckd-f-rows { list-style: none; margin: 0 0 0 1.2rem; padding: 0;
  display: flex; flex-direction: column; gap: .3rem; }
.ckd-f-row { border-left: 2px solid var(--nc-warning, #d29922); padding: .15rem 0 .15rem .4rem; }
/* A muted row is one the system already switched off — drawn quiet so it cannot read as
   an emergency the reader must act on. */
.ckd-f-row.is-muted { border-left-color: var(--nc-text-muted, #6e7681); opacity: .68; }
.ckd-f-rmain { display: flex; align-items: baseline; gap: .4rem; font-size: .72rem; }
.ckd-f-who { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--nc-text-secondary, #c9d1d9); }
.ckd-f-amt { font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; color: var(--nc-text-primary, #e6edf3); }
.ckd-f-age { font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; font-size: .64rem; color: var(--nc-text-muted, #6e7681);
  flex: 0 0 2.6rem; width: 2.6rem; text-align: right; }
.ckd-f-det { margin: .1rem 0 0; font-size: .63rem; color: var(--nc-text-muted, #6e7681);
  overflow-wrap: anywhere; }
.ckd-f-btn { margin-top: .25rem; display: inline-flex; align-items: center; gap: .25rem;
  font-size: .64rem; padding: .18rem .45rem; border-radius: 3px; cursor: pointer;
  background: var(--nc-bg-elevated, #161b22); color: var(--nc-text-secondary, #c9d1d9);
  border: 1px solid var(--nc-border, #30363d); }
.ckd-f-btn:hover:not(:disabled) { border-color: var(--nc-success, #3fb950); color: var(--nc-success, #3fb950); }
.ckd-f-btn:disabled { opacity: .55; cursor: default; }
.ckd-f-foot { margin: .3rem 0 0; font-size: .62rem; }
</style>
