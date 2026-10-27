<template>
  <section class="op-tab op-account">
    <!-- §FESUITE (2026-10-10, the operator batch): a cloud operator provisions no operators (its server answers the
         provisioning rails with "runs on sovereign mainframes only"), so on one this tab asks nothing and says where an
         operator is applied for: its frame's console -->
    <div v-if="onOperator" class="op-account-onop" data-testid="op-on-operator">
      <div class="op-account-elig-eyebrow">{{ t('operatorPortalView.onOperator.eyebrow', 'Cloud provisioning') }}</div>
      <p class="op-account-elig-sub">
        {{ ownFrame?.display_name || ownFrame?.name
          ? tp('operatorPortalView.onOperator.bodyNamed', 'This registry is a cloud operator of {frame}. Cloud operators are applied for and provisioned on their frame, not on an operator.', { frame: ownFrame?.display_name || ownFrame?.name })
          : t('operatorPortalView.onOperator.body', 'This registry is a cloud operator. Cloud operators are applied for and provisioned on their frame, not on an operator.') }}
      </p>
      <a v-if="frameConsole" :href="`${frameConsole}/#/operator?tab=cloud`" class="op-link" data-testid="op-on-operator-frame">
        {{ tp('operatorPortalView.onOperator.link', 'Apply on {frame} →', { frame: ownFrame?.display_name || ownFrame?.name || '' }) }}
      </a>
    </div>
    <template v-else>
    <!-- Eligibility hero -->
    <div
      class="op-account-eligibility"
      :class="{
        'op-account-eligibility--locked': eligibilityLoaded && !eligibilityFailed && !eligibility?.is_unlocked,
        'op-account-eligibility--unlocked': eligibilityLoaded && eligibility?.is_unlocked,
      }"
    >
      <div class="op-account-elig-left">
        <div class="op-account-elig-eyebrow">Cloud provisioning</div>
        <h2 class="op-account-elig-title">
          <span v-if="!eligibilityLoaded">Loading…</span>
          <span v-else-if="eligibilityFailed">—</span>
          <span v-else-if="eligibility?.is_unlocked">Granted · {{ monthsLabel }} left</span>
          <span v-else>Free for testing</span>
        </h2>
        <!-- §FESUITE (V0577): a failed eligibility read is not "free for testing, apply": it hid the provisioning form
             from an operator whose provisioning is granted -->
        <ReadFailedNotice v-if="eligibilityFailed" dense :retry="loadEligibility" data-testid="op-elig-failed" />
        <p v-else class="op-account-elig-sub">
          <!-- §LANDINGTRUTH (his words 2026-10-02 "cloud operators are free for testing there is no fiat lane anymore",
               "remove the owner portal euro unlock too"): the network team grants provisioning; nothing is bought. -->
          <template v-if="eligibility?.is_unlocked">
            Provisioning granted until {{ formatAbsolute(eligibility?.unlocked_until) }}.
          </template>
          <template v-else-if="(eligibility?.months_total_purchased ?? 0) > 0">
            Your provisioning grant has ended. Cloud operators stay free for testing: apply again and the network team
            extends it.
            <router-link to="/operator?tab=cloud" class="op-link">Apply for a free test operator →</router-link>
          </template>
          <template v-else>
            Cloud operators are free for testing. Apply, and once the network team grants provisioning, the form
            below opens here.
            <router-link to="/operator?tab=cloud" class="op-link">Apply for a free test operator →</router-link>
          </template>
        </p>
      </div>
      <div class="op-account-elig-ring" v-if="eligibility?.is_unlocked">
        <svg class="op-account-ring-svg" viewBox="0 0 80 80">
          <circle cx="40" cy="40" r="36" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="3" />
          <circle
            cx="40" cy="40" r="36" fill="none"
            stroke="#00e676" stroke-width="3" stroke-linecap="round"
            :stroke-dasharray="ringDashArray"
            :stroke-dashoffset="ringDashOffset"
            transform="rotate(-90 40 40)"
            style="transition: stroke-dashoffset 0.6s ease;"
          />
          <text x="40" y="44" text-anchor="middle" class="op-account-ring-text">{{ monthsRemainingNum }}</text>
        </svg>
        <div class="op-account-ring-label">months</div>
      </div>
    </div>

    <!-- My cloud operators grid -->
    <div class="op-account-section">
      <h3 class="op-account-section-title">My cloud operators</h3>
      <div v-if="!opsLoaded" class="op-account-loading">Loading…</div>
      <ReadFailedNotice v-else-if="opsFailed" dense :retry="loadStatus" data-testid="op-ops-failed" />
      <div v-else-if="myCloudOps.length === 0" class="op-account-empty">
        You haven't provisioned a cloud operator yet.
        <template v-if="eligibility?.is_unlocked"> Use the form below to provision one.</template>
      </div>
      <div v-else class="op-account-ops-grid">
        <div v-for="op in myCloudOps" :key="op.application_id" class="op-account-op-card">
          <div class="op-account-op-header">
            <div class="op-account-op-name">{{ op.name }}</div>
            <span
              :class="['op-account-op-health',
                op.healthy === true ? 'op-account-op-health--ok'
                : op.healthy === false ? 'op-account-op-health--down'
                : 'op-account-op-health--unknown'
              ]"
            >
              {{ op.healthy === true ? 'healthy' : op.healthy === false ? 'down' : 'unknown' }}
            </span>
          </div>
          <a class="op-account-op-url" :href="safeExternalUrl(op.cloud_url)" target="_blank" rel="noopener">{{ op.cloud_url }}</a>
          <div class="op-account-op-meta">
            <span v-if="op.cloud_provisioned_at">provisioned {{ formatRelative(op.cloud_provisioned_at) }}</span>
            <span v-if="op.cloud_port_base">port :{{ op.cloud_port_base }}</span>
          </div>
          <div class="op-account-op-actions">
            <a class="op-btn-ghost" :href="safeExternalUrl(op.cloud_url + '/ui')" target="_blank" rel="noopener">Open UI</a>
            <a class="op-btn-ghost" :href="safeExternalUrl(op.cloud_url + '/.well-known/registry-card.json')" target="_blank" rel="noopener">Card JSON</a>
          </div>
        </div>
      </div>
    </div>

    <!-- Provision form (gated) -->
    <div class="op-account-section" v-if="eligibility?.is_unlocked">
      <h3 class="op-account-section-title">Provision a new cloud operator</h3>
      <!-- §pass66 (2026-05-22) — Path C: Quick / Advanced tab toggle.
           Quick = current 3-field form (default). Advanced adds optional
           Registry Card v0.3 overrides (visual, persona, commitments, links). -->
      <div class="op-account-prov-tabs">
        <button
          type="button"
          class="op-account-prov-tab"
          :class="{ 'op-account-prov-tab--active': provisionMode === 'quick' }"
          :disabled="provisioning"
          @click="provisionMode = 'quick'"
        >
          Quick
          <span class="op-account-prov-tab-hint">3-field form</span>
        </button>
        <button
          type="button"
          class="op-account-prov-tab"
          :class="{ 'op-account-prov-tab--active': provisionMode === 'advanced' }"
          :disabled="provisioning"
          @click="provisionMode = 'advanced'"
        >
          Advanced
          <span class="op-account-prov-tab-hint">+ visual + persona + SLA + links</span>
        </button>
      </div>
      <div class="op-account-provision">
        <form @submit.prevent="onProvision" class="op-account-provision-form">
          <label class="op-account-label">
            <span>Name <span class="op-account-required">*</span></span>
            <input
              v-model="provisionForm.name"
              type="text"
              class="op-account-input"
              placeholder="e.g. op-alice"
              required
              pattern="^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$"
              :disabled="provisioning"
            />
            <span class="op-account-hint">Lowercase alphanumeric + hyphens. 3-40 chars. Becomes part of your cloud URL.</span>
          </label>
          <label class="op-account-label">
            <span>Organization</span>
            <input
              v-model="provisionForm.organization"
              type="text"
              class="op-account-input"
              placeholder="optional — your company or collective"
              :disabled="provisioning"
            />
          </label>
          <label class="op-account-label">
            <span>Use case</span>
            <textarea
              v-model="provisionForm.use_case"
              class="op-account-input op-account-textarea"
              placeholder="optional — what will agents on this op do?"
              rows="3"
              :disabled="provisioning"
            ></textarea>
          </label>

          <!-- §pass66 — Advanced section. Always rendered when in advanced mode;
               composed payload feeds into card_overrides on submit. -->
          <OPProvisionAdvancedFields
            v-if="provisionMode === 'advanced'"
            ref="advancedFieldsRef"
            v-model="cardOverrides"
          />

          <div class="op-account-provision-actions">
            <button type="submit" class="op-btn-primary" :disabled="provisioning">
              <span v-if="provisioning" class="op-spinner-sm" />
              <span>Provision now</span>
            </button>
            <span class="op-account-hint" v-if="!provisioning">
              Starts ~3-5 containers on your parent frame's host (registry + TEG + nginx + SPIRE agent).
              ~30s to ready.<template v-if="provisionMode === 'advanced'">
              Card overrides applied via cross-reg PUT after stack is healthy.</template>
            </span>
          </div>
        </form>
        <div v-if="provisionError" class="op-account-error">
          <strong>Provision failed.</strong> {{ provisionError }}
        </div>
      </div>
    </div>

    <!-- Provision success result -->
    <Teleport to="body">
      <div
        v-if="provisionResult"
        class="op-modal-backdrop"
        @click.self="acknowledgeProvision"
      >
        <div class="op-modal">
          <div class="op-modal-header">
            <h3 class="op-modal-title">Cloud operator provisioned</h3>
            <button type="button" class="op-modal-close" @click="acknowledgeProvision">×</button>
          </div>
          <div class="op-modal-body">
            <div class="op-modal-success">
              ✓ <strong>{{ provisionResult.containers_started.length }} containers started.</strong>
              Your cloud-op is reachable at:
            </div>
            <a class="op-account-op-url op-account-op-url--big" :href="safeExternalUrl(provisionResult.cloud_url)" target="_blank" rel="noopener">
              {{ provisionResult.cloud_url }}
            </a>
            <!-- §pass66 — Path C card_overrides feedback. Only renders when
                 the user used the Advanced tab (card_overrides_applied is
                 absent on Quick-mode responses). -->
            <div v-if="provisionResult.card_overrides_applied === true"
                 class="op-modal-success" style="margin-top: 0.5rem;">
              ✓ <strong>Registry Card v0.3 overrides applied</strong> — visual identity, persona, commitments and links propagated to the new op.
            </div>
            <div v-else-if="provisionResult.card_overrides_applied === false"
                 class="op-modal-warning" style="margin-top: 0.5rem;">
              <Icon name="mdi:alert" /> <strong>Card overrides not applied</strong> — provision succeeded but the cross-reg PUT failed. Edit via your portal at {{ provisionResult.cloud_url }}/ui#/admin/registry-card
              <div v-if="provisionResult.card_overrides_error" style="font-size: 0.78rem; opacity: 0.8; margin-top: 0.25rem;">
                Detail: {{ provisionResult.card_overrides_error }}
              </div>
            </div>
            <!-- §pass66 — Genesis funding feedback. Always renders on every
                 provision (Quick or Advanced) when funding ran. -->
            <div v-if="provisionResult.genesis_funding_applied === true"
                 class="op-modal-success" style="margin-top: 0.5rem;">
              ✓ <strong>Treasury funded with {{ provisionResult.genesis_funding_amount_avt }} units</strong>, by a cross-TEG transfer from your parent frame's treasury. Visible immediately in your new operator's <code>/admin/treasury</code>.
            </div>
            <div v-else-if="provisionResult.genesis_funding_applied === false"
                 class="op-modal-warning" style="margin-top: 0.5rem;">
              <Icon name="mdi:alert" /> <strong>Treasury not funded</strong> — provision succeeded but the cross-TEG transfer failed. Request a manual top-up via support.
              <div v-if="provisionResult.genesis_funding_error" style="font-size: 0.78rem; opacity: 0.8; margin-top: 0.25rem;">
                Detail: {{ provisionResult.genesis_funding_error }}
              </div>
            </div>
            <div class="op-modal-warning" style="margin-top: 1rem;">
              <strong>Save these credentials NOW</strong> — they are not stored anywhere recoverable.
            </div>
            <dl class="op-modal-creds">
              <div><dt>Federation license key</dt>
                <dd class="op-modal-cred-row">
                  <code class="op-code op-code--reveal">{{ provisionResult.federation_license_key }}</code>
                  <button class="op-modal-copy" @click="copyText(provisionResult.federation_license_key, 'lic')">
                    {{ copied === 'lic' ? 'copied' : 'copy' }}
                  </button>
                </dd>
              </div>
              <div><dt>Admin email</dt><dd><code class="op-code">{{ provisionResult.admin_email }}</code></dd></div>
              <div><dt>Admin password</dt>
                <dd class="op-modal-cred-row">
                  <code class="op-code op-code--reveal">{{ provisionResult.admin_password }}</code>
                  <button class="op-modal-copy" @click="copyText(provisionResult.admin_password, 'pwd')">
                    {{ copied === 'pwd' ? 'copied' : 'copy' }}
                  </button>
                </dd>
              </div>
              <div><dt>Registry port</dt><dd>{{ provisionResult.registry_port }}</dd></div>
              <div><dt>Federation port</dt><dd>{{ provisionResult.federation_port }}</dd></div>
              <div><dt>Peer registered</dt><dd>{{ provisionResult.federation_peer_registered ? 'yes' : 'no' }}</dd></div>
            </dl>
          </div>
          <div class="op-modal-footer">
            <button type="button" class="op-btn-primary" @click="acknowledgeProvision">I have saved the credentials</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Bundle & credentials (collapsible) -->
    <div class="op-account-section" v-if="myStatusApp && hasBundleCreds">
      <h3 class="op-account-section-title">
        <button type="button" class="op-account-collapse-toggle" @click="showBundle = !showBundle">
          <span class="op-account-collapse-arrow" :class="{ 'op-account-collapse-arrow--open': showBundle }">▶</span>
          Bundle & credentials
        </button>
      </h3>
      <div v-if="showBundle" class="op-account-bundle">
        <dl class="op-account-bundle-dl">
          <div v-if="myStatusApp.spire_fingerprint">
            <dt>SPIRE fingerprint</dt>
            <dd><code class="op-code">{{ myStatusApp.spire_fingerprint.slice(0, 32) }}…</code></dd>
          </div>
          <div v-if="myStatusApp.docker_registry_username">
            <dt>Docker username</dt>
            <dd><code class="op-code">{{ myStatusApp.docker_registry_username }}</code></dd>
          </div>
          <div v-if="myStatusApp.docker_pull_token_prefix">
            <dt>Pull token prefix</dt>
            <dd><code class="op-code">{{ myStatusApp.docker_pull_token_prefix }}…</code></dd>
          </div>
          <div>
            <dt>Bundle downloads</dt>
            <dd>{{ myStatusApp.bundle_download_count || 0 }} / 3</dd>
          </div>
        </dl>
        <button
          type="button"
          class="op-btn-primary"
          :disabled="downloading || (myStatusApp.bundle_download_count || 0) >= 3"
          @click="onDownloadBundle"
        >
          {{ downloading ? 'Downloading…' : 'Download bundle' }}
        </button>
      </div>
    </div>

    <!-- Local CLI bridge -->
    <div class="op-cli-bridge">
      <div class="op-cli-eyebrow">From terminal</div>
      <LocalCommand
        :command="`tp status`"
        caption="One-line state summary across your operator stack containers."
      />
      <LocalCommand
        :command="`tp validate-config`"
        caption="Lints .env.operator + docker-compose for required fields. Run after editing config."
      />
      <LocalCommand
        :command="`tp backup`"
        caption="Local snapshot — pg_dump of registry + TEG + EventStore DBs, plus identity-fabric/SPIRE state, plus .env.operator. Tar + SHA-256 manifest. Stored in /opt/theprotocol/backups."
      />
    </div>

    <!-- Danger zone — revocation request -->
    <div class="op-account-section op-account-danger" v-if="isFederationOperator">
      <h3 class="op-account-section-title op-account-section-title--danger">
        <button type="button" class="op-account-collapse-toggle" @click="showDanger = !showDanger">
          <span class="op-account-collapse-arrow" :class="{ 'op-account-collapse-arrow--open': showDanger }">▶</span>
          Danger zone — request revocation
        </button>
      </h3>
      <div v-if="showDanger" class="op-account-danger-body">
        <p class="op-account-danger-warn">
          Requesting revocation flags your operator for review by your parent frame. Once approved by an admin, your federation
          license is suspended and your cloud-op (if any) is torn down. <strong>This is irreversible.</strong>
        </p>
        <textarea
          v-model="revocationReason"
          class="op-account-input op-account-textarea"
          placeholder="State the reason for revocation (e.g. decommissioning, ownership transfer, compromise)"
          rows="3"
        ></textarea>
        <div class="op-account-danger-actions">
          <button
            type="button"
            class="op-btn-danger"
            :disabled="!revocationReason.trim() || submittingRevocation"
            @click="onRequestRevocation"
          >
            <span v-if="submittingRevocation" class="op-spinner-sm" />
            <span>Submit revocation request</span>
          </button>
        </div>
        <div v-if="revocationResult" class="op-account-info">{{ revocationResult }}</div>
      </div>
    </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted } from 'vue'
