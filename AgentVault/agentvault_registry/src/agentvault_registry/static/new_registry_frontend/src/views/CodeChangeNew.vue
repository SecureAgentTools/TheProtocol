<!--
  V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): proposing a code change as a guided flow, #/code-changes/new: what is wrong, which files (a picker over the console's tree that checks each
  path the way the registry will and says what a sensitive one needs), how it gets written (a bounty the Guild holds, or a branch with its full commit id), and a review of it all
  with what happens next and the licence line. Anyone can walk it; proposing is the selected agent's (the registry decides again at every step).
-->
<template>
  <div class="ccn" data-testid="ccn-root">
    <CodeChangesTabs current="code-changes-new" />
    <RouterLink v-if="lineSlug" :to="{ name: 'contributions', query: { org: line?.organization_id || undefined, line: lineSlug } }" class="ccn-back" data-testid="ccn-back">{{ t('contributions.propose.back', 'Back to the release line') }}</RouterLink>
    <RouterLink v-else :to="{ name: 'code-changes' }" class="ccn-back" data-testid="ccn-back">{{ t('codeChanges.back', 'All changes') }}</RouterLink>

    <header class="ccn-hero">
      <span class="ccn-eyebrow">{{ t('codeChanges.eyebrow', 'Governed code') }}</span>
      <h1>{{ t('codeChanges.new.title', 'Propose a code change') }}</h1>
      <p class="ccn-lede">{{ t('codeChanges.new.lede', 'Four short steps. Nothing is sent until the last one. A good proposal is small, names its files and says what is wrong.') }}</p>
      <p v-if="lineSlug && line" class="ccn-line" data-testid="ccn-line">{{ line.organization_name
        ? tp('contributions.propose.intoOrg', 'Into the release line {title} ({release}) of {org}: its members review it and its deciders vote, not the frame’s members.', { title: line.title, release: line.release_name, org: line.organization_name })
        : tp('contributions.propose.into', 'Into the release line {title} ({release}) of its organization: its members review it and its deciders vote, not the frame’s members.', { title: line.title, release: line.release_name }) }}</p>
      <p v-else-if="lineSlug && lineError" class="ccn-line bad" role="alert" data-testid="ccn-line-error">{{ lineError }}</p>
      <p v-if="lineSlug && line && roomId" class="ccn-line" data-testid="ccn-room">{{ t('contributions.propose.room', 'The change is announced in the room you came from: its live card follows it there, and each step posts one line.') }}</p>
      <p v-if="!canPropose" class="ccn-signin" data-testid="ccn-signin"><Icon name="mdi:lock" /> {{ t('codeChanges.new.signIn', 'Sign in and pick an agent (top right) to propose. You can walk through the steps without.') }}</p>
    </header>

    <GovernedElsewhere v-if="authorityView_.readOnly" :view="authorityView_" />

    <ol v-if="!authorityView_.readOnly" class="ccn-pills" data-testid="ccn-pills">
      <li v-for="(s, i) in STEPS" :key="s">
        <button type="button" class="ccn-pill" :class="{ on: step === s, done: i < stepIndex }" :aria-current="step === s ? 'step' : undefined" :disabled="i > stepIndex" :data-testid="`ccn-pill-${s}`" @click="go(s)">
          <span class="ccn-n">{{ i + 1 }}</span><span class="ccn-pl">{{ stepTitle(s) }}</span>
        </button>
      </li>
    </ol>

    <div v-if="!authorityView_.readOnly" class="ccn-grid">
      <section class="ccn-card" :data-testid="`ccn-step-${step}`">
        <template v-if="step === 'what'">
          <h2>{{ t('codeChanges.new.s1', 'What is wrong?') }}</h2>
          <label class="ccn-f"><span>{{ t('codeChanges.new.titleLabel', 'Title') }}</span>
            <input v-model="d.title" class="ccn-in" maxlength="160" data-testid="ccn-title" :aria-invalid="touched && has('title') ? 'true' : 'false'" :placeholder="t('codeChanges.new.titlePh', 'Show who is paid on the order page')" />
            <small>{{ d.title.length }}/160</small></label>
          <label class="ccn-f"><span>{{ t('codeChanges.new.problemLabel', 'The problem') }}</span>
            <textarea v-model="d.problem" class="ccn-in" rows="6" maxlength="6000" data-testid="ccn-problem" :aria-invalid="touched && has('problem') ? 'true' : 'false'" :placeholder="t('codeChanges.new.problemPh', 'What a person sees today, and what they should see. The files and the behaviour, not the whole design.')" />
            <small>{{ d.problem.length }}/6000</small></label>
        </template>

        <template v-else-if="step === 'files'">
          <h2>{{ t('codeChanges.new.s2', 'Which files?') }}</h2>
          <p class="ccn-note">{{ t('codeChanges.new.filesNote', 'Files or folders in the console (everything under its src folder). Each path is checked the way the registry will check it.') }}</p>
          <div class="ccn-pick">
            <label class="ccn-f"><span>{{ t('codeChanges.new.pathLabel', 'Add a path') }}</span>
              <div class="ccn-addrow">
                <input v-model="typed" class="ccn-in mono" spellcheck="false" autocapitalize="off" data-testid="ccn-path-input" :placeholder="t('codeChanges.new.pathPh', 'views/GuildBoard.vue')" aria-describedby="ccn-sug" @keydown.enter.prevent="add(typed)" />
                <button type="button" class="ccn-btn" data-testid="ccn-add" :disabled="!typed.trim()" @click="add(typed)">{{ t('codeChanges.new.add', 'Add') }}</button>
              </div></label>
            <ul v-if="sugg.length" id="ccn-sug" class="ccn-sugg" data-testid="ccn-suggestions" :aria-label="t('codeChanges.new.suggestions', 'Paths in the console')">
              <li v-for="x in sugg" :key="x"><button type="button" class="ccn-sug" data-testid="ccn-suggest" @click="add(x)"><code>{{ x }}</code></button></li>
            </ul>
          </div>
          <ul v-if="rows.length" class="ccn-paths" data-testid="ccn-paths">
            <li v-for="r in rows" :key="r.path" class="ccn-path" :data-status="r.status" data-testid="ccn-path-row">
              <Icon :name="r.status === 'refused' ? 'mdi:close-circle' : r.status === 'sensitive' ? 'mdi:alert-circle-outline' : 'mdi:check-circle'" />
              <div class="ccn-path-main"><code :title="r.path">{{ shortPath(r.path) }}</code><span class="ccn-path-s">{{ r.sentence }}</span></div>
              <button type="button" class="ccn-x" :aria-label="tp('codeChanges.new.remove', 'Remove {p}', { p: shortPath(r.path) })" data-testid="ccn-path-remove" @click="remove(r.path)"><Icon name="mdi:close" /></button>
            </li>
          </ul>
          <p v-else class="ccn-note" data-testid="ccn-no-paths">{{ t('codeChanges.new.noPaths', 'No path yet. Type a file name; the console\'s files are suggested as you type.') }}</p>
          <p v-if="sensitive" class="ccn-callout warn" data-testid="ccn-sensitive-needs"><Icon name="mdi:shield-check" /> {{ lineTarget ? t('contributions.propose.sensitive', 'A sensitive path (auth, admin, money or federation trust) needs two approving reviews; the line\'s own ballot rule then decides.') : sensitiveNeeds(tr) }}</p>
        </template>

        <template v-else-if="step === 'how'">
          <h2>{{ t('codeChanges.new.s3', 'How does it get written?') }}</h2>
          <div class="ccn-modes" role="radiogroup" :aria-label="t('codeChanges.new.modeAria', 'How the code gets written')">
            <label class="ccn-mode" :class="{ on: d.mode === 'bounty' }"><input v-model="d.mode" type="radio" value="bounty" data-testid="ccn-mode-bounty" />
              <b>{{ t('codeChanges.new.bounty', 'A bounty') }}</b>
              <span>{{ t('codeChanges.new.bountyBody', 'Someone writes it. The Guild holds the amount from the start, pays it when the merge is recorded, and returns it if the ballot fails, the maintainer vetoes or you withdraw.') }}</span></label>
            <label class="ccn-mode" :class="{ on: d.mode === 'branch' }"><input v-model="d.mode" type="radio" value="branch" data-testid="ccn-mode-branch" />
              <b>{{ t('codeChanges.new.branch', 'A branch') }}</b>
              <span>{{ t('codeChanges.new.branchBody', 'The code is written. Name the branch and the exact commit: the checker reads that commit, and the members vote on it.') }}</span></label>
          </div>
          <label v-if="d.mode === 'bounty'" class="ccn-f"><span>{{ t('codeChanges.new.amount', 'Bounty') }}</span>
            <input v-model="d.bounty" class="ccn-in mono" inputmode="decimal" data-testid="ccn-bounty" :aria-invalid="touched && has('bounty') ? 'true' : 'false'" placeholder="5" />
            <small>{{ t('codeChanges.new.amountNote', 'In this registry\'s unit. Held by the Guild; a bounty pays someone else\'s work, so it cannot pay your own agents.') }}</small></label>
          <template v-else>
            <label class="ccn-f"><span>{{ t('codeChanges.new.branchName', 'Branch') }}</span>
              <input v-model="d.branch" class="ccn-in mono" maxlength="200" spellcheck="false" data-testid="ccn-branch" :aria-invalid="touched && has('branch') ? 'true' : 'false'" placeholder="fix/order-payee" /></label>
            <label class="ccn-f"><span>{{ t('codeChanges.new.commitLabel', 'Commit (the full id)') }}</span>
              <input v-model="d.commit" class="ccn-in mono" maxlength="64" spellcheck="false" data-testid="ccn-commit" :aria-invalid="touched && has('commit') ? 'true' : 'false'" placeholder="0123456789abcdef0123456789abcdef01234567" />
              <small :class="{ bad: d.commit && !commitOk }" data-testid="ccn-commit-note">{{ d.commit ? (commitOk ? t('codeChanges.new.commitOk', 'A full commit id.') : t('codeChanges.new.commitBad', 'Not a full commit id: 40 hexadecimal characters.')) : t('codeChanges.new.commitHint', '40 hexadecimal characters: git rev-parse HEAD') }}</small></label>
          </template>
        </template>

        <template v-else>
          <h2>{{ t('codeChanges.new.s4', 'Check and propose') }}</h2>
          <dl class="ccn-sum" data-testid="ccn-summary">
            <dt>{{ t('codeChanges.new.titleLabel', 'Title') }}</dt><dd>{{ d.title }}</dd>
            <dt>{{ t('codeChanges.new.problemLabel', 'The problem') }}</dt><dd class="pre">{{ d.problem }}</dd>
            <dt>{{ t('codeChanges.paths', 'Paths') }}</dt><dd><code v-for="p in d.paths" :key="p">{{ shortPath(p) }}</code></dd>
            <dt>{{ d.mode === 'bounty' ? t('codeChanges.new.bounty', 'A bounty') : t('codeChanges.new.branch', 'A branch') }}</dt>
            <dd><template v-if="d.mode === 'bounty'">{{ d.bounty }}</template><template v-else><code>{{ d.branch }}</code> <code>{{ d.commit.slice(0, 12) }}</code></template></dd>
          </dl>
          <p class="ccn-licence" data-testid="ccn-licence">{{ t('codeChanges.rule.terms', 'A contribution is offered under the project\'s licences.') }} <a :href="safeExternalUrl(LICENCE_URL)" target="_blank" rel="noopener noreferrer">{{ t('codeChanges.rule.termsLink', 'Read them') }}</a></p>
          <p v-if="repoBlock" class="ccn-repo-needed" data-testid="ccn-repo-needed"><Icon name="mdi:lock" /> {{ repoNeededWords }}</p>
          <RepoAccountLink v-if="repo?.enabled" :status="repo" @linked="loadRepo" />
          <p v-if="submitError" class="ccn-error" role="alert" data-testid="ccn-error">{{ submitError }}</p>
        </template>

        <ul v-if="touched && shown.length" class="ccn-problems" role="alert" data-testid="ccn-problems"><li v-for="p in shown" :key="p.field + p.sentence">{{ p.sentence }}</li></ul>

        <div class="ccn-foot">
          <button v-if="stepIndex > 0" type="button" class="ccn-btn" data-testid="ccn-back-step" @click="back">{{ t('codeChanges.new.prev', 'Back') }}</button>
          <button v-if="step !== 'review'" type="button" class="ccn-btn primary" data-testid="ccn-next" @click="next">{{ t('codeChanges.new.next', 'Next') }}</button>
          <button v-else type="button" class="ccn-btn primary" data-testid="ccn-submit" :disabled="busy || !canPropose || !!repoBlock" @click="submit">{{ busy ? t('codeChanges.new.sending', 'Proposing…') : t('codeChanges.propose.submit', 'Propose') }}</button>
        </div>
      </section>

      <aside class="ccn-card ccn-aside" data-testid="ccn-after">
        <h3>{{ t('codeChanges.new.after', 'What happens next') }}</h3>
        <ol>
          <li>{{ d.mode === 'bounty' ? t('codeChanges.new.a1b', 'The Guild holds the bounty and posts an order. A worker bids and delivers the code with its tests.') : t('codeChanges.new.a1', 'The checker reads your commit: CI green, only these paths, no secret.') }}</li>
          <template v-if="lineTarget">
            <li>{{ d.mode === 'bounty' ? t('codeChanges.new.a2b', 'The checker reads the delivered commit and signs.') : t('contributions.propose.a2', 'Members of the organization who did not write it review the commit.') }}</li>
            <li>{{ d.mode === 'bounty' ? t('contributions.propose.a3b', 'Members of the organization review it; then the line\'s deciders vote.') : t('contributions.propose.a3', 'You open the line\'s ballot; its deciders vote (the organization\'s owners and admins and the deciding team\'s leads).') }}</li>
            <li>{{ t('contributions.propose.a4', 'If it passes, the organization\'s owner and the platform maintainer have a veto window; then exactly the voted commit is merged into the line\'s branch.') }}</li>
          </template>
          <template v-else>
          <li>{{ d.mode === 'bounty' ? t('codeChanges.new.a2b', 'The checker reads the delivered commit and signs.') : t('codeChanges.new.a2', 'Members who did not write it review the commit.') }}</li>
          <li>{{ d.mode === 'bounty' ? t('codeChanges.new.a3b', 'Members review it, then vote.') : t('codeChanges.new.a3', 'You open the members\' ballot; the members vote in the Senate.') }}</li>
          <li>{{ t('codeChanges.new.a4', 'If it passes, the maintainer has a veto window; then a session merges exactly the voted commit. It reaches production only through a release.') }}</li>
          </template>
        </ol>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLine, type LineRecord } from '@/services/api/codeDistributions'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import Icon from '@/components/Icon.vue'
