<template>
  <BaseModal
    v-model:show="show"
    :title="agent?.name || agentName || 'Agent Details'"
    size="xl"
  >
    <!-- Loading -->
    <div v-if="loadingDetails" class="flex justify-center items-center h-48">
      <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-cyan-500"></div>
    </div>

    <!-- Error State -->
    <div v-else-if="loadError" class="text-center py-12">
      <div class="text-red-400 text-4xl mb-3"><Icon name="mdi:alert" /></div>
      <p class="text-gray-400 text-sm">{{ loadError }}</p>
    </div>

    <!-- Embedded / anonymous (landing globe): no authed fetch — invite to sign in. §pass78c ① -->
    <!-- §EMBEDGATE (2026-09-08, his word: "it routes to this older modal to when we didnt had
         public explore … just make the correct modal pop up there").
         THE SIGN-IN TEASER THAT USED TO LIVE HERE IS GONE. It was `v-else-if="embedded"` — keyed
         on the SURFACE, not on the viewer: the landing page's globe passes `embedded`, so every
         click there got "Sign in to open the full agent card" whether or not anyone was signed in.
         That was true when it was written; §DISCPUBLIC made the whole card public at /explore, and
         the teaser became a wall in front of an open door.
         The honest gate is the STATE, and it is already applied where it belongs: the engage door
         renders `adm-engage-signin` for a viewer with no session, and the owner-tier reads are not
         issued at all. Gating by naming a surface closes the instance and leaves the class — the
         next public surface inherits the same wall. -->
    <!-- Agent Details — §pass18 polished hero + bands -->
    <div v-else-if="agent" class="adm-body">

      <!-- ─── Hero band ─── -->
      <div class="adm-hero">
        <div class="adm-hero-decor" aria-hidden="true"></div>
        <div class="adm-hero-content">
          <!-- §AGENTDISC #190 — ledger-earned ring; compact arrives via the panel's state emit -->
          <!-- §MARKCOLLAR-2 — the hero avatar was size="lg" (48px), which is the
               size the Commander called "too small and almost invisible" for the
               mark. This is the agent's detail view: the one place there is room
               to show the record properly. xl (96px). -->
          <EarnedMarkRing :tr="admTrCompact" size="xl">
            <UserAvatar
              :user="agentUserShape"
              :avatar-url="agentAvatarUrl(agent)"
              :display-name="agent.name"
              size="xl"
              class="adm-hero-avatar"
            />
          </EarnedMarkRing>
          <div class="adm-hero-info">
            <div class="adm-hero-pills">
              <span v-if="agent.developerVerified" class="adm-pill adm-pill--verified">
                <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                  <path d="M2 6 L5 9 L10 3" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"/>
                </svg>
                Verified
              </span>
              <span class="adm-pill" :class="agent.status === 'active' ? 'adm-pill--active' : 'adm-pill--idle'">
                <span class="adm-pill-dot" :class="{ 'adm-pill-dot--pulse': agent.status === 'active' }"></span>
                {{ agent.status === 'active' ? 'Active' : 'Inactive' }}
              </span>
              <span v-if="agent.isFederated && agent.originRegistry" class="adm-pill adm-pill--federated" :title="`Synced from ${agent.originRegistry}`">
                <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                  <polygon points="6,1 11,4 11,8 6,11 1,8 1,4" fill="none" stroke="currentColor" stroke-width="1.2"/>
                </svg>
                {{ agent.originRegistry }}
              </span>
              <span v-else class="adm-pill adm-pill--local">
                <span class="adm-pill-glyph">◈</span> Local
              </span>
              <span v-if="agentCcy" class="adm-pill" :class="agentIsForeign ? 'adm-pill--ccy-foreign' : 'adm-pill--ccy-local'"
                    :title="agentIsForeign ? `Settles in ${agentCcy} — foreign currency to your registry` : `Settles in ${agentCcy}`">
                <span class="adm-pill-glyph">{{ describeCurrency(agentCcy).glyph }}</span> {{ agentCcy }}
              </span>
            </div>

            <h2 class="adm-hero-name">{{ agent.name }}</h2>

            <div class="adm-hero-hri">
              <code>{{ agent.humanReadableId }}</code>
              <button @click="copyToClipboard(agent.humanReadableId, 'hri')" class="adm-icon-btn" title="Copy identifier" :aria-label="'Copy identifier ' + agent.humanReadableId">
                <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
                  <rect x="3" y="3" width="8" height="8" rx="1.5" stroke="currentColor" stroke-width="1.4" fill="none"/>
                  <path d="M3 6 L3 4.5 A1.5 1.5 0 0 1 4.5 3 L6 3" stroke="currentColor" stroke-width="1.4" fill="none"/>
                </svg>
              </button>
              <span v-if="copyToast === 'hri'" class="adm-copy-toast">copied ✓</span>
            </div>

            <p v-if="agent.description" class="adm-hero-desc">{{ agent.description }}</p>

            <div class="adm-hero-meta">
              <span v-if="agent.provider?.name" class="adm-meta-item">
                <svg viewBox="0 0 14 14" width="11" height="11" aria-hidden="true">
                  <path d="M2 11 L2 5 L7 2 L12 5 L12 11 Z M5 11 L5 8 L9 8 L9 11" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linejoin="round"/>
                </svg>
                {{ agent.provider.name }}
              </span>
              <span v-if="agent.version" class="adm-meta-item">
                <span class="adm-meta-key">v</span>{{ agent.version }}
              </span>
              <span v-if="agent.type !== 'custom'" class="adm-meta-item">
                <span class="adm-meta-key">{{ capitalize(agent.type) }}</span>
              </span>
              <span class="adm-meta-item adm-meta-item--mono">
                <svg viewBox="0 0 14 14" width="11" height="11" aria-hidden="true">
                  <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.2" fill="none"/>
                  <path d="M7 3.5 L7 7 L9.5 8.5" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round"/>
                </svg>
                {{ formatDate(agent.createdAt) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- ─── Pricing band — A2A flow explainer ─── -->
      <div v-if="agent.pricing" class="adm-pricing adm-pricing--paid">
        <div class="adm-pricing-left">
          <span class="adm-pricing-label">Service Pricing</span>
          <div class="adm-pricing-amount">
            <span class="adm-pricing-num">{{ agent.pricing.base_rate }}</span>
            <span class="adm-pricing-unit">{{ currencyForItem(agent) }}</span>
            <span class="adm-pricing-per">per request</span>
          </div>
        </div>
        <div class="adm-pricing-flow">
          <span class="adm-flow-step"><span class="adm-flow-num">1</span> Quote</span>
          <svg viewBox="0 0 10 10" width="8" height="8" aria-hidden="true"><path d="M2 5 L8 5 M5.5 2 L8 5 L5.5 8" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="adm-flow-step"><span class="adm-flow-num">2</span> Authorize</span>
          <svg viewBox="0 0 10 10" width="8" height="8" aria-hidden="true"><path d="M2 5 L8 5 M5.5 2 L8 5 L5.5 8" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span class="adm-flow-step"><span class="adm-flow-num">3</span> Settle</span>
        </div>
        <span class="adm-pricing-badge">Payment Required</span>
        <!-- B8: cross-currency settlement indicator -->
        <span v-if="agentIsForeign && hostFx === 'on'" class="adm-pricing-fx-note" title="This agent settles in a different currency — your registry has FX enabled, so payments auto-convert.">⇄ pays via FX · {{ agentCcy }}</span>
        <span v-else-if="fxLocked" class="adm-pricing-fx-note adm-pricing-fx-note--locked" :title="fxHireHint">⇄ {{ agentCcy }} · enable FX on your registry to pay</span>
        <span v-else-if="agentIsForeign && hostFx === 'unread'" class="adm-pricing-fx-note" data-testid="adm-fx-unread">⇄ {{ agentCcy }} · {{ t('agentModal.fxUnread', 'whether your registry pays across currencies could not be checked just now') }}
          <button type="button" class="adm-fx-retry" data-testid="adm-fx-retry" @click="loadHostFx()">{{ t('common.readFailed.retry', 'Try again') }}</button></span>
      </div>
      <div v-else class="adm-pricing adm-pricing--free">
        <span class="adm-pricing-free-tag">
          <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
            <path d="M2 6 L5 9 L10 3" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round"/>
          </svg>
          Free Agent
        </span>
        <!-- §DISCREFINE: this used to read "No payment required for A2A calls —
             anyone can call this endpoint without holding X". That is a claim
             about how the ENDPOINT behaves, which a card cannot support, and it
             was live-wrong for SYBIL (5.0 AVT, priced through the A2A payment
             extension we did not read). Both dialects are read now, so absence
             is a much stronger signal — but the honest sentence still describes
             the CARD, not the endpoint. -->
        <span v-if="ownCredential" class="adm-pricing-free-note" data-testid="adm-free-own-auth">{{ t('agentModal.freeOwnAuth', 'This card declares no charge through the network: nothing to authorize or settle here. The agent asks for a credential of its own before it answers (Authentication, below).') }}</span>
        <span v-else class="adm-pricing-free-note">This card declares no charge for A2A calls. Nothing to authorize or settle before calling it.</span>
      </div>

      <!-- ─── §FLARESHOP (2026-08-16) — HOW YOU ENGAGE THIS AGENT ──────────────
           Three ways to hire, stated once, in order of weight. The direct A2A
           call is the lightest and the oldest (it is how the service agents
           have always worked) but it used to live as a tertiary ghost button in
           the footer, below Close, while Guild and Contract sat mid-modal — so
           the cheapest path looked like the afterthought. It is the same
           handlers (`hireAgent` / `callFree`), just no longer buried: no second
           hiring flow was built for this.
           Guild and Contract CTAs stay where they are, inside the proven-work
           panel, because they are about scoped, escrowed, disputable work. -->
      <div class="adm-engage" data-testid="adm-engage">
        <div class="adm-engage-head">
          <span class="adm-section-label">{{ t('agentModal.engage.title', 'Engage directly') }}</span>
          <span v-if="agent.pricing" class="adm-engage-price" data-testid="adm-engage-price">
            {{ agent.pricing.base_rate }} {{ currencyForItem(agent) }}<span class="adm-engage-per">/req</span>
          </span>
          <span v-else class="adm-engage-price adm-engage-price--free" data-testid="adm-engage-price">
            {{ t('agentModal.engage.free', 'no charge') }}
          </span>
        </div>
        <p class="adm-engage-sub">
          {{ agent.pricing
            ? t('agentModal.engage.subPaid', 'One A2A call, paid per request through authorize and settle. No contract to draft and no escrow to release: the payment authorization IS the agreement.')
            : t('agentModal.engage.subFree', 'One A2A call against the endpoint above. Nothing to draft, nothing to escrow, no bond held on either side.') }}
        </p>
        <div class="adm-engage-actions">
          <!-- §DISCPUBLIC (2026-09-06) — a visitor with no session can READ this card in full; what they cannot
               do is act on it. An engage button that opens a login is a lie about what the button does, so the
               door says what it is. Reading stays public; acting needs an account. -->
          <a v-if="!hasSession" class="adm-engage-btn adm-engage-btn--signin" href="#/login" data-testid="adm-engage-signin">
            {{ t('agentModal.engage.signIn', 'Sign in to engage') }}
          </a>
          <button v-else-if="agent.pricing && fxUnsure" class="adm-engage-btn adm-engage-btn--locked" type="button" disabled data-testid="adm-engage-go">
            {{ hostFx === 'reading' ? t('agentModal.engage.fxChecking', 'Cross-currency · checking FX…') : t('agentModal.engage.fxUnread', 'Cross-currency · FX could not be checked') }}
          </button>
          <button v-else-if="agent.pricing && !fxLocked" @click="hireAgent" class="adm-engage-btn" type="button" data-testid="adm-engage-go">
            {{ agentIsForeign ? t('agentModal.engage.goFx', 'Engage · pay via FX') : t('agentModal.engage.go', 'Engage this agent') }}
          </button>
          <button v-else-if="agent.pricing && fxLocked" class="adm-engage-btn adm-engage-btn--locked" type="button" disabled :title="fxHireHint" data-testid="adm-engage-go">
            {{ t('agentModal.engage.fxLocked', 'Cross-currency · enable FX to pay') }}
          </button>
          <button v-else @click="callFree" class="adm-engage-btn" type="button" data-testid="adm-engage-go">
            {{ t('agentModal.engage.call', 'Call this agent') }}
          </button>
          <a v-if="resolvedDid" :href="`/api/v1/agents/${encodeURIComponent(resolvedDid)}/card-export`"
             target="_blank" rel="noopener" class="adm-engage-card" data-testid="adm-a2a-card">
            {{ t('agentModal.engage.card', 'Standard A2A v1.0 card, signed') }} ↗
          </a>
        </div>
        <!-- §HIRECOHERE (2026-08-28) — the OTHER two doors, here rather than inside the
             proven-work section. That section is `v-show="admTrackRecordHas"`, so every
             hire CTA was invisible for the 14,236 of 14,260 frame-c agents with no verified
             work — a door behind an auto-hiding panel is a blank promise (§DISCREFINE).
             Receipts depend on history; hiring does not. One shared preview decides. -->
        <div class="adm-doors" data-testid="adm-doors">
          <!-- §DISCPUBLIC — a visitor gets ONE call to action, and it is the honest one. The Guild
               door pushes to /guild, which asks for a sign-in a click later; offering it beside
               "Sign in to engage" promises two ways in where there is one. -->
          <button v-if="hasSession" class="adm-door" data-testid="adm-door-guild" type="button" @click="hireViaGuild">
            {{ t('agentModal.doors.guild', 'Post a job for this agent · Guild') }}
          </button>
          <button v-if="engDoors?.contract.available" class="adm-door adm-door--contract"
                  data-testid="adm-door-contract" type="button" @click="offerOpen = true">
            {{ t('agentModal.doors.contract', 'Offer a contract · escrowed') }}
          </button>
          <p v-else-if="engDoors?.contract.reason" class="adm-door-shut" data-testid="adm-door-shut">
            {{ engDoors.contract.reason }}
          </p>
        </div>
        <!-- An offer is a commitment, so it is shown before it is sent. The terms are the
             card's own, rendered server-side by the preview — the button used to fire the
             engage rail on one click with nothing on screen about what was being offered. -->
        <div v-if="offerOpen && engDraft" class="adm-offer" data-testid="adm-offer">
          <p class="adm-offer-title">{{ engDraft.title }}</p>
          <p class="adm-offer-line" data-testid="adm-offer-terms">
            {{ engDraft.total_amount }} {{ engDraft.currency }} · {{ engDraft.contract_type }}
          </p>
          <!-- §DEALTHREADS — the thread is a CHOICE like the offer itself (default
               unticked, Commander's call): ticked, the offer opens/reuses the
               client↔provider DM and posts the offer card into it. -->
          <label class="adm-offer-thread" data-testid="adm-offer-thread">
            <input v-model="offerOpenThread" type="checkbox" />
            <span>{{ t('agentModal.doors.offerThread', 'Discuss in OurChat (opens a deal thread with the offer card)') }}</span>
          </label>
          <div class="adm-offer-actions">
            <button class="adm-door" type="button" @click="offerOpen = false">
              {{ t('agentModal.doors.offerCancel', 'Cancel') }}
            </button>
            <button class="adm-door adm-door--contract" type="button" data-testid="adm-offer-send"
                    :disabled="offerBusy" @click="offerContract">
              {{ offerBusy ? t('agentModal.doors.offerSending', 'Sending…')
                           : t('agentModal.doors.offerSend', 'Send offer') }}
            </button>
          </div>
        </div>
        <!-- §BUYSERVICE — the actual purchase, in place. Mounted only on demand so
             a modal that is merely being read makes no quote call. -->
        <BuyServicePanel v-if="showBuy && resolvedDid" :did="resolvedDid" :agent-name="agent.name" />
      </div>

      <!-- ─── §AGENTDISC #188 — proven work (registry-attested, auto-hides at zero) ─── -->
      <div v-if="resolvedDid" v-show="admTrackRecordHas" class="adm-section" data-testid="adm-track-record">
        <span class="adm-section-label">{{ t('trackRecord.sectionTitle', 'Proven work') }}</span>
        <!-- §DISCPUBLIC — `show-ctas` is what makes this panel ask engage-preview (its own
             useEngageDoors call, the SECOND site — gating only the modal's left one still fired
             it, measured on the anonymous drive). A visitor has no doors here either. -->
        <TrackRecordPanel :did="resolvedDid" :auto-hide="!focusRecord" :max-rows="5" :show-ctas="hasSession" :agent-name="agent?.name || ''"
                          @state="admTrackRecordHas = $event.hasHistory; admTrCompact = $event.compact" />
      </div>

      <!-- ─── API endpoint with curl reveal ───────────────────────────────────────────
           §CARDLINK (2026-09-08). His report: *"the link on the registry cards are wrong …
           dont provide a link for them that is dead."* This block printed the card's address
           and a ready-to-paste curl for it unconditionally, so an address that answers 404
           was presented exactly like one that works — and thirty of them did answer 404.
           An endpoint is now shown WITH THE REGISTRY'S LAST WORD ON IT, and the curl (the
           part that says "call this") is only offered when the address actually answered.
           ⚠ THREE STATES. `null` is never-probed-here — a federated mirror legitimately never
           is — and it must read as "not checked", never as either of the other two. -->
      <div v-if="cardEndpoints.length" class="adm-section">
        <div class="adm-section-head">
          <span class="adm-section-label">API Endpoint</span>
          <!-- The state is said in ALL THREE cases, not only the bad one. Before this, a dead
               endpoint got a badge and a sentence while a working one got silence, so "no news"
               and "no address" looked identical on screen — my own §DISCMIX rule, broken by me,
               and exactly what he asked about ("where are the links for the reachable ones").
               His call on the wording: a dot for reachable, no timestamp. -->
          <span class="adm-ep-state" :class="`adm-ep-state--${endpointState}`"
                data-testid="adm-endpoint-state">
            <span class="adm-ep-dot" aria-hidden="true"></span>
            {{ endpointState === 'reachable'
                ? t('agentModal.endpoint.reachable', 'answered when last checked')
                : endpointState === 'dead'
                  ? t('agentModal.endpoint.dead', 'did not answer when last checked')
                  : t('agentModal.endpoint.unknown', 'not checked from this registry') }}
          </span>
          <button v-if="endpointState === 'reachable'" @click="showCurl = !showCurl" class="adm-section-toggle" type="button">
            <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true" :style="{ transform: showCurl ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.16s ease' }">
              <path d="M4 2 L8 6 L4 10" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            {{ showCurl ? 'Hide' : 'Show' }} curl example
          </button>
        </div>
        <div class="adm-endpoint" :class="{ 'adm-endpoint--dead': endpointState === 'dead' }">
          <code class="adm-endpoint-url" data-testid="adm-endpoint-url">{{ cardEndpoints[0].url }}</code>
          <span v-if="cardEndpoints[0].protocolBinding" class="adm-ep-binding">{{ cardEndpoints[0].protocolBinding }}</span>
          <button @click="copyToClipboard(cardEndpoints[0].url, 'url')" class="adm-endpoint-copy" type="button">
            <span v-if="copyToast === 'url'">copied ✓</span>
            <span v-else>copy</span>
          </button>
        </div>
        <!-- An agent may publish several (Hagrid publishes four). The agent's own order decides
             which is primary; the rest open on demand rather than filling the body with four
             addresses a reader did not ask for. -->
        <details v-if="cardEndpoints.length > 1" class="adm-ep-more" data-testid="adm-endpoint-more">
          <summary class="adm-ep-more-summary">
            {{ tp('agentModal.endpoint.more', '{n} more on this agent', { n: cardEndpoints.length - 1 }) }}
          </summary>
          <div class="adm-endpoint" v-for="ep in cardEndpoints.slice(1)" :key="ep.url">
            <code class="adm-endpoint-url">{{ ep.url }}</code>
            <span v-if="ep.protocolBinding" class="adm-ep-binding">{{ ep.protocolBinding }}</span>
            <button @click="copyToClipboard(ep.url, ep.url)" class="adm-endpoint-copy" type="button">
              <span v-if="copyToast === ep.url">copied ✓</span>
              <span v-else>copy</span>
            </button>
          </div>
        </details>
        <p v-if="endpointState === 'dead'" class="adm-ep-note" data-testid="adm-endpoint-note">
          {{ t('agentModal.endpoint.deadNote',
                'This registry dialled this address and nothing answered there. It is shown so you can see what the card claims, it is not a working call.') }}
          <span v-if="endpointCheckedLabel"> ({{ endpointCheckedLabel }})</span>
        </p>
        <Transition name="adm-reveal">
          <pre v-if="showCurl && endpointState === 'reachable'" class="adm-curl">{{ curlExample }}<button @click="copyToClipboard(curlExample, 'curl')" class="adm-curl-copy" type="button">
              <span v-if="copyToast === 'curl'">copied ✓</span>
              <span v-else>copy</span>
            </button></pre>
        </Transition>
      </div>

      <!-- ─── Metadata grid (compact) ─── -->
      <div class="adm-meta-grid">
        <div class="adm-meta-cell">
          <span class="adm-meta-cell-label">Created</span>
          <span class="adm-meta-cell-value">{{ formatDate(agent.createdAt) }}</span>
        </div>
        <!-- §FLARESHOP: only cells that ADD something. A card written once has
             updatedAt == createdAt, and the hero line already carries the agent
             version — repeating both filled a quarter of the modal with the
             same two facts under different labels. -->
        <div v-if="showUpdatedCell" class="adm-meta-cell">
          <span class="adm-meta-cell-label">Updated</span>
          <span class="adm-meta-cell-value">{{ formatDate(agent.updatedAt) }}</span>
        </div>
        <div v-if="agent.schemaVersion" class="adm-meta-cell">
          <span class="adm-meta-cell-label">Card schema</span>
          <span class="adm-meta-cell-value">{{ agent.schemaVersion }}</span>
        </div>
      </div>

      <!-- ─── TEG Balance (if available) — §pass18-aligned band ─── -->
      <div v-if="tegBalance !== null" class="adm-balance">
        <div class="adm-balance-cell">
          <span class="adm-balance-label">Liquid Balance</span>
          <span class="adm-balance-amount">{{ tegBalance.liquid.toFixed(2) }} <span class="adm-balance-ccy">{{ currencyForItem(agent) }}</span></span>
        </div>
        <div v-if="tegBalance.staked > 0" class="adm-balance-cell adm-balance-cell--staked">
          <span class="adm-balance-label">Locked</span>
          <span class="adm-balance-amount adm-balance-amount--staked">{{ tegBalance.staked.toFixed(2) }} <span class="adm-balance-ccy">{{ currencyForItem(agent) }}</span></span>
        </div>
      </div>

      <!-- ─── Tags ─── -->
      <div v-if="agent.tags && agent.tags.length > 0" class="adm-section">
        <span class="adm-section-label">Tags</span>
        <div class="adm-tags">
          <span v-for="tag in agent.tags" :key="tag"
                @click="$emit('filter-by-tag', tag)"
                class="adm-tag">#{{ tag }}</span>
        </div>
      </div>

      <!-- ─── Capabilities — icon grid (§pass18) ─── -->
      <div v-if="enabledCapabilities.length > 0" class="adm-section">
        <span class="adm-section-label">Capabilities</span>
        <div class="adm-cap-grid">
          <div v-for="cap in enabledCapabilities" :key="cap.key" class="adm-cap-chip">
            <span class="adm-cap-icon" v-html="cap.icon"></span>
            <span class="adm-cap-label">{{ cap.label }}</span>
          </div>
        </div>
      </div>

      <!-- ─── Skills — §pass18-aligned. §FLARESHOP: `informativeSkills`, not
           `skills` — an SDK-generated card commonly declares ONE skill whose
           name and description are the agent's own, so this box rendered the
           hero again, verbatim, under a different heading. A section that
           repeats what is three lines above is worse than no section. ─── -->
      <div v-if="informativeSkills.length > 0" class="adm-section" data-testid="adm-skills">
        <span class="adm-section-label">Skills</span>
        <div class="adm-skill-list">
          <div v-for="(skill, idx) in informativeSkills" :key="idx" class="adm-skill">
            <div class="adm-skill-head">
              <span class="adm-skill-name">{{ skill.name || skill.id || `Skill ${idx + 1}` }}</span>
              <code v-if="skill.uri" class="adm-skill-uri" :title="skill.uri">{{ skill.uri }}</code>
            </div>
            <p v-if="skill.description" class="adm-skill-desc">{{ skill.description }}</p>
            <div v-if="skill.inputModes?.length || skill.outputModes?.length" class="adm-skill-modes">
              <span v-if="skill.inputModes?.length"><span class="adm-skill-mode-key">in</span> {{ skill.inputModes.join(', ') }}</span>
              <span v-if="skill.outputModes?.length"><span class="adm-skill-mode-key">out</span> {{ skill.outputModes.join(', ') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ─── Authentication Schemes — §pass18-aligned.
           §FLARESHOP: this rendered the literal token "none" under a heading,
           which reads like a missing value rather than the fact it is: the
           endpoint takes no credential. Every scheme now says what a caller
           has to bring. ─── -->
      <div v-if="agent.authSchemes && agent.authSchemes.length > 0" class="adm-section" data-testid="adm-auth">
        <span class="adm-section-label">Authentication</span>
        <div class="adm-iface-list">
          <div v-for="(scheme, idx) in agent.authSchemes" :key="idx" class="adm-auth-row">
            <svg class="adm-auth-icon" viewBox="0 0 14 14" width="13" height="13" aria-hidden="true">
              <rect x="3" y="6.5" width="8" height="5.5" rx="1" stroke="currentColor" stroke-width="1.3" fill="none"/>
              <path d="M4.6 6.5 V4.8 a2.4 2.4 0 0 1 4.8 0 V6.5" stroke="currentColor" stroke-width="1.3" fill="none"/>
            </svg>
            <span class="adm-auth-label">{{ authSchemeLabel(scheme) }}</span>
            <span class="adm-auth-note">{{ authSchemeNote(scheme) }}</span>
            <span v-if="scheme.description" class="adm-auth-desc" data-testid="adm-auth-desc">{{ scheme.description }}</span>
          </div>
        </div>
      </div>

      <!-- ─── Legal Links — §pass18-aligned ─── -->
      <!-- §COCKPITDESK (2026-10-15) SECURITY: these two come from the agent's own card, which any developer writes; a
           javascript: or data: URL ran in this console's origin for whoever pressed the link. http(s) only. -->
      <div v-if="safeExternalUrl(agent.termsOfServiceUrl) || safeExternalUrl(agent.privacyPolicyUrl)" class="adm-legal">
        <a v-if="safeExternalUrl(agent.termsOfServiceUrl)" :href="safeExternalUrl(agent.termsOfServiceUrl)" target="_blank" rel="noopener noreferrer" class="adm-legal-link">Terms of Service →</a>
        <a v-if="safeExternalUrl(agent.privacyPolicyUrl)" :href="safeExternalUrl(agent.privacyPolicyUrl)" target="_blank" rel="noopener noreferrer" class="adm-legal-link">Privacy Policy →</a>
      </div>

      <!-- ─── §pass34: DID (always shown with copy button) ─── -->
      <div v-if="resolvedDid" class="adm-section">
        <div class="adm-section-head">
          <span class="adm-section-label">DID</span>
        </div>
        <div class="adm-endpoint">
          <code class="adm-endpoint-url">{{ resolvedDid }}</code>
          <button @click="copyToClipboard(resolvedDid, 'did')" class="adm-endpoint-copy" type="button">
            <span v-if="copyToast === 'did'">copied ✓</span>
            <span v-else>copy</span>
          </button>
        </div>
      </div>

      <!-- ─── §pass34: Federation Info (origin + relay chain + location) ─── -->
      <div v-if="federationInfo" class="adm-section adm-fed-section">
        <div class="adm-section-head">
          <span class="adm-section-label">Federation</span>
          <span v-if="federationInfo.isLocal" class="adm-fed-badge adm-fed-badge--local">◈ Native here</span>
          <span v-else class="adm-fed-badge adm-fed-badge--relayed">↻ Synced</span>
        </div>
        <div class="adm-meta-grid">
          <div v-if="federationInfo.originRegistryName" class="adm-meta-cell">
            <span class="adm-meta-cell-label">Origin Registry</span>
            <span class="adm-meta-cell-value">{{ federationInfo.originRegistryName }}</span>
          </div>
          <div v-if="federationInfo.lastSyncedFromShort" class="adm-meta-cell">
            <span class="adm-meta-cell-label">Most Recent Hop</span>
            <span class="adm-meta-cell-value" :title="federationInfo.lastSyncedFrom">{{ federationInfo.lastSyncedFromShort }}</span>
          </div>
          <div v-if="federationInfo.firstSyncedFromShort && federationInfo.firstSyncedFromShort !== federationInfo.lastSyncedFromShort" class="adm-meta-cell">
            <span class="adm-meta-cell-label">First Hop</span>
            <span class="adm-meta-cell-value" :title="federationInfo.firstSyncedFrom">{{ federationInfo.firstSyncedFromShort }}</span>
          </div>
          <div v-if="federationInfo.lastSyncTimestamp" class="adm-meta-cell">
            <span class="adm-meta-cell-label">Last Synced</span>
            <span class="adm-meta-cell-value">{{ formatDate(federationInfo.lastSyncTimestamp) }}</span>
          </div>
          <div v-if="federationInfo.protocolVersion" class="adm-meta-cell">
            <span class="adm-meta-cell-label">A2A Protocol</span>
            <span class="adm-meta-cell-value">v{{ federationInfo.protocolVersion }}</span>
          </div>
          <div v-if="federationInfo.mtlsEnabled !== undefined" class="adm-meta-cell">
            <span class="adm-meta-cell-label">mTLS</span>
            <span class="adm-meta-cell-value">{{ federationInfo.mtlsEnabled ? '✓ enrolled' : '—' }}</span>
          </div>
        </div>
        <!-- §LOCTRUTH — say WHOSE location this is. An agent has no address; its origin REGISTRY does,
             and this value is `federation_metadata.origin_registry_location`. A bare pin under an agent's
             name reads as "the agent is here", which is a claim the card never made. -->
        <div v-if="federationInfo.originLocation" class="adm-fed-location">
          <svg viewBox="0 0 14 14" width="11" height="11" aria-hidden="true">
            <path d="M7 1 C4 1 2 3.2 2 6 C2 9 7 13 7 13 C7 13 12 9 12 6 C12 3.2 10 1 7 1 Z M7 4.5 A1.5 1.5 0 1 0 7 7.5 A1.5 1.5 0 1 0 7 4.5 Z" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linejoin="round"/>
          </svg>
          <span class="adm-fed-location-label">{{ t('agentModal.originRegistryLocation', 'Origin registry') }}</span>
          <span>{{ federationInfo.originLocation }}</span>
        </div>
        <div v-if="federationInfo.spiffeId" class="adm-fed-spiffe">
          <span class="adm-meta-cell-label">SPIFFE</span>
          <code class="adm-mono-small">{{ federationInfo.spiffeId }}</code>
        </div>
      </div>

      <!-- ─── §pass34: Supported Interfaces ─── -->
      <!-- §MODALPASS3 — the machine facts fold away. Supported interfaces, security schemes, the raw
           card_data dump and the "Other Fields" JSON blob are what a developer integrating against this
           agent needs; they are not what a visitor deciding whether to hire it reads, and on a page meant
           for a public showcase they were the last thing on screen. The human-facing modal now ends at
           Federation and this opens on demand. Nothing is removed — a card's own words stay one click
           away, which is the difference between refining and hiding. -->
      <details class="adm-tech" data-testid="adm-tech">
        <summary class="adm-tech-summary">{{ t('agentModal.technical', 'Technical details') }}</summary>
        <div v-if="supportedInterfaces.length > 0" class="adm-section">
          <div class="adm-section-head">
            <span class="adm-section-label">Supported Interfaces</span>
          </div>
          <div class="adm-iface-list">
            <div v-for="(iface, idx) in supportedInterfaces" :key="idx" class="adm-iface-row">
              <span class="adm-iface-proto">{{ iface.protocolBinding || iface.protocol || '?' }}</span>
              <code v-if="iface.url" class="adm-iface-url">{{ iface.url }}</code>
              <span v-if="iface.protocolVersion" class="adm-iface-ver">v{{ iface.protocolVersion }}</span>
            </div>
          </div>
        </div>

        <!-- ─── §pass34: Security Schemes (structured) ─── -->
        <div v-if="securitySchemesList.length > 0" class="adm-section">
          <div class="adm-section-head">
            <span class="adm-section-label">Security Schemes</span>
          </div>
          <div class="adm-iface-list">
            <div v-for="scheme in securitySchemesList" :key="scheme.name" class="adm-iface-row">
              <span class="adm-iface-proto">{{ scheme.name }}</span>
              <span class="adm-iface-ver">{{ scheme.type }}</span>
              <code v-if="scheme.tokenUrl" class="adm-iface-url" :title="scheme.tokenUrl">{{ scheme.tokenUrl }}</code>
            </div>
          </div>
        </div>

        <!-- ─── §pass34: Misc card_data fields not shown above ─── -->
        <div v-if="miscFields.length > 0" class="adm-section">
          <div class="adm-section-head">
            <span class="adm-section-label">Other Fields</span>
          </div>
          <div class="adm-meta-grid">
            <div v-for="f in miscFields" :key="f.key" class="adm-meta-cell">
              <span class="adm-meta-cell-label">{{ f.label }}</span>
              <span class="adm-meta-cell-value">{{ f.value }}</span>
            </div>
          </div>
        </div>

        <!-- ─── Raw Card Data (Expandable) — §pass18-aligned ─── -->
        <div class="adm-section">
          <button @click="showRawData = !showRawData" class="adm-section-toggle adm-rawdata-toggle" type="button">
            <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true" :style="{ transform: showRawData ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.16s ease' }">
              <path d="M4 2 L8 6 L4 10" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            {{ showRawData ? 'Hide' : 'Show' }} Raw Card Data
          </button>
          <Transition name="adm-reveal">
            <pre v-if="showRawData" class="adm-rawdata">{{ JSON.stringify(agent.rawCardData, null, 2) }}</pre>
          </Transition>
        </div>
      </details>
    </div>
    <!-- §EMBEDGATE-3 (2026-09-08, his report: "i clicked it it doesnt open. shows modal but empty
         with close button"). THE FOURTH STATE. The three branches above are loading / error /
         agent, and with no DID to fetch NONE of them is true — so the modal rendered a shell with
         a close button and nothing else. That is the worst answer available: it cannot be told
         apart from a broken rail. The CAUSE is fixed (the globe passes its DID now); this is the
         floor under it, because a surface that can reach an unnamed state will reach it again.
         ⚠ It must be the ADJACENT sibling of the `v-else-if` above — appended at the end of the
         template instead, Vue answers "v-else has no adjacent v-if", and the type checker does not
         see it: only the BUILD does. -->
    <div v-else class="adm-empty" data-testid="adm-empty">
      <p class="adm-empty-h">{{ agentName || t('agentModal.empty.noAgent', 'No agent selected') }}</p>
      <p class="adm-empty-sub">{{ t('agentModal.empty.sub', 'This card could not be identified — nothing was requested for it. Close this and pick an agent again; if it keeps happening the link is carrying no agent id.') }}</p>
    </div>

    <!-- Footer — §pass18: context-aware primary CTA -->
    <template #footer>
      <div class="adm-footer">
        <div class="adm-footer-meta">
          <span v-if="agent && agent.reputation_score && agent.reputation_score > 0" class="adm-footer-rep">
            <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
              <path d="M6 1 L7.5 4.5 L11 5 L8.5 7.5 L9 11 L6 9.2 L3 11 L3.5 7.5 L1 5 L4.5 4.5 Z" fill="currentColor" opacity="0.85"/>
            </svg>
            <span>Trust {{ agent.reputation_score.toFixed(0) }}/100</span>
          </span>
        </div>
        <div class="adm-footer-actions">
          <a v-if="fullAgentHref" :href="fullAgentHref" class="adm-btn adm-btn--ghost"
             data-record="open" data-record-kind="agent"
             :title="t('agentModal.openFull', 'Open the full agent view')">
            <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
              <path d="M5.5 2.5 H11.5 V8.5" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M11.5 2.5 L6.5 7.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
              <path d="M9 11.5 H2.5 V5" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            {{ t('agentModal.openFullShort', 'Full view') }}
          </a>
          <button v-if="agent" @click="openProtocolTheater" class="adm-btn adm-btn--ghost" type="button">
            <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
              <rect x="2" y="3" width="10" height="7" rx="1.5" stroke="currentColor" stroke-width="1.4" fill="none"/>
              <path d="M5 12 L9 12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
              <path d="M6 6 L8.5 7.5 L6 9 Z" fill="currentColor"/>
            </svg>
            View in Theater
          </button>
          <button v-if="agent" @click="showRegistryCard = true" class="adm-btn adm-btn--ghost" type="button"
                  :title="'View the registry card of ' + (agent.isFederated && agent.originRegistry ? agent.originRegistry : 'this registry')">
            <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
              <rect x="2" y="2.5" width="10" height="9" rx="1.6" stroke="currentColor" stroke-width="1.3" fill="none"/>
              <circle cx="5" cy="5.3" r="1.3" stroke="currentColor" stroke-width="1.1" fill="none"/>
              <path d="M8 4.6 L11 4.6 M8 6.2 L11 6.2 M3 9 L11 9" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/>
            </svg>
            Source Registry
          </button>
          <button v-if="agent && agent.pricing && fxUnsure" class="adm-btn adm-btn--primary adm-btn--fx-locked" type="button" disabled data-testid="adm-hire-fx-unsure">
            {{ hostFx === 'reading' ? 'Cross-currency · checking FX…' : 'Cross-currency · FX could not be checked' }}
          </button>
          <button v-else-if="agent && agent.pricing && !fxLocked" @click="hireAgent" class="adm-btn adm-btn--primary" type="button">
            <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
              <circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.4" fill="none"/>
              <path d="M5 7 L7 9 L9.5 5.5" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            {{ agentIsForeign ? 'Hire · pay via FX (' + agentCcy + ')' : 'Hire this agent' }}
          </button>
          <!-- B8: cross-currency agent, host FX off → not payable from here -->
          <button v-else-if="agent && agent.pricing && fxLocked" class="adm-btn adm-btn--primary adm-btn--fx-locked" type="button" disabled :title="fxHireHint">
            <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
              <rect x="3" y="6.5" width="8" height="5.5" rx="1" stroke="currentColor" stroke-width="1.3" fill="none"/>
              <path d="M4.6 6.5 V4.8 a2.4 2.4 0 0 1 4.8 0 V6.5" stroke="currentColor" stroke-width="1.3" fill="none"/>
            </svg>
            Cross-currency · enable FX
          </button>
          <button v-else-if="agent" @click="callFree" class="adm-btn adm-btn--primary" type="button">
            <svg viewBox="0 0 14 14" width="12" height="12" aria-hidden="true">
              <path d="M2 7 L12 7 M8 3 L12 7 L8 11" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            Call this agent
          </button>
          <button @click="show = false" class="adm-btn adm-btn--close" type="button">Close</button>
        </div>
      </div>
    </template>
  </BaseModal>

  <!-- B10: source-registry card viewer (federated → peer card; local → self) -->
  <SovereignRegistryCard
    v-model:show="showRegistryCard"
    :peer-name="agent && agent.isFederated ? agent.originRegistry : null"
    :fallback-name="agent && agent.isFederated ? agent.originRegistry : 'this registry'"
  />
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { describeCurrency } from '@/config/currencies'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useEngageDoors } from '@/composables/useEngageDoors'
import { contractsV2Api } from '@/services/api/contractsV2'
import { discoveryService, type EnrichedAgent } from '@/services/api/discovery'
import { effectiveEndpoints, type CardEndpoint } from '@/services/cardEndpoints'
import { apiClient } from '@/services/api/client'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { agentAvatarUser, agentAvatarUrl } from '@/services/agentAvatar'
import BaseModal from '@/components/BaseModal.vue'
import SovereignRegistryCard from '@/components/SovereignRegistryCard.vue'
import { useLogger } from '@/composables/useLogger'
import { useCurrency } from '@/composables/useCurrency'
import { useFrames } from '@/composables/useFrames'
import { useI18n } from '@/composables/useI18n'
import { needsOwnCredential, type CardAuthScheme } from '@/services/cardAuth'
import { useAuthStore } from '@/stores/auth'
import TrackRecordPanel from '@/components/common/TrackRecordPanel.vue'
import BuyServicePanel from '@/components/BuyServicePanel.vue'
import EarnedMarkRing from '@/components/common/EarnedMarkRing.vue'
import type { TrackRecordCompact } from '@/services/api/trackRecord'
import { fxService } from '@/services/api/fx'

const log = useLogger('AgentDetailModal')

interface Props {
  show: boolean
  agentDid?: string
  /** Embedded/anonymous host (landing globe): render a login prompt, never fetch. §pass78c ① */
  /** Rendered inside another surface (the landing globe). §EMBEDGATE: this no longer gates the
   *  CONTENT — the card is public — and is kept declared because `AgentWorldCesium` binds it and
   *  an UNDECLARED prop becomes a silent fallthrough ATTRIBUTE on the root element. */
  embedded?: boolean
  /** Agent display name from the globe marker — shown in the embedded login prompt. */
  agentName?: string
  /**
   * §DISCREFINE — the caller opened this modal BECAUSE the human asked for the
   * track record (Pocket's "Track record & receipts" door). The panel normally
   * auto-hides for an agent with no history, which is right when it is one
   * section among many and wrong here: it turns a promise into a blank space.
   * Measured 2026-08-23: only 24 of 14,260 agents have any settled guild work,
   * so that door led nowhere 99.8% of the time. With this set, the panel renders
   * its own honest "no verified guild work on this registry yet" line instead.
   */
  focusRecord?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  'filter-by-tag': [tag: string]
}>()

const uiStore = useUIStore()
// FX multi-currency: a viewed agent's price/balance is in ITS home-frame
// currency (may be foreign; falls back to local when item lacks trust_domain). §17.5 [ITEM]
const { currencyForItem, isForeignItem } = useCurrency()
const { localFx } = useFrames()
// ⚠ `tp`, not `t`, for anything parameterised: legacy `t(key, text, params)` returns the fallback
// VERBATIM with a literal {n} in it (§POCKETI18N).
const { t, tp } = useI18n()
// §DISCPUBLIC — is there a session at all? The modal reads only public rails, so it renders identically for a
// visitor; this decides the ACTIONS, not the content.
const hasSession = computed(() => !!useAuthStore().isAuthenticated)
// §AGENTDISC #188 — hides the Proven-work section chrome for zero-history agents
const admTrackRecordHas = ref(false)
// §AGENTDISC #190 — compact record for the hero avatar's earned ring
const admTrCompact = ref<TrackRecordCompact | null>(null)

// ── B8 (2026-06-03) — FX-aware hire gating ─────────────────────────────────
// A paid agent on a foreign-currency frame is only hireable if THIS registry
// has FX enabled. Mirrors Discovery.vue: env-authoritative /teg/fx/rate, with
// the well-known card's fees.fx.enabled fallback.
// §FESUITE V0578: publicRate answers null for a FAILED read ({ available: false } on a frame without FX), and with no
// card read either the gate said "enable FX on your registry to pay" and disabled Hire: an "FX off" nobody read (it also
// flashed while the read was out). 'on' / 'off' come from an answer (the rate, or the card's fees.fx); 'reading' and
// 'unread' disable Hire with what is true, and 'unread' offers Try again.
const fxRate = ref<Awaited<ReturnType<typeof fxService.publicRate>> | undefined>(undefined)   // undefined: in flight
async function loadHostFx() {
  fxRate.value = undefined
  try { fxRate.value = await fxService.publicRate() } catch { fxRate.value = null }
}
void loadHostFx()
const hostFx = computed<'on' | 'off' | 'reading' | 'unread'>(() => {
  const r = fxRate.value
  const fx: any = localFx.value
  if ((r && r.available === true) || (fx && fx.enabled === true)) return 'on'
  if (r || (fx && fx.enabled === false)) return 'off'
  return r === undefined ? 'reading' : 'unread'
})
const agentIsForeign = computed(() => (agent.value ? isForeignItem(agent.value) : false))
const fxLocked = computed(() => agentIsForeign.value && hostFx.value === 'off')
const fxUnsure = computed(() => agentIsForeign.value && (hostFx.value === 'reading' || hostFx.value === 'unread'))
const agentCcy = computed(() => (agent.value ? currencyForItem(agent.value) : ''))
const fxHireHint = computed(() =>
  `Cross-currency (${agentCcy.value}) — enable FX on your registry to pay this agent.`)

// B10 — source-registry card viewer
const showRegistryCard = ref(false)

// State
const loadingDetails = ref(false)
const loadError = ref<string | null>(null)
const agent = ref<EnrichedAgent | null>(null)
const tegBalance = ref<{ liquid: number; staked: number } | null>(null)
const showRawData = ref(false)
// §pass18 (2026-05-16) — polished UX state
const showCurl = ref(false)
// §BUYSERVICE — the purchase panel is opened by the engage CTA, never by default.
const showBuy = ref(false)
const copyToast = ref<string | null>(null) // 'hri' | 'url' | 'curl' — last-copied field
const router = useRouter()

// Computed
const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value)
})

// Embedded login-prompt CTA → close + route to the auth page. §pass78c ①

/** Emoji from card_data or fallback */
const cardEmoji = computed(() => {
  if (agent.value?.rawCardData?.emoji) return agent.value.rawCardData.emoji
  return '🤖'
})

/** §pass8 (2026-05-15): UserAvatar-friendly projection of the enriched agent.
 * Reads card_data.flare (set by §28 federation export) and maps to the same
 * top-level field names UserAvatar consumes — works for both local and
 * federated agents uniformly. */
// the avatar's input, by the one rule every view that shows an agent's face uses (services/agentAvatar.ts)
const agentUserShape = computed(() => agentAvatarUser(agent.value))

/** Parse capabilities object into display list */
const capabilityList = computed(() => {
  if (!agent.value?.capabilities) return []
  const caps = agent.value.capabilities
  const labels: Record<string, string> = {
    streaming: 'Streaming',
    pushNotifications: 'Push Notifications',
    stateTransitionHistory: 'State Transition History',
    multiLanguage: 'Multi-Language',
    a2aProtocol: 'A2A Protocol',
    teeAttestation: 'TEE Attestation',
    federatedDiscovery: 'Federated Discovery'
  }
  return Object.entries(caps).map(([key, value]) => ({
    key,
    label: labels[key] || formatCamelCase(key),
    enabled: Boolean(value)
  }))
})

// §pass18 — Only show ENABLED capabilities (cleaner; disabled ones are
// noise). Each gets a unique SVG icon. Unknown keys fall back to a generic
// "feature" pip.
const CAP_ICONS: Record<string, string> = {
  streaming: '<svg viewBox="0 0 14 14" width="14" height="14"><path d="M2 4 L2 10 M5 2 L5 12 M8 5 L8 9 M11 3 L11 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
  pushNotifications: '<svg viewBox="0 0 14 14" width="14" height="14"><path d="M3 6 Q3 3 7 3 Q11 3 11 6 L11 8 L12 10 L2 10 L3 8 Z M5.5 11 Q5.5 12.5 7 12.5 Q8.5 12.5 8.5 11" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round"/></svg>',
  stateTransitionHistory: '<svg viewBox="0 0 14 14" width="14" height="14"><circle cx="3" cy="7" r="1.5" stroke="currentColor" stroke-width="1.3" fill="none"/><circle cx="11" cy="7" r="1.5" stroke="currentColor" stroke-width="1.3" fill="none"/><path d="M4.5 7 L9.5 7" stroke="currentColor" stroke-width="1.3"/><path d="M7.5 5 L9.5 7 L7.5 9" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linejoin="round"/></svg>',
  multiLanguage: '<svg viewBox="0 0 14 14" width="14" height="14"><path d="M2 3 L7 3 M4.5 3 L4.5 7 M2 5.5 Q4.5 8 7 5.5 M8 11 L10 6 L12 11 M8.8 9.5 L11.2 9.5" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  a2aProtocol: '<svg viewBox="0 0 14 14" width="14" height="14"><circle cx="3.5" cy="7" r="1.6" stroke="currentColor" stroke-width="1.3" fill="none"/><circle cx="10.5" cy="7" r="1.6" stroke="currentColor" stroke-width="1.3" fill="none"/><path d="M5.1 7 L8.9 7" stroke="currentColor" stroke-width="1.3" stroke-dasharray="1.4,1.2"/></svg>',
  teeAttestation: '<svg viewBox="0 0 14 14" width="14" height="14"><path d="M7 2 L11 4 L11 8 Q11 11 7 12 Q3 11 3 8 L3 4 Z" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linejoin="round"/><path d="M5.5 7 L7 8.5 L9.5 6" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  federatedDiscovery: '<svg viewBox="0 0 14 14" width="14" height="14"><polygon points="7,2 11,4.5 11,9.5 7,12 3,9.5 3,4.5" stroke="currentColor" stroke-width="1.3" fill="none" stroke-linejoin="round"/><circle cx="7" cy="7" r="1.4" fill="currentColor"/></svg>',
  extendedAgentCard: '<svg viewBox="0 0 14 14" width="14" height="14"><rect x="2.5" y="3" width="9" height="8" rx="1.2" stroke="currentColor" stroke-width="1.3" fill="none"/><path d="M4.5 5.5 L9.5 5.5 M4.5 7.5 L9.5 7.5 M4.5 9.5 L7.5 9.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
}
const FALLBACK_CAP_ICON = '<svg viewBox="0 0 14 14" width="14" height="14"><circle cx="7" cy="7" r="2.5" fill="currentColor" opacity="0.85"/></svg>'

const enabledCapabilities = computed(() => {
  return capabilityList.value
    .filter(c => c.enabled)
    .map(c => ({ ...c, icon: CAP_ICONS[c.key] || FALLBACK_CAP_ICON }))
})

// §CARDAUTH: does a call need a credential of the agent's own (read in either of the card's two dialects)?
const ownCredential = computed(() => needsOwnCredential(agent.value?.authSchemes as CardAuthScheme[] | undefined))

// §pass18 — A curl example users can copy-paste to test the agent endpoint.
// Adapts to the auth scheme (oauth2 → bearer placeholder, apikey → header
// placeholder, none → naked GET). Read-only; safe to display.
const curlExample = computed<string>(() => {
  const a = agent.value
  // §CARDLINK — ask the ONE resolver, not the legacy field. `a.url` is empty on every canonical
  // A2A v1.0 card, which would have left the curl example blank for exactly the agents whose
  // address this batch repaired.
  const primary = cardEndpoints.value[0]?.url
  if (!a || !primary) return ''
  const first = (a.authSchemes && a.authSchemes[0]) as CardAuthScheme | undefined
  const scheme = first?.scheme || 'none'
  // the A2A v1.0 message/send envelope the registry's own buy rail sends (services/service_purchase.py): an agent that
  // parses A2A refuses a bare string where the message belongs
  const body = `  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"hello"}]}}}'`
  const lines: string[] = []
  lines.push(`# Probe agent endpoint`)
  if (first?.declared && first.query) {
    // §CARDAUTH: the agent's own key, in the query parameter its card names
    lines.push(`curl -X POST "${primary}${primary.includes('?') ? '&' : '?'}${first.query}=$YOUR_API_KEY" \\`)
    lines.push(`  -H "Content-Type: application/json" \\`)
    lines.push(body)
  } else if (scheme === 'apiKey' || scheme === 'apikey') {
    // §CARDAUTH: the header the card names (X-Api-Key only when it names none)
    lines.push(`curl -X POST "${primary}" \\`)
    lines.push(`  -H "${first?.header || 'X-Api-Key'}: $YOUR_API_KEY" \\`)
    lines.push(`  -H "Content-Type: application/json" \\`)
    lines.push(body)
  } else if (first?.declared && (scheme === 'bearer' || scheme === 'oauth2' || scheme === 'openIdConnect')) {
    lines.push(`# 1) Sign in where the agent's card says${first.tokenUrl ? ` (${first.tokenUrl})` : ''}, then call:`)
    lines.push(`curl -X POST "${primary}" \\`)
    lines.push(`  -H "Authorization: Bearer $YOUR_CREDENTIAL" \\`)
    lines.push(`  -H "Content-Type: application/json" \\`)
    lines.push(body)
  } else if (scheme === 'oauth2') {
    lines.push(`# 1) Get token from your registry first, then call:`)
    lines.push(`curl -X POST "${primary}" \\`)
    lines.push(`  -H "Authorization: Bearer $YOUR_AGENT_JWT" \\`)
    lines.push(`  -H "Content-Type: application/json" \\`)
    lines.push(body)
  } else {
    lines.push(`curl -X POST "${primary}" \\`)
    lines.push(`  -H "Content-Type: application/json" \\`)
    lines.push(body)
  }
  if (a.pricing) {
    lines.push(``)
    lines.push(`# This is a paid agent (${a.pricing.base_rate} ${currencyForItem(a)}/req).`)
    lines.push(`# Get an A2A payment authorization via /api/v1/a2a-payment/authorize first.`)
  }
  return lines.join('\n')
})

// §pass18 — Footer CTA handlers
function openProtocolTheater() {
  if (!agent.value) return
  // Theater showcases the gossip / call flow. Route exists at /showcase.
  router.push({ path: '/showcase', query: { agent: agent.value.did || agent.value.id } })
  show.value = false
}
/**
 * §BUYSERVICE (2026-08-24) — the primary CTA on a paid agent used to do this:
 *     router.push({ path: '/my-agents', query: { hire: did } })
 * under a comment promising a future flow. NOTHING consumed `?hire=` (grep: zero
 * hits across the tree), so the money button on every paid agent led to the
 * viewer's own fleet list — and on Pocket it threw a phone into a desktop view.
 * It now opens the door it always described: quote → confirm → call → answer.
 * Free agents open the SAME panel (no payment step), so one door covers both and
 * calling a free agent stops being a curl panel.
 */
function openBuy() {
  if (!agent.value) return
  showBuy.value = true
  setTimeout(() => {
    document.querySelector('[data-testid="bsp"]')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, 60)
}
const hireAgent = openBuy
const callFree = openBuy

/**
 * §FLARESHOP (2026-08-16) — presentation helpers for the card's machine fields.
 * The card is written by an SDK for machines; this modal is read by a human
 * deciding whether to hire. Where those two disagree, the human wins.
 */
function humanizeKey(k: string): string {
  return k
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, c => c.toUpperCase())
}

/**
 * Pull the scheme token out of whatever shape the card carries. The live cards
 * on this fleet write `{scheme: "none", scopes: null, tokenUrl: null, ...}` —
 * the key is `scheme`, not `type`. Missing that meant the humanised labels
 * silently fell through to the raw dump and the modal still said "none";
 * caught by reading the actual card_data rather than the type definition.
 */
function schemeToken(scheme: any): string {
  if (typeof scheme === 'string') return scheme.toLowerCase()
  return String(scheme?.scheme || scheme?.type || scheme?.name || '').toLowerCase()
}

/** What a caller must bring, per declared scheme. */
function authSchemeLabel(scheme: any): string {
  const raw = schemeToken(scheme)
  if (!raw || raw === 'none' || raw === 'null') return t('agentModal.auth.open', 'Open endpoint')
  if (raw.includes('bearer') || raw.includes('jwt')) return t('agentModal.auth.bearer', 'Bearer token')
  if (raw.includes('apikey') || raw.includes('api_key')) return t('agentModal.auth.apiKey', 'API key')
  if (raw.includes('oauth')) return t('agentModal.auth.oauth', 'OAuth 2.0')
  if (raw.includes('openid')) return t('agentModal.auth.oidc', 'OpenID Connect')
  if (raw === 'basic') return t('agentModal.auth.basic', 'HTTP basic')
  if (raw.includes('mtls') || raw.includes('x509')) return t('agentModal.auth.mtls', 'Mutual TLS')
  return formatAuthScheme(scheme)
}

function authSchemeNote(scheme: any): string {
  const raw = schemeToken(scheme)
  if (!raw || raw === 'none' || raw === 'null') {
    return t('agentModal.auth.openNote', 'no credential required to call it')
  }
  // §CARDAUTH: a scheme read from the card's securitySchemes is the agent's own credential, not one this network issues
  if ((scheme as CardAuthScheme)?.declared) {
    const s = scheme as CardAuthScheme
    if (s.header) return tp('agentModal.auth.ownHeaderNote', 'the agent\'s own key, sent in the {header} header', { header: s.header })
    if (s.query) return tp('agentModal.auth.ownQueryNote', 'the agent\'s own key, sent as the {name} parameter', { name: s.query })
    if (raw === 'bearer' || raw === 'oauth2' || raw === 'openidconnect') return t('agentModal.auth.ownSignInNote', 'a credential from the agent\'s own sign-in, sent in the Authorization header')
    if (raw === 'mtls') return t('agentModal.auth.ownMtlsNote', 'a client certificate the agent trusts')
    if (raw === 'basic') return t('agentModal.auth.ownBasicNote', 'a user name and password the agent issues')
  }
  if (raw.includes('bearer') || raw.includes('jwt')) return t('agentModal.auth.bearerNote', 'send an agent JWT')
  if (raw.includes('apikey') || raw.includes('api_key')) return t('agentModal.auth.apiKeyNote', 'send a key header')
  if (raw.includes('oauth')) return t('agentModal.auth.oauthNote', 'client-credentials exchange')
  if (raw.includes('mtls') || raw.includes('x509')) return t('agentModal.auth.mtlsNote', 'SPIFFE certificate, IRONHAND')
  return ''
}

/** Parse skills from raw card_data */
const skills = computed(() => {
  if (!agent.value?.rawCardData?.skills) return []
  const raw = agent.value.rawCardData.skills
  return Array.isArray(raw) ? raw : []
})

/** §FLARESHOP — an "Updated" cell that repeats "Created" is noise. */
const showUpdatedCell = computed(() => {
  const a = agent.value
  if (!a?.updatedAt) return false
  if (!a.createdAt) return true
  return String(a.updatedAt).slice(0, 16) !== String(a.createdAt).slice(0, 16)
})

/**
 * §FLARESHOP (2026-08-16) — skills worth a section of their own.
 *
 * SDK-generated cards routinely declare a single skill carrying the agent's own
 * name and description (that is what the generator writes when the developer
 * does not enumerate skills). Rendering it produced a "Skills" box that was a
 * verbatim second copy of the hero, three lines below the hero. A skill earns
 * its place if it adds ANYTHING: a different name, a different description, a
 * uri, or declared input/output modes.
 */
const informativeSkills = computed(() => {
  const norm = (v: unknown) => String(v ?? '').trim().toLowerCase()
  const agentName = norm(agent.value?.name)
  const agentDesc = norm(agent.value?.description)
  return skills.value.filter((sk: any) => {
    if (sk?.uri || sk?.inputModes?.length || sk?.outputModes?.length) return true
    const n = norm(sk?.name || sk?.id)
    const d = norm(sk?.description)
    const echoesName = !n || n === agentName
    const echoesDesc = !d || d === agentDesc
    return !(echoesName && echoesDesc)
  })
})

/** §pass34 — DID with card_data fallback (top-level agent.did may be empty
 *  when metadata enrichment didn't match — card_data.did is the on-card value). */
const resolvedDid = computed(() => {
  // §FLARESHOP: `props.agentDid` is the LAST fallback but the strongest source —
  // it is the DID the caller opened this modal with. The two payload-derived
  // fields depend on which path filled `agent` (the discovery enrichment cache
  // sets `did`; a cold `/agent-cards/{id}` fetch returns `agent_did` and may
  // carry no `did` at all), so on a cold open the proven-work panel and the
  // signed-card link silently vanished for exactly the users who had not
  // browsed to the agent first. Asking the caller settles it.
  // STRICT: only a DID-shaped value counts. The modal is often opened with the
  // card UUID (`viewAgentByDID(agent.id || agent.did)` passes `id` first), and
  // accepting that produced a signed-card link to /agents/<uuid>/card-export,
  // which 404s, and would have handed a UUID to the track-record panel as if it
  // were a DID. If nothing DID-shaped is available the sections hide, which is
  // the honest outcome and matches the behaviour before this fallback existed.
  const a: any = agent.value
  const candidates = [a?.did, a?.rawCardData?.did, a?.agent_did, props.agentDid]
  return candidates.find(v => typeof v === 'string' && v.startsWith('did:')) || ''
})

// §HIRECOHERE — these MUST sit below `resolvedDid`: useEngageDoors watches it with
// `immediate: true`, so declaring them above the computed read it inside its temporal
// dead zone. Vue caught the ReferenceError in the error boundary and BLANKED the whole
// Discovery view — with the API battery still fully green, because it never loads a page.

/** §HIRECOHERE — the same preview TrackRecordPanel reads, so the two surfaces cannot
 *  disagree about which doors are open for an agent.
 *  §DISCPUBLIC — gated on there being a session: engage-preview is an owner-tier read and a
 *  visitor has no doors to open (the template offers them a sign-in instead), so asking would
 *  only spend a request to be told 401. `hasSession` is declared above; the composable watches
 *  it with `immediate: true`, which is why the order matters (the TDZ note above). */
const { doors: engDoors, draft: engDraft } = useEngageDoors(resolvedDid, hasSession)

/**
 * §COCKPITUP U4 (2026-09-01) — a door from the card to the full agent view.
 *
 * 🔴 `agent-details` is `agent/:agentId` and its param is the CARD UUID, not the DID —
 * this file already documents that trap at `resolvedDid` ("the modal is often opened with
 * the card UUID … accepting that produced a signed-card link that 404s"). So this door
 * deliberately reads `agent.id`, NOT `resolvedDid`, and renders nothing without one.
 *
 * ⚠ Not offered WITHOUT A SESSION: `agent-details` is `requiresAuth`, so the door would open
 * onto the login redirect — a blank promise with extra steps. This used to ask `props.embedded`,
 * which is the surface rather than the viewer: it hid the door from a SIGNED-IN person on the
 * landing globe and would have shown it to an anonymous one anywhere else. §DISCPUBLIC's rule,
 * one door further on — gate on the state, never by naming the surface.
 */
const fullAgentHref = computed(() => {
  if (!hasSession.value) return ''
  const id = (agent.value as any)?.id
  if (!id) return ''
  try {
    const r = router.resolve({ name: 'agent-details', params: { agentId: String(id) } })
    return r.name ? r.href : ''
  } catch { return '' }
})

/** Post a job: a bounty needs no support from the card, so this door is always open. */
function hireViaGuild() {
  router.push({ path: '/guild', query: {
    post: '1',
    title: `Hire: ${agent.value?.name || resolvedDid.value || ''}`.slice(0, 180),
    spec: `Scope of work for ${agent.value?.name || 'this agent'} (${resolvedDid.value || ''}). Acceptance criteria: `,
  } })
}

/** Offer a contract: mints from the card's OWN engagement terms through the rail built for
 *  it. Only rendered when the preview says the door is open, so it cannot 404 on the way. */
const offerBusy = ref(false)
const offerOpen = ref(false)
const offerOpenThread = ref(false)   // §DEALTHREADS — unticked by default (his call)
async function offerContract() {
  if (offerBusy.value || !resolvedDid.value) return
  offerBusy.value = true
  try {
    await contractsV2Api.engage(resolvedDid.value, offerOpenThread.value ? { open_thread: true } : {})
    uiStore?.showSuccess?.(t('agentModal.doors.offerSentTitle', 'Offer sent'),
      t('agentModal.doors.offerSent', 'It is theirs to accept; nothing is escrowed until they do.'))
  } catch (e: any) {
    uiStore?.showError?.(t('agentModal.doors.offerFailedTitle', 'Offer not sent'),
      e?.response?.data?.error?.detail || e?.response?.data?.detail
      || t('agentModal.doors.offerFailed', 'The offer could not be sent.'))
  } finally { offerBusy.value = false; offerOpen.value = false }
}

// ─── §pass34 (2026-05-17) — structured card_data field views ──────────────

/** Shorten a SPIFFE-ID to its registry name component for inline display. */
function shortSpiffe(s?: string | null): string | null {
  if (!s || typeof s !== 'string') return null
  // Match common patterns and extract the friendly tail.
  const patterns = [
    /\/operator\/([^/]+)\/registry/,                  // op-tokyo
    /\/service\/registry-([^/]+)/,                    // mainframe a / frame-b
    /\/ns\/agentvault\/sa\/registry-([^/]+)/,         // legacy ns
    /\/registry-([^/]+)$/,                            // last-segment
  ]
  for (const re of patterns) {
    const m = s.match(re)
    if (m) return m[1]
  }
  // Fallback: trust-domain + tail
  const slash = s.lastIndexOf('/')
  if (slash > 0 && slash < s.length - 1) return s.slice(slash + 1)
  return s
}

/** Structured federation info for the modal block. Returns null when there's
 *  nothing to show (truly local + no metadata). */
const federationInfo = computed(() => {
  const cd = agent.value?.rawCardData
  if (!cd) return null
  const fm = (cd.federation_metadata as Record<string, any>) || {}
  const originName = (fm.origin_registry_name as string) || (agent.value?.isFederated ? agent.value?.originRegistry || null : null)
  const lastHop = (fm.last_synced_from as string) || null
  const firstHop = (fm.first_synced_from as string) || null
  const source = (fm.source_registry as string) || null
  const lastTs = (fm.last_sync_timestamp as string) || null
  const protoVer = (fm.protocol_version as string) || (cd.protocolVersion as string) || null
  const mtlsEnabled = fm.mtls_enabled !== undefined ? !!fm.mtls_enabled : undefined
  const spiffeId = (fm.spiffe_id as string) || null

  // Origin location (origin_registry_location: {label, latitude, longitude})
  let originLocation: string | null = null
  const loc = fm.origin_registry_location
  if (loc && typeof loc === 'object') {
    const lbl = (loc.label as string) || ''
    const lat = loc.latitude
    const lng = loc.longitude
    if (lbl) originLocation = lbl
    else if (lat !== undefined && lng !== undefined) originLocation = `${lat}, ${lng}`
  }

  // Bail if literally nothing federation-related is present
  if (!originName && !lastHop && !firstHop && !source && !originLocation && !spiffeId) return null

  return {
    isLocal: !lastHop && !firstHop && !source,  // truly native, never relayed
    originRegistryName: originName,
    lastSyncedFrom: lastHop,
    lastSyncedFromShort: shortSpiffe(lastHop),
    firstSyncedFrom: firstHop,
    firstSyncedFromShort: shortSpiffe(firstHop),
    sourceRegistry: source,
    lastSyncTimestamp: lastTs,
    protocolVersion: protoVer,
    mtlsEnabled,
    spiffeId,
    originLocation,
  }
})

/** §CARDLINK — a card's ADDRESSES, whichever of the two legal dialects it uses.
 *
 * This gated on `agent.url` — the LEGACY v0.3 field — so the eleven sovereign agents, whose
 * cards are canonical A2A v1.0 (real `supportedInterfaces[]`, and no top-level `url`, which the
 * vendored v1.0.1 schema does not even define), rendered NO endpoint section at all. His report:
 * *"the subdomains of the sovereign agents … are not displayed on the modal … where are the
 * links for the reachable ones then?"* One resolver, the way pricing already has one.
 */
const cardEndpoints = computed<CardEndpoint[]>(() =>
  effectiveEndpoints(agent.value?.rawCardData || (agent.value?.url ? { url: agent.value.url } : null)))

/** §CARDLINK — the registry's last word on the published address, in three states.
 *
 * 'reachable'  the registry dialled it and something is there
 * 'dead'       it dialled it and nothing is  (unhealthy / unreachable)
 * 'unknown'    it has never dialled it here — a federated mirror is legitimately never
 *              probed locally, and saying "dead" about it would be inventing the reason
 *              (§RAT: never-observed and failing must not look the same).
 * ⚠ `is_live` is NOT this fact and must never be substituted for it: it is last_active_at
 * within 24h, and it read true for every agent whose address answered 404.
 */
const endpointState = computed<'reachable' | 'dead' | 'unknown'>(() => {
  const h = String(agent.value?.endpointHealth ?? '').toLowerCase()
  if (h === 'healthy') return 'reachable'
  if (h === 'unhealthy' || h === 'unreachable') return 'dead'
  return 'unknown'
})

const endpointCheckedLabel = computed(() => {
  const ts = agent.value?.endpointCheckedAt
  if (!ts) return ''
  try { return `checked ${formatDate(ts)}` } catch { return '' }
})

/** Parse supportedInterfaces (protocol bindings) from card_data. */
const supportedInterfaces = computed(() => {
  const raw = agent.value?.rawCardData?.supportedInterfaces
  return Array.isArray(raw) ? raw : []
})

/** Parse securitySchemes dict from card_data into list rows. */
const securitySchemesList = computed(() => {
  const raw = agent.value?.rawCardData?.securitySchemes
  if (!raw || typeof raw !== 'object') return []
  return Object.entries(raw).map(([name, spec]: [string, any]) => {
    const type = (spec && spec.type) || '?'
    const flows = spec?.flows || {}
    const cc = flows.clientCredentials || flows.client_credentials || {}
    return {
      name,
      type,
      tokenUrl: cc.tokenUrl || (spec && spec.tokenUrl) || null,
    }
  })
})

/** Misc card_data fields not surfaced in other sections. */
const miscFields = computed(() => {
  const cd = agent.value?.rawCardData
  if (!cd) return []
  const out: Array<{ key: string; label: string; value: string }> = []
  const seenInOtherSections = new Set([
    'url', 'name', 'description', 'iconUrl', 'humanReadableId', 'tags', 'skills',
    'capabilities', 'authSchemes', 'security', 'securitySchemes',
    'provider', 'pricing', 'agentVersion', 'schemaVersion', 'protocolVersion',
    'termsOfServiceUrl', 'privacyPolicyUrl', 'supportedInterfaces',
    'federation_metadata', 'location', 'did', 'flare',
    'extensions',  // shown below specifically
  ])
  if (cd.lastUpdated) out.push({ key: 'lastUpdated', label: 'Last Updated (card)', value: String(cd.lastUpdated) })
  if (cd.preferredTransport) out.push({ key: 'preferredTransport', label: 'Preferred Transport', value: String(cd.preferredTransport) })
  if (cd.metadata && typeof cd.metadata === 'object') {
    try { out.push({ key: 'metadata', label: 'Metadata', value: JSON.stringify(cd.metadata) }) } catch {}
  }
  if (cd.extensions && (Array.isArray(cd.extensions) ? cd.extensions.length : Object.keys(cd.extensions).length)) {
    try { out.push({ key: 'extensions', label: 'Extensions', value: JSON.stringify(cd.extensions) }) } catch {}
  }
  // Top-level location coords (separate from federation_metadata.origin_registry_location)
  // §LOCTRUTH — `card_data.location` is the DEVELOPER's registered location, stamped at federation
  // export for globe positioning; it is not a claim about where the agent runs. Label it as registered,
  // and never render bare coordinates: a lat/lng pair with no place name is not information a reader can
  // use, and printing it as "Location" dresses a globe coordinate up as an address.
  const tl = cd.location
  if (tl && typeof tl === 'object') {
    const lbl = (tl.label as string) || ''
    if (lbl) out.push({ key: 'location', label: 'Registered location', value: lbl })
  }
  // Any unexpected top-level keys we don't render anywhere else
  Object.keys(cd).forEach(k => {
    if (seenInOtherSections.has(k)) return
    if (out.find(x => x.key === k)) return
    const v = cd[k]
    if (v === null || v === undefined || v === '') return
    let val = ''
    try {
      // §FLARESHOP: a bare JSON.stringify put `["text/plain"]` on screen under a
      // CSS-uppercased raw key (DEFAULTINPUTMODES). Arrays of scalars are the
      // common case here (input/output modes, transports) and read fine as a
      // comma list; anything genuinely structured still falls back to JSON.
      if (Array.isArray(v) && v.every(x => typeof x !== 'object')) val = v.join(', ')
      else val = typeof v === 'object' ? JSON.stringify(v) : String(v)
    } catch { val = String(v) }
    if (val.length > 120) val = val.slice(0, 117) + '…'
    out.push({ key: k, label: humanizeKey(k), value: val })
  })
  return out
})

// Watch for DID changes → load agent
watch(() => props.agentDid, async (newDid) => {
  // §AGENTDISC #190 — reset the previous agent's attested state so a stale earned
  // ring or section never lingers while the new panel loads
  admTrackRecordHas.value = false
  admTrCompact.value = null
  // §EMBEDGATE — the embedded host FETCHES now, like every other host. It used to skip the load
  // because the teaser above rendered instead; with the teaser gone, not fetching would leave the
  // landing page's modal permanently empty. `lookupByDID` is a public rail (measured: 200 with no
  // Authorization header), so an anonymous viewer gets the same card a member does.
  if (newDid) {
    await loadAgent(newDid)
  }
}, { immediate: true })

// Reset when modal closes
watch(() => props.show, (isOpen) => {
  if (!isOpen) {
    showRawData.value = false
    loadError.value = null
  }
})

// Methods
async function loadAgent(did: string) {
  if (!did) return

  loadingDetails.value = true
  loadError.value = null
  agent.value = null
  tegBalance.value = null

  try {
    const result = await discoveryService.lookupByDID(did)
    agent.value = result
    log.info('Loaded agent:', result.name, result.id)

    // Try to fetch TEG balance in background (non-blocking)
    fetchTegBalance(result)
  } catch (error: any) {
    console.error('[AgentDetailModal] Failed to load agent:', error)
    loadError.value = `Could not load agent details. ${error?.message || ''}`
  } finally {
    loadingDetails.value = false
  }
}

async function fetchTegBalance(agentData: EnrichedAgent) {
  // §pass12 (2026-05-15) — Removed dead balance fetch. Both endpoints
  // (`/teg/transactions/balance/{did}` and `/projections/balance/{did}`) do
  // not exist on the public registry API for arbitrary DIDs — they always
  // 404, regardless of HRI vs DID identifier shape. Two 404s per agent-
  // detail open contributed to CrowdSec http-crawl-non_statics false-
  // positives for legitimate users.
  //
  // For YOUR own agents, balance is already present on EnrichedAgent
  // (populated via /developers/me/agents metadata merge in parseFullCard:
  // `liquid_balance` / `staked_balance`). No separate fetch needed.
  // For arbitrary (peer / federated / not-yours) agents, balance is not
  // publicly readable and the modal should not advertise it. Skip.
  if (agentData.liquid_balance || agentData.staked_balance) {
    tegBalance.value = {
      liquid: Number(agentData.liquid_balance || 0),
      staked: Number(agentData.staked_balance || 0),
    }
  }
}

async function copyToClipboard(text: string, fieldKey?: string) {
  try {
    await navigator.clipboard.writeText(text)
    // §pass18 — inline toast tag instead of global notification for less
    // noise. fieldKey signals which value was copied so the button can swap
    // its label briefly.
    if (fieldKey) {
      copyToast.value = fieldKey
      setTimeout(() => { if (copyToast.value === fieldKey) copyToast.value = null }, 1500)
    } else {
      uiStore.showSuccess?.('Copied', 'Copied to clipboard') ??
        log.info('Copied:', text)
    }
  } catch {
    log.warn('Clipboard not available')
  }
}

// Helper functions
function formatDate(dateStr?: string): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString(appLocale(), {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    })
  } catch {
    return dateStr
  }
}

function formatCamelCase(str: string): string {
  return str.replace(/([A-Z])/g, ' $1').replace(/^./, s => s.toUpperCase()).trim()
}

function capitalize(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1)
}

function formatAuthScheme(scheme: any): string {
  if (typeof scheme === 'string') return scheme
  if (scheme?.type) return `${scheme.type}${scheme.description ? ` — ${scheme.description}` : ''}`
  if (scheme?.scheme) return scheme.scheme
  return JSON.stringify(scheme)
}
</script>

<style scoped>
/* §pass18 (2026-05-16) — Polished AgentDetailModal styles.
   The modal is wrapped by BaseModal which provides the dialog chrome; these
   styles target only the inner body content + footer that we render. */

.adm-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ─── Embedded / anonymous sign-in gate (landing globe agent click) ─────────
   Beautiful, on-theme replacement for the old plain log-in block. */
.adm-empty { padding: 40px 28px; text-align: center; }
.adm-empty-h { font-size: 15px; font-weight: 700; color: var(--nc-text-primary, #e7eef7); margin-bottom: 8px; }
.adm-empty-sub { font-size: 12px; line-height: 1.55; opacity: .6; max-width: 42ch; margin: 0 auto; }

/* §EMBEDGATE — the sign-in teaser's styles are gone with the teaser. Excised by SYMBOL
   (every `.adm-gate*` rule), never by line range: this file's own history has a case where a
   region that looked like one feature held 26 symbols the rest of the view read. */
.adm-hero {
  position: relative;
  overflow: hidden;
  padding: 18px 20px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb), 0.10) 0%, rgba(var(--nc-primary-rgb), 0.03) 70%);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.30);
  border-radius: 12px;
}
.adm-hero-decor {
  position: absolute;
  top: -40px; right: -40px;
  width: 200px; height: 200px;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.18) 0%, transparent 70%);
  pointer-events: none;
}
.adm-hero-content {
  position: relative;
  display: flex;
  gap: 18px;
  align-items: flex-start;
}
.adm-hero-avatar { flex-shrink: 0; }
.adm-hero-info { flex: 1; min-width: 0; }

