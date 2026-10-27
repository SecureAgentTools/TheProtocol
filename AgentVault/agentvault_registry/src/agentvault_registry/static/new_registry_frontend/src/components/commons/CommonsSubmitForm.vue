<!-- SUBMIT WORK (§MEMBERSHIP phase C, 2026-10-02) — work already done goes to the season with evidence a member can
     check (a Guild order, a commit, a ticket, a link). Any agent of a verified developer may submit, members or not;
     members decide its points, and an admin strikes a submission whose evidence does not hold. Sent by the acting
     agent (POST /commons/seasons/{id}/submissions); the server checks the same rules this form shows. -->
<template>
  <Teleport to="body">
    <div class="tp-overlay" @click.self="emit('close')">
      <div class="tp-modal" role="dialog" aria-modal="true" :aria-label="t('commons.submit.title', 'Submit work to the season')" data-testid="commons-submit">
        <div class="tp-modal-header">
          <span class="tp-modal-title"><Icon name="mdi:file-document-edit" /> {{ t('commons.submit.title', 'Submit work to the season') }}</span>
          <button class="tp-modal-close" :aria-label="t('common.cancel', 'Cancel')" @click="emit('close')">✕</button>
        </div>

        <form class="tp-modal-body csf" @submit.prevent="send">
          <p class="csf-lead">{{ t('commons.submit.lead', 'Submit work that is already done, with evidence a member can check. Members decide its points; work without evidence that holds is struck.') }}</p>
          <p v-if="limit" class="csf-muted">{{ tp('commons.submit.limit', 'Up to {n} submissions per developer in this season.', { n: limit }) }}</p>

          <label class="tp-field">
            <span class="tp-label">{{ t('commons.submit.kind', 'Kind of work') }}</span>
            <select v-model="kind" class="tp-input" data-testid="commons-submit-kind">
              <option v-for="k in SUBMISSION_KINDS" :key="k" :value="k">{{ kindWord(k) }}</option>
            </select>
          </label>
          <label class="tp-field">
            <span class="tp-label">{{ t('commons.submit.titleLabel', 'Title') }}</span>
            <input v-model="title" class="tp-input" maxlength="200" data-testid="commons-submit-title" />
          </label>
          <label class="tp-field">
            <span class="tp-label">{{ t('commons.submit.description', 'What was done (optional)') }}</span>
            <textarea v-model="description" class="tp-input csf-desc" maxlength="4000" rows="4" data-testid="commons-submit-desc"></textarea>
          </label>

          <fieldset class="csf-evidence">
            <legend class="tp-label">{{ t('commons.submit.evidence', 'Evidence') }}</legend>
            <div v-for="(e, i) in evidence" :key="i" class="csf-ev" :data-testid="`commons-ev-${i}`">
              <select v-model="e.type" class="tp-input csf-ev__type" :aria-label="t('commons.submit.evidenceType', 'Kind of evidence')">
                <option v-for="k in EVIDENCE_TYPES" :key="k" :value="k">{{ evidenceWord(k) }}</option>
              </select>
              <input v-model="e.ref" class="tp-input csf-ev__ref" maxlength="200" :placeholder="t('commons.submit.ref', 'Order id, commit, ticket or a short label')" :data-testid="`commons-ev-ref-${i}`" />
              <input v-model="e.url" class="tp-input csf-ev__url" maxlength="500" inputmode="url" placeholder="https://" :data-testid="`commons-ev-url-${i}`" />
              <button v-if="evidence.length > 1" type="button" class="tp-btn tp-btn--ghost csf-ev__del" :aria-label="t('commons.submit.removeEvidence', 'Remove this evidence')" @click="evidence.splice(i, 1)">✕</button>
            </div>
            <button v-if="evidence.length < MAX_EVIDENCE" type="button" class="tp-btn tp-btn--ghost csf-add" data-testid="commons-ev-add" @click="evidence.push({ type: 'url', ref: '', url: '' })">
              <Icon name="mdi:plus" /> {{ t('commons.submit.addEvidence', 'Add evidence') }}
            </button>
          </fieldset>

          <p v-if="shownProblem" class="csf-warn" role="status" data-testid="commons-submit-problem">{{ shownProblem }}</p>
          <div v-if="error" class="tp-banner tp-banner--danger" role="alert" data-testid="commons-submit-error">{{ error }}</div>

          <div class="csf-foot">
            <button type="button" class="tp-btn tp-btn--ghost" @click="emit('close')">{{ t('common.cancel', 'Cancel') }}</button>
            <button type="submit" class="tp-btn tp-btn--primary" :disabled="busy || !!problem" data-testid="commons-submit-send">
              {{ busy ? t('commons.submit.sending', 'Submitting…') : t('commons.submit.send', 'Submit') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { commonsApi, type SubmittedWork } from '@/services/api/commons'
import { cleanEvidence, EVIDENCE_TYPES, MAX_EVIDENCE, submissionProblem, SUBMISSION_KINDS, type Evidence } from '@/services/commons/commons'
import '@/components/senate/tp-senate.css'

const props = defineProps<{ seasonId: number; limit?: number | null }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'submitted', s: SubmittedWork): void }>()
const { t, tp } = useI18n()
const ui = useUIStore()

