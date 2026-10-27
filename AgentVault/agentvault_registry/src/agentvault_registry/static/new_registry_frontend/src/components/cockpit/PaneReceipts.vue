<script setup lang="ts">
/**
 * §COCKPITSHOW C3 — THE DECISION TRAIL. A module of my own, and the one I would put in
 * front of anyone asking what this system is FOR.
 *
 * The desk already had two aggregate views of consent — Telemetry (how many, how fast) and
 * Latency (the three legs) — and no way to see a single decision. Aggregates are what you
 * watch; the receipt is what you produce when someone asks *"who agreed to this, and what
 * exactly did they see?"* That question is the entire argument for the Cockpit Card, and
 * until now the answer lived only in the API.
 *
 * Each row is one consent event, and it carries the four things that make it evidence:
 *   · WHAT was asked — the verb and the money, from the server-canonical facts, never
 *     re-derived here (the desk rendering a different amount from the one that was signed
 *     is the failure this whole subsystem exists to prevent).
 *   · WHAT HAPPENED — approved, denied, or expired. ⚠ AN EXPIRY IS A DENIAL and is shown
 *     as one: a request that timed out did not "not happen", it was refused by silence.
 *   · HOW LONG the human looked — the read leg, in seconds, beside the posture's floor.
 *   · WHETHER THE ASK WAS REQUIRED — `required` means the gate demanded presence;
 *     `courtesy` means it asked without having to. Folding those together would flatter
 *     the system by making every ask look mandatory.
 *
 * ⚠ `presentation_mismatch` gets its own loud line. It means two surfaces rendered the
 * same challenge differently — the one condition under which a signature does not prove
 * what it appears to prove, and therefore the single most important thing on this pane.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Icon from '@/components/Icon.vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { useCockpitBus } from '@/composables/useCockpitBus'
import { PANES } from './paneRegistry'
import { liabilityApi, type Receipt } from '@/services/api/liability'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.receipts

const rows = ref<Receipt[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    rows.value = (await liabilityApi.receipts({ limit: 40 })).receipts || []
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    if (e?.response?.status === 404) { rows.value = []; err.value = ''; readAt.value = Date.now() }
    else err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
useCockpitBus({ 'liability.resolved': () => { void load() } })
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && rows.value.length === 0)

/** ⚠ Read from the CHALLENGE's own status, never inferred from the presence of a
 *  signature: an approval whose signature failed to store would otherwise read as a
 *  denial, which is the worst direction for this particular mistake. */
function outcome(r: Receipt): { key: string; label: string; tone: string } {
  const st = String(r.challenge?.status || '').toLowerCase()
  if (st === 'approved') return { key: 'approved', label: t('cockpit.rcpt.approved', 'approved'), tone: 'is-ok' }
  if (st === 'denied') return { key: 'denied', label: t('cockpit.rcpt.denied', 'denied'), tone: 'is-no' }
  if (st === 'expired') return { key: 'expired', label: t('cockpit.rcpt.expired', 'expired — a denial by silence'), tone: 'is-no' }
  if (st === 'pending') return { key: 'pending', label: t('cockpit.rcpt.pending', 'still waiting'), tone: 'is-wait' }
  return { key: 'other', label: st || t('cockpit.rcpt.unrecorded', 'not recorded'), tone: 'is-dim' }
}

