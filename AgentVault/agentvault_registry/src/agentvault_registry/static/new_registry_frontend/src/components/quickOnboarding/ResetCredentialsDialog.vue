<!-- RESET AN AGENT'S CREDENTIALS (quick onboarding, 2026-10-09). The rail is POST /onboard/agents/{did}/reset-credentials
     with the developer's ACCOUNT password; it issues a new client ID AND a new client secret, and the old pair stops
     working at once. A developer with a second factor gets HTTP 401 {error:'step_up_required', step_up:{...}}: the
     dialog steps aside for StepUpConfirm (the same challenge the phone approves) and resends with the proof. Every other
     refusal is said here, in the dialog, never as a global error toast (agentApi.resetCredentials names them expected;
     the client's own "Rate Limited" warning on a 429 is the one toast that still shows, beside the dialog's sentence).
     The password is kept only while the reset is under way: through a step-up round, because the proof is resent with
     it, and never after: it is cleared when the reset succeeds, when it is refused, and when the dialog closes.
     The new pair is written where the console keeps agents' keys, exactly as My Agents writes it, and the acting agent
     signs in again with it when it is the one reset. The new secret is shown only here, once: Esc and a click beside
     the dialog do not close it then (Done and the close button do), and focus lands on the sentence saying so. -->
<template>
  <Teleport to="body">
    <div v-if="show && agent && phase !== 'stepup'" class="qo-dlg-overlay" @click.self="onBackdrop">
      <div ref="panel" class="qo-dlg" role="dialog" aria-modal="true" :aria-labelledby="`${uid}-title ${uid}-who`" :aria-describedby="`${uid}-desc`"
           data-testid="qo-reset-dialog" :data-phase="phase" tabindex="-1">
        <header class="qo-dlg__head">
          <span class="qo-dlg__badge" aria-hidden="true"><Icon :name="phase === 'done' ? 'mdi:check-circle' : 'mdi:key-variant'" /></span>
          <div class="qo-dlg__heading">
            <h2 :id="`${uid}-title`" class="qo-dlg__title">
              {{ phase === 'done' ? t('quickOnboarding.reset.doneTitle', 'New credentials issued') : t('quickOnboarding.reset.title', 'Reset credentials') }}
            </h2>
            <!-- part of the dialog's name: the comma keeps the name and the DID apart for a reader (the flex gap only
                 parts them on screen, and the compiler drops the newline between the two) -->
            <p :id="`${uid}-who`" class="qo-dlg__who">
              <span class="qo-dlg__name">{{ agent.name || t('quickOnboarding.agents.unnamed', 'Unnamed agent') }}</span><span class="sr-only">{{ ', ' }}</span>
              <code class="qo-dlg__did">{{ shortDid(agent.did) }}</code>
            </p>
          </div>
          <button type="button" class="qo-dlg__close" :aria-label="t('quickOnboarding.reset.close', 'Close')" :disabled="busy"
                  data-testid="qo-reset-close" @click="closeDialog">
            <Icon name="mdi:close" />
          </button>
        </header>

        <form v-if="phase !== 'done'" class="qo-dlg__body" novalidate @submit.prevent="submit">
          <div :id="`${uid}-desc`" class="qo-dlg__effect">
            <p>{{ t('quickOnboarding.reset.effect1', 'A reset issues a new client ID and a new client secret. The current pair stops working at once: every program that signs in as this agent needs the new one.') }}</p>
            <p>{{ t('quickOnboarding.reset.effect2', 'Sessions it already opened run until they expire. Nothing else about the agent changes: its DID, its card and its balance stay as they are.') }}</p>
            <p>{{ t('quickOnboarding.reset.effect3', 'The registry allows three reset attempts an hour from one address.') }}</p>
          </div>
          <div class="qo-dlg__field">
            <label class="qo-dlg__label" :for="`${uid}-pw`">{{ t('quickOnboarding.reset.password', 'Your account password') }}</label>
            <input :id="`${uid}-pw`" ref="pwInput" v-model="password" class="qo-dlg__input" type="password"
                   autocomplete="current-password" spellcheck="false" :disabled="busy" :aria-invalid="errorKind === 'wrong_password' ? 'true' : 'false'"
                   :aria-describedby="describedBy" data-testid="qo-reset-password" />
            <p :id="`${uid}-hint`" class="qo-dlg__hint">{{ t('quickOnboarding.reset.passwordHint', 'It confirms that you are the one asking. The dialog forgets it when the reset ends or you close it.') }}</p>
          </div>
          <p v-if="error" :id="`${uid}-err`" class="qo-dlg__error" role="alert" data-testid="qo-reset-error" :data-kind="errorKind">
            <Icon name="mdi:alert-circle-outline" class="qo-dlg__error-icon" />
            <span>{{ error }}</span>
          </p>
          <footer class="qo-dlg__foot">
            <button type="button" class="qo-dlg__btn qo-dlg__btn--ghost" :disabled="busy" data-testid="qo-reset-cancel" @click="closeDialog">
              {{ t('quickOnboarding.reset.cancel', 'Cancel') }}
            </button>
            <button type="submit" class="qo-dlg__btn qo-dlg__btn--warn" :disabled="busy || !password" data-testid="qo-reset-submit"
                    :aria-busy="busy ? 'true' : 'false'">
              <Icon :name="busy ? 'mdi:loading' : 'mdi:key-variant'" class="qo-dlg__btn-icon" :class="{ 'qo-spin': busy }" />
              <span>{{ busy ? t('quickOnboarding.reset.working', 'Resetting…') : t('quickOnboarding.reset.submit', 'Reset credentials') }}</span>
            </button>
          </footer>
        </form>

        <div v-else class="qo-dlg__body" data-testid="qo-reset-done">
          <p :id="`${uid}-desc`" ref="okEl" class="qo-dlg__ok" tabindex="-1" data-testid="qo-reset-ok">
            <Icon name="mdi:check" class="qo-dlg__ok-icon" />
            <span>{{ t('quickOnboarding.reset.doneLead', 'The old pair no longer works. Copy the new secret now; this is the only time it is shown.') }}</span>
          </p>
          <CredentialsBlock v-if="newPair" :client-id="newPair.client_id" :client-secret="newPair.client_secret" />
          <!-- one live region, there from the start, so each step of the re-sign-in is announced -->
          <div class="qo-dlg__notes" role="status">
            <p v-if="reauth === 'busy'" class="qo-dlg__note" data-testid="qo-reset-reauth-busy">
              {{ t('quickOnboarding.reset.reauthBusy', 'The console acts as this agent: it is signing in again with the new pair.') }}
            </p>
            <p v-else-if="reauth === 'failed'" class="qo-dlg__note" data-testid="qo-reset-reauth-failed">
              {{ t('quickOnboarding.reset.reauthFailed', 'The console could not sign in again as this agent with the new pair. Pick it again in the agent switcher.') }}
            </p>
            <p v-else-if="reauth === 'done'" class="qo-dlg__note" data-testid="qo-reset-reauth-done">
              {{ t('quickOnboarding.reset.reauthDone', 'The console acts as this agent and has signed in again with the new pair.') }}
            </p>
          </div>
          <footer class="qo-dlg__foot">
            <button type="button" class="qo-dlg__btn qo-dlg__btn--primary" data-testid="qo-reset-finish" @click="closeDialog">
              {{ t('quickOnboarding.reset.finish', 'Done') }}
            </button>
          </footer>
        </div>
      </div>
    </div>
  </Teleport>
  <StepUpConfirm v-if="show && agent && phase === 'stepup'" :show="true" :challenge="challenge" :busy="busy" :error="stepError"
                 :title="t('quickOnboarding.reset.stepUpTitle', 'Confirm this reset')"
                 :lead="t('quickOnboarding.reset.stepUpLead', 'Your account has a second factor, so a person confirms a credential reset. Approve it on your phone, or enter the code from your authenticator app.')"
                 :denied-text="t('quickOnboarding.reset.stepUpDenied', 'You declined this reset on your phone. Nothing changed.')"
                 :expired-text="t('quickOnboarding.reset.stepUpExpired', 'This confirmation expired. Close it and reset again for a new one.')"
                 @update:show="onStepUpShow" @approved="onApproved" @code="onCode" />
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { computed, nextTick, ref, useId, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import CredentialsBlock from './CredentialsBlock.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'
import { useI18n } from '@/composables/useI18n'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useAuthStore } from '@/stores/auth'
import { agentApi, type ResetCredentialsAnswer, type ResetCredentialsBody } from '@/services/api/agents'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import type { StepUpChallenge } from '@/services/membership/membership'
import { proofWasRefused, resetRefusal, shortDid, type ResetRefusal } from '@/services/quickOnboarding'

