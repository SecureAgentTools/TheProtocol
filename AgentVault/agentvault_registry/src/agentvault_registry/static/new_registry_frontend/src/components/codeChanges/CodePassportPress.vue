<!--
  V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511; sessionlogs2026/DESIGN_2026-11-16_DEVELOPER_PASSPORT.md section 2): on a registry that does
  not govern code, beside the governing sentence. A developer takes part on the governing registry through this one: never automatically, only by the press, after
  seeing exactly the card the governing registry receives each time they act. Taking part, the repository account on the code host reads and links through this
  registry too (session-lead seq 5367). Proposing and reviewing go through the developer's own agent (POST /api/v1/code-passport/changes); votes stay with the
  governing registry's members.
-->
<template>
  <section v-if="st && st.available" class="cp" data-testid="cp-root">
    <template v-if="st.consented">
      <p class="cp-line" data-testid="cp-taking-part"><Icon name="mdi:source-branch" />
        {{ tp('codeChanges.passport.takingPart', 'You take part on {governing} from {home}: you propose and review there through your own agent; votes stay with its members.', { governing: st.governing, home: st.home }) }}</p>
      <div class="cp-actions">
        <button type="button" class="cp-btn" :disabled="busy" data-testid="cp-stop" @click="choose(false)">{{ t('codeChanges.passport.stop', 'Stop taking part') }}</button>
      </div>
      <RepoAccountLink :status="repo" :link="linkPassportRepo" @linked="loadRepo" />
    </template>

    <template v-else>
      <div v-if="!open" class="cp-actions">
        <button type="button" class="cp-btn primary" data-testid="cp-open" @click="open = true">{{ tp('codeChanges.passport.open', 'Take part on {governing}', { governing: st.governing }) }}</button>
      </div>
      <div v-else class="cp-panel" data-testid="cp-panel" role="region" :aria-label="tp('codeChanges.passport.open', 'Take part on {governing}', { governing: st.governing })">
        <h3>{{ tp('codeChanges.passport.title', 'Take part in code governance on {governing}', { governing: st.governing }) }}</h3>
        <p class="cp-note">{{ tp('codeChanges.passport.how', 'You keep your account here. Each time you propose or review, {home} signs a card for you and sends it to {governing} with the act; {governing} records the act under that card. Nothing is sent before you press Take part.', { home: st.home, governing: st.governing }) }}</p>
        <template v-if="st.preview">
          <h4>{{ tp('codeChanges.passport.cardTitle', 'What {governing} receives each time you act', { governing: st.governing }) }}</h4>
          <dl class="cp-card" data-testid="cp-card">
            <dt>{{ t('codeChanges.passport.name', 'Your public name') }}</dt>
            <dd>{{ st.preview.display_name || tp('codeChanges.passport.noName', 'none set: shown as developer {ref} of {home}', { ref: st.preview.developer_ref, home: st.preview.home_registry }) }}</dd>
            <dt>{{ t('codeChanges.passport.ref', 'Your developer number here') }}</dt><dd><code>{{ st.preview.developer_ref }}</code></dd>
            <dt>{{ t('codeChanges.passport.home', 'This registry') }}</dt><dd>{{ st.preview.home_registry }}</dd>
            <dt>{{ t('codeChanges.passport.standing', 'Your standing here') }}</dt><dd>{{ st.preview.standing }}</dd>
            <dt>{{ t('codeChanges.passport.agent', 'The agent that acts for you') }}</dt><dd><code>{{ st.preview.agent_did }}</code></dd>
          </dl>
          <ul class="cp-notes">
            <li>{{ t('codeChanges.passport.never', 'Nothing else: never your e-mail address, never your organisations.') }}</li>
            <li>{{ tp('codeChanges.passport.record', '{home} keeps a record of every card it sends: who, through which agent, to whom and why.', { home: st.home }) }}</li>
            <li>{{ tp('codeChanges.passport.votes', 'You propose and review changes; votes stay with {governing}\'s members.', { governing: st.governing }) }}</li>
            <li>{{ tp('codeChanges.passport.standingFollows', 'If {home} suspends or deletes your account, {governing} pauses or ends your part there, and your repository account with it.', { home: st.home, governing: st.governing }) }}</li>
            <li>{{ t('codeChanges.passport.stopAnyTime', 'You can stop taking part here at any time.') }}</li>
          </ul>
        </template>
        <p v-else class="cp-note" data-testid="cp-no-agent">{{ t('codeChanges.passport.noAgent', 'Taking part goes through one of your own agents: create an agent first.') }}</p>
        <p v-if="error" class="cp-error" role="alert" data-testid="cp-error">{{ error }}</p>
        <div class="cp-actions">
          <button v-if="st.preview" type="button" class="cp-btn primary" :disabled="busy" data-testid="cp-confirm" @click="choose(true)">{{ t('codeChanges.passport.confirm', 'Take part') }}</button>
          <button type="button" class="cp-btn" :disabled="busy" data-testid="cp-cancel" @click="open = false; error = ''">{{ t('codeChanges.passport.cancel', 'Not now') }}</button>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import RepoAccountLink from '@/components/codeChanges/RepoAccountLink.vue'
