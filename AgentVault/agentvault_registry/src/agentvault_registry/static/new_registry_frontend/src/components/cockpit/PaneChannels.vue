<script setup lang="ts">
/**
 * §COCKPITA R4 — ONE module, TWO channels, deliberately not blended.
 *
 *   LEFT  (R4a) PROGRESS   what your agents say they are doing, while they do it.
 *                          Observation. Nothing here can act.
 *   RIGHT (R4b) INSTRUCT   send one agent an instruction over its own A2A interface.
 *                          🔴 The only control on this desk that MAKES something happen.
 *
 * They share a pane because they are one conversation, and they are visually separated
 * because reading and acting must never be one gesture. The instruct box therefore names
 * its target, states the transport, and is DISABLED with a reason for any agent whose card
 * declares no A2A interface — measured: Hagrid and Gerald declare none, so a always-enabled
 * button would post into a 404 for two of eleven agents (§DISCREFINE's blank promise).
 *
 * 🔴 "NO NOTES" AND "COULD NOT LOOK" ARE DIFFERENT FACTS. The API answers `degraded` when
 * the buffer is unreadable, and this renders that as an honest gap rather than as quiet.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Icon from '@/components/Icon.vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import AgentLink from './AgentLink.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { PANES } from './paneRegistry'
import { useI18n } from '@/composables/useI18n'
import { agentChannelsApi, type ProgressNote } from '@/services/api/agentChannels'
import { agentApi } from '@/services/api/agents'
import { rankAgents, livenessTier, countLive, LIVE_LIST_PARAMS } from '@/services/agentLiveness'

const { t, tp } = useI18n()
const def = PANES.channels
const props = withDefaults(defineProps<{ pollSeconds?: number }>(), { pollSeconds: 20 })

const notes = ref<ProgressNote[]>([])
const degraded = ref(false)
const degradedReason = ref<string>('')
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)

/* ── the instruct half ── */
const agents = ref<any[]>([])
const target = ref<string>('')
const canInstruct = ref<boolean | null>(null)   // null = not asked yet
const capReason = ref<string | null>(null)
const text = ref('')
const sending = ref(false)
const outcome = ref<string>('')

const nameOf = (a: any) => a?.name || a?.card_data?.name || String(a?.did || '').slice(0, 22)
const targetName = computed(() => {
  const a = agents.value.find(x => (x.did || '') === target.value)
  return a ? nameOf(a) : ''
})

function ago(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  return `${Math.round(s / 3600)}h`
}

/**
 * §COCKPITPOLISH P4 — ROWS NAME THEIR SPEAKER, AND A LOOP DOES NOT EAT THE PANE.
 *
 * The list rendered phase, note, percent and age and never said WHICH agent was talking.
 * With one reporter that reads fine; with eleven it is unreadable — and his screenshot
 * showed the failure mode already: eleven rows alternating IDLE / READING, all from a
 * single agent, with nothing on screen to say so and everything else pushed off.
 *
 * So consecutive notes from the SAME agent in the SAME phase collapse into one row
 * carrying a repeat count and the age of the MOST RECENT of them.
 *
 * ⚠ Collapsing is a kind of hiding, so it is bounded and reversible in meaning: only
 * ADJACENT identical (agent, phase) pairs fold, the count is always shown, and the note
 * text kept is the newest one. A run that resumes after another agent speaks starts a new
 * row rather than being merged across the gap — the timeline stays a timeline.
 */
interface FoldedNote { key: string; did: string; who: string; phase: string; note: string
                       pct: number | null; at: string; repeats: number }

/**
 * §COCKPITTILES T4 — fold by (agent, phase) ACROSS THE PAGE, not only when adjacent.
 *
 * 🔴 The previous version compared each note to the one immediately before it, so an agent
 * alternating IDLE / READING / IDLE / READING folded NOTHING: measured on his desk, fifty
 * near-identical notes reported "0 folded" and filled the pane with the same two lines.
 * Interleaving is the normal case when several agents report at once, which is exactly
 * when a fold is worth having.
 *
 * ⚠ Still the NEWEST row that survives (notes arrive newest-first) and the count is still
 * shown, so folding stays a summary and never a quiet deletion.
 */
