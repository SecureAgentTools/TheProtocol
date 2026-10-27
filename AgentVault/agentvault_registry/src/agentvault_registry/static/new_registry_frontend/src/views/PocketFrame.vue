<!--
  POCKET FRAME — mobile control surface (f-mobile, 2026-07-07 · AAA pass).
  Two jobs, one mobile-first page:
    1) PAIR THIS PHONE — mint a device-scoped avreg_ API key, render a shown-once
       QR the POCKET FRAME app scans to store the session (Keystore/Enclave).
    2) DEVICES — register/list/revoke push targets (ntfy live; fcm/apns stubbed),
       with per-device notification prefs (delegation always; transfers opt-in).
  All calls hit developer-JWT endpoints that already exist. No money path.
-->
<template>
  <div class="pf-wrap">
    <header class="pf-head">
      <div class="pf-head-badge"><Icon name="mdi:cellphone-link" /></div>
      <div class="pf-head-txt">
        <h1>POCKET FRAME</h1>
        <p>Pair your phone and control push notifications for your agents.</p>
      </div>
    </header>

    <!-- WEB PUSH (2026-07-25): the Protocol app's OWN notification channel. No second app to
         install, no vendor account — W3C Web Push with a key we generate ourselves. -->
    <section class="pf-card pf-webpush">
      <h2><Icon name="mdi:bell-ring" /> Notifications on this device</h2>
      <p class="pf-sub">
        Get confirmations directly from this app — no separate notification app required.
      </p>
      <div class="pf-wp-row">
        <div class="pf-wp-state">
          <Icon :name="wpSubscribed ? 'mdi:shield-check' : 'mdi:bell-off-outline'"
                :class="wpSubscribed ? 'pf-ok' : 'pf-dim'" />
          <span v-if="!wpSupported">This browser cannot receive push. On iPhone, add this app to your Home Screen first.</span>
          <span v-else-if="wpDenied">Notifications are blocked for this site. Re-allow them in your browser settings, then reload.</span>
          <span v-else-if="wpSubscribed">This device is subscribed. Confirmations arrive here.</span>
          <span v-else>Not subscribed yet — confirmations will not reach this device.</span>
        </div>
        <button v-if="wpSupported && !wpSubscribed" class="pf-btn pf-btn-primary"
                :disabled="wpBusy || wpDenied" @click="wpSubscribe">
          <Icon name="mdi:bell-ring" /> {{ wpBusy ? 'Enabling…' : 'Enable notifications' }}
        </button>
        <button v-else-if="wpSubscribed" class="pf-btn" :disabled="wpBusy" @click="wpUnsubscribe">
          <Icon name="mdi:bell-off-outline" /> Turn off
        </button>
      </div>
      <p v-if="wpMsg" class="pf-wp-msg">{{ wpMsg }}</p>
    </section>

    <!-- ── PAIR ─────────────────────────────────────────────────────── -->
    <section class="pf-card">
      <h2><Icon name="mdi:qrcode" /> Pair this phone</h2>
      <p class="pf-muted">
        Create a key for this phone and scan it with the POCKET FRAME app. The key is
        stored in your phone's secure hardware and is shown <strong>only once</strong>.
        It cannot reach admin tools or make other keys, and it expires after {{ PAIR_KEY_DAYS }} days.
        Removing the phone below revokes its key; Developer → API Keys can revoke it too.
      </p>
      <div class="pf-field-row">
        <input v-model="pairLabel" class="pf-input" aria-label="Device label" placeholder="Device label (e.g. Commander Pixel 9)" maxlength="60" @keyup.enter="pairPhone" />
        <button class="pf-btn pf-btn-primary pf-btn-wide" :disabled="pairing" @click="pairPhone">
          <Icon :name="pairing ? 'mdi:loading' : 'mdi:cellphone'" :class="{ 'pf-spin': pairing }" /> {{ pairing ? 'Creating…' : 'Pair phone' }}
        </button>
      </div>

      <transition name="pf-fade">
        <div v-if="pairPayload" class="pf-pair-result">
          <canvas ref="pairCanvas" class="pf-qr" width="240" height="240"></canvas>
          <div class="pf-pair-side">
            <p class="pf-warn"><Icon name="mdi:alert-octagon" /> Shown once — scan now or copy it.</p>
            <p v-if="pairExpires" class="pf-muted" data-testid="pf-pair-expires">This key expires on {{ pairExpires }}; pair the phone again then.</p>
            <button class="pf-btn pf-btn-block" :class="{ 'pf-btn-ok': copiedPair }" @click="copy(pairPayload, 'pair')">
              <Icon :name="copiedPair ? 'mdi:check-circle' : 'mdi:content-copy'" /> {{ copiedPair ? 'Copied' : 'Copy pairing data' }}
            </button>
            <details class="pf-details"><summary>What's in this code?</summary>
              <pre class="pf-pre">{{ prettyPair }}</pre>
            </details>
          </div>
        </div>
      </transition>
    </section>

    <!-- ── PUSH DEVICES ─────────────────────────────────────────────── -->
    <section class="pf-card">
      <h2><Icon name="mdi:bell-ring" /> Push devices</h2>
      <p class="pf-muted">
        Get a notification the instant an agent is delegated authority, a capability
        permit is issued or revoked, or (opt-in) a large transfer moves. Uses a
        self-hosted <strong>ntfy</strong> topic — install the ntfy app, subscribe to your
        topic, done.
      </p>

      <div class="pf-newdev">
        <label class="pf-lbl">ntfy topic</label>
        <div class="pf-field-row">
          <input v-model="newTopic" class="pf-input pf-mono" placeholder="ntfy topic" maxlength="64" />
          <button class="pf-btn pf-btn-icon" title="Regenerate topic" @click="newTopic = rollTopic()"><Icon name="mdi:refresh" /></button>
        </div>

        <label class="pf-lbl">Label</label>
        <input v-model="newLabel" class="pf-input" placeholder="e.g. My phone" maxlength="60" />

        <label class="pf-toggle">
          <input type="checkbox" v-model="wantTransfers" />
          <span>Also notify me on transfers ≥</span>
          <!-- §COCKPITDESK (2026-10-15): the frame's own unit (it said AVT on a SBXB frame); empty while unknown, never a wrong
               unit. The amount and its unit wrap together (on a phone the unit fell to a line of its own). -->
          <span class="pf-amt">
            <input v-model.number="transferThreshold" class="pf-input pf-tiny" type="number" min="0" :disabled="!wantTransfers" />
            <span class="pf-muted" data-testid="pf-threshold-unit">{{ localCurrency }}</span>
          </span>
        </label>

        <button class="pf-btn pf-btn-primary pf-btn-block" :disabled="registering" @click="registerDevice">
          <Icon :name="registering ? 'mdi:loading' : 'mdi:bell'" :class="{ 'pf-spin': registering }" /> {{ registering ? 'Registering…' : 'Register device' }}
        </button>
      </div>

      <transition name="pf-fade">
        <div v-if="subscribeHint" class="pf-hint">
          <p><Icon name="mdi:check-circle" /> Registered. Subscribe on your phone:</p>
          <ol>
            <li>Install <strong>ntfy</strong> (App Store / Play / F-Droid).</li>
            <li>Add subscription → topic <code class="pf-mono">{{ subscribeHint }}</code>
              <span v-if="ntfyBase"> on server <code class="pf-mono">{{ ntfyBase }}</code></span>.</li>
          </ol>
          <canvas ref="topicCanvas" class="pf-qr pf-qr-sm" width="180" height="180"></canvas>
        </div>
      </transition>

      <!-- device list -->
      <div v-if="loading" class="pf-devlist">
        <div v-for="n in 2" :key="n" class="pf-dev pf-skel"><span class="pf-skel-ico"></span><span class="pf-skel-line"></span></div>
      </div>
      <ul v-else class="pf-devlist">
        <li v-for="d in devices" :key="d.id" class="pf-dev">
          <Icon :name="d.platform === 'web' ? 'mdi:devices' : 'mdi:cellphone'" class="pf-dev-ico" />
          <div class="pf-dev-body">
            <div class="pf-dev-title">{{ d.label || '(unlabeled)' }} <span class="pf-tag">{{ d.rail }}</span>
              <span v-if="d.paired_key" class="pf-tag" :data-paired="d.paired_key_active ? 'active' : 'revoked'">{{ d.paired_key_active ? 'paired key' : 'key revoked' }}</span></div>
            <div class="pf-mono pf-muted pf-dev-target">{{ d.target }}</div>
          </div>
          <button class="pf-btn pf-btn-icon pf-btn-danger" title="Remove device" @click="askRemove(d)"><Icon name="mdi:trash-can-outline" /></button>
        </li>
        <li v-if="devicesFailed && !devices.length" class="pf-empty">
          <ReadFailedNotice dense text="Your push devices could not be read just now." :retry="load" />
        </li>
        <li v-else-if="!devices.length" class="pf-empty">
          <Icon name="mdi:bell" class="pf-empty-ico" />
          <span>No push devices yet — register one above to get instant alerts.</span>
        </li>
      </ul>
    </section>

    <transition name="pf-fade"><p v-if="err" class="pf-err"><Icon name="mdi:alert-octagon" /> {{ err }}</p></transition>

    <ConfirmActionModal
      :show="!!removeTarget"
      title="Remove push device?"
      :message="removeMessage"
      tone="danger"
      confirmText="Remove device"
      busyText="Removing…"
      :busy="removing"
      @confirm="confirmRemove"
      @close="removeTarget = null"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import QRCode from 'qrcode'
