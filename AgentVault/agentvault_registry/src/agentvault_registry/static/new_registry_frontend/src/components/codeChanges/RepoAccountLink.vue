<!--
  V0667 (order gwo_662c03447bcd627afa4a11e5; room seq 5040 "the flow should be no automatically triggered. Maybe a button on code changes view that links your
  account", session-lead seq 5047 and 5097): the developer's repository account on the public code host. The parent reads the status (GET /developers/me/repo-account)
  and passes it; this shows one button while there is no account. The press shows what the account shares first, then a username and a confirmation; only "Create the
  account" makes it (POST, confirm: true). Its answer, the one-time password, where to sign in and the git line for the author e-mail, is shown once and forgotten on
  Done. A refusal is the registry's sentence. Linked, it names the account and its state; a leg that waits says its reason and next try.
-->
<template>
  <div v-if="status && status.enabled" class="ra" data-testid="ra-root">
    <div v-if="created" class="ra-panel" data-testid="ra-panel" role="region" :aria-label="t('codeChanges.repo.createdAria', 'Your repository account')">
      <h3>{{ t('codeChanges.repo.createdTitle', 'Your repository account is ready') }}</h3>
      <p class="ra-warn" data-testid="ra-once"><Icon name="mdi:alert" /> {{ t('codeChanges.repo.once', 'The password below is shown once and stored nowhere: change it at your first sign-in.') }}</p>
      <dl class="ra-facts">
        <dt>{{ t('codeChanges.repo.usernameLabel', 'Username') }}</dt><dd><code>{{ created.username }}</code></dd>
        <dt>{{ t('codeChanges.repo.passwordLabel', 'One-time password') }}</dt><dd><code data-testid="ra-password">{{ created.password }}</code></dd>
        <dt>{{ t('codeChanges.repo.signInLabel', 'Sign in') }}</dt><dd><a :href="safeExternalUrl(created.sign_in)" target="_blank" rel="noopener noreferrer" data-testid="ra-signin">{{ created.sign_in }}</a></dd>
      </dl>
      <p>{{ t('codeChanges.repo.gitNote', 'Before you push, set your git to the account\'s address, in the clone you push from:') }}</p>
      <pre class="ra-code" data-testid="ra-git">{{ created.git_config }}</pre>
      <button type="button" class="ra-btn primary" data-testid="ra-done" @click="done">{{ t('codeChanges.repo.done', 'Done') }}</button>
    </div>

    <template v-else-if="status.linked">
      <p class="ra-linked" data-testid="ra-linked"><Icon name="mdi:source-branch" />
        {{ t('codeChanges.repo.linkedAs', 'Repository account') }} <a :href="safeExternalUrl(profileUrl)" target="_blank" rel="noopener noreferrer">{{ status.username }}</a></p>
      <p v-if="status.state === 'paused'" class="ra-state" data-testid="ra-state">{{ t('codeChanges.repo.paused', 'Your repository account is paused while your developer account is suspended: it cannot sign in or push; what you published stays readable.') }}</p>
      <p v-else-if="status.state === 'closed'" class="ra-state" data-testid="ra-state">{{ t('codeChanges.repo.closed', 'Your repository account is closed: your developer account was deleted. Contributions already made stay in the history.') }}</p>
      <p v-if="status.pending" class="ra-state" data-testid="ra-pending">{{ pendingWords }}</p>
    </template>

    <template v-else>
      <button v-if="!open" type="button" class="ra-btn" data-testid="ra-open" @click="open = true">{{ t('codeChanges.repo.open', 'Link repository account') }}</button>
      <div v-else class="ra-panel" data-testid="ra-panel" role="region" :aria-label="t('codeChanges.repo.panelAria', 'Link a repository account')">
        <h3>{{ t('codeChanges.repo.sharesTitle', 'What linking means') }}</h3>
        <ul class="ra-shares" data-testid="ra-shares">
          <li v-for="(s, i) in status.shares" :key="i" data-testid="ra-share">{{ s }}</li>
        </ul>
        <label class="ra-field">
          <span>{{ t('codeChanges.repo.usernameLabel', 'Username') }}</span>
          <input v-model.trim="username" type="text" autocomplete="off" spellcheck="false" maxlength="39" data-testid="ra-username" :aria-invalid="usernameBad ? 'true' : 'false'" />
        </label>
        <p v-if="usernameBad" class="ra-note" data-testid="ra-username-note">{{ t('codeChanges.repo.usernameRule', 'A username is 3 to 39 lowercase letters, digits and single hyphens, starting and ending with a letter or digit.') }}</p>
        <label class="ra-check">
          <input v-model="confirmed" type="checkbox" data-testid="ra-confirm" />
          <span>{{ t('codeChanges.repo.confirm', 'I have read what linking means and accept the Terms. Create the account for me.') }}</span>
        </label>
        <p class="ra-note" data-testid="ra-terms">{{ tp('codeChanges.repo.termsLine', 'Creating the account accepts the Terms, version {v}: the code host is their § 5.12.', { v: status.terms_version || '' }) }}
          <RouterLink :to="{ name: 'legal', params: { page: 'terms' } }" target="_blank" rel="noopener">{{ t('codeChanges.repo.termsLink', 'Read the Terms') }}</RouterLink></p>
        <p v-if="error" class="ra-error" role="alert" data-testid="ra-error">{{ error }}</p>
        <div class="ra-actions">
          <button type="button" class="ra-btn primary" data-testid="ra-create" :disabled="!canCreate" @click="create">{{ busy ? t('codeChanges.repo.creating', 'Creating…') : t('codeChanges.repo.create', 'Create the account') }}</button>
          <button type="button" class="ra-btn" data-testid="ra-cancel" :disabled="busy" @click="cancel">{{ t('codeChanges.repo.cancel', 'Cancel') }}</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { linkRepoAccount, type RepoAccountLinked, type RepoAccountStatus } from '@/services/api/repoAccount'
import { refusalWords } from '@/services/api/codeChanges'
import { safeExternalUrl } from '@/utils/safeUrl'

// V0667 the passport: a contributor from another registry links through their home (services/api/codePassport.linkPassportRepo); a member links here
const props = defineProps<{ status: RepoAccountStatus | null; link?: (username: string, termsVersion: string) => Promise<RepoAccountLinked> }>()
const emit = defineEmits<{ (e: 'linked', v: RepoAccountLinked): void }>()
const { t, tp } = useI18n()

// the registry's rule (services/repo_accounts._USERNAME); the registry decides again, and refuses reserved names itself
const USERNAME = /^[a-z0-9](?:[a-z0-9]|-(?!-)){1,37}[a-z0-9]$/
const open = ref(false)
const username = ref('')
const confirmed = ref(false)
const busy = ref(false)
const error = ref('')
const created = ref<RepoAccountLinked | null>(null)

const usernameBad = computed(() => username.value !== '' && !USERNAME.test(username.value))
const canCreate = computed(() => !busy.value && confirmed.value && USERNAME.test(username.value))
const profileUrl = computed(() => `${String(props.status?.host || '').replace(/\/+$/, '')}/${encodeURIComponent(props.status?.username || '')}`)
const when = (iso: string | null) => (iso ? iso.replace('T', ' ').slice(0, 16) + ' UTC' : '')
const pendingWords = computed(() => {
  const p = props.status?.pending
  if (!p) return ''
  const what = p.op === 'pause' ? t('codeChanges.repo.opPause', 'Pausing the account') : p.op === 'restore' ? t('codeChanges.repo.opRestore', 'Restoring the account') : t('codeChanges.repo.opClose', 'Closing the account')
  if (!p.last_error) return tp('codeChanges.repo.pendingFirst', '{what}: waiting for the code host.', { what })
  return p.stuck
    ? tp('codeChanges.repo.pendingStuck', '{what} did not land after {n} tries ({why}); an administrator has been told.', { what, n: p.attempts, why: p.last_error })
    : tp('codeChanges.repo.pendingRetry', '{what} did not land yet ({why}); the next try is at {at}.', { what, why: p.last_error, at: when(p.next_attempt_at) })
})

async function create() {
  if (!canCreate.value) return
  busy.value = true
  error.value = ''
  try {
    created.value = await (props.link || linkRepoAccount)(username.value, props.status?.terms_version || '')
    emit('linked', created.value)
  } catch (e: any) {
    error.value = refusalWords(e, t('codeChanges.repo.failed', 'The account could not be created. Nothing was made; try again.'))
  } finally {
    busy.value = false
  }
}
function cancel() { open.value = false; error.value = ''; confirmed.value = false }
// the one-time password leaves the page with the panel
function done() { created.value = null; open.value = false; username.value = ''; confirmed.value = false }
</script>

<style scoped>
.ra { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace; display: grid; gap: .5rem; min-width: 0; }
.ra-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 18px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: 500 .9rem/1 inherit; cursor: pointer; }
.ra-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.ra-btn:disabled { opacity: .45; cursor: not-allowed; }
.ra-btn:not(:disabled):hover, .ra-btn:focus-visible { filter: brightness(1.12); }
.ra-panel { display: grid; gap: .7rem; padding: 1rem 1.1rem; border: 1px solid rgba(var(--cyan-rgb), .22); border-radius: 12px; background: rgba(var(--cyan-rgb), .04); max-width: 44rem; }
.ra-panel h3 { margin: 0; font-size: 1rem; font-weight: 500; }
.ra-shares { margin: 0; padding-left: 1.1rem; display: grid; gap: .35rem; color: var(--muted); font-size: .88rem; line-height: 1.5; }
.ra-field { display: grid; gap: .3rem; font-size: .85rem; }
.ra-field input { min-height: 38px; padding: 0 .7rem; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .25); background: rgba(0, 0, 0, .25); color: inherit; font: 400 .92rem var(--mono); }
.ra-field input[aria-invalid="true"] { border-color: #e0a040; }
.ra-check { display: flex; gap: .5rem; align-items: flex-start; font-size: .88rem; }
.ra-note, .ra-state { margin: 0; color: var(--muted); font-size: .85rem; line-height: 1.5; }
.ra-error { margin: 0; color: #ff8a80; font-size: .88rem; }
.ra-warn { margin: 0; color: #e0a040; font-size: .88rem; display: flex; gap: .4rem; align-items: center; }
.ra-actions { display: flex; flex-wrap: wrap; gap: .6rem; }
.ra-facts { display: grid; grid-template-columns: max-content 1fr; gap: .35rem .9rem; margin: 0; font-size: .88rem; }
.ra-facts dt { color: var(--muted); }
.ra-facts dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.ra-code { margin: 0; padding: .6rem .8rem; border-radius: 8px; background: rgba(0, 0, 0, .3); font: 400 .85rem var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.ra-linked { margin: 0; display: flex; gap: .4rem; align-items: center; font-size: .9rem; }
.ra-linked a { color: var(--cyan); }
</style>
