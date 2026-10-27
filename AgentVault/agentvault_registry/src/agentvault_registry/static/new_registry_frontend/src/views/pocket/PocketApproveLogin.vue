<template>
  <div class="pal-wrap">
    <div class="pal-card">
      <div class="pal-badge"><Icon name="mdi:login-variant" /></div>
      <h1>{{ t('pocket.approveLogin.title', 'Approve sign-in') }}</h1>

      <p v-if="loading" class="pal-sub">{{ t('common.loading', 'Loading…') }}</p>
      <p v-else-if="err" class="pal-err">{{ err }}</p>

      <template v-else-if="detail">
        <p class="pal-sub">{{ t('pocket.approveLogin.sub', 'Someone is signing in to your account. If this is not you, deny it.') }}</p>
        <!-- What is being approved, shown before any fingerprint is asked for. -->
        <ul class="pal-facts">
          <li><span>{{ t('pocket.approveLogin.from', 'From') }}</span><b>{{ detail.requested_ip || t('pocket.approveLogin.unknownAddr', 'unknown address') }}</b></li>
          <li><span>{{ t('pocket.approveLogin.device', 'Device') }}</span><b>{{ shortUa(detail.requested_ua) }}</b></li>
          <li><span>{{ t('pocket.approveLogin.expires', 'Expires') }}</span><b>{{ secondsLeft }}</b></li>
        </ul>
        <div class="pal-actions">
          <button class="pal-btn pal-ok" :disabled="busy || done" @click="approve">
            <Icon name="mdi:fingerprint" /> {{ busy ? t('pocket.shell.verifying', 'Verifying…') : t('pocket.approveLogin.approve', 'Approve with fingerprint') }}
          </button>
          <button class="pal-btn pal-no" :disabled="busy || done" @click="deny">
            <Icon name="mdi:close" /> {{ t('pocket.approveLogin.deny', 'Deny') }}
          </button>
        </div>
        <p v-if="msg" class="pal-msg">{{ msg }}</p>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
// PUSH LOGIN approval screen (phone side). The fingerprint is raised by the OS inside sign();
// there is no path here that approves without it.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { pushLoginApi } from '@/services/api/pushLogin'
import { useDeviceSigner } from '@/composables/useDeviceSigner'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

const route = useRoute()
const signer = useDeviceSigner()
// The request this screen is about, FOLLOWED rather than read once: the next sign-in's notification, tapped while this
// screen still shows the last one, changes only the query (the service worker navigates the open window; vue-router keeps
// the component), and read once, the new request opened on the last one's "Approved" with both buttons disabled
// (§FESUITE lifecycle 84).
const id = ref(String(route.query.id || ''))
const detail = ref<any>(null)
const loading = ref(true)
const busy = ref(false)
const done = ref(false)
const err = ref('')
const msg = ref('')
const now = ref(Date.now())
let timer: any

const secondsLeft = computed(() => {
  if (!detail.value?.expires_at) return '—'
  const ms = new Date(detail.value.expires_at).getTime() - now.value
  return ms <= 0 ? t('pocket.approveLogin.expired', 'expired') : `${Math.ceil(ms / 1000)}s`
})

function shortUa(ua?: string) {
  if (!ua) return t('pocket.approveLogin.unknownDevice', 'unknown')
  const m = ua.match(/(Chrome|Firefox|Safari|Edg)\/[\d.]+/)
  return m ? m[0] : ua.slice(0, 40)
}

async function load() {
  const asked = id.value
  detail.value = null; err.value = ''; msg.value = ''; done.value = false; busy.value = false; loading.value = true
  if (!asked) { err.value = t('pocket.approveLogin.noRef', 'No approval reference.'); loading.value = false; return }
  try {
    // Session-free read: this screen may be opened on a device that is not signed in.
    const ch = await pushLoginApi.challenge(asked)
    if (asked !== id.value) return   // a newer request was opened meanwhile: its own load answers
    detail.value = { challenge_hash: ch.challenge_hash, requested_ip: ch.requested_ip,
                     requested_ua: '', expires_at: ch.expires_at }
  } catch (e: any) {
    if (asked !== id.value) return
    // A 404 here means the request is already approved, denied or expired — that is a FACT to
    // report, not an error to apologise for. Tapping a stale notification used to dump a raw 409.
    err.value = e?.response?.status === 404
      ? t('pocket.approveLogin.gone', 'This sign-in request is no longer waiting — it was already handled or it expired.')
      : (e?.response?.data?.detail || t('pocket.approveLogin.loadFailed', 'Could not load this request.'))
  } finally { if (asked === id.value) loading.value = false }
}

