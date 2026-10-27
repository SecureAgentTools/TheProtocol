<!-- ─────────────────────────────────────────────────────────────────────────────
     ORGANIZATION INVITATION — the page the ACCEPT INVITATION button lands on.
     §ORGJOIN, 2026-08-28.

     Until today it landed on "404 PAGE NOT FOUND — The page you're looking for
     doesn't exist in this dimension", with a RETURN TO MISSION CONTROL button,
     for every invitee in every signed-in state. Measured, all four:
     logged out, signed in as somebody else, signed in as the invited person,
     and on a phone. The route had never existed; `acceptInvitation` had been
     sitting in the store and the service with zero callers since May, and
     `send_invitation_email`'s own docstring said people could "copy the token
     from the email and POST manually" in the meantime.

     THREE THINGS THIS PAGE REFUSES TO DO.
       · It does not accept on arrival. Joining an organization is a decision,
         and a link click is not consent to it — you are shown WHICH
         organization and as WHAT, and then you press the button.
       · It does not guess at identity. "Is this invitation yours?" is answered
         by the server, which holds both addresses; the page never compares a
         masked hint to a local string.
       · It does not tell a stranger who was invited. The address is masked to
         its first letter and domain — enough to answer "am I signed in as the
         wrong person", which is the single most likely real failure, without
         publishing an address to whoever is holding the link.
