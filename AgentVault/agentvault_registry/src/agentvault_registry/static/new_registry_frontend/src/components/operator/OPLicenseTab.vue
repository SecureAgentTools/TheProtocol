<template>
  <section class="op-tab op-license">
    <!-- §FESUITE (V0575): a lifecycle not read yet, or not read at all, is not "no licence" -->
    <div v-if="!hasLicense && lifecycleRead === 'reading'" class="op-license-na" role="status">Loading…</div>
    <ReadFailedNotice v-else-if="!hasLicense && lifecycleRead === 'unread'" :retry="() => emit('refresh-shell')" />
    <!-- Mainframe / non-licensed case -->
    <div v-else-if="!hasLicense" class="op-license-na">
      <div class="op-license-na-title">No federation license on this registry</div>
      <p class="op-license-na-body">
        Federation licenses are issued to the registries that join a network, frames and <em>cloud operators</em>
        alike. The genesis registry carries none: it issues them.
      </p>
      <p class="op-license-na-body" v-if="lifecycle?.application">
        Your application <code class="op-code">{{ lifecycle.application.name }}</code> is
        <strong>{{ lifecycle.application.status }}</strong>, and a license will be created when the
        cloud op is provisioned. Head to the Account tab to provision.
      </p>
    </div>

    <!-- Has license — show it + rotation UI -->
    <template v-else>
      <div :class="['op-license-card', licenseTone]">
        <div class="op-license-card-header">
          <div>
            <div class="op-license-eyebrow">Active federation license</div>
            <h2 class="op-license-title">{{ license.federation_tier || 'standard' }} tier</h2>
          </div>
          <span :class="['op-status-pill', statusPillTone(license.status)]">
            {{ license.status }}
          </span>
        </div>
        <dl class="op-license-dl">
          <div><dt>Key prefix</dt>
            <dd><code class="op-code">{{ license.license_key_prefix }}…</code></dd>
          </div>
          <div><dt>Operator DID</dt>
            <dd><code class="op-code">{{ truncateDid(license.operator_did) }}</code></dd>
          </div>
          <div><dt>Issued</dt><dd>{{ formatAbsolute(license.issued_at) }}</dd></div>
          <div><dt>Last seen</dt><dd>{{ formatAbsolute(license.last_seen_at) }}</dd></div>
          <div><dt>Events emitted</dt><dd>{{ license.event_count.toLocaleString(appLocale()) }}</dd></div>
        </dl>
      </div>

      <!-- Rotate panel -->
      <div class="op-rotate-panel">
        <div class="op-rotate-header">
          <h3 class="op-rotate-title">Rotate license key</h3>
          <p class="op-rotate-subtitle">
            Rotation invalidates the current key immediately. The new key is shown ONCE — save it before closing the modal.
            Your registry's running config keeps the old key until you restart, so plan a tear-down window if rotating defensively.
          </p>
        </div>
        <div class="op-rotate-form">
          <label class="op-rotate-label">
            <span>Current license key</span>
            <input
              v-model="currentKey"
              :type="showKey ? 'text' : 'password'"
              class="op-rotate-input"
              placeholder="Paste your active license key here (proves ownership)"
              autocomplete="off"
              spellcheck="false"
            />
            <button type="button" class="op-rotate-eye" @click="showKey = !showKey">
              {{ showKey ? 'hide' : 'show' }}
            </button>
          </label>
          <label class="op-rotate-label">
            <span>Reason</span>
            <select v-model="reason" class="op-rotate-input">
              <option value="periodic_rotation">Periodic rotation (recommended quarterly)</option>
              <option value="compromise_suspected">Compromise suspected</option>
              <option value="manual_audit">Manual audit / drill</option>
              <option value="rolling_drill">Rolling drill (planned exercise)</option>
            </select>
          </label>
          <div class="op-rotate-actions">
            <button
              type="button"
              class="op-btn-danger"
              :disabled="!canRotate || rotating"
              @click="onConfirmRotate"
            >
              <span v-if="rotating" class="op-spinner-sm" />
              <span>Rotate license</span>
            </button>
            <span class="op-rotate-hint" v-if="!currentKey">Paste the current key above to enable rotation</span>
          </div>
        </div>
      </div>

      <!-- Rotation result modal (one-time key reveal) -->
      <Teleport to="body">
        <div
          v-if="rotationResult"
          class="op-modal-backdrop"
          role="dialog"
          aria-labelledby="op-rotation-title"
          aria-modal="true"
          @click.self="acknowledgeRotation"
        >
          <div class="op-modal">
            <div class="op-modal-header">
              <h3 id="op-rotation-title" class="op-modal-title">New license key — save now</h3>
              <button type="button" class="op-modal-close" @click="acknowledgeRotation" aria-label="Close">×</button>
            </div>
            <div class="op-modal-body">
              <div class="op-modal-warning">
                <strong>Shown once.</strong> This is the only time you'll see the new key. The old one is now invalid for fresh rotations
                (idempotent replay of THIS rotation will still work for the next 24h).
              </div>
              <div class="op-new-key-box">
                <code class="op-new-key">{{ rotationResult.new_license_key }}</code>
                <button type="button" class="op-new-key-copy" @click="copyNewKey" :class="{ 'op-new-key-copy--copied': copied }">
                  {{ copied ? 'copied' : 'copy' }}
                </button>
              </div>
              <dl class="op-rotation-meta">
                <div><dt>Prefix</dt><dd><code class="op-code">{{ rotationResult.new_license_key_prefix }}…</code></dd></div>
                <div><dt>Rotated at</dt><dd>{{ formatAbsolute(rotationResult.rotated_at) }}</dd></div>
                <div><dt>Rotation #</dt><dd>{{ rotationResult.rotation_id }}</dd></div>
                <div v-if="rotationResult.expires_at"><dt>Expires</dt><dd>{{ formatAbsolute(rotationResult.expires_at) }}</dd></div>
              </dl>
              <div class="op-rotation-next">
                <strong>Next step:</strong> update your operator's <code class="op-code">.env.operator</code>
                with the new <code class="op-code">FEDERATION_LICENSE_KEY=</code> value, then run:
                <LocalCommand
                  :command="`tp license rotate --new-key &lt;PASTED-ABOVE&gt; --confirm`"
                  caption="Persists the new key to .env.operator + restarts registry container. Old key kept in a backup file."
                  tone="warning"
                />
              </div>
            </div>
            <div class="op-modal-footer">
              <button type="button" class="op-btn-primary" @click="acknowledgeRotation">
                I have saved the key
              </button>
            </div>
          </div>
        </div>
      </Teleport>

      <!-- Rotation error -->
      <div v-if="rotationError" class="op-rotation-error">
        <strong>Rotation failed.</strong> {{ rotationError }}
      </div>
    </template>

    <!-- Local CLI bridge -->
    <div class="op-cli-bridge">
      <div class="op-cli-eyebrow">From terminal</div>
      <LocalCommand
        :command="`tp license show`"
        caption="Prints the local license metadata (prefix, expiry, tier). Reads ~/.config/theprotocol/license.json."
      />
      <LocalCommand
        :command="`tp license verify`"
        caption="Round-trips your license against the mainframe. Detects revocation, suspension, drift."
      />
      <LocalCommand
        :command="`tp license rotate --reason periodic_rotation`"
        caption="CLI-side rotation — equivalent to the form above. Persists the new key + restarts registry automatically."
        tone="warning"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed } from 'vue'
