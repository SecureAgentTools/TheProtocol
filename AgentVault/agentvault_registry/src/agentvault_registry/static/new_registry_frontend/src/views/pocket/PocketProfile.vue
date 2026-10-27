<template>
  <!-- §OURSTATE-4 — the public card behind an @handle.

       This exists because the pulse had nowhere to appear. OURSTATE-3a built
       `/handles/{h}` and the QR that points at it, OURSTATE-4 added the pulse
       behind it, and NOTHING in the app ever called either one: a preference
       switch published moments into a surface that did not exist. That is the
       §DISCREFINE class exactly — a door advertised over a blank — so the door
       gets its room. -->
  <div v-if="show" class="pp-wrap" role="dialog" aria-modal="true" :aria-label="titleText">
    <div class="pp-scrim" @click="close" />
    <section class="pp-sheet" ref="sheetEl">
      <header class="pp-head">
        <h2 class="pp-title">{{ titleText }}</h2>
        <button class="pp-x" type="button" :aria-label="t('cta.close', 'Close')" @click="close">
          <Icon name="mdi:close" />
        </button>
      </header>

      <p v-if="loading" class="pp-note">{{ t('ourstate.profile.loading', 'Looking up the handle…') }}</p>
      <p v-else-if="err" class="pp-err" data-testid="pp-err">{{ err }}</p>

      <template v-else-if="profile">
        <!-- THE IDENTITY MANDATE: the whole identity renders wherever a name
             does, through the ONE mount (OurStateIdentity → UserAvatar). -->
        <div class="pp-id">
          <OurStateIdentity ptype="developer" :pid="profile.developer_id"
                            :fallback-name="profile.display_name || profile.handle"
                            size="xl" />
          <div class="pp-idtext">
            <div class="pp-name" data-testid="pp-name">{{ profile.display_name || profile.handle }}</div>
            <div class="pp-handle" data-testid="pp-handle">@{{ profile.handle }}</div>
          </div>
        </div>

        <!-- A private profile is REACHABLE and says so. "No such person" and
             "prefers not to be listed" must never read the same. -->
        <p v-if="profile.visibility !== 'public'" class="pp-note" data-testid="pp-private">
          {{ profile.note || t('ourstate.profile.private',
             'This account is reachable by handle but does not publish a profile.') }}
        </p>

        <template v-else>
          <p v-if="profile.bio" class="pp-bio" data-testid="pp-bio">{{ profile.bio }}</p>
          <div v-if="links.length" class="pp-links">
            <a v-for="l in links" :key="l.href" class="pp-link" :href="safeExternalUrl(l.href)"
               target="_blank" rel="noopener noreferrer">{{ l.label }}</a>
          </div>
        </template>

        <!-- THE PULSE. Three distinct states, never collapsed into each other:
             off (a choice), on-with-nothing (a record), on-with-moments. -->
        <section class="pp-pulse" data-testid="pp-pulse">
          <h3 class="pp-sub">{{ t('ourstate.profile.pulseTitle', 'Pulse') }}</h3>

          <p v-if="pulseLoading" class="pp-note">{{ t('ourstate.profile.pulseLoading', 'Reading the attested record…') }}</p>
          <p v-else-if="pulseErr" class="pp-err">{{ pulseErr }}</p>

          <p v-else-if="!pulse?.enabled" class="pp-note" data-testid="pp-pulse-off">
            {{ pulse?.note || t('ourstate.profile.pulseOff', 'This account does not publish a pulse.') }}
          </p>

          <template v-else>
            <ul v-if="moments.length" class="pp-moments" data-testid="pp-moments">
              <li v-for="(m, i) in moments" :key="i" class="pp-moment">
                <span class="pp-mtext">{{ m.text }}</span>
                <!-- Every moment cites the attested field it came from, so the
                     claim can be checked against the agent's own track record
                     rather than believed. -->
                <span class="pp-msrc">{{ m.source }}</span>
              </li>
            </ul>
            <p v-else class="pp-note" data-testid="pp-pulse-empty">{{ pulse.note }}</p>
            <p v-if="pulse.owner_note" class="pp-owner">{{ pulse.owner_note }}</p>
          </template>
        </section>

        <!-- §OURSTATE-5a — their terms, in the same two registers the room
             Genesis uses: what they SAY, kept apart from what the registry
             ENFORCES. A stranger has to be able to read the price before they
             are asked to pay it. -->
        <section v-if="genesis" class="pp-terms" data-testid="pp-terms">
          <h3 class="pp-sub">{{ t('ourstate.profile.termsTitle', 'Terms') }}</h3>
          <p v-if="genesis.data.stated" class="pp-stated" data-testid="pp-terms-stated">
            {{ genesis.data.stated }}</p>
          <ul class="pp-enforced">
            <li v-for="c in genesis.data.enforced" :key="c.k" class="pp-chip"
                :data-k="c.k">{{ c.label }}</li>
          </ul>
          <p class="pp-fine">{{ t('ourstate.profile.termsFine',
             'Grey lines are enforced by this registry. The sentence above them is theirs.') }}</p>
        </section>

        <p v-if="priced" class="pp-note" data-testid="pp-price-note">
          {{ tp('ourstate.profile.priceNote',
                'A first thread with this person costs {amt} {ccy}, paid to their agent. Replies are free.',
                { amt: contact.price, ccy: contact.currency }) }}
        </p>

        <button class="pp-msg" type="button" data-testid="pp-message"
                :disabled="messaging" @click="message">
          <Icon name="mdi:chat" />
          <span>{{ messaging ? t('ourstate.profile.opening', 'Opening…')
                  : priced ? tp('ourstate.profile.payAndMessage', 'Pay {amt} {ccy} and message',
                               { amt: contact.price, ccy: contact.currency })
                  : t('ourstate.profile.message', 'Message') }}</span>
        </button>

        <!-- The ONE send door (D3), prefilled. The biometric and the confirm
             live there, where every other money moment on this phone lives —
             chat neither moves the money nor re-implements the moment. -->
        <PocketSend v-if="priced" :open="payOpen" mode="send"
                    :ccy="contact.currency || undefined"
                    :initial-to="contact.purse_did || ''"
                    :initial-amount="contact.price || ''"
                    :initial-memo="introMemo"
                    @close="payOpen = false" @sent="onPaid" />
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import PocketSend from '@/views/pocket/PocketSend.vue'
import OurStateIdentity from '@/components/ourstate/OurStateIdentity.vue'
import { chatApi } from '@/services/api/chat'
import { useI18n } from '@/composables/useI18n'
import { safeExternalUrl } from '@/utils/safeUrl'