const folded = computed<FoldedNote[]>(() => {
  const out: FoldedNote[] = []
  const at = new Map<string, number>()
  for (const n of notes.value) {
    const who = (n as any).agent_name || String(n.did || '').slice(0, 24)
    const key = `${n.did}\u0000${n.phase}`
    const seen = at.get(key)
    if (seen !== undefined) { out[seen].repeats += 1; continue }
    at.set(key, out.length)
    out.push({ key: `${n.did}|${n.at}`, did: n.did, who, phase: n.phase,
               note: n.note, pct: n.pct, at: n.at, repeats: 1 })
  }
  return out
})

/** How many raw notes the fold represents, so "12 notes" never silently becomes "3 rows". */
const foldedAway = computed(() => notes.value.length - folded.value.length)
const reporters = computed(() => new Set(notes.value.map(n => n.did)).size)

async function loadProgress() {
  try {
    const r = await agentChannelsApi.progress(60)
    notes.value = r.notes || []
    degraded.value = !!r.degraded
    degradedReason.value = r.reason || ''
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}

/** 🔴 SEARCH, NEVER PAGE. The first cut listed `getMyAgents({limit:100})` and called it a
 *  picker. On this registry the account owns 4,130 agents, so 97.6% of them could not be
 *  chosen at all — including Ironhand Alpha, which is how the browser battery caught it.
 *  `/developers/me/agents` is capped at 200 by design (lifting it is a 13MB response), so
 *  the answer is the server-side search the agents pane already uses, not a bigger page. */
const q = ref('')
const searching = ref(false)
const capped = ref(false)
/** §FESUITE (V0577): the picker's read got no answer. It was swallowed ("degrades to pick nothing"), so the picker sat
 *  empty under "Most recently active first — 0 of these called this registry…": a failed read read as no live agents. */
const agentsFailed = ref(false)

/** 🔴 AND THE DEFAULT LIST IS RANKED BY LIVENESS, NOT BY AGE (§COCKPITPOLISH P2).
 *  Searching already reached the whole fleet; what the operator actually saw on opening
 *  the dropdown was `<no name>`, `forge-a-gen-*` and `extmtls-probe-invalid` twelve times
 *  over, because `created_at DESC` over 4,130 agents is a list of fixtures. The server now
 *  offers `sort=live` and BOTH pickers ask the same shared rail for it. */
async function loadAgents(term = '') {
  searching.value = true
  try {
    const r: any = term.trim().length >= 2
      ? await agentApi.getMyAgents({ q: term.trim(), limit: 25, topLevelOnly: false })
      : await agentApi.getMyAgents({ ...LIVE_LIST_PARAMS })
    const list = Array.isArray(r) ? r : (r?.items || r?.results || [])
    // Re-rank client-side too: a search result set has no server ordering, and the
    // ranking is what decides which of 25 rows the eye lands on.
    agents.value = rankAgents(list)
    // Say so when the list is a slice: a name you cannot see is not a name that is absent.
    capped.value = !term.trim() && list.length >= LIVE_LIST_PARAMS.limit
    agentsFailed.value = false
  } catch {
    // the instruct half degrades to "pick nothing", and SAYS so; progress still renders
    agents.value = []
    capped.value = false
    agentsFailed.value = true
  }
  finally { searching.value = false }
}

const liveCount = computed(() => countLive(agents.value))

/**
 * 🔴 THE BAND IS AN `<optgroup>`, NOT A CHARACTER GLUED TO THE NAME.
 *
 * The first cut prefixed each option with a filled or hollow dot. It read fine and it was
 * wrong twice over: the mark became part of the option's ACCESSIBLE NAME ("dot Ironhand
 * Alpha"), and it broke every caller that addresses an option by its name — the §COCKPITA
 * battery selects `{ label: 'Ironhand Alpha' }` and silently matched nothing, so the
 * capability panel never appeared and a green suite went amber for a reason that had
 * nothing to do with the product. `<optgroup>` is the native, announced way to band a
 * select, and it leaves the name alone. (The desk's chips had the identical bug in the
 * same hour: decoration never joins the text run.)
 */
const bands = computed(() => {
  const live: any[] = [], quiet: any[] = [], rest: any[] = []
  for (const a of agents.value) {
    const t = livenessTier(a)
    if (t === 'fresh' || t === 'recent') live.push(a)
    else if (t === 'quiet') quiet.push(a)
    else rest.push(a)
  }
  return [
    { key: 'live', label: t('cockpit.ch.bandLive', 'Active in the last 15 minutes'), rows: live },
    { key: 'quiet', label: t('cockpit.ch.bandQuiet', 'Active in the last day'), rows: quiet },
    { key: 'rest', label: t('cockpit.ch.bandRest', 'Not seen recently'), rows: rest },
  ].filter(b => b.rows.length)
})

/** Ask the SERVER whether this agent can be instructed. The card is on the client, but the
 *  server owns the answer — two implementations of "can this be instructed" is how the
 *  button and the endpoint come to disagree. */
async function onTargetChange() {
  canInstruct.value = null; capReason.value = null; outcome.value = ''
  if (!target.value) return
  try {
    const c = await agentChannelsApi.capability(target.value)
    canInstruct.value = c.can_instruct
    capReason.value = c.reason
  } catch (e: any) {
    canInstruct.value = false
    capReason.value = e?.response?.data?.detail || 'Could not read this agent’s channel.'
  }
}

async function send() {
  if (!target.value || !text.value.trim() || canInstruct.value !== true) return
  sending.value = true; outcome.value = ''
  try {
    const r = await agentChannelsApi.instruct(target.value, text.value.trim())
    outcome.value = t('cockpit.ch.delivered', 'Delivered in {ms} ms.').replace('{ms}', String(r?.elapsed_ms ?? '—'))
    text.value = ''
    await loadProgress()   // the agent may already have said something about it
  } catch (e: any) {
    outcome.value = e?.response?.data?.detail || e?.message || 'not delivered'
  } finally { sending.value = false }
}

let poll: ReturnType<typeof setInterval> | null = null
onMounted(async () => {
  await Promise.all([loadProgress(), loadAgents()])
  poll = setJitteredInterval(loadProgress, Math.max(10, props.pollSeconds) * 1000)
})
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })
</script>