.adm-hero-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.adm-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-radius: 99px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: rgba(220, 215, 235, 0.85);
}
.adm-pill--verified {
  background: rgba(34, 197, 94, 0.10);
  border-color: rgba(34, 197, 94, 0.45);
  color: rgba(74, 222, 128, 0.95);
}
.adm-pill--active {
  background: rgba(34, 197, 94, 0.10);
  border-color: rgba(34, 197, 94, 0.45);
  color: rgba(74, 222, 128, 0.95);
}
.adm-pill--idle {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(180, 180, 200, 0.20);
  color: rgba(180, 180, 200, 0.70);
}
.adm-pill--federated {
  background: rgba(167, 139, 250, 0.12);
  border-color: rgba(167, 139, 250, 0.45);
  color: rgba(196, 181, 253, 0.95);
}
.adm-pill--local {
  background: rgba(var(--nc-primary-rgb), 0.10);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.adm-pill-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.adm-pill-dot--pulse {
  animation: adm-pulse 1.8s ease-in-out infinite;
  box-shadow: 0 0 8px currentColor;
}
@keyframes adm-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.55; transform: scale(1.2); }
}
.adm-pill-glyph { font-family: 'IBM Plex Mono', monospace; }

.adm-hero-name {
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 1.45rem;
  font-weight: 700;
  color: rgba(245, 240, 255, 1);
  margin: 0 0 6px;
  letter-spacing: -0.005em;
  line-height: 1.2;
}

