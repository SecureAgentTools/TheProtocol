<!--
  V0666 D2 (order gwo_f565ebd0575703f199dd9200; design: sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md section 5): the Contributions area,
  #/contributions, a part of its own with a queue apart from the main line's changes and ballots. For each organization the developer belongs to, its code distributions (its release lines on top of
  our release, never an AGORA payout); per line its change queue by lane (proposed, checked, in review, balloting, passed, merged, and the ended ones), each
  change's checker record, reviews and ballot; the vote for its deciders (through one of their agents, gov.vote, as the main line votes); the organization
  owner's go and veto; and the form that creates a line or changes it (later ballots only). Proposing into a line is the Code changes proposal with the line
  chosen (#/code-changes/new?line=<slug>). Shown where registry-config says code_distributions_enabled; off, a visit says so in one sentence. The registry
  decides every step again (D1: services/code_distributions, services/code_changes); this page words its record and shows its refusals.
-->
<template>
  <div class="ctb" data-testid="ctb-root">
    <header class="ctb-hero">
      <span class="ctb-eyebrow">{{ t('contributions.eyebrow', 'Release lines') }}</span>
      <h1>{{ t('contributions.title', 'Contributions') }}</h1>
      <p class="ctb-lede">{{ t('contributions.intro', 'An organization’s code distribution is its own release line on top of our release: its members propose, its deciders vote, and every change still goes through our signed checker and our veto. A separate queue from the platform’s Code changes and the Senate.') }}</p>
    </header>

    <p v-if="cfgOff" class="ctb-note ctb-off" role="status" data-testid="ctb-off">{{ t('contributions.off', 'Code distributions are off on this registry.') }}</p>
    <div v-else-if="readFailed" class="ctb-error" role="alert" data-testid="ctb-cfg-error">
      <p>{{ t('contributions.cfgError', 'This registry’s settings could not be read; try again.') }}</p>
      <button type="button" class="ctb-btn" @click="reload">{{ t('contributions.retry', 'Try again') }}</button>
    </div>
    <p v-else-if="!cfgOn" class="ctb-note" role="status" data-testid="ctb-reading">{{ t('contributions.reading', 'Reading this registry’s settings') }}</p>
    <p v-else-if="!signedIn" class="ctb-note" data-testid="ctb-signin">{{ t('contributions.signIn', 'Sign in to see the release lines of your organizations.') }}</p>

    <template v-else>
      <section class="ctb-orgs" :aria-busy="orgsLoading ? 'true' : 'false'">
        <h2 class="ctb-h2">{{ t('contributions.orgs.title', 'Your organizations') }}</h2>
        <p v-if="orgsLoading" class="ctb-note" role="status">{{ t('contributions.orgs.loading', 'Reading your organizations') }}</p>
        <div v-else-if="orgsError" class="ctb-error" role="alert" data-testid="ctb-orgs-error">
          <p>{{ t('contributions.orgs.error', 'Your organizations could not be read; try again.') }}</p>
          <button type="button" class="ctb-btn" @click="loadOrgs">{{ t('contributions.retry', 'Try again') }}</button>
        </div>
        <p v-else-if="!orgs.length" class="ctb-note" data-testid="ctb-no-orgs">{{ t('contributions.orgs.none', 'You belong to no organization yet. A release line is an organization’s: join or create one first.') }}</p>
        <div v-else class="ctb-chips" role="tablist" :aria-label="t('contributions.orgs.title', 'Your organizations')">
          <button v-for="o in orgs" :key="o.id" type="button" role="tab" class="ctb-chip" :class="{ on: o.id === orgId }" :aria-selected="o.id === orgId ? 'true' : 'false'"
            :data-testid="`ctb-org-${o.id}`" @click="pickOrg(o.id)">{{ o.name }} <span class="ctb-role">{{ roleWord(o.my_role) }}</span></button>
        </div>
      </section>

      <section v-if="org" class="ctb-lines" :aria-busy="linesLoading ? 'true' : 'false'" data-testid="ctb-lines">
        <div class="ctb-bar">
          <h2 class="ctb-h2">{{ tp('contributions.lines.title', 'Release lines of {org}', { org: org.name }) }}</h2>
          <button v-if="manage && !form" type="button" class="ctb-btn primary" data-testid="ctb-new-line" @click="openCreate">{{ t('contributions.lines.new', 'New release line') }}</button>
        </div>
        <p v-if="linesLoading" class="ctb-note" role="status">{{ t('contributions.lines.loading', 'Reading the release lines') }}</p>
        <div v-else-if="linesError" class="ctb-error" role="alert" data-testid="ctb-lines-error"><p>{{ linesError }}</p>
          <button type="button" class="ctb-btn" @click="loadLines">{{ t('contributions.retry', 'Try again') }}</button></div>
        <p v-else-if="!lines.length && !form" class="ctb-note" data-testid="ctb-no-lines">{{ manage
          ? t('contributions.lines.noneManage', 'This organization has no release line yet. Create one: name it, choose the paths it opens and who decides.')
          : t('contributions.lines.none', 'This organization has no release line yet; its owners and admins create one.') }}</p>
        <ul v-else-if="lines.length" class="ctb-line-list">
          <li v-for="l in lines" :key="l.slug">
            <button type="button" class="ctb-line" :class="{ on: l.slug === lineSlug }" :aria-pressed="l.slug === lineSlug ? 'true' : 'false'" :data-testid="`ctb-line-${l.slug}`" @click="pickLine(l.slug)">
              <span class="ctb-line-t">{{ l.title }}</span>
              <code class="ctb-line-r">{{ l.release_name }}</code>
              <span v-if="l.state === 'paused'" class="ctb-tag warn" data-testid="ctb-line-paused">{{ t('contributions.line.paused', 'Paused') }}</span>
            </button>
          </li>
        </ul>

        <form v-if="form" class="ctb-card ctb-form" data-testid="ctb-form" novalidate @submit.prevent="saveForm">
          <h3>{{ form.mode === 'create' ? t('contributions.form.createTitle', 'A new release line') : tp('contributions.form.editTitle', 'Change {line}', { line: form.before?.title || '' }) }}</h3>
          <p v-if="form.mode === 'edit'" class="ctb-hint" data-testid="ctb-form-later">{{ t('contributions.form.later', 'A change here applies to ballots opened after it: a ballot already open keeps the rule it opened with. The name and the base release do not change.') }}</p>
          <label v-if="form.mode === 'create'" class="ctb-field"><span>{{ t('contributions.form.slug', 'Name') }}</span>
            <input v-model.trim="form.d.slug" data-testid="ctb-f-slug" maxlength="40" autocomplete="off" :aria-invalid="bad('slug') ? 'true' : 'false'" />
            <small>{{ tp('contributions.form.slugHint', 'Lowercase letters, digits and \'-\'. The release is called {release}.', { release: (form.d.base_release || 'V0000') + '_' + (form.d.slug || 'name') }) }}</small></label>
          <label class="ctb-field"><span>{{ t('contributions.form.titleField', 'Title') }}</span>
            <input v-model="form.d.title" data-testid="ctb-f-title" maxlength="200" :aria-invalid="bad('title') ? 'true' : 'false'" /></label>
          <label v-if="form.mode === 'create'" class="ctb-field"><span>{{ t('contributions.form.base', 'Base release') }}</span>
            <input v-model.trim="form.d.base_release" data-testid="ctb-f-base" maxlength="8" placeholder="V0666" :aria-invalid="bad('base_release') ? 'true' : 'false'" />
            <small>{{ t('contributions.form.baseHint', 'Our release the line sits on.') }}</small></label>
          <fieldset class="ctb-field" data-testid="ctb-f-paths"><legend>{{ t('contributions.form.paths', 'Open paths') }}</legend>
            <small>{{ t('contributions.form.pathsHint', 'The paths the line opens to its members: the platform’s open paths, or a part of them.') }}</small>
            <div class="ctb-chips">
              <button v-for="p in platformPaths" :key="p" type="button" class="ctb-chip" :class="{ on: form.d.open_paths.includes(p) }" :aria-pressed="form.d.open_paths.includes(p) ? 'true' : 'false'"
                data-testid="ctb-f-platform-path" :title="p" @click="togglePath(p)">{{ pathLabel(p, tr) }}</button>
            </div>
            <div class="ctb-narrow">
              <input v-model.trim="narrow" data-testid="ctb-f-narrow" :placeholder="t('contributions.form.narrowPh', 'or a part of them, e.g. views/Guild')" @keydown.enter.prevent="addNarrow" />
              <button type="button" class="ctb-btn" data-testid="ctb-f-narrow-add" @click="addNarrow">{{ t('contributions.form.add', 'Add') }}</button>
            </div>
            <ul v-if="form.d.open_paths.length" class="ctb-paths"><li v-for="p in form.d.open_paths" :key="p"><code :title="p">{{ pathLabel(p, tr) }}</code>
              <button type="button" class="ctb-x" :aria-label="tp('contributions.form.remove', 'Remove {p}', { p })" @click="togglePath(p)">×</button></li></ul>
          </fieldset>
          <label class="ctb-field"><span>{{ t('contributions.form.team', 'Deciding team') }}</span>
            <select v-model="form.d.decider_team_id" data-testid="ctb-f-team">
              <option value="">{{ t('contributions.form.noTeam', 'None: the owners and admins decide') }}</option>
              <option v-for="tm in teams" :key="tm.id" :value="tm.id">{{ tm.name }}</option>
            </select>
            <small>{{ t('contributions.form.teamHint', 'The team’s leads decide beside the owners and admins.') }}</small></label>
          <label class="ctb-field"><span>{{ t('contributions.form.quorum', 'Quorum (percent of the deciders)') }}</span>
            <input v-model="form.d.quorum_percent" type="number" :min="QUORUM_MIN" :max="QUORUM_MAX" step="1" data-testid="ctb-f-quorum" :aria-invalid="bad('quorum_percent') ? 'true' : 'false'" />
            <small>{{ tp('contributions.form.quorumHint', 'From {min} to {max}. A ballot closes early once every decider has voted.', { min: QUORUM_MIN, max: QUORUM_MAX }) }}</small></label>
          <label class="ctb-field"><span>{{ t('contributions.form.rule', 'Pass rule') }}</span>
            <select v-model="form.d.pass_rule" data-testid="ctb-f-rule"><option value="simple">{{ t('contributions.form.simple', 'Simple majority of the votes') }}</option></select></label>
          <ul v-if="formTouched && formProblems.length" class="ctb-problems" role="alert" data-testid="ctb-form-problems"><li v-for="p in formProblems" :key="p.field + p.sentence">{{ p.sentence }}</li></ul>
          <p v-if="formError" class="ctb-refusal" role="alert" data-testid="ctb-form-error">{{ formError }}</p>
          <div class="ctb-actions">
            <button type="submit" class="ctb-btn primary" :disabled="formBusy" data-testid="ctb-f-save">{{ form.mode === 'create' ? t('contributions.form.create', 'Create the line') : t('contributions.form.save', 'Save') }}</button>
            <button type="button" class="ctb-btn" :disabled="formBusy" data-testid="ctb-f-cancel" @click="form = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
          </div>
        </form>
      </section>

      <section v-if="line && !form" class="ctb-detail" data-testid="ctb-detail">
        <div class="ctb-card ctb-head">
          <div class="ctb-head-t">
            <h2>{{ line.title }}</h2>
            <p class="ctb-facts"><code data-testid="ctb-release">{{ line.release_name }}</code> <span>·</span> <code>{{ line.branch }}</code>
              <span>·</span> {{ tp('contributions.line.deciders', '{n} deciders now', { n: line.deciders ?? '?' }) }}
              <span>·</span> {{ tp('contributions.line.rule', 'quorum {q} percent, simple majority', { q: line.quorum_percent }) }}</p>
            <p v-if="line.deciders_note" class="ctb-warn" data-testid="ctb-deciders-note">{{ line.deciders_note }}</p>
            <p v-if="line.state === 'paused'" class="ctb-warn" data-testid="ctb-paused-reason">{{ tp('contributions.line.pausedBy', 'Paused by the platform: {reason}. No proposal, vote, ballot or merge until it resumes.', { reason: line.paused_reason || '?' }) }}</p>
            <p class="ctb-paths-line"><code v-for="p in line.open_paths || []" :key="p" :title="p">{{ pathLabel(p, tr) }}</code></p>
          </div>
          <div class="ctb-actions">
            <RouterLink v-if="propose && line.state !== 'paused'" :to="{ name: 'code-changes-new', query: { line: line.slug } }" class="ctb-btn primary" data-testid="ctb-propose">{{ t('contributions.line.propose', 'Propose a change to this line') }}</RouterLink>
            <button v-if="propose" type="button" class="ctb-btn" :disabled="reporting" data-testid="ctb-report" @click="downloadReport">{{ t('contributions.line.report', 'Download the signed report') }}</button>
            <button v-if="manage" type="button" class="ctb-btn" data-testid="ctb-edit-line" @click="openEdit">{{ t('contributions.line.edit', 'Change the line') }}</button>
          </div>
        </div>

        <p v-if="reportError" class="ctb-refusal" role="alert" data-testid="ctb-report-error">{{ reportError }}</p>
        <p v-if="changesLoading" class="ctb-note" role="status">{{ t('contributions.queue.loading', 'Reading the line’s changes') }}</p>
        <div v-else-if="changesError" class="ctb-error" role="alert" data-testid="ctb-changes-error"><p>{{ t('contributions.queue.error', 'The line’s changes could not be read; try again.') }}</p>
          <button type="button" class="ctb-btn" @click="loadChanges">{{ t('contributions.retry', 'Try again') }}</button></div>
        <p v-else-if="!changes.length" class="ctb-note" data-testid="ctb-no-changes">{{ t('contributions.queue.none', 'No change has been proposed to this line yet.') }}</p>
        <div v-else class="ctb-queue" data-testid="ctb-queue">
          <section v-for="lane in shownLanes" :key="lane" class="ctb-lane" :data-lane="lane" :data-testid="`ctb-lane-${lane}`">
            <h3 class="ctb-lane-h">{{ laneWord(lane, tr) }} <span class="ctb-count">{{ lanes[lane].length }}</span></h3>
            <article v-for="c in lanes[lane]" :key="c.id" class="ctb-card ctb-change" :data-testid="`ctb-change-${c.id}`">
              <RouterLink :to="{ name: 'code-change', params: { id: c.id } }" class="ctb-change-t">{{ c.title }}</RouterLink>
              <p class="ctb-small"><span class="ctb-tag" :data-state="c.state">{{ lineStateWord(String(c.state), (x) => stateWord(x, tr), tr) }}</span>
                <span v-if="c.sensitive" class="ctb-tag warn">{{ t('codeChanges.sensitive', 'Sensitive path') }}</span></p>
              <p class="ctb-small" :data-checker="checkerWords(c, tr).state" data-testid="ctb-checker">{{ checkerWords(c, tr).text }}</p>
              <p class="ctb-small" data-testid="ctb-reviews">{{ reviewWords(c, tr) }}</p>
              <p v-if="ballotWords(c, tr)" class="ctb-small" data-testid="ctb-ballot">{{ ballotWords(c, tr) }}</p>
              <p v-if="c.org_go" class="ctb-small" data-testid="ctb-org-go">{{ t('contributions.owner.goneAhead', 'The organization’s owner said go. The platform’s veto window still runs.') }}</p>

              <p v-if="myVote(c) !== undefined" class="ctb-small ctb-ok" data-testid="ctb-voted">{{ myVote(c) ? t('contributions.vote.castFor', 'Your vote for this change is in. A vote is never changed.') : t('contributions.vote.castAgainst', 'Your vote against this change is in. A vote is never changed.') }}</p>
              <div v-else-if="voteOffer(c, me, tr).offer" class="ctb-vote" data-testid="ctb-vote">
                <template v-if="confirming?.id === c.id && confirming?.kind === 'vote'">
                  <p class="ctb-small">{{ confirming?.vote ? t('contributions.vote.confirmFor', 'Vote for this change? A vote is never changed.') : t('contributions.vote.confirmAgainst', 'Vote against this change? A vote is never changed.') }}</p>
                  <div class="ctb-actions">
                    <button type="button" class="ctb-btn primary" :disabled="acting" data-testid="ctb-vote-confirm" @click="castVote(c, !!confirming?.vote)">{{ t('contributions.vote.confirm', 'Cast the vote') }}</button>
                    <button type="button" class="ctb-btn" :disabled="acting" @click="confirming = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
                  </div>
                </template>
                <template v-else-if="!agentDid"><p class="ctb-small" data-testid="ctb-vote-agent">{{ t('contributions.vote.needAgent', 'Choose one of your agents first: the vote goes through an agent, as on the main line.') }}</p></template>
                <div v-else class="ctb-actions">
                  <button type="button" class="ctb-btn" data-testid="ctb-vote-for" @click="confirming = { id: c.id, kind: 'vote', vote: true }">{{ t('contributions.vote.for', 'Vote for') }}</button>
                  <button type="button" class="ctb-btn" data-testid="ctb-vote-against" @click="confirming = { id: c.id, kind: 'vote', vote: false }">{{ t('contributions.vote.against', 'Vote against') }}</button>
                </div>
              </div>
              <p v-else-if="voteOffer(c, me, tr).why" class="ctb-small ctb-muted" data-testid="ctb-vote-why">{{ voteOffer(c, me, tr).why }}</p>

              <div v-if="ownerOffer(c, me)" class="ctb-owner" data-testid="ctb-owner">
                <template v-if="confirming?.id === c.id && confirming?.kind === 'veto'">
                  <label class="ctb-field"><span>{{ t('contributions.owner.why', 'Why the veto (the proposer reads it)') }}</span>
                    <textarea v-model="vetoReason" rows="2" maxlength="1000" data-testid="ctb-veto-reason"></textarea></label>
                  <div class="ctb-actions">
                    <button type="button" class="ctb-btn danger" :disabled="acting || !vetoReason.trim()" data-testid="ctb-veto-confirm" @click="veto(c)">{{ t('contributions.owner.vetoConfirm', 'Veto the change') }}</button>
                    <button type="button" class="ctb-btn" :disabled="acting" @click="confirming = null">{{ t('contributions.form.cancel', 'Cancel') }}</button>
                  </div>
                </template>
                <div v-else class="ctb-actions">
                  <button v-if="!c.org_go" type="button" class="ctb-btn" :disabled="acting" data-testid="ctb-owner-go" @click="go(c)">{{ t('contributions.owner.go', 'Say go (the platform’s window still runs)') }}</button>
                  <button type="button" class="ctb-btn danger" data-testid="ctb-owner-veto" @click="confirming = { id: c.id, kind: 'veto' }; vetoReason = ''">{{ t('contributions.owner.veto', 'Veto') }}</button>
                </div>
              </div>
              <p v-if="refusal[c.id]" class="ctb-refusal" role="alert" :data-testid="`ctb-refusal-${c.id}`">{{ refusal[c.id] }}</p>
            </article>
          </section>
        </div>
        <ContentChangesPanel :line-slug="String(line.slug)" :me="myId" :agent-did="agentDid" :can-propose="propose" :paused="line.state === 'paused'" data-testid="ctb-content" />
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import ContentChangesPanel from '@/components/codeChanges/ContentChangesPanel.vue'
import { getReport } from '@/services/api/distributionReports'
import { downloadSigned } from '@/services/contentChanges/download'
import { useAuthStore } from '@/stores/auth'
import { organizationService, type Organization, type Team } from '@/services/api/organizationService'
import { refusalWords, type ChangeRecord } from '@/services/api/codeChanges'
import { createLine, getLine, listLineChanges, listOrgLines, ownerGo, ownerVeto, updateLine, voteLineChange, type LineRecord } from '@/services/api/codeDistributions'
import { stateWord } from '@/services/codeChanges/codeChangeView'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'
import { useTr } from '@/services/codeChanges/tr'
import {
  LANES, QUORUM_MAX, QUORUM_MIN, ballotWords, canManage, canPropose, checkerWords, draftOf, emptyLine, groupByLane, laneWord, lineBody, linePatch, lineProblems,
  lineStateWord, ownerOffer, pathLabel, platformOpenPaths, releaseOf, reviewWords, voteOffer, type Lane, type LineDraft, type Me,
} from '@/services/codeDistributions/lines'

const { t, tp } = useI18n()
const tr = useTr()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore() as any
const { codeDistributionsEnabled, loaded, readFailed, reload, load: loadCfg } = useRegistryConfig() as any

const cfgOn = computed(() => codeDistributionsEnabled.value === true)
const cfgOff = computed(() => loaded.value && !readFailed.value && !cfgOn.value)
const signedIn = computed(() => !!auth.isAuthenticated)
const myId = computed<number | null>(() => { const v = Number(auth.user?.developer_id ?? auth.user?.id); return Number.isFinite(v) && v > 0 ? v : null })
const agentDid = computed(() => auth.activeAgent?.did || '')

const orgs = ref<Organization[]>([])
const orgsLoading = ref(false)
const orgsError = ref(false)
const orgId = ref('')
const org = computed(() => orgs.value.find((o) => o.id === orgId.value) || null)
const lines = ref<LineRecord[]>([])
const linesLoading = ref(false)
const linesError = ref('')
const lineSlug = ref('')
const line = ref<LineRecord | null>(null)
const changes = ref<ChangeRecord[]>([])
const changesLoading = ref(false)
const changesError = ref(false)
const teams = ref<Team[]>([])
const teamLead = ref(false)
const refusal = reactive<Record<string, string>>({})
const acting = ref(false)
const confirming = ref<{ id: string; kind: 'vote' | 'veto'; vote?: boolean } | null>(null)
const vetoReason = ref('')
const baseRelease = ref('')

const me = computed<Me>(() => ({ developerId: myId.value, orgRole: org.value?.my_role || null, teamLead: teamLead.value, orgOwnerId: org.value?.owner_id ?? null }))
const manage = computed(() => canManage(me.value))
const propose = computed(() => canPropose(me.value))
const lanes = computed(() => groupByLane(changes.value))
// the six lanes always (an empty lane says where a change would stand); "ended" and "other" only when a change is there
const shownLanes = computed<Lane[]>(() => LANES.filter((l) => (l !== 'ended' && l !== 'other') || lanes.value[l].length))
const platformPaths = platformOpenPaths()
const roleWord = (r?: string | null) => ({ owner: t('contributions.role.owner', 'owner'), admin: t('contributions.role.admin', 'admin'), member: t('contributions.role.member', 'member'), guest: t('contributions.role.guest', 'guest') } as Record<string, string>)[String(r || '')] || ''

async function loadOrgs() {
  orgsLoading.value = true; orgsError.value = false
  try {
    orgs.value = (await organizationService.listOrganizations()).filter((o) => o.is_active !== false)
    const want = typeof route.query.org === 'string' ? route.query.org : ''
    const pick = orgs.value.find((o) => o.id === want) || orgs.value[0]
    if (pick) await selectOrg(pick.id)
  } catch { orgsError.value = true } finally { orgsLoading.value = false }
}
async function selectOrg(id: string) {
  orgId.value = id; form.value = null
  await loadLines()
  try { teams.value = (await organizationService.listTeams(id)).filter((x) => x.is_active !== false) } catch { teams.value = [] }
  const want = typeof route.query.line === 'string' ? route.query.line : ''
  const pick = lines.value.find((l) => l.slug === want)
  if (pick) await selectLine(pick.slug)
  else { lineSlug.value = ''; line.value = null; changes.value = [] }
}
function pickOrg(id: string) { void router.replace({ query: { ...route.query, org: id, line: undefined } }); void selectOrg(id) }
async function loadLines() {
  linesLoading.value = true; linesError.value = ''
  try { lines.value = await listOrgLines(orgId.value) } catch (e) { lines.value = []; linesError.value = refusalWords(e, t('contributions.lines.error', 'The release lines could not be read; try again.')) } finally { linesLoading.value = false }
}
async function selectLine(slug: string) {
  lineSlug.value = slug; form.value = null; confirming.value = null
  try { line.value = await getLine(slug) } catch { line.value = lines.value.find((l) => l.slug === slug) || null }
  teamLead.value = false
  const team = line.value?.decider_team_id
  if (team && myId.value !== null) {
    try { teamLead.value = (await organizationService.listTeamMembers(orgId.value, String(team))).some((m) => m.developer_id === myId.value && m.role === 'lead') } catch { teamLead.value = false }
  }
  await loadChanges()
}
function pickLine(slug: string) { void router.replace({ query: { ...route.query, org: orgId.value, line: slug } }); void selectLine(slug) }
async function loadChanges() {
  if (!lineSlug.value) return
  changesLoading.value = true; changesError.value = false
  try { changes.value = await listLineChanges(lineSlug.value) } catch { changesError.value = true } finally { changesLoading.value = false }
}
function replaceChange(rec: ChangeRecord) { if (rec?.id) changes.value = changes.value.map((c) => (c.id === rec.id ? rec : c)) }

async function act(c: ChangeRecord, step: () => Promise<ChangeRecord>) {
  acting.value = true; delete refusal[c.id]
  try { replaceChange(await step()); confirming.value = null } catch (e) { refusal[c.id] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = false }
}
// the registry answers the change, not who voted: the vote this page cast is remembered here so it is said, never offered again (a second is refused)
const voted = reactive<Record<string, boolean>>({})
/** The reader's own vote: the registry's line_ballot.my_vote (FOR, AGAINST, null), else the vote this page just cast (an older registry says none). */
const myVote = (c: ChangeRecord): boolean | undefined => {
  const mv = (c.line_ballot as any)?.my_vote
  return mv === 'FOR' ? true : mv === 'AGAINST' ? false : voted[c.id]
}
const castVote = async (c: ChangeRecord, vote: boolean) => { await act(c, () => voteLineChange(String(c.id), vote)); if (!refusal[c.id]) voted[c.id] = vote }
const go = (c: ChangeRecord) => act(c, () => ownerGo(String(c.id)))
const veto = (c: ChangeRecord) => act(c, () => ownerVeto(String(c.id), vetoReason.value.trim()))

// -- the line form --
const form = ref<{ mode: 'create' | 'edit'; d: LineDraft; before?: LineDraft } | null>(null)
const formTouched = ref(false)
const formBusy = ref(false)
const formError = ref('')
const narrow = ref('')
const formProblems = computed(() => (form.value ? lineProblems(form.value.d, form.value.mode, tr) : []))
const bad = (f: string) => formTouched.value && formProblems.value.some((p) => p.field === f)
function openCreate() { form.value = { mode: 'create', d: emptyLine(baseRelease.value) }; formTouched.value = false; formError.value = '' }
function openEdit() { if (!line.value) return; const d = draftOf(line.value); form.value = { mode: 'edit', d, before: draftOf(line.value) }; formTouched.value = false; formError.value = '' }
function togglePath(p: string) { if (!form.value) return; const ps = form.value.d.open_paths; form.value.d.open_paths = ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p] }
function addNarrow() {
  if (!form.value || !narrow.value) return
  const raw = narrow.value.replace(/\/+$/, '')
  const full = raw.startsWith('agentvault_registry/') ? raw : CONSOLE_PREFIX + raw.replace(/^\/+/, '')
  if (!form.value.d.open_paths.includes(full)) form.value.d.open_paths = [...form.value.d.open_paths, full]
  narrow.value = ''
}
const reporting = ref(false)
const reportError = ref('')
async function downloadReport() {
  if (!line.value) return
  reporting.value = true; reportError.value = ''
  try { downloadSigned(await getReport(String(line.value.slug))) } catch (e) { reportError.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { reporting.value = false }
}

async function saveForm() {
  if (!form.value) return
  formTouched.value = true
  if (formProblems.value.length) return
  formBusy.value = true; formError.value = ''
  try {
    if (form.value.mode === 'create') {
      const rec = await createLine(lineBody(form.value.d, orgId.value) as any)
      form.value = null
      await loadLines()
      pickLine(String(rec.slug))
    } else if (line.value && form.value.before) {
      const patch = linePatch(form.value.before, form.value.d)
      if (Object.keys(patch).length) line.value = { ...line.value, ...(await updateLine(String(line.value.slug), patch as any)) }
      form.value = null
      await loadLines()
    }
  } catch (e) { formError.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { formBusy.value = false }
}

async function readBaseRelease() {
  try {
    const r = await fetch('/.well-known/registry-card.json', { headers: { Accept: 'application/json' } })
    if (r.ok) baseRelease.value = releaseOf((await r.json())?.identity?.software_version)
  } catch { /* the field stays empty; the person types it */ }
}

let started = false
async function start() {
  if (started || !cfgOn.value || !signedIn.value) return
  started = true
  void readBaseRelease()
  await loadOrgs()
}
watch([cfgOn, signedIn], () => { void start() })
onMounted(async () => { await loadCfg?.(); void start() })
</script>

<style scoped>
.ctb { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 80rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.2rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.ctb > * { min-width: 0; }
.ctb-hero { display: grid; gap: .6rem; justify-items: start; }
.ctb-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.ctb-hero h1 { margin: 0; font-size: 1.9rem; font-weight: 300; }
.ctb-lede { margin: 0; color: var(--muted); font-size: .92rem; max-width: 52rem; line-height: 1.6; }
.ctb-h2 { margin: 0; font-size: 1.05rem; font-weight: 500; }
.ctb-note { margin: 0; color: var(--muted); font-size: .88rem; }
.ctb-off { border: 1px dashed rgba(var(--cyan-rgb), .3); border-radius: 12px; padding: 1rem 1.2rem; color: var(--bright); }
.ctb-error { border: 1px solid rgba(248, 113, 113, .35); border-radius: 12px; padding: .9rem 1.1rem; display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; color: #fca5a5; }
.ctb-error p { margin: 0; }
.ctb-orgs, .ctb-lines, .ctb-detail { display: grid; gap: .8rem; }
.ctb-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .8rem; }
.ctb-chips { display: flex; flex-wrap: wrap; gap: .4rem; }
.ctb-chip { min-height: 36px; padding: 0 12px; border-radius: 999px; border: 1px solid rgba(var(--cyan-rgb), .22); background: none; color: var(--muted); font: inherit; font-size: .8rem; cursor: pointer; display: inline-flex; align-items: center; gap: .4rem; max-width: 100%; overflow-wrap: anywhere; }
.ctb-chip.on { color: #04141a; background: var(--cyan); border-color: transparent; font-weight: 600; }
.ctb-role { font: 600 .66rem var(--mono); opacity: .75; text-transform: uppercase; letter-spacing: .05em; }
.ctb-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .84rem; text-decoration: none; cursor: pointer; }
.ctb-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.ctb-btn.danger { color: #fca5a5; border-color: rgba(248, 113, 113, .45); background: rgba(248, 113, 113, .08); }
.ctb-btn:disabled { opacity: .5; cursor: not-allowed; }
.ctb-btn:focus-visible, .ctb-chip:focus-visible, .ctb-line:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.ctb-card { background: rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1rem 1.15rem; min-width: 0; }
.ctb-line-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr)); gap: .6rem; }
.ctb-line { width: 100%; text-align: left; display: grid; gap: .35rem; padding: .8rem 1rem; border-radius: 10px; border: 1px solid rgba(var(--cyan-rgb), .18); background: rgba(var(--cyan-rgb), .03); color: var(--bright); font: inherit; cursor: pointer; min-height: 44px; }
.ctb-line.on { border-color: var(--cyan); background: rgba(var(--cyan-rgb), .09); }
.ctb-line-t { font-size: .95rem; font-weight: 500; overflow-wrap: anywhere; }
.ctb-line-r, .ctb-facts code, .ctb-paths-line code, .ctb-paths code { font: .72rem var(--mono); color: var(--cyan); overflow-wrap: anywhere; }
.ctb-tag { justify-self: start; font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 8px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.ctb-tag.warn { color: #fcd34d; border-color: rgba(245, 158, 11, .4); }
.ctb-tag[data-state='merged'], .ctb-tag[data-state='passed'] { color: #34d399; border-color: rgba(16, 185, 129, .4); }
.ctb-tag[data-state='failed'], .ctb-tag[data-state='vetoed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.ctb-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 1rem; align-items: flex-start; }
.ctb-head-t { display: grid; gap: .45rem; min-width: 0; flex: 1 1 22rem; }
.ctb-head h2 { margin: 0; font-size: 1.2rem; font-weight: 500; overflow-wrap: anywhere; }
.ctb-facts { margin: 0; font-size: .8rem; color: var(--muted); display: flex; flex-wrap: wrap; gap: .35rem; align-items: baseline; }
.ctb-paths-line { margin: 0; display: flex; flex-wrap: wrap; gap: .35rem; }
.ctb-paths-line code { background: rgba(0,0,0,.3); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 5px; padding: 2px 7px; }
.ctb-warn { margin: 0; font-size: .82rem; color: #fcd34d; }
.ctb-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.ctb-queue { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: .8rem; align-items: start; }
.ctb-lane { display: grid; gap: .6rem; align-content: start; min-width: 0; }
.ctb-lane-h { margin: 0; font: 700 11px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); display: flex; gap: .4rem; align-items: center; padding: .4rem 0; border-bottom: 1px solid rgba(255,255,255,.07); }
.ctb-lane[data-lane='ended'] .ctb-lane-h { color: #fca5a5; }
.ctb-count { font-weight: 600; color: var(--cyan); }
.ctb-change { display: grid; gap: .45rem; padding: .8rem .9rem; }
.ctb-change-t { color: var(--bright); text-decoration: none; font-size: .92rem; font-weight: 500; overflow-wrap: anywhere; }
.ctb-change-t:hover, .ctb-change-t:focus-visible { color: var(--cyan); }
.ctb-small { margin: 0; font-size: .78rem; line-height: 1.5; color: #aab4c0; display: flex; flex-wrap: wrap; gap: .35rem; overflow-wrap: anywhere; }
.ctb-small[data-checker='failed'] { color: #fca5a5; }
.ctb-small[data-checker='ok'] { color: #86efac; }
.ctb-muted { color: var(--muted); }
.ctb-ok { color: #86efac; }
.ctb-vote, .ctb-owner { display: grid; gap: .45rem; border-top: 1px solid rgba(255,255,255,.06); padding-top: .5rem; }
.ctb-refusal { margin: 0; font-size: .8rem; color: #fca5a5; overflow-wrap: anywhere; }
.ctb-form { display: grid; gap: .8rem; max-width: 46rem; }
.ctb-form h3 { margin: 0; font-size: 1rem; font-weight: 500; }
.ctb-hint { margin: 0; font-size: .8rem; color: #fcd34d; line-height: 1.5; }
.ctb-field { display: grid; gap: .3rem; font-size: .82rem; border: 0; padding: 0; margin: 0; min-width: 0; }
.ctb-field > span, .ctb-field legend { font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 0; }
.ctb-field small { color: var(--muted); font-size: .74rem; }
.ctb-field input, .ctb-field select, .ctb-field textarea, .ctb-narrow input { min-height: 40px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .25); background: rgba(0,0,0,.3); color: var(--bright); font: inherit; font-size: .86rem; padding: 0 .7rem; min-width: 0; width: 100%; box-sizing: border-box; }
.ctb-field textarea { padding: .5rem .7rem; }
.ctb-field input[aria-invalid='true'] { border-color: rgba(248, 113, 113, .7); }
.ctb-narrow { display: flex; gap: .4rem; }
.ctb-paths { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: .35rem; }
.ctb-paths li { display: inline-flex; align-items: center; gap: .3rem; border: 1px solid rgba(var(--cyan-rgb), .2); border-radius: 6px; padding: 2px 4px 2px 8px; max-width: 100%; }
.ctb-x { min-width: 32px; min-height: 32px; border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 1rem; }
.ctb-problems { margin: 0; padding-left: 1.1rem; color: #fca5a5; font-size: .8rem; display: grid; gap: .2rem; }
@media (max-width: 640px) {
  .ctb { padding: 1rem .8rem 2.5rem; } .ctb-hero h1 { font-size: 1.5rem; }
  .ctb-queue { grid-template-columns: 1fr; } .ctb-line-list { grid-template-columns: 1fr; }
  .ctb-head .ctb-actions { width: 100%; } .ctb-head .ctb-btn { flex: 1 1 auto; justify-content: center; }
}
</style>