────────────────────────────────────────────────────────────────────────────── -->
<template>
  <div class="oi-page">
    <div class="oi-card" data-testid="oi-card">
      <div class="oi-head">
        <Icon name="mdi:office-building" class="oi-head-ico" />
        <span class="oi-head-t">{{ t('orgInvite.heading', 'Organization invitation') }}</span>
      </div>

      <div v-if="loading" class="oi-skel" data-testid="oi-loading"></div>

      <!-- ── the link itself did not resolve ─────────────────────────────── -->
      <template v-else-if="loadErr">
        <Icon name="mdi:alert-circle" class="oi-big oi-warn" />
        <p class="oi-lede" data-testid="oi-loaderr">{{ loadErr }}</p>
      </template>

      <!-- ── joined just now ──────────────────────────────────────────────
           FIRST, and deliberately so. Accepting flips the invitation to
           `accepted`, and this page re-reads it because the membership really
           did change — so on the previous ordering the person who had just
           pressed Join was told "This invitation has already been used."
           True, and a cold and confusing thing to say to someone 200ms after
           they joined. Measured: the join worked (members 1 → 2) while the
           success panel never rendered, which is exactly the kind of thing you
           only see by asserting the OUTCOME rather than the absence of an error. -->
      <template v-else-if="joined">
        <Icon name="mdi:check-circle" class="oi-big oi-ok" />
        <p class="oi-lede" data-testid="oi-joined">
          {{ tp('orgInvite.joined', 'You have joined {org}.', { org: joinedOrgName }) }}
        </p>
        <div class="oi-actions">
          <button class="oi-btn oi-btn--primary" data-testid="oi-open-org" @click="goOrg()">
            <Icon name="mdi:open-in-new" /> {{ t('orgInvite.openOrg', 'Open the organization') }}
          </button>
        </div>
      </template>

      <!-- ── spent / unusable invitations, each its own sentence ───────────
           A spent invitation and "you are already in" are the same ROW and two
           different situations. Someone who followed an old link to an
           organization they belong to needs to be told they belong to it, not
           that a token is used up; the token is our bookkeeping, the membership
           is their answer. Whoever is NOT a member still gets the plain fact. -->
      <template v-else-if="!preview?.valid">
        <Icon :name="showsMembership ? 'mdi:check-circle' : stateIcon" class="oi-big"
              :class="{ 'oi-warn': !showsMembership && preview?.status !== 'accepted',
                        'oi-ok': showsMembership }" />
        <p v-if="showsMembership" class="oi-lede" data-testid="oi-already-member">
          {{ tp('orgInvite.alreadyMember', 'You are already a member of {org}.',
                { org: preview?.organization_name || '' }) }}
        </p>
        <p v-else class="oi-lede" :data-testid="'oi-state-' + (preview?.status || 'unknown')">{{ stateSentence }}</p>
        <p v-if="preview?.status === 'unknown'" class="oi-fine">
          {{ t('orgInvite.unknownFine', 'Invitation links are long. If you copied it by hand, check that the whole link came across.') }}
        </p>
        <div class="oi-actions">
          <button v-if="showsMembership && preview?.organization_id" class="oi-btn oi-btn--primary"
                  data-testid="oi-open-org" @click="goOrg()">
            <Icon name="mdi:open-in-new" /> {{ t('orgInvite.openOrg', 'Open the organization') }}
          </button>
        </div>
      </template>

      <!-- ── a live invitation ───────────────────────────────────────────── -->
      <template v-else>
        <p class="oi-invited" data-testid="oi-invited">
          <strong>{{ preview.organization_name || t('orgInvite.anOrg', 'An organization') }}</strong>
          {{ ' ' }}{{ t('orgInvite.invitedYou', 'invited you to join as') }}{{ ' ' }}
          <span class="oi-role" data-testid="oi-role">{{ roleLabel(preview.role) }}</span>
        </p>
        <p v-if="expiresLabel" class="oi-fine" data-testid="oi-expires">{{ expiresLabel }}</p>

        <!-- nobody is signed in: the common arrival -->
        <template v-if="!authed">
          <p class="oi-lede" data-testid="oi-signin-needed">
            {{ t('orgInvite.signInNeeded', 'Sign in to accept this invitation.') }}
          </p>
          <p class="oi-fine">
            {{ tp('orgInvite.useInvitedAddress',
                  'It was sent to {hint} — use that address, or the invitation will not recognise you.',
                  { hint: preview.invited_email_hint || '' }) }}
          </p>
          <div class="oi-actions">
            <button class="oi-btn oi-btn--primary" data-testid="oi-signin" @click="goLogin()">
              {{ t('orgInvite.signIn', 'Sign in') }}
            </button>
            <button class="oi-btn" data-testid="oi-register" @click="goRegister()">
              {{ t('orgInvite.createAccount', 'Create an account') }}
            </button>
          </div>
          <!-- No ?redirect= on register: registration ends on an e-mail
               confirmation panel and does not sign you in, so a redirect would
               be dropped two hops later. Saying "come back to this link" is
               true, and the link is in their inbox. -->
          <p class="oi-fine">
            {{ t('orgInvite.comeBack', 'After creating your account and confirming your email, open this link again from the invitation.') }}
          </p>
        </template>

        <!-- signed in, but as somebody else: the likeliest real failure -->
        <template v-else-if="preview.you_match === false">
          <Icon name="mdi:account-alert" class="oi-big oi-warn" />
          <p class="oi-lede" data-testid="oi-wrong-account">
            {{ tp('orgInvite.wrongAccount',
                  'This invitation was sent to {hint}, and you are signed in as {me}.',
                  { hint: preview.invited_email_hint || '', me: myEmail }) }}
          </p>
          <div class="oi-actions">
            <button class="oi-btn oi-btn--primary" data-testid="oi-switch" @click="switchAccount()">
              <Icon name="mdi:logout" /> {{ t('orgInvite.switchAccount', 'Sign out and switch account') }}
            </button>
          </div>
        </template>

        <!-- already in: not a failure, just already true -->
        <template v-else-if="preview.already_member">
          <Icon name="mdi:check-circle" class="oi-big oi-ok" />
          <p class="oi-lede" data-testid="oi-already-member">
            {{ tp('orgInvite.alreadyMember', 'You are already a member of {org}.',
                  { org: preview.organization_name || '' }) }}
          </p>
          <div class="oi-actions">
            <button class="oi-btn oi-btn--primary" data-testid="oi-open-org" @click="goOrg()">
              <Icon name="mdi:open-in-new" /> {{ t('orgInvite.openOrg', 'Open the organization') }}
            </button>
          </div>
        </template>

        <!-- the decision -->
        <template v-else>
          <div class="oi-actions">
            <button class="oi-btn oi-btn--primary" :disabled="busy" data-testid="oi-accept" @click="accept()">
              <Icon name="mdi:check" />
              {{ busy ? t('orgInvite.joining', 'Joining…')
                      : tp('orgInvite.join', 'Join {org}', { org: preview.organization_name || '' }) }}
            </button>
          </div>
          <!-- The server's own sentence, not a rewrite of it: the accept rail
               distinguishes an expired invitation from a wrong address from a
               full organization, and each of those is something different for
               the person to do next. -->
          <p v-if="acceptErr" class="oi-err" data-testid="oi-accept-err">{{ acceptErr }}</p>
        </template>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { organizationService, type InvitationPreview } from '@/services/api/organizationService'