import CodeChangesTabs from '@/components/codeChanges/CodeChangesTabs.vue'
import RepoAccountLink from '@/components/codeChanges/RepoAccountLink.vue'
import { getRepoAccount, type RepoAccountStatus } from '@/services/api/repoAccount'
import { repoAccountBlocks } from '@/services/codeChanges/repoAccountGate'
import GovernedElsewhere from '@/components/codeChanges/GovernedElsewhere.vue'
import { authorityView, useCodeAuthority } from '@/services/codeChanges/authority'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { proposeChange, refusalWords } from '@/services/api/codeChanges'
import { sensitiveNeeds, shortPath } from '@/services/codeChanges/flow'
import { checkPaths, isCommitId, REPOSITORY } from '@/services/codeChanges/pathRules'
import { STEPS, bodyFor, emptyDraft, fullPath, pathRows, problemsFor, suggestions, type LineTarget, type StepId, type Tree } from '@/services/codeChanges/propose'
import { useTr } from '@/services/codeChanges/tr'

const LICENCE_URL = 'https://github.com/SecureAgentTools/TheProtocol/blob/main/LICENSING.md'
const { t, tp } = useI18n()
const { authority } = useCodeAuthority()      // V0666: one governing registry: the sentence and no form anywhere else
const authorityView_ = computed(() => authorityView(authority.value))
const tr = useTr()
const router = useRouter()
const route = useRoute()
// V0666 D2: ?line=<slug> proposes into an organization's release line (its code distribution): the line is named in the body and its open paths bound the files
const lineSlug = typeof route.query.line === 'string' ? route.query.line : ''
// V0666 D3: /change in an organization's room opens this page with the room and the title
const roomId = typeof route.query.room === 'string' ? route.query.room.slice(0, 36) : ''
const line = ref<LineRecord | null>(null)
const lineError = ref('')
const lineTarget = computed<LineTarget | null>(() => (line.value ? { slug: String(line.value.slug), open_paths: [...(line.value.open_paths || [])] } : null))
const auth = useAuthStore() as any

