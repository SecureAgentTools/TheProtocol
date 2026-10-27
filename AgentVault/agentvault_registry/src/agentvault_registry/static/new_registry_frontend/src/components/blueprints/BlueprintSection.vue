<template>
  <section :id="`bp-${bp.id}`" class="bps" ref="sectionEl">
    <!-- Header -->
    <header class="bps-head">
      <span class="bps-rank">{{ String(bp.rank).padStart(2, '0') }}</span>
      <div class="bps-head-main">
        <span class="bps-eyebrow">{{ bp.industry }}<span v-if="bp.frontier" class="bps-frontier">{{ t('blueprintsView.frontier.chip', 'FRONTIER') }}</span></span>
        <h2 class="bps-name">{{ bp.systemName }}</h2>
        <p class="bps-promise">{{ bp.promise }}</p>
        <p v-if="bp.frontier" class="bps-frontier-note">{{ t('blueprintsView.frontier.note', 'A frontier chamber: the sector is arriving now and the system is further out than the rest. The rails under it are the same ones, badged the same way.') }}</p>
        <div class="bps-meta">
          <span class="bps-ratio">{{ t('blueprintsView.liveRatio', '{live} of {total} steps on built rails').replace('{live}', String(bp.liveRatio[0])).replace('{total}', String(bp.liveRatio[1])) }}</span>
          <span v-for="r in bp.rails" :key="r" class="bps-railchip" :data-railtip="r">{{ r }} · {{ railName(r) }}</span>
        </div>
      </div>
    </header>

    <!-- Recognition strip: concrete cases before any abstraction -->
    <div v-if="bp.cases.length" class="bps-cases">
      <span class="bps-label">{{ t('blueprintsView.section.cases', 'Recognize your case') }}</span>
      <div class="bps-cases-grid">
        <div v-for="c in bp.cases" :key="c.role" class="bps-case">
          <span class="bps-case-role">{{ c.role }}</span>
          <span class="bps-case-line">{{ c.line }}</span>
        </div>
      </div>
    </div>

    <!-- Problem -->
    <div class="bps-block">
      <span class="bps-label">{{ t('blueprintsView.section.problem', 'The standing problem') }}</span>
      <p class="bps-problem">{{ bp.problem }}</p>
    </div>

    <!-- System -->
    <div class="bps-block">
      <span class="bps-label">{{ t('blueprintsView.section.system', 'The system') }}</span>
      <p v-for="(p, i) in bp.system" :key="i" class="bps-system-p">{{ p }}</p>
    </div>

    <!-- Loom -->
    <div v-if="bp.loom" class="bps-block bps-loom-wrap">
      <span class="bps-label">{{ t('blueprintsView.section.loom', 'Watch it move') }}</span>
      <FlowLoom
        ref="loomRef"
        :nodes="bp.loom.nodes"
        :edges="bp.loom.edges"
        :script="bp.loom.script"
        :aria-title="`${bp.systemName}: request flow`"
        @attack-finished="onAttackFinished"
      />
    </div>

    <!-- Now break it — directly under the Loom so the show and the trigger
         share one viewport; no scroll dance. -->
    <div v-if="bp.attacks.length && bp.loom" class="bps-block bps-attack">
      <span class="bps-label bps-label--deny">{{ t('blueprintsView.section.break', 'Now break it') }}</span>
      <div v-if="bp.attacks.length > 1" class="bps-attack-tabs">
        <button
          v-for="(a, i) in bp.attacks" :key="a.title"
          class="bps-attack-tab" :class="{ 'is-on': i === activeAttack }"
          type="button" @click="selectAttack(i)"
        >{{ a.title }}</button>
      </div>
      <p class="bps-attack-text">{{ attack.attack }}</p>
      <div class="bps-attack-acts">
        <button type="button" class="bps-btn bps-btn--deny" :disabled="attackRunning" @click="runAttack">
          {{ t('blueprintsView.attack.run', 'RUN THE ATTACK') }}
        </button>
        <button v-if="attackDone" type="button" class="bps-btn bps-btn--ghost" @click="resetAttack">
          {{ t('blueprintsView.attack.reset', 'RESET') }}
        </button>
      </div>
      <transition name="bps-fade">
        <div v-if="attackDone" class="bps-attack-result">
          <p><strong>{{ t('blueprintsView.attack.mechanism', 'The mechanism.') }}</strong> {{ attack.mechanism }} <span class="bps-railchip" :data-railtip="attack.rail">{{ attack.rail }} · {{ railName(attack.rail) }}</span></p>
          <p><strong>{{ t('blueprintsView.attack.consequence', 'What did not happen.') }}</strong> {{ attack.consequence }}</p>
          <p v-if="attack.riskRef" class="bps-riskref">
            {{ t('blueprintsView.attack.riskref', 'This attack class is tracked as') }}
            <router-link :to="'/compliance/doc/risk-assessment-framework'" class="bps-riskref-link">{{ attack.riskRef }}</router-link>
            {{ t('blueprintsView.attack.riskrefTail', 'in the public risk register. It was written down before it was demonstrated.') }}
          </p>
        </div>
      </transition>
    </div>

    <!-- Cast -->
    <div v-if="bp.cast.length" class="bps-block">
      <span class="bps-label">{{ t('blueprintsView.section.cast', 'The cast') }}</span>
      <div class="bps-tablewrap">
        <table class="bps-table">
          <thead>
            <tr>
              <th>{{ t('blueprintsView.cast.agent', 'Agent') }}</th>
              <th>{{ t('blueprintsView.cast.role', 'Role') }}</th>
              <th>{{ t('blueprintsView.cast.ceiling', 'Authority ceiling') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in bp.cast" :key="c.agent">
              <td class="bps-mono">{{ c.agent }}</td>
              <td>{{ c.role }}</td>
              <td class="bps-ceiling">{{ c.ceiling }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Primitives -->
    <div class="bps-block">
      <span class="bps-label">{{ t('blueprintsView.section.primitives', 'What the protocol supplies') }}</span>
      <div class="bps-tablewrap">
        <table class="bps-table">
          <thead>
            <tr>
              <th>{{ t('blueprintsView.prim.step', 'Step') }}</th>
              <th>{{ t('blueprintsView.prim.primitive', 'Primitive') }}</th>
              <th>{{ t('blueprintsView.prim.status', 'Status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in bp.primitives" :key="p.step">
              <td>{{ p.step }}</td>
              <td class="bps-mono bps-prim">{{ p.primitive }}</td>
              <td>
                <a v-if="p.href" :href="safeExternalUrl(p.href)" target="_blank" rel="noopener" class="bps-badge" :data-s="p.railStatus">{{ p.railStatus }}</a>
                <span v-else class="bps-badge" :data-s="p.railStatus">{{ p.railStatus }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Stand-up -->
    <div class="bps-block">
      <span class="bps-label">{{ t('blueprintsView.section.standup', 'Standing it up') }}</span>
      <div class="bps-standup">
        <div class="bps-standup-cell">
          <span class="bps-standup-k">{{ t('blueprintsView.standup.infra', 'Infrastructure') }}</span>
          <p>{{ bp.standup.infra }}</p>
        </div>
        <div class="bps-standup-cell">
          <span class="bps-standup-k">{{ t('blueprintsView.standup.agents', 'Agents') }}</span>
          <p>{{ bp.standup.agents }}</p>
        </div>
        <div class="bps-standup-cell">
          <span class="bps-standup-k">{{ t('blueprintsView.standup.integration', 'Integration') }}</span>
          <p>{{ bp.standup.integration }}</p>
        </div>
      </div>
    </div>

    <!-- Legacy bridge (§BPBRIDGE): the systems this chamber runs BESIDE -->
    <div v-if="bp.legacy?.length" class="bps-block">
      <span class="bps-label">{{ t('blueprintsView.section.legacy', 'Runs beside what you already have') }}</span>
      <div class="bps-legacy">
        <div v-for="row in bp.legacy" :key="row.system" class="bps-legacy-row">
          <span class="bps-legacy-sys">{{ row.system }}</span>
          <p>{{ row.connect }}</p>
        </div>
      </div>
      <p class="bps-legacy-note">{{ t('blueprintsView.legacy.parallel',
        'A full sovereign frame boots from pre-built images in minutes, and one server runs several. That is cheap enough to run the whole system in parallel with the legacy stack: the old system keeps running, real work mirrors onto the rails, and you compare ledgers until the evidence settles the argument. Nothing is ripped out.') }}</p>
      <p class="bps-legacy-note bps-legacy-plan">{{ t('blueprintsView.legacy.proxy',
        'Planned: a public proxy library. Free, ready-made connectors for the systems above and whatever else a merge needs, so the bridge is an import, not an integration project.') }}</p>
    </div>

    <!-- Grounding shot -->
    <figure v-if="bp.groundingShot" class="bps-block bps-shot">
      <img :src="bp.groundingShot.src" :alt="bp.groundingShot.caption" loading="lazy" />
      <figcaption>{{ bp.groundingShot.caption }}</figcaption>
    </figure>

    <!-- Non-claims -->
    <div class="bps-block bps-nonclaims">
      <span class="bps-label">{{ t('blueprintsView.section.nonclaims', 'What this does not claim') }}</span>
      <ul>
        <li v-for="n in bp.nonClaims" :key="n">{{ n }}</li>
      </ul>
      <div v-if="bp.complianceRefs?.length" class="bps-comprefs">
        <span class="bps-comprefs-k">{{ t('blueprintsView.section.comprefs', 'Canonical posture:') }}</span>
        <router-link v-for="r in bp.complianceRefs" :key="r.href" :to="r.href" class="bps-compref">{{ r.label }}</router-link>
      </div>
    </div>

    <!-- Wiring diagram (mermaid, lazy) -->
    <details v-if="bp.mermaid" class="bps-wiring" @toggle="onWiringToggle">
      <summary>{{ t('blueprintsView.section.wiring', 'Wiring diagram (technical)') }}</summary>
      <div class="bps-wiring-body">
        <pre :class="`bp-mermaid bp-mermaid-${bp.id}`">{{ bp.mermaid }}</pre>
      </div>
    </details>
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import FlowLoom from './FlowLoom.vue'
import { RAIL_BY_ID } from '@/data/blueprints/rails'
import type { Blueprint } from '@/data/blueprints/types'

const props = defineProps<{ bp: Blueprint }>()
const { t } = useI18n()

const sectionEl = ref<HTMLElement | null>(null)
const loomRef = ref<InstanceType<typeof FlowLoom> | null>(null)

const activeAttack = ref(0)
const attackRunning = ref(false)
const attackDone = ref(false)
const attack = computed(() => props.bp.attacks[activeAttack.value])

function railName(id: string): string {
  return RAIL_BY_ID[id]?.name ?? id
}

let fallbackTimer: number | null = null
function clearFallback() {
  if (fallbackTimer) { window.clearTimeout(fallbackTimer); fallbackTimer = null }
}

function selectAttack(i: number) {
  activeAttack.value = i
  attackDone.value = false
  attackRunning.value = false
  clearFallback()
  loomRef.value?.resetToHappy()
}

function runAttack() {
  if (!attack.value) return
  attackRunning.value = true
  attackDone.value = false
  // The panel sits directly under the Loom, so at most a gentle nudge is
  // needed; 'nearest' never yanks the viewport away from the button.
  sectionEl.value?.querySelector('.bps-loom-wrap')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  loomRef.value?.runAttack(attack.value.script)
  // FlowLoom emits attack-finished; also arm a fallback so the result copy
  // can never be stranded behind a missed event. Cleared on every state
  // change: a stale timer from attack one must never fire into attack two.
  clearFallback()
  fallbackTimer = window.setTimeout(() => { if (attackRunning.value) onAttackFinished() }, 6000)
}
function onAttackFinished() {
  clearFallback()
  attackRunning.value = false
  attackDone.value = true
}
function resetAttack() {
  attackDone.value = false
  clearFallback()
  loomRef.value?.resetToHappy()
}

// Mermaid loads only when the disclosure is actually opened (strategy §9).
let wiringRendered = false
async function onWiringToggle(ev: Event) {
  const el = ev.target as HTMLDetailsElement
  if (!el.open || wiringRendered) return
  wiringRendered = true
  const { renderMermaidDiagrams } = await import('@/composables/docs/useMermaidRenderer')
  await renderMermaidDiagrams({
    selector: `.bp-mermaid-${props.bp.id}`,
    theme: 'blueprints',
    root: sectionEl.value,
  })
}
</script>

<script lang="ts">
export default { name: 'BlueprintSection' }
</script>

<style scoped>
.bps { padding: 3.2rem 0 2.6rem; border-top: 1px solid rgba(var(--flow-rgb, 0, 210, 210), 0.12); }

.bps-head { display: flex; gap: 1.3rem; align-items: flex-start; margin-bottom: 1.8rem; }
.bps-frontier { display: inline-block; margin-left: 0.6rem; padding: 0.08rem 0.42rem; font-size: 0.56rem; font-weight: 800; letter-spacing: 0.12em; color: #c4b5fd; border: 1px dashed rgba(196, 181, 253, 0.55); border-radius: 5px; vertical-align: 1px; }
.bps-frontier-note { margin: 0.35rem 0 0; font-size: 0.78rem; line-height: 1.6; color: var(--bp-dim, #94a3b8); max-width: 62ch; }
.bps-rank {
  font-family: var(--bp-mono); font-size: 3.4rem; font-weight: 800; line-height: 1;
  color: rgba(var(--flow-rgb), 0.22); letter-spacing: -0.03em; flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.bps-eyebrow { display: block; font-family: var(--bp-mono); font-size: 0.64rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: var(--bp-dim); margin-bottom: 0.35rem; }
.bps-name { margin: 0; font-size: 1.9rem; font-weight: 800; letter-spacing: 0.04em; color: var(--bp-ink); }
.bps-promise { margin: 0.4rem 0 0.6rem; font-size: 0.92rem; color: var(--bp-dim); line-height: 1.55; max-width: 620px; }
.bps-meta { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
.bps-ratio { font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; color: #10b981; border: 1px solid rgba(16, 185, 129, 0.35); background: rgba(16, 185, 129, 0.07); border-radius: 20px; padding: 0.18rem 0.55rem; letter-spacing: 0.04em; }
.bps-railchip { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; color: rgba(var(--flow-rgb), 0.9); border: 1px solid rgba(var(--flow-rgb), 0.28); background: rgba(var(--flow-rgb), 0.06); border-radius: 20px; padding: 0.16rem 0.5rem; cursor: help; }

.bps-cases { margin-bottom: 1.9rem; }
.bps-cases-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.6rem; }
.bps-case { border: 1px solid rgba(var(--flow-rgb), 0.16); border-left: 3px solid rgba(var(--flow-rgb), 0.55); border-radius: 10px; background: rgba(var(--flow-rgb), 0.03); padding: 0.7rem 0.85rem; }
.bps-case-role { display: block; font-family: var(--bp-mono); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.03em; color: var(--bp-ink); margin-bottom: 0.3rem; }
.bps-case-line { display: block; font-size: 0.71rem; color: var(--bp-dim); line-height: 1.55; }

.bps-block { margin-bottom: 1.7rem; }
.bps-label { display: block; font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.13em; color: rgba(var(--flow-rgb), 0.8); margin-bottom: 0.55rem; }
.bps-label--deny { color: #f59e0b; }

.bps-problem { margin: 0; font-size: 0.85rem; color: var(--bp-dim); line-height: 1.7; max-width: 760px; }
.bps-system-p { margin: 0 0 0.9rem; font-size: 0.92rem; color: var(--bp-ink-soft); line-height: 1.75; max-width: 780px; }
.bps-system-p:first-of-type::first-letter { color: rgb(var(--flow-rgb)); }

.bps-loom-wrap {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.02), rgba(255, 255, 255, 0) 60%), rgba(var(--flow-rgb), 0.028);
  border: 1px solid rgba(var(--flow-rgb), 0.16);
  border-radius: 13px; padding: 1.1rem 1.2rem 0.9rem;
}

.bps-tablewrap { overflow-x: auto; }
.bps-table { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
.bps-table th { text-align: left; font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--bp-faint); padding: 0.45rem 0.8rem 0.45rem 0; border-bottom: 1px solid rgba(var(--flow-rgb), 0.18); }
.bps-table td { padding: 0.55rem 0.8rem 0.55rem 0; border-bottom: 1px solid rgba(var(--flow-rgb), 0.07); color: var(--bp-dim); vertical-align: top; line-height: 1.5; }
.bps-mono { font-family: var(--bp-mono); font-size: 0.72rem; color: var(--bp-ink-soft); }
.bps-ceiling { color: var(--bp-ink-soft); }
.bps-prim { color: var(--bp-dim); }

.bps-badge { font-family: var(--bp-mono); font-size: 0.58rem; font-weight: 700; letter-spacing: 0.05em; border-radius: 5px; padding: 0.2rem 0.45rem; white-space: nowrap; text-decoration: none; }
.bps-badge[data-s="LIVE"] { color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); background: rgba(16, 185, 129, 0.07); }
.bps-badge[data-s="LIVE (gated)"] { color: rgba(var(--flow-rgb), 1); border: 1px solid rgba(var(--flow-rgb), 0.4); background: rgba(var(--flow-rgb), 0.07); }
.bps-badge[data-s="SHADOW"] { color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.06); }
.bps-badge[data-s="DESIGNED"] { color: #8b98a7; border: 1px solid rgba(139, 152, 167, 0.35); background: rgba(139, 152, 167, 0.06); }
a.bps-badge:hover { filter: brightness(1.25); }

.bps-attack {
  border: 1px solid rgba(245, 158, 11, 0.22); border-radius: 13px;
  background: rgba(245, 158, 11, 0.03); padding: 1.1rem 1.2rem;
}
.bps-attack-tabs { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.7rem; }
.bps-attack-tab { font-family: var(--bp-mono); font-size: 0.64rem; font-weight: 700; letter-spacing: 0.04em; color: var(--bp-dim); background: transparent; border: 1px solid rgba(245, 158, 11, 0.25); border-radius: 20px; padding: 0.3rem 0.75rem; cursor: pointer; }
.bps-attack-tab.is-on { color: #f59e0b; background: rgba(245, 158, 11, 0.09); border-color: rgba(245, 158, 11, 0.5); }
.bps-attack-text { margin: 0 0 0.85rem; font-size: 0.85rem; color: var(--bp-ink-soft); line-height: 1.65; max-width: 720px; }
.bps-attack-acts { display: flex; gap: 0.6rem; }
.bps-btn { font-family: var(--bp-mono); font-size: 0.68rem; font-weight: 800; letter-spacing: 0.09em; border-radius: 8px; padding: 0.55rem 1.05rem; cursor: pointer; transition: transform 0.1s ease, filter 0.2s ease; }
.bps-btn:active { transform: translateY(1px); }
.bps-btn--deny { color: #0a0a06; background: #f59e0b; border: 1px solid #f59e0b; }
.bps-btn--deny:disabled { opacity: 0.55; cursor: default; }
.bps-btn--deny:hover:not(:disabled) { filter: brightness(1.12); }
.bps-btn--ghost { color: var(--bp-dim); background: transparent; border: 1px solid rgba(var(--flow-rgb), 0.3); }
.bps-btn--ghost:hover { color: var(--bp-ink); }
.bps-attack-result { margin-top: 0.95rem; border-top: 1px solid rgba(245, 158, 11, 0.18); padding-top: 0.85rem; }
.bps-attack-result p { margin: 0 0 0.55rem; font-size: 0.8rem; color: var(--bp-dim); line-height: 1.65; max-width: 720px; }
.bps-attack-result strong { color: var(--bp-ink); font-weight: 700; }
.bps-fade-enter-active { transition: opacity 0.35s ease; }
.bps-fade-enter-from { opacity: 0; }

.bps-standup { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.7rem; }
.bps-standup-cell { border: 1px solid rgba(var(--flow-rgb), 0.14); border-radius: 11px; padding: 0.85rem 0.95rem; background: rgba(var(--flow-rgb), 0.025); }
.bps-standup-k { display: block; font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.11em; color: rgba(var(--flow-rgb), 0.85); margin-bottom: 0.4rem; }
.bps-standup-cell p { margin: 0; font-size: 0.74rem; color: var(--bp-dim); line-height: 1.6; }
.bps-legacy { display: grid; gap: 0.55rem; }
.bps-legacy-row { display: grid; grid-template-columns: minmax(0, 230px) 1fr; gap: 0.85rem; border: 1px solid rgba(var(--flow-rgb), 0.14); border-radius: 11px; padding: 0.7rem 0.95rem; background: rgba(var(--flow-rgb), 0.025); }
.bps-legacy-sys { font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: rgba(var(--flow-rgb), 0.85); padding-top: 0.15rem; }
.bps-legacy-row p { margin: 0; font-size: 0.74rem; color: var(--bp-dim); line-height: 1.6; }
.bps-legacy-note { margin: 0.8rem 0 0; font-size: 0.74rem; line-height: 1.65; color: var(--bp-dim); }
.bps-legacy-plan { border-left: 2px solid rgba(var(--flow-rgb), 0.45); padding-left: 0.8rem; }

.bps-shot img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; border-radius: 12px; border: 1px solid rgba(var(--flow-rgb), 0.18); display: block; }
.bps-shot figcaption { margin-top: 0.5rem; font-family: var(--bp-mono); font-size: 0.66rem; color: var(--bp-faint); line-height: 1.5; }

.bps-nonclaims ul { margin: 0; padding-left: 1.1rem; }
.bps-nonclaims li { font-size: 0.78rem; color: var(--bp-dim); line-height: 1.7; }
.bps-comprefs { display: flex; flex-wrap: wrap; align-items: center; gap: 0.45rem; margin-top: 0.7rem; }
.bps-comprefs-k { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--bp-faint); }
.bps-compref { font-family: var(--bp-mono); font-size: 0.64rem; font-weight: 700; color: rgba(var(--flow-rgb), 0.95); border: 1px solid rgba(var(--flow-rgb), 0.3); border-radius: 20px; padding: 0.22rem 0.6rem; text-decoration: none; }
.bps-compref:hover { background: rgba(var(--flow-rgb), 0.08); }

.bps-riskref { margin-top: 0.6rem; font-size: 0.74rem; color: var(--bp-dim); }
.bps-riskref-link { font-family: var(--bp-mono); font-weight: 800; color: #f59e0b; text-decoration: none; border-bottom: 1px dotted rgba(245, 158, 11, 0.5); }
.bps-riskref-link:hover { border-bottom-style: solid; }

.bps-wiring { border: 1px solid rgba(var(--flow-rgb), 0.14); border-radius: 11px; background: rgba(0, 0, 0, 0.25); }
.bps-wiring summary { cursor: pointer; font-family: var(--bp-mono); font-size: 0.68rem; font-weight: 700; letter-spacing: 0.07em; color: var(--bp-dim); padding: 0.7rem 1rem; user-select: none; }
.bps-wiring summary:hover { color: var(--bp-ink); }
.bps-wiring-body { padding: 0.4rem 1rem 1rem; overflow-x: auto; }
.bps-wiring-body pre { margin: 0; font-family: var(--bp-mono); font-size: 0.68rem; color: var(--bp-dim); line-height: 1.6; }
.bps-wiring-body :deep(svg) { max-width: 100%; height: auto; }

@media (max-width: 820px) {
  .bps-standup { grid-template-columns: 1fr; }
  .bps-legacy-row { grid-template-columns: 1fr; gap: 0.3rem; }
  .bps-rank { font-size: 2.2rem; }
  .bps-name { font-size: 1.4rem; }
}
</style>
