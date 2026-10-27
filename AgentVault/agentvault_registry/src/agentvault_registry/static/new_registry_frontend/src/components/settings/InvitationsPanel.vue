<!--
  §OPGUIDE-6 (2026-07-31) — Settings › Invitations.

  Mint and manage beta invite codes without leaving the UI. Until now the only route
  was Swagger or curl, which the Hetzner hand-off had to document as a workaround.

  Visibility: every registry's admins (§FESUITE V0595, a console gap: an open registry's admin
  could mint no code from the console). Where registration is open (GET /auth/registration-config
  → beta_invite_required false) a code is asked for nowhere and grants nothing, admin rights
  included, until invite-only is on: the panel says so instead of being hidden.

  Notes for future editors:
    * `status` is COMPUTED server-side from use_count/max_uses/expires_at — there is no
      status column. "Inactive" in this UI means `expired`.
    * Revoke DELETES the row. The server refuses on an already-used code (a redeemed
      code is history, not a live grant), so used rows show no revoke button at all
      rather than one that always fails.
    * grants_admin is deliberately hard to hit by accident: off by default, its own
      warning strip, and the confirm modal names the consequence in words.
    * Labels are English v1, matching NotificationsPanel and every other Settings panel.
      Only the TAB label is localised.
-->
<template>
  <div class="iv-panel">
    <!-- ── header ─────────────────────────────────────────────── -->
    <div class="iv-header">
      <div class="iv-header-text">
        <h3 class="iv-title">Invitations</h3>
        <p v-if="!openRegistration" class="iv-sub">
          Registration on this registry requires an invite code. Codes created here are the
          only way in.
        </p>
        <!-- §FESUITE V0595 (a console gap: an open registry's admin could mint no code from the console): the tab shows on
             every registry now, and says what a code is worth where registration is open -->
        <p v-else class="iv-sub" data-testid="iv-open-registration">
          Registration on this registry is open: no code is asked for, and a code grants nothing (admin rights
          included) until invite-only is turned on. Codes created now wait for that day. To make someone an admin
          here today, give them admin rights from their developer page in the admin console.
        </p>
      </div>
      <button class="iv-ghost" :disabled="loading" @click="refresh()" title="Reload">
        <Icon name="mdi:refresh" :class="{ 'iv-spin': loading }" /> Refresh
      </button>
    </div>

    <p v-if="loadError" class="iv-banner iv-banner--err" role="alert">
      <Icon name="mdi:alert" /> {{ loadError }}
    </p>

    <!-- ── mint ───────────────────────────────────────────────── -->
    <section class="iv-sec">
      <div class="iv-sec-head">Create new codes</div>

      <div class="iv-form" data-tour="inv-form">
        <label class="iv-field">
          <span class="iv-lbl">How many</span>
          <input v-model.number="form.count" type="number" min="1" max="500" class="iv-in" />
        </label>
        <label class="iv-field">
          <span class="iv-lbl">Uses per code</span>
          <input v-model.number="form.max_uses" type="number" min="1" max="10" class="iv-in" />
        </label>
        <label class="iv-field">
          <span class="iv-lbl">Expires in (days)</span>
          <input
            v-model="expiresRaw" type="number" min="1" max="365" class="iv-in"
            placeholder="never"
          />
        </label>
        <label class="iv-field iv-field--wide">
          <span class="iv-lbl">Note <span class="iv-opt">(for your own records)</span></span>
          <input
            v-model="form.note" type="text" maxlength="255" class="iv-in"
            placeholder="e.g. platform team, second seat"
          />
        </label>
      </div>

      <!-- admin grant: its own strip, never a checkbox lost in a row of four -->
      <div class="iv-adminbox" data-tour="inv-admin-toggle" :class="{ 'iv-adminbox--on': form.grants_admin }">
        <label class="iv-sw">
          <input type="checkbox" v-model="form.grants_admin" data-testid="iv-grants-admin" />
          <span class="iv-sw-track"></span>
        </label>
        <div class="iv-adminbox-text">
          <strong>
            <Icon name="mdi:shield-account" /> Redeeming creates an administrator
          </strong>
          <span>
            Pick the areas below. The account is created holding exactly those admin
            capabilities and nothing else. Use this to hand a registry an administrator
            without creating the account yourself: they register, pick their own password
            and accept the terms. Leave off for an ordinary developer account.
          </span>
        </div>
      </div>

      <!--
        §INVRBAC — WHICH admin capability, chosen per code.

        These five flags ARE the authorization system: every admin route gates on
        require_admin_flag("admin_<area>"). The legacy `is_admin` super-flag is not
        offered here and is never granted by an invitation, because it is a blanket
        bypass of those same gates: an account holding it cannot be narrowed, only
        rebuilt. Nothing is preselected, so "administrator" is never granted by default.

        A flag the CURRENT admin does not hold is shown disabled rather than hidden, so
        the boundary is legible instead of mysterious. The server clamps identically
        (403 on over-reach) and is the authority; this is only courtesy.
      -->
      <div v-if="form.grants_admin" class="iv-flags" data-tour="inv-flags">
        <div class="iv-flags-head">
          Which areas
          <span class="iv-flags-hint">
            {{ form.admin_flags.length }} of {{ ADMIN_FLAGS.length }} selected
          </span>
        </div>
        <label
          v-for="f in ADMIN_FLAGS" :key="f.key"
          class="iv-flag"
          :class="{ on: form.admin_flags.includes(f.key), off: !canGrant(f.key) }"
          :title="canGrant(f.key) ? f.blurb : 'You do not hold this flag, so you cannot pass it on.'"
        >
          <input
            type="checkbox" :checked="form.admin_flags.includes(f.key)"
            :disabled="!canGrant(f.key)" :data-testid="`iv-flag-${f.key}`"
            @change="toggleFlag(f.key)"
          />
          <span class="iv-flag-text">
            <strong>{{ f.label }}</strong>
            <small>{{ f.blurb }}</small>
          </span>
          <!-- 'mdi:lock' is in Icon.vue's LOCAL map; an unknown name blank-renders. -->
          <Icon v-if="!canGrant(f.key)" name="mdi:lock" class="iv-flag-lock" />
        </label>
        <p v-if="form.grants_admin && !form.admin_flags.length" class="iv-flags-warn">
          Pick at least one area. An invitation that names none would be an administrator
          of nothing, and the operator should say what they mean.
        </p>
      </div>

      <div class="iv-mint-actions">
        <button
          class="iv-primary" :disabled="minting || !mintValid"
          data-testid="iv-mint" data-tour="inv-mint" @click="askMint()"
        >
          <Icon name="mdi:plus" />
          {{ minting ? 'Creating…' : mintLabel }}
        </button>
        <span v-if="mintMsg" class="iv-mintmsg" :class="{ 'iv-mintmsg--err': !mintOk }">
          {{ mintMsg }}
        </span>
      </div>

      <!-- freshly minted batch: the ONLY place the codes are laid out for copying -->
      <div v-if="justMinted.length" class="iv-fresh" data-tour="inv-fresh">
        <div class="iv-fresh-head">
          <Icon name="mdi:check-circle" />
          Created {{ justMinted.length }} code{{ justMinted.length === 1 ? '' : 's' }}
          <button class="iv-linkbtn" @click="justMinted = []">dismiss</button>
        </div>
        <div v-for="c in justMinted" :key="c.code" class="iv-fresh-row">
          <code class="iv-code">{{ c.code }}</code>
          <span v-if="c.grants_admin" class="iv-pill iv-pill--admin">
            <Icon name="mdi:shield-account" /> admin
          </span>
          <span class="iv-spacer"></span>
          <button class="iv-ghost iv-ghost--sm" @click="copy(c.code, 'Code copied')">
            <Icon name="mdi:content-copy" /> Code
          </button>
          <button class="iv-ghost iv-ghost--sm" @click="copy(c.invite_url, 'Invite link copied')">
            <Icon name="mdi:content-copy" /> Link
          </button>
        </div>
        <p class="iv-fresh-hint">
          The link already contains the code, so the registration form pre-fills it.
        </p>
      </div>
    </section>

    <!-- ── list ───────────────────────────────────────────────── -->
    <section class="iv-sec">
      <div class="iv-sec-head">
        Existing codes
        <span class="iv-count">{{ codes.length }}</span>
      </div>

      <div class="iv-filters" role="tablist" data-tour="inv-filters">
        <button
          v-for="f in filters" :key="f.key"
          class="iv-fpill" :class="{ active: filter === f.key }"
          :data-testid="`iv-filter-${f.key}`"
          role="tab" :aria-selected="filter === f.key"
          @click="filter = f.key"
        >
          {{ f.label }}
          <span class="iv-fcount">{{ counts[f.key] }}</span>
        </button>
      </div>

      <!-- §FESUITE (2026-10-05): a failed list read drew the banner above AND "No invite codes yet" under it; the list says
           nothing it did not read (the banner says why, the refresh button reads again) -->
      <p v-if="!loading && !loadError && !codes.length" class="iv-empty" data-testid="iv-none">
        No invite codes yet. Create one above to let someone register.
      </p>
      <p v-else-if="!loading && !loadError && !visible.length" class="iv-empty">
        No {{ filter }} codes.
      </p>

      <div v-if="visible.length" class="iv-table" data-testid="iv-table" data-tour="inv-list">
        <div class="iv-thead">
          <span>Code</span><span>Status</span><span>Uses</span>
          <span>Created</span><span>Note</span><span></span>
        </div>
        <div v-for="c in visible" :key="c.code" class="iv-row" :data-status="c.status">
          <div class="iv-cell-code">
            <code class="iv-code">{{ c.code }}</code>
            <span
              v-if="c.grants_admin" class="iv-pill iv-pill--admin"
              :title="`Redeeming grants: ${(c.admin_flags || []).map(flagLabel).join(', ') || 'admin'}`"
            >
              <Icon name="mdi:shield-account" />
              {{ (c.admin_flags || []).length === ADMIN_FLAGS.length
                  ? 'admin: all areas'
                  : 'admin: ' + (c.admin_flags || []).map(flagLabel).join(' + ') }}
            </span>
          </div>

          <div>
            <span class="iv-pill" :class="`iv-pill--${c.status}`">
              <Icon :name="statusIcon(c.status)" /> {{ statusLabel(c.status) }}
            </span>
          </div>

          <div class="iv-uses">{{ c.use_count }} / {{ c.max_uses }}</div>

          <div class="iv-when">
            <span :title="absolute(c.created_at)">{{ relative(c.created_at) }}</span>
            <small v-if="c.created_by_email" class="iv-by">by {{ c.created_by_email }}</small>
            <small v-if="c.used_by_email" class="iv-by iv-by--used">
              redeemed by {{ c.used_by_email }}<template v-if="c.used_at"> · {{ relative(c.used_at) }}</template>
            </small>
            <small v-if="c.expires_at" class="iv-by">
              {{ c.status === 'expired' ? 'expired' : 'expires' }} {{ relative(c.expires_at) }}
            </small>
          </div>

          <div class="iv-note">{{ c.note || '—' }}</div>

          <div class="iv-actions">
            <button class="iv-ghost iv-ghost--sm" @click="copy(c.code, 'Code copied')" title="Copy code">
              <Icon name="mdi:content-copy" />
            </button>
            <button
              v-if="c.status === 'active'"
              class="iv-ghost iv-ghost--sm" @click="copy(c.invite_url, 'Invite link copied')"
              title="Copy invite link"
            >
              <Icon name="mdi:link-variant" />
            </button>
            <!-- used codes are history: the server refuses to delete them, so no button -->
            <button
              v-if="c.status !== 'used'"
              class="iv-ghost iv-ghost--sm iv-ghost--danger"
              :data-testid="`iv-revoke-${c.code}`"
              @click="askRevoke(c)" title="Revoke"
            >
              <Icon name="mdi:trash-can-outline" />
            </button>
          </div>
        </div>
      </div>
    </section>

    <p v-if="toast" class="iv-toast" role="status">{{ toast }}</p>

    <!--
      ConfirmActionModal owns its own `v-if="show"` inside a <Teleport>, and it emits
      `close` (there is no `cancel`). Mounting it with an outer v-if and no `show` prop
      renders NOTHING and swallows the click — which is exactly how the admin-granting
      mint path shipped dead until the browser E2E caught it. Bind `show`, listen for
      `close`.
    -->
    <ConfirmActionModal
      :show="dlg.open"
      :title="dlg.title"
      :message="dlg.message"
      :tone="dlg.tone"
      :confirm-text="dlg.confirmText"
      :busy="dlg.busy"
      @confirm="dlg.onConfirm()"
      @close="dlg.open = false"
    />
  </div>
</template>

<script setup lang="ts">
// §FESUITE V0595: true where registration needs no code (GET /auth/registration-config beta_invite_required false)
withDefaults(defineProps<{ openRegistration?: boolean }>(), { openRegistration: false })
import { appLocale } from '@/services/appLocale'
import { ref, reactive, computed, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { useLogger } from '@/composables/useLogger'
import {
  listInviteCodes, generateInviteCodes, revokeInviteCode,
  ADMIN_FLAGS, flagLabel,
  type InviteCode, type InviteCodeStatus, type AdminFlag,
} from '@/services/api/inviteCodes'
import { useAuthStore } from '@/stores/auth'

const log = useLogger('InvitationsPanel')

const codes = ref<InviteCode[]>([])
const loading = ref(false)
const loadError = ref('')
const minting = ref(false)
const mintMsg = ref('')
const mintOk = ref(true)
const justMinted = ref<InviteCode[]>([])
const toast = ref('')

type FilterKey = 'all' | InviteCodeStatus
const filter = ref<FilterKey>('all')
const filters: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'used', label: 'Used' },
  { key: 'expired', label: 'Inactive' },
]