import LocalCommand from './LocalCommand.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import OPProvisionAdvancedFields from './OPProvisionAdvancedFields.vue'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'
import { registryConfigWithin, useRegistryConfig } from '@/composables/useRegistryConfig'
import { useFrameManifest } from '@/composables/useFrameManifest'
import {
  getMyProvisioningEligibility,
  selfProvisionCloudOperator,
  type ProvisioningEligibility,
  type SelfProvisionResponse,
  type RegistryCardOverrides,
} from '@/services/api/provisioning'

const authStore = useAuthStore()
const isFederationOperator = computed(() => Boolean((authStore as any).isFederationOperator))

// ─── Eligibility ─────────────────────────────────────────
const eligibility = ref<ProvisioningEligibility | null>(null)
const eligibilityLoaded = ref(false)

const monthsRemainingNum = computed(() => {
  const n = eligibility.value?.months_remaining ?? 0
  return Math.max(0, Math.round(Number(n)))
})
const monthsLabel = computed(() => {
  const n = monthsRemainingNum.value
  return n === 1 ? '1 month' : `${n} months`
})

// Ring math (out of 12 months max stride for visual)
const ringCircumference = 2 * Math.PI * 36
const ringDashArray = ringCircumference.toFixed(2)
const ringDashOffset = computed(() => {
  const months = monthsRemainingNum.value
  const stride = Math.min(months, 12)
  const pct = stride / 12
  return (ringCircumference * (1 - pct)).toFixed(2)
})