<template>
  <!-- §COCKPITFRAME F1 — ON THE SHELL. HIS REPORT: *"what agents doing, send isntruction …
       have no background."* Both halves are this one pane, and its root measured
       `rgba(0,0,0,0)` against `rgb(19,24,37)` for every pane built on the shell.
       ⚠ `error` is deliberately NOT handed to the shell. A failure to read the PROGRESS
       buffer must not blank the INSTRUCT half — the shell's error state replaces the whole
       body, and half this pane still works. The honest line stays inline, where it is
       about the half it belongs to. -->
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :read-at="readAt" :reload="loadProgress">
  <div class="chn" data-testid="chn-root" data-tour="cockpit-channels">
    <p v-if="err" class="chn-note chn-err" data-testid="chn-error">{{ err }}</p>

    <div class="chn-grid">
      <!-- ══ LEFT: PROGRESS (observation) ══ -->
      <section class="chn-col" data-testid="chn-progress">
        <header class="chn-h">
          <Icon name="mdi:radar" class="chn-hi" />
          <span>{{ t('cockpit.ch.progressTitle', 'What your agents are doing') }}</span>
        </header>

        <p v-if="loading" class="chn-note">{{ t('cockpit.ch.reading', 'Reading…') }}</p>

        <!-- 🔴 the honest gap: could not look ≠ nothing to see -->
        <p v-else-if="degraded" class="chn-note chn-warn" data-testid="chn-degraded">
          {{ degradedReason || t('cockpit.ch.degraded', 'The progress buffer could not be read, so this is not a claim that your agents are idle.') }}
        </p>

        <p v-else-if="!notes.length" class="chn-note" data-testid="chn-empty">
          {{ t('cockpit.ch.noNotes', 'No agent has reported progress yet. Agents report by posting to /agents/progress with their own token.') }}
        </p>

        <ul v-else class="chn-list" data-testid="chn-notes">
          <li v-for="n in folded" :key="n.key" class="chn-row" data-testid="chn-note">
            <!-- §COCKPITFRAME F5 — the speaker opens its card. The DID was already here,
                 in a `title` nobody could click. -->
            <AgentLink class="chn-who" data-testid="chn-who" :did="n.did" :label="n.who" />
            <span class="chn-phase">{{ n.phase }}</span>
            <span class="chn-text">{{ n.note }}</span>
            <span v-if="n.repeats > 1" class="chn-rep" data-testid="chn-repeat"
                  :title="t('cockpit.ch.repeatHint', 'Consecutive notes from this agent in this phase, folded into one row')">
              ×{{ n.repeats }}
            </span>
            <span v-if="n.pct !== null" class="chn-pct">{{ n.pct }}%</span>
            <span class="chn-when">{{ ago(n.at) }}</span>
          </li>
        </ul>
        <p v-if="notes.length" class="chn-fine" data-testid="chn-progress-foot">
          {{ tp('cockpit.ch.progressFoot', '{n} notes from {a} agents · {f} folded into the row above them',
                { n: notes.length, a: reporters, f: foldedAway }) }}
        </p>
      </section>

      <!-- ══ RIGHT: INSTRUCT (the one control that acts) ══ -->
      <section class="chn-col chn-act" data-testid="chn-instruct" data-tour="cockpit-instruct">
        <header class="chn-h">
          <Icon name="mdi:send" class="chn-hi" />
          <span>{{ t('cockpit.ch.instructTitle', 'Send an instruction') }}</span>
        </header>

        <input v-model="q" class="chn-sel" data-testid="chn-search" type="text"
               :placeholder="t('cockpit.ch.search', 'Search your agents by name…')"
               @keyup.enter="loadAgents(q)" @change="loadAgents(q)" />
        <select :aria-label="t('cockpit.ch.pick', 'Choose an agent')" v-model="target" class="chn-sel" data-testid="chn-target" @change="onTargetChange">
          <option value="">{{ t('cockpit.ch.pick', 'Choose an agent…') }}</option>
          <optgroup v-for="b in bands" :key="b.key" :label="b.label" :data-testid="`chn-band-${b.key}`">
            <option v-for="a in b.rows" :key="a.did" :value="a.did" data-testid="chn-opt">{{ nameOf(a) }}</option>
          </optgroup>
        </select>
        <!-- ⚠ The list is RANKED and CAPPED, and it says both. Ranking sinks the 182
             fixture agents without hiding any of them; the cap is what actually hides,
             so the cap is the thing that gets a sentence. -->
        <ReadFailedNotice v-if="agentsFailed" dense :retry="() => loadAgents(q)" data-testid="chn-agents-failed"
          :text="t('cockpit.ch.agentsUnread', 'Your agents could not be read just now, so there is nobody to choose here yet.')" />
        <p v-else class="chn-fine" data-testid="chn-rank">
          {{ tp('cockpit.ch.ranked', 'Most recently active first — {n} of these called this registry in the last 15 minutes.', { n: liveCount }) }}
        </p>
        <p v-if="capped" class="chn-fine" data-testid="chn-capped">
          {{ t('cockpit.ch.capped', 'Showing the first few. Search by name to reach the rest.') }}
        </p>

        <!-- The door states whether it opens, BEFORE it is used. -->
        <p v-if="target && canInstruct === false" class="chn-note chn-warn" data-testid="chn-cannot">
          {{ capReason }}
        </p>
        <p v-else-if="target && canInstruct === true" class="chn-note chn-ok" data-testid="chn-can">
          {{ t('cockpit.ch.viaA2a', 'Reachable over its own A2A interface.') }}
        </p>

        <textarea v-model="text" class="chn-ta" rows="3" data-testid="chn-text"
                  :disabled="canInstruct !== true"
                  :placeholder="t('cockpit.ch.ph', 'What should this agent do?')" />

        <button class="chn-send" data-testid="chn-send"
                :disabled="canInstruct !== true || !text.trim() || sending"
                @click="send">
          {{ sending ? t('cockpit.ch.sending', 'Sending…')
                     : t('cockpit.ch.send', 'Send to {name}').replace('{name}', targetName || '…') }}
        </button>

        <p v-if="outcome" class="chn-note" data-testid="chn-outcome">{{ outcome }}</p>
        <p class="chn-fine">
          {{ t('cockpit.ch.audited', 'Every instruction is recorded against your account, delivered or not.') }}
        </p>
      </section>
    </div>
  </div>
  </PaneShell>
