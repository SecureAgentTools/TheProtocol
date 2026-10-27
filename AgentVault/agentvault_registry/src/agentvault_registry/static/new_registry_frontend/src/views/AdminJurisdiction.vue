<template>
  <div class="jur-page">
    <header class="jur-hero" data-tour="juri-hero">
      <div>
        <div class="jur-eyebrow"><Icon name="mdi:scale-balance" :size="14" /> WATCHTOWER · JURISDICTION</div>
        <h1 class="jur-h1">{{ t('juriRegauth.title', 'Jurisdiction and Regulatory Authorizations') }}</h1>
        <p class="jur-sub">
          {{ t('juriRegauth.subtitle', 'Declare what the law applicable to this deployment permits, declare which lifecycle acts need state approval, and record the approvals you obtain. Declarations and recorded authorizations are published on the signed registry card: the claim is public, so the liability model is the verification.') }}
        </p>
      </div>
    </header>

    <div v-if="banner" class="jur-banner" :class="banner.ok ? 'jur-banner--ok' : 'jur-banner--err'">
      <Icon :name="banner.ok ? 'mdi:check-circle' : 'mdi:alert'" :size="14" /> {{ banner.text }}
    </div>

    <!-- ═══ Declared profile ═══ -->
    <section class="jur-card" data-tour="juri-profile">
      <div class="jur-card-head"><Icon name="mdi:file-document" :size="15" />
        {{ t('juriRegauth.profileHead', 'DECLARED JURISDICTION PROFILE') }}
        <span class="jur-pill" :class="modePillClass">{{ t('juriRegauth.globalMode', 'global mode') }}: {{ summary?.mode || '?' }}</span>
      </div>
      <template v-if="summary?.declared && summary.profile">
        <div class="jur-rows">
          <div class="jur-row"><label>{{ t('juriRegauth.profileName', 'Profile') }}</label><code>{{ summary.profile.name }} (v{{ summary.profile.version }})</code></div>
          <div class="jur-row"><label>{{ t('juriRegauth.featuresDenied', 'Features denied') }}</label>
            <code v-if="(summary.features_denied || []).length" class="jur-warm">{{ (summary.features_denied || []).join(', ') }}</code>
            <code v-else>{{ t('juriRegauth.none', 'none') }}</code>
          </div>
          <div class="jur-row"><label>{{ t('juriRegauth.declaredAt', 'Declared at') }}</label><code>{{ summary.profile.declared_at || '?' }}</code></div>
          <div class="jur-row"><label>{{ t('juriRegauth.profileHash', 'Profile hash') }}</label><code class="jur-hash">{{ summary.profile_hash }}</code></div>
        </div>
        <p class="jur-hint">{{ t('juriRegauth.profileHint', 'Feature allow/deny and limits are edited through the jurisdiction-profile API. This page manages the regulated-actions declaration and the authorization records.') }}</p>
      </template>
      <!-- §FESUITE (2026-10-05): over a failed read the three sections said "No jurisdiction profile is declared", "No
           regulated actions declared. Nothing parks; the rail is inert." and "Nothing on file yet" under the error banner:
           an all-clear on the compliance page that the page never read. Each says its read failed, with Try again. -->
      <ReadFailedNotice v-else-if="profileRead === 'failed'" dense :retry="loadProfile" data-testid="juri-profile-failed" />
      <p v-else-if="profileRead === 'ok'" class="jur-empty">
        {{ t('juriRegauth.noProfile', 'No jurisdiction profile is declared. Declaring a regulated action below creates a minimal profile carrying the declaration.') }}
      </p>
    </section>

    <!-- ═══ Regulated actions (the declaration) ═══ -->
    <section class="jur-card" data-tour="juri-regulated-actions">
      <div class="jur-card-head"><Icon name="mdi:gavel" :size="15" />
        {{ t('juriRegauth.regActionsHead', 'REGULATED ACTIONS') }}
        <button class="jur-btn jur-head-btn" :disabled="busy || !dirty" @click="saveRegulatedActions" data-testid="juri-save-actions">
          {{ busy ? t('juriRegauth.saving', 'Saving...') : t('juriRegauth.saveDeclaration', 'Save declaration') }}
        </button>
      </div>
      <p class="jur-hint jur-hint--block">
        {{ t('juriRegauth.regActionsHint', 'Each entry declares: this act needs approval from the named authority before it may proceed here. Mode shadow observes and logs; mode enforce parks the act with a checklist until an authorization is recorded. Entry-level enforce is live immediately after saving, even while the global mode stays shadow: you wrote it into your own declaration.') }}
      </p>

      <table v-if="regEntries.length" class="jur-table">
        <thead>
          <tr>
            <th>{{ t('juriRegauth.colAction', 'Action') }}</th>
            <th>{{ t('juriRegauth.colAuthority', 'Authority') }}</th>
            <th>{{ t('juriRegauth.colScope', 'Scope') }}</th>
            <th>{{ t('juriRegauth.colMode', 'Mode') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in regEntries" :key="entry.action" :data-testid="'juri-entry-' + entry.action">
            <td><code>{{ entry.action }}</code>
              <span v-if="displayOnly.includes(entry.action)" class="jur-pill jur-pill--dim" :title="t('juriRegauth.displayOnlyTip', 'Declared and published, but never gated: enforcing the deployment license would freeze the deployment that declares it.')">{{ t('juriRegauth.displayOnly', 'display only') }}</span>
            </td>
            <td><input v-model.trim="entry.authority" class="jur-input" maxlength="120" @input="dirty = true" /></td>
            <td>
              <select :aria-label="t('juriRegauth.scopeAria', 'Scope')" v-model="entry.scope" class="jur-input jur-input--sm" @change="dirty = true">
                <option value="registry">{{ t('juriRegauth.scopeRegistry', 'registry') }}</option>
                <option value="per_subject">{{ t('juriRegauth.scopePerSubject', 'per subject') }}</option>
              </select>
            </td>
            <td>
              <select :aria-label="t('juriRegauth.modeAria', 'Mode')" v-model="entry.mode" class="jur-input jur-input--sm" :class="entry.mode === 'enforce' ? 'jur-enforce' : ''" @change="dirty = true" :data-testid="'juri-mode-' + entry.action">
                <option value="shadow">shadow</option>
                <option value="enforce">enforce</option>
              </select>
            </td>
            <td><button class="jur-btn jur-btn--ghost jur-btn--xs" @click="removeEntry(entry.action)">{{ t('juriRegauth.remove', 'Remove') }}</button></td>
          </tr>
        </tbody>
      </table>
      <ReadFailedNotice v-else-if="profileRead === 'failed'" dense :retry="loadProfile" data-testid="juri-entries-failed" />
      <p v-else-if="profileRead === 'ok'" class="jur-empty">{{ t('juriRegauth.noEntries', 'No regulated actions declared. Nothing parks; the rail is inert.') }}</p>

      <div class="jur-add-row" v-if="addableActions.length">
        <select v-model="addAction" class="jur-input jur-input--sm" data-testid="juri-add-action" :aria-label="t('juriRegauth.addActionAria', 'Action to declare')">
          <option value="" disabled>{{ t('juriRegauth.pickAction', 'action...') }}</option>
          <option v-for="a in addableActions" :key="a" :value="a" :title="permissionTitle(a)">{{ permissionLabel(a) }}</option>
        </select>
        <input v-model.trim="addAuthority" class="jur-input" maxlength="120"
               :placeholder="t('juriRegauth.authorityPh', 'approving authority, e.g. the trade licensing office')" data-testid="juri-add-authority" />
        <button class="jur-btn" :disabled="!addAction || !addAuthority" @click="addEntry" data-testid="juri-add-btn">
          <Icon name="mdi:plus" :size="13" /> {{ t('juriRegauth.declare', 'Declare') }}
        </button>
      </div>
    </section>

    <!-- ═══ Authorizations on file ═══ -->
    <section class="jur-card" data-tour="juri-regauth-table">
      <div class="jur-card-head"><Icon name="mdi:certificate" :size="15" />
        {{ t('juriRegauth.authsHead', 'AUTHORIZATIONS ON FILE') }}
        <label class="jur-toggle jur-head-btn">
          <input type="checkbox" v-model="showRevoked" @change="loadAuthorizations" />
          {{ t('juriRegauth.showRevoked', 'show revoked') }}
        </label>
      </div>
      <table v-if="auths.length" class="jur-table">
        <thead>
          <tr>
            <th>{{ t('juriRegauth.colAction', 'Action') }}</th>
            <th>{{ t('juriRegauth.colSubject', 'Subject') }}</th>
            <th>{{ t('juriRegauth.colAuthority', 'Authority') }}</th>
            <th>{{ t('juriRegauth.colReference', 'Reference') }}</th>
            <th>{{ t('juriRegauth.colWindow', 'Valid') }}</th>
            <th>{{ t('juriRegauth.colStatus', 'Status') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="a in auths" :key="a.id">
            <tr :data-testid="'juri-auth-' + a.reference_id">
              <td><code :title="permissionTitle(a.action)">{{ permissionLabel(a.action) }}</code></td>
              <td><code>{{ a.subject_ref || t('juriRegauth.registryWide', 'registry-wide') }}</code></td>
              <td>{{ a.authority }}<span class="jur-dim"> · {{ a.jurisdiction }}</span></td>
              <td><code class="jur-ref">{{ a.reference_id }}</code>
                <Icon v-if="a.evidence_hash" name="mdi:lock" :size="12" :title="t('juriRegauth.evidenceTip', 'Document hash on file: ') + a.evidence_hash" />
                <button v-if="a.contract_ref" type="button" class="jur-iconbtn"
                        :class="a.contract_resolves === false ? 'jur-iconbtn--broken' : ''"
                        :data-testid="'juri-countersign-' + a.reference_id"
                        :title="(a.contract_resolves === false
                          ? t('juriRegauth.contractBrokenTip', 'Countersign broken: ') + (a.contract_problem || '?') + ' '
                          : t('juriRegauth.contractVerifyTip', 'Countersigned contract, click to verify in this browser: ')) + a.contract_ref"
                        @click="openAttestation(a)">
                  <Icon name="mdi:file-document-edit" :size="12" />
                </button>
              </td>
              <td class="jur-dim">{{ fmtWindow(a) }}</td>
              <td>
                <span class="jur-pill" :class="a.status === 'revoked' ? 'jur-pill--danger' : (a.live ? 'jur-pill--ok' : 'jur-pill--warn')">
                  {{ a.status === 'revoked' ? t('juriRegauth.revoked', 'revoked') : (a.live ? t('juriRegauth.live', 'live') : t('juriRegauth.expired', 'not in window')) }}
                </span>
              </td>
              <td>
                <button v-if="a.status === 'active'" class="jur-btn jur-btn--danger jur-btn--xs"
                        @click="revokeTarget = (revokeTarget === a.id ? '' : a.id)" :data-testid="'juri-revoke-' + a.reference_id">
                  {{ t('juriRegauth.revoke', 'Revoke') }}
                </button>
              </td>
            </tr>
            <tr v-if="revokeTarget === a.id">
              <td colspan="7" class="jur-revoke-row">
                <input v-model.trim="revokeReason" class="jur-input" maxlength="500"
                       :placeholder="t('juriRegauth.revokeReasonPh', 'reason (required, lands in the audit trail and the ledger)')" data-testid="juri-revoke-reason" />
                <button class="jur-btn jur-btn--danger" :disabled="!revokeReason || busy" @click="doRevoke(a.id)" data-testid="juri-revoke-confirm">
                  {{ t('juriRegauth.revokeConfirm', 'Confirm revoke') }}
                </button>
                <button class="jur-btn jur-btn--ghost" @click="revokeTarget = ''; revokeReason = ''">{{ t('juriRegauth.cancel', 'Cancel') }}</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <ReadFailedNotice v-else-if="authsRead === 'failed'" dense :retry="loadAuthorizations" data-testid="juri-auths-failed" />
      <p v-else-if="authsRead === 'ok'" class="jur-empty">{{ t('juriRegauth.noAuths', 'Nothing on file yet. Declared enforce-mode acts stay parked until a covering authorization is recorded below.') }}</p>
    </section>

    <!-- ═══ Record an authorization ═══ -->
    <section class="jur-card" data-tour="juri-regauth-record">
      <div class="jur-card-head"><Icon name="mdi:check-decagram" :size="15" /> {{ t('juriRegauth.recordHead', 'RECORD AN AUTHORIZATION') }}</div>
      <p class="jur-hint jur-hint--block">
        {{ t('juriRegauth.recordHint', 'You obtained approval from the authority out-of-band. Record its reference number here; the act it covers proceeds on the next attempt. The record is your attestation, published on the signed registry card.') }}
      </p>
      <div class="jur-form">
        <div class="jur-field">
          <label for="adminjurisdiction-sel-176">{{ t('juriRegauth.colAction', 'Action') }}</label>
          <select id="adminjurisdiction-sel-176" v-model="recForm.action" class="jur-input" data-testid="juri-rec-action">
            <option value="" disabled>{{ t('juriRegauth.pickAction', 'action...') }}</option>
            <option v-for="a in actions" :key="a" :value="a" :title="permissionTitle(a)">{{ permissionLabel(a) }}</option>
          </select>
        </div>
        <div class="jur-field">
          <label for="juri-rec-subject-field">{{ t('juriRegauth.subjectLabel', 'Subject (blank = registry-wide)') }}</label>
          <input id="juri-rec-subject-field" v-model.trim="recForm.subject_ref" class="jur-input" maxlength="255"
                 :placeholder="t('juriRegauth.subjectPh', 'e.g. the listing ticker: SMKD')" data-testid="juri-rec-subject" />
        </div>
        <div class="jur-field">
          <label for="juri-rec-authority-field">{{ t('juriRegauth.colAuthority', 'Authority') }}</label>
          <input id="juri-rec-authority-field" v-model.trim="recForm.authority" class="jur-input" maxlength="200" data-testid="juri-rec-authority"
                 :placeholder="t('juriRegauth.authorityPh2', 'who approved it')" />
        </div>
        <div class="jur-field">
          <label for="juri-rec-jurisdiction-field">{{ t('juriRegauth.jurisdictionLabel', 'Jurisdiction') }}</label>
          <input id="juri-rec-jurisdiction-field" v-model.trim="recForm.jurisdiction" class="jur-input" maxlength="120" data-testid="juri-rec-jurisdiction"
                 :placeholder="t('juriRegauth.jurisdictionPh', 'e.g. DE, US-NY, EU')" />
        </div>
        <div class="jur-field" data-tour="juri-record-reference">
          <label for="juri-rec-reference-field">{{ t('juriRegauth.referenceLabel', 'Reference id (the state\'s cert or file number)') }}</label>
          <input id="juri-rec-reference-field" v-model.trim="recForm.reference_id" class="jur-input" maxlength="255" data-testid="juri-rec-reference"
                 :placeholder="t('juriRegauth.referencePh', 'e.g. WA-2026/0815-XYZ')" />
        </div>
        <div class="jur-field">
          <label for="juri-rec-from-field">{{ t('juriRegauth.validFromLabel', 'Valid from (blank = now)') }}</label>
          <input id="juri-rec-from-field" v-model="recForm.valid_from" type="datetime-local" class="jur-input" data-testid="juri-rec-from" />
        </div>
        <div class="jur-field">
          <label for="juri-rec-until-field">{{ t('juriRegauth.validUntilLabel', 'Valid until (blank = open-ended)') }}</label>
          <input id="juri-rec-until-field" v-model="recForm.valid_until" type="datetime-local" class="jur-input" data-testid="juri-rec-until" />
        </div>
        <div class="jur-field jur-field--wide" data-tour="juri-record-evidence">
          <label for="juri-rec-evidence-file-field">{{ t('juriRegauth.evidenceLabel', 'Approval document (hashed in your browser; the file never uploads)') }}</label>
          <input id="juri-rec-evidence-file-field" type="file" class="jur-input jur-file" @change="hashEvidenceFile" data-testid="juri-rec-evidence-file" />
          <code v-if="recForm.evidence_hash" class="jur-hash" data-testid="juri-rec-evidence-hash">{{ recForm.evidence_hash }}</code>
        </div>
        <div class="jur-field jur-field--wide">
          <label for="juri-rec-contract-field">{{ t('juriRegauth.contractLabel', 'Countersigned contract ref (optional, strongest tier)') }}</label>
          <input id="juri-rec-contract-field" v-model.trim="recForm.contract_ref" class="jur-input" maxlength="255" data-testid="juri-rec-contract"
                 list="juri-attestation-candidates"
                 :placeholder="t('juriRegauth.contractPh', 'a contract ref countersigned by an authorized representative on this network')" />
          <datalist id="juri-attestation-candidates">
            <option v-for="cd in candidates" :key="cd.id" :value="cd.id">
              {{ cd.title }}{{ cd.referenced ? ' ' + t('juriRegauth.alreadyReferenced', '[already referenced]') : '' }}
            </option>
          </datalist>
          <p class="jur-hint">{{ t('juriRegauth.contractPublicNote', 'Referencing a contract publishes it: its title, parties and full terms become publicly readable proof at /api/v1/jurisdiction/contracts/{id} and its digest rides the signed card. The ref must point at an agreed, zero-value contract; anything else is refused at record time.') }}</p>
        </div>
        <div class="jur-field jur-field--wide">
          <label for="juri-rec-note-field">{{ t('juriRegauth.noteLabel', 'Note (private, admin-only)') }}</label>
          <input id="juri-rec-note-field" v-model.trim="recForm.evidence_note" class="jur-input" maxlength="1000" />
        </div>
      </div>
      <div class="jur-form-actions">
        <button class="jur-btn" :disabled="!canRecord || busy" @click="doRecord" data-testid="juri-rec-submit">
          <Icon name="mdi:check-decagram" :size="13" /> {{ busy ? t('juriRegauth.recording', 'Recording...') : t('juriRegauth.recordBtn', 'Record authorization') }}
        </button>
      </div>
    </section>

    <!-- ═══ §VCSIGN-2: draft the countersign contract ═══ -->
    <section class="jur-card">
      <div class="jur-card-head"><Icon name="mdi:file-document-edit" :size="15" />
        {{ t('juriRegauth.draftHead', 'DRAFT A COUNTERSIGN CONTRACT') }}
      </div>
      <p class="jur-hint jur-hint--block">
        {{ t('juriRegauth.draftHint', 'The strongest evidence tier without the API work: your ACTIVE agent authors a zero-value attestation contract from the record form fields above (authority, jurisdiction, reference, document hash) and offers it to the countersigner. Once they accept, it becomes agreed, shows up in the picker above, and you record the authorization with its id. Its title, parties and full terms become PUBLIC the moment you reference it.') }}
      </p>
      <p v-if="!attestingAgent?.did" class="jur-hint" data-testid="juri-draft-needsagent">
        {{ t('juriRegauth.draftNeedsAgent', 'Select an active agent first: the attesting party authors the contract with its own signature.') }}
      </p>
      <template v-else>
        <div class="jur-form">
          <div class="jur-field jur-field--wide">
            <label for="juri-draft-provider-field">{{ t('juriRegauth.draftProviderLabel', 'Countersigner agent DID (the authority\'s authorized representative)') }}</label>
            <input id="juri-draft-provider-field" v-model.trim="draftForm.provider_did" class="jur-input" maxlength="255" data-testid="juri-draft-provider"
                   placeholder="did:theprotocol:..." />
          </div>
          <div class="jur-field jur-field--wide">
            <label for="juri-draft-covers-field">{{ t('juriRegauth.draftCoversLabel', 'What the approval covers (one sentence)') }}</label>
            <input id="juri-draft-covers-field" v-model.trim="draftForm.covers" class="jur-input" maxlength="500" data-testid="juri-draft-covers" />
          </div>
          <div class="jur-field jur-field--wide">
            <label for="juri-draft-meaning-field">{{ t('juriRegauth.draftMeaningLabel', 'Jurisdictional meaning (published verbatim)') }}</label>
            <textarea id="juri-draft-meaning-field" v-model.trim="draftForm.meaning" class="jur-input jur-textarea" maxlength="2000" rows="4"
                      data-testid="juri-draft-meaning"></textarea>
          </div>
        </div>
        <div class="jur-form-actions">
          <button class="jur-btn" :disabled="!canDraft || draftBusy" @click="doDraftCountersign" data-testid="juri-draft-submit">
            <Icon name="mdi:check-decagram" :size="13" />
            {{ draftBusy ? t('juriRegauth.drafting', 'Creating...') : t('juriRegauth.draftBtn', 'Create and offer to the countersigner') }}
          </button>
          <span v-if="!canDraft && authStore.activeAgent?.did" class="jur-dim">
            {{ t('juriRegauth.draftPrereq', 'Needs authority, jurisdiction and reference filled in the record form above, plus the two fields here.') }}
          </span>
        </div>
        <p v-if="draftResult" class="jur-hint" data-testid="juri-draft-result">
          {{ t('juriRegauth.draftResultA', 'Created and offered: ') }}<code>{{ draftResult.id }}</code>
          {{ t('juriRegauth.draftResultB', ' awaiting acceptance by ') }}<code>{{ draftResult.provider }}</code>
        </p>
      </template>
    </section>

    <!-- ═══ How the park works ═══ -->
    <section class="jur-card" data-tour="juri-how">
      <div class="jur-card-head"><Icon name="mdi:clipboard" :size="15" /> {{ t('juriRegauth.howHead', 'HOW A PARKED ACT LOOKS') }}</div>
      <p class="jur-hint">
        {{ t('juriRegauth.howBody', 'With an entry in enforce mode and nothing on file, the act answers 409 with a checklist naming the action, the authority, and this page. The AGORA admin desk renders that checklist on a blocked listing approval. Record the reference, retry the act, done. Public proof: the signed registry card carries every live authorization, and anyone can read them at /api/v1/jurisdiction/authorizations.') }}
      </p>
    </section>

    <ContractAttestationModal v-model:show="attestShow" :cid="attestCid" base-url="" :reference-id="attestRef" />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * REGAUTH (SPEC 2026-08-15) — the first UI over the jurisdiction profile, plus
 * the regulatory-authorizations rail: declare which lifecycle acts need state
 * approval, record the approvals, revoke them. Watchtower house style
 * (AdminEnforcement conventions); admin_platform-gated backend.
 */
import { computed, defineAsyncComponent, onMounted, reactive, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'

// §VCSIGN: the countersign icon opens the referenced attestation contract and
// re-verifies its digest in this browser (shared modal, lazy).
const ContractAttestationModal = defineAsyncComponent(() =>
  import('@/components/common/ContractAttestationModal.vue'))
import {
  jurisdictionAdminService,
  type AttestationCandidate,
  type ProfileSummary,
  type RegulatoryAuthorization,
} from '@/services/api/jurisdictionAdmin'
import { contractsV2Api } from '@/services/api/contractsV2'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { useAuthStore } from '@/stores/auth'
import { permissionLabel, permissionTitle } from '@/services/permissionLabel'

const { t } = useI18n()

const summary = ref<ProfileSummary | null>(null)
const auths = ref<RegulatoryAuthorization[]>([])

// §VCSIGN modal state (local registry, so base-url stays '')
const attestShow = ref(false)
const attestCid = ref<string | null>(null)
const attestRef = ref<string | null>(null)
function openAttestation(a: RegulatoryAuthorization) {
  attestCid.value = a.contract_ref || null
  attestRef.value = a.reference_id || null
  attestShow.value = true
}

// §VCSIGN-2: countersign picker + draft helper
const authStore = useAuthStore()
// This is an ADMIN route, so the auth store may not have hydrated the active
// agent (that runs on requiresAgent routes). Resolve the attesting party from
// the store OR the credentials vault directly — full creds either way, so the
// agent JWT can always be minted before the create.
function resolveAttestingAgent(): any | null {
  const a = authStore.activeAgent
  if (a?.client_id && a?.client_secret) return a
  try {
    const did = a?.did || localStorage.getItem('activeAgentId') || ''
    if (!did) return null
    const stored = agentCredentialsStore.getCredentials(did)
    if (stored?.client_id && stored?.client_secret) return { did, ...stored }
  } catch { /* vault unavailable */ }
  return null
}
const attestingAgent = computed(() => resolveAttestingAgent())
async function ensureAgentAuth(): Promise<boolean> {
  if (authStore.agentToken) return true
  const agent = resolveAttestingAgent()
  if (!agent) return false
  return authStore.authenticateAsAgent(agent)
}
const candidates = ref<AttestationCandidate[]>([])
async function loadCandidates() {
  try { candidates.value = await jurisdictionAdminService.listAttestationCandidates() }
  catch { candidates.value = [] }  // picker is convenience; the form still takes free input
}

const draftForm = reactive({ provider_did: '', covers: '', meaning: '' })
const DEFAULT_MEANING =
  'What this contract represents in the jurisdictional sense: the client attests that the ' +
  'referenced approval was granted by the named authority; the provider countersigns that ' +
  'attestation by accepting, acting as the authority\'s authorized representative (registrar, ' +
  'counsel, or notary). Zero value moves: this is an agreement-only instrument.'
draftForm.meaning = DEFAULT_MEANING
const draftBusy = ref(false)
const draftResult = ref<{ id: string; provider: string } | null>(null)
const canDraft = computed(() =>
  !!attestingAgent.value?.did && !!draftForm.provider_did.trim() && !!draftForm.covers.trim()
  && !!draftForm.meaning.trim() && !!recForm.authority.trim() && !!recForm.jurisdiction.trim()
  && !!recForm.reference_id.trim())

async function doDraftCountersign() {
  if (!canDraft.value || draftBusy.value) return
  draftBusy.value = true
  draftResult.value = null
  try {
    if (!(await ensureAgentAuth())) {
      err(null, t('juriRegauth.draftNoCreds',
        'The active agent has no stored credentials in this browser, so it cannot sign the contract. Add its credentials in the agent switcher first.'))
      return
    }
    const attesting = resolveAttestingAgent()
    const terms: Record<string, any> = {
      instrument: 'regulatory_attestation',
      authorization_reference: recForm.reference_id.trim(),
      authority: recForm.authority.trim(),
      jurisdiction: recForm.jurisdiction.trim(),
      covers: draftForm.covers.trim(),
      client_capacity: attesting?.name || attesting?.did,
      provider_capacity: 'Authorized representative of ' + recForm.authority.trim(),
      jurisdictional_meaning: draftForm.meaning.trim(),
    }
    if (recForm.evidence_hash) terms.approval_document_sha256 = recForm.evidence_hash
    const c = await contractsV2Api.create({
      title: `Countersigned attestation ${recForm.reference_id.trim()}: ${draftForm.covers.trim().slice(0, 120)}`,
      contract_type: 'license',
      total_amount: 0,
      terms,
      provider_did: draftForm.provider_did.trim(),
    })
    if (c.status === 'draft') await contractsV2Api.offer(c.id)
    draftResult.value = { id: c.id, provider: draftForm.provider_did.trim() }
    ok(t('juriRegauth.draftOk',
      'Attestation contract created and offered to the countersigner. Once they accept, it becomes agreed and appears in the picker above; record the authorization with its id then.'))
    await loadCandidates()
  } catch (e: any) {
    err(e, t('juriRegauth.draftFailed', 'Drafting the countersign contract failed'))
  } finally {
    draftBusy.value = false
  }
}
const actions = ref<string[]>([])
const displayOnly = ref<string[]>([])
const showRevoked = ref(false)
const busy = ref(false)
const dirty = ref(false)
const banner = ref<{ ok: boolean; text: string } | null>(null)

interface RegEntry { action: string; authority: string; scope: 'registry' | 'per_subject'; mode: 'shadow' | 'enforce'; note?: string }
const regEntries = ref<RegEntry[]>([])
const addAction = ref('')
const addAuthority = ref('')

const revokeTarget = ref('')
const revokeReason = ref('')

const recForm = reactive({
  action: '', subject_ref: '', authority: '', jurisdiction: '',
  reference_id: '', valid_from: '', valid_until: '',
  evidence_hash: '', evidence_note: '', contract_ref: '',
})

const DEFAULT_SCOPE: Record<string, 'registry' | 'per_subject'> = {
  'exchange.listing': 'per_subject',
  'exchange.ipo': 'per_subject',
  'fiat.lane': 'registry',
  'registry.operation': 'registry',
}

const modePillClass = computed(() =>
  summary.value?.mode === 'enforce' ? 'jur-pill--danger'
    : summary.value?.mode === 'shadow' ? 'jur-pill--warn' : 'jur-pill--dim')

const addableActions = computed(() =>
  actions.value.filter(a => !regEntries.value.some(e => e.action === a)))

const canRecord = computed(() =>
  !!(recForm.action && recForm.authority.trim() && recForm.jurisdiction.trim() && recForm.reference_id.trim()))

function ok(text: string) { banner.value = { ok: true, text }; window.setTimeout(() => { if (banner.value?.text === text) banner.value = null }, 6000) }
function err(e: any, fallback: string) {
  let d = e?.response?.data?.detail ?? e?.message ?? fallback
  if (typeof d === 'string' && d.trim().startsWith('{')) { try { d = JSON.parse(d) } catch { /* keep the string */ } }
  if (typeof d === 'object' && d) {
    // errors.py stringifies dict details; surface the errors LIST too, else a
    // refused contract_ref reads as a bare "invalid authorization record".
    const msg = d.message || ''
    const errs = Array.isArray(d.errors) && d.errors.length ? ': ' + d.errors.join('; ') : ''
    d = (msg + errs) || JSON.stringify(d)
  }
  banner.value = { ok: false, text: String(d) }
}

function fmtWindow(a: RegulatoryAuthorization): string {
  const from = a.valid_from ? new Date(a.valid_from).toLocaleDateString(appLocale()) : '?'
  const until = a.valid_until
    ? new Date(a.valid_until).toLocaleDateString(appLocale())
    : t('juriRegauth.openEnded', 'open-ended')
  return `${from} -> ${until}`
}

function syncEntriesFromProfile() {
  const block = summary.value?.profile?.requires_authorization || {}
  regEntries.value = Object.entries(block).map(([action, e]) => ({
    action,
    authority: e?.authority || '',
    scope: (e?.scope as any) || DEFAULT_SCOPE[action] || 'registry',
    mode: (e?.mode as any) || 'shadow',
    ...(e?.note ? { note: e.note } : {}),
  })).sort((x, y) => x.action.localeCompare(y.action))
  dirty.value = false
}

// each read's own state: a section says "none" only after its read answered; a failed refresh keeps what it showed
const profileRead = ref<'loading' | 'ok' | 'failed'>('loading')
const authsRead = ref<'loading' | 'ok' | 'failed'>('loading')

async function loadProfile() {
  try {
    summary.value = await jurisdictionAdminService.getProfile()
  } catch (e) {
    if (profileRead.value !== 'ok') profileRead.value = 'failed'
    throw e
  }
  profileRead.value = 'ok'
  syncEntriesFromProfile()
}

async function loadAuthorizations() {
  let res
  try {
    res = await jurisdictionAdminService.listAuthorizations(showRevoked.value)
  } catch (e) {
    if (authsRead.value !== 'ok') authsRead.value = 'failed'
    throw e
  }
  authsRead.value = 'ok'
  auths.value = res.authorizations
  actions.value = res.actions
  displayOnly.value = res.display_only_actions
}

function addEntry() {
  if (!addAction.value || !addAuthority.value.trim()) return
  regEntries.value.push({
    action: addAction.value,
    authority: addAuthority.value.trim(),
    scope: DEFAULT_SCOPE[addAction.value] || 'registry',
    mode: 'shadow',
  })
  regEntries.value.sort((x, y) => x.action.localeCompare(y.action))
  addAction.value = ''
  addAuthority.value = ''
  dirty.value = true
}

function removeEntry(action: string) {
  regEntries.value = regEntries.value.filter(e => e.action !== action)
  dirty.value = true
}

async function saveRegulatedActions() {
  if (busy.value) return
  busy.value = true
  try {
    // Fetch-fresh -> merge -> PUT: the profile document is the single artifact,
    // so this page must never clobber features/limits another surface declared.
    const fresh = await jurisdictionAdminService.getProfile()
    const base = fresh.profile || {
      name: t('juriRegauth.defaultProfileName', 'Operator declaration'),
      version: 0,
      features: {},
    }
    const block: Record<string, any> = {}
    for (const e of regEntries.value) {
      if (!e.authority.trim()) throw new Error(t('juriRegauth.authorityRequired', 'Every declared action needs an authority.'))
      block[e.action] = { authority: e.authority.trim(), scope: e.scope, mode: e.mode, ...(e.note ? { note: e.note } : {}) }
    }
    const next: any = { ...base, version: (Number(base.version) || 0) + 1 }
    delete next.declared_at  // the server stamps it
    if (Object.keys(block).length) next.requires_authorization = block
    else delete next.requires_authorization
    summary.value = await jurisdictionAdminService.putProfile(next)
    syncEntriesFromProfile()
    ok(t('juriRegauth.savedOk', 'Declaration saved. Enforce-mode entries are live now.'))
  } catch (e: any) {
    err(e, t('juriRegauth.saveFailed', 'Saving the declaration failed'))
  } finally {
    busy.value = false
  }
}

/** SubtleCrypto sha256 of the picked file. The bytes never leave this machine;
 *  only the hash is submitted (evidence tier 2). */
async function hashEvidenceFile(ev: Event) {
  const file = (ev.target as HTMLInputElement)?.files?.[0]
  if (!file) { recForm.evidence_hash = ''; return }
  try {
    const buf = await file.arrayBuffer()
    const digest = await crypto.subtle.digest('SHA-256', buf)
    const hex = Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('')
    recForm.evidence_hash = `sha256:${hex}`
  } catch (e: any) {
    err(e, t('juriRegauth.hashFailed', 'Hashing the document failed'))
  }
}

function toIso(local: string): string | null {
  if (!local) return null
  const d = new Date(local)
  return isNaN(d.getTime()) ? null : d.toISOString()
}

async function doRecord() {
  if (!canRecord.value || busy.value) return
  busy.value = true
  try {
    await jurisdictionAdminService.recordAuthorization({
      action: recForm.action,
      subject_ref: recForm.subject_ref.trim() || null,
      authority: recForm.authority.trim(),
      jurisdiction: recForm.jurisdiction.trim(),
      reference_id: recForm.reference_id.trim(),
      valid_from: toIso(recForm.valid_from),
      valid_until: toIso(recForm.valid_until),
      evidence_hash: recForm.evidence_hash || null,
      evidence_note: recForm.evidence_note.trim() || null,
      contract_ref: recForm.contract_ref.trim() || null,
    })
    ok(t('juriRegauth.recordedOk', 'Authorization recorded. The covered act proceeds on its next attempt; the signed card picks it up on the next build.'))
    Object.assign(recForm, { action: '', subject_ref: '', authority: '', jurisdiction: '', reference_id: '', valid_from: '', valid_until: '', evidence_hash: '', evidence_note: '', contract_ref: '' })
    await loadAuthorizations()
  } catch (e: any) {
    err(e, t('juriRegauth.recordFailed', 'Recording failed'))
  } finally {
    busy.value = false
  }
}

async function doRevoke(id: string) {
  if (!revokeReason.value.trim() || busy.value) return
  busy.value = true
  try {
    await jurisdictionAdminService.revokeAuthorization(id, revokeReason.value.trim())
    ok(t('juriRegauth.revokedOk', 'Authorization revoked. The act parks again on its next attempt.'))
    revokeTarget.value = ''
    revokeReason.value = ''
    await loadAuthorizations()
  } catch (e: any) {
    err(e, t('juriRegauth.revokeFailed', 'Revoke failed'))
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    await Promise.all([loadProfile(), loadAuthorizations(), loadCandidates()])
  } catch (e: any) {
    err(e, t('juriRegauth.loadFailed', 'Loading the jurisdiction state failed'))
  }
})
</script>

<style scoped>
.jur-page { max-width: 1120px; margin: 0 auto; padding: 24px 20px 80px; }
.jur-hero { margin-bottom: 18px; }
.jur-eyebrow { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; letter-spacing: 2px; color: var(--brand-primary, #00e5ff); opacity: .85; }
.jur-h1 { margin: 6px 0 4px; font-size: 26px; }
.jur-sub { margin: 0; max-width: 780px; color: var(--text-secondary, #9ab); font-size: 13.5px; line-height: 1.55; }

.jur-banner { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 8px; font-size: 13px; margin-bottom: 14px; border: 1px solid; }
.jur-banner--ok { border-color: rgba(0, 220, 130, .4); background: rgba(0, 220, 130, .08); color: #7ce8b8; }
.jur-banner--err { border-color: rgba(255, 90, 90, .45); background: rgba(255, 90, 90, .08); color: #ff9c9c; }

.jur-card { border: 1px solid var(--border-color, rgba(120, 160, 200, .18)); border-radius: 12px; background: var(--bg-elevated, rgba(10, 18, 30, .55)); padding: 16px 18px; margin-bottom: 18px; }
.jur-card-head { display: flex; align-items: center; gap: 8px; font-size: 12px; letter-spacing: 1.6px; color: var(--text-secondary, #9ab); margin-bottom: 12px; }
.jur-head-btn { margin-left: auto; }

.jur-rows { display: grid; gap: 6px; }
.jur-row { display: flex; gap: 12px; align-items: baseline; font-size: 13px; }
.jur-row label { flex: 0 0 140px; color: var(--text-secondary, #9ab); font-size: 12px; }
.jur-row code { color: var(--text-primary, #e8f1fa); }
.jur-warm { color: #f59e0b !important; }
.jur-hash { font-size: 11px; word-break: break-all; opacity: .85; }
.jur-dim { color: var(--text-secondary, #9ab); font-size: 12px; }
.jur-ref { color: var(--brand-primary, #00e5ff); }

.jur-hint { font-size: 12.5px; color: var(--text-secondary, #9ab); line-height: 1.5; margin: 8px 0 0; }
.jur-hint--block { margin: -2px 0 12px; }
.jur-iconbtn { background: transparent; border: none; padding: 0 2px; cursor: pointer; color: #2dd4bf; vertical-align: middle; }
.jur-iconbtn:hover { filter: brightness(1.35); }
.jur-iconbtn--broken { color: #f87171; }
.jur-empty { font-size: 13px; color: var(--text-secondary, #9ab); margin: 4px 0; }

.jur-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.jur-table th { text-align: left; padding: 6px 8px; color: var(--text-secondary, #9ab); font-size: 11px; letter-spacing: 1px; text-transform: uppercase; border-bottom: 1px solid var(--border-color, rgba(120, 160, 200, .18)); }
.jur-table td { padding: 7px 8px; border-bottom: 1px solid rgba(120, 160, 200, .08); vertical-align: middle; }

.jur-input { background: rgba(0, 0, 0, .25); border: 1px solid var(--border-color, rgba(120, 160, 200, .25)); border-radius: 8px; color: var(--text-primary, #e8f1fa); padding: 7px 10px; font-size: 13px; width: 100%; min-width: 0; }
.jur-input--sm { width: auto; }
.jur-textarea { resize: vertical; font-family: inherit; line-height: 1.45; }
.jur-file { padding: 5px 8px; }
.jur-enforce { border-color: #ff5a5a; color: #ff8a8a; }

.jur-btn { border: 1px solid var(--brand-primary, #00e5ff); background: transparent; color: var(--brand-primary, #00e5ff); border-radius: 8px; padding: 7px 14px; font-size: 12.5px; cursor: pointer; white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; }
.jur-btn:disabled { opacity: .4; cursor: default; }
.jur-btn--ghost { border-color: var(--border-color, rgba(120, 160, 200, .35)); color: var(--text-secondary, #9ab); }
.jur-btn--danger { border-color: #ff5a5a; color: #ff7a7a; }
.jur-btn--xs { padding: 4px 9px; font-size: 11.5px; }

.jur-pill { padding: 2px 9px; border-radius: 999px; font-size: 10.5px; letter-spacing: .8px; text-transform: uppercase; border: 1px solid; margin-left: 8px; }
.jur-pill--ok { border-color: rgba(0, 220, 130, .5); color: #7ce8b8; }
.jur-pill--warn { border-color: rgba(240, 180, 41, .55); color: #f0c95c; }
.jur-pill--danger { border-color: rgba(255, 90, 90, .55); color: #ff8a8a; }
.jur-pill--dim { border-color: var(--border-color, rgba(120, 160, 200, .35)); color: var(--text-secondary, #9ab); }

.jur-add-row { display: flex; gap: 10px; margin-top: 12px; }
.jur-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary, #9ab); cursor: pointer; letter-spacing: normal; text-transform: none; }
.jur-revoke-row { display: flex; gap: 10px; align-items: center; background: rgba(255, 90, 90, .05); }

.jur-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.jur-field { display: flex; flex-direction: column; gap: 5px; }
.jur-field label { font-size: 11.5px; color: var(--text-secondary, #9ab); }
.jur-field--wide { grid-column: 1 / -1; }
.jur-form-actions { margin-top: 14px; display: flex; justify-content: flex-end; }

@media (max-width: 720px) {
  .jur-add-row { flex-direction: column; }
  .jur-table { display: block; overflow-x: auto; }
}
</style>