import LocalCommand from './LocalCommand.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { rotateOwnLicense, newIdempotencyKey, type OperatorLifecycle, type RotateSelfResponse } from '@/services/api/operator'

interface Props {
  lifecycle: OperatorLifecycle | null
  /** the portal's read of the lifecycle: 'read' when the lifecycle above is the registry's answer */
  lifecycleRead?: 'reading' | 'read' | 'unread'
}
const props = withDefaults(defineProps<Props>(), { lifecycleRead: 'read' })
const emit = defineEmits<{ (e: 'refresh-shell'): void }>()

const license = computed(() => props.lifecycle?.federation_license)
const hasLicense = computed(() => Boolean(license.value))
const licenseTone = computed(() => {
  const s = (license.value?.status || '').toLowerCase()
  if (s === 'active') return 'op-license-card--ok'
  if (s === 'suspended') return 'op-license-card--warn'
  return 'op-license-card--bad'
})

const currentKey = ref('')
const showKey = ref(false)
const reason = ref<'periodic_rotation' | 'compromise_suspected' | 'manual_audit' | 'rolling_drill'>('periodic_rotation')
const rotating = ref(false)
const rotationResult = ref<RotateSelfResponse | null>(null)
const rotationError = ref<string | null>(null)
const copied = ref(false)

const canRotate = computed(() => currentKey.value.trim().length >= 16)

async function onConfirmRotate() {
  if (!canRotate.value || rotating.value) return
  const confirmed = window.confirm(
    'Rotate license key NOW?\n\n' +
    '— The current key becomes invalid for fresh authentication immediately.\n' +
    '— The new key is shown ONCE. Save it before closing the modal.\n' +
    '— Idempotent: re-clicking within 24h returns the SAME new key.\n' +
    '— Reason will be logged for audit.\n\n' +
    'Proceed?'
  )
  if (!confirmed) return

  rotating.value = true
  rotationError.value = null
  try {
    const idem = newIdempotencyKey('lic-rot')
    const result = await rotateOwnLicense({ reason: reason.value }, currentKey.value.trim(), idem)
    rotationResult.value = result
    currentKey.value = ''  // wipe input
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || 'Unknown error'
    rotationError.value = typeof detail === 'string' ? detail : JSON.stringify(detail)
  } finally {
    rotating.value = false
  }
}

