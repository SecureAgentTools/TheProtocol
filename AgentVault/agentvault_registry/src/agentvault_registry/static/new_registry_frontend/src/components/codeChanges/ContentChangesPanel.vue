<!--
  V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane beside a release line's code changes, in the Contributions area. An organization's own CONTENT (a migration kit, a
  proxy spec, a policy value, a console text, its branding) changed after the line's ballot and our checker, applied to its own space with the before and after shown, and undone in one
  step by the deciders. The registry decides every step again (services/content_changes); this panel words its record, offers the vote and the undo, and shows its refusals.
-->
<template>
  <section class="cnt" data-testid="cnt-root" :aria-busy="loading ? 'true' : 'false'">
    <div class="cnt-bar">
      <h3 class="cnt-h">{{ t('contentChanges.title', 'Content changes') }}</h3>
      <RouterLink v-if="canPropose && !paused" :to="{ name: 'content-changes-new', query: { line: lineSlug } }" class="cnt-btn primary" data-testid="cnt-propose">{{ t('contentChanges.propose', 'Propose a content change') }}</RouterLink>
    </div>
    <p class="cnt-note">{{ t('contentChanges.lede', 'The organization’s own content, changed in hours and not in a release: our checker reads it first, the line’s deciders vote, and it is applied to the organization’s space with one step to undo it. Never code, never anything global.') }}</p>
    <p v-if="loading" class="cnt-note" role="status">{{ t('contentChanges.loading', 'Reading the content changes') }}</p>
    <div v-else-if="error" class="cnt-error" role="alert" data-testid="cnt-error"><p>{{ error }}</p><button type="button" class="cnt-btn" @click="load">{{ t('contributions.retry', 'Try again') }}</button></div>
    <p v-else-if="!items.length" class="cnt-note" data-testid="cnt-none">{{ t('contentChanges.none', 'No content change has been proposed to this line yet.') }}</p>
    <ul v-else class="cnt-list" data-testid="cnt-list">
      <li v-for="c in items" :key="c.id" class="cnt-card" :data-testid="`cnt-${c.id}`">
        <p class="cnt-top"><span class="cnt-tag">{{ kindWord(String(c.kind), tr) }}</span> <span class="cnt-tag" :data-state="c.state">{{ stateWord(String(c.state), tr) }}</span></p>
        <p class="cnt-title">{{ c.title }}</p>
        <p class="cnt-small" data-testid="cnt-summary">{{ contentSummary(c, tr) }}</p>
        <p v-if="c.kind === 'compliance_pack'" class="cnt-small" data-testid="cnt-pack-note">{{ t('contentChanges.packNote', 'A pack records the organization’s own policy values: stored, voted on and carried in the signed report. No rail enforces it in this release.') }}</p>
        <p class="cnt-small" data-testid="cnt-checker">{{ checkerLine(c, tr) }}</p>
        <p v-if="ballotLine(c, tr)" class="cnt-small" data-testid="cnt-ballot">{{ ballotLine(c, tr) }}</p>
        <div v-if="diff(c)" class="cnt-diff" data-testid="cnt-diff">
          <p class="cnt-small"><span class="cnt-label">{{ t('contentChanges.before', 'Before') }}</span> <code>{{ diff(c)!.before || '-' }}</code></p>
          <p class="cnt-small"><span class="cnt-label">{{ t('contentChanges.after', 'After') }}</span> <code>{{ diff(c)!.after || '-' }}</code></p>
        </div>
        <p v-if="c.apply_error" class="cnt-refusal" role="alert">{{ c.apply_error }}</p>

        <div v-if="c.ballot?.can_vote" class="cnt-act" data-testid="cnt-vote">
          <template v-if="confirming?.id === c.id && confirming?.kind === 'vote'">
            <p class="cnt-small">{{ confirming?.vote ? t('contentChanges.confirmFor', 'Vote for this change? A vote is never changed.') : t('contentChanges.confirmAgainst', 'Vote against this change? A vote is never changed.') }}</p>
            <div class="cnt-row">
              <button type="button" class="cnt-btn primary" :disabled="acting" data-testid="cnt-vote-confirm" @click="vote(c, !!confirming?.vote)">{{ t('contentChanges.cast', 'Cast the vote') }}</button>
              <button type="button" class="cnt-btn" :disabled="acting" @click="confirming = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
            </div>
          </template>
          <p v-else-if="!agentDid" class="cnt-small" data-testid="cnt-vote-agent">{{ t('contributions.vote.needAgent', 'Choose one of your agents first: the vote goes through an agent, as on the main line.') }}</p>
          <div v-else class="cnt-row">
            <button type="button" class="cnt-btn" data-testid="cnt-vote-for" @click="confirming = { id: c.id, kind: 'vote', vote: true }">{{ t('contributions.vote.for', 'Vote for') }}</button>
            <button type="button" class="cnt-btn" data-testid="cnt-vote-against" @click="confirming = { id: c.id, kind: 'vote', vote: false }">{{ t('contributions.vote.against', 'Vote against') }}</button>
          </div>
        </div>
        <p v-else-if="c.ballot?.my_vote" class="cnt-small cnt-ok" data-testid="cnt-voted">{{ t('contentChanges.voted', 'Your vote is in. A vote is never changed.') }}</p>

        <div v-if="c.can_undo" class="cnt-act" data-testid="cnt-undo-box">
          <template v-if="confirming?.id === c.id && confirming?.kind === 'undo'">
            <p class="cnt-small">{{ t('contentChanges.undoConfirm', 'Put back exactly what this change replaced? It is refused if something else changed the content since.') }}</p>
            <div class="cnt-row">
              <button type="button" class="cnt-btn danger" :disabled="acting" data-testid="cnt-undo-confirm" @click="undo(c)">{{ t('contentChanges.undoNow', 'Undo it') }}</button>
              <button type="button" class="cnt-btn" :disabled="acting" @click="confirming = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
            </div>
          </template>
          <button v-else type="button" class="cnt-btn" data-testid="cnt-undo" @click="confirming = { id: c.id, kind: 'undo' }">{{ t('contentChanges.undo', 'Undo this change') }}</button>
        </div>
        <button v-if="c.state === 'balloting' && me !== null && c.proposer_developer_id === me" type="button" class="cnt-btn" :disabled="acting" data-testid="cnt-withdraw" @click="withdraw(c)">{{ t('contentChanges.withdraw', 'Withdraw it') }}</button>
        <button type="button" class="cnt-btn" :disabled="acting" data-testid="cnt-record" @click="record(c)">{{ t('contentChanges.record', 'Download the signed record') }}</button>
        <p v-if="refusal[c.id]" class="cnt-refusal" role="alert" :data-testid="`cnt-refusal-${c.id}`">{{ refusal[c.id] }}</p>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { refusalWords } from '@/services/api/codeChanges'