/** The fingerprint was not given: the person declined or cancelled the prompt, or it timed out (the browser says
 *  NotAllowedError for all three), or it was aborted. Their choice, not a fault, and nothing was sent: said in words, not
 *  as the browser's own sentence ("The operation either timed out or was not allowed. See: https://www.w3.org/…") and
 *  not as a console error (§FESUITE lifecycle 84). */
function notConfirmed(e: any): boolean {
  return e?.name === 'NotAllowedError' || e?.name === 'AbortError'
}

async function approve() {
  const asked = id.value
  busy.value = true; msg.value = ''
  try {
    const a = await signer.sign(detail.value.challenge_hash)
    // approve-direct: the assertion IS the authentication, so this works even on a device that
    // is not signed in yet. Errors are surfaced verbatim — silently swallowing a failed approval
    // is what made an approval look successful while the other device waited forever.
    await pushLoginApi.approveDirect(asked, a)
    if (asked !== id.value) return
    done.value = true
    msg.value = t('pocket.approveLogin.approved', 'Approved. You are signed in on the other device.')
  } catch (e: any) {
    if (asked !== id.value) return
    if (notConfirmed(e)) {
      msg.value = t('pocket.approveLogin.notConfirmed', 'Your fingerprint was not confirmed, so nothing was sent. Approve again, or deny.')
    } else {
      msg.value = e?.response?.data?.detail || e?.message || t('pocket.approveLogin.approveFailed', 'Approval failed — nothing was sent.')
      console.error('[approve-login] failed', e)
    }
  } finally { if (asked === id.value) busy.value = false }
}

async function deny() {
  const asked = id.value
  busy.value = true
  try {
    await pushLoginApi.deny(asked)
    if (asked !== id.value) return
    done.value = true; msg.value = t('pocket.approveLogin.denied', 'Sign-in denied.')
  }
  catch (e: any) {
    if (asked !== id.value) return
    // §POCKETBRIDGE2 W1 — a failed DENY that shows nothing is the worst silence
    // on a security surface: the requester may still be let in elsewhere.
    msg.value = tp('pocket.approveLogin.denyFailed', 'Deny FAILED: {err} — the request may still be pending. Retry.',
                   { err: e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed') })
  }
  finally { if (asked === id.value) busy.value = false }
}

watch(() => route.query.id, (q) => {
  const next = String(q || '')
  if (next === id.value) return
  id.value = next
  void load()
})

onMounted(() => { load(); timer = setInterval(() => { now.value = Date.now() }, 1000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.pal-wrap { padding: 1rem; display:flex; justify-content:center; }
.pal-card { width:100%; max-width:420px; border:1px solid var(--pk-border,#334); border-radius:14px; padding:1.25rem; text-align:center; }
.pal-badge { font-size:2rem; color:#34d399; }
.pal-card h1 { font-size:1.25rem; margin:.5rem 0; }
.pal-sub { font-size:.85rem; opacity:.75; }
.pal-err { color:#f87171; font-size:.85rem; }
.pal-facts { list-style:none; padding:0; margin:1rem 0; font-size:.85rem; text-align:left; }
.pal-facts li { display:flex; justify-content:space-between; padding:.3rem 0; border-bottom:1px solid rgba(255,255,255,.06); }
.pal-facts li span { opacity:.6; }
.pal-facts li b { font-family:monospace; }
.pal-actions { display:flex; flex-direction:column; gap:.5rem; margin-top:1rem; }
.pal-btn { display:inline-flex; align-items:center; justify-content:center; gap:.5rem; padding:.7rem 1rem; border-radius:10px; font-weight:600; }
.pal-ok { background:#059669; color:#fff; }
.pal-no { border:1px solid #f87171; color:#f87171; }
.pal-msg { margin-top:.75rem; font-size:.85rem; opacity:.85; }
</style>