const form = reactive({
  count: 1,
  max_uses: 1,
  note: '' as string,
  grants_admin: false,
  // §INVRBAC — WHICH admin capability the code confers. Starts empty: turning the
  // switch on should not silently mean "everything", which is what the old
  // all-or-nothing grant did.
  admin_flags: [] as AdminFlag[],
})

const auth = useAuthStore()

/**
 * The flags THIS admin may pass on. The server clamps the same way (403 on over-reach)
 * and is the authority; disabling them here just means the operator is not offered a
 * control that would fail. A legacy is_admin superadmin may grant anything.
 */
const grantableFlags = computed(() => {
  const u = (auth.user ?? {}) as unknown as Record<string, unknown>
  if (u.is_admin === true) return ADMIN_FLAGS.map((f) => f.key)
  return ADMIN_FLAGS.filter((f) => Boolean(u[f.key])).map((f) => f.key)
})

const canGrant = (f: AdminFlag) => grantableFlags.value.includes(f)

function toggleFlag(f: AdminFlag) {
  if (!canGrant(f)) return
  const i = form.admin_flags.indexOf(f)
  if (i === -1) form.admin_flags.push(f)
  else form.admin_flags.splice(i, 1)
}

const selectedFlagLabels = computed(() =>
  ADMIN_FLAGS.filter((f) => form.admin_flags.includes(f.key)).map((f) => f.label),
)
// Kept as a string so an empty box means "never expires" rather than 0.
const expiresRaw = ref<string>('')