const { t, tp } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const token = computed(() => String(route.params.token || ''))
const loading = ref(true)
const loadErr = ref('')
const preview = ref<InvitationPreview | null>(null)
const busy = ref(false)
const joined = ref(false)
const acceptErr = ref('')
/* Captured at the moment of joining. The re-read that follows is about the
   membership, and it must not be able to blank the sentence that reports it. */
const joinedOrgName = ref('')
const joinedOrgId = ref('')

const authed = computed(() => !!auth.token)
const myEmail = computed(() => String((auth as any).user?.email || ''))

const roleLabel = (r?: string) => ({
  owner: t('orgInvite.roleOwner', 'an owner'),
  admin: t('orgInvite.roleAdmin', 'an admin'),
  member: t('orgInvite.roleMember', 'a member'),
  guest: t('orgInvite.roleGuest', 'a guest'),
} as Record<string, string>)[String(r || 'member')] || String(r)

/* "You are already a member" replaces the spent-token sentence ONLY for an
   invitation that was actually accepted. An expired or withdrawn link is its own
   fact, and was addressed to somebody else. */
const showsMembership = computed(() =>
  !!preview.value?.already_member && preview.value?.status === 'accepted')

const stateIcon = computed(() =>
  preview.value?.status === 'accepted' ? 'mdi:check-circle'
  : preview.value?.status === 'expired' ? 'mdi:clock-outline'
  : 'mdi:alert-circle')

/* Four different situations, four different sentences. The accept rail collapses
   unknown / accepted / cancelled into one "Invalid or expired invitation", which
   tells a person nothing about what to do next — an invitation someone already
   used and a mistyped link are not the same problem. */
const stateSentence = computed(() => {
  switch (preview.value?.status) {
    case 'accepted':  return t('orgInvite.stAccepted', 'This invitation has already been used.')
    case 'expired':   return t('orgInvite.stExpired', 'This invitation has expired. Ask whoever invited you to send a new one.')
    case 'cancelled': return t('orgInvite.stCancelled', 'This invitation was withdrawn.')
    default:          return t('orgInvite.stUnknown', 'That link is not an invitation we recognise.')
  }
})

const expiresLabel = computed(() => {
  const e = preview.value?.expires_at
  if (!e) return ''
  const d = new Date(e)
  if (Number.isNaN(d.getTime())) return ''
  return tp('orgInvite.expiresOn', 'The invitation is good until {date}.',
            { date: d.toLocaleDateString(appLocale(), { year: 'numeric', month: 'long', day: 'numeric' }) })
})

const selfPath = computed(() => `/organizations/invitations/${token.value}/accept`)
function goLogin() { router.push({ path: '/login', query: { redirect: selfPath.value } }).catch(() => {}) }
function goRegister() { router.push('/register').catch(() => {}) }
async function switchAccount() {
  try { await (auth as any).logout() } catch { /* a failed logout must not strand the page */ }
  goLogin()
}
/* A phone lands in Pocket, a desktop on the dashboard — the same organization,
   the surface each one actually has. */
function goOrg() {
  const narrow = typeof window !== 'undefined' && window.matchMedia?.('(max-width: 899px)')?.matches
  const id = joinedOrgId.value || preview.value?.organization_id || ''
  router.push(narrow ? `/pocket/orgs?org=${id}` : '/organization').catch(() => {})
}