const props = defineProps<{ show: boolean; handle: string; token: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t, tp } = useI18n()
const router = useRouter()

const loading = ref(false)
const err = ref('')
const profile = ref<any>(null)
const pulseLoading = ref(false)
const pulseErr = ref('')
const pulse = ref<any>(null)
const messaging = ref(false)
const payOpen = ref(false)
const sheetEl = ref<HTMLElement | null>(null)

const titleText = computed(() => props.handle ? `@${props.handle.replace(/^@/, '')}`
                                              : t('ourstate.profile.title', 'Profile'))
const moments = computed<any[]>(() => Array.isArray(pulse.value?.moments) ? pulse.value.moments : [])

/* Their terms travel with the public card (both visibilities — a private
   profile that silently refused a paid intro would be a toll booth with no
   sign). `contact.policy` is the EFFECTIVE one: a declared price that cannot
   be paid is reported as open, because that is what will actually happen. */
const contact = computed<any>(() => profile.value?.contact || {})
const priced = computed(() => contact.value.policy === 'priced'
                              && !!contact.value.purse_did && !!contact.value.price)
const genesis = computed<any>(() => profile.value?.genesis_card || null)
const introMemo = computed(() => `first contact @${String(props.handle).replace(/^@/, '')}`)

const links = computed(() => {
  const p = profile.value || {}
  const out: { label: string; href: string }[] = []
  // §FESUITE 135 (2026-10-15): the registry stores these as typed, so a javascript: "website" became a link that ran in
  // the console's origin for whoever opened the profile; only an http(s) address is a link
  const web = safeExternalUrl(p.website_url)
  const gh = safeExternalUrl(p.github_url)
  if (web) out.push({ label: t('ourstate.profile.website', 'Website'), href: web })
  if (gh) out.push({ label: 'GitHub', href: gh })
  if (p.twitter_handle) out.push({ label: 'X', href: `https://x.com/${String(p.twitter_handle).replace(/^@/, '')}` })
  return out
})

/* Two independent reads: a profile that resolves while the pulse errors must
   still render, and a pulse failure must never be drawn as "publishes nothing"
   — an error is not a preference. */
async function load() {
  const h = String(props.handle || '').replace(/^@/, '')
  if (!h) return
  loading.value = true; err.value = ''; profile.value = null
  pulse.value = null; pulseErr.value = ''
  try {
    profile.value = await chatApi.handleProfile(h)
  } catch (e: any) {
    err.value = e?.detail || e?.message || String(e)
    loading.value = false
    return
  }
  loading.value = false
  pulseLoading.value = true
  try {
    pulse.value = await chatApi.handlePulse(h)
  } catch (e: any) {
    pulseErr.value = e?.detail || e?.message || String(e)
  } finally {
    pulseLoading.value = false
  }
}

/* A priced first contact is two acts in the right order: pay on the money
   rail, THEN open the thread with the proof. The registry re-checks the proof
   at the receiver's ledger, so a client that skips the first act simply
   cannot complete the second. */
async function onPaid(r?: any) {
  payOpen.value = false
  // §OURSTATE-6 widened the `sent` payload from a bare ref to a receipt.
  // Accept both shapes rather than assuming the new one everywhere at once.
  const ref = typeof r === 'string' ? r : r?.ref
  if (!ref) {
    err.value = t('ourstate.profile.noRef',
      'The payment went through but returned no reference, so the thread was not opened. Open it from your activity.')
    return
  }
  await openThread(ref)
}

