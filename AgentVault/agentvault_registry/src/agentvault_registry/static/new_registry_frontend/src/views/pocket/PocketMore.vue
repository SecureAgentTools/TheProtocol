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

      <!-- §OURSTATE-3 REACH — your handle: an opt-in ADDRESS so people can
           reach you by name instead of by id. Claiming publishes nothing that
           was private; the profile it opens still obeys your visibility. -->
      <div class="pm-item" data-testid="pm-handle" role="button" tabindex="0" :aria-expanded="handleOpen"
           @click="handleOpen = !handleOpen" @keydown.enter.prevent="handleOpen = !handleOpen" @keydown.space.prevent="handleOpen = !handleOpen">
        <Icon name="mdi:at" /><span>{{ t('pocket.more.handle', 'Your handle') }}</span>
        <span class="pm-val">{{ handleRead !== 'read' ? (handleRead === 'reading' ? '…' : '—')
          : myHandle ? '@' + myHandle : t('pocket.more.handleNone', 'not claimed — you are unreachable by name') }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </div>
      <div v-if="handleOpen" class="pm-awaybox" data-testid="pm-handle-box">
        <ReadFailedNotice v-if="handleRead === 'unread'" dense :retry="loadHandle" data-testid="pm-handle-unread" />
        <p class="pm-awaynote">{{ t('pocket.more.handleWhat', 'A handle is an address, not a profile. 3–32 characters; letters, digits, - and _.') }}</p>
        <div class="pm-handlerow">
          <input v-model="handleDraft" class="pm-awayinput" data-testid="pm-handle-input" maxlength="32"
                 :placeholder="t('pocket.more.handlePh', 'yourname')" :aria-label="t('pocket.more.handle', 'Your handle')" />
          <button class="pm-handlebtn" data-testid="pm-handle-claim" :disabled="handleBusy || handleRead !== 'read'" @click.stop="claimHandle">
            {{ handleBusy ? '…' : t('pocket.more.handleClaim', 'Claim') }}</button>
        </div>
        <p v-if="handleMsg" class="pm-inline-msg" data-testid="pm-handle-msg">{{ handleMsg }}</p>
        <template v-if="myHandle">
          <img v-if="handleQr" :src="handleQr" class="pm-handleqr" data-testid="pm-handle-qr"
               :alt="t('pocket.more.handleQrAlt', 'Contact QR for your handle')" />
          <p class="pm-awaynote" data-testid="pm-handle-link">{{ handleLink }}</p>
          <!-- See what everyone else sees. A published pulse with no way to
               view it is a setting that reports on nothing. -->
          <button v-if="myHandle" class="pm-handlebtn" data-testid="pm-handle-view"
                  @click.stop="viewMyCard">
            {{ t('pocket.more.handleView', 'View my public card') }}</button>
        </template>
      </div>

      <!-- §FESUITE — the people you blocked. A block was a one-way door: the thread said "they are not told" and no screen
           listed a block or lifted one (the API had both since §TWOAGENT G1). -->
      <div class="pm-item" data-testid="pm-blocks" role="button" tabindex="0" :aria-expanded="blocksOpen"
           @click="toggleBlocks" @keydown.enter.prevent="toggleBlocks" @keydown.space.prevent="toggleBlocks">
        <Icon name="mdi:cancel" /><span>{{ t('pocket.more.blocked', 'Blocked') }}</span>
        <span class="pm-val" data-testid="pm-blocks-count">{{ !blocksLoaded ? '…' : blocksFailed ? '—' : blocks.length }}</span>
        <Icon name="mdi:chevron-right" class="pm-chev" />
      </div>
      <div v-if="blocksOpen" class="pm-awaybox" data-testid="pm-blocks-box">
        <ReadFailedNotice v-if="blocksFailed" dense :retry="loadBlocks" />
        <p v-else-if="blocksLoaded && !blocks.length" class="pm-awaynote">{{ t('pocket.more.blockedNone', 'Nobody is blocked.') }}</p>
        <div v-for="b in blocks" :key="`${b.ptype}:${b.id}`" class="pm-handlerow" data-testid="pm-block-row" :data-block="`${b.ptype}:${b.id}`">
          <span class="pm-blockname">{{ blockLabel(b) }}</span>
          <button class="pm-handlebtn" data-testid="pm-unblock" :disabled="unblocking === `${b.ptype}:${b.id}`" @click.stop="unblock(b)">
            {{ t('pocket.more.unblock', 'Unblock') }}</button>
        </div>
        <p v-if="blocksMsg" class="pm-inline-msg" data-testid="pm-blocks-msg">{{ blocksMsg }}</p>
      </div>

      <!-- §OURSTATE-5a CONTACT TERMS — spam control that is economic rather
           than editorial. What a stranger pays to open a FIRST thread; replies
           are always free, and people you have already spoken to are never
           charged again. -->
      <div class="pm-item" data-testid="pm-terms" @click="termsOpen = !termsOpen">
        <Icon name="mdi:hand-coin-outline" /><span>{{ t('pocket.more.terms', 'Contact terms') }}</span>
        <span class="pm-val">{{ termsRead !== 'read' ? (termsRead === 'reading' ? '…' : '—') : termsSummary }}</span>
      </div>
      <div v-if="termsOpen" class="pm-awaybox" data-testid="pm-terms-box">
        <ReadFailedNotice v-if="termsRead === 'unread'" dense :retry="loadTerms" data-testid="pm-terms-unread" />
        <p class="pm-awaynote">{{ t('pocket.more.termsWhat',
          'Applies to a stranger opening their first thread with you. Replies are free, and existing contacts are never charged.') }}</p>
        <div class="pm-handlerow">
          <select v-model="termsPolicy" class="pm-awayinput" data-testid="pm-terms-policy">
            <option value="open">{{ t('pocket.more.termsOpen', 'Open — anyone may write') }}</option>
            <option value="contacts">{{ t('pocket.more.termsContacts', 'Contacts only') }}</option>
            <option value="priced">{{ t('pocket.more.termsPriced', 'Priced first contact') }}</option>
          </select>
        </div>
        <template v-if="termsPolicy === 'priced'">
          <div class="pm-handlerow">
            <input v-model="termsPrice" class="pm-awayinput" data-testid="pm-terms-price"
                   inputmode="decimal" :placeholder="t('pocket.more.termsPricePh', 'amount')" />
            <input v-model="termsCurrency" class="pm-awayinput" data-testid="pm-terms-ccy"
                   maxlength="12" :placeholder="t('pocket.more.termsCcyPh', 'currency')" />
          </div>
          <!-- Humans hold no balance on this network, so the price is payable
               to one of YOUR agents. Named explicitly: a price payable to
               nobody is not a price, and the registry will say so. -->
          <select v-model="termsPurse" class="pm-awayinput" data-testid="pm-terms-purse">
            <option value="">{{ t('pocket.more.termsPursePick', 'which of your agents receives it') }}</option>
            <option v-for="a in localAgents" :key="a.did" :value="a.did">{{ a.name || a.did }}</option>
          </select>
        </template>
        <textarea v-model="termsStated" class="pm-awayinput" data-testid="pm-terms-stated"
                  rows="2" maxlength="2000"
                  :placeholder="t('pocket.more.termsStatedPh', 'what you want people to know (your words)')" />
        <button class="pm-handlebtn" data-testid="pm-terms-save" :disabled="termsBusy || termsRead !== 'read'"
                @click.stop="saveTerms">
          {{ termsBusy ? '…' : t('cta.save', 'Save') }}</button>
        <p v-if="termsMsg" class="pm-inline-msg" data-testid="pm-terms-msg">{{ termsMsg }}</p>
      </div>

      <!-- §OURSTATE-4 PULSE — the opt-in economy feed. Off by default; it
           publishes only work the registry already attests to (settled jobs,
           the stars a counterparty gave, work that traveled). No presence:
           there is no "last seen" here, and no column it could come from. -->
      <div class="pm-item" role="switch" :aria-checked="pulseOn" data-testid="pm-pulse" @click="togglePulse">
        <Icon name="mdi:chart-line" /><span>{{ t('pocket.more.pulse', 'Pulse') }}</span>
        <span class="pm-val">{{ pulseRead !== 'read' ? (pulseRead === 'reading' ? '…' : '—') : pulseOn
          ? tp('pocket.more.pulseOn', '{n} moment(s) published on your profile', { n: String(pulseMoments.length) })
          : t('pocket.more.pulseOff', 'off — your profile shows no activity') }}</span>
        <span class="pm-switch" :class="{ on: pulseOn }" aria-hidden="true"></span>
      </div>
      <ReadFailedNotice v-if="pulseRead === 'unread'" dense :retry="loadPulse" data-testid="pm-pulse-unread" />
      <div v-if="pulseOn" class="pm-awaybox" data-testid="pm-pulse-box">
        <p class="pm-awaynote">{{ t('pocket.more.pulseWhat', 'Only verified work: settled jobs, the stars your counterparties gave, and work done on other registries. Never balances, never presence.') }}</p>
        <p v-for="(m, i) in pulseMoments" :key="i" class="pm-pulsemoment" :data-testid="`pm-pulse-${i}`">{{ m.text }}</p>
        <p v-if="!pulseMoments.length" class="pm-awaynote" data-testid="pm-pulse-empty">
          {{ t('pocket.more.pulseEmpty', 'Published — nothing attested to show yet. Finish a guild job and it appears here.') }}</p>
        <p v-if="pulseMsg" class="pm-inline-msg" data-testid="pm-pulse-msg">{{ pulseMsg }}</p>
      </div>

      <!-- §OURSTATE-2 Away mode v1 (the stage-only Bouncer). A DESIGNATION,
           not an authority: the stand-in discloses itself as software, answers
           a stranger ONCE, and spends nothing. Off until you switch it on. -->
      <div class="pm-item" role="switch" :aria-checked="awayOn" data-testid="pm-away" @click="toggleAway">
        <Icon name="mdi:account-clock" /><span>{{ t('pocket.more.away', 'Away mode') }}</span>
        <span class="pm-val">{{ awayRead !== 'read' ? (awayRead === 'reading' ? '…' : '—') : awayOn
          ? tp('pocket.more.awayOn', '{name} answers new strangers', { name: awayAgentName })
          : t('pocket.more.awayOff', 'off — nobody answers for you') }}</span>
        <span class="pm-switch" :class="{ on: awayOn }" aria-hidden="true"></span>
      </div>
      <ReadFailedNotice v-if="awayRead === 'unread'" dense :retry="loadAway" data-testid="pm-away-unread" />
      <div v-if="awayOpen" class="pm-awaybox" data-testid="pm-away-box">
        <ReadFailedNotice v-if="agentsFailed" dense :retry="loadAway" data-testid="pm-agents-unread"
                          :text="t('pocket.more.agentsUnread', 'Your agents could not be read just now.')" />
        <p class="pm-awaynote">{{ t('pocket.more.awayWhat', 'Your stand-in replies once, says it is software, and stages what the stranger wants. It cannot accept work, sign anything or move money.') }}</p>
        <select v-model="awayAgentDid" class="pm-lang-sel" data-testid="pm-away-agent" @change="saveAway">
          <option value="">{{ t('pocket.more.awayPick', 'Pick one of your agents…') }}</option>
          <option v-for="a in localAgents" :key="a.did" :value="a.did">{{ a.name || a.did }}</option>
        </select>
        <input v-model="awayNote" class="pm-awayinput" data-testid="pm-away-note" maxlength="280"
               :placeholder="t('pocket.more.awayNotePh', 'Optional note the stand-in may pass on')"
               @change="saveAway" />
        <!-- §OURSTATE-5b — bounded negotiation authority. This is an IRONKEY
             capability GRANT ID, not a limit typed into a chat app: the number
             points at a token whose ceiling, currency and expiry live in the
             delegation rail. Revoke the grant there and the line below empties
             on the next read. -->
        <input v-model="awayGrantId" class="pm-awayinput" data-testid="pm-away-grant"
               inputmode="numeric"
               :placeholder="t('pocket.more.awayGrantPh', 'capability grant id (optional)')"
               @change="saveAway" />
        <p class="pm-awaynote" data-testid="pm-away-authority">{{ awayAuthorityLine }}</p>
        <p v-if="awayMsg" class="pm-inline-msg" data-testid="pm-away-msg">{{ awayMsg }}</p>
      </div>
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
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { rememberUiMode, savedUiMode, clearUiMode } from '@/services/uiMode'
import PocketFrame from '@/views/PocketFrame.vue'
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

/* ── §OURSTATE-4 PULSE: opt-in, attested, presence-free ─────────────────── */
// §FESUITE V0578: these four reads ("absence, not an error") answered 200 for absence on every registry that has the
// routes, so a thrown error was a FAILED read that the page drew as an answer: "not claimed — you are unreachable by
// name", Pulse "off — your profile shows no activity", Away "off", and contact terms "open to anyone", whose Save then
// wrote "open" over a priced or contacts-only policy (and Away's whole-value save dropped threads_off, which a thread's
// kill switch writes). Each says '—' and its read failed (Try again) and changes nothing until a read answers; a 404 (a
// registry without the route) keeps the old reading.
type ReadState = 'reading' | 'read' | 'unread'
const absentRoute = (e: any) => e?.response?.status === 404
const pulseRead = ref<ReadState>('reading')
const handleRead = ref<ReadState>('reading')
const termsRead = ref<ReadState>('reading')
const awayRead = ref<ReadState>('reading')
const agentsFailed = ref(false)
const pulseOn = ref(false)
const pulseMoments = ref<any[]>([])
const pulseMsg = ref('')

async function loadPulse() {
  try {
    const r = await apiClient.get('/chat/pulse/me')
    pulseOn.value = !!r.data?.enabled
    pulseMoments.value = r.data?.moments || []
    pulseRead.value = 'read'
  } catch (e: any) { pulseRead.value = absentRoute(e) ? 'read' : (pulseRead.value === 'read' ? 'read' : 'unread') }
}

async function togglePulse() {
  if (pulseRead.value !== 'read') return   // a switch nobody read is not switched
  pulseMsg.value = ''
  const want = !pulseOn.value
  try {
    const r = await apiClient.put('/chat/pulse/me', { enabled: want, show_agents: true })
    pulseOn.value = !!r.data?.enabled
    pulseMoments.value = r.data?.moments || []
    pulseMsg.value = pulseOn.value
      ? t('pocket.more.pulseSaved', 'On. Anyone who opens your handle sees these moments.')
      : t('pocket.more.pulseOffSaved', 'Off. Your profile shows no activity.')
  } catch (e: any) {
    pulseMsg.value = e?.response?.data?.detail || t('pocket.common.requestFailed', 'request failed')
  }
}

/* ── §OURSTATE-3 REACH: the handle + its contact QR ─────────────────────── */
const myHandle = ref('')
/* ── §OURSTATE-5a contact terms ─────────────────────────────────────────── */
const termsOpen = ref(false)
const termsPolicy = ref('open')
const termsPrice = ref('')
const termsCurrency = ref('')
const termsPurse = ref('')
const termsStated = ref('')
const termsBusy = ref(false)
const termsMsg = ref('')
const termsEffective = ref('open')
const termsInert = ref('')

/* The summary shows what is ENFORCED, and names the gap when a declared price
   is not in force — the owner is the only person who can fix it, so they are
   the one person who must be told. */
const termsSummary = computed(() => {
  if (termsInert.value) {
    return tp('pocket.more.termsInert', 'declared, not in force — {why}', { why: termsInert.value })
  }
  if (termsEffective.value === 'priced') {
    return tp('pocket.more.termsPricedVal', '{amt} {ccy} for a first thread',
              { amt: termsPrice.value, ccy: termsCurrency.value })
  }
  if (termsEffective.value === 'contacts') return t('pocket.more.termsContactsVal', 'contacts only')
  return t('pocket.more.termsOpenVal', 'open to anyone')
})

async function loadTerms() {
  try {
    const { data: r } = await apiClient.get('/chat/contact-policy/me')
    termsPolicy.value = r.policy || 'open'
    termsEffective.value = r.effective || 'open'
    termsInert.value = r.inert_reason || ''
    termsPrice.value = r.price || ''
    termsCurrency.value = r.currency || ''
    termsPurse.value = r.purse_did || ''
    termsStated.value = r.genesis?.stated || ''
    termsRead.value = 'read'
  } catch (e: any) { termsRead.value = absentRoute(e) ? 'read' : (termsRead.value === 'read' ? 'read' : 'unread') }
}

async function saveTerms() {
  if (termsRead.value !== 'read') return   // never write defaults over terms nobody read
  termsBusy.value = true; termsMsg.value = ''
  try {
    const { data: r } = await apiClient.put('/chat/contact-policy/me', {
      policy: termsPolicy.value,
      price: termsPolicy.value === 'priced' ? termsPrice.value : undefined,
      currency: termsPolicy.value === 'priced' ? termsCurrency.value : undefined,
      purse_did: termsPolicy.value === 'priced' ? termsPurse.value : undefined,
      stated: termsStated.value,
    })
    termsEffective.value = r.effective || 'open'
    termsInert.value = r.inert_reason || ''
    // Say what will ACTUALLY happen, not "saved" — the two differ exactly when
    // it matters most.
    termsMsg.value = r.inert_reason
      ? tp('pocket.more.termsSavedInert', 'Saved, but not in force — {why}', { why: r.inert_reason })
      : t('pocket.more.termsSaved', 'Saved.')
  } catch (e: any) {
    termsMsg.value = e?.response?.data?.detail || e?.message || t('common.error', 'Something went wrong')
  } finally { termsBusy.value = false }
}

function viewMyCard() {
  if (!myHandle.value) return
  router.push(`/pocket/ourchat?profile=${encodeURIComponent(myHandle.value)}`).catch(() => {})
}

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

const handleOpen = ref(false)
const handleDraft = ref('')
const handleBusy = ref(false)
const handleMsg = ref('')
const handleQr = ref('')
const handleLink = computed(() =>
  myHandle.value ? `${location.origin}/ui#/pocket/ourchat?q=@${myHandle.value}` : '')

async function loadHandle() {
  try {
    const r = await apiClient.get('/chat/handles/me')
    myHandle.value = r.data?.handle || ''
    handleDraft.value = myHandle.value
    if (myHandle.value) void renderHandleQr()
    handleRead.value = 'read'
  } catch (e: any) { handleRead.value = absentRoute(e) ? 'read' : (handleRead.value === 'read' ? 'read' : 'unread') }
}

async function renderHandleQr() {
  try {
    const QR = await import('qrcode')
    handleQr.value = await QR.toDataURL(handleLink.value,
      { margin: 1, width: 200, color: { dark: '#e6edf3', light: '#0a0d1200' } })
  } catch { handleQr.value = '' }
}

/* §FESUITE — the block list and its undo (GET / DELETE /chat/blocks). */
interface BlockRow { ptype: 'developer' | 'agent' | 'remote'; id: string; created_at?: string | null }
const blocks = ref<BlockRow[]>([])
const blocksLoaded = ref(false)
// §FESUITE (V0575): a failed read is not "Nobody is blocked." (and its count is not 0)
const blocksFailed = ref(false)
const blocksOpen = ref(false)
const blocksMsg = ref('')
const unblocking = ref('')
async function loadBlocks() {
  try {
    const { data } = await apiClient.get('/chat/blocks')
    blocks.value = Array.isArray(data?.blocks) ? data.blocks : []
    blocksFailed.value = false
  } catch { blocks.value = []; blocksFailed.value = true } finally { blocksLoaded.value = true }
}
function toggleBlocks() { blocksOpen.value = !blocksOpen.value; if (blocksOpen.value) void loadBlocks() }
function blockLabel(b: BlockRow): string {
  if (b.ptype === 'developer') return tp('pocket.more.blockedDeveloper', 'Developer #{id}', { id: b.id })
  return b.id
}
async function unblock(b: BlockRow) {
  const key = `${b.ptype}:${b.id}`
  unblocking.value = key
  blocksMsg.value = ''
  const body = b.ptype === 'developer' ? { ptype: 'developer', developer_id: Number(b.id) }
    : b.ptype === 'agent' ? { ptype: 'agent', agent_did: b.id } : { ptype: 'remote', remote_key: b.id }
  try {
    await apiClient.delete('/chat/blocks', { data: body })
    blocks.value = blocks.value.filter(x => `${x.ptype}:${x.id}` !== key)
    blocksMsg.value = t('pocket.more.unblocked', 'Unblocked. They can reach you again.')
  } catch (e: any) {
    blocksMsg.value = e?.response?.data?.detail?.detail || e?.response?.data?.detail || t('pocket.common.requestFailed', 'request failed')
  } finally { unblocking.value = '' }
}

async function claimHandle() {
  handleBusy.value = true
  handleMsg.value = ''
  try {
    const r = await apiClient.post('/chat/handles/claim', { handle: handleDraft.value })
    myHandle.value = r.data?.handle || handleDraft.value
    handleMsg.value = tp('pocket.more.handleClaimed', 'Claimed. People can reach you as @{h}.', { h: myHandle.value })
    await renderHandleQr()
  } catch (e: any) {
    // The registry's own words: "already taken", the shape rule, or reserved.
    handleMsg.value = e?.response?.data?.detail?.detail || e?.response?.data?.detail
      || t('pocket.common.requestFailed', 'request failed')
  } finally { handleBusy.value = false }
}

/* ── §OURSTATE-2 Away mode v1: designation only ───────────────────────────
   The pref is the allowlisted `pocket.away` key — no new table, no new
   authority. `enabled` + `agent_did` is the whole switch; `threads_off` is
   written by the thread's own kill switch. */
const awayOn = ref(false)        // EFFECTIVE: armed server-side
const awayWanted = ref(false)    // INTENT: the human's toggle
const awayOpen = ref(false)
const awayAgentDid = ref('')
const awayNote = ref('')
const awayGrantId = ref('')
const awayAuthority = ref<any>(null)
const awayMsg = ref('')
const awayCfg = ref<any>({})
const localAgents = ref<Array<{ did: string; name?: string }>>([])
const awayAgentName = computed(() =>
  localAgents.value.find(a => a.did === awayAgentDid.value)?.name || awayAgentDid.value || '—')

async function loadAway() {
  try {
    const r = await apiClient.get('/developers/me/prefs/pocket.away')
    const v = r.data?.value || {}
    awayCfg.value = v
    awayOn.value = !!v.enabled
    awayWanted.value = !!v.enabled
    awayAgentDid.value = v.agent_did || ''
    awayNote.value = v.note || ''
    awayGrantId.value = v.capability_token_id ? String(v.capability_token_id) : ''
    awayOpen.value = !!v.enabled
    awayRead.value = 'read'
  } catch (e: any) { awayRead.value = absentRoute(e) ? 'read' : (awayRead.value === 'read' ? 'read' : 'unread') }
  try {
    const r = await apiClient.get('/developers/me/agents', { params: { limit: 50 } })
    // /developers/me/agents answers a BARE LIST (response_model=List[AgentRead])
    // — the wrapped shapes are the other rails; assume neither, handle both.
    const rows = Array.isArray(r.data) ? r.data : (r.data?.agents || r.data?.items || [])
    localAgents.value = rows.map((a: any) => ({ did: a.did || a.agent_did, name: a.name }))
      .filter((a: any) => a.did)
    agentsFailed.value = false
  } catch { if (!localAgents.value.length) agentsFailed.value = true }
}

/* The authority line is READ, never composed here: the same endpoint the
   counterparty in a thread reads, so the owner can never see a ceiling a
   stranger would not. */
async function loadAwayAuthority() {
  try {
    const { data } = await apiClient.get('/chat/away/authority')
    awayAuthority.value = data
  } catch { awayAuthority.value = null }
}

const awayAuthorityLine = computed(() => {
  const a = awayAuthority.value
  if (!a) return t('pocket.more.awayAuthUnknown', 'Authority not read yet.')
  if (a.authorized) {
    return tp('pocket.more.awayAuthOn', 'Authorized up to {amt} {ccy} until {when}, underwritten by you.',
              { amt: a.ceiling, ccy: a.currency, when: (a.expires_at || '').slice(0, 16).replace('T', ' ') })
  }
  return tp('pocket.more.awayAuthOff', 'Cannot commit anything — {why}.',
            { why: a.reason || t('pocket.more.awayAuthNoGrant', 'no capability grant') })
})

async function saveAway() {
  if (awayRead.value !== 'read') return   // a whole-value write over a value nobody read would drop its other fields
  awayMsg.value = ''
  // INTENT vs EFFECT, kept apart deliberately. Enabling without a designation
  // would be a switch that promises a stand-in nobody named, so the effective
  // state stays off and says why — but the INTENT survives, or naming an agent
  // afterwards could never arm it (the battery caught exactly that).
  const enabled = awayWanted.value && !!awayAgentDid.value
  const grant = String(awayGrantId.value || '').trim()
  const cfg = { ...(awayCfg.value || {}), enabled, agent_did: awayAgentDid.value || null,
                note: awayNote.value || '',
                // The ID of a grant, never the token itself: OurState displays
                // authority, IRONKEY defines it, and a bearer secret has no
                // business in a preferences row.
                capability_token_id: grant ? Number(grant) : null }
  try {
    await apiClient.put('/developers/me/prefs/pocket.away', { value: cfg })
    awayCfg.value = cfg
    awayOn.value = enabled
    void loadAwayAuthority()
    awayMsg.value = enabled
      ? tp('pocket.more.awaySaved', '{name} will answer new strangers once, disclosed as software.', { name: awayAgentName.value })
      : (awayWanted.value && !awayAgentDid.value
          ? t('pocket.more.awayNeedsAgent', 'Pick an agent — away mode stays off until one is named.')
          : t('pocket.more.awayOffSaved', 'Off. Nobody answers for you.'))
  } catch (e: any) {
    awayMsg.value = e?.response?.data?.detail || t('pocket.common.requestFailed', 'request failed')
  }
}

function toggleAway() {
  if (awayRead.value !== 'read') return
  if (awayWanted.value) { awayWanted.value = false; awayOpen.value = false; void saveAway(); return }
  awayWanted.value = true
  awayOpen.value = true
  void saveAway()   // stays OFF server-side until an agent is named, and says so
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
  void loadAway()
  void loadHandle()
  void loadBlocks()
  void loadTerms()
  void loadAwayAuthority()
  void loadPulse()
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
