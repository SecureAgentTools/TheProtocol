<!--
  V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): your own chat settings, one component for Pocket's More and the
  console. Moved verbatim from PocketMore.vue (its template, script and styles; the testids unchanged): your handle and
  its QR, blocked, contact terms, pulse and the away stand-in. Until now only Pocket's More reached them, so the
  console's #/ourchat could not (inventory item 13); "Your chat settings" in the thread's menu and the chat list now
  open this.
-->
<template>
  <div class="cys" data-testid="chat-you-settings">
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
const router = useRouter()

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


onMounted(() => {
  void loadAway()
  void loadHandle()
  void loadBlocks()
  void loadTerms()
  void loadAwayAuthority()
  void loadPulse()
})
</script>

<style scoped>
.cys { display: contents; }
.pm-item { display: flex; align-items: center; gap: 0.7rem; width: 100%; text-align: left; background: none; border: none;
  color: inherit; padding: 0.9rem 1rem; font-size: 0.9rem; cursor: pointer; text-decoration: none; min-height: 48px;
  border-bottom: 1px solid rgba(255,255,255,0.05); transition: background 0.15s; -webkit-tap-highlight-color: transparent; }
.pm-group .pm-item:last-child, .pm-group > .pm-item:only-of-type { border-bottom: none; }
.pm-item:active { background: rgba(255,255,255,0.06); }
.pm-item :deep(svg) { width: 1.15rem; height: 1.15rem; color: var(--nc-primary, #00d4ff); flex: 0 0 auto; }
.pm-val { margin-left: auto; font-size: 0.75rem; opacity: 0.55; }
.pm-lang-sel { margin-left: auto; max-width: 55%; min-height: 44px; font-size: 16px; color: inherit;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 0.4rem 0.6rem; }
.pm-chev { margin-left: auto; opacity: 0.4; transition: transform 0.15s; }
.pm-chev.open { transform: rotate(90deg); }
.pm-adv .pm-val { margin-left: auto; }
.pm-adv .pm-chev { margin-left: 0.3rem; }
.pm-emergency .pm-val { color: #ff8a8a; opacity: 0.75; }
.pm-switch { margin-left: auto; width: 42px; height: 24px; border-radius: 12px; background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.15); position: relative; flex: 0 0 auto; transition: background 0.2s, border-color 0.2s; }
.pm-switch.on { background: rgba(0,212,255,0.35); border-color: rgba(0,212,255,0.5); }
.pm-switch.on .pm-knob { transform: translateX(18px); }
.pm-inline-msg { font-size: 0.72rem; opacity: 0.75; margin: 0.1rem 1rem 0.6rem; color: #cfe3ee; }
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