const props = defineProps<{
  show: boolean
  agent: { did: string; name?: string | null } | null
}>()
const emit = defineEmits<{
  (e: 'close'): void
  /** the registry issued a new pair (the page reads its list again) */
  (e: 'reset', v: { did: string; client_id: string }): void
}>()

const { t } = useI18n()
const auth = useAuthStore()
const uid = useId()

type Phase = 'ask' | 'stepup' | 'done'
const phase = ref<Phase>('ask')
const password = ref('')
const busy = ref(false)
const error = ref('')
const errorKind = ref<ResetRefusal['kind'] | ''>('')
const challenge = ref<StepUpChallenge | null>(null)
const stepError = ref('')
const newPair = ref<{ client_id: string; client_secret: string } | null>(null)
const reauth = ref<'' | 'busy' | 'done' | 'failed'>('')
/** a re-sign-in answers into the dialog that started it, never into a later opening */
let reauthRun = 0
/** the request in flight: a request that ends after a later one started (Done was pressed during the re-sign-in, the
 *  dialog reopened and sent again) must not touch the later one's busy state */
let sendRun = 0
/** the proof the last request carried: a refused code and a refused approval are told apart */
type Proof = '' | 'code' | 'approval'

const panel = ref<HTMLElement | null>(null)
const pwInput = ref<HTMLInputElement | null>(null)
const okEl = ref<HTMLElement | null>(null)
// the first thing to hold focus: the password while asking; once the new pair is shown, the sentence that says it is
// shown only once (a person reads that before reaching Copy and Done, and a stray Enter cannot close the dialog)
useFocusTrap(panel, {
  activeWhen: computed(() => props.show && !!props.agent && phase.value !== 'stepup'),
  initialFocus: 'input[type="password"], [data-testid="qo-reset-ok"]',
})
const describedBy = computed(() => [`${uid}-hint`, error.value ? `${uid}-err` : ''].filter(Boolean).join(' '))

