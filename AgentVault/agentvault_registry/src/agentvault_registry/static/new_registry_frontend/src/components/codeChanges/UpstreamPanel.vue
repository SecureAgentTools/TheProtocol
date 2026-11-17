<!--
  V0667 D4 (order gwo_b12f07e4c5adaa1f5bf4d115): the upstream panel of a change's page. On a change merged in an organization's release line: "Propose upstream" for the line's deciders,
  then the proposal and its state, then "upstream since". On the main-line change that carries a line's change upstream: where it came from (the line, its change, the ballot and
  result, the reviews, the checker's record), with a way back. Nothing on any other change. The registry decides who may, the paths and once.
-->
<template>
  <section v-if="kind" class="ups" data-testid="up-root" :data-kind="kind">
    <template v-if="kind === 'line'">
      <h2>{{ t('upstream.title', 'Upstream') }}</h2>
      <p v-if="status.kind !== 'none'" class="ups-status" :data-kind="status.kind" data-testid="up-status">
        {{ status.text }}
        <RouterLink v-if="status.changeId" :to="{ name: 'code-change', params: { id: status.changeId } }" class="ups-link" data-testid="up-link">{{ t('upstream.open', 'Open it') }}</RouterLink>
      </p>
      <template v-if="canPropose">
        <p class="ups-note" data-testid="up-explain">{{ t('upstream.explain', 'Propose this merged change to the main code, with its history: it becomes an ordinary code change there, the checker reads its commit again, and the frame\'s members decide it. This line keeps its copy.') }}</p>
        <button type="button" class="ups-btn" :disabled="busy" data-testid="up-propose" @click="emit('propose')">{{ t('upstream.propose', 'Propose upstream') }}</button>
      </template>
      <p v-if="error" class="ups-error" role="alert" data-testid="up-error">{{ error }}</p>
    </template>
    <template v-else>
      <h2>{{ t('upstream.carriedTitle', 'Proposed from a release line') }}</h2>
      <dl class="ups-prov" data-testid="up-provenance">
        <template v-for="f in facts" :key="f.key">
          <dt>{{ f.label }}</dt>
          <dd :data-testid="`up-prov-${f.key}`">{{ f.text }}</dd>
        </template>
      </dl>
      <RouterLink :to="{ name: 'code-change', params: { id: String(rec.upstream_of) } }" class="ups-link" data-testid="up-back">{{ t('upstream.back', 'The change in the release line') }}</RouterLink>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useTr } from '@/services/codeChanges/tr'
import { canProposeUpstream, lineStatus, provenanceFacts, upstreamKind } from '@/services/codeChanges/upstream'

const props = defineProps<{ rec: Record<string, any>; signedIn: boolean; readOnly: boolean; busy: boolean; error: string }>()
const emit = defineEmits<{ (e: 'propose'): void }>()
const { t } = useI18n()
const tr = useTr()
const kind = computed(() => upstreamKind(props.rec))
const canPropose = computed(() => !props.readOnly && canProposeUpstream(props.rec, props.signedIn))
const status = computed(() => lineStatus(props.rec, tr))
const facts = computed(() => provenanceFacts(props.rec, tr))
</script>

<style scoped>
.ups { border: 1px solid var(--nc-border, #2b3340); border-radius: 8px; padding: 14px 16px; margin-bottom: 14px; background: var(--nc-surface, #12171f); }
.ups h2 { font-size: 1rem; margin: 0 0 8px; }
.ups-status, .ups-note { margin: 0 0 8px; font-size: .9rem; color: var(--nc-text-secondary, #b4bfcc); }
.ups-status[data-kind='landed'] { color: var(--nc-success, #7ee0a1); }
.ups-status[data-kind='ended'] { color: var(--nc-warning, #f0c674); }
.ups-btn { background: var(--nc-primary, #3b82f6); color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; font-size: .9rem; cursor: pointer; }
.ups-btn:disabled { opacity: .6; cursor: default; }
.ups-error { color: var(--nc-danger, #ff8a80); margin: 8px 0 0; font-size: .9rem; }
.ups-link { color: var(--nc-primary, #7fb2ff); font-size: .9rem; margin-left: 6px; }
.ups-prov { display: grid; grid-template-columns: max-content 1fr; gap: 4px 14px; margin: 0 0 10px; font-size: .9rem; }
.ups-prov dt { color: var(--nc-text-secondary, #b4bfcc); }
.ups-prov dd { margin: 0; overflow-wrap: anywhere; }
</style>
