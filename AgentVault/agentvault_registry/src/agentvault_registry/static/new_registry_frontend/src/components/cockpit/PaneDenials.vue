<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITSHOW B4 — REFUSALS. Rewritten 2026-08-31.
 *
 * 🔴 HIS ASK, verbatim: *"make them sound like the real deal NOT!! some approve powerpoint
 * slide 6 or something! real cool examples real world showing value of the system why
 * approvals needed!"*
 *
 * Nothing here is fabricated, and nothing needed to be. This pane previously reported
 * *"No refusals recorded for your agents in the last 30 days"* — while his own agents
 * carried **3,357** of them. The pane fanned out over `/developers/me/agents?sort=balance`
 * and asked the top few for their feeds; the agents holding refusals are the WORKING ones,
 * and the ones holding balance are canaries and sim fixtures. It was not empty, it was
 * looking down the wrong axis, and it reported its sample as the population.
 *
 * One developer-scoped query replaces the fan-out. What it surfaces on day one is the best
 * argument this system has:
 *
 *   3,330 × permission_outside_caveats — an attenuated capability token asked for a
 *          permission its own caveats never granted, and was refused. That is L4 doing
 *          precisely what it exists for, three thousand times, without a human present.
 *      10 × holder_mismatch — a token presented by an agent it was not issued to. The
 *          confused-deputy attack, caught at the gate.
 *       2 × revoked_reuse — a revoked token replayed and refused.
 *       2 × circuit_breaker_trip — the loudest thing that can happen to a token.
 *
 * So each reason is rendered with the SENTENCE that says what actually happened and why it
 * mattered, not the enum. An operator reading `permission_outside_caveats` learns nothing;
 * one reading *"a delegated token reached past the authority it was given"* learns the
 * whole argument for delegation having caveats at all.
 *
 * ⚠ A reason we cannot label is counted, never dropped — the number this pane exists to
 * report must not be quietly understated by rows with unparseable details (§MISUSEDETAIL).
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.denials

interface Row { action: string; reason: string; count: number; latest: string | null; agents: number }
interface Example { action: string; at: string | null; agent_name: string | null; agent_did: string; reason: string | null }

const summary = ref<Row[]>([])
/** §COCKPITTILES T1 — the reason taxonomy is short, but eight was still a constant. */
const FETCH_LIMIT = 20
const listEl = ref<HTMLElement | null>(null)
const { count: fitRows } = useFillCount(listEl, { rowPx: 74, min: 2, max: FETCH_LIMIT, reservePx: 78 })
const shownRows = computed(() => summary.value.slice(0, fitRows.value))
const heldBack = computed(() => Math.max(0, summary.value.length - shownRows.value.length))
const examples = ref<Example[]>([])
const total = ref(0)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const { data } = await apiClient.get('/developers/me/authz-denials', { params: { limit: FETCH_LIMIT, examples: 5 } })
    summary.value = data?.summary || []
    examples.value = data?.examples || []
    total.value = Number(data?.total || 0)
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && summary.value.length === 0)

/** THE SENTENCE, not the enum. Each says what was attempted and what stopped it. */
const SAY: Record<string, { head: string; why: string }> = {
  permission_outside_caveats: {
    head: 'A delegated permit reached past the authority it was given',
    why: 'An attenuated capability asked for a permission its own caveats never granted. Refused at the gate, with no human in the loop and nothing to undo.',
  },
  holder_mismatch: {
    head: 'A permit was presented by an agent it was not issued to',
    why: 'The confused-deputy attack: a valid credential in the wrong hands. Possession alone proves nothing here — the holder is checked against the grant.',
  },
  revoked_reuse: {
    head: 'A revoked permit was replayed',
    why: 'Authority that had already been withdrawn was offered again. Revocation is re-derived per request, so it conveyed nothing.',
  },
  rbac_deny: {
    head: 'An agent attempted something its role does not carry',
    why: 'Authenticated is not authorized. The agent proved who it was and was still refused.',
  },
  spend_deny: {
    head: 'A payment exceeded the agent’s spend policy',
    why: 'The money stopped before the transfer, not after — a limit that only reported afterwards would be a report, not a limit.',
  },
  org_ceiling_deny: {
    head: 'A purchase went past the organisation’s per-transaction cap',
    why: 'The cap is checked before solvency, so an agent with the funds is still refused when the org did not grant that much authority.',
  },
  capability_circuit_breaker_trip: {
    head: 'A capability permit was cut off after repeated misuse',
    why: 'Not one refusal but a pattern of them. The breaker stops the permit rather than the request.',
  },
  rate_per_hour_exceeded: {
    head: 'An agent hit its hourly payment rate limit',
    why: 'Not the size of one payment but the pace of many. A velocity cap is what stops a compromised or looping agent draining an account in small, individually-legal steps.',
  },
}
/** ⚠ A reason may carry its own EVIDENCE after a colon — `rate_per_hour_exceeded:max=30`.
 *  The sentence is looked up on the base, and the tail is kept and shown, because "it hit
 *  a limit" and "it hit a limit OF THIRTY" are different amounts of help. */