const mintValid = computed(() =>
  Number.isFinite(form.count) && form.count >= 1 && form.count <= 500 &&
  Number.isFinite(form.max_uses) && form.max_uses >= 1 && form.max_uses <= 10 &&
  // An admin invitation that names no area would grant everything by omission on the
  // server. Make the operator say what they mean.
  (!form.grants_admin || form.admin_flags.length > 0),
)
const mintLabel = computed(() => {
  const n = form.count || 1
  const kind = form.grants_admin ? 'admin code' : 'code'
  return `Create ${n} ${kind}${n === 1 ? '' : 's'}`
})

const counts = computed<Record<FilterKey, number>>(() => ({
  all: codes.value.length,
  active: codes.value.filter(c => c.status === 'active').length,
  used: codes.value.filter(c => c.status === 'used').length,
  expired: codes.value.filter(c => c.status === 'expired').length,
}))

const visible = computed(() =>
  filter.value === 'all' ? codes.value : codes.value.filter(c => c.status === filter.value),
)

function statusLabel(s: InviteCodeStatus) {
  return s === 'expired' ? 'inactive' : s
}
function statusIcon(s: InviteCodeStatus) {
  if (s === 'used') return 'mdi:account-check'
  if (s === 'expired') return 'mdi:clock-outline'
  return 'mdi:check-circle'
}

