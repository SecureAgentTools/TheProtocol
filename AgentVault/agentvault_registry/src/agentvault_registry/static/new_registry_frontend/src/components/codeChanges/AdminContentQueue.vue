<!--
  V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane's content changes in the platform's Contributions inbox (admin_platform): every organization's content changes in one queue, newest first,
  filtered by state and kind, our checker's record and the applied before and after on each, and the platform's undo of an applied one (the registry refuses it if the content changed since).
-->
<template>
  <section class="acq" data-testid="acq-root" :aria-busy="loading ? 'true' : 'false'">
    <div class="acq-bar">
      <h2 class="acq-h">{{ tp('contentChanges.admin.title', 'Content changes ({n})', { n: items.length }) }}</h2>
      <div class="acq-filters" role="group" :aria-label="t('contentChanges.admin.filters', 'Filter the content changes')">
        <label><span>{{ t('contributions.admin.fState', 'State') }}</span>
          <select v-model="state" data-testid="acq-f-state" @change="load"><option value="">{{ t('contributions.admin.all', 'All') }}</option>
            <option v-for="s in CONTENT_STATES" :key="s" :value="s">{{ stateWord(s, tr) }}</option></select></label>
        <label><span>{{ t('contentChanges.admin.fKind', 'Kind') }}</span>
          <select v-model="kind" data-testid="acq-f-kind" @change="load"><option value="">{{ t('contributions.admin.all', 'All') }}</option>
            <option v-for="k in CONTENT_KINDS" :key="k" :value="k">{{ kindWord(k, tr) }}</option></select></label>
      </div>
    </div>
    <p v-if="loading" class="acq-note" role="status">{{ t('contentChanges.loading', 'Reading the content changes') }}</p>
    <div v-else-if="error" class="acq-error" role="alert" data-testid="acq-error"><p>{{ error }}</p><button type="button" class="acq-btn" @click="load">{{ t('contributions.retry', 'Try again') }}</button></div>
    <p v-else-if="!items.length" class="acq-note" data-testid="acq-none">{{ t('contentChanges.admin.none', 'No organization has proposed a content change on this registry yet.') }}</p>
    <ul v-else class="acq-list" data-testid="acq-list">
      <li v-for="c in items" :key="c.id" class="acq-row" :data-testid="`acq-${c.id}`">
        <p class="acq-top"><span class="acq-tag">{{ kindWord(String(c.kind), tr) }}</span> <span class="acq-tag" :data-state="c.state">{{ stateWord(String(c.state), tr) }}</span>
          <code class="acq-line">{{ c.code_distribution?.release_name }}</code></p>
        <p class="acq-title">{{ c.title }}</p>
        <p class="acq-small">{{ contentSummary(c, tr) }}</p>
        <p v-if="c.kind === 'compliance_pack'" class="acq-small" data-testid="acq-pack-note">{{ t('contentChanges.packNote', 'A pack records the organization’s own policy values: stored, voted on and carried in the signed report. No rail enforces it in this release.') }}</p>
        <p class="acq-small" data-testid="acq-checker">{{ checkerLine(c, tr) }}</p>
        <p v-if="ballotLine(c, tr)" class="acq-small">{{ ballotLine(c, tr) }}</p>
        <p v-if="diff(c)" class="acq-small" data-testid="acq-diff"><span class="acq-label">{{ t('contentChanges.before', 'Before') }}</span> <code>{{ diff(c)!.before || '-' }}</code>
          <span class="acq-label">{{ t('contentChanges.after', 'After') }}</span> <code>{{ diff(c)!.after || '-' }}</code></p>
        <button v-if="c.can_undo" type="button" class="acq-btn" :disabled="acting === c.id" data-testid="acq-undo" @click="undo(c)">{{ t('contentChanges.undo', 'Undo this change') }}</button>
        <p v-if="refusal[c.id]" class="acq-refusal" role="alert">{{ refusal[c.id] }}</p>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { refusalWords } from '@/services/api/codeChanges'
import { CONTENT_KINDS, adminListContentChanges, undoContentChange, type ContentRecord } from '@/services/api/contentChanges'
import { useTr } from '@/services/codeChanges/tr'
import { CONTENT_STATES, appliedDiff, ballotLine, checkerLine, contentSummary, kindWord, stateWord } from '@/services/contentChanges/words'

const { t, tp } = useI18n()
const tr = useTr()
const items = ref<ContentRecord[]>([])
const loading = ref(false)
const error = ref('')
const state = ref('')
const kind = ref('')
const acting = ref('')
const refusal = reactive<Record<string, string>>({})
const diff = (c: ContentRecord) => appliedDiff(c)

async function load() {
  loading.value = true; error.value = ''
  try { items.value = await adminListContentChanges({ ...(state.value ? { state: state.value } : {}), ...(kind.value ? { kind: kind.value } : {}) }) } catch (e) { items.value = []; error.value = refusalWords(e, t('contentChanges.error', 'The content changes could not be read; try again.')) } finally { loading.value = false }
}
async function undo(c: ContentRecord) {
  acting.value = String(c.id); refusal[c.id] = ''
  try { const rec = await undoContentChange(String(c.id), ''); const i = items.value.findIndex((x) => x.id === rec.id); if (i >= 0) items.value[i] = rec } catch (e) { refusal[c.id] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = '' }
}
onMounted(load)
</script>

<style scoped>
.acq { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace; display: grid; gap: .7rem; }
.acq-bar { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: .8rem; }
.acq-h { margin: 0; font-size: 1.05rem; font-weight: 500; color: var(--bright); }
.acq-filters { display: flex; flex-wrap: wrap; gap: .6rem; }
.acq-filters label { display: grid; gap: .25rem; font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.acq-filters select { min-height: 36px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .25); background: rgba(0, 0, 0, .3); color: var(--bright); font: inherit; font-size: .82rem; padding: 0 .5rem; }
.acq-note { margin: 0; color: var(--muted); font-size: .86rem; }
.acq-error { border: 1px solid rgba(248, 113, 113, .35); border-radius: 12px; padding: .8rem 1rem; display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; color: #fca5a5; }
.acq-error p { margin: 0; }
.acq-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
.acq-row { display: grid; gap: .35rem; padding: .8rem .95rem; background: rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; min-width: 0; }
.acq-top { margin: 0; display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
.acq-tag { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 8px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.acq-tag[data-state='applied'] { color: #34d399; border-color: rgba(16, 185, 129, .4); }
.acq-tag[data-state='failed'], .acq-tag[data-state='apply_failed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.acq-line { font: .72rem var(--mono); color: var(--cyan); overflow-wrap: anywhere; }
.acq-title { margin: 0; font-size: .92rem; font-weight: 500; color: var(--bright); overflow-wrap: anywhere; }
.acq-small { margin: 0; font-size: .78rem; line-height: 1.5; color: #aab4c0; overflow-wrap: anywhere; }
.acq-small code { font: .74rem var(--mono); color: var(--cyan); }
.acq-label { font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 0 .35rem 0 .6rem; }
.acq-refusal { margin: 0; font-size: .8rem; color: #fca5a5; overflow-wrap: anywhere; }
.acq-btn { justify-self: start; display: inline-flex; align-items: center; min-height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .84rem; cursor: pointer; }
.acq-btn:disabled { opacity: .5; cursor: not-allowed; }
.acq-btn:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
</style>
