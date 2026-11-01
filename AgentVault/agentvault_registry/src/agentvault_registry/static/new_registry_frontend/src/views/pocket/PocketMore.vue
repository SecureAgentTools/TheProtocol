<!-- POCKET · More — devices/pairing (embedded), security posture, Advanced-mode switch, sign out. -->
<template>
  <div class="pm-wrap">
    <h1 class="pm-title">{{ t('pocket.tabs.more', 'More') }}</h1>

    <section class="pm-group">
      <button class="pm-item" @click="showDevices = !showDevices">
        <Icon name="mdi:bell-ring" /><span>{{ t('pocket.more.devices', 'Devices & alerts') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" :class="{ open: showDevices }" />
      </button>
      <div v-if="showDevices" class="pm-embed"><PocketFrame /></div>
      <router-link to="/pocket/notifications" class="pm-item">
        <Icon name="mdi:bell" /><span>{{ t('pocket.more.notifHistory', 'Notification history') }}</span>
        <span class="pm-val">{{ t('pocket.more.notifHistoryVal', 'what fired, what was held back') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <!-- D2 (§OURSTATE-1): OurState took the tab slot — Approvals keeps this
           door (route + NEEDS YOU doors unchanged). -->
      <router-link to="/pocket/approvals" class="pm-item" data-testid="pm-approvals">
        <Icon name="mdi:shield-key" /><span>{{ t('pocket.more.approvals', 'Approvals') }}</span>
        <span class="pm-val">{{ t('pocket.more.approvalsVal', 'sign-ins, spends and challenges waiting on you') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>

      <!-- §OURSTATE-7 D — support, as a thread. Filing here files a real
           ticket on the support rail and then lands you in its conversation;
           the reply arrives where you already read, not in a settings tab. -->
      <div class="pm-item" data-testid="pm-support" @click="supportOpen = !supportOpen">
        <Icon name="mdi:lifebuoy" /><span>{{ t('pocket.more.support', 'Contact support') }}</span>
        <span class="pm-val">{{ t('pocket.more.supportVal', 'opens a thread — replies land in OurChat') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" :class="{ open: supportOpen }" />
      </div>
      <div v-if="supportOpen" class="pm-awaybox" data-testid="pm-support-box">
        <input v-model="supportSubject" class="pm-awayinput" data-testid="pm-support-subject"
               maxlength="200" :placeholder="t('pocket.more.supportSubject', 'Subject')" />
        <textarea v-model="supportBody" class="pm-awayinput" data-testid="pm-support-body"
                  rows="3" maxlength="4000"
                  :placeholder="t('pocket.more.supportBody', 'What happened?')"></textarea>
        <button class="pm-handlebtn" data-testid="pm-support-send"
                :disabled="supportBusy || !supportSubject.trim() || !supportBody.trim()"
                @click.stop="fileTicket">{{ t('pocket.more.supportSend', 'Open a ticket') }}</button>
        <p v-if="supportMsg" class="pm-inline-msg" data-testid="pm-support-msg">{{ supportMsg }}</p>
      </div>

      <!-- V0652 (ak): your chat settings, one component with the console's (ChatYouSettings) -->
      <ChatYouSettings />
    </section>

    <section class="pm-group">
      <div v-if="bioAvailable" class="pm-item" role="switch" :aria-checked="lock.enabled.value" @click="toggleBio">
        <Icon name="mdi:fingerprint" /><span>{{ t('pocket.more.bioLock', 'Biometric lock') }}</span>
        <span class="pm-switch" :class="{ on: lock.enabled.value }" aria-hidden="true"><span class="pm-knob"></span></span>
      </div>
      <div v-else class="pm-item pm-static">
        <Icon name="mdi:fingerprint" /><span>{{ t('pocket.more.bioLock', 'Biometric lock') }}</span>
        <span class="pm-val">{{ t('pocket.more.bioUnavailable', 'unavailable on this device') }}</span>
      </div>
      <p v-if="bioMsg" class="pm-inline-msg">{{ bioMsg }}</p>

      <!-- #PK32 — THE SEALED VAULT. Agent secrets mint agent JWTs that move
           money; leaving them plaintext on a phone is the risk the Commander
           named. The rows below state the CURRENT storage truth and offer the
           strongest seal this device supports — never a silent downgrade. -->
      <!-- ⚠ icon names must exist in Icon.vue's LOCAL map — an unknown name is
           a SILENT blank (the 47-missing-names find, 2026-08-21). mdi:lock and
           mdi:fingerprint are in the map; mdi:lock-plus/-check are NOT. -->
      <div v-if="vaultUi.state === 'plain' && credCount > 0" class="pm-item" data-testid="pm-seal" @click="doSeal">
        <Icon name="mdi:lock" /><span>{{ t('pocket.more.sealCreds', 'Seal agent credentials') }}</span>
        <span class="pm-val">{{ tp('pocket.more.sealCredsVal', '{n} unencrypted on this device', { n: credCount }) }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </div>
      <div v-else-if="vaultUi.state === 'sealed-open' || vaultUi.state === 'sealed-locked'" class="pm-item" data-testid="pm-sealed" @click="doUnseal">
        <Icon :name="vaultUi.kdf === 'webauthn-prf' ? 'mdi:fingerprint' : 'mdi:lock'" /><span>{{ t('pocket.more.credsSealed', 'Credentials sealed') }}</span>
        <span class="pm-val">{{ vaultUi.kdf === 'webauthn-prf' ? t('pocket.more.kdfPrf', 'biometric key (PRF)') : t('pocket.more.kdfDevice', 'device key — weaker') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </div>
      <div v-if="sealOffer" class="pm-sealoffer" data-testid="pm-seal-offer">
        <p>{{ t('pocket.more.sealOffer', 'Your lock key predates sealing, so the fingerprint cannot derive the vault key.') }}</p>
        <button class="pm-mini" @click="doReenrollSeal">{{ t('pocket.more.upgradeSeal', 'Upgrade lock & seal (recommended)') }}</button>
        <button class="pm-mini pm-mini-ghost" @click="doDeviceSeal">{{ t('pocket.more.deviceSeal', 'Seal with a device key — protects copies of storage, not code running in this app') }}</button>
      </div>
      <p v-if="vaultMsg" class="pm-inline-msg" data-testid="pm-vault-msg">{{ vaultMsg }}</p>

      <!-- §POCKETCREDS — the phone's credential doors. Both open the shell's
           global agent sheet on the named lane (query watched there); the
           header brand is the third door, on the SWITCH lane. -->
      <router-link :to="{ query: { sheet: 'agent', tab: 'import' } }" class="pm-item" data-testid="pm-cred-import">
        <Icon name="mdi:import" /><span>{{ t('pocket.more.credImport', 'Import agent credentials') }}</span>
        <span class="pm-val">{{ t('pocket.more.credImportVal', 'paste or attach JSON') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <router-link :to="{ query: { sheet: 'agent', tab: 'adopt' } }" class="pm-item" data-testid="pm-cred-adopt">
        <Icon name="mdi:key" /><span>{{ t('pocket.more.credAdopt', 'Adopt an agent onto this phone') }}</span>
        <span class="pm-val">{{ t('pocket.more.credAdoptVal', 'fresh credentials, no transport') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>

      <router-link to="/pocket/orgs" class="pm-item" data-testid="pm-orgs">
        <Icon name="mdi:office-building" /><span>{{ t('pocket.orgs.title', 'Organizations') }}</span>
        <span class="pm-val">{{ t('pocket.more.orgsVal', 'members, the room, the treasury') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <router-link to="/pocket/activity" class="pm-item">
        <Icon name="mdi:history" /><span>{{ t('pocket.activity.title', 'Activity') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <div class="pm-item pm-static">
        <Icon name="mdi:shield-check" /><span>{{ t('pocket.more.security', 'Security') }}</span>
        <span class="pm-val">{{ ironkeyErr ? t('pocket.more.ironkeyUnreachable', 'IRONKEY status unreachable') : 'IRONKEY ' + (ironkeyMode || '—') }}</span>
      </div>
      <div class="pm-item pm-static">
        <Icon name="mdi:key" /><span>{{ t('pocket.more.session', 'Session') }}</span>
        <span class="pm-val">{{ userLabel }}</span>
      </div>
    </section>

    <section class="pm-group">
      <router-link :to="{ path: '/pocket/approvals', query: { panic: '1' } }" class="pm-item pm-emergency" data-tour="pk-more-emergency">
        <Icon name="mdi:alert-octagon" /><span>{{ t('pocket.more.emergency', 'Emergency') }}</span>
        <span class="pm-val">{{ t('pocket.more.emergencyVal', 'freeze all agents') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
    </section>

    <section class="pm-group">
      <!-- §POCKETBRIDGE3 WS-D/WS-C — the assistant panel + Connect-Claude onboarding -->
      <router-link class="pm-item" to="/pocket/assistant" data-testid="pm-assistant">
        <Icon name="mdi:robot-outline" /><span>{{ t('pocket.assistant.title', 'Assistant') }}</span>
        <span class="pm-val">{{ t('pocket.more.assistantVal', 'voice commands + Claude brains') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <router-link class="pm-item" to="/pocket/claude" data-testid="pm-claude">
        <Icon name="mdi:link-variant" /><span>{{ t('pocket.more.useClaude', 'Use Claude with this registry') }}</span>
        <span class="pm-val">{{ t('pocket.more.useClaudeVal', 'connect your claude.ai subscription') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <button class="pm-item" data-tour="pk-more-tour" @click="startTour">
        <Icon name="mdi:map-marker-path" /><span>{{ t('pocket.more.tour', 'App tour') }}</span>
        <span class="pm-val">{{ t('pocket.more.tourVal', 'replay the walkthrough') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </button>
      <!-- §COCKPITDESK (2026-10-14): the desk from the phone, where the registry serves it. The saved mode stays as it is:
           this opens one surface, it does not switch the person to the desktop console. -->
      <router-link v-if="cockpitDeskEnabled" class="pm-item" to="/desk" data-testid="pm-desk">
        <Icon name="mdi:view-dashboard-variant-outline" /><span>{{ t('pocket.more.desk', 'Cockpit Desk') }}</span>
        <span class="pm-val">{{ t('pocket.more.deskVal', 'your panes, one column') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </router-link>
      <a class="pm-item pm-adv" href="#/mission-control" data-tour="pk-more-adv" @click="setAdvanced">
        <Icon name="mdi:cog" /><span>{{ t('pocket.agents.advancedMode', 'Advanced mode') }}</span>
        <span class="pm-val">{{ t('pocket.more.advancedVal', 'full Mission Control') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </a>
      <!-- §POCKETI18N A — the language picker, reachable WITHOUT leaving the
           phone. Options are ENDONYMS on purpose: this is the one control that
           must stay legible when the interface language is wrong. "Auto" is a
           first-class state (clears the saved choice, the device governs) and
           says what it detected. Same store as the desktop switcher. -->
      <div class="pm-item pm-lang" data-testid="pm-language">
        <Icon name="mdi:translate" /><span>{{ t('pocket.more.language', 'Language') }}</span>
        <select v-model="langSel" class="pm-lang-sel" data-testid="pm-language-sel"
                :aria-label="t('pocket.more.language', 'Language')" @change="applyLang">
          <option value="">Auto · {{ SUPPORTED_LOCALES[detectedLocale] }}</option>
          <option v-for="(name, code) in SUPPORTED_LOCALES" :key="code" :value="code">{{ name }}</option>
        </select>
      </div>
      <!-- §POCKETBRIDGE2 P0.2 — the ONLY thing that makes Pocket a desktop
           default is this switch (a visit is not a choice). Off = heuristic:
           phones open Pocket, desktops open the bridge. -->
      <div class="pm-item" role="switch" :aria-checked="pocketDefault" data-testid="pm-pocket-default" @click="togglePocketDefault">
        <Icon name="mdi:cellphone" /><span>{{ t('pocket.more.pocketDefault', 'Pocket by default') }}</span>
        <span class="pm-val">{{ pocketDefault ? t('pocket.more.everyLogin', 'every login opens Pocket') : t('pocket.more.phonesOnly', 'phones only (automatic)') }}</span>
        <span class="pm-switch" :class="{ on: pocketDefault }" aria-hidden="true"><span class="pm-knob"></span></span>
      </div>
    </section>

    <section class="pm-group">
      <button class="pm-item pm-out" @click="signOut">
        <Icon name="mdi:logout" /><span>{{ t('pocket.more.signOut', 'Sign out') }}</span>
      </button>
    </section>

    <p class="pm-foot">{{ t('pocket.more.foot', 'POCKET FRAME · sovereign agent economy in your pocket') }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { rememberUiMode, savedUiMode, clearUiMode } from '@/services/uiMode'
import PocketFrame from '@/views/PocketFrame.vue'
import ChatYouSettings from '@/components/ourstate/ChatYouSettings.vue'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import { usePocketLock } from '@/composables/usePocketLock'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { useGuidedTourStore } from '@/views/Tutorials/guided/tourStore'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { messageOf } from '@/utils/httpError'
import { SUPPORTED_LOCALES, setLocale, getBrowserLocale, type SupportedLocale } from '@/i18n'

const { t, tp } = useI18n()
const { cockpitDeskEnabled } = useRegistryConfig()

/* ── §OURSTATE-7 D — file a support ticket, land in its thread ───────────── */
const supportOpen = ref(false)
const supportSubject = ref('')
const supportBody = ref('')
const supportBusy = ref(false)
const supportMsg = ref('')

async function fileTicket() {
  if (supportBusy.value) return
  supportBusy.value = true
  supportMsg.value = ''
  try {
    const r = await apiClient.post('/chat/support/open', {
      subject: supportSubject.value.trim(), message: supportBody.value.trim() })
    supportSubject.value = ''; supportBody.value = ''
    const cid = r.data?.conversation_id
    if (cid) {
      supportOpen.value = false
      router.push(`/pocket/ourchat/${cid}`).catch(() => {})
    } else {
      // The TICKET exists — say what did happen, not what did not. Its thread
      // catches up on the next message.
      supportMsg.value = r.data?.note || t('pocket.more.supportFiled',
        'Ticket filed. Its thread will appear shortly.')
    }
  } catch (e: any) {
    supportMsg.value = messageOf(e?.response?.data, e?.detail || String(e))
  } finally { supportBusy.value = false }
}

/* §POCKETI18N A — '' = Auto (nothing saved; the device language governs and
 * keeps governing if the device changes). A named pick is recorded and shared
 * with the desktop switcher; Auto DELETES the record rather than saving a
 * snapshot of it — a visit is not a choice, and neither is a default. */
const detectedLocale = getBrowserLocale()
const savedLang = (() => { try { const v = localStorage.getItem('locale'); return v && v in SUPPORTED_LOCALES ? v : '' } catch { return '' } })()
const langSel = ref<string>(savedLang)
async function applyLang(): Promise<void> {
  if (langSel.value === '') {
    try { localStorage.removeItem('locale') } catch { /* detection still applies next boot */ }
    await setLocale(detectedLocale)
    try { localStorage.removeItem('locale') } catch { /* setLocale re-saved; Auto means UNSAVED */ }
  } else {
    await setLocale(langSel.value as SupportedLocale)
  }
}
const showDevices = ref(false)
const ironkeyMode = ref('')
const ironkeyErr = ref(false)
const auth = useAuthStore()
const router = useRouter()
const lock = usePocketLock()
const bioAvailable = ref(false)
const bioMsg = ref('')

async function toggleBio() {
  bioMsg.value = ''
  if (lock.enabled.value) {
    // #PK32 — refused while the vault is sealed under this key; the reason renders verbatim.
    const off = lock.disable()
    bioMsg.value = off.ok ? t('pocket.more.bioOff', 'Biometric lock turned off.') : (off.reason || t('pocket.more.bioOffFailed', 'Could not turn the lock off.'))
    refreshVault()
    return
  }
  const ok = await lock.enroll()
  bioMsg.value = ok ? t('pocket.more.bioOn', 'Biometric lock is on — Pocket will lock when reopened.') : t('pocket.more.bioEnrollFailed', 'Enrollment cancelled or failed.')
  refreshVault()
}

const userLabel = computed(() => (auth as any).user?.name || (auth as any).user?.email || t('pocket.more.authenticated', 'authenticated'))

/* ── #PK32 sealed-vault state + ceremonies ── */
const vaultUi = ref(lock.vaultInfo())
const vaultMsg = ref('')
const sealOffer = ref(false)
const credCount = ref(0)
function refreshVault() {
  vaultUi.value = lock.vaultInfo()
  try { credCount.value = Object.keys(agentCredentialsStore.getAllCredentials()).length } catch { credCount.value = 0 }
}
async function doSeal() {
  vaultMsg.value = ''; sealOffer.value = false
  if (!lock.enabled.value) { vaultMsg.value = t('pocket.more.enrollFirst', 'Enroll the biometric lock first — the seal is built on its key.'); return }
  const r = await lock.sealCredentials()
  if (r.ok) { vaultMsg.value = t('pocket.more.sealed', 'Sealed. Secrets are now encrypted at rest and unlock with your fingerprint.') }
  else if (r.reason === 'prf-unavailable') { sealOffer.value = true }
  else { vaultMsg.value = r.reason || t('pocket.more.sealFailed', 'Sealing failed — nothing was changed.') }
  refreshVault()
}
async function doReenrollSeal() {
  vaultMsg.value = ''; sealOffer.value = false
  const ok = await lock.enroll()
  if (!ok) { vaultMsg.value = t('pocket.more.reenrollCancelled', 'Re-enrolment cancelled — credentials stay as they were.'); refreshVault(); return }
  const r = await lock.sealCredentials()
  vaultMsg.value = r.ok ? t('pocket.more.lockUpgraded', 'Lock upgraded and credentials sealed under the new fingerprint key.')
    : (r.reason === 'prf-unavailable'
        ? t('pocket.more.noPrf', 'This device’s authenticator does not support PRF at all — the device-key seal is the strongest available here.')
        : r.reason || t('pocket.more.sealFailed', 'Sealing failed — nothing was changed.'))
  if (!r.ok && r.reason === 'prf-unavailable') sealOffer.value = true
  refreshVault()
}
async function doDeviceSeal() {
  vaultMsg.value = ''; sealOffer.value = false
  const r = await lock.sealCredentialsDeviceKey()
  vaultMsg.value = r.ok
    ? t('pocket.more.deviceSealed', 'Sealed with a device key. This protects copied or backed-up storage; it is weaker than the biometric seal.')
    : (r.reason || t('pocket.more.sealFailed', 'Sealing failed — nothing was changed.'))
  refreshVault()
}
async function doUnseal() {
  vaultMsg.value = ''
  const r = await lock.unsealCredentialsToPlain()
  vaultMsg.value = r.ok ? t('pocket.more.unsealed', 'Unsealed — credentials are stored unencrypted on this device again.') : (r.reason || t('pocket.more.unsealFailed', 'Unseal failed.'))
  refreshVault()
}

function setAdvanced() { rememberUiMode('advanced') }
/* §POCKETBRIDGE2 P0.2 — the explicit default switch (and nothing else) records 'pocket'. */
const pocketDefault = ref(savedUiMode() === 'pocket')
function togglePocketDefault() {
  if (pocketDefault.value) { clearUiMode() } else { rememberUiMode('pocket') }
  pocketDefault.value = savedUiMode() === 'pocket'
}
function startTour() { useGuidedTourStore().start('pocket') }
async function signOut() { try { await (auth as any).logout() } catch {} router.push('/login').catch(() => { window.location.hash = '#/login' }) }

onMounted(async () => {
  refreshVault()
  try { const { data } = await apiClient.get('/agents/authz/catalog'); ironkeyMode.value = data?.mode || ''; ironkeyErr.value = false } catch { ironkeyErr.value = true }
  try { bioAvailable.value = await lock.available() } catch { bioAvailable.value = false }
})
</script>

<style scoped>
.pm-wrap { max-width: 560px; margin: 0 auto; padding: 1rem; box-sizing: border-box; display: flex; flex-direction: column; gap: 0.8rem; }
.pm-title { font-size: 1.15rem; margin: 0; }
.pm-group { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; overflow: hidden; }
.pm-item { display: flex; align-items: center; gap: 0.7rem; width: 100%; text-align: left; background: none; border: none;
  color: inherit; padding: 0.9rem 1rem; font-size: 0.9rem; cursor: pointer; text-decoration: none; min-height: 48px;
  border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.15s; -webkit-tap-highlight-color: transparent; }
.pm-group .pm-item:last-child, .pm-group > .pm-item:only-of-type { border-bottom: none; }
.pm-item:active { background: rgba(255,255,255,0.06); }
.pm-item :deep(svg) { width: 1.15rem; height: 1.15rem; color: var(--nc-primary, #00d4ff); flex: 0 0 auto; }
.pm-static { cursor: default; }
.pm-val { margin-left: auto; font-size: 0.75rem; opacity: 0.55; }
.pm-lang { flex-wrap: wrap; row-gap: 6px; }
.pm-lang-sel { margin-left: auto; max-width: 55%; min-height: 44px; font-size: 16px; color: inherit;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 0.4rem 0.6rem; }
.pm-chev { margin-left: auto; opacity: 0.4; transition: transform 0.15s; }
.pm-chev.open { transform: rotate(90deg); }
.pm-adv .pm-val { margin-left: auto; }
.pm-adv .pm-chev { margin-left: 0.3rem; }
.pm-out { color: #ff8a8a; }
.pm-out :deep(svg) { color: #ff8a8a; }
.pm-emergency { color: #ff6b6b; font-weight: 600; }
.pm-emergency :deep(svg) { color: #ff4d4d; }
.pm-emergency .pm-val { color: #ff8a8a; opacity: 0.75; }
.pm-embed { border-top: 1px solid rgba(255,255,255,0.05); }
.pm-embed :deep(.pf-wrap) { padding: 0.6rem; }
.pm-embed :deep(.pf-head) { display: none; }
.pm-switch { margin-left: auto; width: 42px; height: 24px; border-radius: 12px; background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.15); position: relative; flex: 0 0 auto; transition: background 0.2s, border-color 0.2s; }
.pm-switch.on { background: rgba(0,212,255,0.35); border-color: rgba(0,212,255,0.5); }
.pm-knob { position: absolute; top: 1px; left: 1px; width: 20px; height: 20px; border-radius: 50%; background: #e6edf3; transition: transform 0.2s cubic-bezier(0.34,1.4,0.64,1); }
.pm-switch.on .pm-knob { transform: translateX(18px); }
.pm-inline-msg { font-size: 0.72rem; opacity: 0.75; margin: 0.1rem 1rem 0.6rem; color: #cfe3ee; }
.pm-sealoffer { padding: 0.4rem 1rem 0.8rem; display: flex; flex-direction: column; gap: 0.45rem; }
.pm-sealoffer p { margin: 0; font-size: 0.76rem; opacity: 0.7; }
.pm-mini { background: rgba(0,212,255,0.1); border: 1px solid rgba(0,212,255,0.3); border-radius: 11px;
  color: #e6edf3; font-size: 0.78rem; font-weight: 600; padding: 0.6rem 0.8rem; min-height: 44px; cursor: pointer;
  text-align: left; -webkit-tap-highlight-color: transparent; }
.pm-mini-ghost { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.12); font-weight: 500; opacity: 0.85; }
.pm-foot { text-align: center; font-size: 0.68rem; color: #8a94a3; margin: 0.4rem 0 0; letter-spacing: 0.04em; } /* §FESUITE: was opacity 0.35, 2.8:1 */
@media (prefers-reduced-motion: reduce) { .pm-knob { transition: none; } }
.pm-awaybox { display: flex; flex-direction: column; gap: 8px; padding: 8px 16px 12px; }
.pm-awaynote { font-size: .74rem; opacity: .65; margin: 0; }
.pm-awayinput { min-height: 44px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font: inherit; font-size: 16px; }
.pm-handlerow { display: flex; gap: 8px; align-items: center; }
.pm-blockname { flex: 1; min-width: 0; overflow-wrap: anywhere; font-size: 0.82rem; }
.pm-handlerow .pm-awayinput { flex: 1; }
.pm-handlebtn { min-height: 44px; padding: 0 16px; border-radius: 10px; border: none; background: var(--primary-color, #4fd8c4); color: #06211d; font-weight: 700; }
.pm-handleqr { align-self: center; width: 200px; height: 200px; image-rendering: pixelated; }
.pm-pulsemoment { font-size: .8rem; margin: 0; padding: 4px 0; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); }
</style>