function what(r: Receipt): string {
  const f = r.challenge?.facts || {}
  const verb = String(r.challenge?.action_type || r.event_type || '').replace(/[._]/g, ' ')
  const amt = f.amount
  const ccy = f.currency
  // ⚠ NEVER a bare number: an amount with no unit is honest, an amount with the wrong
  // unit is what §FOREIGNACT was. If the facts carry no currency, no unit is printed.
  if (amt !== undefined && amt !== null && amt !== '') {
    return `${verb} · ${money(String(amt))}${ccy ? ` ${ccy}` : ''}`
  }
  return verb || '—'
}
function counterparty(r: Receipt): string {
  const f = r.challenge?.facts || {}
  return String(f.counterparty_did || f.purpose || r.action_ref || '')
}
const secs = (ms: number | null) => (ms === null || ms === undefined ? null : ms / 1000)
function readLabel(r: Receipt): string {
  const s = secs(r.legs_ms?.read)
  if (s === null) return t('cockpit.rcpt.noRead', 'read time not recorded')
  return tp('cockpit.rcpt.read', 'looked at it for {s}s', { s: s.toFixed(s < 10 ? 1 : 0) })
}
function ago(iso: string | null): string {
  if (!iso) return ''
  const norm = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const s = Math.max(0, Math.round((Date.now() - Date.parse(norm)) / 1000))
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

const counts = computed(() => {
  const c: Record<string, number> = {}
  for (const r of rows.value) { const k = outcome(r).key; c[k] = (c[k] || 0) + 1 }
  return c
})
const mismatches = computed(() => rows.value.filter(r => r.presentation_mismatch).length)
/** 🔴 THE THIRD STATE, and the reason the second one stopped screaming.
 *  This pane told the Commander that 10 of his receipts "recorded two surfaces rendering
 *  the same ask differently — inspect before relying on the signature". Every one of the
 *  ten was his German desk beside the English phone he approves on: the presentation hash
 *  covers the WORDS on screen, so two languages must hash differently. Comparable ⇒
 *  compared; not comparable ⇒ said so. Reassurance would have been the third lie. */
const incomparable = computed(() => rows.value.filter(r => r.presentation_incomparable && !r.presentation_mismatch).length)
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.rcpt.empty', 'No consent has been asked for on your mandates yet. Every ask leaves a receipt here, whatever the answer.')">
    <div class="rcp" data-testid="ckd-receipts" data-tour="cockpit-receipts">
      <p class="rcp-lede">
        {{ t('cockpit.rcpt.lede', 'Every time an agent needed authority you had not already given, and what you did about it.') }}
      </p>

      <!-- 🔴 The one condition under which a signature does not prove what it appears to. -->
      <p v-if="mismatches" class="rcp-mismatch" data-testid="rcpt-mismatch">
        <Icon name="mdi:alert-circle-outline" class="rcp-mi" />
        {{ tp('cockpit.rcpt.mismatch', '{n} receipt(s) recorded two surfaces rendering the same ask differently — inspect before relying on the signature.', { n: mismatches }) }}
      </p>
      <p v-if="incomparable" class="rcp-incomp" data-testid="rcpt-incomparable"
         :title="t('cockpit.rcpt.incomparableHint', 'The presentation hash covers the words that were on screen, so the same ask rendered in two languages hashes differently by design. Nothing is wrong here — but these receipts carry no cross-surface corroboration either.')">
        {{ tp('cockpit.rcpt.incomparable', '{n} receipt(s) were shown in more than one language, so their renderings cannot be compared — neither agreement nor disagreement was established.', { n: incomparable }) }}
      </p>

      <ul class="rcp-list">
        <li v-for="r in rows" :key="r.evidence_id" class="rcp-row" data-testid="rcpt-row"
            :class="outcome(r).tone">
          <div class="rcp-top">
            <span class="rcp-what" data-testid="rcpt-what">{{ what(r) }}</span>
            <span class="rcp-out" data-testid="rcpt-outcome">{{ outcome(r).label }}</span>
            <span class="rcp-age">{{ ago(r.at) }}</span>
          </div>
          <p class="rcp-sub">
            <span v-if="counterparty(r)" class="rcp-cp" :title="counterparty(r)">{{ counterparty(r) }}</span>
            <span class="rcp-read">{{ readLabel(r) }}</span>
            <span v-if="r.ask_reason" class="rcp-ask" data-testid="rcpt-ask"
                  :title="r.ask_reason === 'required'
                            ? t('cockpit.rcpt.requiredHint', 'The gate demanded presence — the action could not proceed without it.')
                            : t('cockpit.rcpt.courtesyHint', 'Presence was asked for without being demanded. Counting these as required would flatter the system.')">
              {{ r.ask_reason === 'required' ? t('cockpit.rcpt.required', 'required') : t('cockpit.rcpt.courtesy', 'courtesy') }}
            </span>
          </p>
        </li>
      </ul>

      <p class="rcp-foot" data-testid="rcpt-foot">
        {{ tp('cockpit.rcpt.foot', '{n} receipts · {a} approved · {d} denied · {e} expired',
              { n: rows.length, a: counts.approved || 0, d: counts.denied || 0, e: counts.expired || 0 }) }}
        <RecordLink kind="consent" class="ckd-doorsep"
                    :label="t('cockpit.door.consent', 'Full evidence chain')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.rcp { display: flex; flex-direction: column; gap: .35rem; }
.rcp-lede { margin: 0; font-size: .63rem; line-height: 1.35; color: var(--nc-text-muted, #6e7681); }
.rcp-mismatch { margin: 0; display: flex; gap: .25rem; align-items: baseline; font-size: .64rem; color: var(--nc-danger, #f85149); }
/* Quieter than the mismatch on purpose: this is an absence of evidence, not evidence. */
.rcp-incomp { margin: 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); line-height: 1.4; }
.rcp-mi { width: 12px; height: 12px; flex: 0 0 auto; }
.rcp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .3rem; }
.rcp-row { border-left: 2px solid var(--nc-border, rgba(255,255,255,.14)); padding-left: .45rem; }
.rcp-row.is-ok { border-left-color: rgba(63,185,80,.6); }
.rcp-row.is-no { border-left-color: rgba(248,81,73,.55); }
.rcp-row.is-wait { border-left-color: rgba(210,153,34,.6); }
.rcp-top { display: flex; align-items: baseline; gap: .4rem; }
.rcp-what { flex: 1; min-width: 0; font-size: .73rem; color: var(--nc-text-primary, #e6edf3);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rcp-out { font-size: .58rem; letter-spacing: .04em; text-transform: uppercase; flex: 0 0 auto; }
.is-ok .rcp-out { color: var(--nc-success, #3fb950); }
.is-no .rcp-out { color: var(--nc-danger, #f85149); }
.is-wait .rcp-out { color: var(--nc-warning, #d29922); }
.is-dim .rcp-out { color: var(--nc-text-muted, #6e7681); }
.rcp-age { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .6rem;
  color: var(--nc-text-muted, #6e7681); flex: 0 0 2.2rem; text-align: right; }
.rcp-sub { margin: .05rem 0 0; display: flex; gap: .4rem; font-size: .6rem; color: var(--nc-text-muted, #6e7681); }
.rcp-cp { max-width: 14rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rcp-read { flex: 1; }
.rcp-ask { text-transform: uppercase; letter-spacing: .05em; font-size: .54rem; opacity: .85; }
.rcp-foot { margin: .25rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.ckd-doorsep { margin-left: .4rem; }
</style>