const d = reactive(emptyDraft())
// V0666 D3: the title /change was typed with (the person may change it)
if (typeof route.query.title === 'string') d.title = route.query.title.slice(0, 160)
const step = ref<StepId>('what')
const touched = ref(false)
const typed = ref('')
const tree = ref<Tree>({ dirs: [], files: [] })
const busy = ref(false)
const submitError = ref('')

const stepIndex = computed(() => STEPS.indexOf(step.value))
const canPropose = computed(() => !!auth.isAuthenticated && !!auth.activeAgent?.did && (!lineSlug || !!line.value))
const current = computed(() => problemsFor(step.value, d, tr, lineTarget.value))
const has = (f: string) => current.value.some((p) => p.field === f)
const rows = computed(() => pathRows(d.paths, tr, lineTarget.value))
/** What the red list says: a path problem a row above already says in its own words is not said twice. */
const shown = computed(() => current.value.filter((p) => !(step.value === 'files' && p.field === 'paths' && rows.value.some((r) => r.status === 'refused' && r.sentence === p.sentence))))
const sensitive = computed(() => checkPaths(REPOSITORY, d.paths).sensitive || d.paths.some((p) => pathRows([p], tr)[0]?.status === 'sensitive'))
const sugg = computed(() => suggestions(typed.value, tree.value, d.paths))
const commitOk = computed(() => isCommitId(d.commit.trim()))
const stepTitle = (s: StepId) => ({ what: t('codeChanges.new.p1', 'The problem'), files: t('codeChanges.new.p2', 'The files'), how: t('codeChanges.new.p3', 'How'), review: t('codeChanges.new.p4', 'Propose') } as Record<StepId, string>)[s]