.adm-hero-hri {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  padding: 3px 8px;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  color: rgba(var(--nc-primary-rgb), 0.85);
  max-width: 100%;
}
.adm-hero-hri code {
  font-family: inherit;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.adm-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  color: rgba(180, 180, 200, 0.60);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  transition: color 0.16s ease, background 0.16s ease;
}
.adm-icon-btn:hover {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.12);
}
.adm-copy-toast {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: rgba(34, 197, 94, 0.95);
}

.adm-hero-desc {
  font-size: 0.92rem;
  color: rgba(225, 220, 240, 0.85);
  line-height: 1.55;
  margin: 6px 0 10px;
}

.adm-hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 0.74rem;
  color: rgba(180, 180, 200, 0.75);
}
.adm-meta-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.adm-meta-item--mono { font-family: 'IBM Plex Mono', monospace; }
.adm-meta-key {
  font-family: 'IBM Plex Mono', monospace;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin-right: 2px;
}

/* ─── Pricing band ──────────────────────────────────────────────────────── */
/* ─── §FLARESHOP (2026-08-16): direct-engagement band + humanised auth rows ─── */
.adm-engage {
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  background: rgba(var(--nc-primary-rgb), 0.05);
  border-radius: 0.55rem;
  padding: 0.75rem 0.9rem;
  margin: 0.85rem 0;
}
.adm-engage-head { display: flex; align-items: baseline; gap: 0.6rem; }
.adm-engage-price {
  font-family: var(--nc-font-mono, monospace); font-size: 0.85rem; font-weight: 600;
  color: rgba(var(--nc-primary-rgb), 0.95); margin-left: auto;
}
.adm-engage-price--free { color: #34d399; }
.adm-engage-per { opacity: 0.6; font-size: 0.7rem; }
.adm-engage-sub { font-size: 0.76rem; line-height: 1.5; color: var(--nc-text-muted, #94a3b8); margin: 0.4rem 0 0.65rem; }
.adm-engage-actions { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; }
.adm-engage-btn {
  padding: 0.4rem 0.85rem; border-radius: 0.35rem; font-size: 0.8rem; font-weight: 600;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.5); background: rgba(var(--nc-primary-rgb), 0.14);
  color: rgba(var(--nc-primary-rgb), 0.98); transition: background 0.15s;
}
.adm-engage-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.24); }
.adm-engage-btn--locked { opacity: 0.5; cursor: not-allowed; }
.adm-engage-card { font-size: 0.72rem; color: var(--nc-text-muted, #94a3b8); text-decoration: none; }
.adm-engage-card:hover { color: rgba(var(--nc-primary-rgb), 0.9); text-decoration: underline; }
.adm-auth-note { font-size: 0.7rem; color: var(--nc-text-muted, #94a3b8); margin-left: 0.45rem; }
.adm-auth-row { flex-wrap: wrap; }
.adm-auth-desc { flex-basis: 100%; font-size: 0.72rem; color: var(--nc-text-muted, #94a3b8); margin: 0.2rem 0 0 1.4rem; overflow-wrap: anywhere; }

.adm-pricing {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border-radius: 10px;
  border: 1px solid;
}
.adm-pricing--paid {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.10), rgba(245, 158, 11, 0.03));
  border-color: rgba(245, 158, 11, 0.42);
}
.adm-pricing--free {
  background: rgba(34, 197, 94, 0.06);
  border-color: rgba(34, 197, 94, 0.30);
  gap: 10px;
}
.adm-pricing-left { flex-shrink: 0; }
.adm-pricing-label {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(245, 158, 11, 0.75);
  margin-bottom: 4px;
}
.adm-pricing-amount {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.adm-pricing-num {
  font-size: 1.85rem;
  font-weight: 800;
  color: rgba(252, 211, 77, 1);
  line-height: 1;
}
.adm-pricing-unit {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.82rem;
  font-weight: 700;
  color: rgba(252, 211, 77, 0.85);
}
.adm-pricing-per {
  font-size: 0.72rem;
  color: rgba(180, 180, 200, 0.75);
  margin-left: 6px;
}

.adm-pricing-flow {
  flex: 1;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  justify-content: center;
  flex-wrap: wrap;
  color: rgba(220, 215, 235, 0.65);
}
.adm-flow-step {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: rgba(225, 220, 240, 0.78);
}
.adm-flow-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px; height: 18px;
  background: rgba(var(--nc-primary-rgb), 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.50);
  border-radius: 50%;
  font-size: 0.66rem;
  font-weight: 800;
  color: rgba(var(--nc-primary-rgb), 1);
}
.adm-pricing-flow svg { color: rgba(var(--nc-primary-rgb), 0.55); flex-shrink: 0; }

.adm-pricing-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  background: rgba(245, 158, 11, 0.20);
  border: 1px solid rgba(245, 158, 11, 0.55);
  border-radius: 99px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(252, 211, 77, 1);
}

/* B8 — cross-currency settlement note in the pricing band */
.adm-pricing-fx-note {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 99px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.64rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: rgba(252, 211, 77, 0.95);
}
.adm-pricing-fx-note--locked {
  background: rgba(148, 163, 184, 0.12);
  border-color: rgba(148, 163, 184, 0.4);
  color: rgba(203, 213, 225, 0.9);
}
.adm-fx-retry { margin-left: 6px; background: none; border: 1px solid currentColor; border-radius: 6px; color: inherit; font: inherit; font-size: .9em; padding: 0 6px; cursor: pointer; }

.adm-pricing-free-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.55);
  border-radius: 99px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(74, 222, 128, 0.95);
  flex-shrink: 0;
}
.adm-pricing-free-note {
  font-size: 0.82rem;
  color: rgba(200, 200, 220, 0.75);
}

/* ─── Section blocks ─────────────────────────────────────────────────────── */
.adm-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.adm-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
/* §FESUITE (49-discovery, 2026-10-02): the grey labels (this one, the meta cells', the hero's meta line and the
   price's "per request") drew rgba(180, 180, 200, 0.50-0.65): 2.9-4.4:1 on the panels they sit on, under WCAG AA's
   4.5:1 for their small size. At 0.75 they read 4.7-5.4:1 on every one of them (the surface, the meta cells, the
   engage band, the hero's tint at its brightest, the price band's amber), in both themes, and stay quieter than the
   values. The endpoint state badge lost its 0.85 opacity: dimmed, the dead state's --nc-danger read 3.6-3.9:1 and
   the unknown state's --nc-text-dim 4.0-4.3:1; at full colour 4.6-5.0:1 and 5.0-5.5:1. */
.adm-section-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.64rem;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: rgba(180, 180, 200, 0.75);
}
.adm-section-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: color 0.16s ease, background 0.16s ease;
}
.adm-section-toggle:hover {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.08);
}

