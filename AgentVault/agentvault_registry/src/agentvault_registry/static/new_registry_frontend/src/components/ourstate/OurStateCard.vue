<template>
  <!-- The ONE card renderer — every typed card in every thread comes through
       here, driven by the pure brain (services/chat/cards.ts). Unknown types
       render the honest fallback row; DEFANGED cards (request-state threads)
       render with their doors suppressed and say why. -->
  <div class="osc" :class="`osc-${view.type.replace('.', '-')}`" :data-testid="`osc-${view.type}`">

    <template v-if="view.type === 'pay.request'">
      <div class="osc-head"><Icon name="mdi:cash" /> {{ t('ourstate.card.payRequest', 'Payment request') }}</div>
      <div class="osc-amount">{{ view.amount }} {{ view.currency }}</div>
      <div v-if="view.memo" class="osc-memo">{{ view.memo }}</div>
      <button v-if="!view.defanged && !mine" class="osc-btn" data-testid="osc-pay-door"
              @click="emit('pay', { amount: view.amount, currency: view.currency, memo: view.memo })">
        {{ t('ourstate.card.payNow', 'Pay') }}</button>
      <div v-else-if="view.defanged" class="osc-defanged" data-testid="osc-defanged">
        <Icon name="mdi:shield-key" /> {{ t('ourstate.card.defanged', 'Accept the request to use this card.') }}</div>
    </template>

    <template v-else-if="view.type === 'pay.receipt'">
      <div class="osc-head"><Icon name="mdi:check-circle" /> {{ t('ourstate.card.payReceipt', 'Payment receipt') }}</div>
      <div class="osc-amount">{{ view.amount }} {{ view.currency }}</div>
      <!-- §OURSTATE-6 — on a cross-frame send the arrival is a DIFFERENT unit
           and a smaller number. Both are shown, because the recipient's half is
           the half they care about. -->
      <div v-if="view.receivedAmount" class="osc-arrived" data-testid="osc-arrived">
        {{ tp('ourstate.card.arrived', 'arrived: {amt} {ccy}',
              { amt: view.receivedAmount, ccy: view.receivedCurrency }) }}
      </div>
      <div v-if="view.txId" class="osc-ref">{{ t('ourstate.card.ref', 'ref') }} {{ shorten(view.txId) }}</div>
      <div class="osc-note">{{ t('ourstate.card.receiptNote', 'A claim with a ledger ref — verify against your activity.') }}</div>
      <!-- The honest correction affordance: NOT an undo. The money is gone; a
           transfer on this network is final and rule 10 forbids reaching into
           balances. All anyone can do is ASK, so that is what the button says. -->
      <button v-if="mine && !view.defanged" class="osc-btn osc-ghost" data-testid="osc-askback"
              @click="emit('ask-back', { amount: view.amount, currency: view.currency,
                                         txId: view.txId })">
        {{ t('ourstate.card.askBack', 'Ask them to send it back') }}</button>
    </template>

    <template v-else-if="view.type === 'service.call'">
      <div class="osc-head"><Icon name="mdi:send" /> {{ t('ourstate.card.serviceCall', 'Service call') }}</div>
      <div class="osc-ask">{{ view.ask }}</div>
    </template>

    <template v-else-if="view.type === 'service.result'">
      <div class="osc-head">
        <Icon :name="view.ok ? 'mdi:check-circle' : 'mdi:alert-circle'" />
        {{ view.ok ? t('ourstate.card.delivered', 'Delivered') : t('ourstate.card.notDelivered', 'Not delivered') }}
      </div>
      <div v-if="view.resultText" class="osc-answer" data-testid="osc-answer">{{ view.resultText }}</div>
      <div v-else-if="view.ok" class="osc-answer osc-raw">{{ t('ourstate.card.structuredAnswer', 'Structured answer delivered.') }}</div>
      <div class="osc-receipt" data-testid="osc-receipt">
        <template v-if="view.paidAmount">
          {{ tp('ourstate.card.paidLine', 'Paid {amt} {ccy}', { amt: view.paidAmount, ccy: view.paidCurrency || '' }) }}
          <span class="osc-settle" :class="`s-${effectiveSettlement || 'none'}`">· {{ settleWord }}</span>
        </template>
        <!-- §CHATCOHERE — this branch fires whenever no amount was paid, which
             includes a call that FAILED. "Free call" then reads as "this one was
             free" directly above the refusal explaining that it did not happen.
             A free call and a call that never ran are different facts. -->
        <template v-else-if="!view.ok">{{ t('ourstate.card.nothingCharged', 'Nothing was charged.') }}</template>
        <template v-else>{{ t('ourstate.card.freeCall', 'Free call — nothing charged.') }}</template>
      </div>
      <div v-if="!view.ok" class="osc-honest" data-testid="osc-honest">{{ view.summary }}</div>
      <div v-else-if="effectiveSettlement === 'failed'" class="osc-honest osc-warn" data-testid="osc-honest">{{ view.summary }}</div>
      <div v-if="view.truncated" class="osc-note">{{ t('ourstate.card.truncated', 'Long answer shortened for the thread.') }}</div>

      <!-- §OURSTATE-6 — THE PAYLOAD, BEHIND A TAP. The card is a summary; this
           is what the summary is a summary OF. It is not hidden for tidiness:
           an answer you paid for should be readable in full without leaving the
           thread, and a card that pastes the whole envelope inline is unreadable
           on a phone. Closed by default, and the toggle names how many fields
           are there so the door is not a blank promise. -->
      <template v-if="view.payload">
        <button class="osc-disclose" data-testid="osc-payload-toggle"
                :aria-expanded="payloadOpen ? 'true' : 'false'" @click="payloadOpen = !payloadOpen">
          <Icon :name="payloadOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'" />
          {{ payloadOpen
             ? t('ourstate.card.hidePayload', 'Hide what it returned')
             : tp('ourstate.card.showPayload', 'Show what it returned ({n} fields)',
                  { n: String(Object.keys(view.payload).length) }) }}
        </button>
        <dl v-if="payloadOpen" class="osc-payload" data-testid="osc-payload">
          <template v-for="(val, key) in view.payload" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val) }}</dd>
          </template>
        </dl>
      </template>
    </template>

    <template v-else-if="view.type === 'agent.card'">
      <div class="osc-head"><Icon name="mdi:robot" /> {{ t('ourstate.card.agentCard', 'Agent') }}</div>
      <OurStateIdentity ptype="agent" :pid="view.did" :fallback-name="view.name" size="sm" show-name
                        :clickable="!view.defanged" @open="emit('open-agent', view.did)" />
      <div v-if="view.defanged" class="osc-defanged" data-testid="osc-defanged">
        <Icon name="mdi:shield-key" /> {{ t('ourstate.card.defanged', 'Accept the request to use this card.') }}</div>
    </template>

    <!-- §OURSTATE-2 WORK cards: a POINTER at an engagement that already
         exists on the contracts / guild rails. The door opens that rail; this
         card never accepts, awards or settles anything itself. -->
    <template v-else-if="work">
      <div class="osc-head">
        <Icon :name="work.type === 'guild.order' ? 'mdi:briefcase' : 'mdi:file-document'" />
        {{ work.type === 'guild.order'
          ? t('ourstate.card.guildOrder', 'Guild order')
          : t('ourstate.card.contractOffer', 'Contract') }}
      </div>
      <div class="osc-worktitle" data-testid="osc-work-title">{{ work.title }}</div>
      <div v-if="work.amount && work.currency" class="osc-amount">{{ work.amount }} {{ work.currency }}</div>
      <div class="osc-workref">
        <span v-if="work.status" class="osc-workstatus">{{ work.status }}</span>
        <span class="osc-ref">{{ t('ourstate.card.ref', 'ref') }} {{ work.ref }}</span>
      </div>
      <button v-if="!work.defanged" class="osc-btn" data-testid="osc-work-open"
              @click="emit('open-work', { kind: work.type, ref: work.ref })">
        {{ t('ourstate.card.openWork', 'Open in Work') }}</button>
      <div v-else class="osc-defanged" data-testid="osc-defanged">
        <Icon name="mdi:shield-key" /> {{ t('ourstate.card.defanged', 'Accept the request to use this card.') }}</div>
      <p class="osc-worknote">{{ t('ourstate.card.workNote', 'A pointer. Awarding, delivering and settling happen on the work rail itself.') }}</p>
    </template>

    <!-- §CHATDESK C5 ORG WORK RECEIPT — rail-authored, read-only: the record
         of org money that ALREADY moved on an existing rail. No door on
         purpose — a receipt is history, and history has no buttons. -->
    <template v-else-if="owr">
      <div class="osc-head" data-testid="osc-owr">
        <Icon name="mdi:bank" /> {{ owrKindLabel }}
      </div>
      <div class="osc-amount" data-testid="osc-owr-amount">{{ owr.amount }} {{ owr.currency }}</div>
      <div v-if="owr.memo" class="osc-memo">{{ owr.memo }}</div>
      <div v-if="owr.counterparty" class="osc-certmeta">{{ owr.counterparty }}</div>
      <div v-if="owr.ref" class="osc-ref">{{ t('ourstate.card.ref', 'ref') }} {{ shorten(owr.ref) }}</div>
      <p class="osc-worknote">{{ t('ourstate.card.owrNote', 'Posted by the registry from the ledger — verify against the treasury tab.') }}</p>
    </template>

    <!-- §SHOWCASESTOCKS CERTIFICATE — an Ed25519 attestation that this holding
         exists, minted by the registry on its own read of the cap table. The
         signature is the whole value, so an UNSIGNED one says so loudly rather
         than looking identical to a signed one. -->
    <template v-else-if="cert">
      <div class="osc-head" data-testid="osc-cert">
        <Icon name="mdi:certificate" class="osc-ic" />
        {{ cert.signature ? t('ourstate.card.cert', 'Holding certificate')
                          : t('ourstate.card.certUnsigned', 'Holding certificate: UNSIGNED') }}
      </div>
      <div class="osc-worktitle" data-testid="osc-cert-qty">
        {{ cert.qty }} × ${{ cert.symbol }}
      </div>
      <div v-if="cert.displayName" class="osc-workref"><span class="osc-ref">{{ cert.displayName }}</span></div>
      <div v-if="cert.avgCost" class="osc-amount" data-testid="osc-cert-cost">
        {{ cert.avgCost }} {{ cert.currency }} {{ t('ourstate.card.avgCost', 'average cost') }}
      </div>
      <div class="osc-certmeta" data-testid="osc-cert-id">{{ cert.certificateId }}</div>
      <div class="osc-certmeta">
        {{ cert.venue }}<span v-if="cert.asOf"> · {{ String(cert.asOf).slice(0, 19).replace('T', ' ') }}</span>
      </div>
      <div v-if="cert.signature" class="osc-certsig" data-testid="osc-cert-sig">
        {{ cert.signatureAlg }} · {{ cert.pubkeyId }}
      </div>
      <p class="osc-worknote">
        {{ cert.signature
           ? t('ourstate.card.certNote', 'Signed by this registry and verifiable offline: recompute the digest over the claim and check it against the registry’s published attestation key. It states a holding at a moment — the next trade supersedes it.')
           : (cert.unsignedReason || t('ourstate.card.certNoSig', 'This holding is stated but NOT signed, so it proves nothing on its own.')) }}
      </p>
    </template>

    <!-- §OURCHAT-ORG LISTING — a POINTER at a share listing on the venue. The
         price shown is indicative and says so; the ticket re-reads the book
         before anyone can act, because a price pasted into a conversation is
         stale the moment it is sent. -->
    <template v-else-if="listing">
      <div class="osc-head" data-testid="osc-listing">
        <Icon name="mdi:chart-line" />
        {{ t('ourstate.card.listing', 'Listing') }}
      </div>
      <div class="osc-worktitle" data-testid="osc-listing-sym">${{ listing.symbol }}</div>
      <div v-if="listing.displayName" class="osc-workref">
        <span class="osc-ref">{{ listing.displayName }}</span>
      </div>
      <div v-if="listing.lastPrice && listing.currency" class="osc-amount" data-testid="osc-listing-px">
        {{ listing.lastPrice }} {{ listing.currency }}
      </div>
      <button v-if="!listing.defanged" class="osc-btn" data-testid="osc-listing-open"
              @click="emit('open-trade', { symbol: listing.symbol })">
        {{ t('ourstate.card.openTrade', 'Open in Trade') }}</button>
      <div v-else class="osc-defanged" data-testid="osc-defanged">
        <Icon name="mdi:shield-key" /> {{ t('ourstate.card.defanged', 'Accept the request to use this card.') }}</div>
      <p class="osc-worknote">{{ t('ourstate.card.listingNote', 'A pointer. Any price here is indicative — the ticket reads the live book, and you choose the side and the size there.') }}</p>
    </template>

    <!-- §OURSTATE-5e MEDIA — a pointer, rendered as a pointer. No preview, no
         <img src>: the bytes arrive only through an authenticated fetch the
         viewer asks for, so a card can never make the app load someone's file
         on sight. -->
    <template v-else-if="media">
      <div class="osc-head" data-testid="osc-media">
        <Icon name="mdi:file-document" />
        <span class="osc-media-name">{{ media.name }}</span>
        <span class="osc-media-size">{{ media.human }}</span>
      </div>
      <button v-if="!media.defanged" class="osc-btn" data-testid="osc-media-get"
              :disabled="downloading" @click="download">
        {{ downloading ? t('ourstate.card.mediaGetting', 'Fetching…')
                       : t('ourstate.card.mediaGet', 'Download') }}</button>
      <div v-else class="osc-defanged" data-testid="osc-media-defanged">
        <Icon name="mdi:shield-key" />
        {{ t('ourstate.card.mediaDefanged', 'Accept the request before opening files from a stranger.') }}</div>
      <p v-if="mediaErr" class="osc-worknote" data-testid="osc-media-err">{{ mediaErr }}</p>
    </template>

    <!-- §OURSTATE-5f APPLET — a declarative form. The fields are DATA; the one
         action is a door this app already has, and pressing it OPENS that door
         prefilled. Nothing here fires, and nothing here is markup. -->
    <template v-else-if="applet">
      <div class="osc-head" data-testid="osc-applet">
        <Icon name="mdi:file-text" />
        <span class="osc-applet-title">{{ applet.title }}</span>
      </div>
      <div v-for="f in applet.fields" :key="f.key" class="osc-applet-field">
        <label class="osc-applet-label" :for="`af-${f.key}`">{{ f.label }}</label>
        <select v-if="f.kind === 'choice'" :id="`af-${f.key}`" v-model="appletValues[f.key]"
                class="osc-applet-input" :data-testid="`osc-af-${f.key}`">
          <option v-for="c in f.choices" :key="c" :value="c">{{ c }}</option>
        </select>
        <input v-else-if="f.kind === 'confirm'" :id="`af-${f.key}`" type="checkbox"
               v-model="appletValues[f.key]" :data-testid="`osc-af-${f.key}`" />
        <input v-else :id="`af-${f.key}`" v-model="appletValues[f.key]"
               :type="f.kind === 'number' ? 'number' : 'text'"
               :inputmode="f.kind === 'number' ? 'decimal' : undefined"
               class="osc-applet-input" :data-testid="`osc-af-${f.key}`" />
      </div>
      <button v-if="applet.action.kind && !applet.defanged" class="osc-btn"
              data-testid="osc-applet-go" @click="runApplet">
        {{ applet.action.label || t('ourstate.card.appletOpen', 'Open') }}</button>
      <div v-else-if="applet.defanged" class="osc-defanged" data-testid="osc-applet-defanged">
        <Icon name="mdi:shield-key" /> {{ t('ourstate.card.defanged', 'Accept the request to use this card.') }}</div>
      <p class="osc-worknote">{{ t('ourstate.card.appletNote',
         'This opens a door in the app with these details filled in. Nothing is sent until you confirm it there.') }}</p>
    </template>

    <!-- §DEALTHREADS — proposal / counter: structured NEGOTIATION text. The
         doors FILL (use-terms prefills the engage confirm; counter opens the
         composer); nothing fires from here, and amounts are decoration the
         engage rail re-reads. Defanged in request-state threads like every
         other card (a stranger's terms are readable, not walkable). -->
    <template v-else-if="deal">
      <div class="osc-head" :data-testid="'osc-' + deal.type">
        <Icon name="mdi:briefcase" />
        <span class="osc-deal-kind">{{ deal.type === 'engagement.counter'
          ? t('ourstate.card.dealCounter', 'Counter-terms') : t('ourstate.card.dealProposal', 'Proposed terms') }}</span>
      </div>
      <div class="osc-deal-title">{{ deal.title }}</div>
      <div v-if="deal.total" class="osc-amount">{{ deal.total }} {{ deal.currency }}</div>
      <ul v-if="deal.milestones.length" class="osc-deal-ms">
        <li v-for="(m, i) in deal.milestones" :key="i">{{ m.title }}<span v-if="m.amount"> — {{ m.amount }} {{ deal.currency || '' }}</span></li>
      </ul>
      <p v-if="deal.note" class="osc-deal-note">{{ deal.note }}</p>
      <p v-if="deal.supersedes" class="osc-worknote" data-testid="osc-deal-supersedes">
        {{ t('ourstate.card.dealSupersedes', 'Replaces an earlier set of terms — the thread keeps the whole history.') }}</p>
      <template v-if="!deal.defanged">
        <div class="osc-deal-doors">
          <button class="osc-btn" data-testid="osc-deal-use" @click="emit('use-terms', deal)">
            {{ t('ourstate.card.dealUse', 'Use these terms') }}</button>
          <button class="osc-btn osc-ghost" data-testid="osc-deal-counter" @click="emit('counter-terms', deal)">
            {{ t('ourstate.card.dealCounterBtn', 'Counter') }}</button>
        </div>
        <p class="osc-worknote">{{ t('ourstate.card.dealNote',
          'Terms here are conversation. Money only moves through the offer door, which re-reads everything.') }}</p>
      </template>
      <div v-else class="osc-defanged" data-testid="osc-deal-defanged">
        <Icon name="mdi:shield-key" /> {{ t('ourstate.card.defanged', 'Accept the request to use this card.') }}</div>
    </template>

    <!-- §DEALTHREADS — rail-authored transitions. Doors act on the EXISTING
         contract rails; the rail (not the card) decides who may walk through. -->
    <template v-else-if="dealOffer">
      <div class="osc-head" data-testid="osc-deal-offer">
        <Icon name="mdi:file-document" />
        <span class="osc-deal-kind">{{ t('ourstate.card.dealOffer', 'Contract offer') }}</span>
      </div>
      <div class="osc-deal-title">{{ dealOffer.title }}</div>
      <div class="osc-amount">{{ dealOffer.total }} {{ dealOffer.currency }}</div>
      <p v-if="dealOffer.offerExpiresAt" class="osc-worknote" data-testid="osc-offer-ttl">
        {{ t('ourstate.card.dealTtl', 'Silence lets it expire:') }} {{ fmtWhen(dealOffer.offerExpiresAt) }}</p>
      <template v-if="!dealOffer.defanged">
        <div class="osc-deal-doors">
          <button v-if="!dealOffer.providerHome" class="osc-btn" data-testid="osc-offer-accept"
                  @click="emit('accept-offer', { contractId: dealOffer.contractId, providerDid: dealOffer.providerDid })">
            {{ t('ourstate.card.dealAccept', 'Accept (as the provider)') }}</button>
          <button class="osc-btn osc-ghost" data-testid="osc-offer-view"
                  @click="emit('open-contract', { contractId: dealOffer.contractId })">
            {{ t('ourstate.card.dealView', 'View contract') }}</button>
        </div>
        <p v-if="dealOffer.providerHome" class="osc-worknote">
          {{ t('ourstate.card.dealRemoteAccept', 'The provider accepts from their home registry:') }} {{ dealOffer.providerHome }}</p>
      </template>
    </template>

    <template v-else-if="dealAccepted">
      <div class="osc-head" data-testid="osc-deal-accepted">
        <Icon name="mdi:check-circle" />
        <span class="osc-deal-kind">{{ t('ourstate.card.dealAccepted', 'Offer accepted — escrow held') }}</span>
      </div>
      <div class="osc-amount">{{ dealAccepted.total }} {{ dealAccepted.currency }}</div>
      <button class="osc-btn osc-ghost" data-testid="osc-accepted-view"
              @click="emit('open-contract', { contractId: dealAccepted.contractId })">
        {{ t('ourstate.card.dealView', 'View contract') }}</button>
    </template>

    <template v-else-if="dealMilestone">
      <div class="osc-head" data-testid="osc-deal-milestone">
        <Icon name="mdi:package" />
        <span class="osc-deal-kind">{{ t('ourstate.card.dealDelivered', 'Delivered:') }} {{ dealMilestone.title }}</span>
      </div>
      <button class="osc-btn" data-testid="osc-milestone-review"
              @click="emit('open-contract', { contractId: dealMilestone.contractId })">
        {{ t('ourstate.card.dealReview', 'Review delivery') }}</button>
    </template>

    <template v-else-if="dealSettled">
      <div class="osc-head" data-testid="osc-deal-settled">
        <Icon name="mdi:cash-check" />
        <span class="osc-deal-kind">{{ dealSettled.completed
          ? t('ourstate.card.dealCompleted', 'Contract completed — settled')
          : t('ourstate.card.dealSettledPart', 'Milestone settled') }}</span>
      </div>
      <div class="osc-amount">{{ dealSettled.amount }} {{ dealSettled.currency }}</div>
      <p v-if="dealSettled.providerHome" class="osc-worknote">
        {{ t('ourstate.card.dealSettledHome', 'Paid cross-registry to the provider\'s home:') }} {{ dealSettled.providerHome }}</p>
      <p class="osc-worknote">{{ t('ourstate.card.dealLedger', 'A record of money that already moved on the contract rail.') }}</p>
    </template>

    <template v-else>
      <div class="osc-head osc-unknown" data-testid="osc-unknown">
        <Icon name="mdi:help-circle" />
        {{ tp('ourstate.card.unsupported', 'Unsupported card ({type}) — update the app.', { type: unknownType }) }}
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, reactive, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import apiClient from '@/services/api/client'
import OurStateIdentity from '@/components/ourstate/OurStateIdentity.vue'
import { cardView, type ChatCard } from '@/services/chat/cards'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

const props = withDefaults(defineProps<{
  card: ChatCard | null
  /** True while the viewer's side of the thread is a pending request (§6). */
  defang?: boolean
  /** True when the viewer authored the message (no pay door on your own ask). */
  mine?: boolean
  /** §OURSTATE-6 — the token's LIVE status, when the thread could read it.
   *  Null means "not re-read", never "unsettled": absence is not a verdict. */
  liveSettlement?: string | null
}>(), { defang: false, mine: false, liveSettlement: null })

/** Closed by default: the thread stays scannable, the answer stays reachable. */
const payloadOpen = ref(false)

const emit = defineEmits<{
  (e: 'pay', p: { amount: string; currency: string; memo: string }): void
  (e: 'open-agent', did: string): void
  (e: 'open-work', p: { kind: 'contract.offer' | 'guild.order'; ref: string }): void
  /* §OURCHAT-ORG — the venue door. The card hands up a SYMBOL; the thread
     opens the existing order ticket with it. No side, no quantity, no order. */
  (e: 'open-trade', p: { symbol: string }): void
  /* §OURSTATE-5f — the applet's ONE action, handed up as an intent. The card
     never navigates and never calls a rail itself. */
  /* §OURSTATE-6 — a REQUEST to return a payment, never a reversal. */
  (e: 'ask-back', p: { amount: string; currency: string; txId: string | null }): void
  (e: 'applet-door', p: { kind: string; values: Record<string, any>
                          amount: string | null; currency: string | null
                          did: string | null }): void
  /* §DEALTHREADS — negotiation doors. use-terms prefills the engage confirm;
     counter-terms opens the proposal composer with these terms + supersedes
     supplied by the PARENT (only the parent knows the message id). The
     contract doors open/act on the EXISTING rails — the rail is the gate. */
  (e: 'use-terms', p: { title: string; total: string | null; currency: string | null
                        note: string | null }): void
  (e: 'counter-terms', p: { title: string; total: string | null; currency: string | null
                            note: string | null }): void
  (e: 'open-contract', p: { contractId: string }): void
  (e: 'accept-offer', p: { contractId: string; providerDid: string }): void
}>()

const view = computed(() => cardView(props.card, { defang: props.defang }))

/** The WORK branch, NARROWED here rather than in the template: a `v-else-if`
 *  with an `||` cannot narrow a discriminated union, which is exactly how the
 *  unknown branch lost its `rawType` (the ratchet caught it). */
/** Same reason as `work`: the trailing `v-else` is not a type guard, so the
 *  unsupported branch reads its label through a narrowing computed. */
const unknownType = computed(() => (view.value.type === 'unknown' ? view.value.rawType : 'card'))

/* Same narrowing discipline as `work`: a `v-else-if` cannot narrow a
   discriminated union, so each branch reads through its own computed. */
const media = computed(() => (view.value.type === 'media' ? view.value : null))
const applet = computed(() => (view.value.type === 'applet' ? view.value : null))

/* §DEALTHREADS — each branch narrows through its own computed (house rule). */
const deal = computed(() => (view.value.type === 'engagement.proposal'
  || view.value.type === 'engagement.counter' ? view.value : null))
const dealOffer = computed(() => (view.value.type === 'engagement.offer' ? view.value : null))
const dealAccepted = computed(() => (view.value.type === 'engagement.accepted' ? view.value : null))
const dealMilestone = computed(() => (view.value.type === 'engagement.milestone' ? view.value : null))
const dealSettled = computed(() => (view.value.type === 'engagement.settled' ? view.value : null))

function fmtWhen(iso: string): string {
  try { return new Date(iso).toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}

const appletValues = reactive<Record<string, any>>({})
const downloading = ref(false)
const mediaErr = ref('')

/* The download is an AUTHENTICATED fetch the viewer asked for, turned into a
   blob locally. No <img src>, no link: a card cannot cause a request until a
   human presses this. */
async function download() {
  const m = media.value
  if (!m || downloading.value) return
  downloading.value = true; mediaErr.value = ''
  try {
    const r = await apiClient.get(`/chat/attachments/${m.attachmentId}`, { responseType: 'blob' })
    const url = URL.createObjectURL(r.data as Blob)
    const a = document.createElement('a')
    a.href = url; a.download = m.name
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 4000)
  } catch (e: any) {
    // 410 is a real answer, not a failure: the file was removed.
    mediaErr.value = e?.response?.status === 410
      ? t('ourstate.card.mediaGone', 'This file was removed.')
      : (e?.response?.data?.detail || t('common.error', 'Something went wrong'))
  } finally { downloading.value = false }
}

/* FILL, NEVER FIRE — the same rule the slash composer and the voice grammar
   live under. The applet hands its collected values to the door; the door is
   where a human confirms, with its own biometric where money is involved. */
function runApplet() {
  const a = applet.value?.action
  if (!a?.kind) return
  emit('applet-door', { kind: a.kind, values: { ...appletValues },
                        amount: a.amount, currency: a.currency, did: a.did })
}

const work = computed(() => {
  const v = view.value
  return v.type === 'contract.offer' || v.type === 'guild.order' ? v : null
})

const listing = computed(() => (view.value.type === 'exchange.listing' ? view.value : null))
// §SHOWCASESTOCKS — the signed holding artifact. RAIL-ONLY, so if one of these
// is on screen the REGISTRY minted it.
const cert = computed(() => (view.value.type === 'share.certificate' ? view.value : null))
// §CHATDESK C5 — the firm's money record in the firm's room.
const owr = computed(() => (view.value.type === 'org.work.receipt' ? view.value : null))
const owrKindLabel = computed(() => {
  if (!owr.value) return ''
  switch (owr.value.kind) {
    case 'treasury.fund': return t('ourstate.card.owrFund', 'Treasury funded an agent')
    case 'treasury.remit': return t('ourstate.card.owrRemit', 'Agent remitted to treasury')
    case 'dividend.declared': return t('ourstate.card.owrDividend', 'Distribution declared')
    case 'guild.settled': return t('ourstate.card.owrGuild', 'Firm engagement settled')
    default: return owr.value.kind
  }
})

/* §OURSTATE-6 — A RECEIPT MUST NOT FREEZE MID-FLIGHT.
   `/a2a-payment/settle` answers 200 with status `settling` and moves the money
   in a BACKGROUND task, so the word written into the card is honest at write
   time and STALE a second later. Measured on the Commander's own demo: the
   2 BVT had reached Auditor Ash and the ledger held the transfer row, while the
   card still read "settling" — and would have read it forever, because a card
   is a stored snapshot.
   `stage` is the buy rail's own verdict that the settle leg completed, and the
   result summary ALREADY treats stage=settled as delivered; the displayed word
   must not disagree with the sentence beside it. A live re-read handed down by
   the thread (`liveSettlement`) wins over both — and a FAILED status is never
   upgraded by either, because that is the one word nobody may soften. */
const effectiveSettlement = computed(() => {
  const v: any = view.value
  const stored = v.settlementStatus
  if (stored === 'failed' || stored === 'released') return stored
  if (props.liveSettlement) return props.liveSettlement
  if (v.stage === 'settled' && (stored === 'settling' || !stored)) return 'settled'
  return stored
})

const settleWord = computed(() => {
  const s = effectiveSettlement.value
  if (s === 'settled') return t('ourstate.card.settled', 'settled')
  if (s === 'settling') return t('ourstate.card.settling', 'settling')
  if (s === 'consumed') return t('ourstate.card.unsettled', 'not settled yet')
  if (s === 'released') return t('ourstate.card.released', 'nothing charged')
  if (s === 'failed') return t('ourstate.card.settleFailed', 'NOT PAID')
  return s || ''
})

const shorten = (s: string) => !s ? '' : s.length > 18 ? s.slice(0, 8) + '…' + s.slice(-6) : s
</script>

<style scoped>
.osc { border: 1px solid var(--border-color, rgba(128,128,128,.25)); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; max-width: 100%; }
.osc-head { display: inline-flex; align-items: center; gap: 6px; font-size: .78rem; letter-spacing: .04em; text-transform: uppercase; opacity: .75; }
.osc-amount { font-size: 1.25rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.osc-memo, .osc-ask { font-size: .9rem; }
.osc-answer { white-space: pre-wrap; word-break: break-word; font-size: .95rem; }
.osc-raw { opacity: .8; font-style: italic; }
.osc-receipt { font-size: .8rem; opacity: .85; font-variant-numeric: tabular-nums; }
.osc-honest { font-size: .82rem; }
.osc-warn, .s-failed { color: var(--warning-color, #f59e0b); }
.osc-note, .osc-ref { font-size: .72rem; opacity: .6; }
.osc-defanged { display: inline-flex; align-items: center; gap: 6px; font-size: .78rem; opacity: .7; }
.osc-btn { align-self: flex-start; min-height: 44px; padding: 0 18px; border-radius: 10px; border: none; font-weight: 600; cursor: pointer; background: var(--primary-color, #4fd8c4); color: #06211d; }
.osc-unknown { text-transform: none; letter-spacing: 0; }
/* §CHATPOLISH (2026-08-30) — ten classes below carried MARKUP AND NO RULE
   anywhere in the tree (control-tested reachability scan). The §ROOMVIEW class:
   invisible to every green battery and to a code read, because an unstyled
   element still renders — it just renders as body text. The worst of them is
   the applet: its whole form (field rows, labels, inputs) had no styling at
   all, so a declarative card rendered as native browser controls stacked
   flush inside a themed bubble. */
/* the cross-frame ARRIVAL line (§OURSTATE-6): a different unit and a smaller
   number, and the half the recipient actually cares about — it may not read as
   an afterthought, nor as loud as the amount it qualifies. */
.osc-arrived { font-size: .82rem; opacity: .8; font-variant-numeric: tabular-nums; }
/* "Ask them to send it back" is not the primary act of a receipt: the money is
   already gone. A ghost variant of .osc-btn says so without shouting. */
.osc-ghost { background: none; color: inherit; border: 1px solid var(--border-color, rgba(128,128,128,.35)); font-weight: 500; }
.osc-settle { opacity: .8; }
.osc-ic { flex: none; width: 14px; height: 14px; }
.osc-media-name { font-weight: 600; text-transform: none; letter-spacing: 0; overflow: hidden; text-overflow: ellipsis; }
.osc-media-size { opacity: .6; font-variant-numeric: tabular-nums; text-transform: none; letter-spacing: 0; }
.osc-applet-title { font-weight: 600; text-transform: none; letter-spacing: 0; }
.osc-applet-field { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.osc-applet-label { font-size: .78rem; opacity: .7; min-width: 96px; }
.osc-applet-input { flex: 1; min-width: 0; min-height: 36px; padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit;
  font: inherit; font-size: .88rem; }
.osc-worktitle { font-weight: 700; }
.osc-workref { display: flex; align-items: center; gap: 8px; font-size: .72rem; opacity: .6; flex-wrap: wrap; }
.osc-workstatus { text-transform: uppercase; letter-spacing: .05em; border: 1px solid var(--border-color, rgba(128,128,128,.35)); border-radius: 6px; padding: 0 5px; }
.osc-certmeta { font-family: ui-monospace, monospace; font-size: 10.5px; line-height: 1.5;
  color: var(--nc-text-dim, #8b98a8); word-break: break-all; }
.osc-certsig { font-family: ui-monospace, monospace; font-size: 10.5px; margin-top: 3px;
  color: var(--nc-primary, #4fd1c5); word-break: break-all; }
.osc-worknote { font-size: .68rem; opacity: .5; margin: 0; }
/* §DEALTHREADS — negotiation + transition cards */
.osc-deal-kind { font-weight: 600; }
.osc-deal-title { font-size: .92rem; font-weight: 600; }
.osc-deal-ms { list-style: disc; margin: 2px 0 0; padding-left: 18px; font-size: .78rem; opacity: .75; }
.osc-deal-note { font-size: .8rem; opacity: .7; margin: 4px 0 0; white-space: pre-wrap; }
.osc-deal-doors { display: flex; gap: 8px; flex-wrap: wrap; }
.osc-disclose { display: inline-flex; align-items: center; gap: 4px; min-height: 36px; padding: 0;
  border: none; background: none; color: inherit; opacity: .7; cursor: pointer; font-size: .78rem; text-align: left; }
.osc-payload { margin: 2px 0 0; display: grid; grid-template-columns: minmax(0, auto) minmax(0, 1fr);
  gap: 2px 10px; font-size: .74rem; }
.osc-payload dt { opacity: .6; white-space: nowrap; }
.osc-payload dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
</style>