// ─── My ops ──────────────────────────────────────────────
const opsLoaded = ref(false)
const myStatusApp = ref<any>(null)
const myCloudOps = ref<Array<{
  application_id: string
  name: string
  cloud_url: string
  cloud_port_base: number | null
  cloud_provisioned_at: string | null
  cloud_torn_down_at: string | null
  healthy: boolean | null
}>>([])

const hasBundleCreds = computed(() =>
  !!(myStatusApp.value?.spire_fingerprint
     || myStatusApp.value?.docker_registry_username
     || myStatusApp.value?.bundle_download_count !== undefined)
)

// ─── Provision form ──────────────────────────────────────
const provisionForm = ref({ name: '', organization: '', use_case: '' })
const provisioning = ref(false)
const provisionError = ref<string | null>(null)
const provisionResult = ref<SelfProvisionResponse | null>(null)
const copied = ref<string | null>(null)

// §pass66 — Path C / Advanced Provisioning Form. Mode toggle + overrides
// state. Overrides only sent when mode === 'advanced' AND payload is
// non-empty (the advanced sub-component strips empties before emit).
const provisionMode = ref<'quick' | 'advanced'>('quick')
const cardOverrides = ref<RegistryCardOverrides>({})
const advancedFieldsRef = ref<InstanceType<typeof OPProvisionAdvancedFields> | null>(null)