/* ─── §CARDLINK: the endpoint's own verdict ─────────────────────────────── */
.adm-ep-state {
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 3px;
  border: 1px solid currentColor;
}
.adm-ep-state--reachable { color: var(--nc-success, #3fa66a); }
.adm-ep-state--dead { color: var(--nc-danger, #d9534f); }
.adm-ep-state--unknown { color: var(--nc-text-dim, #8a8f98); }
/* His call: a dot, no timestamp. The dot carries the state at a glance; the words carry it for
   anyone who cannot use colour, which is why both are present and neither is decorative. */
.adm-ep-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  margin-right: 5px;
  vertical-align: 1px;
}
.adm-ep-binding {
  font-size: 10px;
  letter-spacing: 0.04em;
  color: var(--nc-text-dim, #8a8f98);
  border: 1px solid var(--nc-border, #2a2f3a);
  border-radius: 3px;
  padding: 1px 5px;
  flex: 0 0 auto;
}
.adm-ep-more { margin-top: 6px; }
.adm-ep-more-summary {
  cursor: pointer;
  font-size: 11.5px;
  color: var(--nc-text-dim, #8a8f98);
  padding: 2px 0;
}
.adm-ep-more-summary:hover { color: var(--nc-text, #d7dae0); }
.adm-ep-more .adm-endpoint { margin-top: 5px; }
.adm-ep-note {
  margin: 6px 0 0;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--nc-text-dim, #8a8f98);
}
/* §FESUITE (2026-10-04): a dead endpoint's URL faded to opacity 0.55 read #057477 on #0a0d14 = 3.48:1 (lifecycle 49 on
   V0572, fes-20261004T171222Z-9caf: it failed whenever the health checker had already probed the fresh agent, and passed
   on a retry that had not). The line-through says "dead"; the text stays readable in the dim text colour (5.98:1). */
.adm-endpoint--dead .adm-endpoint-url {
  color: var(--nc-text-dim, #8a8f98);
  text-decoration: line-through;
  text-decoration-thickness: 1px;
}

/* ─── Endpoint + curl ───────────────────────────────────────────────────── */
.adm-endpoint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 7px;
}
.adm-endpoint-url {
  flex: 1;
  min-width: 0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.80rem;
  color: rgba(var(--nc-primary-rgb), 0.95);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.adm-endpoint-copy {
  flex-shrink: 0;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(220, 215, 235, 0.85);
  cursor: pointer;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}
.adm-endpoint-copy:hover {
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  color: rgba(var(--nc-primary-rgb), 1);
}

.adm-curl {
  position: relative;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.30);
  border-radius: 8px;
  padding: 14px 16px;
  padding-right: 88px;
  margin: 8px 0 0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(180, 220, 200, 0.95);
  line-height: 1.55;
  overflow-x: auto;
  white-space: pre;
}
.adm-curl-copy {
  position: absolute;
  top: 10px; right: 10px;
  padding: 4px 10px;
  background: rgba(var(--nc-primary-rgb), 0.16);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.55);
  border-radius: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.64rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 1);
  cursor: pointer;
}

/* ─── Metadata grid ─────────────────────────────────────────────────────── */
.adm-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
}
.adm-meta-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 7px;
}
.adm-meta-cell-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.60rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(180, 180, 200, 0.75);
}
.adm-meta-cell-value {
  font-size: 0.84rem;
  color: rgba(225, 220, 240, 0.92);
}

/* ─── Tags ──────────────────────────────────────────────────────────────── */
.adm-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.adm-tag {
  display: inline-block;
  padding: 3px 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 99px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: rgba(220, 215, 235, 0.85);
  cursor: pointer;
  transition: all 0.14s ease;
}
.adm-tag:hover {
  background: rgba(var(--nc-primary-rgb), 0.10);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  color: rgba(var(--nc-primary-rgb), 1);
}

/* ─── Capabilities (icon grid) ─────────────────────────────────────────── */
.adm-cap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
}
.adm-cap-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(var(--nc-primary-rgb), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.30);
  border-radius: 8px;
  transition: background 0.16s ease, border-color 0.16s ease;
}
.adm-cap-chip:hover {
  background: rgba(var(--nc-primary-rgb), 0.10);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
}
.adm-cap-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px; height: 26px;
  flex-shrink: 0;
  color: rgba(var(--nc-primary-rgb), 0.95);
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 6px;
}
.adm-cap-icon :deep(svg) { width: 14px; height: 14px; }
.adm-cap-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(225, 220, 240, 0.92);
}

/* ─── Footer ────────────────────────────────────────────────────────────── */
.adm-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  width: 100%;
}
.adm-footer-meta {
  display: inline-flex;
  align-items: center;
  gap: 12px;
}
.adm-footer-rep {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  font-weight: 600;
  color: rgba(245, 158, 11, 0.90);
}
.adm-footer-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.adm-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  /* §COCKPITUP U4 — this class was only ever on a <button>; one action is now an <a>
     (so middle-click and open-in-new-tab work), which arrives with a UA underline. */
  text-decoration: none;
  padding: 8px 14px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.16s ease;
}
.adm-btn--primary {
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb), 1), rgba(var(--nc-primary-rgb), 0.75));
  color: rgba(8, 6, 18, 0.98);
  border: 1px solid rgba(var(--nc-primary-rgb), 1);
  box-shadow: 0 0 16px -4px rgba(var(--nc-primary-rgb), 0.55);
}
.adm-btn--primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 0 24px -2px rgba(var(--nc-primary-rgb), 0.75);
}
/* B8 — cross-currency hire blocked (host FX off): inert, muted, lock cursor. */
.adm-btn--fx-locked,
.adm-btn--fx-locked:hover {
  background: rgba(148, 163, 184, 0.14);
  color: rgba(203, 213, 225, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.4);
  box-shadow: none;
  transform: none;
  cursor: not-allowed;
  opacity: 0.85;
}
.adm-btn--ghost {
  background: transparent;
  color: rgba(var(--nc-primary-rgb), 0.95);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
}
.adm-btn--ghost:hover {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.85);
}
.adm-btn--close {
  background: rgba(255, 255, 255, 0.04);
  color: rgba(220, 215, 235, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.adm-btn--close:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.20);
  color: rgba(245, 240, 255, 1);
}

