<!-- V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the seven steps a code change goes through. `compact` draws only the line and the titles (a change's own page);
     the default draws each step with who acts and what happens (the page that explains the way a change goes). On a phone the steps stack. -->
<template>
  <ol class="cs" :class="{ compact, explain }" data-testid="cs">
    <li v-for="(s, i) in steps" :key="s.key" class="cs-step" :class="s.state" :data-testid="`cs-${s.key}`" :data-state="s.state" :aria-current="s.state === 'current' ? 'step' : undefined">
      <span class="cs-dot" aria-hidden="true">
        <Icon v-if="s.state === 'done'" name="mdi:check-circle" />
        <Icon v-else-if="s.state === 'stopped'" name="mdi:alert-circle-outline" />
        <template v-else>{{ i + 1 }}</template>
      </span>
      <span class="cs-text">
        <b class="cs-title">{{ s.title }}</b>
        <span class="cs-who">{{ s.who }}</span>
        <span v-if="!compact && body(s.key)" class="cs-body">{{ body(s.key) }}</span>
        <span v-if="s.note" class="cs-note" :data-testid="`cs-note-${s.key}`">{{ s.note }}</span>
        <span v-if="s.state === 'stopped'" class="cs-sr">{{ t('codeChanges.step.stopped', 'It stopped here.') }}</span>
        <span v-else-if="s.state === 'current'" class="cs-sr">{{ t('codeChanges.step.current', 'It is here now.') }}</span>
      </span>
    </li>
  </ol>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { stepWords, type StepView } from '@/services/codeChanges/flow'
import { useTr } from '@/services/codeChanges/tr'

const props = withDefaults(defineProps<{ steps: StepView[]; compact?: boolean; explain?: boolean }>(), { compact: false, explain: false })
const { t } = useI18n()
const bodies = stepWords(useTr())
const body = (k: string) => (props.compact ? '' : bodies.find((b) => b.key === k)?.body || '')
</script>

<style scoped>
.cs { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: .5rem; counter-reset: s; }
.cs-step { position: relative; display: grid; grid-template-rows: auto 1fr; gap: .55rem; padding-top: .1rem; min-width: 0; }
.cs-step::before { content: ''; position: absolute; top: 14px; left: calc(28px + .3rem); right: calc(-.5rem + .3rem); height: 1px; background: rgba(var(--cyan-rgb), .22); }
.cs-step:last-child::before { display: none; }
.cs-step.done::before { background: var(--cyan); }
.cs-dot { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; font: 600 .74rem 'IBM Plex Mono', monospace; color: #8b97a6; border: 1px solid rgba(var(--cyan-rgb), .28); background: #070d13; z-index: 1; }
.cs-dot :deep(svg) { width: 18px; height: 18px; }
.cs-step.done .cs-dot { color: var(--cyan); border-color: var(--cyan); }
.cs-step.current .cs-dot { color: #04141a; background: var(--cyan); border-color: var(--cyan); box-shadow: 0 0 0 4px rgba(var(--cyan-rgb), .16); }
.cs-step.stopped .cs-dot { color: #fca5a5; border-color: rgba(248, 113, 113, .6); }
.cs-text { display: grid; gap: .2rem; align-content: start; min-width: 0; }
.cs-title { font-size: .84rem; font-weight: 600; color: #dbe4ee; }
.cs-step.todo .cs-title { color: #8b97a6; font-weight: 500; }
.explain .cs-step.todo .cs-title { color: #dbe4ee; font-weight: 600; }
.explain .cs-step.todo .cs-dot { color: var(--cyan); }
.cs-who { font: 600 .66rem 'IBM Plex Mono', monospace; letter-spacing: .05em; text-transform: uppercase; color: #8b97a6; }
.cs-body { font-size: .76rem; line-height: 1.5; color: #aab4c0; }
.cs-note { font-size: .76rem; line-height: 1.45; color: var(--cyan); overflow-wrap: anywhere; }
.cs-step.stopped .cs-note { color: #fca5a5; }
.cs-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.compact .cs-who { display: none; }
@media (max-width: 900px) {
  .cs { grid-template-columns: 1fr; gap: 0; }
  .cs-step { grid-template-columns: 28px minmax(0, 1fr); grid-template-rows: none; gap: .8rem; padding-bottom: 1rem; }
  .cs-step::before { top: 30px; bottom: 0; left: 13px; right: auto; width: 1px; height: auto; }
  .cs-step:last-child { padding-bottom: 0; }
}
</style>