function absolute(iso: string) {
  try { return new Date(iso).toLocaleString(appLocale()) } catch { return iso }
}
function relative(iso: string) {
  try {
    const then = new Date(iso).getTime()
    const diff = Date.now() - then
    const fut = diff < 0
    const s = Math.abs(diff) / 1000
    const pick = (): string => {
      if (s < 60) return 'just now'
      if (s < 3600) return `${Math.floor(s / 60)}m`
      if (s < 86400) return `${Math.floor(s / 3600)}h`
      if (s < 2592000) return `${Math.floor(s / 86400)}d`
      return new Date(then).toLocaleDateString(appLocale())
    }
    const v = pick()
    if (v === 'just now' || v.includes('/') || v.includes('.')) return v
    return fut ? `in ${v}` : `${v} ago`
  } catch { return iso }
}

function flash(msg: string) {
  toast.value = msg
  window.setTimeout(() => { if (toast.value === msg) toast.value = '' }, 2200)
}

async function copy(text: string, msg: string) {
  try {
    await navigator.clipboard.writeText(text)
    flash(msg)
  } catch {
    // Clipboard is blocked on insecure origins and in some embedded webviews —
    // say so instead of silently doing nothing.
    flash('Copy blocked by the browser — select the text manually')
  }
}

async function refresh() {
  loading.value = true
  loadError.value = ''
  try {
    codes.value = await listInviteCodes({ limit: 500 })
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { detail?: string } } }
    loadError.value = err?.response?.status === 403
      ? 'Your account does not have the admin_support right needed to manage invite codes.'
      : (err?.response?.data?.detail || 'Could not load invite codes.')
    log.error('load failed', e)
  } finally {
    loading.value = false
  }
}