import { useI18n } from '@/composables/useI18n'
import { refusalWords } from '@/services/api/codeChanges'
import { getPassport, getPassportRepo, linkPassportRepo, setPassport, type PassportState } from '@/services/api/codePassport'
import type { RepoAccountStatus } from '@/services/api/repoAccount'

const { t, tp } = useI18n()
const st = ref<PassportState | null>(null)
const repo = ref<RepoAccountStatus | null>(null)
const open = ref(false)
const busy = ref(false)
const error = ref('')

async function loadRepo() {
  try { repo.value = await getPassportRepo() } catch { repo.value = null }
}
async function load() {
  try { st.value = await getPassport() } catch { st.value = null; return }
  if (st.value?.consented && st.value.available) await loadRepo()
}
async function choose(on: boolean) {
  busy.value = true
  error.value = ''
  try {
    st.value = await setPassport(on)
    open.value = false
    repo.value = null
    if (on) await loadRepo()
  } catch (e: any) {
    error.value = refusalWords(e, t('codeChanges.passport.failed', 'That did not go through; nothing changed. Try again.'))
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.cp { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace; display: grid; gap: .6rem; min-width: 0; margin: 4px 0 10px; }
.cp-line { margin: 0; display: flex; gap: .5rem; align-items: flex-start; line-height: 1.5; }
.cp-actions { display: flex; flex-wrap: wrap; gap: .6rem; }
.cp-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 18px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: inherit; font: inherit; cursor: pointer; }
.cp-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.cp-btn:disabled { opacity: .45; cursor: not-allowed; }
.cp-btn:not(:disabled):hover, .cp-btn:focus-visible { filter: brightness(1.12); }
.cp-panel { display: grid; gap: .7rem; padding: 1rem 1.1rem; border: 1px solid rgba(var(--cyan-rgb), .22); border-radius: 12px; background: rgba(var(--cyan-rgb), .04); max-width: 44rem; }
.cp-panel h3 { margin: 0; font-size: 1rem; font-weight: 500; }
.cp-panel h4 { margin: 0; font-size: .9rem; font-weight: 500; }
.cp-card { display: grid; grid-template-columns: max-content 1fr; gap: .35rem .9rem; margin: 0; font-size: .88rem; }
.cp-card dt { color: var(--muted); }
.cp-card dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.cp-card code { font: 400 .85rem var(--mono); }
.cp-notes { margin: 0; padding-left: 1.1rem; display: grid; gap: .35rem; color: var(--muted); font-size: .88rem; line-height: 1.5; }
.cp-note { margin: 0; color: var(--muted); font-size: .88rem; line-height: 1.5; }
.cp-error { margin: 0; color: #ff8a80; font-size: .88rem; }
</style>