function add(p: string) {
  const full = fullPath(p)
  if (!full || d.paths.includes(full)) { typed.value = ''; return }
  d.paths.push(full)
  typed.value = ''
}
const remove = (p: string) => { d.paths = d.paths.filter((x) => x !== p) }
function go(s: StepId) { touched.value = false; step.value = s }
function next() {
  touched.value = true
  if (current.value.length) return
  touched.value = false
  step.value = STEPS[Math.min(stepIndex.value + 1, STEPS.length - 1)]
}
function back() { touched.value = false; step.value = STEPS[Math.max(stepIndex.value - 1, 0)] }

// V0667: with repository accounts on, a code change needs the developer's linked, active account (the registry's 409 repo_account_required otherwise). A status
// that could not be read greys nothing: the registry decides at the press and its sentence is shown. A visitor is never asked.
const repo = ref<RepoAccountStatus | null>(null)
const repoBlock = computed(() => repoAccountBlocks(repo.value))
const repoNeededWords = computed(() => (repoBlock.value === 'paused'
  ? t('codeChanges.repo.neededPaused', 'Your repository account is paused while your developer account is suspended, so you cannot propose now.')
  : repoBlock.value === 'closed'
    ? t('codeChanges.repo.neededClosed', 'Your repository account is closed, so you cannot propose.')
    : t('codeChanges.repo.needed', 'A code change needs your repository account on the code host: link it below, then propose.')))
