<template>
  <div class="tpl-tab">
    <!-- not enabled on this registry -->
    <div v-if="disabled" class="tpl-empty">
      <Icon name="file-text" class="tpl-empty-ico" />
      <p>Contract templates are not enabled on this registry yet.</p>
    </div>

    <template v-else>
      <div class="tpl-toolbar">
        <input v-model="q" class="tpl-search" type="search"
               placeholder="Search templates…" @keyup.enter="reload" />
        <select v-model="pricing" class="tpl-select" aria-label="Filter by pricing" @change="reload">
          <option value="">All pricing</option>
          <option value="free">Free</option>
          <option value="purchase">Paid (one-time)</option>
          <option value="royalty">Paid (royalty)</option>
        </select>
        <label class="tpl-mine"><input v-model="mine" type="checkbox" @change="reload" /> Mine</label>
        <button class="tpl-btn tpl-btn--ghost" @click="reload" :disabled="loading">Reload</button>
        <button class="tpl-btn tpl-btn--primary" data-tour="tpl-new" @click="openCreate">
          <Icon name="plus" /> New template
        </button>
      </div>

      <div v-if="loading" class="tpl-loading">Loading templates…</div>

      <ReadFailedNotice v-else-if="listFailed && !items.length" :retry="reload" data-testid="tpl-list-failed" />

      <div v-else-if="!items.length" class="tpl-empty">
        <Icon name="file-text" class="tpl-empty-ico" />
        <p>No templates yet. Author one here — free and professionally maintained paid
           templates share this library.</p>
        <button class="tpl-btn tpl-btn--primary" data-tour="tpl-new-empty" @click="openCreate">
          Create the first template
        </button>
      </div>

      <div v-else class="tpl-grid">
        <div v-for="t in items" :key="t.id" class="tpl-card">
          <div class="tpl-card-head">
            <span class="tpl-title" :title="t.slug">{{ t.title }}</span>
            <span class="tpl-badge" :class="'tpl-badge--' + t.pricing_model">
              {{ pricingLabel(t) }}
            </span>
          </div>
          <p class="tpl-summary">{{ t.summary || 'No summary.' }}</p>
          <div class="tpl-meta">
            <span class="tpl-chip"><Icon name="layers" /> {{ t.contract_type }}</span>
            <span class="tpl-chip" title="Real agreements made from this template">
              <Icon name="check" /> {{ t.usage_count }} used
            </span>
            <span v-if="t.settle_rate !== null && t.settle_rate !== undefined" class="tpl-chip"
                  title="completed / (completed + disputed + cancelled)">
              <Icon name="star" /> {{ Math.round((t.settle_rate || 0) * 100) }}% settled
            </span>
            <span v-if="t.maintained_by_org_id" class="tpl-chip tpl-chip--org"
                  title="Maintained by an organization with an AGORA listing behind it">maintained</span>
            <span v-if="t.verified" class="tpl-chip tpl-chip--verified">verified</span>
          </div>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="openDetail(t)">Details</button>
            <button class="tpl-btn tpl-btn--primary" :disabled="busy === t.id" @click="useTemplate(t)">
              {{ busy === t.id ? 'Working…' : useLabel(t) }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="nextCursor" class="tpl-more">
        <button class="tpl-btn tpl-btn--ghost" @click="loadMore" :disabled="loading">Load more</button>
      </div>

      <!-- detail drawer (versions + interchange hash) -->
      <BaseModal v-if="detail" :show="true" :title="detail.title" @update:show="detail = null">
        <div class="tpl-detail">
          <p class="tpl-summary">{{ detail.summary || 'No summary.' }}</p>
          <div class="tpl-kv"><span>Owner</span><code>{{ detail.owner_agent_did }}</code></div>
          <div class="tpl-kv"><span>Pricing</span><b>{{ pricingLabel(detail) }}</b></div>
          <div class="tpl-kv"><span>Visibility</span><b>{{ detail.visibility }}</b></div>
          <div class="tpl-kv" v-if="detail.settle_rate !== null && detail.settle_rate !== undefined">
            <span>Settle rate</span><b>{{ Math.round((detail.settle_rate || 0) * 100) }}%</b>
          </div>
          <h4 class="tpl-h4">Versions (published = frozen forever)</h4>
          <!-- §FESUITE (V0578): the versions come from the template read; over a failed read this drew the list row's
               (which carries none) as an empty table: a template with versions drawn as one without -->
          <ReadFailedNotice v-if="detailFailed" dense data-testid="tpl-detail-unread" :retry="retryDetail"
            text="This template's versions could not be read just now." />
          <table v-else class="tpl-vtable">
            <thead><tr><th>v</th><th>changelog</th><th>state</th><th>content hash</th><th></th></tr></thead>
            <tbody>
              <tr v-for="v in detail.versions || []" :key="v.id">
                <td>{{ v.version }}</td>
                <td>{{ v.changelog || '—' }}</td>
                <td>{{ v.published_at ? 'published' : 'draft' }}</td>
                <td><code class="tpl-hash" :title="v.content_hash">{{ v.content_hash.slice(0, 16) }}…</code></td>
                <td>
                  <button
                    v-if="!v.published_at && ownsDetail"
                    class="tpl-btn tpl-btn--freeze"
                    data-tour="tpl-publish"
                    :disabled="busy === detail.id"
                    @click="askPublish(v.version)"
                  >Publish</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="tpl-hint">A version's payload (terms + form schema + milestones + hash) is the
            import/export format — <code>GET /contracts/templates/{{ detail.id }}/versions/&lt;n&gt;</code>.</p>

          <!-- §FEPARITY-R4 — authoring actions -->
          <div class="tpl-author-bar" data-tour="tpl-author-bar">
            <template v-if="ownsDetail">
              <button class="tpl-btn tpl-btn--ghost" data-tour="tpl-newversion" @click="openVersion">
                New draft version
              </button>
              <button class="tpl-btn tpl-btn--ghost" data-tour="tpl-editmeta" @click="openMeta">
                Edit metadata
              </button>
            </template>
            <button class="tpl-btn tpl-btn--ghost" data-tour="tpl-fork" @click="openFork">Fork</button>
            <span v-if="!ownsDetail" class="tpl-hint tpl-hint--inline">
              You do not own this template — forking gives you your own line.
            </span>
          </div>
        </div>
      </BaseModal>

      <!-- ── create ───────────────────────────────────────────────────────── -->
      <BaseModal v-if="showCreate" :show="true" title="New contract template" @update:show="showCreate = false">
        <div class="tpl-detail">
          <p class="tpl-hint">Creates the template and its <b>v1 draft</b>. Nothing is frozen until
            you publish a version, and publishing is irreversible.</p>
          <label class="tpl-field">Slug (lowercase, digits and dashes)
            <input v-model="cForm.slug" class="tpl-input" placeholder="milestone-build-order" />
          </label>
          <label class="tpl-field">Title
            <input v-model="cForm.title" class="tpl-input" placeholder="Milestone build order" />
          </label>
          <label class="tpl-field">Summary (optional)
            <input v-model="cForm.summary" class="tpl-input" />
          </label>
          <div class="tpl-row">
            <label class="tpl-field">Contract type
              <input v-model="cForm.contract_type" class="tpl-input" />
            </label>
            <label class="tpl-field">Visibility
              <select v-model="cForm.visibility" class="tpl-input">
                <option v-for="v in VISIBILITIES" :key="v" :value="v">{{ v }}</option>
              </select>
            </label>
          </div>
          <div class="tpl-row">
            <label class="tpl-field">Pricing
              <select v-model="cForm.pricing_model" class="tpl-input" data-tour="tpl-pricing">
                <option value="free">free</option>
                <option value="purchase">purchase (one-time)</option>
                <option value="royalty">royalty (per settlement)</option>
              </select>
            </label>
            <label v-if="cForm.pricing_model === 'purchase'" class="tpl-field">Price ({{ frameCcy }})
              <input v-model="cForm.price" type="number" min="0" step="0.000001" class="tpl-input" />
            </label>
            <label v-else-if="cForm.pricing_model === 'royalty'" class="tpl-field">Royalty (bps, max 500)
              <input v-model="cForm.royalty_bps" type="number" min="1" max="500" step="1" class="tpl-input" />
            </label>
          </div>
          <p v-if="createHint" class="tpl-err" data-tour="tpl-create-hint">{{ createHint }}</p>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="showCreate = false">Cancel</button>
            <button class="tpl-btn tpl-btn--primary" data-tour="tpl-create-submit"
                    :disabled="!createValid || busy === '__create'" @click="submitCreate">
              {{ busy === '__create' ? 'Creating…' : 'Create draft' }}
            </button>
          </div>
        </div>
      </BaseModal>

      <!-- ── new version ──────────────────────────────────────────────────── -->
      <BaseModal v-if="showVersion" :show="true" title="New draft version" @update:show="showVersion = false">
        <div class="tpl-detail">
          <p class="tpl-hint">Content is versioned, never edited in place. Published versions stay
            exactly as the agreements referencing them saw them.</p>
          <label class="tpl-field">Changelog
            <input v-model="vForm.changelog" class="tpl-input" placeholder="what changed and why" />
          </label>
          <label class="tpl-field">Terms (JSON, optional)
            <textarea v-model="vForm.terms" class="tpl-input tpl-textarea" rows="6" placeholder="{ }"></textarea>
          </label>
          <p v-if="versionHint" class="tpl-err">{{ versionHint }}</p>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="showVersion = false">Cancel</button>
            <button class="tpl-btn tpl-btn--primary" :disabled="busy === '__version'" @click="submitVersion">
              {{ busy === '__version' ? 'Saving…' : 'Create draft version' }}
            </button>
          </div>
        </div>
      </BaseModal>

      <!-- ── publish confirm (irreversible) ───────────────────────────────── -->
      <BaseModal v-if="publishN !== null" :show="true" title="Publish version — irreversible" @update:show="publishN = null">
        <div class="tpl-detail">
          <p class="tpl-warn" data-tour="tpl-publish-warn">
            Publishing <b>v{{ publishN }}</b> FREEZES it permanently. It can never be edited or
            unpublished, because contracts made from it must keep referring to the exact terms
            they agreed to. Create a new version instead if you need changes.
          </p>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="publishN = null">Cancel</button>
            <button class="tpl-btn tpl-btn--freeze" data-tour="tpl-publish-confirm"
                    :disabled="busy === '__publish'" @click="submitPublish">
              {{ busy === '__publish' ? 'Freezing…' : 'Freeze and publish' }}
            </button>
          </div>
        </div>
      </BaseModal>

      <!-- ── metadata ─────────────────────────────────────────────────────── -->
      <BaseModal v-if="showMeta" :show="true" title="Edit metadata" @update:show="showMeta = false">
        <div class="tpl-detail">
          <p class="tpl-hint">Metadata, visibility and pricing only — this never touches version
            content. Existing agreements are unaffected.</p>
          <label class="tpl-field">Title <input v-model="mForm.title" class="tpl-input" /></label>
          <label class="tpl-field">Summary <input v-model="mForm.summary" class="tpl-input" /></label>
          <div class="tpl-row">
            <label class="tpl-field">Visibility
              <select v-model="mForm.visibility" class="tpl-input">
                <option v-for="v in VISIBILITIES" :key="v" :value="v">{{ v }}</option>
              </select>
            </label>
            <label class="tpl-field">Pricing
              <select v-model="mForm.pricing_model" class="tpl-input">
                <option value="free">free</option>
                <option value="purchase">purchase</option>
                <option value="royalty">royalty</option>
              </select>
            </label>
          </div>
          <div class="tpl-row">
            <label v-if="mForm.pricing_model === 'purchase'" class="tpl-field">Price ({{ frameCcy }})
              <input v-model="mForm.price" type="number" min="0" step="0.000001" class="tpl-input" />
            </label>
            <label v-else-if="mForm.pricing_model === 'royalty'" class="tpl-field">Royalty (bps, max 500)
              <input v-model="mForm.royalty_bps" type="number" min="1" max="500" class="tpl-input" />
            </label>
          </div>
          <p v-if="metaHint" class="tpl-err">{{ metaHint }}</p>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="showMeta = false">Cancel</button>
            <button class="tpl-btn tpl-btn--primary" :disabled="busy === '__meta'" @click="submitMeta">
              {{ busy === '__meta' ? 'Saving…' : 'Save' }}
            </button>
          </div>
        </div>
      </BaseModal>

      <!-- ── fork ─────────────────────────────────────────────────────────── -->
      <BaseModal v-if="showFork" :show="true" title="Fork template" @update:show="showFork = false">
        <div class="tpl-detail">
          <p class="tpl-hint">Your fork starts <b>private and free</b>, and royalty is not inherited —
            you price your own line. The lineage back to the original is recorded.</p>
          <label class="tpl-field">New slug
            <input v-model="fForm.slug" class="tpl-input" placeholder="my-fork-of-it" />
          </label>
          <label class="tpl-field">New title (optional)
            <input v-model="fForm.title" class="tpl-input" />
          </label>
          <p v-if="forkHint" class="tpl-err">{{ forkHint }}</p>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="showFork = false">Cancel</button>
            <button class="tpl-btn tpl-btn--primary" data-tour="tpl-fork-submit"
                    :disabled="!SLUG_RE.test(fForm.slug) || busy === '__fork'" @click="submitFork">
              {{ busy === '__fork' ? 'Forking…' : 'Create fork' }}
            </button>
          </div>
        </div>
      </BaseModal>

      <!-- instantiate modal -->
      <BaseModal v-if="useTarget" :show="true" :title="'Use: ' + useTarget.title" @update:show="useTarget = null">
        <div class="tpl-detail">
          <p class="tpl-hint">This copies the published version's terms into a new contract OFFER
            from your active agent (escrow fires when the provider accepts). The template is never
            referenced again once the offer exists.</p>
          <label class="tpl-field">Total amount ({{ frameCcy }})
            <input v-model="useAmount" type="number" min="0" step="0.000001" class="tpl-input" />
          </label>
          <label class="tpl-field">Provider DID (optional — empty = open offer)
            <input v-model="useProvider" type="text" class="tpl-input" placeholder="did:theprotocol:…" />
          </label>
          <div class="tpl-actions">
            <button class="tpl-btn tpl-btn--ghost" @click="useTarget = null">Cancel</button>
            <button class="tpl-btn tpl-btn--primary" :disabled="busy === useTarget.id" @click="confirmUse">
              {{ busy === useTarget.id ? 'Creating…' : 'Create contract offer' }}
            </button>
          </div>
        </div>
      </BaseModal>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { contractsV2Api, type ContractTemplate } from '@/services/api/contractsV2'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import BaseModal from '@/components/BaseModal.vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { fmt } from '@/services/cockpit/num'   // a v2 amount arrives as str(Decimal) ("2.0000000000", "0E-10")

const emit = defineEmits<{ (e: 'minted', contract: any): void }>()

const uiStore = useUIStore()
const items = ref<ContractTemplate[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const disabled = ref(false)
const busy = ref<string | null>(null)
const q = ref('')
const pricing = ref('')
const mine = ref(false)
const detail = ref<ContractTemplate | null>(null)
const detailFailed = ref(false)
const useTarget = ref<ContractTemplate | null>(null)
const useAmount = ref<string>('')
const useProvider = ref<string>('')
const frameCcy = ref(currentOwnCurrency())

// ── §FEPARITY-R4 authoring ──────────────────────────────────────────────────
// The library had browse/purchase/instantiate but no way to AUTHOR: the empty state
// literally told people to POST to the API. All five authoring routes are agent-JWT +
// require_agent_permission('contract.template.publish').
const authStore = useAuthStore()
const VISIBILITIES = ['private', 'org', 'unlisted', 'public'] as const
// Mirrors the server's pattern exactly so we reject locally instead of eating a 422.
const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,118}$/

const showCreate = ref(false)
const showVersion = ref(false)
const showMeta = ref(false)
const showFork = ref(false)
const publishN = ref<number | null>(null)
const createHint = ref('')
const versionHint = ref('')
const metaHint = ref('')
const forkHint = ref('')

const cForm = reactive({
  slug: '', title: '', summary: '', contract_type: 'work_order',
  visibility: 'private', pricing_model: 'free', price: '', royalty_bps: '',
})
const vForm = reactive({ changelog: '', terms: '' })
const mForm = reactive({ title: '', summary: '', visibility: '', pricing_model: '', price: '', royalty_bps: '' })
const fForm = reactive({ slug: '', title: '' })

/** Ownership decides which authoring actions are OFFERED; the server still decides
 *  whether they are allowed. We never render a control that is guaranteed to 403. */
const ownsDetail = computed(() => {
  const did = authStore.activeAgent?.did
  return !!did && !!detail.value?.owner_agent_did && detail.value.owner_agent_did === did
})

const createValid = computed(() => {
  if (!SLUG_RE.test(cForm.slug) || !cForm.title.trim()) return false
  if (cForm.pricing_model === 'purchase') return Number(cForm.price) > 0
  if (cForm.pricing_model === 'royalty') {
    const b = Number(cForm.royalty_bps)
    return b > 0 && b <= 500
  }
  return true
})

/** One place that turns an authoring rejection into an honest sentence. A 403 here is
 *  a real answer (the permission is grant-only), not a glitch to paper over. */
function authoringError(e: any, fallback: string): string {
  const status = e?.response?.status
  const detailMsg = e?.response?.data?.detail
  if (status === 403) {
    return typeof detailMsg === 'string' && detailMsg
      ? detailMsg
      : 'Your active agent lacks contract.template.publish (grant-only permission).'
  }
  if (status === 409) return typeof detailMsg === 'string' ? detailMsg : 'Conflict — slug taken or version already frozen.'
  return String(detailMsg || e?.message || fallback).slice(0, 240)
}

function requireAgent(): boolean {
  if (!authStore.activeAgent?.did) {
    uiStore.showError('No active agent', 'Templates are authored by an agent — activate one first.')
    return false
  }
  return true
}

function openCreate() {
  if (!requireAgent()) return
  createHint.value = ''
  Object.assign(cForm, {
    slug: '', title: '', summary: '', contract_type: 'work_order',
    visibility: 'private', pricing_model: 'free', price: '', royalty_bps: '',
  })
  showCreate.value = true
}

async function submitCreate() {
  if (!createValid.value) return
  createHint.value = ''
  busy.value = '__create'
  try {
    const body: any = {
      slug: cForm.slug.trim(),
      title: cForm.title.trim(),
      contract_type: cForm.contract_type.trim() || 'work_order',
      visibility: cForm.visibility,
      pricing_model: cForm.pricing_model,
    }
    if (cForm.summary.trim()) body.summary = cForm.summary.trim()
    if (cForm.pricing_model === 'purchase') body.price = Number(cForm.price)
    if (cForm.pricing_model === 'royalty') body.royalty_bps = Number(cForm.royalty_bps)
    const res = await contractsV2Api.createTemplate(body)
    uiStore.showSuccess('Template created', `${res.template_id} — v1 draft (not published)`)
    showCreate.value = false
    await reload()
  } catch (e: any) {
    createHint.value = authoringError(e, 'Create failed')
  } finally {
    busy.value = null
  }
}

function openVersion() {
  versionHint.value = ''
  vForm.changelog = ''
  vForm.terms = ''
  showVersion.value = true
}

async function submitVersion() {
  const t = detail.value
  if (!t) return
  versionHint.value = ''
  let terms: Record<string, any> | undefined
  if (vForm.terms.trim()) {
    try {
      terms = JSON.parse(vForm.terms)
    } catch {
      versionHint.value = 'Terms must be valid JSON.'
      return
    }
  }
  busy.value = '__version'
  try {
    const body: any = {}
    if (vForm.changelog.trim()) body.changelog = vForm.changelog.trim()
    if (terms) body.terms = terms
    const res = await contractsV2Api.createTemplateVersion(t.id, body)
    uiStore.showSuccess('Draft version created', `v${res.version} — publish it to freeze`)
    showVersion.value = false
    await openDetail(t)
  } catch (e: any) {
    versionHint.value = authoringError(e, 'Version failed')
  } finally {
    busy.value = null
  }
}

function askPublish(n: number) { publishN.value = n }

async function submitPublish() {
  const t = detail.value
  if (!t || publishN.value === null) return
  const n = publishN.value
  busy.value = '__publish'
  try {
    await contractsV2Api.publishTemplateVersion(t.id, n)
    uiStore.showSuccess('Version published', `v${n} is frozen permanently.`)
    publishN.value = null
    await openDetail(t)
    await reload()
  } catch (e: any) {
    uiStore.showError('Publish failed', authoringError(e, 'Publish failed'))
  } finally {
    busy.value = null
  }
}

function openMeta() {
  const t = detail.value
  if (!t) return
  metaHint.value = ''
  Object.assign(mForm, {
    title: t.title || '',
    summary: t.summary || '',
    visibility: t.visibility || 'private',
    pricing_model: t.pricing_model || 'free',
    price: t.price != null ? String(t.price) : '',
    royalty_bps: t.royalty_bps != null ? String(t.royalty_bps) : '',
  })
  showMeta.value = true
}

async function submitMeta() {
  const t = detail.value
  if (!t) return
  metaHint.value = ''
  if (mForm.pricing_model === 'purchase' && !(Number(mForm.price) > 0)) {
    metaHint.value = 'Purchase pricing needs a price above zero.'
    return
  }
  if (mForm.pricing_model === 'royalty') {
    const b = Number(mForm.royalty_bps)
    if (!(b > 0 && b <= 500)) { metaHint.value = 'Royalty must be between 1 and 500 bps.'; return }
  }
  busy.value = '__meta'
  try {
    const body: any = {
      title: mForm.title.trim(),
      summary: mForm.summary.trim(),
      visibility: mForm.visibility,
      pricing_model: mForm.pricing_model,
    }
    if (mForm.pricing_model === 'purchase') body.price = Number(mForm.price)
    if (mForm.pricing_model === 'royalty') body.royalty_bps = Number(mForm.royalty_bps)
    await contractsV2Api.patchTemplate(t.id, body)
    uiStore.showSuccess('Template updated', 'Metadata saved — version content untouched.')
    showMeta.value = false
    await openDetail(t)
    await reload()
  } catch (e: any) {
    metaHint.value = authoringError(e, 'Update failed')
  } finally {
    busy.value = null
  }
}

function openFork() {
  if (!requireAgent()) return
  forkHint.value = ''
  fForm.slug = ''
  fForm.title = ''
  showFork.value = true
}

async function submitFork() {
  const t = detail.value
  if (!t || !SLUG_RE.test(fForm.slug)) return
  forkHint.value = ''
  busy.value = '__fork'
  try {
    const body: any = { slug: fForm.slug.trim() }
    if (fForm.title.trim()) body.title = fForm.title.trim()
    const res = await contractsV2Api.forkTemplate(t.id, body)
    uiStore.showSuccess('Forked', `${res.template_id} — private, free, v1 draft`)
    showFork.value = false
    detail.value = null
    await reload()
  } catch (e: any) {
    forkHint.value = authoringError(e, 'Fork failed')
  } finally {
    busy.value = null
  }
}

function pricingLabel(t: ContractTemplate): string {
  if (t.pricing_model === 'purchase') return `${t.price} ${t.price_currency || ''} one-time`
  if (t.pricing_model === 'royalty') return `${(t.royalty_bps / 100).toFixed(2)}% royalty`
  return 'FREE'
}

function useLabel(t: ContractTemplate): string {
  return t.pricing_model === 'purchase' ? 'Buy / use' : 'Use template'
}

async function fetchPage(cursor?: string) {
  const res = await contractsV2Api.listTemplates({
    q: q.value || undefined,
    pricing_model: pricing.value || undefined,
    mine: mine.value || undefined,
    limit: 24,
    cursor,
  })
  return res
}

// §FESUITE (V0577): a list read that failed is not "No templates yet… Create the first template"; with nothing on
// screen the list says the read failed (Try again), with rows on screen they stay and the toast says the refresh failed
const listFailed = ref(false)
async function reload() {
  loading.value = true
  listFailed.value = false
  try {
    const res = await fetchPage()
    items.value = res.items
    nextCursor.value = res.next_cursor
    disabled.value = false
  } catch (e: any) {
    if (e?.response?.status === 503) disabled.value = true
    else if (items.value.length) uiStore.showError('Templates', 'Failed to load templates')
    else listFailed.value = true
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!nextCursor.value) return
  loading.value = true
  try {
    const res = await fetchPage(nextCursor.value)
    items.value = items.value.concat(res.items)
    nextCursor.value = res.next_cursor
  } finally {
    loading.value = false
  }
}

async function openDetail(t: ContractTemplate) {
  try {
    detail.value = await contractsV2Api.getTemplate(t.id)
    detailFailed.value = false
  } catch {
    // the list row keeps the drawer's title, owner and pricing; its versions were not read
    detail.value = t
    detailFailed.value = true
  }
}
function retryDetail() {
  if (detail.value) return openDetail(detail.value)
}

function useTemplate(t: ContractTemplate) {
  useTarget.value = t
  useAmount.value = ''
  useProvider.value = ''
}

async function confirmUse() {
  const t = useTarget.value
  if (!t) return
  busy.value = t.id
  try {
    if (t.pricing_model === 'purchase') {
      // purchase is idempotent server-side ("already purchased" → ok)
      await contractsV2Api.purchaseTemplate(t.id)
    }
    const body: any = {}
    if (useAmount.value !== '') body.total_amount = Number(useAmount.value)
    if (useProvider.value.trim()) body.provider_did = useProvider.value.trim()
    const c = await contractsV2Api.instantiateTemplate(t.id, body)
    frameCcy.value = c.currency || frameCcy.value
    uiStore.showSuccess('Contract offered', `${c.id} — ${fmt(c.total_amount, 4)} ${c.currency} (escrow fires at accept)`)
    useTarget.value = null
    emit('minted', c)
    reload()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Instantiate failed'
    uiStore.showError('Instantiate failed', String(msg).slice(0, 240))
  } finally {
    busy.value = null
  }
}

onMounted(reload)
</script>

<style scoped>
.tpl-tab { padding: 0.25rem 0; }
.tpl-toolbar { display: flex; gap: 0.6rem; align-items: center; flex-wrap: wrap; margin-bottom: 1rem; }
.tpl-search { flex: 1 1 220px; min-width: 180px; padding: 0.5rem 0.75rem; border-radius: 8px;
  border: 1px solid var(--border-color, #2a2f45); background: var(--bg-secondary, #12152b); color: inherit; }
.tpl-select { padding: 0.5rem; border-radius: 8px; border: 1px solid var(--border-color, #2a2f45);
  background: var(--bg-secondary, #12152b); color: inherit; }
.tpl-mine { display: flex; gap: 0.35rem; align-items: center; font-size: 0.85rem; opacity: 0.85; }
.tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.9rem; }
.tpl-card { border: 1px solid var(--border-color, #2a2f45); border-radius: 12px; padding: 0.9rem;
  background: var(--bg-secondary, rgba(255,255,255,0.02)); display: flex; flex-direction: column; gap: 0.55rem; }
.tpl-card-head { display: flex; justify-content: space-between; gap: 0.5rem; align-items: baseline; }
.tpl-title { font-weight: 600; }
.tpl-badge { font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 999px; white-space: nowrap;
  border: 1px solid currentColor; }
.tpl-badge--free { color: #4ade80; }
.tpl-badge--purchase { color: #fbbf24; }
.tpl-badge--royalty { color: #a78bfa; }
.tpl-summary { font-size: 0.85rem; opacity: 0.8; margin: 0; min-height: 2.2em; }
.tpl-meta { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.tpl-chip { font-size: 0.72rem; display: inline-flex; align-items: center; gap: 0.25rem;
  padding: 0.12rem 0.45rem; border-radius: 999px; background: rgba(255,255,255,0.06); }
.tpl-chip--org { background: rgba(96,165,250,0.15); color: #93c5fd; }
.tpl-chip--verified { background: rgba(74,222,128,0.15); color: #4ade80; }
.tpl-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: auto; }
.tpl-btn { padding: 0.45rem 0.9rem; border-radius: 8px; font-size: 0.82rem; cursor: pointer;
  border: 1px solid var(--border-color, #2a2f45); background: transparent; color: inherit; }
/* §FESUITE: white on #6366f1 is 4.46:1; the same indigo a shade deeper carries it at 4.6 */
.tpl-btn--primary { background: var(--accent-color, #5b5eef); border-color: transparent; color: #fff; }
.tpl-btn:disabled { opacity: 0.55; cursor: default; }
/* §FESUITE: the dimming was on the whole block, so it dimmed the empty state's own call to action (4.46 -> 3.2:1) */
.tpl-empty { text-align: center; padding: 2.5rem 1rem; }
.tpl-empty > p { opacity: 0.8; }
.tpl-empty-ico { width: 34px; height: 34px; opacity: 0.6; margin-bottom: 0.5rem; }
.tpl-loading { opacity: 0.7; padding: 1.5rem 0; }
.tpl-more { text-align: center; margin-top: 1rem; }
.tpl-detail { display: flex; flex-direction: column; gap: 0.6rem; }
.tpl-kv { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.85rem; }
.tpl-kv span { opacity: 0.65; }
.tpl-h4 { margin: 0.6rem 0 0.2rem; font-size: 0.9rem; }
.tpl-vtable { width: 100%; font-size: 0.8rem; border-collapse: collapse; }
.tpl-vtable th, .tpl-vtable td { text-align: left; padding: 0.3rem 0.45rem;
  border-bottom: 1px solid var(--border-color, #2a2f45); }
.tpl-hash { font-size: 0.72rem; }
.tpl-hint { font-size: 0.78rem; opacity: 0.7; }
.tpl-field { display: flex; flex-direction: column; gap: 0.3rem; font-size: 0.85rem; }
.tpl-input { padding: 0.5rem 0.7rem; border-radius: 8px; border: 1px solid var(--border-color, #2a2f45);
  background: var(--bg-secondary, #12152b); color: inherit; }

/* §FEPARITY-R4 — authoring */
.tpl-textarea { font-family: 'IBM Plex Mono', monospace; font-size: 0.76rem; resize: vertical; }
.tpl-row { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.tpl-row > .tpl-field { flex: 1 1 12rem; }
.tpl-hint--inline { display: inline-flex; align-items: center; }
.tpl-err { font-size: 0.78rem; color: #ff6b6b; margin: 0.15rem 0 0; }
.tpl-warn {
  font-size: 0.82rem; line-height: 1.5;
  padding: 0.7rem 0.85rem; border-radius: 8px;
  border: 1px solid rgba(255, 176, 32, 0.35);
  background: rgba(255, 176, 32, 0.08);
}
.tpl-author-bar {
  display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center;
  margin-top: 0.9rem; padding-top: 0.8rem;
  border-top: 1px solid var(--border-color, #2a2f45);
}
.tpl-btn--freeze {
  background: rgba(255, 176, 32, 0.14);
  border-color: rgba(255, 176, 32, 0.5);
  color: #ffb020;
}
.tpl-btn--freeze:hover:not(:disabled) { background: rgba(255, 176, 32, 0.24); }
@media (max-width: 480px) { .tpl-grid { grid-template-columns: 1fr; } .tpl-row { flex-direction: column; } }
</style>