async function copyNewKey() {
  if (!rotationResult.value) return
  try {
    await navigator.clipboard.writeText(rotationResult.value.new_license_key)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch { /* swallow */ }
}

function acknowledgeRotation() {
  rotationResult.value = null
  copied.value = false
}

function statusPillTone(s: string): string {
  const lower = (s || '').toLowerCase()
  if (lower === 'active') return 'op-status-pill--ok'
  if (lower === 'suspended') return 'op-status-pill--warn'
  return 'op-status-pill--down'
}

function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(appLocale(), { dateStyle: 'medium', timeStyle: 'short' }) }
  catch { return iso }
}

function truncateDid(did: string): string {
  if (!did || did.length <= 40) return did || '—'
  return did.slice(0, 22) + '…' + did.slice(-10)
}
</script>

<style scoped>
.op-tab { padding: 1.2rem 1.6rem 2rem; }

.op-license-na {
  padding: 2rem;
  background: rgba(0, 8, 14, 0.4);
  border: 1px dashed rgba(255, 255, 255, 0.18);
  border-radius: 4px;
  text-align: center;
}
.op-license-na-title {
  font-size: 1.05rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.85); margin-bottom: 0.6rem;
}
.op-license-na-body {
  margin: 0 auto 0.5rem; max-width: 560px;
  font-size: 0.86rem;
  color: rgba(255, 255, 255, 0.55); line-height: 1.6;
}
.op-license-na-body em { color: rgba(var(--nc-primary-rgb), 0.85); font-style: normal; }

.op-license-card {
  padding: 1.2rem 1.4rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid;
  border-radius: 4px;
}
.op-license-card--ok   { border-color: rgba(0, 230, 118, 0.28); }
.op-license-card--warn { border-color: rgba(255, 176, 0, 0.32); }
.op-license-card--bad  { border-color: rgba(255, 82, 82, 0.32); }

.op-license-card-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 1rem;
  padding-bottom: 0.7rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.op-license-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  margin-bottom: 0.3rem;
}
.op-license-title {
  margin: 0; font-size: 1.3rem; font-weight: 600;
  text-transform: capitalize;
  color: rgba(255, 255, 255, 0.9);
}

.op-status-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 600;
  padding: 0.2rem 0.55rem;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.op-status-pill--ok   { color: #00e676; background: rgba(0, 230, 118, 0.08); }
.op-status-pill--warn { color: #ffb300; background: rgba(255, 179, 0, 0.08); }
.op-status-pill--down { color: #ff5252; background: rgba(255, 82, 82, 0.08); }

.op-license-dl > div {
  display: grid; grid-template-columns: 160px 1fr; gap: 0.6rem;
  padding: 0.35rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05);
  font-size: 0.8rem;
}
.op-license-dl > div:last-child { border-bottom: none; }
.op-license-dl dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.45); text-transform: uppercase;
}
.op-license-dl dd { margin: 0; color: rgba(255, 255, 255, 0.85); }

.op-rotate-panel {
  margin-top: 1.4rem;
  padding: 1.2rem 1.4rem;
  background: rgba(28, 0, 0, 0.35);
  border: 1px solid rgba(255, 82, 82, 0.25);
  border-radius: 4px;
}
.op-rotate-header { margin-bottom: 1rem; }
.op-rotate-title {
  margin: 0 0 0.4rem; font-size: 1rem; font-weight: 600;
  color: rgba(255, 200, 200, 0.95);
}
.op-rotate-subtitle {
  margin: 0; font-size: 0.78rem; line-height: 1.55;
  color: rgba(255, 220, 220, 0.65);
}
.op-rotate-form { display: flex; flex-direction: column; gap: 0.8rem; }
.op-rotate-label {
  display: flex; flex-direction: column; gap: 0.3rem;
  position: relative;
}
.op-rotate-label > span {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 200, 200, 0.75); font-weight: 600;
  font-family: 'IBM Plex Mono', monospace;
}
.op-rotate-input {
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(255, 82, 82, 0.25);
  color: rgba(255, 255, 255, 0.9);
  padding: 0.55rem 0.75rem;
  font-size: 0.85rem;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  border-radius: 2px; outline: none;
  width: 100%;
  min-height: 38px;
}
.op-rotate-input:focus {
  border-color: rgba(255, 82, 82, 0.5);
  box-shadow: 0 0 8px rgba(255, 82, 82, 0.15);
}
.op-rotate-eye {
  position: absolute; right: 0.5rem; top: 1.55rem;
  background: transparent; border: none;
  color: rgba(255, 255, 255, 0.45);
  font-size: 0.7rem; cursor: pointer; padding: 0.2rem 0.4rem;
  font-family: 'IBM Plex Mono', monospace;
}
.op-rotate-eye:hover { color: rgba(255, 255, 255, 0.85); }
.op-rotate-actions { display: flex; align-items: center; gap: 0.8rem; margin-top: 0.4rem; }
.op-rotate-hint {
  font-size: 0.72rem; color: rgba(255, 200, 200, 0.6);
  font-family: 'IBM Plex Mono', monospace;
}