function resetState() {
  phase.value = 'ask'; password.value = ''; busy.value = false; error.value = ''; errorKind.value = ''
  challenge.value = null; stepError.value = ''; newPair.value = null; reauth.value = ''
  reauthRun++
}
// every opening starts clean, and a closed dialog keeps nothing (the password above all)
/** the control that opened the dialog: focus goes back to it on close, also after a step-up round (the trap that
 *  remembers it on its own is re-armed by that round, by then inside the dialog) */
let opener: HTMLElement | null = null
watch(() => props.show, (v) => {
  resetState()
  if (v && typeof document !== 'undefined') opener = document.activeElement as HTMLElement | null
})
watch(() => props.agent?.did, () => { if (props.show) resetState() })

function closeDialog() {
  if (busy.value) return
  const back = opener
  opener = null
  resetState()
  emit('close')
  void nextTick(() => { if (back && document.body.contains(back)) back.focus() })
}
/** Esc and a click beside the dialog close it while asking; never while the new pair is shown (it is shown only here,
 *  once): then focus goes back to the sentence that says so, inside the dialog. Done and the close button still close. */
function onEscape() {
  if (phase.value === 'done') { okEl.value?.focus(); return }
  closeDialog()
}
function onBackdrop() {
  onEscape()
}

function say(r: ResetRefusal) {
  errorKind.value = r.kind
  switch (r.kind) {
    case 'wrong_password': error.value = t('quickOnboarding.reset.err.password', 'That password is not right.'); break
    case 'not_owner': error.value = t('quickOnboarding.reset.err.notOwner', 'This agent is not yours, so its credentials cannot be reset here.'); break
    case 'not_found': error.value = t('quickOnboarding.reset.err.notFound', 'This agent no longer exists on this registry.'); break
    case 'inactive': error.value = r.message || t('quickOnboarding.reset.err.inactive', 'A suspended or deleted agent cannot have its credentials reset.'); break
    case 'rate_limited': error.value = t('quickOnboarding.reset.err.rateLimited', 'The registry allows three reset attempts an hour from one address, and a wrong password or a confirmation round counts as one. Try again later; nothing changed.'); break
    case 'session': error.value = t('quickOnboarding.reset.err.session', 'Your sign-in could not be confirmed. Sign in again, then retry; nothing changed.'); break
    default: error.value = (r as { message?: string }).message || t('quickOnboarding.reset.err.other', 'The reset did not go through. Nothing changed.')
  }
}

