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

    <!-- §OURSTATE-5e MEDIA — a pointer, rendered as a pointer. No <img src>:
         the bytes arrive only through an authenticated fetch the viewer asks
         for, so a card can never make the app load someone's file on sight.
         V0652 (ae): a text file's first lines ride on the card, written there
         by its registry from the stored file; markdown is drawn by the chat's
         own renderer (raw HTML is text, the result sanitized), every other
         kind as text. "Open" is that same authenticated fetch, shown here. -->
    <template v-else-if="media">
      <div class="osc-head" data-testid="osc-media">
        <Icon name="mdi:file-document" />
        <span class="osc-media-name">{{ media.name }}</span>
        <span class="osc-media-size">{{ media.human }}</span>
      </div>
      <template v-if="!opened">
        <!-- eslint-disable-next-line vue/no-v-html -- sanitized: renderMarkdown (markdown-it html:false, then DOMPurify) -->
        <div v-if="media.preview && media.previewKind === 'markdown'" class="osc-media-preview osc-media-md"
             data-testid="osc-media-preview" data-kind="markdown" v-html="mediaPreviewHtml" />
        <pre v-else-if="media.preview" class="osc-media-preview osc-media-pre" data-testid="osc-media-preview"
             :data-kind="media.previewKind">{{ media.preview }}</pre>
        <p v-if="media.preview && media.previewTruncated" class="osc-media-note" data-testid="osc-media-more">
          {{ t('ourstate.card.mediaMore', 'The file goes on: open it to read the rest.') }}</p>
      </template>
      <p v-if="media.previewWithheld" class="osc-media-note" data-testid="osc-media-withheld"
         :data-why="media.previewWithheld">
        {{ media.previewWithheld === 'credential'
          ? t('ourstate.card.mediaWithheldCredential', 'No preview: it looks like it holds a credential.')
          : t('ourstate.card.mediaWithheldBinary', 'No preview: this is not a text file.') }}</p>
      <div v-if="opened" class="osc-media-open" data-testid="osc-media-open" :data-kind="opened.kind">
        <p v-if="opened.binary" class="osc-media-note" data-testid="osc-media-nottext">
          {{ t('ourstate.card.mediaNotText', 'This file is not text: download it to open it.') }}</p>
        <!-- eslint-disable-next-line vue/no-v-html -- sanitized: renderMarkdown (markdown-it html:false, then DOMPurify) -->
        <div v-else-if="opened.kind === 'markdown'" class="osc-media-md" v-html="opened.html" />
        <pre v-else class="osc-media-pre">{{ opened.text }}</pre>
        <p v-if="opened.cut" class="osc-media-note" data-testid="osc-media-cut">
          {{ tp('ourstate.card.mediaOpenCut', 'Showing the first {n} characters: download the file for the rest.',
                { n: openMaxLabel }) }}</p>
      </div>
      <div v-if="!media.defanged" class="osc-media-actions">
        <button v-if="media.isText && !media.previewWithheld" class="osc-btn osc-ghost" data-testid="osc-media-open-btn"
                :disabled="opening" :aria-expanded="opened ? 'true' : 'false'" @click="toggleOpen">
          {{ opened ? t('ourstate.card.mediaClose', 'Close')
                    : opening ? t('ourstate.card.mediaOpening', 'Opening…') : t('ourstate.card.mediaOpen', 'Open') }}</button>
        <button class="osc-btn" data-testid="osc-media-get"
                :disabled="downloading" @click="download">
          {{ downloading ? t('ourstate.card.mediaGetting', 'Fetching…')
                         : t('ourstate.card.mediaGet', 'Download') }}</button>
      </div>
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

    <!-- V0650 (l) — approvals in the chat. Both are RAIL records: the request names what is asked and shows its live
         status (a later decision card in the thread, or its expiry); the decision names who decided, in which role,
         and repeats the artifact's sha256. Deciding happens in the panel pinned above the thread, never on a card. -->
    <template v-else-if="approvalRequest">
      <div class="osc-head" data-testid="osc-approval-request">
        <Icon name="mdi:shield-check" />
        <span class="osc-deal-kind">{{ t('ourstate.card.approvalAsks', 'Asks for approval') }}</span>
        <span class="osc-approval-status" :data-status="liveApproval || 'pending'" data-testid="osc-approval-status">
          · {{ approvalStatusWord }}</span>
      </div>
      <div class="osc-worktitle">{{ approvalRequest.title }}</div>
      <div v-if="approvalRequest.unlocks" class="osc-memo">
        {{ tp('ourstate.approvals.unlocks', 'Unlocks: {what}', { what: approvalRequest.unlocks }) }}</div>
      <div v-if="approvalRequest.artifactSha256" class="osc-ref" :title="approvalRequest.artifactSha256">
        sha256 {{ shorten(approvalRequest.artifactSha256) }}</div>
      <p class="osc-worknote">{{ t('ourstate.card.approvalWhere', "Decided in the room's approvals panel.") }}</p>
    </template>

    <template v-else-if="approvalDecided">
      <div class="osc-head" :data-testid="`osc-approval-${approvalDecided.decision}`">
        <Icon :name="approvalDecided.decision === 'approved' ? 'mdi:check-decagram' : 'mdi:close'" />
        <span class="osc-deal-kind">{{ approvalDecided.decision === 'approved'
          ? t('ourstate.card.approvalApproved', 'Approved')
          : t('ourstate.card.approvalDenied', 'Denied') }}</span>
      </div>
      <div class="osc-worktitle">{{ approvalDecided.title }}</div>
      <div class="osc-memo">{{ tp('ourstate.card.approvalBy', 'By {who} ({role})', {
        who: approvalDecided.decidedByName || `#${approvalDecided.decidedById ?? ''}`,
        role: approvalDecided.role === 'owner' ? t('ourstate.card.approvalOwner', 'owner') : t('ourstate.card.approvalApprover', 'approver') }) }}</div>
      <div v-if="approvalDecided.artifactSha256" class="osc-ref" :title="approvalDecided.artifactSha256">
        sha256 {{ shorten(approvalDecided.artifactSha256) }}</div>
      <div v-if="approvalDecided.note" class="osc-memo">{{ approvalDecided.note }}</div>
      <!-- V0652 (aa): the one act it opened, on the card itself (V0651 (o)); used once, it opens nothing else -->
      <div v-if="approvalDecided.used" class="osc-used" data-testid="osc-approval-used"
           :title="approvalDecided.used.actSha256 ? `sha256 ${approvalDecided.used.actSha256}` : ''">
        <Icon name="mdi:check" />
        <span>{{ tp('ourstate.card.approvalUsed', 'Used for {act}, {when}', { act: approvalDecided.used.act,
          when: approvalDecided.used.at ? fmtWhen(approvalDecided.used.at) : '' }) }}</span></div>
    </template>

    <!-- V0652 (aa): a progress card its author keeps current in place: its steps and its verdict, one card instead of
         many messages. A step's state reads by its shape as well as its word. -->
    <template v-else-if="progress">
      <div class="osc-head" :data-testid="`osc-progress-${progress.state}`">
        <Icon :name="PROGRESS_ICON[progress.state]" />
        <span class="osc-deal-kind osc-progress-state" :data-state="progress.state">{{ progressWord }}</span>
        <span v-if="progressTotals && progressTotals.total" class="osc-progress-count" data-testid="osc-progress-count">
          · {{ tp('ourstate.card.progressCount', '{done} of {total} steps', { done: progressTotals.done, total: progressTotals.total }) }}</span>
      </div>
      <div class="osc-worktitle">{{ progress.title }}</div>
      <ol v-if="progress.steps.length" class="osc-steps">
        <li v-for="(st, i) in progress.steps" :key="i" class="osc-step" :data-state="st.state" :data-testid="`osc-step-${i}`">
          <span class="osc-step-mark" aria-hidden="true" />
          <span class="osc-step-label">{{ st.label }}</span>
          <span class="osc-step-word">{{ stepWord(st.state) }}</span>
          <span v-if="st.note" class="osc-step-note">{{ st.note }}</span>
        </li>
      </ol>
      <p v-if="progress.note" class="osc-memo osc-progress-note">{{ progress.note }}</p>
    </template>

    <!-- V0652 (aa): a Guild order in the room its poster named, kept current by the Guild rail (posted, a bid, awarded,
         delivered, settled): the order's record, read from the order itself. -->
    <template v-else-if="guildLive">
      <div class="osc-head" data-testid="osc-guild-live" :data-status="guildLive.status">
        <Icon name="mdi:briefcase" />
        <span class="osc-deal-kind">{{ t('ourstate.card.guildOrder', 'Guild order') }}</span>
        <span class="osc-approval-status osc-guild-status" :data-status="guildLive.status" data-testid="osc-guild-status">
          · {{ guildStatusWord }}</span>
      </div>
      <div class="osc-worktitle">{{ guildLive.title }}</div>
      <div class="osc-memo osc-guild-facts">
        <span v-if="guildLive.bounty" class="osc-guild-bounty">{{ guildLive.bounty }} {{ guildLive.currency }}</span>
        <span v-if="guildLive.posterName">{{ tp('ourstate.card.guildBy', 'posted by {who}', { who: guildLive.posterName }) }}</span>
        <span v-if="guildLive.workerName || guildLive.workerDid" data-testid="osc-guild-worker">{{ tp('ourstate.card.guildTo', 'to {who}', {
          who: guildLive.workerName || shorten(guildLive.workerDid || '') }) }}</span>
        <span>{{ guildLive.bids === 1 ? t('ourstate.card.guildBidOne', '1 bid')
          : tp('ourstate.card.guildBids', '{n} bids', { n: guildLive.bids }) }}</span>
      </div>
      <ol class="osc-stages" :aria-label="t('ourstate.card.guildStages', 'The order so far')">
        <li v-for="st in guildStageList" :key="st.stage" class="osc-stage" :class="{ on: st.reached }"
            :data-testid="`osc-stage-${st.stage}`" :title="st.at ? fmtWhen(st.at) : ''">
          <span class="osc-stage-mark" aria-hidden="true" />
          <span class="osc-stage-label">{{ stageWord(st.stage) }}</span>
        </li>
      </ol>
      <div class="osc-ref">{{ guildLive.orderId }}</div>
      <button v-if="guildLive.orderId" type="button" class="osc-btn osc-btn--quiet" data-testid="osc-guild-open"
              @click="emit('open-work', { kind: 'guild.order', ref: guildLive.orderId })">
        {{ t('ourstate.card.guildOpen', 'Open the order') }}</button>
    </template>

    <!-- V0652 (ab) — a choice: the question and its options (decided in the pinned panel, by one tap on one option),
         then which option was chosen, by whom, or that none was. -->
    <template v-else-if="choiceRequest">
      <div class="osc-head" data-testid="osc-choice-request">
        <Icon name="mdi:format-list-bulleted" />
        <span class="osc-deal-kind">{{ t('ourstate.card.choiceAsks', 'Asks you to choose') }}</span>
        <span class="osc-approval-status" :data-status="liveApproval || 'pending'" data-testid="osc-choice-status">
          · {{ approvalStatusWord }}</span>
      </div>
      <div class="osc-worktitle">{{ choiceRequest.title }}</div>
      <ol class="osc-options" data-testid="osc-choice-options">
        <li v-for="(o, i) in choiceRequest.options" :key="i">{{ o }}</li>
      </ol>
      <p class="osc-worknote">{{ t('ourstate.card.choiceWhere', 'Chosen in the panel pinned above this thread.') }}</p>
    </template>

    <template v-else-if="choiceDecided">
      <div class="osc-head" :data-testid="`osc-choice-${choiceDecided.decision}`">
        <Icon :name="choiceDecided.decision === 'chosen' ? 'mdi:check-decagram' : 'mdi:close'" />
        <span class="osc-deal-kind">{{ choiceDecided.decision === 'chosen' && choiceDecided.chosen
          ? tp('ourstate.card.choiceChose', 'Chose \u201c{label}\u201d', { label: choiceDecided.chosen.label })
          : t('ourstate.card.choiceNone', 'None of the options') }}</span>
      </div>
      <div class="osc-worktitle">{{ choiceDecided.title }}</div>
      <div class="osc-memo">{{ tp('ourstate.card.approvalBy', 'By {who} ({role})', {
        who: choiceDecided.decidedByName || `#${choiceDecided.decidedById ?? ''}`,
        role: choiceDecided.role === 'owner' ? t('ourstate.card.approvalOwner', 'owner') : t('ourstate.card.approvalApprover', 'approver') }) }}</div>
      <div v-if="choiceDecided.note" class="osc-memo">{{ choiceDecided.note }}</div>
    </template>

    <template v-else>
      <div class="osc-head osc-unknown" data-testid="osc-unknown">
        <Icon name="mdi:help-circle" />
        {{ tp('ourstate.card.unsupported', 'Unsupported card ({type}) — update the app.', { type: unknownType }) }}
      </div>
    </template>

    <!-- V0652 (aa): a card that changed in place says so, and its history (who, when, what changed) is one press away -->
    <div v-if="rev > 0" class="osc-live" data-testid="osc-live">
      <span class="osc-live-tx">{{ rev === 1
        ? tp('ourstate.card.updatedOnce', 'Updated once, {when}', { when: updatedWhen })
        : tp('ourstate.card.updatedMany', 'Updated {n} times, last {when}', { n: rev, when: updatedWhen }) }}</span>
      <button type="button" class="osc-live-btn" data-testid="osc-history" @click="emit('history')">
        <Icon name="mdi:history" /> {{ t('ourstate.card.history', 'History') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, reactive, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import apiClient from '@/services/api/client'
import OurStateIdentity from '@/components/ourstate/OurStateIdentity.vue'
import { cardView, type ChatCard } from '@/services/chat/cards'
import { guildStages, stepTotals } from '@/services/chat/liveCards'
import { OPEN_MAX_CHARS, openedFile, previewHtml, type OpenedFile } from '@/services/chat/filePreview'
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
  /** V0650 (l) — an approval request's live status (pending | approved | denied | expired | withdrawn: V0654 (aq)),
   *  read from the thread. */
  liveApproval?: string | null
  /** V0652 (aa): how many times the card was updated in place (0: as posted), and when the last update landed. */
  rev?: number
  updatedAt?: string | null
}>(), { defang: false, mine: false, liveSettlement: null, liveApproval: null, rev: 0, updatedAt: null })

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
  /** V0652 (aa): the card's history was asked for (the thread reads it and shows it) */
  (e: 'history'): void
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
const approvalRequest = computed(() => (view.value.type === 'approval.request' ? view.value : null))
const approvalDecided = computed(() => (view.value.type === 'approval.decided' ? view.value : null))
const choiceRequest = computed(() => (view.value.type === 'choice.request' ? view.value : null))   // V0652 (ab)
const choiceDecided = computed(() => (view.value.type === 'choice.decided' ? view.value : null))
const approvalStatusWord = computed(() => ({
  approved: t('ourstate.card.approvalApproved', 'Approved'),
  chosen: t('ourstate.card.choiceChosen', 'Chosen'),
  denied: t('ourstate.card.approvalDenied', 'Denied'),
  expired: t('ourstate.approvals.expired', 'expired'),
  withdrawn: t('ourstate.card.approvalWithdrawn', 'withdrawn by the agent that asked'),   // V0654 (aq), item 18
} as Record<string, string>)[props.liveApproval || ''] || t('ourstate.card.approvalPending', 'waiting for a decision'))