function base(reason: string | null | undefined): string {
  return String(reason || '').split(':')[0]
}
function detail(r: Row): string {
  const tail = String(r.reason || '').split(':').slice(1).join(':')
  return tail ? tail.replace(/[_=]/g, ' ') : ''
}
function say(r: Row) {
  const k = r.reason && r.reason !== '(unspecified)' ? base(r.reason) : r.action.replace(/^ironkey\./, '')
  return SAY[k] || {
    head: k.replace(/_/g, ' '),
    why: t('cockpit.denials.unlabelled', 'Recorded at the gate. This build has no sentence for this reason yet — the count is still real.'),
  }
}
function ago(iso: string | null): string {
  if (!iso) return ''
  const norm = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const s = Math.max(0, Math.round((Date.now() - Date.parse(norm)) / 1000))
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.denials.empty2', 'No authorization refusal has been recorded for your agents in this window. That is a real zero, taken across your whole fleet in one query — not a sample.')">
    <div class="dn" data-testid="ckd-denials" data-tour="cockpit-denials" ref="listEl" :data-fit="fitRows">
      <p class="dn-lede" data-testid="dn-lede">
        {{ tp('cockpit.denials.lede', '{n} refusals across your fleet in the last 30 days — each one an action an agent tried to take and could not.', { n: nCount(total) }) }}
      </p>

      <ul class="dn-list">
        <li v-for="r in shownRows" :key="`${r.action}-${r.reason}`" class="dn-row" data-testid="dn-row">
          <div class="dn-head">
            <span class="dn-n" data-testid="dn-count">{{ nCount(r.count) }}</span>
            <span class="dn-say">{{ say(r).head }}</span>
          </div>
          <p class="dn-why">{{ say(r).why }}</p>
          <p class="dn-meta">
            <template v-if="detail(r)"><span class="dn-ev" data-testid="dn-evidence">{{ detail(r) }}</span> · </template>
            {{ tp('cockpit.denials.meta', 'across {a} agent(s) · most recent {age} ago', { a: r.agents, age: ago(r.latest) }) }}
          </p>
        </li>
      </ul>

      <p v-if="heldBack" class="dn-more" data-testid="dn-more">
        {{ tp('cockpit.denials.more', '+{n} more refusal kinds — make the tile taller in Arrange.', { n: heldBack }) }}
      </p>

      <div v-if="examples.length" class="dn-ex" data-testid="dn-examples">
        <p class="dn-ex-h">{{ t('cockpit.denials.recent', 'Most recent') }}</p>
        <p v-for="(e, i) in examples" :key="i" class="dn-ex-r">
          <!-- §COCKPITFRAME F5 — the identity opens the agent card that already existed (`AgentDetailModal`); the desk owns the one dialog. -->
          <AgentLink class="dn-ex-who" :did="e.agent_did" :label="e.agent_name || e.agent_did.slice(0, 22)" />
          <span class="dn-ex-what">{{ (e.reason || e.action.replace(/^ironkey\./, '')).replace(/_/g, ' ') }}</span>
          <span class="dn-ex-age">{{ ago(e.at) }}</span>
        </p>
      </div>
    </div>
  </PaneShell>
</template>

<style scoped>
.dn { display: flex; flex-direction: column; gap: .4rem; }
.dn-lede { margin: 0; font-size: .66rem; line-height: 1.35; color: var(--nc-text-dim, #8b949e); }
.dn-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .45rem; }
.dn-row { border-left: 2px solid rgba(210,153,34,.45); padding-left: .5rem; }
.dn-head { display: flex; align-items: baseline; gap: .4rem; }
.dn-n { font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .82rem; font-weight: 600; color: var(--nc-warning, #d29922); flex: 0 0 auto; }
.dn-say { font-size: .73rem; color: var(--nc-text-primary, #e6edf3); line-height: 1.25; }
.dn-why { margin: .1rem 0 0; font-size: .63rem; line-height: 1.4; color: var(--nc-text-muted, #6e7681); }
.dn-meta { margin: .1rem 0 0; font-size: .58rem; color: var(--nc-text-muted, #6e7681); opacity: .8; }
.dn-ev { font-family: var(--nc-font-mono, ui-monospace, monospace); color: var(--nc-warning, #d29922); opacity: .9; }
.dn-more { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-dim, #8b949e); }
.dn-ex { border-top: 1px solid var(--nc-border-subtle, rgba(255,255,255,.08)); padding-top: .3rem; }
.dn-ex-h { margin: 0 0 .15rem; font-size: .56rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.dn-ex-r { margin: 0; display: flex; gap: .4rem; font-size: .64rem; align-items: baseline; }
.dn-ex-who { flex: 0 0 8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--nc-text-secondary, #c9d1d9); }
.dn-ex-what { flex: 1; color: var(--nc-text-muted, #6e7681); }
.dn-ex-age { color: var(--nc-text-muted, #6e7681); font-family: var(--nc-font-mono, ui-monospace, monospace); }
</style>