async function send(body: ResetCredentialsBody, proof: Proof = '') {
  const agent = props.agent
  if (!agent || busy.value) return
  const run = ++sendRun
  busy.value = true
  error.value = ''; errorKind.value = ''
  let refocus = false
  try {
    const ans = await agentApi.resetCredentials(agent.did, body)
    await succeeded(agent, ans)
  } catch (e) {
    const r = resetRefusal(e)
    if (r.kind === 'step_up') {
      // a step-up answer to a request that carried a proof means the proof was refused; say which one, in words a
      // person can act on (the registry's reason, "challenge is pending", is about its own bookkeeping)
      const refusedProof = phase.value === 'stepup' && !!proof && proofWasRefused(r.reason)
      challenge.value = r.challenge
      stepError.value = !refusedProof ? ''
        : proof === 'code'
          ? t('quickOnboarding.reset.stepUpBadCode', 'That code was not accepted. Check the code in your authenticator app and try again.')
          : t('quickOnboarding.reset.stepUpBadApproval', 'The approval was not accepted: it expired or was declined. Approve the new request, or enter a code.')
      phase.value = 'stepup'
    } else {
      // the call ended without a reset: the password goes, and the field is where the person acts on the answer
      phase.value = 'ask'; challenge.value = null; stepError.value = ''
      say(r)
      password.value = ''
      refocus = true
    }
  } finally {
    if (run === sendRun) busy.value = false
  }
  // the field was disabled during the call, which sent focus to the page: give it back (after it is enabled again)
  if (refocus && run === sendRun) { await nextTick(); pwInput.value?.focus() }
}

async function succeeded(agent: { did: string; name?: string | null }, ans: ResetCredentialsAnswer) {
  password.value = ''
  // §FEFRAME W1, exactly as My Agents does it: the reset killed the old secret, so the one this browser kept is dead
  // from now on; save the new pair in its place. Minted by THIS console's registry, so local to it: no address.
  try {
    const prev = agentCredentialsStore.getCredentials(agent.did)
    agentCredentialsStore.storeCredentials({
      did: agent.did,
      client_id: ans.client_id,
      client_secret: ans.client_secret,
      name: agent.name || prev?.name,
      humanReadableId: prev?.humanReadableId,
      registry: prev?.registry,
      registry_url: undefined,
    })
  } catch { /* the dialog still shows the pair; saving it is a convenience */ }
  newPair.value = { client_id: ans.client_id, client_secret: ans.client_secret }
  challenge.value = null; stepError.value = ''
  phase.value = 'done'
  emit('reset', { did: agent.did, client_id: ans.client_id })
  // Done answers from now on: the re-sign-in below runs on its own and says how it went
  busy.value = false
  await nextTick()
  okEl.value?.focus()
  // the acting agent was the one reset: sign in again with the new pair (its old secret no longer mints)
  const active = auth.activeAgent as { did?: string } | null
  if (active?.did === agent.did) {
    const run = ++reauthRun
    reauth.value = 'busy'
    let ok = false
    try { ok = await auth.authenticateAsAgent({ ...active, client_id: ans.client_id, client_secret: ans.client_secret }) } catch { ok = false }
    if (run === reauthRun) reauth.value = ok ? 'done' : 'failed'
  }
}

function submit() {
  if (!password.value) {
    errorKind.value = ''
    error.value = t('quickOnboarding.reset.err.empty', 'Enter your account password.')
    return
  }
  void send({ password: password.value })
}