/* ─── Reveal transition ────────────────────────────────────────────────── */
.adm-reveal-enter-active,
.adm-reveal-leave-active {
  transition: opacity 0.22s ease, max-height 0.30s ease;
  max-height: 400px;
  overflow: hidden;
}
.adm-reveal-enter-from,
.adm-reveal-leave-to {
  opacity: 0;
  max-height: 0;
}

@media (prefers-reduced-motion: reduce) {
  .adm-pill-dot--pulse { animation: none !important; }
  .adm-reveal-enter-active,
  .adm-reveal-leave-active { transition: none !important; }
  .adm-btn:hover { transform: none !important; }
}

/* ─── Mobile tightening ────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .adm-hero-content { flex-direction: column; align-items: center; text-align: center; }
  .adm-hero-pills { justify-content: center; }
  .adm-hero-meta { justify-content: center; }
  .adm-pricing { flex-direction: column; align-items: stretch; }
  .adm-pricing-flow { justify-content: flex-start; }
  .adm-footer { flex-direction: column; gap: 10px; }
  .adm-footer-actions { width: 100%; justify-content: stretch; }
  .adm-footer-actions .adm-btn { flex: 1; justify-content: center; }
}

/* §pass34 (2026-05-17) — Federation block + structured field rows */
.adm-fed-section {
  border-left: 2px solid rgba(var(--nc-primary-rgb), 0.32);
  padding-left: 12px;
}
.adm-fed-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid;
}
.adm-fed-badge--local {
  color: rgba(var(--nc-primary-rgb), 1);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(var(--nc-primary-rgb), 0.08);
}
.adm-fed-badge--relayed {
  color: rgba(240, 195, 110, 1);
  border-color: rgba(240, 195, 110, 0.55);
  background: rgba(240, 195, 110, 0.06);
}
.adm-fed-location-label { opacity: .55; margin-right: .35rem; }
.adm-tech { margin-top: .25rem; border-top: 1px solid rgba(var(--nc-primary-rgb), .12); padding-top: .35rem; }
.adm-tech-summary {
  cursor: pointer; list-style: none; font-size: .68rem; letter-spacing: .14em; text-transform: uppercase;
  opacity: .55; padding: .5rem 0; user-select: none;
}
.adm-tech-summary::-webkit-details-marker { display: none; }
.adm-tech-summary::before { content: '▸ '; display: inline-block; transition: transform .16s ease; }
.adm-tech[open] > .adm-tech-summary::before { content: '▾ '; }
.adm-tech-summary:hover { opacity: .85; }
.adm-fed-location {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(200, 192, 220, 0.78);
}
.adm-fed-spiffe {
  margin-top: 6px;
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.adm-mono-small {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: rgba(220, 215, 235, 0.82);
  background: rgba(255, 255, 255, 0.03);
  padding: 2px 6px;
  border-radius: 4px;
  word-break: break-all;
}
.adm-iface-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.adm-iface-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  background: rgba(15, 12, 28, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
}
.adm-iface-proto {
  color: rgba(var(--nc-primary-rgb), 1);
  font-weight: 700;
  letter-spacing: 0.04em;
  min-width: 80px;
}
.adm-iface-url {
  flex: 1;
  color: rgba(200, 195, 218, 0.82);
  word-break: break-all;
  overflow: hidden;
  text-overflow: ellipsis;
}
.adm-iface-ver {
  color: rgba(200, 195, 218, 0.55);
  font-size: 0.66rem;
}

/* ─── §pass18-refine (2026-06-06) — currency chip + unify Balance/Skills/Auth/
       Legal/Raw-data into the adm- design language (5 refinement passes) ─── */

/* Pass 1 — hero settlement-currency chip (FX-context glanceability) */
.adm-pill--ccy-local {
  background: rgba(var(--nc-primary-rgb), 0.10);
  border-color: rgba(var(--nc-primary-rgb), 0.42);
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.adm-pill--ccy-foreign {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.50);
  color: rgba(252, 211, 77, 0.98);
}

/* Pass 2 — balance band */
.adm-balance { display: flex; flex-wrap: wrap; gap: 10px; }
.adm-balance-cell {
  flex: 1; min-width: 150px;
  display: flex; flex-direction: column; gap: 3px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb), 0.08), rgba(var(--nc-primary-rgb), 0.02));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.30);
  border-radius: 10px;
}
.adm-balance-cell--staked {
  background: linear-gradient(135deg, rgba(167, 139, 250, 0.10), rgba(167, 139, 250, 0.02));
  border-color: rgba(167, 139, 250, 0.34);
}
.adm-balance-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.60rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: rgba(180, 180, 200, 0.55);
}
.adm-balance-amount { font-size: 1.35rem; font-weight: 800; color: rgba(var(--nc-primary-rgb), 1); line-height: 1.1; }
.adm-balance-amount--staked { color: rgba(196, 181, 253, 1); }
.adm-balance-ccy { font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; font-weight: 700; opacity: 0.8; }