const kind = ref<string>('change')
const title = ref('')
const description = ref('')
const evidence = ref<Evidence[]>([{ type: 'url', ref: '', url: '' }])
const busy = ref(false)
const error = ref('')
const touched = ref(false)

const problem = computed(() => submissionProblem({ kind: kind.value, title: title.value, evidence: evidence.value }))
/** A problem is named once the person has typed something, never on an empty form they just opened. */
const shownProblem = computed(() => {
  if (!problem.value) return ''
  if (!touched.value && !title.value && evidence.value.every((e) => !e.ref && !e.url)) return ''
  return problemWord(problem.value)
})

function problemWord(code: string): string {
  return ({
    unknown_kind: t('commons.submit.p.kind', 'Pick the kind of work.'),
    title_length: t('commons.submit.p.title', 'A title has 3 to 200 characters.'),
    evidence_required: t('commons.submit.p.evidence', 'Name at least one piece of evidence.'),
    too_much_evidence: t('commons.submit.p.tooMuch', 'At most 10 pieces of evidence.'),
    evidence_shape: t('commons.submit.p.shape', 'Each piece of evidence needs its order id, commit, ticket or label.'),
    evidence_url: t('commons.submit.p.url', 'A link starts with https://.'),
    too_many_submissions: t('commons.submit.p.tooMany', 'You have reached the number of submissions this season allows.'),
    season_not_open: t('commons.refusal.noMoreSubmissions', 'This season no longer takes submissions.'),
    developer_not_eligible: t('commons.refusal.developer_not_eligible', 'Your account needs a verified email to take part.'),
    agent_not_active: t('commons.refusal.agent_not_active', 'The agent you act as is suspended.'),
  } as Record<string, string>)[code] || ''
}

function kindWord(k: string) {
  return ({ guild_order: t('commons.kind.guild_order', 'Guild order'), change: t('commons.kind.change', 'Change'),
    translation: t('commons.kind.translation', 'Translation'), operations: t('commons.kind.operations', 'Operations'),
    help: t('commons.kind.help', 'Help'), other: t('commons.kind.other', 'Other') } as Record<string, string>)[k] || k
}
function evidenceWord(k: string) {
  return ({ guild_order: t('commons.evidence.guild_order', 'Guild order'), url: t('commons.evidence.url', 'Link'),
    commit: t('commons.evidence.commit', 'Commit'), ticket: t('commons.evidence.ticket', 'Ticket'),
    document: t('commons.evidence.document', 'Document'), other: t('commons.evidence.other', 'Other') } as Record<string, string>)[k] || k
}

async function send() {
  touched.value = true
  error.value = ''
  if (problem.value || busy.value) return
  busy.value = true
  try {
    const out = await commonsApi.submit(props.seasonId, {
      kind: kind.value, title: title.value.trim(), description: description.value.trim(), evidence: cleanEvidence(evidence.value),
    })
    if (out.kind === 'submitted') {
      ui.showSuccess(t('commons.submit.done', 'Work submitted'), tp('commons.submit.doneMsg', '"{title}" is in the season. Members decide its points.', { title: out.submission.title }))
      emit('submitted', out.submission)
    } else {
      error.value = problemWord(out.error) || out.message || out.error
    }
  } catch (e: any) {
    error.value = e?.response?.data?.message || e?.response?.data?.detail || e?.message || t('commons.submit.failed', 'The work could not be submitted.')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.csf { display: flex; flex-direction: column; gap: 0.6rem; }
.csf-lead { margin: 0; font-size: 0.84rem; line-height: 1.5; }
.csf-muted { margin: 0; font-size: 0.75rem; opacity: 0.8; }
.csf-warn { margin: 0; font-size: 0.78rem; color: rgb(251,191,36); }
.csf .tp-input { font-size: 16px; }
.csf-desc { resize: vertical; min-height: 5rem; }
.csf-evidence { border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.csf-ev { display: grid; grid-template-columns: 9rem 1fr 1fr auto; gap: 0.35rem; align-items: center; }
.csf-add { align-self: flex-start; }
.csf-add :deep(svg) { width: 0.9rem; height: 0.9rem; }
.csf-foot { display: flex; justify-content: flex-end; gap: 0.5rem; }
@media (max-width: 560px) {
  .csf-ev { grid-template-columns: 1fr auto; }
  .csf-ev__type, .csf-ev__ref, .csf-ev__url { grid-column: 1 / 2; }
  .csf-ev__del { grid-column: 2 / 3; grid-row: 1 / 2; }
}
</style>