import Icon from '@/components/Icon.vue'
import { useFrames } from '@/composables/useFrames'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { devicePushApi, randomNtfyTopic, type PushDevice } from '@/services/api/devicePush'
import { developerApi } from '@/services/api/developer'
import { appLocale } from '@/services/appLocale'

// ── WEB PUSH: this app's own channel ──────────────────────────────────────────────────────
const wpSupported = typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window
const wpSubscribed = ref(false)
const wpDenied = ref(false)
const wpBusy = ref(false)
const wpMsg = ref('')
const { localCurrency } = useFrames()

// TS 5.7+ types a Uint8Array by its buffer; WebAuthn and Push take a BufferSource, which excludes a buffer that could be
// shared, so these helpers say what they return: a fresh ArrayBuffer-backed array.
function urlB64ToUint8Array(b64: string): Uint8Array<ArrayBuffer> {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)))
}

async function wpRefresh() {
  if (!wpSupported) return
  wpDenied.value = Notification.permission === 'denied'
  try {
    const reg = await navigator.serviceWorker.ready
    wpSubscribed.value = !!(await reg.pushManager.getSubscription())
  } catch { wpSubscribed.value = false }
}

async function wpSubscribe() {
  wpBusy.value = true; wpMsg.value = ''
  try {
    const perm = await Notification.requestPermission()
    if (perm !== 'granted') { wpDenied.value = perm === 'denied'; wpMsg.value = 'Permission was not granted.'; return }
    const { application_server_key } = await devicePushApi.webpushKey()
    if (!application_server_key) { wpMsg.value = 'This registry has no push key configured.'; return }
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(application_server_key),
    })
    await devicePushApi.webpushSubscribe(sub.toJSON() as any, 'This device')
    wpSubscribed.value = true
    wpMsg.value = 'Subscribed. Confirmations now arrive on this device.'
  } catch (e: any) {
    wpMsg.value = e?.message || 'Could not enable notifications.'
  } finally { wpBusy.value = false }
}