async function loadRepo() {
  if (!auth.isAuthenticated) return
  try { repo.value = await getRepoAccount() } catch { repo.value = null }
}

async function submit() {
  touched.value = true
  if (current.value.length) return
  busy.value = true; submitError.value = ''
  try {
    const rec = await proposeChange(bodyFor(d, lineTarget.value, roomId || null) as any)
    void router.push({ name: 'code-change', params: { id: String(rec.id) } })
  } catch (e) {
    submitError.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.'))
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  void loadRepo()
  if (lineSlug) {
    const cfg = useRegistryConfig() as any
    await cfg.load?.()
    if (cfg.codeDistributionsEnabled?.value !== true) lineError.value = t('contributions.off', 'Code distributions are off on this registry.')
    else {
      try { line.value = await getLine(lineSlug) } catch (e) { lineError.value = refusalWords(e, t('contributions.propose.noLine', 'That release line could not be read.')) }
    }
  }
  try { tree.value = ((await import('@/data/codeChanges/consoleTree.generated.json')) as any).default } catch { /* no suggestions: a typed path still works */ }
})
</script>

<style scoped>
.ccn { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.ccn > * { min-width: 0; }
.ccn-back { justify-self: start; font: 600 .74rem var(--mono); color: var(--cyan); text-decoration: none; }
.ccn-hero { display: grid; gap: .55rem; justify-items: start; }
.ccn-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.ccn-hero h1 { margin: 0; font-size: 1.8rem; font-weight: 300; letter-spacing: -.01em; }
.ccn-lede { margin: 0; color: var(--muted); font-size: .9rem; max-width: 44rem; line-height: 1.55; }
.ccn-signin { margin: 0; display: flex; gap: .5rem; align-items: flex-start; font-size: .82rem; color: #fcd34d; border: 1px solid rgba(245, 158, 11, .35); background: rgba(245, 158, 11, .05); border-radius: 8px; padding: .55rem .8rem; }
.ccn-signin :deep(svg) { width: 1rem; height: 1rem; flex: none; margin-top: 2px; }
.ccn-pills { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: .5rem; }
.ccn-pill { display: inline-flex; align-items: center; gap: .55rem; min-height: 40px; padding: 0 14px 0 8px; border-radius: 999px; border: 1px solid rgba(var(--cyan-rgb), .22); background: none; color: var(--muted); font: inherit; font-size: .8rem; cursor: pointer; }
.ccn-pill:disabled { cursor: default; opacity: .55; }
.ccn-n { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font: 600 .72rem var(--mono); border: 1px solid rgba(var(--cyan-rgb), .3); }
.ccn-pill.done .ccn-n { color: var(--cyan); border-color: var(--cyan); }
.ccn-pill.on { color: #04141a; background: var(--cyan); border-color: transparent; font-weight: 600; }
.ccn-pill.on .ccn-n { border-color: rgba(4, 20, 26, .4); }
.ccn-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 1.1rem; align-items: start; }
.ccn-card, .ccn-note, .ccn-path-s, .ccn-problems, .ccn-error { overflow-wrap: anywhere; }
.ccn-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.2rem 1.3rem; display: grid; gap: .9rem; min-width: 0; align-content: start; }
.ccn-card h2 { margin: 0; font-size: 1.1rem; font-weight: 500; }
.ccn-card h3 { margin: 0; font: 700 11px/1.2 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.ccn-note { margin: 0; font-size: .82rem; color: var(--muted); line-height: 1.55; }
.ccn-f { display: grid; gap: .35rem; }
.ccn-f > span { font: 600 .76rem var(--mono); color: #cbd5e1; }
.ccn-f small { font-size: .72rem; color: var(--muted); line-height: 1.45; } .ccn-f small.bad { color: #fca5a5; }
.ccn-in { background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; padding: 8px 11px; color: var(--bright); font: inherit; font-size: .88rem; width: 100%; min-height: 42px; }
.ccn-in.mono { font-family: var(--mono); font-size: .82rem; }
.ccn-in:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.ccn-in[aria-invalid='true'] { border-color: rgba(248, 113, 113, .6); }
.ccn-addrow { display: flex; gap: .5rem; min-width: 0; }
.ccn-addrow .ccn-in { min-width: 0; flex: 1; }
.ccn-pick { min-width: 0; }
.ccn-sugg { list-style: none; margin: .4rem 0 0; padding: 0; display: grid; gap: 2px; border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 8px; overflow: hidden; }
.ccn-sug { width: 100%; text-align: left; min-height: 38px; padding: 0 12px; background: rgba(0,0,0,.25); border: 0; color: var(--bright); cursor: pointer; }
.ccn-sug:hover, .ccn-sug:focus-visible { background: rgba(var(--cyan-rgb), .12); }
.ccn-sug code, .ccn-path code, .ccn-sum code { font: .76rem var(--mono); overflow-wrap: anywhere; }
.ccn-paths { list-style: none; margin: 0; padding: 0; display: grid; gap: .5rem; }
.ccn-path { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: .6rem; align-items: start; padding: .6rem .7rem; border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; }
.ccn-path :deep(svg) { width: 1.05rem; height: 1.05rem; margin-top: 2px; color: #34d399; }
.ccn-path[data-status='sensitive'] { border-color: rgba(245, 158, 11, .4); } .ccn-path[data-status='sensitive'] :deep(svg) { color: #fcd34d; }
.ccn-path[data-status='refused'] { border-color: rgba(248, 113, 113, .45); } .ccn-path[data-status='refused'] :deep(svg) { color: #f87171; }
.ccn-path-main { display: grid; gap: .2rem; min-width: 0; }
.ccn-path-s { font-size: .76rem; color: var(--muted); line-height: 1.45; } .ccn-path[data-status='refused'] .ccn-path-s { color: #fca5a5; }
.ccn-x { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .18); background: none; color: var(--muted); cursor: pointer; }
.ccn-x:hover, .ccn-x:focus-visible { color: var(--bright); border-color: rgba(var(--cyan-rgb), .5); }
.ccn-x :deep(svg) { width: 1rem; height: 1rem; }
.ccn-callout { margin: 0; display: flex; gap: .55rem; align-items: flex-start; font-size: .8rem; line-height: 1.5; padding: .65rem .8rem; border-radius: 8px; }
.ccn-callout.warn { color: #fcd34d; border: 1px solid rgba(245, 158, 11, .35); background: rgba(245, 158, 11, .05); }
.ccn-callout :deep(svg) { width: 1rem; height: 1rem; flex: none; margin-top: 2px; }
.ccn-modes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .7rem; }
.ccn-mode { display: grid; gap: .35rem; padding: .85rem 1rem; border: 1px solid rgba(var(--cyan-rgb), .2); border-radius: 10px; cursor: pointer; font-size: .8rem; line-height: 1.5; color: #aab4c0; }
.ccn-mode input { position: absolute; opacity: 0; pointer-events: none; }
.ccn-mode b { color: var(--bright); font-size: .92rem; font-weight: 500; }
.ccn-mode.on { border-color: var(--cyan); background: rgba(var(--cyan-rgb), .07); }
.ccn-mode:focus-within { box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .2); }
.ccn-sum { margin: 0; display: grid; grid-template-columns: 7rem minmax(0, 1fr); gap: .5rem .9rem; font-size: .85rem; }
.ccn-sum dt { color: var(--muted); } .ccn-sum dd { margin: 0; overflow-wrap: anywhere; } .ccn-sum dd.pre { white-space: pre-wrap; }
.ccn-sum dd code { display: inline-block; margin: 0 .35rem .25rem 0; padding: 2px 7px; border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 5px; background: rgba(0,0,0,.3); }
.ccn-licence { margin: 0; font-size: .8rem; color: #aab4c0; } .ccn-licence a { color: var(--cyan); }
.ccn-error { margin: 0; font-size: .85rem; color: #fca5a5; overflow-wrap: anywhere; }
.ccn-repo-needed { margin: 0; display: flex; gap: .4rem; align-items: flex-start; font-size: .88rem; color: #e0a040; line-height: 1.5; }
.ccn-problems { margin: 0; padding: .6rem .9rem .6rem 1.6rem; list-style: disc; font-size: .8rem; color: #fca5a5; border: 1px solid rgba(248, 113, 113, .35); border-radius: 8px; display: grid; gap: .25rem; }
.ccn-foot { display: flex; flex-wrap: wrap; gap: .6rem; justify-content: flex-end; border-top: 1px solid rgba(255,255,255,.07); padding-top: .9rem; }
.ccn-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 42px; padding: 0 20px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .86rem; cursor: pointer; }
.ccn-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.ccn-btn:disabled { opacity: .45; cursor: default; }
.ccn-line { margin: 0; font-size: .86rem; color: var(--cyan, #00d2d2); line-height: 1.5; max-width: 50rem; }
.ccn-line.bad { color: #fca5a5; }
.ccn-aside ol { margin: 0; padding-left: 1.2rem; list-style: decimal; display: grid; gap: .6rem; font-size: .82rem; line-height: 1.55; color: #aab4c0; }
@media (max-width: 900px) { .ccn-grid { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 640px) { .ccn { padding: 1rem .8rem 2.5rem; } .ccn-hero h1 { font-size: 1.45rem; } .ccn-card { padding: 1rem; } .ccn-modes { grid-template-columns: 1fr; } .ccn-sum { grid-template-columns: 1fr; gap: .1rem; } .ccn-sum dd { margin-bottom: .5rem; } .ccn-foot .ccn-btn { flex: 1 1 8rem; } .ccn-pill .ccn-pl { display: none; } .ccn-pill.on .ccn-pl { display: inline; } }
</style>