// ── confirm modal plumbing (named `dlg`, NOT `confirm` — see note) ────────────────────────────────────
const dlg = reactive({
  open: false,
  title: '',
  message: '',
  tone: 'primary' as 'primary' | 'warn' | 'danger',
  confirmText: 'Confirm',
  busy: false,
  onConfirm: () => {},
})

function askMint() {
  const n = form.count || 1
  if (!form.grants_admin) { void doMint(); return }
  // Only the admin-granting path is gated — an ordinary code is cheap and revocable.
  dlg.open = true
  dlg.tone = 'warn'
  dlg.title = 'Create administrator invite'
  dlg.confirmText = `Create ${n} admin code${n === 1 ? '' : 's'}`
  const labels = selectedFlagLabels.value
  const all = labels.length === ADMIN_FLAGS.length
  // Name the exact authority. "Are you sure" tells the operator nothing they did not
  // already know; the list of areas is the thing they can actually check.
  dlg.message =
    `Anyone who redeems ${n === 1 ? 'this code' : 'one of these codes'} becomes an administrator ` +
    `for <strong>${labels.join(', ')}</strong> the moment they register` +
    (all ? ', which is every admin area on this registry.' : '.') +
    ' They choose their own password, so you will never know their credentials.' +
    ' The account gets these capabilities and no others: the legacy <code>is_admin</code>' +
    ' super-flag is not granted, so what it may do stays visible and can be narrowed later.'
  dlg.busy = false
  dlg.onConfirm = () => { void doMint(true) }
}

async function doMint(fromModal = false) {
  minting.value = true
  mintMsg.value = ''
  if (fromModal) dlg.busy = true
  try {
    const days = expiresRaw.value.trim() === '' ? null : Number(expiresRaw.value)
    const batch = await generateInviteCodes({
      count: form.count,
      max_uses: form.max_uses,
      expires_days: days && Number.isFinite(days) ? days : null,
      note: form.note.trim() || null,
      grants_admin: form.grants_admin,
      // Only sent when the switch is on: flags without the switch are authority
      // nobody confirmed, and the server ignores them for the same reason.
      admin_flags: form.grants_admin ? [...form.admin_flags] : null,
    })
    justMinted.value = batch.codes
    mintOk.value = true
    mintMsg.value = `Created ${batch.count}.`
    dlg.open = false
    await refresh()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } }
    mintOk.value = false
    mintMsg.value = err?.response?.data?.detail || 'Creating the codes failed.'
    log.error('mint failed', e)
  } finally {
    minting.value = false
    dlg.busy = false
  }
}