async function wpUnsubscribe() {
  wpBusy.value = true
  try {
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    if (sub) { await devicePushApi.webpushUnsubscribe(sub.endpoint).catch(() => {}); await sub.unsubscribe() }
    wpSubscribed.value = false
    wpMsg.value = 'Notifications turned off for this device.'
  } finally { wpBusy.value = false }
}

const devices = ref<PushDevice[]>([])
// §FESUITE (the failing-reads census, 2026-10-04): with the devices' read failed the list said "No push devices yet"
const devicesFailed = ref(false)
const loading = ref(true)
const err = ref('')

// pairing
const pairLabel = ref('')
const pairing = ref(false)
const pairPayload = ref('')
const copiedPair = ref(false)
const pairCanvas = ref<HTMLCanvasElement | null>(null)
const pairExpires = ref('')
// §POCKETPAIR: what a paired phone's key may do, and for how long. SEC-10: 'pocket:device' is the phone's own scope
// (it registers its push device with the key), 'mcp:tools' the MCP tools its assistant drives.
const PAIR_KEY_SCOPES = ['mcp:tools', 'pocket:device']
const PAIR_KEY_DAYS = 90
const prettyPair = computed(() => {
  try { return JSON.stringify(JSON.parse(pairPayload.value), null, 2) } catch { return pairPayload.value }
})