import { getRecord } from '@/services/api/distributionReports'
import { downloadSigned } from '@/services/contentChanges/download'
import { listContentChanges, undoContentChange, voteContentChange, withdrawContentChange, type ContentRecord } from '@/services/api/contentChanges'
import { useTr } from '@/services/codeChanges/tr'
import { appliedDiff, ballotLine, checkerLine, contentSummary, kindWord, stateWord } from '@/services/contentChanges/words'

const props = defineProps<{ lineSlug: string; me: number | null; agentDid: string; canPropose: boolean; paused: boolean }>()
const { t } = useI18n()
const tr = useTr()

const items = ref<ContentRecord[]>([])
const loading = ref(false)
const error = ref('')
const acting = ref(false)
const refusal = reactive<Record<string, string>>({})
const confirming = ref<{ id: string; kind: 'vote' | 'undo'; vote?: boolean } | null>(null)

const diff = (c: ContentRecord) => appliedDiff(c)

async function load() {
  loading.value = true; error.value = ''
  try { items.value = await listContentChanges({ code_distribution: props.lineSlug }) } catch (e) { items.value = []; error.value = refusalWords(e, t('contentChanges.error', 'The content changes could not be read; try again.')) } finally { loading.value = false }
}
function replace(rec: ContentRecord) {
  const i = items.value.findIndex((x) => x.id === rec.id)
  if (i >= 0) items.value[i] = rec
}
async function run(c: ContentRecord, step: () => Promise<ContentRecord>) {
  acting.value = true; refusal[c.id] = ''
  try { replace(await step()); confirming.value = null } catch (e) { refusal[c.id] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = false }
}
async function record(c: ContentRecord) {
  acting.value = true; refusal[c.id] = ''
  try { downloadSigned(await getRecord(props.lineSlug, String(c.id))) } catch (e) { refusal[c.id] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = false }
}
const vote = (c: ContentRecord, v: boolean) => run(c, () => voteContentChange(String(c.id), v))
const undo = (c: ContentRecord) => run(c, () => undoContentChange(String(c.id), ''))
const withdraw = (c: ContentRecord) => run(c, () => withdrawContentChange(String(c.id), ''))

onMounted(load)
watch(() => props.lineSlug, load)
</script>

<style scoped>
.cnt { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace; display: grid; gap: .7rem; }
.cnt-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .8rem; }
.cnt-h { margin: 0; font-size: 1rem; font-weight: 500; color: var(--bright); }
.cnt-note { margin: 0; color: var(--muted); font-size: .86rem; line-height: 1.55; max-width: 52rem; }
.cnt-error { border: 1px solid rgba(248, 113, 113, .35); border-radius: 12px; padding: .8rem 1rem; display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; color: #fca5a5; }
.cnt-error p { margin: 0; }
.cnt-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); gap: .8rem; align-items: start; }
.cnt-card { display: grid; gap: .45rem; padding: .85rem .95rem; background: rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; min-width: 0; }
.cnt-top { margin: 0; display: flex; flex-wrap: wrap; gap: .4rem; }
.cnt-tag { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 8px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.cnt-tag[data-state='applied'] { color: #34d399; border-color: rgba(16, 185, 129, .4); }
.cnt-tag[data-state='failed'], .cnt-tag[data-state='apply_failed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.cnt-tag[data-state='undone'], .cnt-tag[data-state='withdrawn'] { color: var(--muted); border-color: rgba(255, 255, 255, .15); }
.cnt-title { margin: 0; font-size: .92rem; font-weight: 500; color: var(--bright); overflow-wrap: anywhere; }
.cnt-small { margin: 0; font-size: .78rem; line-height: 1.5; color: #aab4c0; overflow-wrap: anywhere; }
.cnt-small code { font: .74rem var(--mono); color: var(--cyan); }
.cnt-label { font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-right: .4rem; }
.cnt-diff { display: grid; gap: .2rem; border-top: 1px solid rgba(255, 255, 255, .06); padding-top: .4rem; }
.cnt-ok { color: #86efac; }
.cnt-refusal { margin: 0; font-size: .8rem; color: #fca5a5; overflow-wrap: anywhere; }
.cnt-act { display: grid; gap: .45rem; border-top: 1px solid rgba(255, 255, 255, .06); padding-top: .5rem; }
.cnt-row { display: flex; flex-wrap: wrap; gap: .5rem; }
.cnt-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .84rem; text-decoration: none; cursor: pointer; }
.cnt-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.cnt-btn.danger { color: #fca5a5; border-color: rgba(248, 113, 113, .45); background: rgba(248, 113, 113, .08); }
.cnt-btn:disabled { opacity: .5; cursor: not-allowed; }
.cnt-btn:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
</style>