function askRevoke(c: InviteCode) {
  dlg.open = true
  dlg.tone = 'danger'
  dlg.title = 'Revoke invite code'
  dlg.confirmText = 'Revoke'
  dlg.message =
    `<code>${c.code}</code> will be deleted permanently. Anyone holding this code or its ` +
    'link will no longer be able to register. This cannot be undone.' +
    (c.grants_admin ? ' <strong>This is an administrator code.</strong>' : '')
  dlg.busy = false
  dlg.onConfirm = async () => {
    dlg.busy = true
    try {
      await revokeInviteCode(c.code)
      justMinted.value = justMinted.value.filter(x => x.code !== c.code)
      dlg.open = false
      flash('Code revoked')
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      loadError.value = err?.response?.data?.detail || 'Revoke failed.'
      dlg.open = false
      log.error('revoke failed', e)
    } finally {
      dlg.busy = false
    }
  }
}

onMounted(() => { void refresh() })
</script>

<style scoped>
.iv-panel { display: flex; flex-direction: column; gap: 1.25rem; }

.iv-header { display: flex; align-items: flex-start; gap: 1rem; }
.iv-header-text { flex: 1; min-width: 0; }
.iv-title { margin: 0 0 0.25rem; font-size: 1rem; letter-spacing: 0.04em; color: var(--nc-text, #e8f4f4); }
.iv-sub { margin: 0; font-size: 0.8rem; color: rgba(var(--nc-primary-rgb), 0.72); line-height: 1.5; }

.iv-sec { border: 1px solid rgba(var(--nc-primary-rgb), 0.16); border-radius: 6px; overflow: hidden; }
.iv-sec-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.55rem 0.85rem; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem; letter-spacing: 0.16em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.85);
  background: rgba(var(--nc-primary-rgb), 0.06);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.14);
}
.iv-count {
  margin-left: auto; font-size: 0.7rem; letter-spacing: 0.06em;
  color: rgba(var(--nc-primary-rgb), 0.7);
}

/* ── mint form ── */
.iv-form {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.75rem; padding: 0.9rem;
}
.iv-field { display: flex; flex-direction: column; gap: 0.3rem; min-width: 0; }
.iv-field--wide { grid-column: 1 / -1; }
.iv-lbl { font-size: 0.72rem; color: rgba(var(--nc-primary-rgb), 0.8); letter-spacing: 0.03em; }
.iv-opt { color: rgba(var(--nc-primary-rgb), 0.45); }
.iv-in {
  background: rgba(0, 0, 0, 0.3); color: var(--nc-text, #e8f4f4);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 4px;
  padding: 0.42rem 0.55rem; font-size: 0.85rem; font-family: inherit; width: 100%;
}
.iv-in:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.7); }