// device registration
const newTopic = ref(randomNtfyTopic())
const newLabel = ref('')
const wantTransfers = ref(false)
const transferThreshold = ref(100)
const registering = ref(false)
const subscribeHint = ref('')
const topicCanvas = ref<HTMLCanvasElement | null>(null)
const ntfyBase = ref((import.meta as any).env?.VITE_NTFY_PUBLIC_URL || '')

// remove modal
const removeTarget = ref<PushDevice | null>(null)
const removing = ref(false)

const rollTopic = () => randomNtfyTopic()
const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))

async function load() {
  loading.value = true
  try {
    // Best-effort: this frame's runtime public ntfy base (from PUSH_NTFY_PUBLIC_URL)
    // overrides the build-time VITE_NTFY_PUBLIC_URL fallback. A failure or empty
    // value leaves the fallback in place — the QR degrades to the bare topic.
    try {
      const cfg = await devicePushApi.getConfig()
      if (cfg?.ntfy_public_url) ntfyBase.value = cfg.ntfy_public_url
    } catch { /* keep build-const fallback */ }
    const { devices: d } = await devicePushApi.listMine()
    devices.value = d
    devicesFailed.value = false
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'Failed to load devices'
    devicesFailed.value = !devices.value.length
  } finally {
    loading.value = false
  }
}

async function pairPhone() {
  err.value = ''; copiedPair.value = false; pairExpires.value = ''
  pairing.value = true
  try {
    // §COCKPITDESK (2026-10-15): the pairing QR never carried a key. This read `key.key` from the legacy
    // /developers/me/apikeys, which answers `plain_api_key` (and drops the name, minting an unlabelled, non-expiring
    // key per press); the phone app (mobile/src/pairing.ts) refuses a payload without an avreg_ key. The canonical rail
    // (/auth/api-keys, FLOW 9) names the key after the device and gives it the server's default expiry.
    const label = pairLabel.value.trim() || 'POCKET FRAME device'
    // §POCKETPAIR (2026-10-15): the phone's key is not a full key. It reaches no admin route and cannot make other keys
    // (both mint rails refuse a key broader than the one asking), and it expires. SEC-10: 'pocket:device' is what lets
    // the phone register its push device with it (an MCP connector's 'mcp:tools' key cannot); removing the phone below
    // revokes the key.
    const created: any = await developerApi.createApiKey(`POCKET FRAME: ${label}`, { scopes: PAIR_KEY_SCOPES, expires_in_days: PAIR_KEY_DAYS })
    const apiKey = created?.plain_api_key
    if (typeof apiKey !== 'string' || !apiKey.startsWith('avreg_')) throw new Error('The registry answered without a key to pair with.')
    const payload = { v: 1, registry_url: window.location.origin, api_key: apiKey, label }
    pairPayload.value = JSON.stringify(payload)
    const exp = created?.api_key_info?.expires_at
    pairExpires.value = exp ? new Date(exp).toLocaleDateString(appLocale(), { year: 'numeric', month: 'short', day: 'numeric' }) : ''
    await nextTick()
    if (pairCanvas.value) await QRCode.toCanvas(pairCanvas.value, pairPayload.value, { width: 240, margin: 1 })
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'Pairing failed'
  } finally {
    pairing.value = false
  }
}

async function registerDevice() {
  err.value = ''
  registering.value = true
  try {
    const prefs: any = {}
    if (wantTransfers.value) prefs.min_transfer_avt = Number(transferThreshold.value) || 0
    await devicePushApi.register({
      platform: 'android', rail: 'ntfy', target: newTopic.value,
      label: newLabel.value || null, prefs: Object.keys(prefs).length ? prefs : null,
    })
    subscribeHint.value = newTopic.value
    await nextTick()
    if (topicCanvas.value) {
      const sub = ntfyBase.value ? `${ntfyBase.value.replace(/\/$/, '')}/${newTopic.value}` : newTopic.value
      await QRCode.toCanvas(topicCanvas.value, sub, { width: 180, margin: 1 })
    }
    newTopic.value = randomNtfyTopic(); newLabel.value = ''
    await load()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'Registration failed'
  } finally {
    registering.value = false
  }
}

