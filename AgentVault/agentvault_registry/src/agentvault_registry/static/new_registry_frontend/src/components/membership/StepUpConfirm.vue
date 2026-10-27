<!-- STEP-UP CONFIRM (§MEMBERSHIP, 2026-10-02) — a member's binding vote answered 428: a person confirms it. The dialog
     shows the same lines the phone shows (components/cockpit/presentation.ts, so both screens agree on what is signed),
     waits for the phone's approval (the `liability.resolved` cue, with a 5 s look at the pending list in case the socket
     is down), and takes an authenticator code where the member has one. The parent resends the vote with the proof.
     Quick onboarding (2026-10-09): a modal in name AND in keys. Focus enters it (the code field, else the phone's own
     button, else Cancel), Tab stays inside, Esc cancels like the close button, and focus goes back where it was. Every
     caller already lets go of its own trap while this one is open (PocketSenate pauses its sheet's; the credential
     reset dialog steps aside), so one trap holds the keyboard at a time. -->
<template>
  <Teleport to="body">
    <div v-if="show && challenge" class="tp-overlay" @click.self="close">
      <div ref="panel" class="tp-modal tp-modal--sm" role="dialog" aria-modal="true" :aria-label="titleText" tabindex="-1"
           data-testid="stepup-confirm" :data-challenge="challenge.challengeId">
        <div class="tp-modal-header">
          <span class="tp-modal-title"><Icon name="mdi:shield-check" /> {{ titleText }}</span>
          <button type="button" class="tp-modal-close" :aria-label="t('common.cancel', 'Cancel')" data-testid="stepup-close" @click="close">
            <Icon name="mdi:close" />
          </button>
        </div>

        <div class="tp-modal-body">
          <p class="suc-lead">{{ lead || t('membership.stepUp.lead', 'Votes on this registry are confirmed by a person. Approve this one on your phone, or enter a code.') }}</p>

          <div class="suc-what">
            <div class="suc-what__title">{{ t('membership.stepUp.what', 'What you confirm') }}</div>
            <dl class="suc-lines" data-testid="stepup-lines">
              <template v-for="l in lines" :key="l.key">
                <dt>{{ l.label }}</dt><dd :data-key="l.key">{{ l.value }}</dd>
              </template>
            </dl>
          </div>

          <div v-if="outcome === 'denied'" class="tp-banner tp-banner--danger" role="status" data-testid="stepup-denied">
            {{ deniedText || t('membership.stepUp.denied', 'You declined this vote on your phone. Nothing was cast.') }}
          </div>
          <div v-else-if="expired" class="tp-banner tp-banner--warn" role="status" data-testid="stepup-expired">
            {{ expiredText || t('membership.stepUp.expired', 'This confirmation expired. Vote again to get a new one.') }}
          </div>
          <template v-else>
            <div v-if="hasDevice" class="suc-phone" data-testid="stepup-phone">
              <Icon name="mdi:cellphone" />
              <div>
                <div>{{ t('membership.stepUp.phone', 'On your phone: open Pocket, then Approvals. A notification is on its way.') }}</div>
                <div class="suc-muted" aria-live="polite">{{ t('membership.stepUp.waiting', 'Waiting for your phone…') }}</div>
              </div>
            </div>
            <button v-if="canSignHere && hasDevice" type="button" class="tp-btn tp-btn--primary suc-sign" :disabled="busy"
                    data-testid="stepup-sign-here" @click="$emit('sign')">
              <Icon name="mdi:shield-check" /> {{ t('membership.stepUp.signHere', 'Confirm with this device') }}
            </button>

            <form v-if="hasTotp" class="tp-field suc-code" @submit.prevent="submitCode">
              <label class="tp-label" for="suc-code">{{ hasDevice ? t('membership.stepUp.codeLabel', 'Or enter the code from your authenticator app') : t('membership.stepUp.codeOnly', 'Enter the code from your authenticator app') }}</label>
              <div class="suc-code__row">
                <input id="suc-code" v-model="code" class="tp-input" inputmode="numeric" autocomplete="one-time-code"
                       maxlength="8" pattern="[0-9]{6,8}" data-testid="stepup-code" />
                <button type="submit" class="tp-btn tp-btn--success" :disabled="busy || !codeOk" data-testid="stepup-code-submit">
                  {{ t('membership.stepUp.confirmCode', 'Confirm with code') }}
                </button>
              </div>
            </form>
          </template>

          <div v-if="error" class="tp-banner tp-banner--danger" role="alert" data-testid="stepup-error">{{ error }}</div>
        </div>

        <div class="tp-modal-footer">
          <span class="suc-muted" data-testid="stepup-clock">{{ expired ? '' : tp('membership.stepUp.expiresIn', 'Expires in {s} s', { s: left }) }}</span>
          <button type="button" class="tp-btn tp-btn--ghost" data-testid="stepup-cancel" @click="close">{{ t('common.cancel', 'Cancel') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useCockpitBus } from '@/composables/useCockpitBus'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { liabilityApi } from '@/services/api/liability'
import { buildPresentation } from '@/components/cockpit/presentation'
import { secondsLeft, type StepUpChallenge } from '@/services/membership/membership'
// the dialog's tp-* look is the Senate's; Pocket and the Bridge terminal do not load that sheet themselves
import '@/components/senate/tp-senate.css'

const props = withDefaults(defineProps<{
  show: boolean
  challenge: StepUpChallenge | null
  busy?: boolean
  error?: string
  /** the phone: this device holds an enrolled key and can sign the challenge itself */
  canSignHere?: boolean
  /** Quick onboarding (2026-10-09): what the caller asks a person to confirm (an agent's credential reset is not a
   *  vote). Each is optional; without them the dialog is the vote's, word for word. */
  title?: string
  lead?: string
  deniedText?: string
  expiredText?: string
}>(), { busy: false, error: '', canSignHere: false, title: '', lead: '', deniedText: '', expiredText: '' })

const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  /** the phone approved (or the challenge left the pending list): resend the vote with this challenge id */
  (e: 'approved', challengeId: string): void
  (e: 'code', totp: string): void
  (e: 'sign'): void
}>()