.op-btn-primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
  padding: 0.55rem 1.2rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, border-color 0.18s, box-shadow 0.18s;
  min-height: 36px;
}
.op-btn-primary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.28);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.2);
}
.op-btn-danger {
  background: rgba(255, 82, 82, 0.18);
  border: 1px solid rgba(255, 82, 82, 0.55);
  color: rgba(255, 200, 200, 1);
  padding: 0.55rem 1.2rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, box-shadow 0.18s;
  display: inline-flex; align-items: center; gap: 0.5rem; min-height: 36px;
}
.op-btn-danger:hover:not(:disabled) {
  background: rgba(255, 82, 82, 0.32);
  box-shadow: 0 0 18px rgba(255, 82, 82, 0.25);
}
.op-btn-danger:disabled { opacity: 0.4; cursor: not-allowed; }

.op-spinner-sm {
  width: 11px; height: 11px;
  border: 1.5px solid rgba(255, 82, 82, 0.25);
  border-top-color: rgba(255, 200, 200, 0.95);
  border-radius: 50%; animation: opSpin 0.8s linear infinite;
}
@keyframes opSpin { to { transform: rotate(360deg); } }

.op-rotation-error {
  margin-top: 1rem; padding: 0.8rem 1rem;
  background: rgba(40, 0, 0, 0.6);
  border: 1px solid rgba(255, 82, 82, 0.45);
  border-radius: 3px;
  font-size: 0.82rem; color: rgba(255, 200, 200, 0.95);
}

/* Modal */
.op-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  z-index: 10100;
  display: flex; align-items: center; justify-content: center;
  padding: 1rem;
}
.op-modal {
  max-width: 580px; width: 100%; max-height: 90vh; overflow-y: auto;
  background: rgba(0, 8, 14, 0.95);
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
.op-modal-warning {
  padding: 0.7rem 0.9rem;
  background: rgba(255, 176, 0, 0.1);
  border-left: 3px solid rgba(255, 176, 0, 0.7);
  font-size: 0.8rem; line-height: 1.55;
  color: rgba(255, 220, 160, 0.95);
  margin-bottom: 1rem;
}
.op-new-key-box {
  display: flex; gap: 0.5rem; align-items: stretch;
  margin-bottom: 1rem;
}
.op-new-key {
  flex: 1; padding: 0.7rem 0.85rem;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(0, 230, 118, 0.3);
  color: #b9ffe0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.86rem; word-break: break-all;
  border-radius: 2px;
}
.op-new-key-copy {
  background: rgba(0, 230, 118, 0.15);
  border: 1px solid rgba(0, 230, 118, 0.5);
  color: #b9ffe0;
  padding: 0 1rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s;
}
.op-new-key-copy:hover { background: rgba(0, 230, 118, 0.28); }
.op-new-key-copy--copied { background: rgba(0, 230, 118, 0.35); }

.op-rotation-meta {
  margin: 0 0 1rem;
  padding: 0.7rem 0.9rem;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 2px;
}
.op-rotation-meta > div {
  display: grid; grid-template-columns: 100px 1fr; gap: 0.5rem;
  padding: 0.2rem 0; font-size: 0.78rem;
}
.op-rotation-meta dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.4); text-transform: uppercase;
}
.op-rotation-meta dd { margin: 0; color: rgba(255, 255, 255, 0.85); }
.op-rotation-next {
  font-size: 0.82rem; color: rgba(255, 255, 255, 0.75); line-height: 1.55;
}
.op-rotation-next strong { color: rgba(255, 255, 255, 1); }

.op-code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  background: rgba(0, 0, 0, 0.32);
  padding: 0.1rem 0.4rem;
  border-radius: 2px;
  color: #c0e4ff;
}

.op-cli-bridge {
  margin-top: 1.8rem;
  padding-top: 1.3rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.op-cli-eyebrow {
  font-size: 0.65rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45); font-weight: 600;
  margin-bottom: 0.6rem;
}

@media (max-width: 640px) {
  .op-tab { padding: 1rem; }
  .op-license-dl > div, .op-rotation-meta > div { grid-template-columns: 1fr; gap: 0.15rem; }
}
</style>