async function message() {
  if (!props.token || messaging.value) return
  if (priced.value) { payOpen.value = true; return }
  await openThread()
}

async function openThread(introRef?: string) {
  if (!props.token || messaging.value) return
  messaging.value = true
  try {
    const r = await chatApi.createConversation(
      props.token, 'dm', { ptype: 'developer', handle: `@${String(props.handle).replace(/^@/, '')}` } as any,
      undefined, introRef)
    emit('close')
    router.push(`/pocket/ourchat/${r.conversation_id}`).catch(() => {})
  } catch (e: any) {
    err.value = e?.detail || String(e)
  } finally {
    messaging.value = false
  }
}

function close() { emit('close') }

/* `immediate: true` — a sheet mounted with show ALREADY true never fires a
   lazy watcher, which is how three prefill defects shipped this session. */
watch(() => [props.show, props.handle], () => { if (props.show) load() }, { immediate: true })

function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && props.show) close() }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.pp-wrap { position: fixed; inset: 0; z-index: 60; display: flex; align-items: flex-end; }
.pp-scrim { position: absolute; inset: 0; background: rgba(0,0,0,0.55); }
.pp-sheet {
  position: relative; width: 100%; max-height: 88vh; overflow-y: auto;
  background: var(--nc-surface, #11161d); border-top-left-radius: 18px;
  border-top-right-radius: 18px; padding: 1rem 1rem 1.6rem;
  box-shadow: 0 -8px 30px rgba(0,0,0,0.5);
}
.pp-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
/* §FINDFIX — desktop presents this as a centered dialog above the shell chrome
   (sidebar is z-index 10000); the phone bottom sheet below the breakpoint is
   byte-identical. */
@media (min-width: 900px) {
  .pp-wrap { align-items: center; justify-content: center; padding: 32px; z-index: 10500; }
  .pp-sheet { width: min(600px, 100%); max-height: min(80vh, 760px); border-radius: 16px;
              border: 1px solid var(--border-color, rgba(128,128,128,.25));
              box-shadow: 0 24px 64px rgba(0,0,0,.55); }
}
.pp-title { font-size: 1.05rem; font-weight: 700; margin: 0; }
.pp-x { min-width: 44px; min-height: 44px; background: none; border: none; color: inherit; }
.pp-id { display: flex; align-items: center; gap: 12px; margin: 0.8rem 0 0.4rem; }
.pp-name { font-size: 1.1rem; font-weight: 700; }
.pp-handle { opacity: 0.7; font-size: 0.9rem; }
.pp-bio { margin: 0.5rem 0; line-height: 1.45; }
.pp-links { display: flex; flex-wrap: wrap; gap: 10px; margin: 0.4rem 0 0.2rem; }
.pp-link { color: var(--nc-primary, #00d4ff); text-decoration: none; min-height: 44px; display: inline-flex; align-items: center; }
.pp-pulse { margin-top: 1rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.8rem; }
/* §ORGPOCKET polish (2026-08-28) — the agent TERMS block on this sheet had
   markup and no rule that could reach it, so `.pp-enforced` rendered as a
   browser-default bulleted list and every `.pp-chip` as a bullet point. A class
   named "chip" that paints as a bullet is the §ROOMVIEW `.ost-hosting` defect
   in miniature: the markup describes an intent the stylesheet never carried. */
.pp-idtext { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.pp-terms { margin-top: 1rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.8rem; }
.pp-stated { margin: 0 0 0.5rem; line-height: 1.5; }
.pp-enforced { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.pp-chip {
  font-size: 0.72rem; padding: 3px 9px; border-radius: 999px;
  background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
  white-space: nowrap;
}
.pp-fine { font-size: 0.72rem; opacity: 0.6; line-height: 1.5; margin: 0.6rem 0 0; }
.pp-sub { font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.7; margin: 0 0 0.5rem; }
.pp-moments { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.pp-moment { display: flex; flex-direction: column; gap: 2px; }
.pp-mtext { line-height: 1.4; }
.pp-msrc { font-size: 0.72rem; opacity: 0.55; font-variant-numeric: tabular-nums; }
.pp-note { opacity: 0.72; line-height: 1.45; margin: 0.4rem 0; }
.pp-owner { margin-top: 0.6rem; font-style: italic; opacity: 0.8; }
.pp-err { color: var(--nc-danger, #ff6b6b); margin: 0.4rem 0; }
.pp-msg {
  margin-top: 1.1rem; width: 100%; min-height: 48px; border-radius: 12px;
  border: 1px solid var(--nc-primary, #00d4ff); background: transparent;
  color: var(--nc-primary, #00d4ff); font-size: 1rem; font-weight: 600;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
}
.pp-msg[disabled] { opacity: 0.6; }
</style>