async function onProvision() {
  if (provisioning.value) return
  provisioning.value = true
  provisionError.value = null
  try {
    const payload: Parameters<typeof selfProvisionCloudOperator>[0] = {
      name: provisionForm.value.name.trim(),
      organization: provisionForm.value.organization.trim() || null,
      use_case: provisionForm.value.use_case.trim() || null,
    }
    // §pass66 — only attach card_overrides if user filled at least one field
    // in Advanced mode. Backend Pydantic accepts None → skips cross-reg PUT.
    if (provisionMode.value === 'advanced' && cardOverrides.value
        && Object.keys(cardOverrides.value).length > 0) {
      payload.card_overrides = cardOverrides.value
    }
    const result = await selfProvisionCloudOperator(payload)
    provisionResult.value = result
    provisionForm.value = { name: '', organization: '', use_case: '' }
    advancedFieldsRef.value?.reset?.()
    cardOverrides.value = {}
    // Refresh state
    setTimeout(() => loadStatus(), 600)
    setTimeout(() => loadEligibility(), 600)
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || 'Unknown error'
    provisionError.value = typeof detail === 'string' ? detail : JSON.stringify(detail)
  } finally {
    provisioning.value = false
  }
}

function acknowledgeProvision() {
  provisionResult.value = null
  copied.value = null
}