async function load() {
  loading.value = true; loadErr.value = ''
  try {
    preview.value = await organizationService.previewInvitation(token.value)
  } catch {
    // The lookup itself failing is NOT the same as an invalid invitation, and
    // must not be dressed up as one.
    loadErr.value = t('orgInvite.loadErr', 'The invitation could not be read just now. Try the link again in a moment.')
  } finally { loading.value = false }
}

async function accept() {
  if (busy.value) return
  busy.value = true; acceptErr.value = ''
  try {
    joinedOrgName.value = preview.value?.organization_name || ''
    joinedOrgId.value = preview.value?.organization_id || ''
    await organizationService.acceptInvitation(token.value)
    joined.value = true
    await load()          // re-read: membership and status both changed
  } catch (e: any) {
    acceptErr.value = String(e?.message || t('orgInvite.acceptFailed', 'That did not go through.'))
  } finally { busy.value = false }
}

/* 🔴 A SECOND INVITATION LINK IN THE SAME TAB SHOWED THE FIRST ONE'S ANSWER.
   Two invitation URLs differ only in a route PARAM, so vue-router reuses this
   component and `onMounted` never runs again — measured: after a hash-only
   navigation from a spent invitation to an unknown token the page still read
   "This invitation has already been used", and only a full reload told the
   truth. Someone with two invitations in their inbox would have been shown the
   wrong organization, and in the worst ordering a Join button for an invitation
   they were not looking at. */
watch(token, (t, prev) => {
  if (!t || t === prev) return
  joined.value = false
  joinedOrgName.value = ''
  joinedOrgId.value = ''
  acceptErr.value = ''
  void load()
})
onMounted(load)
</script>

<style scoped>
.oi-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 24px 16px; background: var(--nc-bg, #060b14);
}
.oi-card {
  width: 100%; max-width: 460px; padding: 26px 22px 24px; border-radius: 14px;
  background: rgba(13,22,38,0.92); border: 1px solid rgba(var(--nc-primary-rgb),0.14);
  text-align: center; color: var(--nc-text, rgba(226,232,240,0.9));
}
.oi-head { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 18px; }
.oi-head-ico { font-size: 18px; color: rgba(var(--nc-primary-rgb),0.8); }
.oi-head-t {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase; color: rgba(var(--nc-primary-rgb),0.75);
}
.oi-big { font-size: 40px; margin: 10px auto 6px; display: block; color: rgba(var(--nc-primary-rgb),0.75); }
.oi-warn { color: rgba(250,204,21,0.85); }
.oi-ok { color: rgba(74,222,128,0.9); }
.oi-invited { font-size: 1.05rem; line-height: 1.55; margin: 0 0 8px; }
.oi-role { color: rgba(var(--nc-primary-rgb),0.9); font-weight: 600; white-space: nowrap; }
.oi-lede { font-size: 0.92rem; line-height: 1.6; margin: 10px 0 0; }
.oi-fine { font-size: 0.78rem; line-height: 1.6; opacity: 0.68; margin: 10px 0 0; overflow-wrap: anywhere; }
.oi-err { font-size: 0.82rem; line-height: 1.5; margin: 12px 0 0; color: rgba(248,113,113,0.92); }
.oi-actions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-top: 18px; }
.oi-btn {
  display: inline-flex; align-items: center; gap: 7px; cursor: pointer;
  min-height: 44px; padding: 0 18px; border-radius: 10px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.12);
  color: rgba(226,232,240,0.88);
}
.oi-btn--primary {
  background: rgba(var(--nc-primary-rgb),0.14);
  border-color: rgba(var(--nc-primary-rgb),0.38);
  color: rgba(var(--nc-primary-rgb),0.95);
}
.oi-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.oi-skel { height: 92px; border-radius: 10px; background: rgba(255,255,255,0.05); animation: oi-pulse 1.4s ease-in-out infinite; }
@keyframes oi-pulse { 0%,100% { opacity: 0.5 } 50% { opacity: 0.85 } }
@media (prefers-reduced-motion: reduce) { .oi-skel { animation: none } }
@media (max-width: 420px) {
  .oi-card { padding: 20px 16px 18px; }
  .oi-actions { flex-direction: column; }
  .oi-btn { width: 100%; justify-content: center; }
}
</style>
