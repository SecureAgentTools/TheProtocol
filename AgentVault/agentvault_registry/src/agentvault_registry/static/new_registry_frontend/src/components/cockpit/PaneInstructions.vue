<script setup lang="ts">
/**
 * §COCKPITPOLISH P7.1 (2026-08-31) — INSTRUCTION HISTORY.
 *
 * The desk has exactly one control that makes an agent ACT, and since §COCKPITA R4 every
 * attempt through it has written a `security_audit_logs` row — delivered or not, because
 * an instruction that failed to arrive was still ISSUED. Until now NOTHING RENDERED THEM.
 * A rail that writes and is never read is a rail nobody can tell has stopped writing.
 *
 * This closes the loop: what you told your agents, when, and whether it landed.
 *
 * 🔴 FAILURES ARE THE POINT, NOT AN EXCEPTION. A history that showed only the delivered
 * ones would make the loop look perfect on precisely the day it broke, so an undelivered
 * attempt renders LOUDER than a delivered one and carries the reason the endpoint gave.
 *
 * ⚠ THE TEXT IS NOT HERE AND NEVER WAS. The audit row keeps the instruction's LENGTH, not
 * its content. The pane says so rather than leaving a reader to conclude the field was
 * lost — "we never stored it" and "we stored it and cannot show you" are different facts.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Icon from '@/components/Icon.vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'
import { agentChannelsApi, type InstructionRecord } from '@/services/api/agentChannels'

const { t, tp } = useI18n()
const def = PANES.instructions

const rows = ref<InstructionRecord[]>([])
const textRetained = ref(false)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const r = await agentChannelsApi.instructions(40)
    rows.value = r.instructions || []
    textRetained.value = !!r.text_retained
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && rows.value.length === 0)
const failures = computed(() => rows.value.filter(r => r.outcome !== 'success').length)

function when(iso: string | null): string {
  if (!iso) return '—'
  // ⚠ The audit column is a NAIVE timestamp (no timezone) written in UTC. Parsed as local
  // it reads two hours in the future on this box, so the Z is appended when absent.
  const norm = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const ms = Date.parse(norm)
  if (!Number.isFinite(ms)) return iso
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.instr.empty', 'You have not instructed any agent from this desk yet.')">
    <div class="ins" data-testid="ckd-instructions" data-tour="cockpit-instructions">
      <ul class="ins-list">
        <li v-for="(r, i) in rows" :key="`${r.at}-${i}`" class="ins-row" data-testid="ins-row"
            :class="{ 'is-fail': r.outcome !== 'success' }">
          <Icon :name="r.outcome === 'success' ? 'mdi:check-circle-outline' : 'mdi:alert-circle-outline'"
                class="ins-ic" />
          <AgentLink class="ins-who" :did="r.agent_did"
                     :label="r.agent_name || r.agent_did" :hint="r.agent_name ? r.agent_did : ''" />
          <span class="ins-out" data-testid="ins-outcome"
                :title="r.detail || ''">{{ r.delivery || r.outcome }}</span>
          <span v-if="r.elapsed_ms !== null && r.elapsed_ms !== undefined" class="ins-ms">{{ r.elapsed_ms }}ms</span>
          <span class="ins-when">{{ when(r.at) }}</span>
        </li>
      </ul>

      <p class="ins-foot" data-testid="ins-foot">
        {{ tp('cockpit.instr.foot', '{n} recent · {f} did not arrive', { n: rows.length, f: failures }) }}
        <template v-if="!textRetained">
          — {{ t('cockpit.instr.noText', 'the instruction text is not stored, only its length') }}
        </template>
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ins { display: flex; flex-direction: column; gap: .3rem; }
.ins-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .18rem; }
.ins-row { display: flex; align-items: center; gap: .4rem; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.ins-ic { width: 13px; height: 13px; flex: 0 0 auto; color: var(--nc-success, #3fb950); }
.ins-row.is-fail { color: var(--nc-warning, #d29922); }
.ins-row.is-fail .ins-ic { color: var(--nc-danger, #f85149); }
.ins-who { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ins-out { font-size: .6rem; letter-spacing: .04em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); flex: 0 0 auto; }
.ins-row.is-fail .ins-out { color: var(--nc-danger, #f85149); }
.ins-ms { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .64rem; color: var(--nc-text-muted, #6e7681); flex: 0 0 auto; }
.ins-when { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .64rem; color: var(--nc-text-muted, #6e7681); flex: 0 0 auto; min-width: 2.2rem; text-align: right; }
.ins-foot { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
</style>