async function copyText(s: string, marker: string) {
  try { await navigator.clipboard.writeText(s); copied.value = marker; setTimeout(() => { copied.value = null }, 1500) }
  catch { /* swallow */ }
}

// ─── Bundle / credentials ────────────────────────────────
const showBundle = ref(false)
const downloading = ref(false)
async function onDownloadBundle() {
  if (downloading.value) return
  downloading.value = true
  try {
    const r = await apiClient.get('/operators/my-bundle', { responseType: 'blob' })
    const url = URL.createObjectURL(r.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${myStatusApp.value?.application?.name || 'operator'}-bundle.tar.gz`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    URL.revokeObjectURL(url)
    setTimeout(() => loadStatus(), 800)
  } catch (e) {
    // Toast or banner could go here; leaving silent for now
  } finally {
    downloading.value = false
  }
}

// ─── Revocation ──────────────────────────────────────────
const showDanger = ref(false)
const revocationReason = ref('')
const submittingRevocation = ref(false)
const revocationResult = ref<string | null>(null)
async function onRequestRevocation() {
  if (!revocationReason.value.trim() || submittingRevocation.value) return
  if (!window.confirm('Submit revocation request? This will flag your operator for admin review and IS reversible only at admin discretion.')) return
  submittingRevocation.value = true
  try {
    await apiClient.post('/operators/request-revocation', { reason: revocationReason.value.trim() })
    revocationResult.value = 'Request submitted. An admin will review.'
    revocationReason.value = ''
  } catch (e: any) {
    revocationResult.value = `Submission failed: ${e?.response?.data?.detail || e?.message || 'unknown'}`
  } finally {
    submittingRevocation.value = false
  }
}

// ─── Loaders ─────────────────────────────────────────────
// §FESUITE (V0577): a read that failed says so; its absence is not an answer (see the two notices above)
const eligibilityFailed = ref(false)
const opsFailed = ref(false)
async function loadEligibility() {
  eligibilityFailed.value = false
  try {
    eligibility.value = await getMyProvisioningEligibility()
  } catch { eligibility.value = null; eligibilityFailed.value = true }
  finally { eligibilityLoaded.value = true }
}
async function loadStatus() {
  opsFailed.value = false
  try {
    const r = await apiClient.get('/operators/my-status')
    const status = r.data
    myStatusApp.value = status?.application || status
    // my-status returns a single application object or { application: {...}, cloud_ops: [...] }
    if (Array.isArray(status?.cloud_ops)) {
      myCloudOps.value = status.cloud_ops
    } else if (status?.application?.cloud_url) {
      myCloudOps.value = [{
        application_id: status.application.id,
        name: status.application.name,
        cloud_url: status.application.cloud_url,
        cloud_port_base: status.application.cloud_port_base,
        cloud_provisioned_at: status.application.cloud_provisioned_at,
        cloud_torn_down_at: status.application.cloud_torn_down_at,
        healthy: status.application.healthy ?? null,
      }]
    } else {
      myCloudOps.value = []
    }
  } catch (e: any) {
    if (e?.response?.status === 404) myCloudOps.value = []   // no application: "none" is the server's answer
    else opsFailed.value = true                              // not "You haven't provisioned a cloud operator yet."
  } finally {
    opsLoaded.value = true
  }
}

function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(appLocale(), { dateStyle: 'medium', timeStyle: 'short' }) }
  catch { return iso }
}
function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try {
    const ms = Date.now() - new Date(iso).getTime()
    if (ms < 0) return 'just now'
    const s = Math.floor(ms / 1000); if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  } catch { return iso }
}

const { t, tp } = useI18n()
const { config: regConfig } = useRegistryConfig()
const { ownFrame } = useFrameManifest()
/** this registry is a cloud operator (MINTING_AUTHORITY=disabled): the provisioning rails run on its frame */
const onOperator = computed(() => regConfig.value.is_federated_operator === true)
const frameConsole = computed(() =>
  ownFrame.value && ownFrame.value.role === 'frame' && ownFrame.value.console_url ? ownFrame.value.console_url.replace(/\/+$/, '') : '')

async function loadAll() {
  // a cloud operator answers both rails 503 ("runs on sovereign mainframes only"): ask nothing there
  if ((await registryConfigWithin()).is_federated_operator === true) return
  await Promise.all([loadEligibility(), loadStatus()])
}

onMounted(loadAll)

defineExpose({ refresh: loadAll })
</script>

<style scoped>
.op-tab { padding: 1.2rem 1.6rem 2rem; }

/* §FESUITE (the operator batch): on a cloud operator, the card that says where operators are provisioned */
.op-account-onop {
  display: flex; flex-direction: column; gap: 0.5rem;
  padding: 1.4rem 1.6rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 4px;
}
.op-account-eligibility {
  display: flex; gap: 1.5rem; align-items: center;
  padding: 1.4rem 1.6rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 4px;
  transition: border-color 0.4s, background 0.4s;
}
.op-account-eligibility--locked   { border-color: rgba(255, 176, 0, 0.32); background: rgba(28, 20, 0, 0.45); }
.op-account-eligibility--unlocked { border-color: rgba(0, 230, 118, 0.28); background: rgba(0, 24, 12, 0.45); }

.op-account-elig-left { flex: 1 1 auto; min-width: 0; }
.op-account-elig-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  margin-bottom: 0.4rem;
}
.op-account-elig-title {
  margin: 0 0 0.4rem; font-size: 1.5rem; font-weight: 600;
  color: #f4f9ff; letter-spacing: -0.01em;
}
.op-account-eligibility--unlocked .op-account-elig-title { color: #b9ffe0; }
.op-account-eligibility--locked .op-account-elig-title   { color: #ffe1a0; }
.op-account-elig-sub {
  margin: 0; font-size: 0.86rem; line-height: 1.55;
  color: rgba(255, 255, 255, 0.62);
  font-family: 'IBM Plex Mono', monospace;
}

.op-account-elig-ring { display: flex; flex-direction: column; align-items: center; flex: 0 0 auto; }
.op-account-ring-svg { width: 80px; height: 80px; }
.op-account-ring-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.6rem; font-weight: 700;
  fill: #b9ffe0;
}
.op-account-ring-label {
  margin-top: 0.3rem; font-size: 0.62rem; letter-spacing: 0.14em;
  text-transform: uppercase; color: rgba(0, 230, 118, 0.65); font-weight: 600;
}

.op-account-section { margin-top: 1.5rem; }
.op-account-section-title {
  margin: 0 0 0.7rem; font-size: 1rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.op-account-section-title--danger { color: rgba(255, 200, 200, 0.9); }

.op-account-collapse-toggle {
  background: transparent; border: none;
  color: inherit; cursor: pointer;
  font-size: inherit; font-weight: inherit;
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0; font-family: inherit;
}
.op-account-collapse-arrow {
  display: inline-block; transition: transform 0.2s;
  font-size: 0.72rem; color: rgba(var(--nc-primary-rgb), 0.7);
}
.op-account-collapse-arrow--open { transform: rotate(90deg); }

.op-account-loading, .op-account-empty {
  padding: 1.8rem; text-align: center;
  background: rgba(0, 8, 14, 0.3);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 3px;
  font-size: 0.82rem;
  color: rgba(255, 255, 255, 0.45);
}

.op-account-ops-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 0.8rem;
}
.op-account-op-card {
  padding: 1rem 1.1rem;
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.16);
  border-radius: 3px;
  transition: border-color 0.25s, transform 0.25s;
}
.op-account-op-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  transform: translateY(-1px);
}
.op-account-op-header {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 0.45rem;
}
.op-account-op-name {
  font-size: 0.95rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}
.op-account-op-health {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 600;
  padding: 0.15rem 0.45rem;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.op-account-op-health--ok      { color: #00e676; background: rgba(0, 230, 118, 0.08); }
.op-account-op-health--down    { color: #ff5252; background: rgba(255, 82, 82, 0.08); }
.op-account-op-health--unknown { color: rgba(255, 255, 255, 0.45); background: rgba(255, 255, 255, 0.04); }
.op-account-op-url {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  color: rgba(var(--nc-primary-rgb), 0.9);
  text-decoration: none;
  margin-bottom: 0.5rem;
  word-break: break-all;
}
.op-account-op-url--big { font-size: 0.95rem; padding: 0.6rem; background: rgba(0, 0, 0, 0.4); border-radius: 2px; }
.op-account-op-url:hover { text-decoration: underline; }
.op-account-op-meta {
  display: flex; gap: 0.7rem; flex-wrap: wrap;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.45);
  font-family: 'IBM Plex Mono', monospace;
  margin-bottom: 0.5rem;
}
.op-account-op-actions { display: flex; gap: 0.4rem; }

.op-account-provision {
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.16);
  border-radius: 3px;
  padding: 1.2rem 1.4rem;
}
/* §pass66 — Path C: Quick/Advanced tab toggle above the provision form */
.op-account-prov-tabs {
  display: flex;
  gap: 0.25rem;
  margin-bottom: 0.75rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.16);
}
.op-account-prov-tab {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  padding: 0.5rem 0.9rem;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.55);
  transition: color 0.15s ease, border-color 0.15s ease;
}
.op-account-prov-tab:hover:not(:disabled) {
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.op-account-prov-tab--active {
  color: var(--nc-primary, #00d2d2);
  border-bottom-color: var(--nc-primary, #00d2d2);
}
.op-account-prov-tab:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.op-account-prov-tab-hint {
  font-size: 0.62rem;
  text-transform: none;
  letter-spacing: 0.04em;
  opacity: 0.6;
  font-family: inherit;
}

.op-account-provision-form { display: flex; flex-direction: column; gap: 0.85rem; }
.op-account-label { display: flex; flex-direction: column; gap: 0.3rem; }
.op-account-label > span:first-child {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  font-family: 'IBM Plex Mono', monospace;
}
.op-account-required { color: #ff9999; font-weight: 700; margin-left: 0.15rem; }
.op-account-input {
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.9);
  padding: 0.55rem 0.75rem;
  font-size: 0.84rem;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  border-radius: 2px;
  outline: none;
  min-height: 38px;
}
.op-account-input:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  box-shadow: 0 0 8px rgba(var(--nc-primary-rgb), 0.15);
}
.op-account-textarea { resize: vertical; min-height: 70px; font-family: inherit; }
.op-account-hint {
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.4);
  line-height: 1.45;
}
.op-account-provision-actions {
  display: flex; gap: 0.8rem; align-items: center;
  margin-top: 0.3rem;
}

.op-btn-primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
  padding: 0.55rem 1.2rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, box-shadow 0.18s;
  display: inline-flex; align-items: center; gap: 0.4rem;
  min-height: 36px;
}
.op-btn-primary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.28);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.2);
}
.op-btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

.op-btn-ghost {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  color: rgba(var(--nc-primary-rgb), 0.9);
  padding: 0.35rem 0.7rem;
  font-size: 0.68rem; letter-spacing: 0.09em; text-transform: uppercase;
  font-weight: 600; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  text-decoration: none;
  transition: background 0.18s, border-color 0.18s;
}
.op-btn-ghost:hover {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.42);
}

.op-btn-danger {
  background: rgba(255, 82, 82, 0.18);
  border: 1px solid rgba(255, 82, 82, 0.55);
  color: rgba(255, 200, 200, 1);
  padding: 0.55rem 1.2rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  display: inline-flex; align-items: center; gap: 0.4rem; min-height: 36px;
  transition: background 0.18s;
}
.op-btn-danger:hover:not(:disabled) { background: rgba(255, 82, 82, 0.32); }
.op-btn-danger:disabled { opacity: 0.4; cursor: not-allowed; }

.op-spinner-sm {
  width: 11px; height: 11px;
  border: 1.5px solid rgba(var(--nc-primary-rgb), 0.25);
  border-top-color: rgba(var(--nc-primary-rgb), 0.95);
  border-radius: 50%; animation: opSpin 0.8s linear infinite;
}
@keyframes opSpin { to { transform: rotate(360deg); } }

.op-account-bundle {
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 3px;
  padding: 1rem 1.2rem;
}
.op-account-bundle-dl { margin: 0 0 0.8rem; }
.op-account-bundle-dl > div {
  display: grid; grid-template-columns: 160px 1fr; gap: 0.5rem;
  padding: 0.3rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05);
  font-size: 0.78rem;
}
.op-account-bundle-dl > div:last-child { border-bottom: none; }
.op-account-bundle-dl dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.4); text-transform: uppercase;
}
.op-account-bundle-dl dd { margin: 0; color: rgba(255, 255, 255, 0.85); }

.op-account-danger {
  margin-top: 2rem;
  padding-top: 1.4rem;
  border-top: 1px solid rgba(255, 82, 82, 0.18);
}
.op-account-danger-body {
  background: rgba(28, 0, 0, 0.4);
  border: 1px solid rgba(255, 82, 82, 0.25);
  border-radius: 3px;
  padding: 1rem 1.2rem;
}
.op-account-danger-warn {
  margin: 0 0 0.8rem;
  font-size: 0.84rem; line-height: 1.55;
  color: rgba(255, 200, 200, 0.85);
}
.op-account-danger-actions { margin-top: 0.6rem; }

.op-account-error, .op-account-info {
  margin-top: 0.7rem;
  padding: 0.7rem 0.9rem;
  font-size: 0.82rem;
  border-radius: 2px;
}
.op-account-error {
  background: rgba(40, 0, 0, 0.5);
  border-left: 3px solid rgba(255, 82, 82, 0.6);
  color: rgba(255, 200, 200, 0.95);
}
.op-account-info {
  background: rgba(0, 20, 12, 0.45);
  border-left: 3px solid rgba(0, 230, 118, 0.6);
  color: rgba(180, 255, 220, 0.95);
}

.op-link {
  color: rgba(var(--nc-primary-rgb), 0.9);
  text-decoration: none;
  border-bottom: 1px dotted rgba(var(--nc-primary-rgb), 0.35);
}
.op-link:hover { border-bottom-style: solid; }

.op-code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  background: rgba(0, 0, 0, 0.32);
  padding: 0.1rem 0.4rem;
  border-radius: 2px;
  color: #c0e4ff;
}
.op-code--reveal {
  flex: 1; padding: 0.5rem 0.7rem; font-size: 0.82rem;
  word-break: break-all; min-width: 0;
}

/* Modal */
.op-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  z-index: 10100;
  display: flex; align-items: center; justify-content: center; padding: 1rem;
}
.op-modal {
  max-width: 640px; width: 100%; max-height: 90vh; overflow-y: auto;
  background: rgba(0, 8, 14, 0.96);
  border: 1px solid rgba(0, 230, 118, 0.35);
  border-radius: 4px;
  box-shadow: 0 0 40px rgba(0, 230, 118, 0.18);
}
.op-modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 1rem 1.4rem;
  border-bottom: 1px solid rgba(0, 230, 118, 0.2);
}
.op-modal-title {
  margin: 0; font-size: 1.05rem; font-weight: 600;
  color: #b9ffe0;
}
.op-modal-close {
  background: transparent; border: none; color: rgba(255, 255, 255, 0.6);
  font-size: 1.5rem; cursor: pointer; padding: 0 0.5rem; line-height: 1;
}
.op-modal-close:hover { color: rgba(255, 255, 255, 1); }
.op-modal-body { padding: 1.2rem 1.4rem; }
.op-modal-footer {
  padding: 1rem 1.4rem;
  border-top: 1px solid rgba(0, 230, 118, 0.15);
  display: flex; justify-content: flex-end;
}
.op-modal-success {
  font-size: 0.9rem; color: rgba(180, 255, 220, 0.95);
  margin-bottom: 0.7rem;
}
.op-modal-warning {
  padding: 0.7rem 0.9rem;
  background: rgba(255, 176, 0, 0.1);
  border-left: 3px solid rgba(255, 176, 0, 0.7);
  font-size: 0.82rem; color: rgba(255, 220, 160, 0.95);
}
.op-modal-creds { margin: 1rem 0 0; }
.op-modal-creds > div {
  display: grid; grid-template-columns: 180px 1fr; gap: 0.6rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid rgba(0, 230, 118, 0.08);
  font-size: 0.8rem;
}
.op-modal-creds > div:last-child { border-bottom: none; }
.op-modal-creds dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.45); text-transform: uppercase;
}
.op-modal-creds dd { margin: 0; color: rgba(255, 255, 255, 0.92); }
.op-modal-cred-row { display: flex; gap: 0.5rem; align-items: stretch; }
.op-modal-copy {
  background: rgba(0, 230, 118, 0.12);
  border: 1px solid rgba(0, 230, 118, 0.4);
  color: #b9ffe0;
  padding: 0 0.85rem;
  font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s;
}
.op-modal-copy:hover { background: rgba(0, 230, 118, 0.25); }

.op-cli-bridge {
  margin-top: 1.8rem; padding-top: 1.3rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.op-cli-eyebrow {
  font-size: 0.65rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45); font-weight: 600;
  margin-bottom: 0.6rem;
}

@media (max-width: 768px) {
  .op-tab { padding: 1rem; }
  .op-account-eligibility { flex-direction: column; }
  .op-account-bundle-dl > div, .op-modal-creds > div { grid-template-columns: 1fr; gap: 0.15rem; }
}
</style>