function fmtWhen(iso: string): string {
  try { return new Date(iso).toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}

/* V0652 (aa): cards that live */
const progress = computed(() => (view.value.type === 'progress' ? view.value : null))
const guildLive = computed(() => (view.value.type === 'guild.order.live' ? view.value : null))
const progressTotals = computed(() => (progress.value ? stepTotals(progress.value.steps) : null))
const PROGRESS_ICON: Record<string, string> = { running: 'mdi:timer-sand', passed: 'mdi:check-circle',
  failed: 'mdi:close-circle', cancelled: 'mdi:cancel' }
const progressWord = computed(() => ({
  running: t('ourstate.card.progressRunning', 'In progress'), passed: t('ourstate.card.progressPassed', 'Passed'),
  failed: t('ourstate.card.progressFailed', 'Failed'), cancelled: t('ourstate.card.progressCancelled', 'Cancelled'),
} as Record<string, string>)[progress.value?.state || 'running'])
function stepWord(state: string): string {
  return ({ pending: t('ourstate.card.stepPending', 'waiting'), running: t('ourstate.card.stepRunning', 'running'),
    done: t('ourstate.card.stepDone', 'done'), failed: t('ourstate.card.stepFailed', 'failed'),
    skipped: t('ourstate.card.stepSkipped', 'skipped') } as Record<string, string>)[state] || state
}
const guildStageList = computed(() => (guildLive.value ? guildStages(guildLive.value.events) : []))
function stageWord(stage: string): string {
  return ({ posted: t('ourstate.card.stagePosted', 'posted'), bid: t('ourstate.card.stageBid', 'bid'),
    awarded: t('ourstate.card.stageAwarded', 'awarded'), submitted: t('ourstate.card.stageDelivered', 'delivered'),
    settled: t('ourstate.card.stageSettled', 'settled') } as Record<string, string>)[stage] || stage
}
const guildStatusWord = computed(() => ({
  open: t('ourstate.card.guildOpenStatus', 'open for bids'), awarded: t('ourstate.card.guildAwarded', 'awarded'),
  submitted: t('ourstate.card.guildDelivered', 'delivered, waiting for the poster'),
  settling: t('ourstate.card.guildSettling', 'settling'), settled: t('ourstate.card.guildSettled', 'settled'),
  disputed: t('ourstate.card.guildDisputed', 'disputed'), resolving: t('ourstate.card.guildResolving', 'resolving'),
  resolved: t('ourstate.card.guildResolved', 'resolved'), cancelled: t('ourstate.card.guildCancelled', 'cancelled'),
  expired: t('ourstate.card.guildExpired', 'expired'),
} as Record<string, string>)[guildLive.value?.status || 'open'] || (guildLive.value?.status ?? ''))
const updatedWhen = computed(() => (props.updatedAt ? fmtWhen(props.updatedAt) : ''))

const appletValues = reactive<Record<string, any>>({})
const downloading = ref(false)
const mediaErr = ref('')

/* V0652 (ae): the preview's HTML (markdown only; '' for the kinds shown as text), and "Open": the same authenticated
   fetch as the download, read as text and shown in the card. */
const mediaPreviewHtml = computed(() => previewHtml(media.value?.preview, media.value?.previewKind))
const opening = ref(false)
const opened = ref<OpenedFile | null>(null)
const openMaxLabel = new Intl.NumberFormat(appLocale()).format(OPEN_MAX_CHARS)
async function toggleOpen() {
  if (opened.value) { opened.value = null; return }
  const m = media.value
  if (!m || opening.value) return
  opening.value = true; mediaErr.value = ''
  try {
    const r = await apiClient.get(`/chat/attachments/${m.attachmentId}`, { responseType: 'arraybuffer' })
    opened.value = openedFile(r.data as ArrayBuffer, m.mime, m.name)
  } catch (e: any) {
    mediaErr.value = e?.response?.status === 410
      ? t('ourstate.card.mediaGone', 'This file was removed.')
      : t('common.error', 'Something went wrong')
  } finally { opening.value = false }
}

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
/* V0652 (ae): a text file's first lines, and the whole file when opened */
.osc-media-preview { margin: 6px 0 0; max-height: 17em; overflow: hidden; }
.osc-media-pre {
  margin: 0; padding: 8px 10px; border-radius: 6px; background: rgba(128, 128, 128, .12);
  font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .76rem; line-height: 1.45;
  white-space: pre-wrap; overflow-wrap: anywhere; text-transform: none; letter-spacing: 0;
}
.osc-media-md { font-size: .86rem; line-height: 1.5; overflow-wrap: anywhere; text-transform: none; letter-spacing: 0; }
.osc-media-md :deep(p) { margin: 0 0 .45em; }
.osc-media-md :deep(ul), .osc-media-md :deep(ol) { margin: .3em 0 .45em; padding-left: 1.3em; }
.osc-media-md :deep(h1), .osc-media-md :deep(h2), .osc-media-md :deep(h3),
.osc-media-md :deep(h4), .osc-media-md :deep(h5), .osc-media-md :deep(h6) { margin: .35em 0 .2em; font-size: 1em; font-weight: 600; }
.osc-media-md :deep(code) { font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: .86em; padding: 0 4px; border-radius: 3px; background: rgba(128, 128, 128, .18); }
.osc-media-md :deep(pre) { margin: .4em 0; padding: 8px 10px; border-radius: 6px; background: rgba(128, 128, 128, .14); overflow-x: auto; }
.osc-media-md :deep(pre code) { padding: 0; background: none; }
.osc-media-md :deep(a) { color: var(--primary-color, #4fd8c4); text-decoration: underline; text-underline-offset: 2px; }
.osc-media-md :deep(blockquote) { margin: .3em 0; padding-left: 10px; border-left: 2px solid rgba(128, 128, 128, .45); }
/* #8b96a5 holds 4.5:1 on the dark card at this size */
.osc-media-note { margin: 4px 0 0; font-size: .74rem; color: #8b96a5; text-transform: none; letter-spacing: 0; }
.osc-media-open { margin-top: 8px; padding-top: 8px; max-height: 60vh; overflow: auto; border-top: 1px solid var(--border-color, rgba(128, 128, 128, .2)); }
.osc-media-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
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
.osc-options { margin: 4px 0 6px; padding-left: 20px; font-size: .9rem; }   /* V0652 (ab) */
/* §DEALTHREADS — negotiation + transition cards */
.osc-deal-kind { font-weight: 600; }
/* V0650 (l): an approval request's live status beside its head */
.osc-approval-status { font-weight: 500; opacity: 0.85; }
.osc-approval-status[data-status='approved'] { color: var(--nc-success, #2fb36d); opacity: 1; }
.osc-approval-status[data-status='denied'], .osc-approval-status[data-status='expired'],
.osc-approval-status[data-status='withdrawn'] { opacity: 0.65; }
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
/* V0652 (aa): cards that live. A step's state reads by its shape (hollow waiting, half running, filled done, a
   diamond failed, a dash skipped) as well as its word; the order's stages are a segmented line, lit as reached. */
.osc-used { display: flex; align-items: flex-start; gap: 6px; font-size: .82rem; color: var(--nc-success, #2fb36d); }
.osc-used :deep(svg) { flex: none; width: 14px; height: 14px; margin-top: 2px; }
.osc-progress-state[data-state='passed'] { color: var(--nc-success, #2fb36d); }
.osc-progress-state[data-state='failed'] { color: var(--warning-color, #f59e0b); }
.osc-progress-count { font-variant-numeric: tabular-nums; text-transform: none; letter-spacing: 0; }
.osc-steps { list-style: none; margin: 2px 0 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
.osc-step { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; column-gap: 8px; align-items: baseline;
  font-size: .86rem; padding: 2px 0; }
.osc-step-mark { width: 9px; height: 9px; box-sizing: border-box; align-self: center; border-radius: 50%;
  border: 1px solid #8b96a5; }
.osc-step[data-state='running'] .osc-step-mark { border-color: var(--nc-primary, #00d2d2);
  background: linear-gradient(90deg, var(--nc-primary, #00d2d2) 50%, transparent 50%); }
.osc-step[data-state='done'] .osc-step-mark { border-color: var(--nc-primary, #00d2d2); background: var(--nc-primary, #00d2d2); }
.osc-step[data-state='failed'] .osc-step-mark { border-radius: 1px; border-color: var(--warning-color, #f59e0b);
  background: var(--warning-color, #f59e0b); transform: rotate(45deg) scale(.85); }
.osc-step[data-state='skipped'] .osc-step-mark { height: 1px; border: 0; border-radius: 0; background: #8b96a5; }
.osc-step-label { min-width: 0; overflow-wrap: anywhere; }
.osc-step-word { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .64rem; letter-spacing: .08em;
  text-transform: uppercase; color: #8b96a5; }
.osc-step[data-state='failed'] .osc-step-word { color: var(--warning-color, #f59e0b); }
.osc-step-note { grid-column: 2 / 4; font-size: .76rem; color: #8b96a5; overflow-wrap: anywhere; }
.osc-progress-note { color: #c4ccd6; }
.osc-guild-facts { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.osc-guild-bounty { font-weight: 600; font-variant-numeric: tabular-nums; }
.osc-guild-status[data-status='settled'] { color: var(--nc-success, #2fb36d); opacity: 1; }
.osc-guild-status[data-status='disputed'] { color: var(--warning-color, #f59e0b); opacity: 1; }
.osc-stages { list-style: none; margin: 4px 0 0; padding: 0; display: flex; gap: 3px; }
.osc-stage { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.osc-stage-mark { height: 2px; background: rgba(128, 128, 128, .28); }
.osc-stage.on .osc-stage-mark { background: var(--nc-primary, #00d2d2); }
.osc-stage-label { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .58rem; letter-spacing: .1em;
  text-transform: uppercase; color: #6b7685; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.osc-stage.on .osc-stage-label { color: #c4ccd6; }
.osc-btn--quiet { background: none; color: var(--nc-primary, #00d2d2); border: 1px solid var(--nc-border-strong, #343a4d); }
.osc-live { display: flex; align-items: center; gap: 10px; margin-top: 2px; padding-top: 6px;
  border-top: 1px solid var(--nc-border-subtle, rgba(128, 128, 128, .14)); }
.osc-live-tx { flex: 1; min-width: 0; font-size: .72rem; color: #8b96a5; }
.osc-live-btn { display: inline-flex; align-items: center; gap: 4px; min-height: 34px; padding: 0 10px; border-radius: 8px;
  border: 1px solid var(--nc-border-strong, #343a4d); background: none; color: inherit; font-size: .74rem; cursor: pointer; }
.osc-live-btn :deep(svg) { width: 13px; height: 13px; }
@media (pointer: coarse) { .osc-live-btn { min-height: 44px; } }
</style>