const { t, tp } = useI18n()
const titleText = computed(() => props.title || t('membership.stepUp.title', 'Confirm your vote'))

// the keyboard stays in the dialog while it asks; the first control a person acts with takes the focus
const panel = ref<HTMLElement | null>(null)
useFocusTrap(panel, {
  activeWhen: computed(() => props.show && !!props.challenge),
  initialFocus: '#suc-code, [data-testid="stepup-sign-here"], [data-testid="stepup-cancel"]',
})

const lines = computed(() => buildPresentation(props.challenge?.facts || {}, (k, fb) => t(k, fb)))
const hasDevice = computed(() => !props.challenge || props.challenge.methods.length === 0 || props.challenge.methods.includes('device'))
const hasTotp = computed(() => !!props.challenge && props.challenge.methods.includes('totp'))

const code = ref('')
const codeOk = computed(() => /^[0-9]{6,8}$/.test(code.value.trim()))
function submitCode() { if (codeOk.value && !props.busy) emit('code', code.value.trim()) }

const outcome = ref<'' | 'denied'>('')
const issuedAt = ref(Date.now())
const now = ref(Date.now())
const left = computed(() => (props.challenge ? secondsLeft(props.challenge, now.value, issuedAt.value) : 0))
const expired = computed(() => !!props.challenge && left.value <= 0)

let announced = ''
function approvedOnce(id: string) {
  if (!id || announced === id || props.busy) return
  announced = id
  emit('approved', id)
}

// The phone's answer, as the server announces it to this developer's sockets.
useCockpitBus({
  'liability.resolved': (data: any) => {
    const id = props.challenge?.challengeId
    if (!id || String(data?.challenge_id || '') !== id) return
    if (String(data?.status || '').toLowerCase() === 'denied') { outcome.value = 'denied'; return }
    approvedOnce(id)
  },
})

// The same answer without the socket: once the challenge leaves this developer's pending list it was decided (or it
// expired); the resend tells which. Every 5 s, never faster, and only while the dialog waits on a device.
let tick: ReturnType<typeof setInterval> | null = null
let poll: ReturnType<typeof setInterval> | null = null
async function lookPending() {
  const id = props.challenge?.challengeId
  if (!id || props.busy || expired.value || outcome.value || !hasDevice.value) return
  try {
    const r = await liabilityApi.pendingChallenges()
    const still = (r?.challenges || []).some((c: any) => String(c?.id) === id)
    if (!still) approvedOnce(id)
  } catch { /* the socket path still works; a failed look is not a decision */ }
}

function start() {
  stop()
  issuedAt.value = Date.now(); now.value = Date.now(); outcome.value = ''; code.value = ''; announced = ''
  tick = setInterval(() => { now.value = Date.now() }, 1000)
  poll = setInterval(() => { void lookPending() }, 5000)
}
function stop() {
  if (tick) { clearInterval(tick); tick = null }
  if (poll) { clearInterval(poll); poll = null }
}
function close() { stop(); emit('update:show', false) }

watch(() => props.challenge?.challengeId, (id) => { if (id && props.show) start() })
watch(() => props.show, (v) => { if (v && props.challenge) start(); else stop() })
onMounted(() => { if (props.show && props.challenge) start() })
onUnmounted(stop)

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => !!(props.show && props.challenge), close)
</script>

<style scoped>
.suc-lead { margin: 0 0 0.75rem; font-size: 0.85rem; line-height: 1.5; }
.suc-what { border: 1px solid rgba(var(--nc-primary-rgb, 0,212,255), 0.14); border-radius: 8px; padding: 0.6rem 0.8rem; margin-bottom: 0.75rem; }
.suc-what__title { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.8; margin-bottom: 0.35rem; }
.suc-lines { display: grid; grid-template-columns: max-content 1fr; gap: 0.2rem 0.75rem; margin: 0; font-size: 0.82rem; }
.suc-lines dt { opacity: 0.8; }
.suc-lines dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }
.suc-phone { display: flex; gap: 0.6rem; align-items: flex-start; font-size: 0.84rem; line-height: 1.45; margin-bottom: 0.75rem; }
.suc-phone :deep(svg) { width: 1.3rem; height: 1.3rem; flex: 0 0 auto; color: var(--nc-primary, #00d4ff); }
.suc-sign { width: 100%; margin-bottom: 0.75rem; }
.suc-code__row { display: flex; gap: 0.5rem; }
.suc-code__row .tp-input { flex: 1 1 auto; min-width: 0; font-variant-numeric: tabular-nums; letter-spacing: 0.15em; font-size: 16px; }
.suc-muted { font-size: 0.75rem; opacity: 0.8; }
</style>