</template>

<style scoped>
.chn { display: flex; flex-direction: column; min-height: 0; gap: .5rem; }
/* §COCKPITSHOW A3 — HIS REPORT: *"send instruction to agent could use some modul height
   alignment."* The two columns are one conversation and read as two unrelated boxes when
   the observation side runs long and the acting side stops halfway up. `align-items:
   stretch` (the grid default, made explicit so nobody "tidies" it to start) plus a
   `margin-top:auto` on the instruct column's fine print means the box fills its share and
   the caption sits on the floor, instead of leaving a hole under the button. */
.chn-grid { display: grid; grid-template-columns: 1fr; gap: .75rem; align-items: stretch; }
@media (min-width: 900px) { .chn-grid { grid-template-columns: 1.2fr 1fr; } }
.chn-col { display: flex; flex-direction: column; gap: .4rem; min-width: 0; }
/* the last line of the acting column is its disclosure — it belongs at the bottom */
.chn-act > .chn-fine:last-child { margin-top: auto; }
/* and the progress list takes the slack on its own side rather than pushing the pane */
.chn-col > .chn-list { flex: 1 1 auto; }
.chn-act { border-left: 1px solid var(--nc-border, #21262d); padding-left: .75rem; }
@media (max-width: 899px) { .chn-act { border-left: 0; padding-left: 0; border-top: 1px solid var(--nc-border, #21262d); padding-top: .6rem; } }
.chn-h { display: flex; align-items: center; gap: .35rem; font-size: .68rem; letter-spacing: .06em;
         text-transform: uppercase; color: var(--nc-text-secondary, #c9d1d9); }
.chn-hi { font-size: .85rem; }
.chn-note { font-size: .68rem; color: var(--nc-text-dim, #8b949e); margin: 0; }
.chn-err { color: var(--nc-danger, #f85149); }
.chn-warn { color: var(--nc-warning, #d29922); }
.chn-ok { color: var(--nc-success, #3fb950); }
.chn-fine { font-size: .6rem; color: var(--nc-text-dim, #8b949e); margin: .2rem 0 0; }
.chn-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; max-height: 15rem; }
.chn-row { display: flex; align-items: baseline; gap: .4rem; padding: .18rem 0;
           border-bottom: 1px solid var(--nc-border-subtle, #1b2128); font-size: .68rem; }
.chn-who { font-size: .64rem; color: var(--nc-text-primary, #e6edf3); flex: 0 0 auto;
  max-width: 9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.chn-rep { font-size: .6rem; color: var(--nc-text-muted, #6e7681); flex: 0 0 auto;
  font-family: var(--nc-font-mono, ui-monospace, monospace); }
.chn-phase { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .62rem;
             text-transform: uppercase; color: var(--nc-primary, #58a6ff); flex: 0 0 auto; }
.chn-text { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chn-pct, .chn-when { flex: 0 0 auto; font-size: .62rem; color: var(--nc-text-dim, #8b949e);
                      font-family: var(--nc-font-mono, ui-monospace, monospace); }
.chn-sel, .chn-ta { width: 100%; background: var(--nc-bg-elevated, #0d1117);
                    border: 1px solid var(--nc-border, #21262d); border-radius: 4px;
                    color: var(--nc-text, #e6edf3); font-size: .72rem; padding: .3rem .4rem; }
.chn-ta { resize: vertical; font-family: inherit; }
.chn-ta:disabled { opacity: .5; }
.chn-send { align-self: flex-start; background: var(--nc-primary, #58a6ff); color: #06121f;
            border: 0; border-radius: 4px; padding: .3rem .7rem; font-size: .7rem;
            font-weight: 600; cursor: pointer; }
.chn-send:disabled { opacity: .45; cursor: not-allowed; }
</style>