function askRemove(d: PushDevice) { removeTarget.value = d; err.value = '' }
const removeMessage = computed(() => {
  const d = removeTarget.value
  if (!d) return ''
  const name = `<strong>${escapeHtml(d.label || d.target)}</strong>`
  // §POCKETPAIR: a paired phone's key goes with it; say so before the press, not after.
  return d.paired_key && d.paired_key_active
    ? `Stop sending notifications to ${name} and revoke the key this phone was paired with? It will need to be paired again.`
    : `Stop sending notifications to ${name}? You can re-register it any time.`
})
async function confirmRemove() {
  if (!removeTarget.value) return
  removing.value = true
  try {
    await devicePushApi.remove(removeTarget.value.id)
    removeTarget.value = null
    await load()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'Remove failed'
  } finally {
    removing.value = false
  }
}

async function copy(text: string, which: 'pair') {
  try { await navigator.clipboard.writeText(text); if (which === 'pair') { copiedPair.value = true; setTimeout(() => (copiedPair.value = false), 1800) } } catch { /* clipboard blocked */ }
}

onMounted(() => { load(); wpRefresh() })   // wpRefresh: reflect this device's real subscription state
</script>

<style scoped>
.pf-wrap { max-width: 720px; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; gap: 1rem; box-sizing: border-box; width: 100%; }
.pf-wrap * { box-sizing: border-box; }
.pf-head { display: flex; gap: 0.8rem; align-items: center; }
.pf-head-badge { width: 2.6rem; height: 2.6rem; border-radius: 12px; display: grid; place-items: center; flex: 0 0 auto;
  background: linear-gradient(135deg, rgba(0,212,255,0.2), rgba(0,212,255,0.05)); border: 1px solid rgba(0,212,255,0.3); }