.iv-adminbox {
  display: flex; gap: 0.75rem; align-items: flex-start;
  margin: 0 0.9rem; padding: 0.7rem 0.8rem; border-radius: 5px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  background: rgba(0, 0, 0, 0.18); transition: border-color 0.15s, background 0.15s;
}
.iv-adminbox--on { border-color: rgba(255, 176, 32, 0.65); background: rgba(255, 176, 32, 0.08); }
.iv-adminbox-text { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.78rem; line-height: 1.5; }
.iv-adminbox-text strong { color: var(--nc-text, #e8f4f4); font-weight: 600; display: flex; align-items: center; gap: 0.35rem; }
.iv-adminbox--on .iv-adminbox-text strong { color: #ffc857; }
.iv-adminbox-text span { color: rgba(var(--nc-primary-rgb), 0.72); }
.iv-adminbox code { font-family: 'IBM Plex Mono', monospace; font-size: 0.74rem; }

/* §INVRBAC — the per-area picker. Amber like the admin strip it belongs to, so the
   whole admin-granting path reads as one thing rather than two controls that happen
   to be adjacent. */
.iv-flags { margin: 0.5rem 0.9rem 0; padding: 0.6rem 0.7rem; border-radius: 5px;
  border: 1px solid rgba(255, 176, 32, 0.32); background: rgba(255, 176, 32, 0.05); }
.iv-flags-head {
  display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem;
  font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
  color: #ffc857; margin-bottom: 0.5rem;
}
.iv-flags-hint { font-size: 0.68rem; letter-spacing: 0; text-transform: none; opacity: 0.7; }
.iv-flag {
  display: flex; align-items: flex-start; gap: 0.55rem; padding: 0.4rem 0.45rem;
  border-radius: 4px; cursor: pointer; transition: background 0.12s;
}
.iv-flag:hover { background: rgba(255, 176, 32, 0.07); }
.iv-flag.on { background: rgba(255, 176, 32, 0.11); }
.iv-flag.off { cursor: not-allowed; opacity: 0.42; }
.iv-flag input { margin-top: 0.2rem; accent-color: #ffc857; cursor: inherit; }
.iv-flag-text { display: flex; flex-direction: column; gap: 0.1rem; font-size: 0.78rem; line-height: 1.45; }
.iv-flag-text strong { color: var(--nc-text, #e8f4f4); font-weight: 600; }
.iv-flag.on .iv-flag-text strong { color: #ffc857; }
.iv-flag-text small { color: rgba(var(--nc-primary-rgb), 0.65); font-size: 0.72rem; }
.iv-flag-lock { margin-left: auto; opacity: 0.6; flex: 0 0 auto; }
.iv-flags-warn { margin: 0.4rem 0 0; font-size: 0.74rem; color: #ffb020; line-height: 1.45; }

.iv-sw { position: relative; flex: 0 0 auto; width: 34px; height: 18px; cursor: pointer; margin-top: 0.15rem; }
.iv-sw input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; }
.iv-sw-track {
  position: absolute; inset: 0; border-radius: 9px;
  background: rgba(0, 0, 0, 0.5); border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  transition: background 0.15s, border-color 0.15s; pointer-events: none;
}
.iv-sw-track::after {
  content: ''; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px;
  border-radius: 50%; background: rgba(var(--nc-primary-rgb), 0.6); transition: transform 0.15s, background 0.15s;
}
.iv-sw input:checked + .iv-sw-track { background: rgba(255, 176, 32, 0.3); border-color: rgba(255, 176, 32, 0.8); }
.iv-sw input:checked + .iv-sw-track::after { transform: translateX(16px); background: #ffc857; }
.iv-sw input:focus-visible + .iv-sw-track { outline: 2px solid var(--nc-primary); outline-offset: 2px; }

.iv-mint-actions { display: flex; align-items: center; gap: 0.75rem; padding: 0.9rem; flex-wrap: wrap; }
.iv-mintmsg { font-size: 0.78rem; color: rgba(var(--nc-primary-rgb), 0.8); }
.iv-mintmsg--err { color: #ff8a8a; }

.iv-primary {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: rgba(var(--nc-primary-rgb), 0.16); color: var(--nc-primary);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.5); border-radius: 4px;
  padding: 0.45rem 0.85rem; font-size: 0.82rem; cursor: pointer; font-family: inherit;
}
.iv-primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.3); color: #fff; }
.iv-primary:disabled { opacity: 0.45; cursor: not-allowed; }

.iv-ghost {
  display: inline-flex; align-items: center; gap: 0.35rem;
  background: transparent; color: rgba(var(--nc-primary-rgb), 0.85);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 4px;
  padding: 0.35rem 0.6rem; font-size: 0.76rem; cursor: pointer; font-family: inherit;
}
.iv-ghost:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.12); color: #fff; }
.iv-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.iv-ghost--sm { padding: 0.25rem 0.45rem; font-size: 0.72rem; }
.iv-ghost--danger { color: rgba(255, 138, 138, 0.9); border-color: rgba(255, 138, 138, 0.35); }
.iv-ghost--danger:hover { background: rgba(255, 80, 80, 0.16); color: #ff9a9a; }
.iv-linkbtn {
  background: none; border: none; color: rgba(var(--nc-primary-rgb), 0.7);
  text-decoration: underline; cursor: pointer; font-size: 0.72rem; font-family: inherit; margin-left: auto;
}

/* ── freshly minted ── */
.iv-fresh { margin: 0 0.9rem 0.9rem; border: 1px solid rgba(80, 220, 160, 0.35); border-radius: 5px; background: rgba(80, 220, 160, 0.06); }
.iv-fresh-head {
  display: flex; align-items: center; gap: 0.4rem; padding: 0.5rem 0.7rem;
  font-size: 0.76rem; color: #7fe3b5; border-bottom: 1px solid rgba(80, 220, 160, 0.22);
}
.iv-fresh-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.45rem 0.7rem; flex-wrap: wrap; }
.iv-fresh-hint { margin: 0; padding: 0 0.7rem 0.6rem; font-size: 0.72rem; color: rgba(var(--nc-primary-rgb), 0.6); }
.iv-spacer { flex: 1; }

/* ── filters ── */
.iv-filters { display: flex; gap: 0.4rem; padding: 0.75rem 0.9rem 0; flex-wrap: wrap; }
.iv-fpill {
  display: inline-flex; align-items: center; gap: 0.35rem;
  background: transparent; color: rgba(var(--nc-primary-rgb), 0.75);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22); border-radius: 999px;
  padding: 0.25rem 0.7rem; font-size: 0.74rem; cursor: pointer; font-family: inherit;
}
.iv-fpill.active { background: rgba(var(--nc-primary-rgb), 0.18); color: #fff; border-color: rgba(var(--nc-primary-rgb), 0.6); }
.iv-fcount { font-size: 0.68rem; opacity: 0.7; }

/* ── table ── */
.iv-table { padding: 0.5rem 0.9rem 0.9rem; }
.iv-thead, .iv-row {
  display: grid;
  grid-template-columns: minmax(190px, 1.4fr) 108px 62px minmax(150px, 1fr) minmax(90px, 0.9fr) 108px;
  gap: 0.5rem; align-items: center;
}
.iv-thead {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.12em;
  text-transform: uppercase; color: rgba(var(--nc-primary-rgb), 0.55);
  padding: 0.35rem 0.4rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.14);
}
.iv-row { padding: 0.5rem 0.4rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08); font-size: 0.78rem; }
.iv-row:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.iv-row[data-status='used'], .iv-row[data-status='expired'] { opacity: 0.68; }

.iv-cell-code { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; min-width: 0; }
.iv-code {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;
  color: var(--nc-text, #e8f4f4); word-break: break-all;
}
.iv-uses { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: rgba(var(--nc-primary-rgb), 0.8); }
.iv-when { display: flex; flex-direction: column; gap: 0.1rem; min-width: 0; }
.iv-by { font-size: 0.68rem; color: rgba(var(--nc-primary-rgb), 0.55); word-break: break-all; }
.iv-by--used { color: rgba(var(--nc-primary-rgb), 0.75); }
.iv-note { font-size: 0.74rem; color: rgba(var(--nc-primary-rgb), 0.7); word-break: break-word; }
.iv-actions { display: flex; gap: 0.25rem; justify-content: flex-end; }

.iv-pill {
  display: inline-flex; align-items: center; gap: 0.25rem;
  padding: 0.12rem 0.45rem; border-radius: 999px;
  font-size: 0.68rem; letter-spacing: 0.04em;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3); color: rgba(var(--nc-primary-rgb), 0.9);
}
.iv-pill--active  { border-color: rgba(80, 220, 160, 0.5); color: #7fe3b5; background: rgba(80, 220, 160, 0.1); }
.iv-pill--used    { border-color: rgba(var(--nc-primary-rgb), 0.35); }
.iv-pill--expired { border-color: rgba(255, 176, 32, 0.45); color: #ffc857; background: rgba(255, 176, 32, 0.08); }
.iv-pill--admin   { border-color: rgba(255, 176, 32, 0.6); color: #ffc857; background: rgba(255, 176, 32, 0.1); }

.iv-empty { padding: 1rem 0.9rem; margin: 0; font-size: 0.8rem; color: rgba(var(--nc-primary-rgb), 0.55); }

.iv-banner {
  display: flex; align-items: center; gap: 0.45rem; margin: 0;
  padding: 0.55rem 0.75rem; border-radius: 4px; font-size: 0.8rem;
}
.iv-banner--err { background: rgba(255, 80, 80, 0.12); border: 1px solid rgba(255, 80, 80, 0.35); color: #ff9a9a; }

.iv-toast {
  position: fixed; bottom: 1.5rem; left: 50%; transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.88); color: var(--nc-primary);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4); border-radius: 4px;
  padding: 0.5rem 0.9rem; font-size: 0.8rem; z-index: 3000; margin: 0;
}

.iv-spin { animation: iv-rot 0.9s linear infinite; }
@keyframes iv-rot { to { transform: rotate(360deg); } }

@media (max-width: 780px) {
  .iv-thead { display: none; }
  .iv-row {
    grid-template-columns: 1fr auto; gap: 0.35rem 0.5rem;
    padding: 0.7rem 0.4rem;
  }
  .iv-cell-code { grid-column: 1 / -1; }
  .iv-note { grid-column: 1 / -1; }
  .iv-actions { grid-column: 2; justify-content: flex-end; }
}
</style>