function onApproved(challengeId: string) {
  void send({ password: password.value, challenge_id: challengeId }, 'approval')
}
function onCode(code: string) {
  void send({ password: password.value, totp_code: code, challenge_id: challenge.value?.challengeId }, 'code')
}
async function onStepUpShow(v: boolean) {
  if (v || busy.value) return
  // the person closed the confirmation: nothing was reset, the reset ended; back to the dialog, which says so
  phase.value = 'ask'; challenge.value = null; stepError.value = ''
  password.value = ''
  errorKind.value = 'other'
  error.value = t('quickOnboarding.reset.err.notConfirmed', 'Not confirmed, so nothing changed.')
  await nextTick()
  pwInput.value?.focus()
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => !!(props.show && props.agent && phase.value !== 'stepup'), onEscape)
</script>

<style scoped>
.qo-dlg-overlay {
  position: fixed; inset: 0; z-index: 10100;
  /* teleported to <body>: it takes the console's own face, as the page behind it does (DashboardLayout's shell) */
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  display: flex; align-items: center; justify-content: center; padding: 1rem;
  background: rgba(2, 6, 12, 0.74);
  backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  animation: qo-dlg-fade var(--nc-duration-fast, 200ms) ease-out;
}
.qo-dlg {
  width: 100%; max-width: 34rem; max-height: calc(100vh - 2rem); overflow-y: auto;
  display: flex; flex-direction: column;
  background: linear-gradient(180deg, var(--nc-overlay), var(--nc-surface));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 16px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(var(--nc-primary-rgb), 0.06), 0 0 60px rgba(var(--nc-primary-rgb), 0.08);
  color: var(--nc-text-primary, #e8eaed);
  animation: qo-dlg-rise 260ms cubic-bezier(.2, .7, .3, 1) both;
}
.qo-dlg:focus { outline: none; }
.qo-dlg:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-dlg__head { display: flex; align-items: flex-start; gap: 0.85rem; padding: 1.25rem 1.25rem 0.9rem; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
.qo-dlg__badge {
  flex: 0 0 auto; width: 2.5rem; height: 2.5rem; border-radius: 12px; display: grid; place-items: center; font-size: 1.25rem;
  color: var(--nc-primary-bright, var(--nc-primary));
  background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
}
.qo-dlg__heading { flex: 1 1 auto; min-width: 0; }
.qo-dlg__title { margin: 0; font-size: 1.15rem; font-weight: 700; line-height: 1.25; }
.qo-dlg__who { margin: 0.3rem 0 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.25rem 0.6rem; min-width: 0; }
.qo-dlg__name { font-weight: 600; font-size: 0.9rem; overflow-wrap: anywhere; }
.qo-dlg__did { font-family: 'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, Consolas, monospace; font-size: 0.76rem; color: var(--nc-text-secondary, #9aa0a6); overflow-wrap: anywhere; }
.qo-dlg__close {
  flex: 0 0 auto; width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; cursor: pointer; font-size: 1.05rem;
  color: var(--nc-text-secondary, #9aa0a6); background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08);
}
.qo-dlg__close:hover:not(:disabled) { color: var(--nc-text-primary, #e8eaed); border-color: rgba(255, 255, 255, 0.2); }
.qo-dlg__close:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-dlg__close:disabled { opacity: 0.5; cursor: not-allowed; }
.qo-dlg__body { display: flex; flex-direction: column; gap: 1rem; padding: 1.1rem 1.25rem 1.25rem; }
.qo-dlg__effect { display: flex; flex-direction: column; gap: 0.5rem; font-size: 0.88rem; line-height: 1.55; color: var(--nc-text-secondary, #9aa0a6); }
.qo-dlg__effect p { margin: 0; }
.qo-dlg__field { display: flex; flex-direction: column; gap: 0.4rem; }
.qo-dlg__label { font-size: 0.8rem; font-weight: 600; color: var(--nc-text-primary, #e8eaed); }
.qo-dlg__input {
  width: 100%; box-sizing: border-box; font: inherit; font-size: 16px; line-height: 1.4;
  padding: 0.7rem 0.85rem; border-radius: 10px; border: 1px solid var(--nc-border, #2a2f3e);
}
/* the global input rule's --nc-border (!important) is under 3:1 on this surface; one more class outranks it */
.qo-dlg__input { border-color: rgba(255, 255, 255, 0.38) !important; }
.qo-dlg__input:focus { border-color: var(--nc-primary) !important; box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.35) !important; }
.qo-dlg__hint { margin: 0; font-size: 0.76rem; line-height: 1.45; color: var(--nc-text-secondary, #9aa0a6); }
.qo-dlg__error {
  display: flex; align-items: flex-start; gap: 0.5rem; margin: 0; padding: 0.65rem 0.8rem; border-radius: 10px;
  font-size: 0.85rem; line-height: 1.45; color: #ffc1cd;
  background: var(--nc-danger-subtle); border: 1px solid var(--nc-danger-glow);
}
.qo-dlg__error-icon { font-size: 1rem; flex: 0 0 auto; margin-top: 0.1rem; }
.qo-dlg__ok {
  display: flex; align-items: flex-start; gap: 0.5rem; margin: 0; font-size: 0.88rem; line-height: 1.5; color: #b7ffd9;
}
.qo-dlg__ok:focus { outline: none; }
.qo-dlg__ok:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 4px; border-radius: 6px; }
.qo-dlg__ok-icon { font-size: 1.05rem; flex: 0 0 auto; margin-top: 0.1rem; }
/* the live region stays in the accessibility tree while empty (a region shown only with its text is not announced) */
.qo-dlg__notes { display: flex; flex-direction: column; gap: 0.4rem; }
.qo-dlg__notes:empty { margin-top: -1rem; }
.qo-dlg__note { margin: 0; font-size: 0.82rem; line-height: 1.5; color: var(--nc-text-secondary, #9aa0a6); }
.qo-dlg__foot { display: flex; justify-content: flex-end; gap: 0.6rem; flex-wrap: wrap; padding-top: 0.25rem; }
.qo-dlg__btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.45rem; min-height: 44px; padding: 0.55rem 1.1rem;
  border-radius: 10px; cursor: pointer; font: inherit; font-size: 0.9rem; font-weight: 650;
  transition: background var(--nc-duration-fast, 200ms) ease, border-color var(--nc-duration-fast, 200ms) ease;
}
.qo-dlg__btn:focus-visible { outline: 2px solid var(--nc-primary-bright, var(--nc-primary)); outline-offset: 2px; }
.qo-dlg__btn:disabled { opacity: 0.55; cursor: not-allowed; }
.qo-dlg__btn--ghost { background: transparent; color: var(--nc-text-primary, #e8eaed); border: 1px solid rgba(255, 255, 255, 0.16); }
.qo-dlg__btn--ghost:hover:not(:disabled) { border-color: rgba(255, 255, 255, 0.32); }
.qo-dlg__btn--warn { color: #fff1e0; background: rgba(255, 149, 0, 0.2); border: 1px solid rgba(255, 149, 0, 0.6); }
.qo-dlg__btn--warn:hover:not(:disabled) { background: rgba(255, 149, 0, 0.3); }
.qo-dlg__btn--primary {
  color: #fff; border: 1px solid rgba(var(--nc-primary-rgb), 0.7);
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.32), rgba(var(--nc-primary-rgb), 0.2));
}
.qo-dlg__btn--primary:hover { background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.42), rgba(var(--nc-primary-rgb), 0.28)); }
.qo-dlg__btn-icon { font-size: 1rem; }
.qo-spin { animation: qo-dlg-spin 0.9s linear infinite; }
@keyframes qo-dlg-spin { to { transform: rotate(360deg); } }
@keyframes qo-dlg-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes qo-dlg-rise { from { opacity: 0; transform: translateY(10px) scale(0.985); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .qo-dlg-overlay, .qo-dlg, .qo-spin { animation: none; }
  .qo-dlg__btn { transition: none; }
}
@media (max-width: 480px) {
  .qo-dlg-overlay { align-items: flex-end; padding: 0; }
  .qo-dlg { max-width: 100%; max-height: 92vh; border-radius: 16px 16px 0 0; }
  .qo-dlg__foot { flex-direction: column-reverse; }
  .qo-dlg__btn { width: 100%; }
}
</style>