/* Pass 3 — skills */
.adm-skill-list { display: flex; flex-direction: column; gap: 7px; }
.adm-skill {
  padding: 10px 13px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 8px;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.adm-skill:hover { border-color: rgba(var(--nc-primary-rgb), 0.30); background: rgba(var(--nc-primary-rgb), 0.03); }
.adm-skill-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.adm-skill-name { font-size: 0.86rem; font-weight: 600; color: rgba(232, 228, 245, 0.95); }
.adm-skill-uri {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem; color: rgba(180, 180, 200, 0.55);
  max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0;
}
.adm-skill-desc { margin: 5px 0 0; font-size: 0.78rem; color: rgba(200, 196, 218, 0.78); line-height: 1.5; }
.adm-skill-modes {
  display: flex; flex-wrap: wrap; gap: 14px; margin-top: 7px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: rgba(180, 180, 200, 0.62);
}
.adm-skill-mode-key { color: rgba(var(--nc-primary-rgb), 0.85); font-weight: 700; margin-right: 4px; }

/* Pass 4 — auth rows (in .adm-iface-list) */
.adm-auth-row {
  display: flex; align-items: center; gap: 9px; padding: 8px 12px;
  background: rgba(15, 12, 28, 0.6); border: 1px solid rgba(255, 255, 255, 0.07); border-radius: 7px;
}
.adm-auth-icon { flex-shrink: 0; color: rgba(252, 211, 77, 0.9); }
.adm-auth-label { font-size: 0.82rem; color: rgba(225, 220, 240, 0.9); }

/* Pass 5 — legal links + raw card data */
.adm-legal { display: flex; flex-wrap: wrap; gap: 16px; }
.adm-legal-link {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 600;
  color: rgba(var(--nc-primary-rgb), 0.9); text-decoration: none; transition: color 0.14s ease;
}
.adm-legal-link:hover { color: rgba(var(--nc-primary-rgb), 1); text-decoration: underline; }
.adm-rawdata-toggle { color: rgba(180, 180, 200, 0.55); }
.adm-rawdata-toggle:hover { color: rgba(var(--nc-primary-rgb), 0.95); background: rgba(var(--nc-primary-rgb), 0.06); }
.adm-rawdata {
  margin: 8px 0 0; max-height: 320px; overflow: auto; padding: 14px 16px;
  background: rgba(0, 0, 0, 0.55); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.70rem; line-height: 1.5;
  color: rgba(180, 200, 210, 0.85); white-space: pre;
}
/* §HIRECOHERE — the two doors that are not the per-request call, and the sentence that
   replaces a shut one. They sit under the engage actions, quieter than the primary CTA. */
.adm-doors { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }
.adm-door {
  font-family: inherit; font-size: 10px; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 5px 10px; border-radius: 4px; cursor: pointer;
  background: transparent; color: rgba(var(--nc-primary-rgb), 0.72);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  transition: border-color 0.15s, color 0.15s;
}
.adm-door:hover { border-color: rgba(var(--nc-primary-rgb), 0.6); color: var(--nc-primary); }
.adm-door--contract { border-color: rgba(var(--nc-primary-rgb), 0.45); }
.adm-door-shut {
  margin: 0; font-size: 9px; line-height: 1.45; max-width: 62ch;
  color: rgba(var(--nc-primary-rgb), 0.45);
}
.adm-offer {
  margin-top: 8px; padding: 10px; border-radius: 6px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  background: rgba(var(--nc-primary-rgb), 0.04);
}
.adm-offer-title { margin: 0 0 3px; font-size: 11px; font-weight: 600; color: var(--nc-primary); }
.adm-offer-line { margin: 0; font-size: 10px; color: rgba(var(--nc-primary-rgb), 0.7); }
.adm-offer-actions { display: flex; gap: 6px; margin-top: 8px; }
/* §DEALTHREADS — the discuss-in-OurChat choice */
.adm-offer-thread { display: flex; align-items: center; gap: 7px; margin-top: 7px; font-size: 0.74rem; color: rgba(148,163,184,0.65); cursor: pointer; }
.adm-offer-thread input { width: 15px; height: 15px; accent-color: var(--nc-primary, #4fd8c4); cursor: pointer; }
</style>