.pf-head-badge :deep(svg) { width: 1.5rem; height: 1.5rem; color: var(--nc-primary, #00d4ff); }
.pf-head-txt { min-width: 0; }
.pf-head h1 { font-size: 1.35rem; margin: 0; letter-spacing: 0.02em; }
.pf-head p { margin: 0.15rem 0 0; opacity: 0.7; font-size: 0.85rem; }
.pf-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 1.1rem; }
.pf-card h2 { font-size: 1rem; margin: 0 0 0.5rem; display: flex; align-items: center; gap: 0.4rem; }
.pf-card h2 :deep(svg) { width: 1.1rem; height: 1.1rem; color: var(--nc-primary, #00d4ff); }
.pf-muted { opacity: 0.65; font-size: 0.85rem; line-height: 1.45; }
.pf-lbl { display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.55; margin: 0.6rem 0 0.25rem; }
/* a phone puts the button under the field rather than cutting the field's hint to "Device label (e.g. C" */
.pf-field-row { display: flex; gap: 0.5rem; align-items: stretch; flex-wrap: wrap; }
.pf-field-row > .pf-input { flex: 1 1 14rem; }
.pf-input { flex: 1 1 auto; min-width: 0; width: 100%; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 0.6rem 0.75rem; color: inherit; font-size: 0.9rem; transition: border-color 0.15s; }
.pf-input:focus { outline: none; border-color: var(--nc-primary, #00d4ff); }
.pf-tiny { flex: 0 0 76px; width: 76px; text-align: right; }
.pf-mono { font-family: ui-monospace, monospace; }
.pf-toggle { display: flex; align-items: center; gap: 0.45rem; font-size: 0.85rem; margin: 0.7rem 0 0; flex-wrap: wrap; }
.pf-toggle input[type="checkbox"] { accent-color: var(--nc-primary, #00d4ff); }
.pf-btn { display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); border-radius: 10px; padding: 0.6rem 0.9rem; color: inherit; font-size: 0.88rem; cursor: pointer; transition: background 0.15s, border-color 0.15s; white-space: nowrap; }
.pf-btn:hover:not(:disabled) { background: rgba(255,255,255,0.12); }
/* §COCKPITDESK (2026-10-15), the phone camera: "Enable notifications" was disabled (notifications blocked) and looked pressable */
.pf-btn:disabled { opacity: .45; cursor: not-allowed; }
.pf-amt { display: inline-flex; align-items: center; gap: .35rem; white-space: nowrap; }
.pf-btn :deep(svg) { width: 1rem; height: 1rem; }
.pf-btn-primary { background: var(--nc-primary, #00d4ff); color: #05121a; border-color: transparent; font-weight: 600; }
.pf-btn-primary:hover:not(:disabled) { filter: brightness(1.08); background: var(--nc-primary, #00d4ff); }
.pf-btn-wide { flex: 0 0 auto; }
.pf-btn-block { width: 100%; margin-top: 0.7rem; }
.pf-btn-icon { flex: 0 0 auto; padding: 0.6rem; }
.pf-btn-danger { color: #ff6b6b; border-color: rgba(255,107,107,0.3); }
.pf-btn-ok { color: #34d399; border-color: rgba(52,211,153,0.4); }
.pf-btn:disabled { opacity: 0.5; cursor: default; }
.pf-spin { animation: pf-rot 0.9s linear infinite; }
@keyframes pf-rot { to { transform: rotate(360deg); } }
.pf-pair-result { display: flex; gap: 1rem; margin-top: 0.85rem; flex-wrap: wrap; align-items: flex-start; }
.pf-qr { background: #fff; border-radius: 12px; padding: 6px; flex: 0 0 auto; }
.pf-qr-sm { margin-top: 0.6rem; }
.pf-pair-side { flex: 1 1 190px; min-width: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.pf-warn, .pf-err { color: #ffcc66; font-size: 0.85rem; display: flex; align-items: center; gap: 0.4rem; }
.pf-warn :deep(svg), .pf-err :deep(svg) { width: 1rem; height: 1rem; flex: 0 0 auto; }
.pf-err { color: #ff6b6b; }
.pf-details { font-size: 0.8rem; opacity: 0.8; }
.pf-pre { background: rgba(0,0,0,0.4); border-radius: 8px; padding: 0.6rem; overflow-x: auto; font-size: 0.72rem; max-width: 100%; }
.pf-newdev { display: flex; flex-direction: column; margin: 0.5rem 0 0; }
.pf-hint { background: rgba(0,212,255,0.06); border: 1px solid rgba(0,212,255,0.2); border-radius: 12px; padding: 0.85rem; margin: 0.85rem 0; font-size: 0.85rem; }
.pf-hint ol { margin: 0.4rem 0 0; padding-left: 1.2rem; line-height: 1.6; }
.pf-hint code { background: rgba(0,0,0,0.4); padding: 0.1rem 0.35rem; border-radius: 5px; word-break: break-all; }
.pf-devlist { list-style: none; margin: 0.85rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.pf-dev { display: flex; align-items: center; gap: 0.65rem; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05); border-radius: 11px; padding: 0.6rem 0.75rem; }
.pf-dev-ico { width: 1.3rem; height: 1.3rem; opacity: 0.8; flex: 0 0 auto; }
.pf-dev-body { flex: 1 1 auto; min-width: 0; }
.pf-dev-title { font-size: 0.9rem; display: flex; align-items: center; gap: 0.4rem; }
.pf-dev-target { font-size: 0.72rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pf-tag { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.04em; background: rgba(0,212,255,0.14); color: var(--nc-primary, #00d4ff); padding: 0.08rem 0.4rem; border-radius: 5px; }
.pf-empty { display: flex; align-items: center; gap: 0.6rem; padding: 1.1rem 0.5rem; opacity: 0.55; font-size: 0.85rem; justify-content: center; text-align: center; }
.pf-empty-ico { width: 1.4rem; height: 1.4rem; flex: 0 0 auto; }
.pf-skel { pointer-events: none; }
.pf-skel-ico { width: 1.3rem; height: 1.3rem; border-radius: 6px; background: rgba(255,255,255,0.08); flex: 0 0 auto; }
.pf-skel-line { height: 0.8rem; flex: 1 1 auto; border-radius: 5px; background: linear-gradient(90deg, rgba(255,255,255,0.06), rgba(255,255,255,0.13), rgba(255,255,255,0.06)); background-size: 200% 100%; animation: pf-shim 1.3s ease-in-out infinite; }
@keyframes pf-shim { to { background-position: -200% 0; } }
.pf-fade-enter-active, .pf-fade-leave-active { transition: opacity 0.2s ease; }
.pf-fade-enter-from, .pf-fade-leave-to { opacity: 0; }

/* WEB PUSH card */
.pf-webpush .pf-wp-row { display:flex; align-items:center; gap:.75rem; flex-wrap:wrap; margin-top:.6rem; }
.pf-webpush .pf-wp-state { display:flex; align-items:center; gap:.5rem; flex:1; min-width:240px; font-size:.85rem; }
.pf-webpush .pf-ok { color:#34d399; }
.pf-webpush .pf-dim { opacity:.5; }
.pf-webpush .pf-wp-msg { font-size:.78rem; opacity:.75; margin-top:.5rem; }
</style>
